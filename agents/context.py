# agents/context.py
#
# Serialización COMPACTA del contexto que reciben los LLM (F3-05, ADR-0015). Funciones puras,
# testeables sin LLM. El objetivo es que un análisis completo entre en el free tier de Groq
# (8000 tokens/min) sin perder información clínica:
#   - el análisis del Monitor como resumen legible (no el repr de Pydantic),
#   - las alertas agrupadas por métrica y lado (una línea por grupo, no una por mes),
#   - el historial sin la serie mensual (el Monitor ya la resumió) y con las últimas sesiones,
#   - la conversación de seguimiento con los últimos turnos, sin los mensajes del Monitor.

from __future__ import annotations

from typing import Optional

from orchestrator.state import Alert, MetricStats, MonitorAnalysis
from tools.threshold_tools import THRESHOLDS

_METRIC_LABELS = {
    "glucose_fasting": ("Glucosa en ayunas", "mg/dL"),
    "hba1c": ("HbA1c", "%"),
    "glucose_postprandial": ("Glucosa postprandial", "mg/dL"),
    "weight": ("Peso", "kg"),
    "blood_pressure_systolic": ("PA sistólica", "mmHg"),
    "blood_pressure_diastolic": ("PA diastólica", "mmHg"),
}


def _fmt(value: float) -> str:
    return f"{value:g}"


def _stats_line(metric: str, stats: Optional[MetricStats], insufficient: Optional[str] = None) -> str:
    label, unit = _METRIC_LABELS[metric]
    if stats is None:
        return f"- {label}: sin datos"
    if insufficient:
        # Sin Δ ni dirección: con 1 registro "Δ +0 · estable" invitaba al LLM a afirmar una
        # estabilidad que no se puede observar (eval edge_01, ADR-0003).
        return f"- {label} ({unit}): último {_fmt(stats.last_value)} · SIN tendencia evaluable ({insufficient})"
    return (f"- {label} ({unit}): último {_fmt(stats.last_value)} · media {_fmt(round(stats.mean, 1))} · "
            f"mín {_fmt(stats.min_value)} · máx {_fmt(stats.max_value)} · "
            f"Δ {stats.delta:+g} · {stats.direction}")


def _alert_groups(alerts: list[Alert]) -> list[str]:
    """Una línea por (métrica, lado): cantidad, período, peor valor y umbral vulnerado."""
    groups: dict[tuple[str, bool], list[Alert]] = {}
    for a in alerts:
        groups.setdefault((a.metric, "hipoglucemia" in a.description), []).append(a)
    lines = []
    for (metric, is_hypo), group in groups.items():
        label, unit = _METRIC_LABELS.get(metric, (metric, ""))
        worst = min(group, key=lambda a: a.value) if is_hypo else max(group, key=lambda a: a.value)
        severities = sorted({a.severity for a in group})
        dates = sorted(a.date for a in group)
        period = dates[0].isoformat() if len(dates) == 1 else f"{dates[0].isoformat()} a {dates[-1].isoformat()}"
        # Umbral vulnerado del peor valor, SIN la fuente: el LLM la citaba como si fuera un
        # fragmento recuperado de la guía (eval edge_03). Las citas salen solo del RAG.
        detail = worst.description.split("(", 1)[-1].rstrip(")").split(";", 1)[0]
        lines.append(
            f"- {label}{' (hipoglucemia)' if is_hypo else ''}: {len(group)} registro(s) "
            f"[{', '.join(severities)}], {period}; peor valor {_fmt(worst.value)} {unit} ({detail})"
        )
    return lines


def control_targets() -> str:
    """
    Metas de control que usa el sistema, generadas desde la tabla de umbrales (fuente única, ADR-0011).
    Sin esto el LLM inventaba metas ("HbA1c < 6.5 %", "meta < 9 %") en la evaluación (edge_01, edge_06).
    """
    parts = []
    for spec in THRESHOLDS.values():
        bands = ", ".join(
            f"{'hipoglucemia ' if b.side == 'baja' else ''}{b.severity} {b.comparator} {b.threshold:g}"
            for b in spec["bands"]
        )
        parts.append(f"{spec['label']} ({spec['unit']}): alerta si {bands}")
    return "; ".join(parts)


