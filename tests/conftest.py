"""
Se carga el archivo .env para que las variables de entorno estén disponibles durante la ejecución de los tests.
Pytest busca automáticamente este archivo en el directorio de tests antes de correr cualquier test.
"""

import os

import pytest
from dotenv import load_dotenv

from tools.history_store import get_store

load_dotenv()


@pytest.fixture(autouse=True)
def _history_store_temporal(tmp_path, monkeypatch):
    """
    Cada test usa un historial SQLite propio y vacío: nunca escribe en data/tp2.db
    ni depende de lo que haya ahí. Los tests que necesitan pacientes usan `seeded_store`.
    """
    monkeypatch.setenv("HISTORY_BACKEND", "sqlite")
    monkeypatch.setenv("HISTORY_DB_PATH", str(tmp_path / "history.db"))
    get_store.cache_clear()
    yield
    get_store().close()
    get_store.cache_clear()


@pytest.fixture
def seeded_store():
    """Historial temporal con los pacientes de data/sample/ cargados (sin sesiones)."""
    from data.load_history import load_all

    store = get_store()
    load_all(store, verbose=False)
    return store
