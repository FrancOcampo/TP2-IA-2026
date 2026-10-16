# rag/config.py
#
# Configuración compartida por la ingesta y el retrieval (antes duplicada en ambos
# módulos). Si ingest y retriever usan embeddings distintos, los vectores son
# incompatibles: por eso el proveedor se guarda en la metadata de la colección y el
# retriever lo verifica (ADR-0006).
#
#   EMBEDDING_PROVIDER=multilingual (default) → fastembed paraphrase-multilingual-MiniLM-L12-v2
#                                         (ONNX, en proceso, ~220 MB la primera vez). Necesario porque
#                                         las consultas van en español y parte del corpus está en inglés.
#   EMBEDDING_PROVIDER=local            → ONNX all-MiniLM-L6-v2 integrado en ChromaDB (solo inglés).
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


MULTILINGUAL_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


def embedding_provider() -> str:
    return os.getenv("EMBEDDING_PROVIDER", "multilingual").lower()


def embedding_id() -> str:
    """Identificador del embedding activo; se guarda en la metadata de la colección."""
    provider = embedding_provider()
    if provider == "ollama":
        return f"ollama:{OLLAMA_EMBEDDING_MODEL}"
    if provider == "local":
        return "local:all-MiniLM-L6-v2"
    return f"fastembed:{MULTILINGUAL_MODEL.split('/')[-1]}"


class MultilingualEmbedding:
    """
    Embeddings multilingües locales (fastembed, ONNX). Las consultas van en español y parte del
    corpus (ADA Standards of Care) está en inglés: con el modelo solo-inglés el retrieval
    cross-lingüe fallaba (0 de 9 consultas) y con este acierta 8 de 8 (ADR-0017).
    El modelo se carga en la primera llamada, no al construir el objeto.
    """

    def __init__(self, model_name: str = MULTILINGUAL_MODEL):
        self.model_name = model_name
        self._model = None

    def __call__(self, input):  # noqa: A002 (firma de chromadb.EmbeddingFunction)
        if self._model is None:
            from fastembed import TextEmbedding

            self._model = TextEmbedding(self.model_name)
        return [v.tolist() for v in self._model.embed(list(input), batch_size=32)]

    # Contrato de chromadb.EmbeddingFunction
    def embed_query(self, input):  # noqa: A002
        return self(input)

    @staticmethod
    def name() -> str:
        return "fastembed_multilingual"

    def get_config(self) -> dict:
        return {"model_name": self.model_name}

    @staticmethod
    def build_from_config(config: dict) -> "MultilingualEmbedding":
        return MultilingualEmbedding(config.get("model_name", MULTILINGUAL_MODEL))

    def default_space(self) -> str:
        return "cosine"

    def supported_spaces(self) -> list[str]:
        return ["cosine", "l2", "ip"]


def get_embedding_function():
    provider = embedding_provider()
    if provider == "ollama":
        from chromadb.utils.embedding_functions import OllamaEmbeddingFunction

        return OllamaEmbeddingFunction(model_name=OLLAMA_EMBEDDING_MODEL, url=OLLAMA_URL)
    if provider == "local":
        from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

        return DefaultEmbeddingFunction()
    return MultilingualEmbedding()
