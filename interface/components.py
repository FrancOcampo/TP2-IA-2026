# interface/components.py
#
# Componentes de presentación reutilizables de la UI (tarea del Integrante D).
#
# Son funciones PURAS: reciben los modelos Pydantic de orchestrator/state.py (o datos del log)
# y devuelven Markdown/HTML como string. No dependen de Gradio → se pueden testear sin levantar
# la interfaz y se reusan tanto en interface/app.py como en los tests del Fragmento 3.
#
# Toleran datos faltantes (analysis=None, métricas sin CSV, log vacío): la UI no debe romperse
# si un paciente no tiene datos de EHR todavía (p. ej. mientras B no entrega el dataset real).

from __future__ import annotations

import html
import json
from collections import deque
from pathlib import Path
from typing import Optional

from orchestrator.state import (
    Alert,
    Medication,
    MetricStats,
    MonitorAnalysis,
    PatientMetrics,
)
from tools.patient_tools import SAMPLE_DATA_DIR
from interface.logging_config import LOG_DIR, LOG_FILE

# Artefacto que produce tests/eval_runner.py y consume la pestaña "Evaluación".
EVAL_REPORT_FILE = LOG_DIR / "eval_report.json"

# -------------------------------------------------------------------
# Etiquetas legibles y formato
# -------------------------------------------------------------------

# Nombre clínico legible de cada métrica (con su unidad).
METRIC_LABELS: dict[str, str] = {
    "glucose_fasting": "Glucosa en ayunas (mg/dL)",
    "hba1c": "HbA1c (%)",
    "glucose_postprandial": "Glucosa postprandial (mg/dL)",
    "weight": "Peso (kg)",
    "blood_pressure_systolic": "PA sistólica (mmHg)",
    "blood_pressure_diastolic": "PA diastólica (mmHg)",
}

# Flecha por dirección de tendencia (output de MetricStats.direction).
_DIRECTION_ARROW = {"subiendo": "↑", "bajando": "↓", "estable": "→"}

# Emoji por severidad (output de Alert.severity).
_SEVERITY_EMOJI = {"severa": "🔴", "moderada": "🟠", "leve": "🟡"}


def _fmt(x: float) -> str:
    """Formatea un número con hasta 1 decimal, sin ceros sobrantes (5.40 → '5.4')."""
    return f"{x:.1f}".rstrip("0").rstrip(".") if isinstance(x, float) else str(x)


# -------------------------------------------------------------------
# Selector de pacientes
# -------------------------------------------------------------------

def list_patients(data_dir: Path | None = None) -> list[str]:
    """
    IDs de pacientes disponibles, derivados de los CSV del EHR (`data/sample/*.csv`).
    Dinámico a propósito: cuando B reemplace el fixture por el dataset real, el selector
    de la UI se actualiza solo. Devuelve [] si no hay datos.
    """
    base = data_dir or SAMPLE_DATA_DIR
    if not base.exists():
        return []
    return sorted(p.stem for p in base.glob("*.csv"))


# -------------------------------------------------------------------
# Badge de severidad
# -------------------------------------------------------------------

def severity_badge(severity: str) -> str:
    """Devuelve un badge legible (emoji + texto) para una severidad de alerta."""
    emoji = _SEVERITY_EMOJI.get(severity.lower(), "⚪")
    return f"{emoji} {severity.capitalize()}"


# -------------------------------------------------------------------
# Tabla de alertas
# -------------------------------------------------------------------

