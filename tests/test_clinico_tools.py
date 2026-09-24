# tests/test_clinico_tools.py
#
# Tests de las tools del Agente Clínico (historial + RAG). Ver docs/tests.md.
#
# - Historial: determinísticos, sobre un SQLite temporal cargado con data/sample/
#   (fixture `seeded_store` de conftest.py). No requieren infraestructura.
# - RAG: integración (marcador `integration`), requieren el índice de ChromaDB (rag/ingest.py).
#
# Correr en entorno completo
#   uv run pytest tests/test_clinico_tools.py

import pytest

from tools.history_tools import (
    compare_with_previous_sessions,
    get_patient_history,
    update_patient_history,
)
from rag.retriever import search_clinical_guidelines


def test_get_patient_history_con_datos(seeded_store):
    doc = get_patient_history("P001")
    assert doc["found"] is True
    assert doc.get("patient_id") == "P001"
    assert doc["metrics_history"], "el perfil incluye la serie de métricas"
    assert doc["diagnoses"][0]["code"] == "E11"
    assert doc["sessions"] == []


def test_get_patient_history_paciente_inexistente_no_lanza(seeded_store):
    """F2-07: dentro del loop ReAct una excepción tumbaba al Clínico."""
    assert get_patient_history("PX99") == {"patient_id": "PX99", "found": False, "sessions": []}


def test_sesiones_semilla_de_p002(seeded_store):
    sessions = get_patient_history("P002")["sessions"]
    assert [s["date"] for s in sessions] == ["2025-03-20", "2025-06-20", "2025-09-20"]
    assert sessions[-1]["metrics_summary"]["hba1c"] == 7.5


def test_compare_con_sesiones_semilla(seeded_store):
    result = compare_with_previous_sessions("P002", current_metrics={"hba1c": 8.2})
    assert result["sessions_count"] == 3
    assert result["deltas"] == {"hba1c": 0.7}


def test_tool_del_clinico_no_propaga_excepciones(seeded_store, monkeypatch):
    import json
    import agents.clinical as clinical

    def _roto(patient_id):
        raise ConnectionError("sin conexión")

    monkeypatch.setattr(clinical, "get_patient_history", _roto)
    out = json.loads(clinical.tool_get_patient_history.invoke({"patient_id": "P002"}))
    assert out == {"error": "sin conexión"}


def test_compare_with_previous_sessions_sin_historial(seeded_store):
    result = compare_with_previous_sessions("P004")
    assert result["previous_session"] is None
    assert result["deltas"] == {}
    assert result["sessions_count"] == 0


def test_update_y_compare_con_sesion_guardada(seeded_store):
    result = update_patient_history("P001", {
        "query": "Analizá al paciente P002", "report": "reporte", "alerts": [],
        "metrics_summary": {"hba1c": 8.2},
    })
    assert result["ok"] is True, result
    saved = get_patient_history("P001")["sessions"][-1]
    assert saved["session_id"] == result["session_id"]
    assert saved["report_summary"] == "reporte"

    comparison = compare_with_previous_sessions("P001", current_metrics={"hba1c": 7.9})
    assert comparison["sessions_count"] == 1
    assert comparison["previous_session"]["metrics_summary"] == {"hba1c": 8.2}
    assert comparison["deltas"] == {"hba1c": -0.3}


def test_update_paciente_inexistente_no_inventa_sesion(seeded_store):
    result = update_patient_history("PX99", {"report": "r"})
    assert result == {"ok": False, "error": "El paciente 'PX99' no está en el historial."}


@pytest.mark.integration
def test_search_clinical_guidelines_retorna_fragmentos():
    fragments = search_clinical_guidelines("objetivo HbA1c diabetes tipo 2", k=3)
    assert isinstance(fragments, list)
    assert len(fragments) > 0
    assert all(isinstance(f, str) for f in fragments)


@pytest.mark.integration
def test_search_clinical_guidelines_hipoglucemia():
    fragments = search_clinical_guidelines("manejo hipoglucemia nivel 1", k=2)
    assert isinstance(fragments, list)
    assert len(fragments) > 0


@pytest.mark.integration
def test_search_clinical_guidelines_incluye_fuente():
    fragments = search_clinical_guidelines("objetivo HbA1c", k=1)
    assert len(fragments) > 0
    assert fragments[0].startswith("[")
    assert ".md]" in fragments[0].split("\n")[0]
