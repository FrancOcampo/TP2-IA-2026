# ADR-0006 · Embeddings locales en proceso por defecto y chunking con tamaño mínimo

- **Estado:** Aceptado
- **Fecha:** 2026-09-24
- **Relacionado:** [plan MVP](../plan_mvp.md) MVP-02 · F2-06 (puntos 2 y 3) · [ADR-0005](0005-historial-en-sqlite-local.md)

## Contexto

- El RAG dependía de **Ollama** (`nomic-embed-text`) corriendo en `localhost:11434`. Sin Ollama la ingesta fallaba
  y el retriever devolvía `[]` en silencio: los reportes salían sin citas y nadie se enteraba.
- `ingest.py` y `retriever.py` duplicaban el modelo, la ruta y la colección; si divergían, los vectores eran
  incompatibles sin ningún aviso.
- Al medir la ingesta apareció un bug del chunker: si un título quedaba al principio de la ventana, el corte caía a
  pocos caracteres y el chunk siguiente avanzaba **de a 1 carácter**. Las guías producían **22 932 chunks, 89 % de
  menos de 100 caracteres** (títulos sueltos y casi duplicados). Además, el final de cada documento generaba 50
  chunks cada vez más cortos. Eso degradaba el retrieval y hacía la indexación unas 10 veces más lenta.
- `collection.add` con ids fijos hacía que re-ingestar no actualizara nada; reindexar exigía borrar la carpeta a mano.

## Decisión

1. **Embeddings locales por defecto:** el modelo ONNX `all-MiniLM-L6-v2` que trae ChromaDB (`onnxruntime` ya es
   dependencia). Corre en proceso y se descarga una vez (~80 MB). Ollama queda como opción
   (`EMBEDDING_PROVIDER=ollama`).
2. **Configuración única** en `rag/config.py`. El embedding activo se guarda en la metadata de la colección
   (`embedding`). La ingesta recrea la colección si no coincide, y el retriever lanza `RagIndexUnavailable` y loguea
   **un** error claro por proceso con el comando para arreglarlo.
3. **Chunker con tamaño mínimo por corte** (`MIN_CHUNK_SIZE = CHUNK_SIZE // 2`) y fin del loop al llegar al final del
   texto: 2450 chunks, ninguno de menos de 100 caracteres.
4. **Ingesta idempotente:** `upsert` por id estable (`fuente::chunkN`), borrado de chunks sobrantes de cada fuente y
   `--rebuild`. Metadata `section` (último título Markdown).

## Alternativas consideradas

- **Pedir Ollama como requisito** — un servicio más para instalar y mantener corriendo. Va en contra de "MVP con solo
  `uv`".
- **Modelo multilingüe (fastembed / sentence-transformers)** — probablemente mejor para guías en español, pero suma
  una dependencia (o `torch`, que es pesado). La medición de referencia con MiniLM da 9/10 consultas con fragmento
  relevante en el top-3, suficiente para el MVP. Queda como mejora medible con el mismo banco de consultas
  (`rag/RAG_TUNING.md`).
- **Embeddings de la API del LLM (Gemini)** — ata el RAG a una API key y a la red, y cada ingesta consume cuota.

## Consecuencias

- Un clon nuevo indexa con `uv run python rag/ingest.py` (~2.5 min en CPU) sin instalar nada. MVP-04 lo automatiza.
- Los índices creados antes con Ollama se detectan como incompatibles y se reindexan solos.
- MiniLM está entrenado sobre todo en inglés. Si las citas resultan pobres en la evaluación con LLM real, el primer
  cambio a probar es un modelo multilingüe.
- Los tests de ingesta son determinísticos (embedding falso en memoria). Los de retrieval real siguen siendo
  `integration` porque necesitan el índice.
