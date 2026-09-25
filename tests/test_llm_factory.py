# tests/test_llm_factory.py
#
# Configuración del LLM (plan MVP-03 / F4-01): modelo por defecto único, alias de la
# API key de Gemini y descripción del modo de ejecución. Determinístico, no llama al LLM.

import pytest

from agents.llm_factory import DEFAULT_MODELS, active_model, generation_kwargs, has_api_key, llm_status


@pytest.fixture(autouse=True)
def _sin_config(monkeypatch):
    for var in ("LLM_PROVIDER", "LLM_MODEL", "GROQ_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY",
                "LLM_MAX_TOKENS", "LLM_REASONING_EFFORT", "AGENT_MODE", "LLM_FALLBACK_MODELS", "OPENROUTER_API_KEY",
                "LLM_API_KEY", "LLM_BASE_URL", "OPENROUTER_DATA_COLLECTION", "LLM_TIMEOUT_S"):
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
    assert llm.runnable.max_retries == 1, "el principal pasa rápido al respaldo"
    assert llm.fallbacks[0].max_retries > 1, "el último de la cadena espera y reintenta"

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


# ---------------- proveedores compatibles con OpenAI (ADR-0020) ----------------

def test_openrouter_es_un_proveedor_con_su_key_y_su_modelo(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    assert active_model() == ("openrouter", "deepseek/deepseek-v4-flash")
    assert not has_api_key()
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-x")
    assert has_api_key() and "openrouter" in llm_status()


def test_proveedor_desconocido_cae_en_groq(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "no-existe")
    assert active_model()[0] == "groq"


def test_openrouter_construye_el_cliente_con_privacidad_y_timeout(monkeypatch):
    from agents.llm_factory import build_llm

    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-x")
    monkeypatch.setenv("LLM_FALLBACK_MODELS", "")
    llm = build_llm()
    assert llm.model_name == "deepseek/deepseek-v4-flash"
    assert str(llm.openai_api_base).startswith("https://openrouter.ai/api/v1")
    assert llm.extra_body["provider"] == {"data_collection": "deny"}
    assert llm.request_timeout == 45.0


def test_openai_compat_usa_la_url_configurada(monkeypatch):
    from agents.llm_factory import build_llm

    monkeypatch.setenv("LLM_PROVIDER", "openai_compat")
    monkeypatch.setenv("LLM_API_KEY", "sk-x")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("LLM_MODEL", "deepseek-chat")
    llm = build_llm()
    assert llm.model_name == "deepseek-chat" and str(llm.openai_api_base) == "https://api.deepseek.com"


def test_cadena_entre_proveedores_omite_los_que_no_tienen_key(monkeypatch):
    from agents.llm_factory import build_llm, fallback_models

    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-x")
    assert fallback_models() == ["groq:openai/gpt-oss-120b"]
    assert not hasattr(build_llm(), "fallbacks"), "sin GROQ_API_KEY el respaldo de Groq se omite"

    monkeypatch.setenv("GROQ_API_KEY", "gsk_x")
    llm = build_llm()
    assert llm.runnable.model_name == "deepseek/deepseek-v4-flash"
    assert [f.model_name for f in llm.fallbacks] == ["openai/gpt-oss-120b"]


def test_los_ids_de_openrouter_con_dos_puntos_no_se_confunden_con_un_proveedor(monkeypatch):
    from agents.llm_factory import fallback_chain

    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("LLM_FALLBACK_MODELS", "deepseek/deepseek-chat:free,gemini:gemini-2.5-flash-lite")
    assert fallback_chain() == [("openrouter", "deepseek/deepseek-chat:free"), ("gemini", "gemini-2.5-flash-lite")]


def test_el_aislamiento_de_los_tests_no_deja_ningun_proveedor_de_pago():
    """Un .env con LLM_PROVIDER=openrouter y su key no debe llegar a los tests (gastarían crédito real)."""
    import os

    for var in ("LLM_PROVIDER", "OPENROUTER_API_KEY", "LLM_API_KEY", "GROQ_API_KEY", "GEMINI_API_KEY"):
        assert var not in os.environ, var
