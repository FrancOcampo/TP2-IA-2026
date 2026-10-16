# tests/test_rag_config.py
#
# Selección del embedding del RAG (ADR-0017). Determinístico: no descarga ni carga ningún modelo.

import pytest

from rag import config


@pytest.fixture(autouse=True)
def _sin_proveedor(monkeypatch):
    monkeypatch.delenv("EMBEDDING_PROVIDER", raising=False)


def test_el_default_es_multilingue():
    assert config.embedding_provider() == "multilingual"
    assert config.embedding_id() == "fastembed:paraphrase-multilingual-MiniLM-L12-v2"
    assert isinstance(config.get_embedding_function(), config.MultilingualEmbedding)


def test_los_otros_proveedores_tienen_id_propio(monkeypatch):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "local")
    assert config.embedding_id() == "local:all-MiniLM-L6-v2"
    monkeypatch.setenv("EMBEDDING_PROVIDER", "ollama")
    assert config.embedding_id() == "ollama:nomic-embed-text"


def test_el_modelo_se_carga_en_la_primera_llamada_no_al_construir():
    ef = config.MultilingualEmbedding()
    assert ef._model is None


def test_config_serializable_para_chroma():
    ef = config.MultilingualEmbedding()
    assert config.MultilingualEmbedding.build_from_config(ef.get_config()).model_name == ef.model_name
    assert config.MultilingualEmbedding.name() == "fastembed_multilingual"