def summarize_analysis(analysis: Optional[MonitorAnalysis], data_period: Optional[str] = None) -> str:
    """
    Resumen legible y compacto del MonitorAnalysis para los prompts del Clínico. `data_period`
    ("AAAA-MM-DD a AAAA-MM-DD") evita que el LLM invente fechas (eval happy_02).
    """
    if analysis is None:
        return "(sin análisis del Monitor)"
    window = analysis.analysis_window
    window_txt = ("toda la serie" if window.is_global
                  else f"últimos {window.last_n_months} meses" if window.last_n_months
                  else f"{window.start or '…'} a {window.end or '…'}")
    lines = [f"Ventana analizada: {window_txt} ({analysis.records_count} registro(s) mensuales)."]
    if data_period:
        lines.append(f"Período de los registros del EHR: {data_period} (el último registro es el valor actual).")
    if analysis.monitor_notes:
        lines.append(f"Criterio del Monitor: {analysis.monitor_notes}")
    lines.append("Metas de control del sistema (parámetros del sistema; usá estas y no otras, y no las "
                 f"cites como texto de una guía): {control_targets()}.")

    lines.append("Estadísticas:")
    lines.append(_stats_line("glucose_fasting", analysis.glucose_fasting_stats, analysis.insufficient_data.get("glucose_fasting")))
    lines.append(_stats_line("hba1c", analysis.hba1c_stats, analysis.insufficient_data.get("hba1c")))
    lines.append(_stats_line("glucose_postprandial", analysis.glucose_postprandial_stats, analysis.insufficient_data.get("glucose_postprandial")))
    lines.append(_stats_line("weight", analysis.weight_stats, analysis.insufficient_data.get("weight")))
    lines.append(_stats_line("blood_pressure_systolic", analysis.blood_pressure_stats.systolic, analysis.insufficient_data.get("blood_pressure_systolic")))
    lines.append(_stats_line("blood_pressure_diastolic", analysis.blood_pressure_stats.diastolic, analysis.insufficient_data.get("blood_pressure_diastolic")))

    if analysis.alerts:
        lines.append(f"Alertas ({len(analysis.alerts)} en total, agrupadas):")
        lines.extend(_alert_groups(analysis.alerts))
    else:
        lines.append("Alertas: ninguna.")

    if analysis.insufficient_data:
        lines.append("Datos insuficientes (no estimar ni completar):")
        lines.extend(f"- {m}: {reason}" for m, reason in sorted(analysis.insufficient_data.items()))

    if analysis.extra_windows:
        lines.append("Otras ventanas pedidas: " + ", ".join(
            f"{k} último {_fmt(s.last_value)} ({s.direction})" for k, s in analysis.extra_windows.items()
        ))

    meds = ", ".join(f"{m.name} {m.dose} ({m.frequency})" for m in analysis.medication) or "sin registros"
    lines.append(f"Medicación activa: {meds}")
    lines.append(f"requires_longitudinal_comparison: {analysis.requires_longitudinal_comparison}")
    return "\n".join(lines)


def metrics_summary(analysis: MonitorAnalysis) -> dict[str, float]:
    """Último valor de cada métrica con datos (se persiste al guardar y se compara entre sesiones)."""
    series = {
        "glucose_fasting": analysis.glucose_fasting_stats,
        "hba1c": analysis.hba1c_stats,
        "glucose_postprandial": analysis.glucose_postprandial_stats,
        "weight": analysis.weight_stats,
        "blood_pressure_systolic": analysis.blood_pressure_stats.systolic,
        "blood_pressure_diastolic": analysis.blood_pressure_stats.diastolic,
    }
    return {name: stats.last_value for name, stats in series.items() if stats is not None}


_QUOTE_RE = None


def _normalize(text: str) -> str:
    import re
    import unicodedata

    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9<>=%.]+", " ", text).strip()


def validate_citations(report: str, rag_context: list[str]) -> tuple[str, int]:
    """
    Marca las citas textuales del reporte que NO aparecen en los fragmentos recuperados por el RAG
    (F3-04, parcial). Una cita es un texto entre comillas de al menos 15 caracteres. Devuelve el
    reporte con "⚠️ (cita no verificada)" después de cada cita inventada y la cantidad marcada.
    """
    import re

    global _QUOTE_RE
    if _QUOTE_RE is None:
        _QUOTE_RE = re.compile(r'[“"«]([^”"»\n]{15,}?)[”"»]')
    corpus = _normalize(" ".join(rag_context or []))
    unverified = 0

    def _check(match):
        nonlocal unverified
        quote = _normalize(match.group(1).strip(" .…"))
        if quote and quote in corpus:
            return match.group(0)
        unverified += 1
        return match.group(0) + " ⚠️ (cita no verificada)"

    return _QUOTE_RE.sub(_check, report), unverified


def compact_history(doc: dict, max_sessions: int = 3) -> dict:
    """
    Historial para el LLM: perfil clínico y las últimas `max_sessions` sesiones (fecha, métricas,
    resumen). Sin `metrics_history`: la serie mensual ya está resumida en el análisis del Monitor.
    """
    if not doc.get("found", True):
        return {"patient_id": doc.get("patient_id"), "found": False, "sessions": []}
    sessions = doc.get("sessions") or []
    return {
        "patient_id": doc.get("patient_id"),
        "found": True,
        "demographics": doc.get("demographics", {}),
        "diagnoses": doc.get("diagnoses", []),
        "comorbidities": doc.get("comorbidities", []),
        "medications": doc.get("medications", []),
        "sessions_count": len(sessions),
        "last_sessions": [
            {k: s.get(k) for k in ("date", "metrics_summary", "report_summary") if s.get(k) is not None}
            for s in sessions[-max_sessions:]
        ],
    }


def recent_conversation(conversation: list[dict], max_turns: int = 6, max_chars: int = 600) -> str:
    """
    Últimos `max_turns` mensajes de la conversación, sin los del Monitor y truncados: el reporte
    completo ya va una vez en el prompt de seguimiento, no hace falta repetirlo.
    """
    msgs = [m for m in (conversation or []) if not str(m.get("content", "")).startswith("[Monitor")]
    lines = []
    for m in msgs[-max_turns:]:
        role = "Médico" if m.get("role") == "user" else "Asistente"
        content = str(m.get("content", ""))
        if len(content) > max_chars:
            content = content[:max_chars] + "…"
        lines.append(f"{role}: {content}")
    return "\n".join(lines) or "(sin conversación previa)"
