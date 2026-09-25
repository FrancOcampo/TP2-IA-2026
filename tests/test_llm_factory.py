# tests/test_llm_factory.py
#
# Configuración del LLM (plan MVP-03 / F4-01): modelo por defecto único, alias de la
# API key de Gemini y descripción del modo de ejecución. Determinístico, no llama al LLM.

import pytest

from agents.llm_factory import DEFAULT_MODELS, active_model, has_api_key, llm_status


@pytest.fixture(autouse=True)
def _sin_config(monkeypatch):
    for var in ("LLM_PROVIDER", "LLM_MODEL", "GROQ_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(var, raising=False)


def test_default_es_el_modelo_del_articulo():
    assert active_model() == ("groq", "openai/gpt-oss-120b")


def test_llm_model_pisa_el_default(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "otro-modelo")
    assert active_model() == ("groq", "otro-modelo")


def test_gemini_acepta_gemini_api_key(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    assert not has_api_key()
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    assert has_api_key()
    assert active_model() == ("gemini", DEFAULT_MODELS["gemini"])


def test_key_de_otro_proveedor_no_cuenta(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "x")  # proveedor activo: groq
    assert not has_api_key()


def test_llm_status_explica_el_modo(monkeypatch):
    assert "GROQ_API_KEY" in llm_status() and "determinístico" in llm_status()
    monkeypatch.setenv("GROQ_API_KEY", "x")
    assert llm_status() == "LLM activo: groq · openai/gpt-oss-120b"
