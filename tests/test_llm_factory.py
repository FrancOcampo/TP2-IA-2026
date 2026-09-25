# tests/test_llm_factory.py
#
# Configuración del LLM (plan MVP-03 / F4-01): modelo por defecto único, alias de la
# API key de Gemini y descripción del modo de ejecución. Determinístico, no llama al LLM.

import pytest

from agents.llm_factory import DEFAULT_MODELS, active_model, generation_kwargs, has_api_key, llm_status


@pytest.fixture(autouse=True)
def _sin_config(monkeypatch):
    for var in ("LLM_PROVIDER", "LLM_MODEL", "GROQ_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY",
                "LLM_MAX_TOKENS", "LLM_REASONING_EFFORT", "AGENT_MODE", "LLM_FALLBACK_MODELS"):
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
    assert llm_status() == "LLM activo: groq · openai/gpt-oss-120b (respaldo: openai/gpt-oss-20b)"


def test_modelos_de_razonamiento_limitan_el_esfuerzo():
    """Sin esto gpt-oss gasta todo el límite razonando y devuelve respuestas vacías."""
    assert generation_kwargs("openai/gpt-oss-120b") == {"max_tokens": 4096, "reasoning_effort": "low"}
    assert generation_kwargs("qwen/qwen3.8-27b") == {"max_tokens": 4096}


def test_modo_de_agentes_por_defecto_es_lean(monkeypatch):
    from agents.llm_factory import agent_mode

    assert agent_mode() == "lean"
    monkeypatch.setenv("AGENT_MODE", "react")
    assert agent_mode() == "react"
    monkeypatch.setenv("AGENT_MODE", "cualquiera")
    assert agent_mode() == "lean"


def test_cadena_de_respaldo_de_modelos(monkeypatch):
    from agents.llm_factory import build_llm

    monkeypatch.setenv("GROQ_API_KEY", "x")
    llm = build_llm()
    assert llm.runnable.model_name == "openai/gpt-oss-120b"
    assert [f.model_name for f in llm.fallbacks] == ["openai/gpt-oss-20b"]

    monkeypatch.setenv("LLM_FALLBACK_MODELS", "")
    assert not hasattr(build_llm(), "fallbacks"), "LLM_FALLBACK_MODELS vacío = sin respaldo"


def test_respaldo_tambien_con_tools_y_salida_estructurada(monkeypatch):
    from pydantic import BaseModel

    from agents.llm_factory import build_llm
    from agents.monitor import MONITOR_TOOLS

    class Plan(BaseModel):
        x: int

    monkeypatch.setenv("GROQ_API_KEY", "x")
    assert len(build_llm(MONITOR_TOOLS).fallbacks) == 1
    assert len(build_llm(structured_output=Plan).fallbacks) == 1
