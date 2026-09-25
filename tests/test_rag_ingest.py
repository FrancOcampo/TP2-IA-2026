# tests/test_rag_ingest.py
#
# Ingesta y apertura del índice RAG (plan MVP-02). Determinístico: ChromaDB en memoria
# con un embedding falso (no descarga modelos ni requiere Ollama).

import chromadb
import pytest
from chromadb.api.types import EmbeddingFunction

import rag.ingest as ingest
import rag.retriever as retriever
from rag.ingest import CHUNK_SIZE, MIN_CHUNK_SIZE, build_collection, chunk_document, split_text


class _FakeEmbedding(EmbeddingFunction):
    """Vector de 8 dimensiones derivado del texto: estable y sin modelo."""

    def __init__(self):
        pass

    def __call__(self, input):
        return [[float((sum(map(ord, t)) >> i) % 7 + 1) for i in range(8)] for t in input]

    @staticmethod
    def name() -> str:
        return "fake"

    def get_config(self) -> dict:
        return {}

    @staticmethod
    def build_from_config(config: dict) -> "_FakeEmbedding":
        return _FakeEmbedding()


def _guide(n_sections: int = 30) -> str:
    """Guía sintética con títulos frecuentes: el caso que antes generaba miles de chunks."""
    return "\n".join(
        f"## Sección {i}\n\n" + ("La glucemia en ayunas se controla periódicamente. " * 8)
        for i in range(n_sections)
    )


def test_chunks_respetan_tamano_minimo_y_maximo():
    chunks = split_text(_guide())
    assert all(len(c) <= CHUNK_SIZE for c in chunks)
    # Todos salvo el último dejan al menos MIN_CHUNK_SIZE (menos el strip de espacios).
    assert all(len(c) >= MIN_CHUNK_SIZE - 5 for c in chunks[:-1])


def test_cantidad_de_chunks_proporcional_al_texto():
    """Regresión: un título al inicio de la ventana hacía avanzar de a 1 carácter."""
    text = _guide()
    assert len(split_text(text)) <= 2 * len(text) / MIN_CHUNK_SIZE


def test_el_final_del_texto_no_genera_chunks_repetidos():
    chunks = split_text(_guide())
    assert len(chunks) == len(set(chunks))


def test_texto_corto_es_un_solo_chunk():
    assert split_text("Meta de HbA1c < 7 %.") == ["Meta de HbA1c < 7 %."]


def test_chunk_document_registra_la_seccion():
    chunks = chunk_document({"source": "guia.md", "text": _guide(5)})
    assert chunks[0]["metadata"]["section"] == "Sección 0"
    assert chunks[-1]["metadata"]["section"].startswith("Sección ")
    assert chunks[0]["id"] == "guia.md::chunk0"


@pytest.fixture
def collection():
    client = chromadb.EphemeralClient()
    name = f"t{id(object())}"
    yield client.create_collection(name, embedding_function=_FakeEmbedding())
    client.delete_collection(name)


def test_reingestar_no_duplica(collection):
    docs = [{"source": "guia.md", "text": _guide()}]
    total = build_collection(docs, collection)
    build_collection(docs, collection)
    assert collection.count() == total


def test_reingestar_una_guia_mas_corta_borra_chunks_viejos(collection):
    build_collection([{"source": "guia.md", "text": _guide(30)}], collection)
    total = build_collection([{"source": "guia.md", "text": _guide(3)}], collection)
    assert collection.count() == total


def test_retriever_sin_indice_devuelve_vacio_y_avisa(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(retriever, "CHROMA_DIR", tmp_path / "no_existe")
    monkeypatch.setattr(retriever, "_warned_missing_index", False)

    assert retriever.search_clinical_guidelines("hipoglucemia") == []
    assert retriever.search_clinical_guidelines("hipoglucemia") == []
    avisos = [r for r in caplog.records if "rag/ingest.py" in r.getMessage()]
    assert len(avisos) == 1, "el error de índice faltante se loguea una sola vez"


def test_index_ready_sin_indice(tmp_path, monkeypatch):
    monkeypatch.setattr(ingest, "CHROMA_DIR", tmp_path / "no_existe")
    assert ingest.index_ready() is False


def test_guias_excluidas_no_se_cargan(tmp_path):
    (tmp_path / "ADA_2024.md").write_text("# Introducción\n\nMetodología.", encoding="utf-8")
    (tmp_path / "guia.md").write_text("# Metas\n\nHbA1c < 7 %.", encoding="utf-8")
    assert [d["source"] for d in ingest.load_markdown_files(tmp_path, verbose=False)] == ["guia.md"]


def test_huella_cambia_con_el_contenido_de_las_guias():
    a = ingest.corpus_fingerprint([{"source": "g.md", "text": "HbA1c < 7 %"}])
    b = ingest.corpus_fingerprint([{"source": "g.md", "text": "HbA1c < 8 %"}])
    assert a != b
    assert a == ingest.corpus_fingerprint([{"source": "g.md", "text": "HbA1c < 7 %"}])


def test_ingesta_quita_guias_que_ya_no_se_indexan(collection):
    build_collection([{"source": "vieja.md", "text": _guide(3)}], collection)
    docs = [{"source": "guia.md", "text": _guide(3)}]
    ingest._remove_other_sources(collection, docs)
    build_collection(docs, collection)
    fuentes = {m["source"] for m in collection.get(include=["metadatas"])["metadatas"]}
    assert fuentes == {"guia.md"}


def test_el_readme_de_la_carpeta_no_es_una_guia(tmp_path):
    (tmp_path / "README.md").write_text("# Guías\n\nDocumentación de la carpeta.", encoding="utf-8")
    (tmp_path / "guia.md").write_text("# Metas\n\nHbA1c < 7 %.", encoding="utf-8")
    assert [d["source"] for d in ingest.load_markdown_files(tmp_path, verbose=False)] == ["guia.md"]
