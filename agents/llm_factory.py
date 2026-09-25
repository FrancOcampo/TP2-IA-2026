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

# Única fuente del modelo por defecto (F4-01, ADR-0014). Groq dio de baja Llama 3.3 70B (el del
# artículo); gpt-oss-120b es el modelo con tool calling más capaz disponible en el free tier.
DEFAULT_MODELS = {
    "groq": "openai/gpt-oss-120b",
    "gemini": "gemma-4-31b-it",
}

# Cadena de respaldo (ADR-0016): si el modelo principal responde 429/413/404 (cuota diaria o por
# minuto agotada, modelo dado de baja), la llamada se reintenta con el siguiente. En Groq cada
# modelo tiene su propia cuota, así que la cadena suma presupuesto en el free tier.
# qwen/qwen3.8-27b NO va: su límite de 1000 tokens de salida por minuto no alcanza para un reporte.
DEFAULT_FALLBACK_MODELS = {
    "groq": ("openai/gpt-oss-20b",),
    "gemini": (),
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


def build_llm(tools: list[Any] | None = None, structured_output: Any = None):
    """
    Construye el LLM configurado según LLM_PROVIDER, con las tools bindeadas o con salida
    estructurada (`structured_output`, un modelo Pydantic), y la cadena de respaldo de modelos.
    """
    provider, model = active_model()
    build = _build_gemini if provider == "gemini" else _build_groq
    chain = [model] + [m for m in fallback_models() if m != model]
    # Los modelos intermedios reintentan una vez para pasar rápido al respaldo; el ÚLTIMO de la
    # cadena reintenta más (respetando el retry-after del proveedor): si falla, no queda a quién
    # pasar. Sin esto, un pico de tokens/minuto en el respaldo degradaba el caso (eval edge_04).
    runnables = [
        _configure(build(m, retries=1 if i < len(chain) - 1 else LAST_MODEL_RETRIES), tools, structured_output)
        for i, m in enumerate(chain)
    ]
    if len(runnables) == 1:
        return runnables[0]
    return runnables[0].with_fallbacks(runnables[1:], exceptions_to_handle=_fallback_exceptions())


def fallback_models() -> list[str]:
    """Modelos de respaldo: LLM_FALLBACK_MODELS (separados por coma; vacío = sin respaldo) o el default."""
    env = os.getenv("LLM_FALLBACK_MODELS")
    if env is not None:
        return [m.strip() for m in env.split(",") if m.strip()]
    return list(DEFAULT_FALLBACK_MODELS.get(_provider(), ()))


def _configure(llm, tools, structured_output):
    if structured_output is not None:
        return llm.with_structured_output(structured_output)
    return llm.bind_tools(tools) if tools else llm


def _fallback_exceptions() -> tuple[type[BaseException], ...]:
    """Errores HTTP del proveedor (cuota, tamaño, modelo inexistente) que habilitan el respaldo."""
    try:
        from groq import APIStatusError
        return (APIStatusError,)
    except ImportError:  # pragma: no cover
        return (Exception,)


def agent_mode() -> str:
    """
    Modo de los agentes (ADR-0015), leído en cada llamada:
      - "lean" (default): pocas llamadas al LLM, pensado para el free tier (8000 tokens/min).
      - "react": loops ReAct completos (Monitor y Clínico eligen todas sus tools). Requiere más
        cuota: activarlo al pasar a una API paga (AGENT_MODE=react en .env).
    """
    mode = os.getenv("AGENT_MODE", "lean").lower()
    return mode if mode in ("lean", "react") else "lean"


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
        backups = [m for m in fallback_models() if m != model]
        return f"LLM activo: {provider} · {model}" + (f" (respaldo: {', '.join(backups)})" if backups else "")
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


# Modelos de razonamiento: consumen tokens "pensando" antes de responder. Sin límite de esfuerzo,
# gpt-oss gastó los 2048 tokens por defecto en razonar y devolvió una respuesta VACÍA
# (finish_reason=length). "low" alcanza para redactar reportes y cuesta ~1/3 de tokens.
_REASONING_MODEL_PREFIXES = ("openai/gpt-oss",)


def generation_kwargs(model: str) -> dict:
    """Límite de salida y esfuerzo de razonamiento (configurables por env; ADR-0015)."""
    kwargs: dict[str, Any] = {"max_tokens": int(os.getenv("LLM_MAX_TOKENS", "4096"))}
    if model.startswith(_REASONING_MODEL_PREFIXES):
        kwargs["reasoning_effort"] = os.getenv("LLM_REASONING_EFFORT", "low")
    return kwargs


LAST_MODEL_RETRIES = 4


def _build_groq(model: str, retries: int = 1):
    from langchain_groq import ChatGroq

    return ChatGroq(model=model, temperature=0, api_key=_api_key(), max_retries=retries,
                    **generation_kwargs(model))


def _build_gemini(model: str, retries: int = 1):
    from langchain_google_genai import ChatGoogleGenerativeAI

    return ChatGoogleGenerativeAI(model=model, temperature=0, google_api_key=_api_key(), max_retries=retries)
