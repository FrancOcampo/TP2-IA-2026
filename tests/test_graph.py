# tests/test_graph.py
#
# Plomería del grafo: routing, comunicación entre nodos y guardrail del loop.
# Dos modos (ver docs/tests.md):
#   - DETERMINÍSTICO (default): el fixture autouse fuerza el fallback sin LLM →
#     rápido y reproducible. Es el gate de CI.
#   - ESTOCÁSTICO (marcador `llm`): invoca el LLM real con aserciones laxas/
#     estructurales (valida que los agentes se cablean, no resultados exactos).

import pytest

from agents.llm_factory import has_api_key
from orchestrator.graph import build_graph, decide_next, route_from_orchestrator


@pytest.fixture(autouse=True)
def _force_fallback(request, monkeypatch):
    """Modo determinístico salvo en tests marcados `llm` (que usan el LLM real)."""
    if request.node.get_closest_marker("llm"):
        return
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)


@pytest.fixture
def app():
    # Una instancia nueva por test para no compartir el checkpointer
    return build_graph()


def _cfg(thread_id):
    return {"configurable": {"thread_id": thread_id}}


def test_pipeline_completo(app):
    """Consulta nueva → Monitor → Clínico, termina con reporte."""
    init = {"patient_id": "P001", "query": "Analizá al paciente", "conversation": []}
    out = app.invoke(init, _cfg("t-pipeline"))

    assert out["is_followup"] is False
    assert out["report"] is not None
    assert out["iteration"] == 1                # el Clínico corrió una vez
    # Monitor + Clínico agregaron un mensaje cada uno
    assert len(out["conversation"]) == 2


def test_followup_va_directo_al_clinico(app):
    """Con reporte previo, una pregunta de seguimiento no recalcula el Monitor."""
    init = {"patient_id": "P001", "query": "Analizá al paciente", "conversation": []}
    app.invoke(init, _cfg("t-follow"))
    out = app.invoke({"query": "¿Qué significa la HbA1c?"}, _cfg("t-follow"))

    assert out["is_followup"] is True


def test_confirmacion_termina_sin_agentes(app):
    """'confirmar' marca awaiting_confirmation y corta el flujo."""
    init = {"patient_id": "P001", "query": "Analizá al paciente", "conversation": []}
    app.invoke(init, _cfg("t-confirm"))
    out = app.invoke({"query": "confirmar"}, _cfg("t-confirm"))

    assert out["awaiting_confirmation"] is True


# ---- Unit tests de las funciones de routing ----

def test_decide_next_refina_si_info_insuficiente():
    state = {"iteration": 1, "is_followup": False, "information_sufficient": False}
    assert decide_next(state) == "monitor"


def test_decide_next_guardrail_corta_en_3():
    state = {"iteration": 3, "is_followup": False, "information_sufficient": False}
    assert decide_next(state) == "end"


def test_decide_next_termina_si_info_suficiente():
    state = {"iteration": 1, "is_followup": False, "information_sufficient": True}
    assert decide_next(state) == "end"


def test_route_from_orchestrator():
    assert route_from_orchestrator({"awaiting_confirmation": True}) == "save"
    assert route_from_orchestrator({"is_followup": True}) == "followup"
    assert route_from_orchestrator({}) == "pipeline"


def test_refinamiento_loop_insuficiente(app):
    """Paciente P004 (datos insuficientes) -> dispara loop de refinamiento y frena por guardrail."""
    init = {"patient_id": "P004", "query": "Analizá al paciente P004", "conversation": []}
    out = app.invoke(init, _cfg("t-refine"))

    # El orquestador debe realizar 3 iteraciones (vuelta al monitor y clínico) por datos insuficientes
    assert out["iteration"] == 3
    assert out["information_sufficient"] is True  # En la última iteración, frena por guardrail (suficiente=True para terminar)
    assert out["report"] is not None
    # Cada vuelta agrega mensajes a la conversación (1 monitor + 1 clínico por vuelta = 6 mensajes)
    assert len(out["conversation"]) == 6


# ---- Modo estocástico: el LLM real (plomería, no contenido) ----

@pytest.mark.llm
def test_pipeline_estocastico_se_cablea(app):
    """Con LLM real, el pipeline completo corre de punta a punta y respeta el guardrail.

    Aserciones LAXAS a propósito: validan que Monitor y Clínico se comunican y que el
    grafo termina, no un resultado exacto (eso es no determinístico).
    """
    if not has_api_key():
        pytest.skip("requiere API key (modo estocástico)")

    init = {"patient_id": "P002", "query": "Analizá al paciente", "conversation": []}
    out = app.invoke(init, _cfg("t-llm"))

    assert out["report"] is not None          # el Clínico produjo un reporte
    assert len(out["conversation"]) >= 2       # Monitor y Clínico aportaron mensajes
    assert 1 <= out["iteration"] <= 3          # terminó dentro del guardrail


@pytest.mark.llm
def test_seguimiento_estocastico_no_pisa_reporte(app):
    """Con LLM real, la respuesta de seguimiento va a followup_answer y el reporte queda igual (F1-03)."""
    if not has_api_key():
        pytest.skip("requiere API key (modo estocástico)")

    init = {"patient_id": "P002", "query": "Analizá al paciente", "conversation": []}
    reporte = app.invoke(init, _cfg("t-llm-follow"))["report"]
    out = app.invoke({"query": "¿Qué significa la HbA1c?"}, _cfg("t-llm-follow"))

    assert out["is_followup"] is True
    assert out["followup_answer"]
    assert out["report"] == reporte
