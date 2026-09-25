# agents/clinical.py
#
# Agente Clínico real — reemplaza el stub de orchestrator/graph.py.
#
# Implementación (contrato A+C, ADR-0015):
#   - Agente ReAct: el LLM interpreta los hallazgos del Monitor, consulta el historial del
#     paciente y las guías clínicas vía RAG, y redacta el reporte.
#   - AGENT_MODE=lean (default, free tier): el historial y la comparación se consultan por código
#     (son búsquedas determinísticas) y van en el prompt; el LLM solo busca en las guías y redacta,
#     con pocos pasos. AGENT_MODE=react: el LLM decide todas las tools (loop completo).
#   - El contexto va compacto en ambos modos (agents/context.py, F3-05).
#   - Historial: tools/history_tools.py (SQLite local o MongoDB, ver tools/history_store.py).
#   - RAG: rag/retriever.py + ChromaDB (implementación real).
#   - El output es una actualización del AgentState.

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool

from agents.context import (
    compact_history,
    metrics_summary,
    recent_conversation,
    summarize_analysis,
    validate_citations,
)
from agents.llm_factory import agent_mode, build_llm, extract_content

from agents.prompts import (
    CLINICAL_HUMAN_TEMPLATE_FOLLOWUP,
    CLINICAL_HUMAN_TEMPLATE_REPORT,
    CLINICAL_LEAN_PREFETCH,
    CLINICAL_SYSTEM_PROMPT,
)
from orchestrator.state import AgentState
from tools.history_tools import compare_with_previous_sessions, get_patient_history
from rag.retriever import search_clinical_guidelines
from tools.patient_tools import load_patient_data

logger = logging.getLogger(__name__)

# -------------------------------------------------------------------
# Tools LangChain — wrappers de las funciones clínicas stubs.
# -------------------------------------------------------------------

def _safe_json(fn, *args) -> str:
    """Ejecuta una tool y serializa el resultado; un error vuelve como {"error": ...} al LLM."""
    try:
        return json.dumps(fn(*args), ensure_ascii=False, default=str)
    except Exception as e:
        logger.warning("Clínico: tool %s falló: %s", fn.__name__, e)
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@tool("get_patient_history")
def tool_get_patient_history(patient_id: str) -> str:
    """Devuelve el perfil del paciente (demografía, diagnósticos, comorbilidades, medicación
    de base) y el historial de sesiones previas guardadas. `found: false` si no existe.

    Args:
        patient_id: ID del paciente (ej. "P001")
    """
    return _safe_json(lambda pid: compact_history(get_patient_history(pid)), patient_id)


@tool("compare_with_previous_sessions")
def tool_compare_with_previous_sessions(patient_id: str) -> str:
    """Compara métricas de la sesión actual del paciente con las previas registradas.

    Args:
        patient_id: ID del paciente (ej. "P001")
    """
    return _safe_json(compare_with_previous_sessions, patient_id)


@tool("search_clinical_guidelines")
def tool_search_clinical_guidelines(query: str) -> str:
    """Busca fragmentos relevantes de las guías clínicas (SAD 2025 y Guía Nacional/MSAL 2019) basados en el query.

    Args:
        query: consulta de búsqueda (ej. "objetivo HbA1c" o "hipoglucemia severa")
    """
    fragments = search_clinical_guidelines(query, k=3)
    return "\n\n".join(fragments) if fragments else "No se encontraron fragmentos relevantes."


# Lista de tools para bind al LLM
CLINICAL_TOOLS = [
    tool_get_patient_history,
    tool_compare_with_previous_sessions,
    tool_search_clinical_guidelines,
]

# Pasos máximos del loop por modo (cada paso reenvía todo el historial de mensajes al LLM).
_MAX_CLINICAL_STEPS = {"react": 10, "lean": 3}

_FORCE_ANSWER = (
    "Ya no quedan pasos de herramientas. Redactá ahora la respuesta final con la información "
    "disponible, sin llamar herramientas."
)


def _build_clinical_llm():
    """Construye el LLM del Clínico con las tools bindeadas."""
    return build_llm(CLINICAL_TOOLS)


def _build_answer_llm():
    """LLM sin tools: fuerza la redacción cuando se agotan los pasos (F3-06)."""
    return build_llm()


def _data_period(patient_id: str) -> str | None:
    """Rango de fechas del EHR del paciente, para que el LLM no invente fechas."""
    try:
        dates = load_patient_data(patient_id).dates
        return f"{dates[0].isoformat()} a {dates[-1].isoformat()}"
    except (FileNotFoundError, ValueError):
        return None


def _prefetch_longitudinal(patient_id: str, analysis) -> tuple[dict, dict]:
    """Historial compacto y comparación con la sesión anterior, calculados por código (modo lean)."""
    history = compact_history(get_patient_history(patient_id))
    current = metrics_summary(analysis) if analysis else None
    comparison = compare_with_previous_sessions(patient_id, current_metrics=current)
    return history, comparison


