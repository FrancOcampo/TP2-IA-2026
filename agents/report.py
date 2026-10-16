# agents/report.py
#
# Reporte clínico estructurado (F3-04, ADR-0019). Generación *anclada* (grounded):
#   - El LLM NO escribe citas, metas ni umbrales. Recibe los fragmentos del RAG numerados (F1, F2…) y
#     las alertas agrupadas con id (A1, A2…), y devuelve un `ClinicalReport` con la interpretación de
#     cada alerta y los IDs de fragmentos que la respaldan.
#   - El CÓDIGO arma el Markdown: valores, umbrales y comparación salen de los datos determinísticos, las
#     citas salen del banco de fragmentos (id → fuente + texto recuperado) y el disclaimer lo agrega
#     siempre (D8). Un id inexistente o una cifra sin respaldo queda marcada, nunca silenciada.
# Todo lo de este módulo es determinístico y testeable sin LLM.

from __future__ import annotations

import re
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Optional

from pydantic import BaseModel, Field

from agents.context import AlertGroup, alert_groups
from orchestrator.state import MonitorAnalysis

DISCLAIMER = (
    "⚠️ Este reporte es un insumo de soporte a la decisión clínica. "
    "No reemplaza el criterio del médico tratante ni constituye un diagnóstico médico."
)
_DISCLAIMER_MARK = "no reemplaza el criterio del médico tratante"

# Máximo de caracteres de un fragmento que se muestra como cita en el reporte
_QUOTE_CHARS = 280


# -------------------------------------------------------------------
# Modelos de salida del LLM
# -------------------------------------------------------------------

class AlertInterpretation(BaseModel):
    """Interpretación de UN grupo de alertas (id A1, A2… que entrega el sistema)."""
    alert_id: str = Field(description="Id del grupo de alertas, tal como figura en el análisis (ej. A1).")
    interpretation: str = Field(
        description="1–2 oraciones que interpretan el hallazgo. Sin números de metas: el sistema los agrega.")
    fragment_ids: list[int] = Field(
        default_factory=list,
        description="Números (sin la F) de los fragmentos de guía que respaldan la interpretación. Vacío si ninguno aplica.")


class ClinicalReport(BaseModel):
    summary: str = Field(description="Estado metabólico general en 2–3 oraciones.")
    longitudinal: Optional[str] = Field(
        default=None, description="Evolución respecto de la sesión anterior; null si no hay sesiones previas.")
    alerts: list[AlertInterpretation] = Field(default_factory=list)
    trends: list[str] = Field(default_factory=list, description="Tendencias relevantes, una oración cada una.")
    suggested_questions: list[str] = Field(
        default_factory=list, description="Hasta 3 preguntas de seguimiento para el médico.")
    limitations: list[str] = Field(default_factory=list, description="Limitaciones de los datos, si las hay.")


# -------------------------------------------------------------------
# Banco de fragmentos (id → fuente + texto)
# -------------------------------------------------------------------

@dataclass
class FragmentBank:
    """Fragmentos recuperados en una corrida del Clínico, con id estable (1, 2, 3…)."""
    items: list[tuple[str, str]] = field(default_factory=list)  # (fuente, texto)

    def add(self, formatted: str) -> int:
        """Agrega un fragmento con el formato del retriever ("[fuente] texto") y devuelve su id (sin duplicar)."""
        source, text = _split_source(formatted)
        for i, item in enumerate(self.items, start=1):
            if item == (source, text):
                return i
        self.items.append((source, text))
        return len(self.items)

    def get(self, fragment_id: int) -> Optional[tuple[str, str]]:
        return self.items[fragment_id - 1] if 1 <= fragment_id <= len(self.items) else None

    def as_prompt(self) -> str:
        return "\n".join(f"[F{i}] ({src}) {text}" for i, (src, text) in enumerate(self.items, start=1)) or "(sin fragmentos)"

    def texts(self) -> list[str]:
        return [text for _, text in self.items]


def _split_source(formatted: str) -> tuple[str, str]:
    m = re.match(r"^\[([^\]]+)\]\s*(.*)$", formatted, re.S)
    return (m.group(1), m.group(2).strip()) if m else ("guía", formatted.strip())


# Banco de la corrida actual: lo llenan la búsqueda por código (modo lean) y la tool del LLM (modo react).
_BANK: ContextVar[Optional[FragmentBank]] = ContextVar("fragment_bank", default=None)


def new_bank() -> FragmentBank:
    bank = FragmentBank()
    _BANK.set(bank)
    return bank


def current_bank() -> Optional[FragmentBank]:
    return _BANK.get()


# -------------------------------------------------------------------
# Búsqueda de guías por código (modo lean) y tool numerada (modo react)
# -------------------------------------------------------------------

_SIDE_QUERY = {
    "hipoglucemia": "hipoglucemia niveles definición tratamiento diabetes tipo 2",
    "alta": "meta de control glucémico objetivo diabetes tipo 2",
}