def alerts_table(alerts: list[Alert]) -> str:
    """Tabla Markdown de alertas, ordenadas por severidad (severa → moderada → leve)."""
    if not alerts:
        return "✅ **Sin alertas**: no se detectaron violaciones de umbrales clínicos."

    orden = {"severa": 0, "moderada": 1, "leve": 2}
    alerts_ordenadas = sorted(alerts, key=lambda a: orden.get(a.severity.lower(), 9))

    filas = [
        "| Severidad | Métrica | Valor | Fecha | Detalle |",
        "|---|---|---|---|---|",
    ]
    for a in alerts_ordenadas:
        metrica = METRIC_LABELS.get(a.metric, a.metric)
        filas.append(
            f"| {severity_badge(a.severity)} | {metrica} | {_fmt(a.value)} | {a.date.isoformat()} | {a.description} |"
        )
    return "\n".join(filas)


# -------------------------------------------------------------------
# Visualización de tendencias
# -------------------------------------------------------------------

def _trend_row(label: str, stats: Optional[MetricStats]) -> str:
    if stats is None:  # métrica sin registros: no se inventan valores (ADR-0003)
        return f"| {label} | — | — | — | — | — | sin datos |"
    arrow = _DIRECTION_ARROW.get(stats.direction, "")
    return (
        f"| {label} | {_fmt(stats.last_value)} | {_fmt(stats.mean)} | "
        f"{_fmt(stats.min_value)} | {_fmt(stats.max_value)} | {_fmt(stats.delta):>4} | "
        f"{arrow} {stats.direction} |"
    )


def trends_view(analysis: Optional[MonitorAnalysis]) -> str:
    """
    Tabla Markdown con las estadísticas por métrica (último, media, mín, máx, Δ, tendencia).
    Devuelve un aviso si todavía no hay análisis del Monitor, y lista las métricas con datos
    insuficientes para evaluar su evolución.
    """
    if analysis is None:
        return "_Sin análisis del Monitor todavía. Ejecutá un análisis para ver las tendencias._"

    filas = [
        "| Métrica | Último | Media | Mín | Máx | Δ | Tendencia |",
        "|---|---|---|---|---|---|---|",
        _trend_row(METRIC_LABELS["glucose_fasting"], analysis.glucose_fasting_stats),
        _trend_row(METRIC_LABELS["hba1c"], analysis.hba1c_stats),
        _trend_row(METRIC_LABELS["glucose_postprandial"], analysis.glucose_postprandial_stats),
        _trend_row(METRIC_LABELS["weight"], analysis.weight_stats),
        _trend_row(METRIC_LABELS["blood_pressure_systolic"], analysis.blood_pressure_stats.systolic),
        _trend_row(METRIC_LABELS["blood_pressure_diastolic"], analysis.blood_pressure_stats.diastolic),
    ]
    if analysis.insufficient_data:
        filas.append("")
        filas.append("⚠️ **Datos insuficientes para evaluar la evolución:**")
        for metric, motivo in analysis.insufficient_data.items():
            filas.append(f"- {METRIC_LABELS.get(metric, metric)}: {motivo}")
    return "\n".join(filas)


# -------------------------------------------------------------------
# Perfil resumido del paciente
# -------------------------------------------------------------------

def patient_profile(
    patient_id: str,
    metrics: Optional[PatientMetrics],
    medication: Optional[list[Medication]],
) -> str:
    """
    Resumen del paciente para mostrar ANTES de lanzar el análisis (paso 2 del flujo).
    Combina lo disponible del EHR (rango de fechas, último peso/PA) con la medicación activa.
    Degrada con elegancia si faltan datos.
    """
    if not patient_id:
        return "_Seleccioná un paciente para ver su perfil._"

    lineas = [f"### Paciente {patient_id}"]

    if metrics and metrics.dates:
        n = len(metrics.dates)
        lineas.append(
            f"- **Registros EHR**: {n} ({metrics.dates[0].isoformat()} → {metrics.dates[-1].isoformat()})"
        )
        if metrics.weight:
            lineas.append(f"- **Último peso**: {_fmt(metrics.weight[-1])} kg")
        if metrics.blood_pressure_systolic and metrics.blood_pressure_diastolic:
            lineas.append(
                f"- **Última PA**: {_fmt(metrics.blood_pressure_systolic[-1])}/"
                f"{_fmt(metrics.blood_pressure_diastolic[-1])} mmHg"
            )
    else:
        lineas.append("- _Sin datos de EHR cargados para este paciente._")

    if medication:
        meds = ", ".join(f"{m.name} {m.dose} ({m.frequency})" for m in medication)
        lineas.append(f"- **Medicación activa**: {meds}")
    else:
        lineas.append("- **Medicación activa**: sin registros")

    return "\n".join(lineas)


