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
def _sin_llm_real(request, monkeypatch):
    """
    Los tests no marcados `llm` NUNCA llaman a la API real: sin keys en el entorno y sin que un import tardío
    (p. ej. interface.app, que hace load_dotenv al importarse) las vuelva a cargar desde .env. Sin esto, un test
    que se olvidaba de simular el LLM gastaba cuota de Groq y fallaba de forma intermitente con 429.
    """
    if request.node.get_closest_marker("llm"):
        return
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
    # TODAS las variables del LLM, no solo algunas keys: el .env del desarrollador puede fijar el proveedor
    # (p. ej. LLM_PROVIDER=openrouter) y, con su key, los tests llamarían a un proveedor de pago (lento y con costo).
    for var in ("LLM_PROVIDER", "LLM_MODEL", "LLM_FALLBACK_MODELS", "LLM_BASE_URL", "LLM_API_KEY",
                "GROQ_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(var, raising=False)


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
