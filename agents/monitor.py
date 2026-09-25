# agents/monitor.py
#
# Agente Monitor real — reemplaza el stub de orchestrator/graph.py.
#
# Implementación (contrato A+C, ver "Flujo de métricas" en docs/CLAUDE.md):
#   - Agente ReAct: el LLM (Groq llama-3.3-70b) razona QUÉ métricas analizar, QUÉ ventana
#     temporal usar, y decide cuándo tiene suficiente información. No hace aritmética.
#   - Las tools son determinísticas, finas y separadas (§2.6): load_patient_data,
#     calculate_stats, detect_threshold_violations, get_medication_schedule.
#   - Las tools se invocan por `patient_id` (cargan + recortan internamente; el LLM no
#     mueve arrays). El recorte temporal vive en `window_metrics` (un solo lugar).
#   - El output es un `MonitorAnalysis` (modelo Pydantic de orchestrator/state.py).
#
# El nodo del grafo (`monitor_node` en graph.py) invoca `run_monitor_agent(state)` y
# mapea el resultado al estado compartido.

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool

from agents.llm_factory import build_llm

from agents.prompts import MONITOR_HUMAN_TEMPLATE, MONITOR_SYSTEM_PROMPT
from orchestrator.state import (
    AgentState,
    Alert,
    BloodPressureStats,
    Medication,
    MetricStats,
    MonitorAnalysis,
    PatientMetrics,
    TimeRange,
)
from tools.patient_tools import (
    SERIES_METRICS,
    calculate_stats,
    get_medication_schedule,
    load_patient_data,
    window_metrics,
)
from tools.threshold_tools import THRESHOLDS, detect_threshold_violations

logger = logging.getLogger(__name__)

# -------------------------------------------------------------------
# Tools LangChain — wrappers de las funciones determinísticas de C.
# Cada @tool tiene un docstring que el LLM usa para decidir cuándo invocarla.
# Reciben y devuelven tipos simples (str/float/dict) porque el LLM
# trabaja con JSON, no con objetos Pydantic directamente.
# -------------------------------------------------------------------


@tool("load_patient_data")
def tool_load_patient_data(patient_id: str) -> str:
    """Carga el historial clínico completo del paciente desde el EHR.

    Devuelve un resumen de las series temporales disponibles (fechas, número de registros
    y métricas incluidas). Debe invocarse una vez al inicio del análisis para confirmar
    que los datos existen.

    Args:
        patient_id: ID del paciente (ej. "P001")
    """
    try:
        metrics = load_patient_data(patient_id)
        n = len(metrics.dates)
        first = metrics.dates[0].isoformat() if metrics.dates else "N/A"
        last = metrics.dates[-1].isoformat() if metrics.dates else "N/A"
        return json.dumps({
            "patient_id": patient_id,
            "total_records": n,
            "date_range": f"{first} a {last}",
            "metrics_available": list(SERIES_METRICS),
            "has_cgm": metrics.cgm_series is not None,
        }, ensure_ascii=False)
    except (FileNotFoundError, ValueError) as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@tool("calculate_stats")
def tool_calculate_stats(patient_id: str, metric: str, last_n_months: Optional[int] = None) -> str:
    """Calcula estadísticas clínicas para una métrica del paciente.

    Devuelve: último valor, media, mínimo, máximo, cambio neto (delta) y dirección
    de la tendencia ("subiendo"/"bajando"/"estable"). Invocar una vez por cada métrica
    a analizar.

    Args:
        patient_id: ID del paciente (ej. "P001")
        metric: nombre de la métrica. Opciones: glucose_fasting, hba1c,
                glucose_postprandial, weight, blood_pressure_systolic,
                blood_pressure_diastolic
        last_n_months: si se indica, analiza solo los últimos N meses. Si no se indica,
                       analiza toda la serie.
    """
    try:
        tr = TimeRange(last_n_months=last_n_months) if last_n_months else None
        stats = calculate_stats(patient_id, metric, tr)
        return json.dumps({
            "metric": metric,
            "last_value": stats.last_value,
            "mean": round(stats.mean, 2),
            "min_value": stats.min_value,
            "max_value": stats.max_value,
            "delta": round(stats.delta, 2),
            "direction": stats.direction,
        }, ensure_ascii=False)
    except (ValueError, FileNotFoundError) as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@tool("detect_threshold_violations")