# -------------------------------------------------------------------
# Reporte clínico (panel principal)
# -------------------------------------------------------------------

def format_report(report: Optional[str]) -> str:
    """Formatea el reporte del Agente Clínico para el panel principal."""
    if not report:
        return (
            "_El reporte clínico aparecerá acá tras ejecutar el análisis._\n\n"
            "1. Seleccioná un paciente · 2. (Opcional) Agregá contexto clínico · "
            "3. Presioná **Analizar paciente**."
        )
    return report


# -------------------------------------------------------------------
# Visor de logs (pestaña de observabilidad)
# -------------------------------------------------------------------

# Grupo de evento → predicado, para el filtro de la pestaña dev.
_EVENT_GROUPS: dict[str, str] = {
    "node": "node_start",
    "routing": "routing",
    "llm": "llm",
    "tool": "tool",
}


def _event_group(event: str) -> str:
    """Clasifica un `event` del log en un grupo legible (node/routing/llm/tool/otro)."""
    if event == "node_start":
        return "node"
    if event == "routing":
        return "routing"
    if event.startswith("llm"):
        return "llm"
    if event.startswith("tool"):
        return "tool"
    return "otro"


def load_log_entries(
    event_filter: Optional[str] = None,
    path: Path | None = None,
    limit: int = 500,
) -> list[dict]:
    """
    Lee `logs/agent.jsonl` y devuelve las entradas (dicts), más recientes primero.

    - `event_filter`: None/"todos" → todas; "node"/"routing"/"llm"/"tool" → solo ese grupo.
    - Tolera líneas corruptas/parciales (las saltea) y archivo inexistente (devuelve []).
    """
    log_path = path or LOG_FILE
    if not log_path.exists():
        return []

    group = event_filter if event_filter not in (None, "todos", "all") else None

    # Tail acotado: conservamos solo las últimas `limit` entradas (ya filtradas) con un
    # deque de tamaño fijo. Así la memoria queda acotada y no materializamos miles de dicts
    # aunque el .jsonl haya crecido hasta el tope de rotación (5 MB).
    kept: deque[dict] = deque(maxlen=limit)
    with log_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if group and _event_group(entry.get("event", "")) != group:
                continue
            kept.append(entry)

    kept.reverse()  # más recientes primero
    return list(kept)


def _summarize_entry(entry: dict) -> str:
    """Resumen de una línea de log para la columna 'resumen' de la tabla."""
    event = entry.get("event", "")
    name = entry.get("name", "")
    if event == "routing":
        return f"{name} → nodo {entry.get('node', '?')}"
    if event == "llm_start":
        n = len(entry.get("prompts") or entry.get("messages") or [])
        return f"{name} · {n} prompt(s)"
    if event == "llm_end":
        tokens = entry.get("tokens")
        return f"{len(entry.get('responses') or [])} respuesta(s)" + (f" · tokens={tokens}" if tokens else "")
    if event == "tool_start":
        return f"{name} · input={entry.get('input', '')}"
    if event == "tool_end":
        return f"output={entry.get('output', '')}"
    if event in ("llm_error", "tool_error"):
        return f"⚠️ {entry.get('error', '')}"
    return name


# Largo máximo del texto que se muestra en el resumen colapsado de cada fila. El detalle
# completo (input/output de tools, prompts y respuestas del LLM) queda en el JSON crudo que
# se despliega al expandir la fila, así que acá solo acotamos lo que se ve de un vistazo.
_CELL_MAX = 120


