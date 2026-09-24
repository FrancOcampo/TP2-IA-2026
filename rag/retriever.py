# rag/retriever.py
#
# Etapa 2 del pipeline RAG: dado un texto de consulta, busca en ChromaDB los
# fragmentos de guías clínicas más relevantes y los devuelve listos para inyectar
# en el prompt del Agente Clínico.
#
# Parámetros tunables documentados en rag/RAG_TUNING.md → sección "Retrieval".

import logging

import chromadb

from rag.config import CHROMA_DIR, COLLECTION_NAME, embedding_id, get_embedding_function

# TUNABLE: cuántos fragmentos devolver por consulta. Ver RAG_TUNING.md → "k (top-k)".
DEFAULT_K = 3

logger = logging.getLogger(__name__)

_MISSING_INDEX_MSG = (
    "Índice de guías clínicas no disponible ({reason}). Los reportes saldrán sin citas. "
    "Ejecutá: uv run python rag/ingest.py"
)
_warned_missing_index = False


class RagIndexUnavailable(RuntimeError):
    """El índice de ChromaDB no existe, está vacío o fue creado con otro embedding."""


def _get_collection() -> chromadb.Collection:
    """Abre la colección persistida con el embedding activo. Lanza RagIndexUnavailable si no sirve."""
    if not CHROMA_DIR.exists():
        raise RagIndexUnavailable("no existe data/chroma_db/")
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    try:
        col = client.get_collection(name=COLLECTION_NAME, embedding_function=get_embedding_function())
    except Exception as e:
        raise RagIndexUnavailable(f"no existe la colección '{COLLECTION_NAME}'") from e
    indexed_with = (col.metadata or {}).get("embedding")
    if indexed_with != embedding_id():
        raise RagIndexUnavailable(
            f"indexado con '{indexed_with}' y el embedding activo es '{embedding_id()}'; usar --rebuild"
        )
    return col


def search_clinical_guidelines(query: str, k: int = DEFAULT_K) -> list[str]:
    """
    Busca en ChromaDB los `k` fragmentos de guías clínicas más relevantes para `query`.

    Devuelve una lista de strings (los fragmentos), ordenados de mayor a menor
    similitud. Lista vacía si la colección está vacía, no hay resultados, o si
    el índice no está disponible (se loguea un error claro una vez).

    Parámetro tunable principal: `k`. Ver RAG_TUNING.md → "k (top-k)".
    """
    try:
        col = _get_collection()
        results = col.query(
            query_texts=[query],
            n_results=k,
            # TUNABLE: qué campos incluir en la respuesta. "documents" son los textos;
            # "metadatas" incluye la fuente (nombre del archivo) y el chunk_index.
            # Agregar "distances" si querés filtrar por score mínimo (ver RAG_TUNING.md).
            include=["documents", "metadatas", "distances"],
        )

        documents = results["documents"][0] if results["documents"] else []
        distances = results["distances"][0] if results["distances"] else []
        metadatas = results["metadatas"][0] if results["metadatas"] else []

        # TUNABLE: umbral de distancia coseno. Con "cosine" en ChromaDB, la distancia
        # devuelta es 1 - similitud (0 = idéntico, 2 = opuesto). Filtrar por < 0.5
        # descarta fragmentos poco relevantes. Ver RAG_TUNING.md → "Umbral de distancia".
        DISTANCE_THRESHOLD = 1.0  # 1.0 = sin filtro (acepta todo); bajar para ser más estricto

        filtered = []
        for doc, dist, meta in zip(documents, distances, metadatas):
            if dist < DISTANCE_THRESHOLD:
                source = meta.get("source", "Guía Desconocida")
                filtered.append(f"[{source}] {doc}")

        return filtered
    except RagIndexUnavailable as e:
        # Error de configuración, no transitorio: se avisa claro una sola vez por proceso.
        global _warned_missing_index
        if not _warned_missing_index:
            logger.error(_MISSING_INDEX_MSG.format(reason=e))
            _warned_missing_index = True
        return []
    except Exception as e:
        logger.warning("RAG no disponible: %s", e)
        return []


def get_rag_fragment(query: str, k: int = DEFAULT_K) -> str:
    """
    Versión formateada de search_clinical_guidelines: devuelve un único string
    listo para inyectar en el prompt del Agente Clínico.

    Formato:
        [Fragmento 1]
        <texto>

        [Fragmento 2]
        <texto>
        ...
    """
    fragments = search_clinical_guidelines(query, k=k)
    if not fragments:
        return "No se encontraron fragmentos relevantes en las guías clínicas."

    parts = [f"[Fragmento {i + 1}]\n{frag}" for i, frag in enumerate(fragments)]
    return "\n\n".join(parts)


if __name__ == "__main__":
    # Prueba rápida del retriever. Ajustar la query para evaluar calidad.
    # Ver rag/RAG_TUNING.md para saber qué parámetros tocar.
    TEST_QUERY = "manejo hipoglucemia nivel 1 diabetes tipo 2"
    print(f"Query: {TEST_QUERY}\n")
    print(get_rag_fragment(TEST_QUERY))

