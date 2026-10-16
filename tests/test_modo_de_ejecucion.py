# tests/test_modo_de_ejecucion.py
#
# Modo de ejecución visible (F3-06, parcial): cada nodo registra si usó el LLM o cayó al fallback (y por
# qué), y la UI avisa. Determinístico: se simulan los errores del proveedor.

import pytest

import agents.clinical as clinical
import agents.monitor as monitor
import orchestrator.graph as graph
from interface.components import execution_warning
from orchestrator.graph import _fallback_reason, build_graph


def _cfg(t):
    return {"configurable": {"thread_id": t}}


def _analizar(app, t, pid="P002"):
    return app.invoke({"patient_id": pid, "query": f"Analizá al paciente {pid}", "conversation": []}, _cfg(t))


@pytest.mark.parametrize("error, motivo", [
    ("Error code: 429 - Rate limit reached for model", "rate_limit"),
    ("Error code: 413 - Request too large", "too_large"),
    ("Error code: 404 - model_not_found", "error"),
    ("conexión rechazada", "error"),
])
def test_motivo_de_la_caida_al_fallback(error, motivo):
    assert _fallback_reason(RuntimeError(error)) == motivo


def test_sin_api_key_queda_registrado(monkeypatch):
    for var in ("GROQ_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    out = _analizar(build_graph(), "m-1")
    assert out["execution_mode"] == {"monitor": "fallback:no_api_key", "clinical": "fallback:no_api_key"}


def test_cuota_agotada_en_el_clinico_se_registra(monkeypatch):
    monkeypatch.setattr(graph, "has_api_key", lambda: True)
    monkeypatch.setattr(monitor, "run_monitor_agent", lambda state: monitor._build_analysis(state["patient_id"]))

    def _sin_cuota(state):
        raise RuntimeError("Error code: 429 - Rate limit reached for model `x` on tokens per day")

    monkeypatch.setattr(clinical, "run_clinical_agent", _sin_cuota)
    out = _analizar(build_graph(), "m-2")

    assert out["execution_mode"] == {"monitor": "llm", "clinical": "fallback:rate_limit"}
    assert "[Clinical fallback]" in out["report"]


def test_con_llm_no_hay_aviso(monkeypatch):
    monkeypatch.setattr(graph, "has_api_key", lambda: True)
    monkeypatch.setattr(monitor, "run_monitor_agent", lambda state: monitor._build_analysis(state["patient_id"]))
    monkeypatch.setattr(clinical, "run_clinical_agent",
                        lambda state: {"report": "Reporte del LLM.", "conversation": []})
    out = _analizar(build_graph(), "m-3")

    assert out["execution_mode"] == {"monitor": "llm", "clinical": "llm"}
    assert execution_warning(out["execution_mode"]) == ""


def test_el_cambio_de_paciente_limpia_el_modo(monkeypatch):
    for var in ("GROQ_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    app = build_graph()
    _analizar(app, "m-4")
    monkeypatch.setattr(graph, "has_api_key", lambda: True)
    monkeypatch.setattr(monitor, "run_monitor_agent", lambda state: monitor._build_analysis(state["patient_id"]))
    monkeypatch.setattr(clinical, "run_clinical_agent", lambda state: {"report": "ok", "conversation": []})
    out = app.invoke({"query": "Analizá al paciente P003"}, _cfg("m-4"))
    assert out["execution_mode"] == {"monitor": "llm", "clinical": "llm"}


def test_aviso_de_la_ui_explica_el_motivo():
    aviso = execution_warning({"monitor": "llm", "clinical": "fallback:rate_limit"})
    assert "clinical" in aviso and "cuota" in aviso and "determinístico" in aviso
    assert "API key" in execution_warning({"monitor": "fallback:no_api_key", "clinical": "fallback:no_api_key"})
    assert execution_warning(None) == "" and execution_warning({}) == ""


def test_la_ui_muestra_el_aviso_al_analizar(monkeypatch):
    for var in ("GROQ_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    from interface import app

    chat, _, reporte, _, _ = app.analyze("P001", "")
    assert "⚠️" in chat[0]["content"] and "⚠️" in reporte