def guideline_queries(analysis: Optional[MonitorAnalysis], doctor_context: str = "", max_queries: int = 3) -> list[str]:
    """Consultas al RAG derivadas de los grupos de alertas (más severas primero); una general si no hay alertas."""
    groups = alert_groups(analysis.alerts) if analysis else []
    queries: list[str] = []
    for g in sorted(groups, key=lambda g: (g.severity_rank, -g.count)):
        side = "hipoglucemia" if g.is_hypo else "alta"
        queries.append(f"{g.label} {_SIDE_QUERY[side]}")
    if not queries:
        queries.append("metas de control glucémico y seguimiento en diabetes tipo 2")
    queries = queries[:max_queries]
    if doctor_context.strip():
        queries[0] = f"{queries[0]} {doctor_context.strip()[:120]}"
    return queries


# Señales de que un fragmento es un tramo de bibliografía (autores, revista, año;volumen) y no contenido
# clínico: en la evaluación con el LLM real citaba listas de referencias como si fueran respaldo.
_REFERENCE_HINTS = re.compile(
    r"(\bet al\b|\b(?:19|20)\d{2}\s*;\s*\d+|\bdoi\b|N Engl J Med|Diabetes Care|Lancet|JAMA|\bBMJ\b"
    r"|\b\d{1,3}\.?\s+[A-ZÁÉÍÓÚ][\wáéíóúñ]+\s+[A-Z]{1,3}[,.]"
    r"|Sociedad Argentina de Diabetes\.\s+Gu[ií]a|Ministerio de Salud de la Naci[oó]n\.)", re.I)


_STRONG_REFERENCE = re.compile(
    r"^\s*\d{1,3}\.?\s+(?:Sociedad|Ministerio|Federaci[oó]n|Asociaci[oó]n|American|World|International)\b"
    r"|\b(?:Sociedad Argentina de Diabetes|Ministerio de Salud de la Naci[oó]n)\.\s+(?:Gu[ií]a|Recomendaciones)")


def looks_like_references(text: str) -> bool:
    """True si el fragmento parece bibliografía (2 señales, o 1 señal fuerte), para no ofrecerlo como respaldo."""
    return len(_REFERENCE_HINTS.findall(text)) >= 2 or bool(_STRONG_REFERENCE.search(text))


def prefetch_guidelines(bank: FragmentBank, queries: list[str], search, k: int = 3, max_fragments: int = 6) -> None:
    """Llena el banco con los mejores fragmentos de cada consulta (`search` = search_clinical_guidelines)."""
    for query in queries:
        for formatted in search(query, k=k):
            if len(bank.items) >= max_fragments:
                return
            if not looks_like_references(formatted):
                bank.add(formatted)


def numbered_search_result(bank: FragmentBank, fragments: list[str]) -> str:
    """Resultado de la tool `search_clinical_guidelines` con ids [F#] para que el LLM cite por número."""
    fragments = [f for f in fragments if not looks_like_references(f)]
    if not fragments:
        return "No se encontraron fragmentos relevantes."
    return "\n\n".join(f"[F{bank.add(f)}] {f}" for f in fragments)


# -------------------------------------------------------------------
# Validación de cifras (metas inventadas)
# -------------------------------------------------------------------

_VALUE_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(mg/dl|mg/dL|%)", re.I)


def _norm_number(raw: str) -> str:
    return raw.replace(",", ".").rstrip("0").rstrip(".") if "." in raw.replace(",", ".") else raw


def unsupported_values(text: str, context: str) -> list[str]:
    """
    Cifras con unidad (mg/dL, %) que aparecen en `text` pero no en el contexto que recibió el LLM
    (análisis, comparación, historial y fragmentos). Es lo que delata una meta inventada, p. ej.
    "objetivo < 110 mg/dL" cuando ningún dato ni fragmento menciona 110.
    """
    known = {_norm_number(m.group(1)) for m in _VALUE_RE.finditer(context)}
    known |= {_norm_number(n) for n in re.findall(r"\d+(?:[.,]\d+)?", context)}
    bad = []
    for m in _VALUE_RE.finditer(text):
        if _norm_number(m.group(1)) not in known:
            bad.append(f"{m.group(1)} {m.group(2)}")
    return sorted(set(bad))


# -------------------------------------------------------------------
# Render (Markdown armado por código)
# -------------------------------------------------------------------

def ensure_disclaimer(text: str) -> str:
    """Agrega el disclaimer si el texto no lo trae (D8: lo garantiza el código, no el prompt)."""
    if _DISCLAIMER_MARK in text.lower():
        return text
    return f"{text.rstrip()}\n\n---\n{DISCLAIMER}"


def _flag(text: str, context: str) -> str:
    bad = unsupported_values(text, context)
    return f"{text} ⚠️ (cifra sin respaldo en los datos: {', '.join(bad)})" if bad else text


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÑ¿¡0-9])")
_NOISE = re.compile(r"(?:->\s*\w\s*)+|\bR\d{1,3}\b|\bComentario\b(?=\s+R?\d)|[\u2022\u25aa\u25cf|#*_`>]+")


def _words(text: str) -> set[str]:
    import unicodedata

    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return {w for w in re.findall(r"[a-z0-9]{4,}", plain)}


