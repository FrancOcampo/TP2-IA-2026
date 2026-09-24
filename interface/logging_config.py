# interface/logging_config.py
#
# Observabilidad del sistema (tarea del Integrante D).
#
# Provee dos capas complementarias de trazabilidad:
#   1. LangSmith — trazas estructuradas en la nube. Se activa automáticamente vía las
#      variables de entorno LANGSMITH_* del .env (no requiere código acá).
#   2. Logging propio — fallback exigido por la 2ª entrega. Registra cada llamada al LLM
#      (prompts y respuestas) y cada invocación a tools (input y output) en dos destinos:
#        - Consola: formato legible para humanos (demo en vivo).
#        - Archivo logs/agent.jsonl: una línea JSON por evento (machine-readable, greppeable
#          con `jq` y consumible por la pestaña de observabilidad de la UI).
#
# El logging propio se engancha al grafo mediante un BaseCallbackHandler de LangChain que
# se pasa en config={"callbacks": get_callbacks()} al invocar el grafo. Los hooks de
# chain disparan incluso con los nodos stub actuales; los de llm/tool se activan solos
# cuando A/B/C reemplacen los stubs por agentes y tools reales.

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

# -------------------------------------------------------------------
# Rutas y constantes
# -------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = PROJECT_ROOT / "logs"
LOG_FILE = LOG_DIR / "agent.jsonl"

LOGGER_NAME = "tp2"

# Longitud máxima de los campos de texto (prompts, respuestas, outputs) en los logs,
# para que las trazas no exploten con payloads enormes.
_MAX_FIELD_LEN = 2000


# -------------------------------------------------------------------
# Formatters
# -------------------------------------------------------------------

class JsonLinesFormatter(logging.Formatter):
    """Serializa cada LogRecord como una línea JSON (JSON Lines)."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "event": getattr(record, "event", "log"),
        }
        # Datos estructurados del evento, adjuntados vía extra={"data": {...}}.
        data = getattr(record, "data", None)
        if isinstance(data, dict):
            payload.update(data)
        else:
            payload["message"] = record.getMessage()
        return json.dumps(payload, ensure_ascii=False, default=str)


class HumanFormatter(logging.Formatter):
    """Formato legible de una línea para la consola."""

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.now().strftime("%H:%M:%S")
        event = getattr(record, "event", "log")
        return f"{ts} [{event}] {record.getMessage()}"


# -------------------------------------------------------------------
# Setup del logging
# -------------------------------------------------------------------

def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """
    Configura el logger 'tp2' con dos handlers (consola legible + archivo JSONL).
    Idempotente: invocarlo varias veces no duplica handlers.

    Se llama una vez en el entry point (interface/app.py). Devuelve el logger.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    # La consola de Windows usa cp1252 por defecto: sin esto los acentos salen como
    # "determin?stico" con un carácter de reemplazo (F4-04).
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level)
    logger.propagate = False  # no propagar al root para no duplicar salida

    if getattr(logger, "_tp2_configured", False):
        return logger

    console = logging.StreamHandler()
    console.setFormatter(HumanFormatter())
    logger.addHandler(console)

    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=5_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(JsonLinesFormatter())
    logger.addHandler(file_handler)

    logger._tp2_configured = True  # type: ignore[attr-defined]
    return logger


def tracing_status() -> dict[str, Any]:
    """Estado de LangSmith según las variables de entorno (para diagnóstico/UI)."""
    enabled = os.getenv("LANGSMITH_TRACING", "").lower() == "true"
    return {
        "langsmith_enabled": enabled,
        "project": os.getenv("LANGSMITH_PROJECT"),
        "has_api_key": bool(os.getenv("LANGSMITH_API_KEY")),
    }


# -------------------------------------------------------------------
# Helpers internos
# -------------------------------------------------------------------

def _truncate(value: Any) -> Any:
    """Acorta strings largos para mantener acotadas las trazas."""
    text = value if isinstance(value, str) else str(value)
    if len(text) > _MAX_FIELD_LEN:
        return text[:_MAX_FIELD_LEN] + f"... [+{len(text) - _MAX_FIELD_LEN} chars]"
    return text


def _resolve_name(serialized: dict | None, metadata: dict | None, kwargs: dict) -> str:
    """Resuelve un nombre legible para el componente (nodo de LangGraph, tool o modelo)."""
    if metadata and metadata.get("langgraph_node"):
        return str(metadata["langgraph_node"])
    if kwargs.get("name"):
        return str(kwargs["name"])
    if serialized:
        if serialized.get("name"):
            return str(serialized["name"])
        ident = serialized.get("id")
        if isinstance(ident, list) and ident:
            return str(ident[-1])
    return "unknown"


# -------------------------------------------------------------------
# Callback handler — registra LLM, tools y nodos del grafo
# -------------------------------------------------------------------

