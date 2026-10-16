# rag/ingest.py
#
# Etapa 1 del pipeline RAG: lee las guías clínicas en Markdown, las divide en
# chunks, genera embeddings (locales por defecto; ver rag/config.py) y los indexa en ChromaDB.
#
# Ejecutar una vez (main.py lo hace solo si falta el índice) o cada vez que cambian las guías:
#   uv run python rag/ingest.py            # idempotente: upsert por id de chunk
#   uv run python rag/ingest.py --rebuild  # borra la colección y reindexa desde cero
#
# ══════════════════════════════════════════════════════════════
#  PARÁMETROS TUNABLES — afectan directamente la calidad del RAG
# ══════════════════════════════════════════════════════════════

import argparse
import hashlib
import re
import sys
from pathlib import Path

import chromadb

# Permite correrlo como script (`python rag/ingest.py`) además de importarlo.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rag.config import (  # noqa: E402
    CHROMA_DIR,
    COLLECTION_NAME,
    GUIAS_DIR,
    embedding_id,
    get_embedding_function,
)

# ── Modelo de embeddings ───────────────────────────────────────
# TUNABLE: se elige con EMBEDDING_PROVIDER (rag/config.py). Cambiarlo exige --rebuild:
# los vectores de modelos distintos son incompatibles.

# ── Chunking ───────────────────────────────────────────────────
# TUNABLE: chunk_size controla cuánto texto entra en cada fragmento.
#   - Más grande (1000+): más contexto por chunk, pero el embedding "diluye" el tema.
#   - Más chico (200-300): embeddings más precisos, pero puede partir conceptos.
#   Recomendado para guías médicas densas: 400-600.
CHUNK_SIZE = 500

# TUNABLE: overlap es cuántos caracteres se repiten entre chunks consecutivos.
#   - Más overlap: menos riesgo de partir definiciones, pero más redundancia en el índice.
#   - Regla práctica: 10-20% del chunk_size.
CHUNK_OVERLAP = 50

# ── Separadores de chunk ───────────────────────────────────────
# TUNABLE: el chunker intenta cortar en estos separadores (en orden de preferencia).
# Para Markdown, priorizar títulos y párrafos antes que cortar en medio de una oración.
# Agregar "\n## " o "\n### " si las guías tienen secciones bien marcadas.
SEPARATORS = ["\n## ", "\n### ", "\n\n", "\n", ". ", " "]

# Un corte en separador solo se acepta en la segunda mitad de la ventana. Sin este mínimo,
# un título al principio de la ventana producía un corte a pocos caracteres y el chunk
# siguiente avanzaba de a 1 carácter: miles de fragmentos diminutos y casi repetidos.
MIN_CHUNK_SIZE = CHUNK_SIZE // 2


# ──────────────────────────────────────────────────────────────
# Implementación
# ──────────────────────────────────────────────────────────────

# Guías que NO se indexan, con el motivo. ADA_2024.md solo tiene la introducción y la
# metodología (S1–S4): indexarla deja que el LLM la cite como respaldo de umbrales que no
# contiene (plan F2-06, ADR-0013). Se vuelve a indexar cuando tenga contenido clínico.
EXCLUDED_GUIDES = {
    "README.md": "documentación de la carpeta, no es una guía clínica",
    "ADA_2024.md": "solo introducción y metodología; sin contenido clínico (F2-06)",
}


def load_markdown_files(guias_dir: Path, verbose: bool = True) -> list[dict]:
    """Lee los .md de guias_dir que no estén en EXCLUDED_GUIDES. Devuelve lista de {source, text}."""
    docs = []
    for path in sorted(guias_dir.glob("*.md")):
        if path.name in EXCLUDED_GUIDES:
            if verbose:
                print(f"  Excluida: {path.name} ({EXCLUDED_GUIDES[path.name]})")
            continue
        text = path.read_text(encoding="utf-8").strip()
        if text:
            docs.append({"source": path.name, "text": text})
            if verbose:
                print(f"  Cargado: {path.name} ({len(text):,} caracteres)")
    return docs


def corpus_fingerprint(docs: list[dict]) -> str:
    """
    Huella del índice: guías incluidas (nombre + contenido) y parámetros de chunking. Se guarda
    en la colección; si cambia, el índice está desactualizado y `index_ready()` da False.
    """
    h = hashlib.sha256()
    h.update(repr((CHUNK_SIZE, CHUNK_OVERLAP, MIN_CHUNK_SIZE, SEPARATORS)).encode())
    for doc in sorted(docs, key=lambda d: d["source"]):
        h.update(doc["source"].encode())
        h.update(doc["text"].encode())
    return h.hexdigest()[:16]


_HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE)


def _split_spans(text: str) -> list[tuple[int, int]]:
    """
    Posiciones (inicio, fin) de cada chunk en `text`, respetando los SEPARATORS (en orden
    de preferencia). Garantiza que ningún chunk supere CHUNK_SIZE, que cada corte (salvo
    el último) deje al menos MIN_CHUNK_SIZE caracteres y que haya CHUNK_OVERLAP de solapamiento.
    """
    spans = []
    start = 0
    text_len = len(text)

    while start < text_len:
        end = min(start + CHUNK_SIZE, text_len)

        # Si no llegamos al final, retrocedemos hasta el mejor separador disponible
        if end < text_len:
            cut = end
            for sep in SEPARATORS:
                pos = text.rfind(sep, start + MIN_CHUNK_SIZE, end)
                if pos != -1:
                    cut = pos + len(sep)
                    break
            end = cut

        if text[start:end].strip():
            spans.append((start, end))
        if end >= text_len:
            break

        # El siguiente chunk empieza CHUNK_OVERLAP caracteres antes del corte
        start = max(start + 1, end - CHUNK_OVERLAP)

    return spans