def best_excerpt(text: str, hint: str = "", max_chars: int = _QUOTE_CHARS) -> str:
    """
    Extracto citable de un fragmento: oraciones COMPLETAS (el fragmento empieza y termina en cortes
    arbitrarios del texto), sin marcas de la extracción del PDF, y la más pertinente a `hint` (la
    interpretación que respalda). Devuelve "" si no queda ninguna oración utilizable.
    """
    clean = re.sub(r"\s+", " ", _NOISE.sub(" ", text)).strip()
    parts = _SENTENCE_SPLIT.split(clean)
    # Si el fragmento arranca a mitad de oración (minúscula), esa primera parte está cortada.
    if len(parts) > 1 and parts[0][:1].islower():
        parts = parts[1:]
    parts = [p.strip() for p in parts if len(p.strip()) >= 40 and len(p.split()) >= 6 and not looks_like_references(p)]
    # La última oración puede estar cortada por el límite del fragmento.
    if parts and not parts[-1].endswith((".", "!", "?", ")")) and len(parts) > 1:
        parts = parts[:-1]
    if not parts:
        return ""
    target = _words(hint)
    scored = sorted(range(len(parts)), key=lambda i: (-len(_words(parts[i]) & target), i))
    chosen = [scored[0]]
    # Suma la oración siguiente si entra, para que la cita tenga contexto.
    if scored[0] + 1 < len(parts) and len(parts[scored[0]]) + len(parts[scored[0] + 1]) + 1 <= max_chars:
        chosen.append(scored[0] + 1)
    excerpt = " ".join(parts[i] for i in sorted(chosen))
    return excerpt if len(excerpt) <= max_chars else excerpt[:max_chars].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def _cite(fragment_ids: list[int], bank: FragmentBank, hint: str = "") -> list[str]:
    lines = []
    for fid in dict.fromkeys(fragment_ids):
        item = bank.get(fid)
        if item is None:
            lines.append(f"  - ⚠️ cita no verificada: el fragmento F{fid} no existe")
            continue
        source, text = item
        quote = best_excerpt(text, hint)
        lines.append(f"  - «{quote}» — [{source}]" if quote else f"  - (fragmento F{fid} sin texto citable) — [{source}]")
    return lines


def render_report(
    report: ClinicalReport,
    analysis: Optional[MonitorAnalysis],
    bank: FragmentBank,
    comparison: Optional[dict],
    context: str,
    patient_id: str = "",
) -> str:
    """Markdown final. `context` es el texto que vio el LLM (para detectar cifras sin respaldo)."""
    groups = alert_groups(analysis.alerts) if analysis else []
    n_sec = [0]

    def sec(title: str) -> str:
        n_sec[0] += 1
        return f"### {n_sec[0]}. {title}"

    by_id = {a.alert_id.strip().upper(): a for a in report.alerts}
    out = [f"## Reporte clínico — paciente {patient_id}".rstrip(" —"), "", sec("Estado metabólico general"),
           _flag(report.summary, context)]

    out += ["", sec("Evaluación longitudinal")]
    deltas = (comparison or {}).get("deltas") or {}
    prev = (comparison or {}).get("previous_session") or {}
    if prev:
        if report.longitudinal:
            out.append(_flag(report.longitudinal, context))
        if deltas:
            out += ["", f"Cambios respecto de la sesión anterior ({prev.get('date', 's/f')}):", "",
                    "| Métrica | Δ (actual − anterior) |", "|---|---|"]
            out += [f"| {m} | {d:+g} |" for m, d in deltas.items()]
    else:
        # Sin sesión previa real no se muestra ninguna "evolución" que el LLM pudiera haber escrito igual.
        out.append("No hay sesiones previas guardadas para comparar.")

    out += ["", sec("Alertas y respaldo en las guías")]
    if not groups:
        out.append("Sin alertas: los valores están dentro de las metas de control del sistema.")
    for g in groups:
        out += ["", f"**{g.id} · {g.title}**", f"- Hallazgo: {g.finding}"]
        item = by_id.get(g.id)
        if item is None:
            out.append("- Interpretación: (el modelo no interpretó este grupo)")
            continue
        out.append(f"- Interpretación: {_flag(item.interpretation, context)}")
        out += _cite(item.fragment_ids, bank, item.interpretation) or ["  - (sin cita de guía para este hallazgo)"]

    if report.trends:
        out += ["", sec("Tendencias relevantes")] + [f"- {_flag(t, context)}" for t in report.trends]

    limits = list(report.limitations)
    if analysis and analysis.insufficient_data:
        limits += [f"Datos insuficientes para {m}: {why}" for m, why in sorted(analysis.insufficient_data.items())]
    if limits:
        out += ["", sec("Limitaciones")] + [f"- {x}" for x in limits]

    if report.suggested_questions:
        out += ["", sec("Preguntas de seguimiento sugeridas")] + [
            f"{i}. {q}" for i, q in enumerate(report.suggested_questions[:3], start=1)]

    return ensure_disclaimer("\n".join(out))
