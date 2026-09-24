# orchestrator/graph.py

import logging

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from datetime import date

from orchestrator.state import AgentState, MonitorAnalysis
from orchestrator.router import (
    is_followup_message,
    is_confirmation_message,
    is_cancellation_message,
    is_reset_message,
    extract_patient_id,
)
from agents.llm_factory import has_api_key
from tools.history_tools import update_patient_history
from tools.patient_tools import load_patient_data
from agents.monitor import window_key

logger = logging.getLogger(__name__)


# -------------------------------------------------------------------
# Nodo Orquestador
# -------------------------------------------------------------------

def _reset_patient_scope() -> dict:
    """
    Campos derivados de un análisis que no deben sobrevivir a un cambio de paciente o a
    un reinicio (D4). Única fuente de esta limpieza; F3-01 la reutiliza.

    TODO(F3-02): sumar `refinement_request` cuando exista en AgentState.
    """
    return {
        "metrics_history": None,
        "medication": None,
        "patient_history": None,
        "analysis": None,
        "longitudinal_comparison": None,
        "rag_context": None,
        "report": None,
        "followup_answer": None,
        "analysis_query": None,
        "save_result": None,
        "error": None,
    }


def orchestrator_node(state: AgentState) -> AgentState:
    """
    Punto de entrada del grafo. Infiere la intención del médico a partir del
    mensaje (state["query"]) y del estado de la sesión, e inicializa el control
    del flujo para esta invocación.

    Recuerda el paciente activo (`active_patient_id`): si el objetivo cambia, o el médico
    pide reiniciar, limpia los campos derivados y fuerza el pipeline completo (D4).

    Guardado (D5): `save_requested=True` en el input (botón de la UI) o un texto inequívoco
    ("confirmar", "guardar sesión") llevan al nodo `save`; "cancelar" termina con un aviso.
    El guardado opera sobre el paciente activo: nunca cambia de paciente.

    TODO: reemplazar la heurística de router.py por clasificación vía LLM.
    """
    query = state.get("query") or ""
    active = state.get("active_patient_id")

    # La señal del botón viaja en el input de esta invocación; el nodo `save` la apaga
    # al terminar, así que un True persistido no dispara un guardado en el mensaje siguiente.
    saving = bool(state.get("save_requested")) or is_confirmation_message(query)
    cancelling = not saving and is_cancellation_message(query)

    updates: dict = {
        "save_requested": saving,
        # Control del loop: se reinicia en cada mensaje nuevo del médico
        "iteration": 0,
        "information_sufficient": True,
        # Un error de dominio o una respuesta de un mensaje anterior no se arrastran
        "error": None,
        "followup_answer": None,
    }
    if saving or cancelling:
        updates["is_followup"] = False
        if cancelling:
            updates["conversation"] = [{"role": "assistant", "content": "Guardado cancelado."}]
        return updates

    # El id nombrado en el mensaje manda: en el chat no viene `patient_id` y el que
    # figura en el estado es el del análisis anterior.
    target = extract_patient_id(query) or state.get("patient_id") or active
    switching = bool(target) and target != active
    resetting = is_reset_message(query)
    updates["active_patient_id"] = target
    updates["patient_id"] = target or ""

    if switching or resetting:
        logger.info("Orquestador: %s (activo=%s → objetivo=%s), limpiando estado derivado",
                    "cambio de paciente" if switching else "reinicio", active, target)
        updates.update(_reset_patient_scope())
        updates["is_followup"] = False
    else:
        # Routing inferido (heurística por ahora; ver router.py)
        updates["is_followup"] = is_followup_message(state, query)
    if not updates["is_followup"]:
        # Consulta que origina el análisis vigente: es la que se persiste al guardar.
        updates["analysis_query"] = query
    return updates


# -------------------------------------------------------------------
# Nodo de guardado — persiste la sesión en el historial (F1-04)
# -------------------------------------------------------------------

def _metrics_summary(analysis: MonitorAnalysis) -> dict[str, float]:
    """Último valor de cada métrica con datos; permite comparar con la próxima sesión."""
    series = {
        "glucose_fasting": analysis.glucose_fasting_stats,
        "hba1c": analysis.hba1c_stats,
        "glucose_postprandial": analysis.glucose_postprandial_stats,
        "weight": analysis.weight_stats,
        "blood_pressure_systolic": analysis.blood_pressure_stats.systolic,
        "blood_pressure_diastolic": analysis.blood_pressure_stats.diastolic,
    }
    return {name: stats.last_value for name, stats in series.items() if stats is not None}