def _clip(text: str, n: int = _CELL_MAX) -> str:
    """Recorta un texto a `n` caracteres para mostrarlo en el resumen de una fila."""
    text = text or ""
    return text if len(text) <= n else text[: n - 1] + "…"


def log_view_html(entries: list[dict]) -> str:
    """
    Render del visor de logs como HTML plano (clase `tp2-logs`, estilada en interface/app.py).

    Cada entrada es un `<details>`: el `<summary>` muestra hora/evento/componente/resumen en
    una grilla (como una tabla) y, al expandirlo, aparece el JSON crudo completo en un `<pre>`.

    Reemplaza al antiguo gr.Dataframe a propósito: el Dataframe es un widget de planilla
    editable que tardaba ~15 s en montarse en el navegador al abrir la pestaña. Un bloque de
    HTML estático con `<details>` se pinta en milisegundos y no necesita gr.State ni un
    segundo viaje al servidor para ver el detalle (va inline). Tolera la lista vacía.
    """
    if not entries:
        return (
            "<div class='tp2-logs'><div class='tp2-empty'>"
            "Sin trazas registradas todavía. Ejecutá un análisis y volvé a refrescar."
            "</div></div>"
        )

    out = [
        "<div class='tp2-logs'>",
        "<div class='tp2-head'>"
        "<span>Hora</span><span>Evento</span><span>Componente</span><span>Resumen</span>"
        "</div>",
    ]
    for e in entries:
        ts = html.escape((e.get("ts") or "")[11:23])  # solo HH:MM:SS.mmm
        event = html.escape(e.get("event", ""))
        name = html.escape(_clip(e.get("name", "")))
        summary = html.escape(_clip(_summarize_entry(e)))
        raw = html.escape(json.dumps(e, ensure_ascii=False, indent=2, default=str))
        out.append(
            "<details class='tp2-row'><summary><div class='tp2-cells'>"
            f"<span class='tp2-ts'>{ts}</span>"
            f"<span class='tp2-ev'>{event}</span>"
            f"<span class='tp2-nm' title=\"{name}\">{name}</span>"
            f"<span class='tp2-sm' title=\"{summary}\">{summary}</span>"
            "</div></summary>"
            f"<pre class='tp2-raw'>{raw}</pre></details>"
        )
    out.append("</div>")
    return "".join(out)


# -------------------------------------------------------------------
# Visor de evaluación cualitativa (pestaña "Evaluación")
# -------------------------------------------------------------------
#
# Lee el artefacto JSON que produce tests/eval_runner.py (logs/eval_report.json): un HISTORIAL
# de corridas (array de objetos-corrida). Cada corrida tiene su propio set de casos evaluados.
# La UI ofrece un selector de corrida + un selector de caso, y compara "esperado vs. obtenido".
# Como el resto del módulo, son funciones puras (string in → string out), testeables sin Gradio.

# Etiqueta legible + emoji por categoría de caso (las 3 del enunciado).
EVAL_CATEGORY_LABELS: dict[str, str] = {
    "happy_path": "🟢 Happy path",
    "edge_cases": "🟠 Edge case",
    "adversarial": "🔴 Adversarial",
}

_RUN_HINT = (
    "Generá el artefacto con `uv run python tests/eval_runner.py` "
    "(requiere API key del LLM) y volvé a refrescar."
)


# Marcador por status de la corrida de un caso. "degraded" = el LLM falló y el grafo cayó al
# fallback determinístico (la salida no refleja al modelo); "error" = el caso crasheó entero.
_STATUS_MARK = {"ok": "", "degraded": "🟠", "error": "🔴"}


def _category_label(category: str) -> str:
    return EVAL_CATEGORY_LABELS.get(category, f"⚪ {category}")


def _case_status(case: dict) -> str:
    """Status del caso, con fallback para artefactos viejos sin el campo `status`."""
    st = case.get("status")
    if st:
        return st
    return "error" if case.get("error") else "ok"


