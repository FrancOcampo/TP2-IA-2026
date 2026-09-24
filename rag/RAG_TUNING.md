# RAG — Guía de parámetros tunables

Referencia rápida para ajustar la calidad del pipeline RAG sin tener que leer
el código. Cada parámetro indica en qué archivo vive y qué efecto produce.

**Regla general:** después de cambiar cualquier parámetro de ingestión
(`CHUNK_SIZE`, `CHUNK_OVERLAP`, `SEPARATORS`, `MIN_CHUNK_SIZE`, `EMBEDDING_PROVIDER`), correr
`uv run python rag/ingest.py --rebuild`. Sin `--rebuild` la ingesta es idempotente (upsert por id
de chunk) y borra los chunks que ya no existen; si el embedding activo no coincide con el del índice,
el índice se recrea solo y el retriever avisa en vez de devolver resultados incompatibles.
Los parámetros de retrieval (`k`, `DISTANCE_THRESHOLD`) no requieren re-ingestión.

---

## Ingestión (`rag/ingest.py`)

### `EMBEDDING_PROVIDER` (`.env`, definido en `rag/config.py`)
Modelo que convierte texto en vectores numéricos ([ADR-0006](../docs/adr/0006-embeddings-locales-sin-ollama.md)).

| Valor | Modelo | Dimensión | Cuándo usarlo |
|---|---|---|---|
| `local` (default) | ONNX `all-MiniLM-L6-v2` integrado en ChromaDB | 384 | Sin servicios; ~80 MB descargados la primera vez |
| `ollama` | `nomic-embed-text` (`OLLAMA_EMBEDDING_MODEL`) | 768 | Si hay Ollama instalado (`ollama pull nomic-embed-text`) |

Cambiar el proveedor requiere `--rebuild` (los vectores son incompatibles).

**Medición de referencia (2026-09-24, `local`):** 2450 chunks, indexado en ~2.5 min en CPU; 10 consultas
en español con palabras clave esperadas en el top-3 → 9/10 (falla "control de lípidos con estatinas").

### `MIN_CHUNK_SIZE`
Un corte en separador solo se acepta en la segunda mitad de la ventana (`CHUNK_SIZE // 2`). Antes
no había mínimo: un título al principio de la ventana generaba cortes de pocos caracteres y el
índice tenía **22 932 chunks, 89 % de menos de 100 caracteres** (hoy 2450, ninguno < 100).

### Metadata por chunk
`source` (archivo), `chunk_index` y `section` (último título Markdown anterior al chunk).

---

### `CHUNK_SIZE`
Cuántos **caracteres** entra en cada fragmento.

| Valor | Efecto |
|---|---|
| 200–300 | Fragmentos muy precisos; riesgo de partir definiciones |
| **500 (default)** | Balance entre precisión y contexto |
| 800–1000 | Más contexto por chunk; el embedding puede "diluir" el tema principal |

Para guías médicas con tablas de umbrales y criterios diagnósticos, valores entre
400 y 600 dan mejores resultados que valores extremos.

---

### `CHUNK_OVERLAP`
Cuántos caracteres se repiten entre chunks consecutivos.

| Valor | Efecto |
|---|---|
| 0 | Sin solapamiento; mayor riesgo de partir conceptos en el corte |
| **50 (default)** | ~10% del chunk; preserva la continuidad en la mayoría de los casos |
| 100–150 | Mayor redundancia en el índice; útil si los conceptos son muy densos |

Regla práctica: mantener el overlap entre el 10% y el 20% del `CHUNK_SIZE`.

---

### `SEPARATORS`
Orden de preferencia para decidir dónde cortar un chunk.

Default: `["\n## ", "\n### ", "\n\n", "\n", ". ", " "]`

El chunker intenta cortar en el primer separador que encuentra dentro del límite
de `CHUNK_SIZE`. Si las guías tienen una estructura de títulos consistente
(`## Sección`, `### Subsección`), estos separadores ya están cubiertos.

Ajustar si las guías usan otra convención (p. ej. títulos numerados `1.2.3`):
agregar el patrón como primer elemento de la lista.

---

### `hnsw:space` (función de distancia)
Define cómo ChromaDB mide la similitud entre vectores.

| Valor | Cuándo usarlo |
|---|---|
| `"cosine"` (default) | Texto: mide ángulo entre vectores, ignora magnitud |
| `"l2"` | Datos numéricos; menos adecuado para texto |
| `"ip"` | Inner product; útil con modelos entrenados con esta métrica |

Para embeddings de texto, `"cosine"` es casi siempre la mejor opción.
**Cambiar este valor requiere re-ingestión.**

---

## Retrieval (`rag/retriever.py`)

### `k` (top-k)
Cuántos fragmentos devolver por consulta.

| Valor | Efecto |
|---|---|
| 1–2 | Muy específico; puede perder contexto complementario |
| **3 (default)** | Balance estándar para la mayoría de las consultas |
| 5–6 | Más contexto; el prompt del LLM crece; puede incluir fragmentos irrelevantes |

El valor se puede ajustar por tipo de consulta: `k=2` para preguntas muy
concretas ("¿cuál es el umbral de HbA1c?"), `k=5` para consultas amplias
("¿qué dice la guía sobre el manejo integral del diabético tipo 2?").

---

### `DISTANCE_THRESHOLD`
Filtra fragmentos cuya distancia coseno supera este umbral.

Con `hnsw:space = "cosine"`, ChromaDB devuelve distancias en `[0, 2]`:
- `0` = vectores idénticos
- `1` = sin relación
- `2` = opuestos

| Valor | Efecto |
|---|---|
| `1.0` (default) | Sin filtro; acepta todos los resultados de ChromaDB |
| `0.7` | Descarta fragmentos con similitud menor al 30% |
| `0.5` | Solo fragmentos con alta similitud; puede devolver lista vacía |

Recomendación: empezar sin filtro (`1.0`) y, si el Agente Clínico recibe
fragmentos claramente irrelevantes, bajar a `0.7`.

---

## LangChain Tools (`tools/rag_tools.py`)

### `k` en `search_clinical_guidelines_tool` y `get_rag_context_tool`
Mismo parámetro que en retrieval, pero hardcodeado en la llamada al retriever.

Cambiar `k=3` por el valor deseado en cada tool según el caso de uso:
- `search_clinical_guidelines_tool`: devuelve lista; C la puede iterar.
- `get_rag_context_tool`: devuelve string formateado; más cómodo para un solo
  LLM call.

Considerar exponer `k` como parámetro de la tool si el Agente Clínico necesita
controlarlo dinámicamente según la complejidad de la consulta.

---

## Cómo evaluar si el RAG mejoró

1. Correr una consulta de prueba con `uv run python rag/retriever.py` (ver el
   bloque `__main__` del archivo).
2. Leer los fragmentos devueltos: ¿son relevantes para la pregunta?
3. Cambiar un parámetro, re-ingestar si corresponde, y repetir.
4. Cuando el sistema esté integrado, comparar reportes del Agente Clínico con
   y sin RAG para el mismo paciente.
