# agents/llm_factory.py
#
# Factory de LLM intercambiable vía variable de entorno LLM_PROVIDER.
# Proveedores: "groq" (default) | "gemini" | "openrouter" | "openai_compat" (ADR-0020).
#
# Variables de entorno por proveedor (LLM_MODEL es opcional y pisa el default):
#   groq          → GROQ_API_KEY
#   gemini        → GOOGLE_API_KEY o GEMINI_API_KEY
#   openrouter    → OPENROUTER_API_KEY   (API compatible con OpenAI; cientos de modelos)
#   openai_compat → LLM_API_KEY + LLM_BASE_URL (cualquier API compatible con OpenAI: DeepSeek, Cerebras,
#                   Mistral, OpenCode Zen, Ollama local en http://localhost:11434/v1, etc.)
#
# Cadena de respaldo entre proveedores: LLM_FALLBACK_MODELS="gemini:gemini-2.5-flash-lite,groq:openai/gpt-oss-20b"
# (cada entrada es `proveedor:modelo`; sin prefijo de proveedor conocido, es un modelo del proveedor principal).
# Las entradas de un proveedor sin API key configurada se omiten.
#
# Sin la API key del proveedor activo el grafo corre en modo determinístico (fallbacks).

import os
from typing import Any

PROVIDERS = ("groq", "gemini", "openrouter", "openai_compat")

# Única fuente del modelo por defecto (F4-01, ADR-0014). Groq dio de baja Llama 3.3 70B (el del
# artículo); gpt-oss-120b es el modelo con tool calling más capaz disponible en el free tier.
DEFAULT_MODELS = {
    "groq": "openai/gpt-oss-120b",
    "gemini": "gemini-2.5-flash-lite",
    # Modelo barato con herramientas y salida estructurada (~0,0004 USD por análisis, ADR-0020).
    "openrouter": "deepseek/deepseek-v4-flash",
    "openai_compat": "gpt-4o-mini",
}

# Cadena de respaldo (ADR-0016): si el modelo principal responde 429/413/404 (cuota diaria o por
# minuto agotada, modelo dado de baja), la llamada se reintenta con el siguiente. En Groq cada
# modelo tiene su propia cuota, así que la cadena suma presupuesto en el free tier.
# qwen/qwen3.8-27b NO va: su límite de 1000 tokens de salida por minuto no alcanza para un reporte.
DEFAULT_FALLBACK_MODELS = {
    "groq": ("openai/gpt-oss-20b",),
    "gemini": ("groq:openai/gpt-oss-20b",),
    # Si se acaba el saldo (402) o falla el proveedor: respaldo en Groq (free tier; no entrena con los datos).
    "openrouter": ("groq:openai/gpt-oss-120b",),
    "openai_compat": (),
}

# Variables aceptadas para la API key de cada proveedor, en orden de preferencia.
_API_KEY_ENV = {
    "groq": ("GROQ_API_KEY",),
    "gemini": ("GOOGLE_API_KEY", "GEMINI_API_KEY"),
    "openrouter": ("OPENROUTER_API_KEY",),
    "openai_compat": ("LLM_API_KEY",),
}

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def _provider() -> str:
    """
    Proveedor activo, leído en CADA llamada (no en tiempo de import).

    Antes era una constante `_PROVIDER = os.getenv(...)` evaluada al importar el módulo, lo
    cual era frágil: si el `load_dotenv()` del entry point corría DESPUÉS de importar este
    módulo (como pasaba en tests/eval_runner.py), el proveedor quedaba congelado en el default
    "groq" y se ignoraba `LLM_PROVIDER` del .env → el modelo de Gemini terminaba yéndose a Groq.
    """
    provider = os.getenv("LLM_PROVIDER", "groq").lower()
    return provider if provider in PROVIDERS else "groq"


def _split_entry(entry: str, default_provider: str) -> tuple[str, str]:
    """`proveedor:modelo` → (proveedor, modelo). Los ids de OpenRouter llevan ':' (p. ej. `x/y:free`), así que
    solo se separa si el prefijo es un proveedor conocido."""
    prefix, sep, rest = entry.partition(":")
    if sep and prefix in PROVIDERS:
        return prefix, rest
    return default_provider, entry


def build_llm(tools: list[Any] | None = None, structured_output: Any = None):
    """
    Construye el LLM configurado según LLM_PROVIDER, con las tools bindeadas o con salida
    estructurada (`structured_output`, un modelo Pydantic), y la cadena de respaldo de modelos
    (que puede cruzar proveedores).
    """
    provider, model = active_model()
    chain = [(provider, model)]
    for provider_b, model_b in fallback_chain():
        if (provider_b, model_b) not in chain and _api_key(provider_b):
            chain.append((provider_b, model_b))
    # Los modelos intermedios reintentan una vez para pasar rápido al respaldo; el ÚLTIMO de la
    # cadena reintenta más (respetando el retry-after del proveedor): si falla, no queda a quién
    # pasar. Sin esto, un pico de tokens/minuto en el respaldo degradaba el caso (eval edge_04).
    runnables = [
        _configure(_build(p, m, retries=1 if i < len(chain) - 1 else LAST_MODEL_RETRIES), p, tools, structured_output)
        for i, (p, m) in enumerate(chain)
    ]
    if len(runnables) == 1:
        return runnables[0]
    return runnables[0].with_fallbacks(runnables[1:], exceptions_to_handle=_fallback_exceptions())


