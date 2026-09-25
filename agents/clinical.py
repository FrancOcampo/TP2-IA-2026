# agents/clinical.py
#
# Agente Clínico real — reemplaza el stub de orchestrator/graph.py.
#
# Implementación (contrato A+C, ADR-0015 y ADR-0019):
#   - MODO REPORTE: el historial y la comparación se consultan por código. Las guías se buscan por código
#     (AGENT_MODE=lean, default, free tier) o con un loop ReAct (AGENT_MODE=react). El paso final es SIEMPRE una
#     llamada con salida estructurada (`ClinicalReport`): el LLM interpreta y cita por id de fragmento; el
#     reporte lo arma el código (agents/report.py), con disclaimer y cifras validadas.
#   - MODO SEGUIMIENTO: loop ReAct con las tools; la respuesta lleva disclaimer y cifras validadas por código.
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
from agents.report import (
    ClinicalReport,
    current_bank,
    ensure_disclaimer,
    guideline_queries,
    new_bank,
    numbered_search_result,
    prefetch_guidelines,
    render_report,
    unsupported_values,
)

from agents.prompts import (
    CLINICAL_HUMAN_TEMPLATE_FOLLOWUP,
    CLINICAL_REPORT_HUMAN_TEMPLATE,
    CLINICAL_REPORT_SYSTEM_PROMPT,
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
    """Busca fragmentos relevantes de las guías clínicas (SAD 2025, Guía Nacional/MSAL 2019 y ADA Standards of Care 2024) basados en el query.

    Args:
        query: consulta de búsqueda (ej. "objetivo HbA1c" o "hipoglucemia severa")
    """
    fragments = search_clinical_guidelines(query, k=3)
    bank = current_bank()
    if bank is not None:
        # Con ids [F#]: el LLM cita por número y el reporte valida que existan.
        return numbered_search_result(bank, fragments)
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


def _build_report_llm():
    """LLM del paso final del reporte: una llamada con salida estructurada (`ClinicalReport`)."""
    return build_llm(structured_output=ClinicalReport)


def _data_period(patient_id: str) -> str | None:
    """Rango de fechas del EHR del paciente, para que el LLM no invente fechas."""
    try:
        dates = load_patient_data(patient_id).dates
        return f"{dates[0].isoformat()} a {dates[-1].isoformat()}"
    except (FileNotFoundError, ValueError):
        return None


def _prefetch_longitudinal(patient_id: str, analysis) -> tuple[dict, dict]:
    """Historial compacto y comparación con la sesión anterior, calculados por código."""
    history = compact_history(get_patient_history(patient_id))
    current = metrics_summary(analysis) if analysis else None
    comparison = compare_with_previous_sessions(patient_id, current_metrics=current)
    return history, comparison


def _react_loop(llm, messages: list, max_steps: int, on_tool=None):
    """
    Loop ReAct manual: el LLM pide tools, se ejecutan y se devuelven los resultados, hasta que responde sin
    tool_calls o se agotan los pasos (en ese caso una última llamada sin tools fuerza la respuesta).
    Devuelve el último mensaje del LLM.
    """
    tools_by_name = {t.name: t for t in CLINICAL_TOOLS}
    response = None
    for step in range(max_steps):
        response = llm.invoke(messages)
        messages.append(response)
        if not response.tool_calls:
            logger.info("Clínico: LLM terminó tras %d pasos", step + 1)
            return response

        for tc in response.tool_calls:
            tool_name, tool_args, tool_id = tc["name"], tc["args"], tc["id"]
            tool_fn = tools_by_name.get(tool_name)
            result = (json.dumps({"error": f"Tool desconocida: {tool_name}"}) if tool_fn is None
                      else tool_fn.invoke(tool_args))
            messages.append(ToolMessage(content=result, tool_call_id=tool_id))
            if on_tool:
                on_tool(tool_name, result)
            logger.info(
                "Clínico: tool=%s args=%s → %s",
                tool_name, json.dumps(tool_args, ensure_ascii=False),
                result[:200] if isinstance(result, str) else str(result)[:200],
            )
    logger.warning("Clínico: alcanzó el límite de %d pasos; se fuerza la respuesta", max_steps)
    return _build_answer_llm().invoke(messages + [HumanMessage(content=_FORCE_ANSWER)])


def _nonempty(response) -> str:
    text = extract_content(response).strip()
    if not text:
        # Nunca se guarda una respuesta vacía: se falla fuerte y el nodo cae al fallback (logueado).
        finish = (getattr(response, "response_metadata", {}) or {}).get("finish_reason")
        raise RuntimeError(f"el LLM devolvió una respuesta vacía (finish_reason={finish})")
    return text


def run_clinical_agent(state: AgentState) -> dict[str, Any]:
    """Ejecuta el Agente Clínico: MODO SEGUIMIENTO (loop ReAct) o MODO REPORTE (reporte estructurado)."""
    if state.get("is_followup") and state.get("report"):
        return _run_followup(state)
    return _run_report(state)


def _run_followup(state: AgentState) -> dict[str, Any]:
    """
    Respuesta a una pregunta sobre el reporte ya generado. Va a `followup_answer` y el reporte de la sesión no se
    toca (D3). El disclaimer lo agrega el código (D8) y las cifras/citas sin respaldo quedan marcadas.
    """
    patient_id = state.get("patient_id", "")
    analysis = state.get("analysis")
    bank = new_bank()
    human = CLINICAL_HUMAN_TEMPLATE_FOLLOWUP.format(
        report=state.get("report"),
        analysis=summarize_analysis(analysis, _data_period(patient_id)),
        conversation=recent_conversation(state.get("conversation", [])),
        query=state.get("query", ""),
    )
    mode = agent_mode()
    logger.info("Clínico: seguimiento (modo %s)", mode)
    response = _react_loop(
        _build_clinical_llm(),
        [SystemMessage(content=CLINICAL_SYSTEM_PROMPT), HumanMessage(content=human)],
        _MAX_CLINICAL_STEPS[mode],
    )
    answer = _nonempty(response)
    answer, unverified = validate_citations(answer, bank.texts() + list(state.get("rag_context") or []))
    bad = unsupported_values(answer, human + bank.as_prompt())
    if unverified or bad:
        logger.warning("Clínico: seguimiento con %d cita(s) no verificadas y %d cifra(s) sin respaldo", unverified, len(bad))
    if bad:
        answer += f"\n\n⚠️ Cifras sin respaldo en los datos ni en las guías recuperadas: {', '.join(bad)}."
    answer = ensure_disclaimer(answer)
    return {
        "followup_answer": answer,
        "information_sufficient": True,
        "conversation": [{"role": "assistant", "content": answer}],
    }


def _run_report(state: AgentState) -> dict[str, Any]:
    """
    Reporte clínico estructurado (F3-04, ADR-0019):
      1. Historial y comparación con la sesión anterior, por código.
      2. Fragmentos de guías: por código (lean) o con un loop ReAct (react); todos con id F#.
      3. UNA llamada con salida estructurada: el LLM interpreta cada grupo de alertas y cita por id.
      4. El código arma el Markdown (agents/report.py) con disclaimer y cifras/citas validadas.
    """
    patient_id = state.get("patient_id", "")
    doctor_context = state.get("doctor_context", "") or ""
    analysis = state.get("analysis")
    mode = agent_mode()
    bank = new_bank()

    history, comparison = _prefetch_longitudinal(patient_id, analysis)
    analysis_text = summarize_analysis(analysis, _data_period(patient_id))
    longitudinal_block = (
        f"Historial del paciente (ya consultado):\n{json.dumps(history, ensure_ascii=False, default=str)}\n\n"
        f"Comparación con la sesión anterior (deltas = actual − anterior):\n"
        f"{json.dumps(comparison, ensure_ascii=False, default=str)}"
    )

    if mode == "lean":
        prefetch_guidelines(bank, guideline_queries(analysis, doctor_context), search_clinical_guidelines)
    else:
        human = (f"{analysis_text}\n\n{longitudinal_block}\n\nConsulta del médico: {state.get('query', '')}\n"
                 "Buscá en las guías el respaldo de cada hallazgo con search_clinical_guidelines.")
        _react_loop(_build_clinical_llm(),
                    [SystemMessage(content=CLINICAL_SYSTEM_PROMPT), HumanMessage(content=human)],
                    _MAX_CLINICAL_STEPS[mode])

    human_report = CLINICAL_REPORT_HUMAN_TEMPLATE.format(
        analysis=analysis_text,
        doctor_context=doctor_context or "(sin contexto adicional)",
        query=state.get("query", ""),
        longitudinal=longitudinal_block,
        fragments=bank.as_prompt(),
    )
    logger.info("Clínico: reporte estructurado (modo %s, %d fragmento(s))", mode, len(bank.items))
    report = _build_report_llm().invoke([
        SystemMessage(content=CLINICAL_REPORT_SYSTEM_PROMPT),
        HumanMessage(content=human_report),
    ])
    if not isinstance(report, ClinicalReport) or not report.summary.strip():
        raise RuntimeError("el LLM no devolvió un reporte estructurado válido")

    markdown = render_report(report, analysis, bank, comparison, human_report, patient_id)
    flagged = markdown.count("⚠️ (cifra sin respaldo") + markdown.count("cita no verificada")
    if flagged:
        logger.warning("Clínico: %d cifra(s)/cita(s) sin respaldo marcadas en el reporte", flagged)

    return {
        "report": markdown,
        "report_structured": report.model_dump(),
        "conversation": [{"role": "assistant", "content": markdown}],
        "longitudinal_comparison": {"text": json.dumps(comparison, ensure_ascii=False, default=str)},
        "rag_context": [f"[{src}] {text}" for src, text in bank.items],
    }