def tool_detect_threshold_violations(patient_id: str, metric: str, last_n_months: Optional[int] = None) -> str:
    """Detecta valores fuera de las metas de control de DM2 para una métrica.

    Compara cada valor contra las metas de control (no criterios diagnósticos) y devuelve las alertas
    (hiperglucemia e hipoglucemia) con fecha, valor, severidad y descripción.
    Métricas sin umbral definido (weight, blood_pressure_*) devuelven lista vacía.

    Args:
        patient_id: ID del paciente (ej. "P001")
        metric: nombre de la métrica. Opciones con umbral: glucose_fasting, hba1c,
                glucose_postprandial
        last_n_months: si se indica, analiza solo los últimos N meses. Si no se indica,
                       analiza toda la serie.
    """
    try:
        tr = TimeRange(last_n_months=last_n_months) if last_n_months else None
        alerts = detect_threshold_violations(patient_id, metric, tr)
        return json.dumps([{
            "metric": a.metric,
            "value": a.value,
            "severity": a.severity,
            "date": a.date.isoformat(),
            "description": a.description,
        } for a in alerts], ensure_ascii=False)
    except (ValueError, FileNotFoundError) as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@tool("get_medication_schedule")
def tool_get_medication_schedule(patient_id: str) -> str:
    """Devuelve la medicación activa del paciente (nombre, dosis, frecuencia).

    Args:
        patient_id: ID del paciente (ej. "P001")
    """
    meds = get_medication_schedule(patient_id)
    return json.dumps([{
        "name": m.name,
        "dose": m.dose,
        "frequency": m.frequency,
    } for m in meds], ensure_ascii=False)


# Lista de tools para bind al LLM
MONITOR_TOOLS = [
    tool_load_patient_data,
    tool_calculate_stats,
    tool_detect_threshold_violations,
    tool_get_medication_schedule,
]


# -------------------------------------------------------------------
# Agente Monitor — corre el análisis completo y devuelve MonitorAnalysis
# -------------------------------------------------------------------

# Máximo de iteraciones del loop ReAct del Monitor (guardrail interno del agente,
# distinto del guardrail de 3 iteraciones del grafo orquestador-monitor-clínico).
_MAX_MONITOR_STEPS = 20

# Registros mínimos de una métrica para poder evaluar su evolución (por debajo, va a
# `insufficient_data`; ADR-0003).
_MIN_RECORDS_FOR_TREND = 2


def _build_monitor_llm():
    """Construye el LLM del Monitor con las tools bindeadas."""
    return build_llm(MONITOR_TOOLS)


