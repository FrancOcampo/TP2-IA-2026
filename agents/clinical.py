# agents/clinical.py
#
# Agente Clínico real — reemplaza el stub de orchestrator/graph.py.
#
# Implementación (contrato A+C):
#   - Agente ReAct: el LLM (Groq llama-3.3-70b-versatile) interpreta los hallazgos del Monitor,
#     consulta el historial del paciente en MongoDB y las guías clínicas vía RAG, y redacta el reporte.
#   - Historial: tools/history_tools.py (SQLite local o MongoDB, ver tools/history_store.py).
#   - RAG: rag/retriever.py + ChromaDB (implementación real).
#   - El output es una actualización del AgentState.

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool

from agents.llm_factory import build_llm, extract_content

from agents.prompts import (
    CLINICAL_HUMAN_TEMPLATE_FOLLOWUP,
    CLINICAL_HUMAN_TEMPLATE_REPORT,
    CLINICAL_SYSTEM_PROMPT,
)
from orchestrator.state import AgentState
from tools.history_tools import compare_with_previous_sessions, get_patient_history
from rag.retriever import search_clinical_guidelines

logger = logging.getLogger(__name__)

# -------------------------------------------------------------------
# Tools LangChain — wrappers de las funciones clínicas stubs.
# -------------------------------------------------------------------

@tool
def tool_get_patient_history(patient_id: str) -> str:
    """Devuelve el historial clínico de sesiones previas del paciente desde MongoDB.

    Args:
        patient_id: ID del paciente (ej. "P001")
    """
    return str(get_patient_history(patient_id))


@tool
def tool_compare_with_previous_sessions(patient_id: str) -> str:
    """Compara métricas de la sesión actual del paciente con las previas registradas.

    Args:
        patient_id: ID del paciente (ej. "P001")
    """
    return str(compare_with_previous_sessions(patient_id))


@tool
def tool_search_clinical_guidelines(query: str) -> str:
    """Busca fragmentos relevantes de las guías clínicas (ADA, SAD, MSAL) basados en el query.

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

_MAX_CLINICAL_STEPS = 10


def _build_clinical_llm():
    """Construye el LLM del Clínico con las tools bindeadas."""
    return build_llm(CLINICAL_TOOLS)


def run_clinical_agent(state: AgentState) -> dict[str, Any]:
    """
    Ejecuta el Agente Clínico como un loop ReAct manual:
    1. Determina si es MODO REPORTE o MODO SEGUIMIENTO.
    2. Envía el system prompt + el human message correspondiente al LLM.
    3. El LLM decide qué tools invocar (guidelines, history, comparison).
    4. Se ejecutan las tools y se devuelven los resultados al LLM.
    5. Se repite hasta que el LLM emite una respuesta sin tool_calls.
    6. Se parsea el contenido final y se actualiza el estado.
    """
    patient_id = state.get("patient_id", "")
    query = state.get("query", "")
    doctor_context = state.get("doctor_context", "") or ""
    is_followup = state.get("is_followup", False)
    existing_report = state.get("report")
    analysis = state.get("analysis")

    llm = _build_clinical_llm()

    # Acumuladores de resultados de las herramientas para el estado estructurado
    last_history_fetched = ""
    last_comparison_fetched = ""
    collected_rag_context: list[str] = []

    # Determinar modo y formatear el mensaje humano inicial
    if is_followup and existing_report:
        # MODO SEGUIMIENTO
        # Para pasar el historial de conversación en el template, lo formateamos de forma legible
        conv_list = state.get("conversation", [])
        formatted_conv = ""
        for msg in conv_list:
            role = "Médico" if msg.get("role") == "user" else "Asistente"
            content = msg.get("content", "")
            formatted_conv += f"{role}: {content}\n"

        human_msg_content = CLINICAL_HUMAN_TEMPLATE_FOLLOWUP.format(
            report=existing_report,
            analysis=str(analysis),
            conversation=formatted_conv or "(sin conversación previa)",
            query=query,
        )
    else:
        # MODO REPORTE
        human_msg_content = CLINICAL_HUMAN_TEMPLATE_REPORT.format(
            analysis=str(analysis),
            doctor_context=doctor_context or "(sin contexto adicional)",
            query=query,
        )

    messages = [
        SystemMessage(content=CLINICAL_SYSTEM_PROMPT),
        HumanMessage(content=human_msg_content),
    ]

    logger.info("Clínico: Iniciando loop ReAct (Modo: %s)", "Seguimiento" if is_followup else "Reporte")

    # Loop ReAct
    for step in range(_MAX_CLINICAL_STEPS):
        response = llm.invoke(messages)
        messages.append(response)

        # Si no hay tool_calls, el LLM terminó de redactar
        if not response.tool_calls:
            logger.info("Clínico: LLM terminó tras %d pasos", step + 1)
            break

        # Ejecutar cada tool_call
        for tc in response.tool_calls:
            tool_name = tc["name"]
            tool_args = tc["args"]
            tool_id = tc["id"]

            tool_fn = {t.name: t for t in CLINICAL_TOOLS}.get(tool_name)
            if tool_fn is None:
                result = json.dumps({"error": f"Tool desconocida: {tool_name}"})
            else:
                result = tool_fn.invoke(tool_args)

            messages.append(ToolMessage(content=result, tool_call_id=tool_id))

            # Guardar en acumuladores
            if tool_name == "tool_get_patient_history":
                last_history_fetched = result
            elif tool_name == "tool_compare_with_previous_sessions":
                last_comparison_fetched = result
            elif tool_name == "tool_search_clinical_guidelines":
                collected_rag_context.append(result)

            logger.info(
                "Clínico: tool=%s args=%s → %s",
                tool_name, json.dumps(tool_args, ensure_ascii=False),
                result[:200] if isinstance(result, str) else str(result)[:200],
            )
    else:
        logger.warning("Clínico: alcanzó el límite de %d pasos", _MAX_CLINICAL_STEPS)

    final_content = extract_content(response)

    # Modo seguimiento: la respuesta va a `followup_answer` y el reporte de la sesión no se
    # toca (D3). No hay evaluación de suficiencia: el refinamiento es solo del modo reporte.
    if is_followup and existing_report:
        return {
            "followup_answer": final_content,
            "information_sufficient": True,
            "conversation": [{"role": "assistant", "content": final_content}],
        }

    # La suficiencia de información NO se infiere del texto (D6): la decide clinical_node con
    # un criterio determinístico sobre el análisis (F1-06). TODO(F3-02): ClinicalAssessment.
    updates: dict[str, Any] = {
        "report": final_content,
        "conversation": [{
            "role": "assistant",
            "content": final_content,
        }]
    }

    # Si se cargó información longitudinal, guardarla estructuradamente
    if last_comparison_fetched:
        updates["longitudinal_comparison"] = {"text": last_comparison_fetched}
    elif not is_followup:
        # Fallback si no la llamó pero es P001/P002/P003 y requiere comparación
        if analysis and analysis.requires_longitudinal_comparison:
            comp_str = str(compare_with_previous_sessions(patient_id))
            updates["longitudinal_comparison"] = {"text": comp_str}

    # Si se buscaron guías, agregarlas al contexto
    if collected_rag_context:
        updates["rag_context"] = collected_rag_context

    return updates
