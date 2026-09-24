# agents/llm_factory.py
#
# Factory de LLM intercambiable vía variable de entorno LLM_PROVIDER.
# Valores soportados: "groq" (default) | "gemini"
#
# Variables de entorno por proveedor (LLM_MODEL es opcional y pisa el default):
#   groq   → GROQ_API_KEY                     (default: DEFAULT_MODELS["groq"])
#   gemini → GOOGLE_API_KEY o GEMINI_API_KEY  (default: DEFAULT_MODELS["gemini"])
#
# Sin la API key del proveedor activo el grafo corre en modo determinístico (fallbacks).

import os
from typing import Any

# Única fuente del modelo por defecto (F4-01). El de Groq es el que declara el artículo.
DEFAULT_MODELS = {
    "groq": "llama-3.3-70b-versatile",
    "gemini": "gemma-4-31b-it",
}

# Variables aceptadas para la API key de cada proveedor, en orden de preferencia.
_API_KEY_ENV = {
    "groq": ("GROQ_API_KEY",),
    "gemini": ("GOOGLE_API_KEY", "GEMINI_API_KEY"),
}


def _provider() -> str:
    """
    Proveedor activo, leído en CADA llamada (no en tiempo de import).

    Antes era una constante `_PROVIDER = os.getenv(...)` evaluada al importar el módulo, lo
    cual era frágil: si el `load_dotenv()` del entry point corría DESPUÉS de importar este
    módulo (como pasaba en tests/eval_runner.py), el proveedor quedaba congelado en el default
    "groq" y se ignoraba `LLM_PROVIDER` del .env → el modelo de Gemini terminaba yéndose a Groq.
    """
    return os.getenv("LLM_PROVIDER", "groq").lower()


def build_llm(tools: list[Any] | None = None):
    """Construye el LLM configurado según LLM_PROVIDER y le bindea las tools dadas."""
    if _provider() == "gemini":
        return _build_gemini(tools)
    return _build_groq(tools)


def active_model() -> tuple[str, str]:
    """Proveedor y modelo activos: LLM_MODEL si está definido, si no el default del proveedor."""
    provider = _provider()
    return provider, os.getenv("LLM_MODEL") or DEFAULT_MODELS.get(provider, DEFAULT_MODELS["groq"])


def _api_key() -> str | None:
    """API key del proveedor activo (la primera variable aceptada que esté definida)."""
    for env_var in _API_KEY_ENV.get(_provider(), _API_KEY_ENV["groq"]):
        if os.environ.get(env_var):
            return os.environ[env_var]
    return None


def has_api_key() -> bool:
    """Devuelve True si la API key del proveedor activo está configurada."""
    return bool(_api_key())


def llm_status() -> str:
    """Descripción del modo de ejecución, para la UI y los logs de arranque."""
    provider, model = active_model()
    if has_api_key():
        return f"LLM activo: {provider} · {model}"
    expected = " o ".join(_API_KEY_ENV.get(provider, _API_KEY_ENV["groq"]))
    return (f"Sin API key de {provider} ({expected} en .env): los agentes corren en modo "
            "determinístico, sin LLM.")


def extract_content(response) -> str:
    """Extrae el texto de un AIMessage independientemente del proveedor.

    Groq devuelve response.content como str; Gemini como list[dict].
    """
    content = response.content or ""
    if isinstance(content, list):
        return "".join(
            p.get("text", "") if isinstance(p, dict) else str(p)
            for p in content
        )
    return content


def _build_groq(tools):
    from langchain_groq import ChatGroq

    _, model = active_model()
    llm = ChatGroq(model=model, temperature=0, api_key=_api_key())
    return llm.bind_tools(tools) if tools else llm


def _build_gemini(tools):
    from langchain_google_genai import ChatGoogleGenerativeAI

    _, model = active_model()
    llm = ChatGoogleGenerativeAI(model=model, temperature=0, google_api_key=_api_key())
    return llm.bind_tools(tools) if tools else llm