def run_monitor_agent(state: AgentState) -> MonitorAnalysis:
    """
    Ejecuta el Agente Monitor como un loop ReAct manual:
    1. Envía el system prompt + el mensaje con patient_id y doctor_context.
    2. El LLM decide qué tools invocar (load, stats, violations, meds).
    3. Se ejecutan las tools y se devuelven los resultados al LLM.
    4. Se repite hasta que el LLM emite una respuesta sin tool_calls.
    5. Se parsea la respuesta final como MonitorAnalysis.

    Si el LLM no logra armar un análisis estructurado, se construye uno
    programáticamente como fallback (las tools son determinísticas y ya se
    ejecutaron durante el loop).
    """
    patient_id = state.get("patient_id", "")
    query = state.get("query", "")
    doctor_context = state.get("doctor_context", "") or ""

    llm = _build_monitor_llm()

    # Armar la secuencia inicial de mensajes
    human_msg = MONITOR_HUMAN_TEMPLATE.format(
        patient_id=patient_id,
        query=query or "(sin consulta específica)",
        doctor_context=doctor_context or "(sin contexto adicional)",
    )
    messages = [
        SystemMessage(content=MONITOR_SYSTEM_PROMPT),
        HumanMessage(content=human_msg),              # patient_id + doctor_context
    ]

    # Lo que el LLM pidió y obtuvo; se ensambla de forma determinística al final
    collected = CollectedResults()

    # Loop ReAct
    for step in range(_MAX_MONITOR_STEPS):
        response = llm.invoke(messages)
        messages.append(response)

        # Si no hay tool_calls, el LLM terminó de razonar
        if not response.tool_calls:
            logger.info("Monitor: LLM terminó tras %d pasos", step + 1)
            break

        # Ejecutar cada tool_call y agregar el resultado como ToolMessage
        from langchain_core.messages import ToolMessage

        for tc in response.tool_calls:
            tool_name = tc["name"]
            tool_args = tc["args"]
            tool_id = tc["id"]

            # Buscar la tool por nombre
            tool_fn = {t.name: t for t in MONITOR_TOOLS}.get(tool_name)
            if tool_fn is None:
                result = json.dumps({"error": f"Tool desconocida: {tool_name}"})
            else:
                result = tool_fn.invoke(tool_args)

            messages.append(ToolMessage(content=result, tool_call_id=tool_id))

            collected.track(tool_name, tool_args, result)

            logger.info(
                "Monitor: tool=%s args=%s → %s",
                tool_name, json.dumps(tool_args, ensure_ascii=False),
                result[:200] if isinstance(result, str) else str(result)[:200],
            )
    else:
        logger.warning("Monitor: alcanzó el límite de %d pasos", _MAX_MONITOR_STEPS)

    # Construir MonitorAnalysis con fallback programático
    # (El LLM razonó y ejecutó las tools; ahora ensamblamos los resultados
    # de forma determinística para no depender del parsing de la respuesta del LLM.)
    return _build_analysis(patient_id, collected)


def _timerange_from_args(tool_args: dict) -> TimeRange:
    """Ventana pedida en una tool call (los wrappers solo exponen `last_n_months`)."""
    n = tool_args.get("last_n_months")
    return TimeRange(last_n_months=n) if n else TimeRange()


def window_key(timerange: TimeRange) -> str:
    """Clave legible y estable de una ventana: 'global', '3m' o 'AAAA-MM-DD..AAAA-MM-DD'."""
    if timerange.is_global:
        return "global"
    if timerange.last_n_months is not None:
        return f"{timerange.last_n_months}m"
    return f"{timerange.start or ''}..{timerange.end or ''}"


@dataclass
class CollectedResults:
    """
    Registro de las llamadas analíticas del LLM (F1-05). Se registran las LLAMADAS
    (métrica + ventana), no se deducen de los resultados: una detección sin alertas
    también cuenta como hecha y no se repite.
    """
    analysis_window: Optional[TimeRange] = None  # ventana de la primera llamada analítica (D7)
    stats: dict[tuple[str, str], MetricStats] = field(default_factory=dict)  # (métrica, ventana)
    checked: set[tuple[str, str]] = field(default_factory=set)             # detecciones hechas
    alerts: dict[tuple[str, str], list[Alert]] = field(default_factory=dict)
    meds: list[Medication] = field(default_factory=list)

    def track(self, tool_name: str, tool_args: dict, result: str) -> None:
        try:
            data = json.loads(result)
        except (json.JSONDecodeError, TypeError):
            return
        if isinstance(data, dict) and "error" in data:
            return

        if tool_name == tool_get_medication_schedule.name and isinstance(data, list):
            self.meds = [Medication(**m) for m in data]
            return
        if tool_name not in (tool_calculate_stats.name, tool_detect_threshold_violations.name):
            return

        timerange = _timerange_from_args(tool_args)
        if self.analysis_window is None:
            self.analysis_window = timerange
        key = (tool_args.get("metric", ""), window_key(timerange))

        if tool_name == tool_calculate_stats.name and isinstance(data, dict):
            self.stats[key] = MetricStats(**{k: data[k] for k in MetricStats.model_fields})
        elif isinstance(data, list):
            self.checked.add(key)
            self.alerts[key] = [
                Alert(metric=a["metric"], value=a["value"], severity=a["severity"],
                      date=date.fromisoformat(a["date"]), description=a["description"])
                for a in data
            ]