def run_clinical_agent(state: AgentState) -> dict[str, Any]:
    """
    Ejecuta el Agente Clínico como un loop ReAct manual:
    1. Determina si es MODO REPORTE o MODO SEGUIMIENTO.
    2. Envía el system prompt + el human message (contexto compacto) al LLM.
       En modo lean, el historial y la comparación ya van en el mensaje.
    3. El LLM decide qué tools invocar; se ejecutan y se devuelven los resultados.
    4. Se repite hasta que el LLM emite una respuesta sin tool_calls, o se agotan los pasos:
       en ese caso una última llamada sin tools fuerza la respuesta (nunca queda vacía).
    5. Se actualiza el estado.
    """
    patient_id = state.get("patient_id", "")
    query = state.get("query", "")
    doctor_context = state.get("doctor_context", "") or ""
    is_followup = bool(state.get("is_followup") and state.get("report"))
    existing_report = state.get("report")
    analysis = state.get("analysis")
    mode = agent_mode()

    llm = _build_clinical_llm()

    # Acumuladores de resultados de las herramientas para el estado estructurado
    comparison: dict | str | None = None
    collected_rag_context: list[str] = []

    if is_followup:
        human_msg_content = CLINICAL_HUMAN_TEMPLATE_FOLLOWUP.format(
            report=existing_report,
            analysis=summarize_analysis(analysis, _data_period(patient_id)),
            conversation=recent_conversation(state.get("conversation", [])),
            query=query,
        )
    else:
        human_msg_content = CLINICAL_HUMAN_TEMPLATE_REPORT.format(
            analysis=summarize_analysis(analysis, _data_period(patient_id)),
            doctor_context=doctor_context or "(sin contexto adicional)",
            query=query,
        )
        if mode == "lean":
            history, comparison = _prefetch_longitudinal(patient_id, analysis)
            human_msg_content += CLINICAL_LEAN_PREFETCH.format(
                history=json.dumps(history, ensure_ascii=False, default=str),
                comparison=json.dumps(comparison, ensure_ascii=False, default=str),
            )

    messages = [
        SystemMessage(content=CLINICAL_SYSTEM_PROMPT),
        HumanMessage(content=human_msg_content),
    ]

    max_steps = _MAX_CLINICAL_STEPS[mode]
    logger.info("Clínico: loop ReAct (modo %s, %s, máx %d pasos)",
                mode, "seguimiento" if is_followup else "reporte", max_steps)

    tools_by_name = {t.name: t for t in CLINICAL_TOOLS}
    response = None
    for step in range(max_steps):
        response = llm.invoke(messages)
        messages.append(response)

        # Si no hay tool_calls, el LLM terminó de redactar
        if not response.tool_calls:
            logger.info("Clínico: LLM terminó tras %d pasos", step + 1)
            break

        for tc in response.tool_calls:
            tool_name, tool_args, tool_id = tc["name"], tc["args"], tc["id"]
            tool_fn = tools_by_name.get(tool_name)
            result = (json.dumps({"error": f"Tool desconocida: {tool_name}"}) if tool_fn is None
                      else tool_fn.invoke(tool_args))
            messages.append(ToolMessage(content=result, tool_call_id=tool_id))

            if tool_name == tool_compare_with_previous_sessions.name:
                comparison = result
            elif tool_name == tool_search_clinical_guidelines.name:
                collected_rag_context.append(result)

            logger.info(
                "Clínico: tool=%s args=%s → %s",
                tool_name, json.dumps(tool_args, ensure_ascii=False),
                result[:200] if isinstance(result, str) else str(result)[:200],
            )
    else:
        logger.warning("Clínico: alcanzó el límite de %d pasos; se fuerza la respuesta", max_steps)
        response = _build_answer_llm().invoke(messages + [HumanMessage(content=_FORCE_ANSWER)])

    final_content = extract_content(response).strip()
    if not final_content:
        # Nunca se guarda un reporte vacío: se falla fuerte y el nodo cae al fallback (logueado).
        finish = (getattr(response, "response_metadata", {}) or {}).get("finish_reason")
        raise RuntimeError(f"el LLM devolvió una respuesta vacía (finish_reason={finish})")

    # Citas textuales que no provienen de ningún fragmento recuperado quedan marcadas (F3-04).
    rag_texts = collected_rag_context + list(state.get("rag_context") or [])
    final_content, unverified = validate_citations(final_content, rag_texts)
    if unverified:
        logger.warning("Clínico: %d cita(s) no verificadas contra los fragmentos del RAG", unverified)

    # Modo seguimiento: la respuesta va a `followup_answer` y el reporte de la sesión no se
    # toca (D3). No hay evaluación de suficiencia: el refinamiento es solo del modo reporte.
    if is_followup:
        return {
            "followup_answer": final_content,
            "information_sufficient": True,
            "conversation": [{"role": "assistant", "content": final_content}],
        }

    # La suficiencia de información NO se infiere del texto (D6): la decide clinical_node con
    # un criterio determinístico sobre el análisis (F1-06). TODO(F3-02): ClinicalAssessment.
    updates: dict[str, Any] = {
        "report": final_content,
        "conversation": [{"role": "assistant", "content": final_content}],
    }
    if comparison is None and analysis and analysis.requires_longitudinal_comparison:
        comparison = compare_with_previous_sessions(patient_id, current_metrics=metrics_summary(analysis))
    if comparison is not None:
        # TODO(F2-04): dict estructurado por métrica con clasificación de la evolución.
        updates["longitudinal_comparison"] = {"text": comparison if isinstance(comparison, str)
                                              else json.dumps(comparison, ensure_ascii=False, default=str)}
    if collected_rag_context:
        updates["rag_context"] = collected_rag_context
    return updates
