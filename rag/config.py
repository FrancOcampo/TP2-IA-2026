# rag/config.py
#
# Configuración compartida por la ingesta y el retrieval (antes duplicada en ambos
# módulos). Si ingest y retriever usan embeddings distintos, los vectores son
# incompatibles: por eso el proveedor se guarda en la metadata de la colección y el
# retriever lo verifica (ADR-0006).
#
#   EMBEDDING_PROVIDER=local  (default) → ONNX all-MiniLM-L6-v2 integrado en ChromaDB,
#                                         en proceso, sin servicios (se descarga ~80 MB
#                                         la primera vez en ~/.cache/chroma).
#   EMBEDDING_PROVIDER=ollama           → Ollama `nomic-embed-text` en OLLAMA_URL.

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

CHROMA_DIR = Path(__file__).resolve().parent.parent / "data" / "chroma_db"
COLLECTION_NAME = "guias_clinicas"
GUIAS_DIR = Path(__file__).resolve().parent.parent / "data" / "guias"

# TUNABLE: modelo de Ollama (solo con EMBEDDING_PROVIDER=ollama).
OLLAMA_EMBEDDING_MODEL = "nomic-embed-text"
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")


def embedding_provider() -> str:
    return os.getenv("EMBEDDING_PROVIDER", "local").lower()


def embedding_id() -> str:
    """Identificador del embedding activo; se guarda en la metadata de la colección."""
    if embedding_provider() == "ollama":
        return f"ollama:{OLLAMA_EMBEDDING_MODEL}"
    return "local:all-MiniLM-L6-v2"


def get_embedding_function():
    if embedding_provider() == "ollama":
        from chromadb.utils.embedding_functions import OllamaEmbeddingFunction

        return OllamaEmbeddingFunction(model_name=OLLAMA_EMBEDDING_MODEL, url=OLLAMA_URL)
    from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

    return DefaultEmbeddingFunction()