def _dedupe_alerts(alerts: list[Alert]) -> list[Alert]:
    """
    Una observación genera a lo sumo una alerta: clave (métrica, fecha). Un registro no puede
    violar la banda alta y la baja a la vez, así que la fecha identifica al lado.
    TODO(F2-03): usar (metric, date, side) cuando Alert tenga `side`.
    """
    seen: set[tuple[str, date]] = set()
    unique = []
    for a in alerts:
        if (a.metric, a.date) not in seen:
            seen.add((a.metric, a.date))
            unique.append(a)
    return sorted(unique, key=lambda a: (a.date, a.metric))


def _build_analysis(patient_id: str, collected: Optional[CollectedResults] = None) -> MonitorAnalysis:
    """
    Ensambla el MonitorAnalysis a partir de lo que pidió el LLM (o de nada, en el fallback).

    Una sola ventana principal (D7): la de la primera llamada analítica del LLM, o global.
    Lo que el LLM no pidió se completa con esa MISMA ventana. Las stats pedidas con otra
    ventana quedan en `extra_windows`; sus alertas no se mezclan con las principales.

    Nunca se inventan valores (ADR-0003): una métrica sin registros en la ventana queda con
    stats `None`, y las que tienen menos de `_MIN_RECORDS_FOR_TREND` registros se declaran en
    `insufficient_data`. Requiere que el paciente tenga datos en el EHR (lo verifica el nodo).
    """
    collected = collected or CollectedResults()
    window = collected.analysis_window or TimeRange()
    main_key = window_key(window)
    windowed = window_metrics(load_patient_data(patient_id), window)

    stats: dict[str, MetricStats] = {}
    insufficient_data: dict[str, str] = {}
    for metric in SERIES_METRICS:
        n_records = len(getattr(windowed, metric))
        if n_records < _MIN_RECORDS_FOR_TREND:
            insufficient_data[metric] = (
                f"{n_records} registro(s) en la ventana {main_key}; se requieren al menos "
                f"{_MIN_RECORDS_FOR_TREND} para evaluar la evolución"
            )
        if (metric, main_key) in collected.stats:
            stats[metric] = collected.stats[(metric, main_key)]
            continue
        try:
            stats[metric] = calculate_stats(patient_id, metric, window)
        except ValueError:
            # Sin registros para la métrica: se deja sin stats en lugar de inventar valores
            insufficient_data[metric] = f"sin registros en la ventana {main_key}"

    alerts: list[Alert] = []
    for metric in THRESHOLDS:
        if (metric, main_key) in collected.checked:
            alerts.extend(collected.alerts[(metric, main_key)])
        else:
            alerts.extend(detect_threshold_violations(patient_id, metric, window))
    discarded = sum(len(v) for (m, k), v in collected.alerts.items() if k != main_key)
    if discarded:
        logger.info("Monitor: %d alerta(s) de ventanas secundarias no se mezclan con la ventana %s",
                    discarded, main_key)
    alerts = _dedupe_alerts(alerts)

    extra_windows = {
        f"{metric}@{key}": s for (metric, key), s in collected.stats.items() if key != main_key
    }
    meds = collected.meds or get_medication_schedule(patient_id)
    has_moderate_or_severe = any(a.severity in ("moderada", "severa") for a in alerts)

    return MonitorAnalysis(
        glucose_fasting_stats=stats.get("glucose_fasting"),
        hba1c_stats=stats.get("hba1c"),
        glucose_postprandial_stats=stats.get("glucose_postprandial"),
        weight_stats=stats.get("weight"),
        blood_pressure_stats=BloodPressureStats(
            systolic=stats.get("blood_pressure_systolic"),
            diastolic=stats.get("blood_pressure_diastolic"),
        ),
        cgm_metrics=None,  # CGM fuera de alcance
        alerts=alerts,
        medication=meds,
        requires_rag=has_moderate_or_severe,
        requires_longitudinal_comparison=has_moderate_or_severe,  # TODO(F3-03): criterio propio
        insufficient_data=insufficient_data,
        records_count=len(windowed.dates),
        analysis_window=window,
        extra_windows=extra_windows,
    )