def fallback_chain() -> list[tuple[str, str]]:
    """Respaldos como (proveedor, modelo): LLM_FALLBACK_MODELS (separados por coma; vacío = sin respaldo) o el default."""
    provider = _provider()
    env = os.getenv("LLM_FALLBACK_MODELS")
    entries = [e.strip() for e in env.split(",") if e.strip()] if env is not None else list(DEFAULT_FALLBACK_MODELS[provider])
    return [_split_entry(e, provider) for e in entries]


def fallback_models() -> list[str]:
    """Modelos de respaldo tal como se muestran (`proveedor:modelo` si cambia de proveedor)."""
    provider = _provider()
    return [m if p == provider else f"{p}:{m}" for p, m in fallback_chain()]


def _configure(llm, provider, tools, structured_output):
    if structured_output is not None:
        if provider in ("openrouter", "openai_compat"):
            # function_calling es el método que aceptan la mayoría de los modelos compatibles con OpenAI
            # (json_schema estricto solo lo soportan algunos).
            return llm.with_structured_output(structured_output, method="function_calling")
        return llm.with_structured_output(structured_output)
    return llm.bind_tools(tools) if tools else llm


def _fallback_exceptions() -> tuple[type[BaseException], ...]:
    """Errores HTTP de los proveedores (cuota, tamaño, modelo inexistente) que habilitan el respaldo."""
    found: list[type[BaseException]] = []
    for module, name in (("groq", "APIStatusError"), ("openai", "APIStatusError"),
                         ("google.api_core.exceptions", "GoogleAPICallError")):
        try:
            found.append(getattr(__import__(module, fromlist=[name]), name))
        except (ImportError, AttributeError):  # pragma: no cover
            continue
    return tuple(found) or (Exception,)


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
    return provider, os.getenv("LLM_MODEL") or DEFAULT_MODELS[provider]


def _api_key(provider: str | None = None) -> str | None:
    """API key del proveedor (por defecto el activo): la primera variable aceptada que esté definida."""
    for env_var in _API_KEY_ENV[provider or _provider()]:
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
        backups = [b for b in fallback_models() if b != model]
        return f"LLM activo: {provider} · {model}" + (f" (respaldo: {', '.join(backups)})" if backups else "")
    expected = " o ".join(_API_KEY_ENV[provider])
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


def _build(provider: str, model: str, retries: int = 1):
    if provider == "gemini":
        return _build_gemini(model, retries)
    if provider in ("openrouter", "openai_compat"):
        return _build_openai_compatible(provider, model, retries)
    return _build_groq(model, retries)


def _build_groq(model: str, retries: int = 1):
    from langchain_groq import ChatGroq

    return ChatGroq(model=model, temperature=0, api_key=_api_key("groq"), max_retries=retries,
                    **generation_kwargs(model))


def _build_gemini(model: str, retries: int = 1):
    from langchain_google_genai import ChatGoogleGenerativeAI

    return ChatGoogleGenerativeAI(model=model, temperature=0, google_api_key=_api_key("gemini"), max_retries=retries)


def _build_openai_compatible(provider: str, model: str, retries: int = 1):
    """OpenRouter u otra API compatible con OpenAI (ADR-0020), con `langchain-openai`."""
    from langchain_openai import ChatOpenAI

    kwargs: dict[str, Any] = {"max_tokens": int(os.getenv("LLM_MAX_TOKENS", "4096"))}
    extra_body: dict[str, Any] = {}
    if provider == "openrouter":
        base_url = OPENROUTER_BASE_URL
        # Privacidad: por defecto solo proveedores que no guardan ni entrenan con los datos
        # (OPENROUTER_DATA_COLLECTION=allow para ampliar la oferta de proveedores con datos sintéticos).
        extra_body["provider"] = {"data_collection": os.getenv("OPENROUTER_DATA_COLLECTION", "deny")}
        if model.startswith(_REASONING_MODEL_PREFIXES):
            extra_body["reasoning"] = {"effort": os.getenv("LLM_REASONING_EFFORT", "low")}
    else:
        base_url = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
    if extra_body:
        kwargs["extra_body"] = extra_body
    # Tiempo máximo por llamada: sin él, un proveedor lento bloquea el análisis minutos (medido: 248 s
    # en una corrida en la que otras tardaron 33 s). Al vencer, el cliente reintenta (y OpenRouter
    # puede rutear a otro proveedor).
    return ChatOpenAI(model=model, temperature=0, api_key=_api_key(provider), base_url=base_url,
                      max_retries=retries, timeout=float(os.getenv("LLM_TIMEOUT_S", "45")), **kwargs)
