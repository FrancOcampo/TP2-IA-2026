# tests/test_main.py
#
# Arranque del MVP (plan MVP-04): bootstrap idempotente de historial + índice.
# Determinístico: historial SQLite temporal (conftest.py) e ingesta simulada.

import main
import rag.ingest


def test_bootstrap_carga_pacientes_y_no_reindexa_si_hay_indice(monkeypatch):
    llamadas = []
    monkeypatch.setattr(rag.ingest, "index_ready", lambda: True)
    monkeypatch.setattr(rag.ingest, "ingest", lambda **kw: llamadas.append(kw))

    main.bootstrap()
    main.bootstrap()  # idempotente

    from tools.history_store import get_store
    assert {"P001", "P002", "P003", "P004"} <= set(get_store().list_patient_ids())
    assert llamadas == []


def test_bootstrap_indexa_si_falta_el_indice(monkeypatch):
    llamadas = []
    monkeypatch.setattr(rag.ingest, "index_ready", lambda: False)
    monkeypatch.setattr(rag.ingest, "ingest", lambda **kw: llamadas.append(kw))

    main.bootstrap()
    assert len(llamadas) == 1


def test_bootstrap_sin_indexar_avisa(monkeypatch, capsys):
    monkeypatch.setattr(rag.ingest, "index_ready", lambda: False)
    monkeypatch.setattr(rag.ingest, "ingest", lambda **kw: (_ for _ in ()).throw(AssertionError("no debía indexar")))

    main.bootstrap(ingest_if_missing=False)
    assert "Sin índice" in capsys.readouterr().out