class LoggingCallbackHandler(BaseCallbackHandler):
    """
    Engancha los eventos de LangChain/LangGraph y los registra vía el logger 'tp2'.
    Cada evento sale en consola (legible) y en logs/agent.jsonl (estructurado).
    """

    def __init__(self) -> None:
        self.logger = logging.getLogger(LOGGER_NAME)

    def _emit(self, event: str, summary: str, data: dict[str, Any]) -> None:
        self.logger.info(summary, extra={"event": event, "data": {"event": event, **data}})

    # ---- LLM ----

    def on_llm_start(self, serialized, prompts, *, run_id, parent_run_id=None,
                     tags=None, metadata=None, **kwargs):
        name = _resolve_name(serialized, metadata, kwargs)
        self._emit(
            "llm_start",
            f"LLM start: {name} ({len(prompts)} prompt/s)",
            {"name": name, "run_id": str(run_id),
             "prompts": [_truncate(p) for p in prompts]},
        )

    def on_chat_model_start(self, serialized, messages, *, run_id, parent_run_id=None,
                            tags=None, metadata=None, **kwargs):
        name = _resolve_name(serialized, metadata, kwargs)
        flat = [
            {"type": m.__class__.__name__, "content": _truncate(getattr(m, "content", m))}
            for batch in messages for m in batch
        ]
        self._emit(
            "llm_start",
            f"Chat model start: {name} ({len(flat)} mensaje/s)",
            {"name": name, "run_id": str(run_id), "messages": flat},
        )

    def on_llm_end(self, response: LLMResult, *, run_id, parent_run_id=None,
                   tags=None, **kwargs):
        texts: list[str] = []
        for batch in response.generations:
            for gen in batch:
                texts.append(_truncate(getattr(gen, "text", "") or ""))
        tokens = None
        if response.llm_output and isinstance(response.llm_output, dict):
            tokens = response.llm_output.get("token_usage") or response.llm_output.get("usage")
        self._emit(
            "llm_end",
            f"LLM end ({len(texts)} respuesta/s)" + (f" · tokens={tokens}" if tokens else ""),
            {"run_id": str(run_id), "responses": texts, "tokens": tokens},
        )

    def on_llm_error(self, error, *, run_id, parent_run_id=None, tags=None, **kwargs):
        self._emit("llm_error", f"LLM error: {error}",
                   {"run_id": str(run_id), "error": str(error)})

    # ---- Tools ----

    def on_tool_start(self, serialized, input_str, *, run_id, parent_run_id=None,
                      tags=None, metadata=None, inputs=None, **kwargs):
        # Para tools queremos el nombre de la TOOL (en `serialized`/`name`), no el del nodo
        # del grafo (langgraph_node) — por eso no usamos `_resolve_name` con metadata acá.
        name = (serialized or {}).get("name") or kwargs.get("name") \
            or _resolve_name(serialized, None, kwargs)
        self._emit(
            "tool_start",
            f"Tool start: {name}",
            {"name": name, "run_id": str(run_id),
             "input": _truncate(inputs if inputs is not None else input_str)},
        )

    def on_tool_end(self, output, *, run_id, parent_run_id=None, **kwargs):
        self._emit("tool_end", "Tool end",
                   {"run_id": str(run_id), "output": _truncate(output)})

    def on_tool_error(self, error, *, run_id, parent_run_id=None, **kwargs):
        self._emit("tool_error", f"Tool error: {error}",
                   {"run_id": str(run_id), "error": str(error)})

    # ---- Chains / nodos del grafo ----

    def on_chain_start(self, serialized, inputs, *, run_id, parent_run_id=None,
                       tags=None, metadata=None, **kwargs):
        # Solo registramos chains del grafo (tienen langgraph_node en metadata), para no
        # ensuciar el log con los chains internos de LangChain.
        node = metadata.get("langgraph_node") if metadata else None
        if not node:
            return
        # Dentro de un mismo nodo, LangGraph dispara este hook para el cuerpo del nodo
        # (name == nodo) y también para su función de routing/arista condicional
        # (name == route_from_orchestrator / decide_next). Los separamos.
        name = kwargs.get("name") or node
        if name == node:
            self._emit("node_start", f"Nodo start: {node}",
                       {"name": node, "run_id": str(run_id)})
        else:
            self._emit("routing", f"Routing: {name} (nodo {node})",
                       {"name": name, "node": node, "run_id": str(run_id)})

    def on_chain_end(self, outputs, *, run_id, parent_run_id=None, **kwargs):
        # Sin metadata acá; mantenemos un registro liviano del cierre por run_id.
        return


# -------------------------------------------------------------------
# API pública
# -------------------------------------------------------------------

def get_callbacks() -> list[BaseCallbackHandler]:
    """
    Devuelve los callbacks de logging para pasar al grafo:
        app.invoke(state, config={"configurable": {...}, "callbacks": get_callbacks()})
    El tracer de LangSmith se agrega solo vía variables de entorno; no va acá.
    """
    return [LoggingCallbackHandler()]