def build_session_data(state: AgentState) -> dict:
    """Contenido de la sesión a persistir (definición conceptual §2.6, Tool 9)."""
    analysis = state["analysis"]
    return {
        "date": date.today().isoformat(),
        "query": state.get("analysis_query") or "",
        "doctor_context": state.get("doctor_context") or "",
        "report": state["report"],
        "alerts": [a.model_dump(mode="json") for a in analysis.alerts],
        "metrics_summary": _metrics_summary(analysis),
        "longitudinal_comparison": state.get("longitudinal_comparison"),
        "suggested_questions": [],  # TODO(F3-04): preguntas sugeridas del reporte estructurado
    }


def save_node(state: AgentState) -> AgentState:
    """
    Persiste la sesión del paciente activo con `update_patient_history` y deja el resultado
    real en `save_result` (id o error). Sin reporte o sin análisis no guarda nada.
    """
    patient_id = state.get("active_patient_id") or state.get("patient_id") or ""
    if not state.get("report") or state.get("analysis") is None:
        result = {"ok": False, "error": "No hay reporte para guardar."}
    else:
        result = update_patient_history(patient_id=patient_id, session_data=build_session_data(state))

    if result.get("ok"):
        message = f"💾 Sesión guardada en el historial de {patient_id} (id {result['session_id']})."
        logger.info("Guardado: sesión %s de %s", result["session_id"], patient_id)
    else:
        message = f"⚠️ No se guardó la sesión: {result.get('error', 'error desconocido')}"
        logger.warning("Guardado fallido para %s: %s", patient_id, result.get("error"))
    return {
        "save_requested": False,
        "save_result": result,
        "conversation": [{"role": "assistant", "content": message}],
    }


# -------------------------------------------------------------------
# Nodo Monitor — agente real con fallback a stub si no hay API key
# -------------------------------------------------------------------

def _patient_data_error(patient_id: str) -> str | None:
    """
    Verifica que el paciente tenga datos en el EHR antes de analizarlo (ADR-0003).
    Devuelve el mensaje de error para el médico, o None si hay datos.
    """
    try:
        load_patient_data(patient_id)
    except FileNotFoundError:
        return f"No hay datos de EHR para el paciente '{patient_id}'."
    except ValueError:
        return f"El paciente '{patient_id}' no tiene registros cargados en el EHR."
    return None


def monitor_node(state: AgentState) -> AgentState:
    """
    Analiza las métricas del paciente con el Agente Monitor real (ReAct + tools
    determinísticas). Si no hay GROQ_API_KEY configurada, cae al stub para que
    los tests y el desarrollo sin LLM sigan funcionando.

    Si el paciente no tiene datos, no se analiza nada: se devuelve `error` y el grafo
    termina sin invocar al Clínico (nunca se inventan valores, ADR-0003).
    """
    patient_id = state.get("patient_id", "")

    error = _patient_data_error(patient_id)
    if error:
        logger.warning("Monitor: %s", error)
        return {
            "analysis": None,
            "error": error,
            "conversation": [{
                "role": "assistant",
                "content": f"[Monitor] {error}",
            }],
        }

    # Refinamiento (vuelta desde el Clínico): la única acción posible hoy es ampliar a la
    # ventana global, y es determinística (F1-06). TODO(F3-02): ejecutar el RefinementRequest.
    if state.get("iteration", 0) >= 1:
        return _monitor_refinement(state)

    # Si no hay API key, usar el fallback determinístico sin LLM
    if not has_api_key():
        logger.warning("Monitor: sin API key, ejecutando fallback determinístico")
        return _monitor_fallback(state)

    try:
        from agents.monitor import run_monitor_agent
        analysis = run_monitor_agent(state)

        # Resumen legible para la conversación
        n_alerts = len(analysis.alerts)
        alert_summary = f"{n_alerts} alerta(s) detectada(s)" if n_alerts > 0 else "sin alertas"
        summary = (
            f"Análisis del paciente {patient_id} completado: {alert_summary}. "
            f"Métricas analizadas: glucosa en ayunas, HbA1c, glucosa postprandial, "
            f"peso, presión arterial. Medicación: {len(analysis.medication)} fármaco(s)."
        )

        return {
            "analysis": analysis,
            "conversation": [{
                "role": "assistant",
                "content": f"[Monitor] {summary}",
            }],
        }
    except Exception as e:
        logger.error("Monitor: error en agente real, fallback determinístico: %s", e)
        return _monitor_fallback(state)