def _status_counts(cases: list[dict]) -> dict[str, int]:
    """Cuenta casos por status (ok / degraded / error)."""
    counts = {"ok": 0, "degraded": 0, "error": 0}
    for c in cases:
        counts[_case_status(c)] = counts.get(_case_status(c), 0) + 1
    return counts


def load_eval_history(path: Path | None = None) -> list[dict]:
    """
    Lee el historial de evaluación (logs/eval_report.json) y lo devuelve como lista de corridas.

    Devuelve [] si el archivo no existe o está corrupto. Migra el formato viejo (un único
    objeto-reporte) envolviéndolo en una lista de una corrida, para no romper artefactos previos.
    """
    report_path = path or EVAL_REPORT_FILE
    if not report_path.exists():
        return []
    try:
        data = json.loads(report_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):  # formato viejo (un solo reporte) → una corrida
        return [data]
    return []


def eval_history_summary_md(history: list[dict] | None) -> str:
    """Encabezado del historial: cuántas corridas hay y cuándo fue la última."""
    if not history:
        return "_Todavía no hay corridas de evaluación._\n\n" + _RUN_HINT
    ultima = history[-1]
    return (
        f"**Historial de evaluación** — {len(history)} corrida(s) registrada(s) · "
        f"última: {ultima.get('generated_at', '?')} (`{ultima.get('model', '?')}`)"
    )


def eval_run_choices(history: list[dict] | None) -> list[tuple[str, int]]:
    """Opciones (label, índice) para el selector de corridas, más recientes primero."""
    if not history:
        return []
    choices = []
    for i, run in enumerate(history):
        n_casos = run.get("case_count", len(run.get("cases", [])))
        counts = _status_counts(run.get("cases", []))
        flags = []
        if counts["degraded"]:
            flags.append(f"🟠{counts['degraded']}")
        if counts["error"]:
            flags.append(f"🔴{counts['error']}")
        flag = f" · {' '.join(flags)}" if flags else ""
        label = (
            f"#{i + 1} · {run.get('generated_at', '?')} · "
            f"`{run.get('model', '?')}` · {n_casos} caso(s){flag}"
        )
        choices.append((label, i))
    choices.reverse()  # la corrida más reciente arriba
    return choices


def get_eval_run(history: list[dict] | None, run_idx: int | None) -> Optional[dict]:
    """Devuelve la corrida en ese índice (o la última si no se especifica o es inválido)."""
    if not history:
        return None
    if run_idx is None:
        return history[-1]
    try:
        return history[int(run_idx)]
    except (IndexError, ValueError, TypeError):
        return history[-1]


def eval_summary_md(report: Optional[dict]) -> str:
    """Cabecera con los metadatos de una corrida y el desglose por categoría."""
    if not report:
        return (
            "_Todavía no hay resultados de evaluación._\n\n" + _RUN_HINT
        )

    cases = report.get("cases", [])
    por_categoria = {cat: 0 for cat in EVAL_CATEGORY_LABELS}
    for c in cases:
        por_categoria[c.get("category", "")] = por_categoria.get(c.get("category", ""), 0) + 1
    desglose = " · ".join(
        f"{_category_label(cat)}: {n}" for cat, n in por_categoria.items() if n
    )

    counts = _status_counts(cases)
    flags = []
    if counts["degraded"]:
        flags.append(f"🟠 {counts['degraded']} degradado(s) al fallback")
    if counts["error"]:
        flags.append(f"🔴 {counts['error']} con error")
    estado = " · " + " · ".join(flags) if flags else " · ✅ sin incidencias"

    return (
        f"**Evaluación cualitativa** — {len(cases)} caso(s) · "
        f"proveedor `{report.get('provider', '?')}` · modelo `{report.get('model', '?')}`  \n"
        f"Generado: {report.get('generated_at', '?')}  \n"
        f"{desglose}{estado}"
    )


