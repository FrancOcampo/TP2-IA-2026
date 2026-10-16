# tests/test_guardado.py
#
# Guardado de sesión de punta a punta (F1-04): grafo real en modo determinístico +
# historial SQLite temporal (conftest.py). Sin mocks: verifica lo que queda persistido.

import pytest

from orchestrator.graph import build_graph
from tools.history_tools import compare_with_previous_sessions, get_patient_history


@pytest.fixture(autouse=True)
def _force_fallback(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


@pytest.fixture
def app(seeded_store):
    return build_graph()


def _cfg(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def _analizar(app, patient_id: str, thread_id: str) -> dict:
    return app.invoke(
        {"patient_id": patient_id, "query": f"Analizá al paciente {patient_id}", "conversation": []},
        _cfg(thread_id),
    )


def test_boton_guardar_persiste_la_sesion(app):
    analisis = _analizar(app, "P002", "g-1")
    out = app.invoke({"save_requested": True, "query": "guardar sesión"}, _cfg("g-1"))

    assert out["save_result"]["ok"] is True
    sesion = get_patient_history("P002")["sessions"][-1]
    assert sesion["session_id"] == out["save_result"]["session_id"]
    assert sesion["query"] == "Analizá al paciente P002", "se guarda la consulta del análisis, no 'guardar sesión'"
    assert sesion["report"] == analisis["report"]
    assert len(sesion["alerts"]) == len(analisis["analysis"].alerts)
    assert sesion["metrics_summary"]["hba1c"] == 8.2
    assert "💾" in out["conversation"][-1]["content"]


def test_la_sesion_guardada_se_ve_en_la_siguiente_comparacion(app):
    _analizar(app, "P002", "g-2")
    app.invoke({"save_requested": True, "query": "guardar sesión"}, _cfg("g-2"))

    comparacion = compare_with_previous_sessions("P002", current_metrics={"hba1c": 8.0})
    assert comparacion["sessions_count"] == 4  # 3 sesiones semilla + la guardada
    assert comparacion["deltas"] == {"hba1c": -0.2}


def test_texto_confirmar_tambien_guarda(app):
    _analizar(app, "P001", "g-3")
    out = app.invoke({"query": "Confirmar."}, _cfg("g-3"))
    assert out["save_result"]["ok"] is True


def test_la_senal_no_queda_encendida(app):
    """Tras guardar, el mensaje siguiente es un seguimiento, no otro guardado."""
    _analizar(app, "P001", "g-4")
    app.invoke({"save_requested": True, "query": "guardar sesión"}, _cfg("g-4"))
    out = app.invoke({"query": "¿Qué significa la HbA1c?"}, _cfg("g-4"))

    assert out["is_followup"] is True
    assert len(get_patient_history("P001")["sessions"]) == 1


@pytest.mark.parametrize("mensaje", ["si", "sí", "yes", "no", "Sí, gracias"])
def test_respuestas_cortas_no_guardan(app, mensaje):
    _analizar(app, "P001", f"g-si-{mensaje}")
    out = app.invoke({"query": mensaje}, _cfg(f"g-si-{mensaje}"))

    assert not out.get("save_requested")
    assert get_patient_history("P001")["sessions"] == []


def test_sin_reporte_no_guarda(app):
    out = app.invoke({"save_requested": True, "query": "guardar sesión", "conversation": []}, _cfg("g-5"))
    assert out["save_result"] == {"ok": False, "error": "No hay reporte para guardar."}


def test_paciente_sin_datos_no_guarda(app):
    _analizar(app, "PX99", "g-6")
    out = app.invoke({"save_requested": True, "query": "guardar sesión"}, _cfg("g-6"))
    assert out["save_result"]["ok"] is False


def test_cancelar_no_guarda_y_avisa(app):
    _analizar(app, "P001", "g-7")
    out = app.invoke({"query": "cancelar"}, _cfg("g-7"))

    assert out["conversation"][-1]["content"] == "Guardado cancelado."
    assert get_patient_history("P001")["sessions"] == []


def test_historial_no_disponible_informa_el_error(app, monkeypatch):
    """Si el almacén falla, el médico ve el error: nunca un 'guardado' falso."""
    import tools.history_tools as ht

    class _Roto:
        def add_session(self, *a, **k):
            raise ConnectionError("sin conexión")

    monkeypatch.setattr(ht, "get_store", lambda: _Roto())
    _analizar(app, "P001", "g-8")
    out = app.invoke({"save_requested": True, "query": "guardar sesión"}, _cfg("g-8"))

    assert out["save_result"]["ok"] is False
    assert "sin conexión" in out["save_result"]["error"]
    assert "No se guardó" in out["conversation"][-1]["content"]
