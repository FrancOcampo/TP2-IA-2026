# tests/test_modo_lean.py
#
# AGENT_MODE=lean (ADR-0015) y contexto compacto para los LLM (F3-05). Determinístico: LLM
# falsos que devuelven respuestas guionadas y registran lo que reciben.

import pytest
from langchain_core.messages import AIMessage

import agents.clinical as clinical
import agents.monitor as monitor
from agents.context import compact_history, recent_conversation, summarize_analysis
from agents.monitor import MonitorPlan, _build_analysis
from orchestrator.graph import build_graph
from tools.history_tools import get_patient_history


@pytest.fixture(autouse=True)
def _lean(monkeypatch):
    monkeypatch.setenv("AGENT_MODE", "lean")


class _FakeLLM:
    """Devuelve las respuestas guionadas en orden y guarda los mensajes recibidos."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.received = []

    def invoke(self, messages):
        self.received.append(messages)
        return self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]


# ------------------------------------------------------------------
# Contexto compacto
# ------------------------------------------------------------------

def test_resumen_del_analisis_agrupa_alertas_y_no_es_repr():
    texto = summarize_analysis(_build_analysis("P002"))
    assert "MetricStats(" not in texto and "Alert(" not in texto
    assert "Alertas (17 en total, agrupadas):" in texto
    assert sum(1 for l in texto.splitlines() if l.startswith("- ") and "registro(s) [" in l) == 3
    assert len(texto) < 2500, "el resumen debe ser mucho más chico que el repr del análisis"


def test_resumen_marca_hipoglucemia_y_datos_insuficientes():
    assert "(hipoglucemia)" in summarize_analysis(_build_analysis("P003"))
    assert "Datos insuficientes" in summarize_analysis(_build_analysis("P004"))


def test_historial_compacto_sin_serie_mensual(seeded_store):
    doc = compact_history(get_patient_history("P002"))
    assert "metrics_history" not in doc
    assert doc["sessions_count"] == 3 and len(doc["last_sessions"]) == 3
    assert compact_history(get_patient_history("PX99")) == {"patient_id": "PX99", "found": False, "sessions": []}


def test_conversacion_reciente_sin_monitor_y_truncada():
    conv = [{"role": "assistant", "content": "[Monitor] análisis"}] + [
        {"role": "user" if i % 2 else "assistant", "content": f"m{i} " + "x" * 1000} for i in range(10)
    ]
    texto = recent_conversation(conv, max_turns=4, max_chars=50)
    assert "[Monitor]" not in texto
    assert texto.count("\n") == 3 and "m9" in texto and "m5" not in texto
    assert all(len(l) < 80 for l in texto.splitlines())


# ------------------------------------------------------------------
# Monitor lean: una llamada estructurada
# ------------------------------------------------------------------

def test_monitor_lean_usa_la_ventana_del_plan(monkeypatch):
    plan_llm = _FakeLLM([MonitorPlan(last_n_months=3, rationale="El médico pidió el último trimestre.")])
    monkeypatch.setattr(monitor, "_build_plan_llm", lambda: plan_llm)

    analysis = monitor.run_monitor_agent({"patient_id": "P002", "query": "últimos 3 meses"})

    assert len(plan_llm.received) == 1, "modo lean: una sola llamada al LLM"
    assert "últimos 3 meses" in plan_llm.received[0][1].content
    assert analysis.analysis_window.last_n_months == 3
    assert analysis.monitor_notes == "El médico pidió el último trimestre."


# ------------------------------------------------------------------
# Clínico lean: historial y comparación por código
# ------------------------------------------------------------------

def _state_reporte(patient_id="P002"):
    return {"patient_id": patient_id, "query": "Analizá", "analysis": _build_analysis(patient_id),
            "conversation": []}


def test_clinico_lean_precarga_historial_y_comparacion(seeded_store, monkeypatch):
    llm = _FakeLLM([AIMessage(content="Reporte clínico.")])
    monkeypatch.setattr(clinical, "_build_clinical_llm", lambda: llm)

    updates = clinical.run_clinical_agent(_state_reporte())

    human = llm.received[0][1].content
    assert "Historial del paciente (ya consultado" in human
    assert '"hba1c": 0.7' in human, "la comparación trae deltas contra la sesión semilla (8.2 − 7.5)"
    assert "metrics_history" not in human
    assert updates["report"] == "Reporte clínico."
    assert updates["longitudinal_comparison"]


def test_clinico_fuerza_respuesta_al_agotar_pasos(seeded_store, monkeypatch):
    busqueda = AIMessage(content="", tool_calls=[{
        "name": "search_clinical_guidelines", "args": {"query": "HbA1c"}, "id": "c1", "type": "tool_call"}])
    monkeypatch.setattr(clinical, "_build_clinical_llm", lambda: _FakeLLM([busqueda]))
    monkeypatch.setattr(clinical, "_build_answer_llm", lambda: _FakeLLM([AIMessage(content="Respuesta final.")]))
    monkeypatch.setattr(clinical, "search_clinical_guidelines", lambda q, k=3: ["[guia.md] meta < 7 %"])

    updates = clinical.run_clinical_agent(_state_reporte())
    assert updates["report"] == "Respuesta final.", "nunca queda un reporte vacío por agotar pasos"
    assert len(updates["rag_context"]) == 3


# ------------------------------------------------------------------
# Grafo en modo lean: refinamiento con la ventana elegida por el plan
# ------------------------------------------------------------------

def test_refinamiento_lean_amplia_ventana(seeded_store, monkeypatch):
    import orchestrator.graph as graph

    monkeypatch.setattr(graph, "has_api_key", lambda: True)
    monkeypatch.setattr(monitor, "_build_plan_llm",
                        lambda: _FakeLLM([MonitorPlan(last_n_months=1, rationale="último mes")]))

    def _sin_llm(state):
        raise RuntimeError("sin LLM: fallback del Clínico")

    monkeypatch.setattr(clinical, "run_clinical_agent", _sin_llm)
    out = build_graph().invoke(
        {"patient_id": "P002", "query": "¿Cómo le fue el último mes?", "conversation": []},
        {"configurable": {"thread_id": "lean-refine"}},
    )
    assert out["iteration"] == 2
    assert out["analysis"].analysis_window.is_global


def test_clinico_no_guarda_reportes_vacios(seeded_store, monkeypatch):
    vacio = AIMessage(content="", response_metadata={"finish_reason": "length"})
    monkeypatch.setattr(clinical, "_build_clinical_llm", lambda: _FakeLLM([vacio]))
    with pytest.raises(RuntimeError, match="vacía"):
        clinical.run_clinical_agent(_state_reporte())