def _monitor_refinement(state: AgentState) -> AgentState:
    """Re-análisis del refinamiento: mismas tools, ventana global (la más amplia disponible)."""
    from agents.monitor import _build_analysis

    patient_id = state.get("patient_id", "")
    previous = state.get("analysis")
    analysis = _build_analysis(patient_id)
    before = window_key(previous.analysis_window) if previous else "?"
    logger.info("Monitor: refinamiento de %s, ventana %s → global", patient_id, before)
    return {
        "analysis": analysis,
        "conversation": [{
            "role": "assistant",
            "content": f"[Monitor] Refinamiento: análisis ampliado de la ventana {before} a toda la serie.",
        }],
    }


def _monitor_fallback(state: AgentState) -> AgentState:
    """
    Fallback determinístico del Monitor: ejecuta todas las tools directamente
    sin LLM y construye un MonitorAnalysis. Útil para tests y cuando no hay API key.
    """
    patient_id = state.get("patient_id", "")

    try:
        from agents.monitor import _build_analysis

        # Sin resultados previos de un LLM: _build_analysis ejecuta todas las tools (ventana global).
        analysis = _build_analysis(patient_id)

        return {
            "analysis": analysis,
            "conversation": [{
                "role": "assistant",
                "content": f"[Monitor fallback] Análisis determinístico del paciente {patient_id} completado.",
            }],
        }
    except Exception as e:
        logger.error("Monitor fallback: error: %s", e)
        return {
            "analysis": None,
            "error": f"Error al analizar al paciente '{patient_id}': {e}",
            "conversation": [{
                "role": "assistant",
                "content": f"[Monitor] Error al analizar paciente {patient_id}: {e}",
            }],
        }


def information_sufficient_for(analysis: MonitorAnalysis | None) -> bool:
    """
    Criterio determinístico de suficiencia (F1-06, D6). La información es insuficiente SOLO si
    hay métricas sin datos suficientes Y existe una acción de refinamiento posible: hoy, ampliar
    una ventana acotada a la serie global. Si la ventana ya es global no hay nada más que pedir:
    se informa con la limitación explícita en el reporte.
    """
    if analysis is None or not analysis.insufficient_data:
        return True
    return analysis.analysis_window.is_global


def clinical_node(state: AgentState) -> AgentState:
    """
    Interpreta los hallazgos del Monitor y genera el reporte clínico
    (modos reporte y seguimiento). Antes de redactar, evalúa si la información
    del Monitor alcanza y expone la señal `information_sufficient`.
    """
    # Si no hay API key, usar el fallback determinístico sin LLM
    if not has_api_key():
        logger.warning("Clínico: sin API key, ejecutando fallback determinístico")
        return _clinical_fallback(state)

    try:
        from agents.clinical import run_clinical_agent
        updates = run_clinical_agent(state)
        # Incrementar la iteración en el nodo
        updates["iteration"] = state.get("iteration", 0) + 1
        if not state.get("is_followup"):
            updates["information_sufficient"] = information_sufficient_for(state.get("analysis"))
        return updates
    except Exception as e:
        logger.error("Clínico: error en agente real, fallback determinístico: %s", e)
        return _clinical_fallback(state)


