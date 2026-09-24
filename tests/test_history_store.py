# tests/test_history_store.py
#
# Contrato del almacén de historial (tools/history_store.py) sobre SQLite.
# Determinístico: cada test usa un archivo temporal (conftest.py).

import pytest

from tools.history_store import SQLiteHistoryStore, get_store


def _session(sid: str, saved_at: str, **extra) -> dict:
    return {"session_id": sid, "saved_at": saved_at, "date": saved_at[:10], **extra}


def test_paciente_inexistente_devuelve_none():
    assert get_store().get_patient("PX99") is None


def test_upsert_y_lectura_del_perfil():
    store = get_store()
    store.upsert_patient({"patient_id": "P001", "metrics_history": [{"hba1c": 6.8}], "medications": []})

    doc = store.get_patient("P001")
    assert doc == {"patient_id": "P001", "metrics_history": [{"hba1c": 6.8}], "medications": [], "sessions": []}


def test_sesiones_en_orden_cronologico():
    store = get_store()
    store.upsert_patient({"patient_id": "P002"})
    store.add_session("P002", _session("s2", "2026-09-20T10:00:00+00:00"))
    store.add_session("P002", _session("s1", "2026-09-10T10:00:00+00:00"))

    assert [s["session_id"] for s in store.get_patient("P002")["sessions"]] == ["s1", "s2"]


def test_reupsert_conserva_las_sesiones():
    """Recargar los datos (load_history) no borra lo que guardó el médico."""
    store = get_store()
    store.upsert_patient({"patient_id": "P002", "medications": []})
    store.add_session("P002", _session("s1", "2026-09-10T10:00:00+00:00"))
    store.upsert_patient({"patient_id": "P002", "medications": [{"name": "metformina"}]})

    doc = store.get_patient("P002")
    assert doc["medications"] == [{"name": "metformina"}]
    assert len(doc["sessions"]) == 1


def test_sesion_de_paciente_inexistente_falla():
    with pytest.raises(KeyError):
        get_store().add_session("PX99", _session("s1", "2026-09-10T10:00:00+00:00"))


def test_persistencia_entre_conexiones(tmp_path):
    path = tmp_path / "persist.db"
    first = SQLiteHistoryStore(path)
    first.upsert_patient({"patient_id": "P003"})
    first.add_session("P003", _session("s1", "2026-09-10T10:00:00+00:00", report_summary="texto con acentos: glucemia"))
    first.close()

    second = SQLiteHistoryStore(path)
    assert second.get_patient("P003")["sessions"][0]["report_summary"] == "texto con acentos: glucemia"
    second.close()


def test_carga_de_pacientes_de_muestra(seeded_store):
    ids = seeded_store.list_patient_ids()
    assert {"P001", "P002", "P003", "P004"} <= set(ids)