def eval_case_choices(report: Optional[dict]) -> list[tuple[str, str]]:
    """Opciones (label, id) para el selector de casos, en el orden del reporte."""
    if not report:
        return []
    choices = []
    for c in report.get("cases", []):
        desc = _clip(c.get("description", ""), 56)
        emoji = _category_label(c.get("category", "")).split(" ", 1)[0]
        mark = _STATUS_MARK.get(_case_status(c), "")
        suffix = f" {mark}" if mark else ""
        choices.append((f"{emoji} {c.get('id', '?')} — {desc}{suffix}", c.get("id", "")))
    return choices


def find_eval_case(report: Optional[dict], case_id: str | None) -> Optional[dict]:
    """Devuelve el caso con ese id (o el primero si no se especifica) del reporte."""
    if not report:
        return None
    cases = report.get("cases", [])
    if not cases:
        return None
    if case_id:
        for c in cases:
            if c.get("id") == case_id:
                return c
    return cases[0]


def eval_context_md(case: Optional[dict]) -> str:
    """Tira de contexto del caso: categoría, descripción, setup e input."""
    if not case:
        return "_Seleccioná un caso para ver la comparación._"

    lineas = [
        f"#### {_category_label(case.get('category', ''))} · `{case.get('id', '?')}`",
        case.get("description", ""),
    ]
    if case.get("setup"):
        pasos = "; ".join(json.dumps(s, ensure_ascii=False) for s in case["setup"])
        lineas.append(f"- **Setup previo:** {pasos}")
    lineas.append(f"- **Input:** `{json.dumps(case.get('input', {}), ensure_ascii=False)}`")

    meta = []
    if case.get("alerts_count") is not None:
        meta.append(f"alertas: {case['alerts_count']}")
    if case.get("duration_s") is not None:
        meta.append(f"⏱ {case['duration_s']}s")
    if case.get("model"):
        meta.append(f"modelo `{case['model']}`")
    if case.get("evaluated_at"):
        meta.append(f"corrido: {case['evaluated_at']}")
    if meta:
        lineas.append(f"- _{' · '.join(meta)}_")

    return "\n".join(lineas)


def eval_expected_md(case: Optional[dict]) -> str:
    """Panel izquierdo: el comportamiento esperado del caso."""
    if not case:
        return ""
    return case.get("expected_behavior", "_(sin comportamiento esperado definido)_")


def eval_obtained_md(case: Optional[dict]) -> str:
    """Panel derecho: la salida obtenida del sistema (reporte/respuesta del Clínico)."""
    if not case:
        return ""

    status = _case_status(case)
    if status == "error":
        return f"🔴 **Error durante la ejecución del caso**\n\n```\n{case.get('error', '')}\n```"

    parts = []
    if status == "degraded":
        # El LLM falló y el grafo cayó al fallback determinístico: la salida de abajo NO refleja
        # al modelo, así que avisamos antes de mostrarla para no puntuarla como si fuera del LLM.
        parts.append(
            "🟠 **Salida degradada — fallback determinístico, NO refleja al LLM.**  \n"
            "El modelo falló durante la corrida (rate limit, 413, timeout…) y el grafo respondió "
            "con su fallback sin LLM. Volvé a correr el caso con más cupo de tokens.\n\n"
            f"_Motivo:_\n```\n{case.get('error', '')}\n```"
        )
    obtained = case.get("obtained")
    if obtained:
        parts.append(obtained)
    return "\n\n".join(parts) if parts else "_(sin salida)_"


def eval_case_view(
    report: Optional[dict], case_id: str | None
) -> tuple[str, str, str]:
    """Render completo de un caso: (contexto, esperado, obtenido). Atajo para el wiring."""
    case = find_eval_case(report, case_id)
    return eval_context_md(case), eval_expected_md(case), eval_obtained_md(case)
