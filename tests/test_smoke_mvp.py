# tests/test_smoke_mvp.py
#
# Smoke test del MVP (docs/plan_mvp.md → MVP-05): el recorrido del médico en la UI, de punta a
# punta, usando los MISMOS callbacks que la interfaz Gradio (interface/app.py) sobre el grafo
# real en modo determinístico y un historial SQLite temporal (conftest.py).
#
#   bootstrap → perfil → analizar → seguimiento → guardar → nueva consulta ve la sesión guardada

import pytest

import main
import rag.ingest
from tools.history_tools import compare_with_previous_sessions


@pytest.fixture(autouse=True)
def _mvp_sin_llm(monkeypatch):
    for var in ("GROQ_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    # El índice RAG no se construye en el gate (2-3 min); su lógica tiene tests propios.
    monkeypatch.setattr(rag.ingest, "index_ready", lambda: True)
    main.bootstrap()


def test_recorrido_completo_del_medico():
    from interface import app

    # Perfil antes de analizar: viene del historial (sesiones semilla incluidas).
    perfil = app.on_patient_change("P002")
    assert "Diabetes mellitus tipo 2" in perfil
    assert "Sesiones previas**: 3" in perfil

    # Analizar
    chat, thread_id, reporte, alertas, tendencias = app.analyze("P002", "Refiere baja adherencia.")
    assert thread_id
    assert "17 alerta(s)" in chat[0]["content"]
    assert "P002" in reporte
    assert "hba1c" in alertas.lower() or "HbA1c" in alertas

    # Seguimiento: responde en el chat sin tocar el reporte del panel
    historial, caja = app.follow_up("¿Qué significa la HbA1c?", chat, thread_id)
    assert caja == ""
    assert historial[-1]["role"] == "assistant" and historial[-1]["content"]

    # "sí" en el chat no guarda nada
    historial, _ = app.follow_up("sí", historial, thread_id)
    assert compare_with_previous_sessions("P002")["sessions_count"] == 3

    # Guardar con el botón
    historial = app.save_session(thread_id, historial)
    assert "💾 Sesión guardada" in historial[-1]["content"]

    # Una consulta nueva ve la sesión recién guardada como la anterior
    comparacion = compare_with_previous_sessions("P002", current_metrics={"hba1c": 8.2})
    assert comparacion["sessions_count"] == 4
    assert comparacion["deltas"] == {"hba1c": 0.0}
    assert app.on_patient_change("P002").count("Sesiones previas**: 4") == 1


def test_paciente_inexistente_en_la_ui():
    from interface import app

    chat, _, reporte, alertas, _ = app.analyze("PX99", "")
    assert "No hay datos de EHR" in chat[0]["content"]
    assert "controlado" not in reporte.lower()
    assert "Sin análisis" in alertas


def test_guardar_sin_analisis_previo():
    from interface import app

    historial = app.save_session("", [])
    assert "No hay sesión activa" in historial[-1]["content"]


def test_cambio_de_paciente_desde_el_chat_avisa():
    """El grafo cambia de paciente (ADR-0004); la UI avisa que los paneles quedaron del anterior."""
    from interface import app

    chat, thread_id, *_ = app.analyze("P002", "")
    historial, _ = app.follow_up("analizá al paciente P003", chat, thread_id)
    assert "cambió de P002 a P003" in historial[-1]["content"]

    historial, _ = app.follow_up("¿Qué significa la HbA1c?", historial, thread_id)
    assert "cambió de" not in historial[-1]["content"]