def _clinical_fallback(state: AgentState) -> AgentState:
    """
    Fallback determinístico del Clínico: genera un reporte estático según el análisis
    y las alertas. Útil para tests y cuando no hay API key.

    Nunca afirma que el paciente está controlado si faltan datos (ADR-0003).
    """
    patient_id = state.get("patient_id", "")
    analysis = state.get("analysis")
    iteration = state.get("iteration", 0) + 1

    # Seguimiento sin LLM: no se regenera el reporte (D3); se responde en followup_answer.
    if state.get("is_followup") and state.get("report"):
        answer = (
            "[Clinical fallback] Sin LLM configurado no se pueden responder preguntas de "
            "seguimiento. El reporte de la sesión sigue disponible en el panel."
        )
        return {
            "followup_answer": answer,
            "iteration": iteration,
            "information_sufficient": True,
            "conversation": [{"role": "assistant", "content": answer}],
        }

    information_sufficient = information_sufficient_for(analysis)
    if not information_sufficient:
        report = (
            f"[Clinical fallback] Información cuantitativa insuficiente para {patient_id} en la "
            f"ventana {window_key(analysis.analysis_window)}. Solicitando ampliación al Monitor."
        )
    else:
        report = f"[Clinical fallback] Reporte determinístico del paciente {patient_id}. "
        if analysis:
            if analysis.alerts:
                report += f"Se detectaron {len(analysis.alerts)} alerta(s). "
            elif analysis.insufficient_data:
                report += "Sin alertas en los registros disponibles. "
            else:
                report += "Paciente metabólicamente controlado, sin alertas. "
            if analysis.insufficient_data:
                report += (
                    "Datos insuficientes para evaluar la evolución de: "
                    f"{', '.join(sorted(analysis.insufficient_data))} "
                    f"({analysis.records_count} registro(s) en toda la serie disponible). "
                )
            report += f"Medicación activa: {', '.join(m.name for m in analysis.medication)}."
        else:
            report += "No hay análisis de monitor disponible."

    return {
        "report": report,
        "iteration": iteration,
        "information_sufficient": information_sufficient,
        "conversation": [{
            "role": "assistant",
            "content": report
        }]
    }


# -------------------------------------------------------------------
# Funciones de routing — deciden las transiciones condicionales
# -------------------------------------------------------------------

def route_from_orchestrator(state: AgentState) -> str:
    """
    Decide el camino desde el Orquestador:
    - guardado pedido           → nodo `save` (persiste y termina)
    - guardado cancelado        → terminar
    - pregunta de seguimiento   → directo al Clínico
    - consulta nueva            → pipeline completo (Monitor → Clínico)
    """
    if state.get("save_requested"):
        return "save"
    if is_cancellation_message(state.get("query") or ""):
        return "cancel"
    if state.get("is_followup"):
        return "followup"
    return "pipeline"


def route_after_monitor(state: AgentState) -> str:
    """
    Tras el Monitor: si no hubo datos del paciente (`error`), el flujo termina sin
    invocar al Clínico; si hay análisis, sigue a la interpretación (ADR-0003).
    """
    return "end" if state.get("error") else "clinical"


def decide_next(state: AgentState) -> str:
    """
    Evalúa el estado tras el Agente Clínico y decide si refinar o terminar.
    Implementa el loop de refinamiento descripto en la definición conceptual:
    el Orquestador devuelve el control al Monitor cuando el Clínico señala que
    la información es insuficiente, respetando el guardrail de 3 iteraciones.
    """
    # Guardrail: máximo 3 iteraciones
    if state.get("iteration", 0) >= 3:
        return "end"

    # En seguimiento el Clínico responde directo: no hay refinamiento
    if state.get("is_followup"):
        return "end"

    # Loop de refinamiento: el Clínico marcó información insuficiente
    if not state.get("information_sufficient", True):
        return "monitor"

    return "end"


# -------------------------------------------------------------------
# Construcción del grafo
# -------------------------------------------------------------------

def build_graph():
    graph = StateGraph(AgentState)

    # Registrar nodos
    graph.add_node("orchestrator", orchestrator_node)
    graph.add_node("monitor", monitor_node)
    graph.add_node("clinical", clinical_node)
    graph.add_node("save", save_node)

    # Entry point
    graph.set_entry_point("orchestrator")

    # El Orquestador decide el flujo según la intención inferida
    graph.add_conditional_edges(
        "orchestrator",
        route_from_orchestrator,
        {
            "pipeline": "monitor",
            "followup": "clinical",
            "save": "save",
            "cancel": END,
        }
    )
    graph.add_edge("save", END)

    # El Monitor entrega sus hallazgos al Clínico, salvo que no haya datos del paciente
    graph.add_conditional_edges(
        "monitor",
        route_after_monitor,
        {
            "clinical": "clinical",
            "end": END,
        }
    )

    # El Clínico evalúa si refinar (volver al Monitor) o terminar (guardrail acá)
    graph.add_conditional_edges(
        "clinical",
        decide_next,
        {
            "monitor": "monitor",
            "end": END,
        }
    )

    # Compilar con memoria de sesión (checkpointer por thread_id)
    memory = MemorySaver()
    return graph.compile(checkpointer=memory)


# Instancia global del grafo
app = build_graph()