def split_text(text: str) -> list[str]:
    """Divide text en chunks (ver _split_spans)."""
    return [text[a:b].strip() for a, b in _split_spans(text)]


def chunk_document(doc: dict) -> list[dict]:
    """
    Chunks de un documento con su metadata: `source`, `chunk_index` y `section` (último
    título Markdown anterior al inicio del chunk; "" si no hay). Ids estables por posición.
    """
    text = doc["text"]
    headings = [(m.start(), m.group(1)) for m in _HEADING_RE.finditer(text)]
    chunks = []
    for i, (start, end) in enumerate(_split_spans(text)):
        section = ""
        for pos, title in headings:
            if pos > start:
                break
            section = title
        chunks.append({
            "id": f"{doc['source']}::chunk{i}",
            "text": text[start:end].strip(),
            "metadata": {"source": doc["source"], "chunk_index": i, "section": section[:200]},
        })
    return chunks


def build_collection(docs: list[dict], collection: chromadb.Collection, batch_size: int = 64) -> int:
    """
    Indexa los documentos con `upsert` (re-ingestar no duplica) y borra los chunks viejos de
    cada fuente que ya no existen (p. ej. si una guía se acortó). Devuelve el total de chunks.
    """
    total = 0
    for doc in docs:
        chunks = chunk_document(doc)
        new_ids = {c["id"] for c in chunks}
        stale = [i for i in collection.get(where={"source": doc["source"]}, include=[])["ids"]
                 if i not in new_ids]
        if stale:
            collection.delete(ids=stale)
        for idx in range(0, len(chunks), batch_size):
            batch = chunks[idx: idx + batch_size]
            collection.upsert(
                ids=[c["id"] for c in batch],
                documents=[c["text"] for c in batch],
                metadatas=[c["metadata"] for c in batch],
            )
        print(f"  {doc['source']}: {len(chunks)} chunks indexados")
        total += len(chunks)
    return total


def _remove_other_sources(collection: chromadb.Collection, docs: list[dict]) -> None:
    """Borra los chunks de guías que ya no se indexan (eliminadas o excluidas)."""
    sources = [d["source"] for d in docs]
    stale = collection.get(where={"source": {"$nin": sources}}, include=[])["ids"]
    if stale:
        print(f"  Quitando {len(stale)} chunk(s) de guías que ya no se indexan.")
        collection.delete(ids=stale)


def open_collection(client, rebuild: bool = False) -> chromadb.Collection:
    """
    Abre (o crea) la colección con el embedding activo. Con `rebuild`, o si la colección
    existente se indexó con otro embedding, la borra y la recrea (vectores incompatibles).
    """
    existing = {c.name if hasattr(c, "name") else c for c in client.list_collections()}
    if COLLECTION_NAME in existing:
        current = client.get_collection(COLLECTION_NAME).metadata or {}
        if rebuild or current.get("embedding") != embedding_id():
            print(f"Borrando la colección existente (embedding: {current.get('embedding', '?')}).")
            client.delete_collection(COLLECTION_NAME)
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=get_embedding_function(),
        # TUNABLE: función de distancia entre vectores.
        # "cosine" es la más común para similitud semántica de texto.
        # Otras opciones: "l2" (distancia euclidiana), "ip" (inner product).
        metadata={"hnsw:space": "cosine", "embedding": embedding_id()},
    )


def index_ready() -> bool:
    """
    True si el índice existe, tiene chunks, usa el embedding activo y corresponde a las guías y
    parámetros actuales (`corpus_fingerprint`). Si no, hay que ingestar.
    """
    if not CHROMA_DIR.exists():
        return False
    try:
        col = chromadb.PersistentClient(path=str(CHROMA_DIR)).get_collection(COLLECTION_NAME)
        meta = col.metadata or {}
        return (
            meta.get("embedding") == embedding_id()
            and meta.get("fingerprint") == corpus_fingerprint(load_markdown_files(GUIAS_DIR, verbose=False))
            and col.count() > 0
        )
    except Exception:
        return False


def ingest(rebuild: bool = False) -> int:
    print(f"Embeddings           : {embedding_id()}")
    print(f"Chunk size / overlap : {CHUNK_SIZE} / {CHUNK_OVERLAP}")
    print(f"Guías desde          : {GUIAS_DIR}")
    print(f"ChromaDB en          : {CHROMA_DIR}\n")

    docs = load_markdown_files(GUIAS_DIR)
    if not docs:
        print("No se encontraron archivos .md en data/guias/. Abortando.")
        return 0

    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    collection = open_collection(client, rebuild=rebuild)

    print("Indexando chunks...\n")
    _remove_other_sources(collection, docs)
    total = build_collection(docs, collection)
    # La huella se registra al final: un índice a medio hacer no queda marcado como listo.
    # Chroma no admite reenviar las claves hnsw:* (la distancia queda en la configuración).
    metadata = {k: v for k, v in (collection.metadata or {}).items() if not k.startswith("hnsw:")}
    collection.modify(metadata={**metadata, "fingerprint": corpus_fingerprint(docs)})
    print(f"\nTotal chunks en la colección: {collection.count()} ({total} de esta corrida)")
    print("Ingestión completada.")
    return total


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Indexa las guías clínicas en ChromaDB.")
    parser.add_argument("--rebuild", action="store_true", help="borra la colección y reindexa desde cero")
    ingest(rebuild=parser.parse_args().rebuild)
