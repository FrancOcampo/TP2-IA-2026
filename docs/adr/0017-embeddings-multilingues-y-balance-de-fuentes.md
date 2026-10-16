# ADR-0017 · Embeddings multilingües locales y recuperación balanceada entre guías

- **Estado:** Aceptado
- **Fecha:** 2026-09-25
- **Relacionado:** F2-06 (EAS-17) · reemplaza el embedding por defecto de [ADR-0006](0006-embeddings-locales-sin-ollama.md) · [ADR-0013](0013-corpus-sin-ada-y-huella-del-indice.md)

## Contexto

- El equipo decidió incorporar al corpus las secciones 2, 6, 9 y 10 de las *ADA Standards of Care 2024*, que están
  **en inglés**. Las consultas de los agentes van en **español** y las otras dos guías (SAD 2025 y Guía Nacional
  2019) también.
- Con el embedding por defecto (`all-MiniLM-L6-v2`, entrenado sobre todo en inglés) se midió con 9 consultas en
  español sobre el texto de la ADA indexado: **0 de 9** devolvieron un fragmento de la ADA en el top-5. Las consultas
  solo encontraban texto en español, así que el contenido nuevo era invisible.
- Además, la Guía Nacional aporta ~1.900 de los ~3.600 fragmentos y copa el top-3 que ve el agente: aun con embeddings
  multilingües, la ADA aparecía recién en los puestos 4 y 5 para hipoglucemia nivel 2, justo el umbral que cita.

## Decisión

1. **Embedding por defecto: `paraphrase-multilingual-MiniLM-L12-v2`** vía `fastembed` (ONNX, en proceso, ~220 MB la
   primera vez), como `EMBEDDING_PROVIDER=multilingual`. `local` (MiniLM-L6) y `ollama` siguen disponibles. La clase
   `MultilingualEmbedding` (`rag/config.py`) carga el modelo en la primera llamada.
2. Medición previa sobre un subconjunto (ADA S02/S06/S09 + SAD): con este modelo **8 de 8** consultas encuentran la
   sección correcta de la ADA y las consultas sobre la guía SAD siguen funcionando.
3. **Recuperación balanceada** (`_balance_sources`): se piden 4×k candidatos y se eligen los k fragmentos repartidos
   entre las guías (el mejor de cada una primero, después por rondas). Con el corpus completo, el top-3 incluye la ADA
   en 7 de 10 consultas de prueba; las otras 3 son temas que las guías en español cubren bien.
4. El índice existente se detecta como incompatible (cambió `embedding` en la metadata) y se reconstruye solo la
   primera vez que corre `main.py` o `rag/ingest.py`.

## Alternativas consideradas

- **Traducir la consulta al inglés con el LLM** — consume tokens en cada búsqueda, justo el recurso escaso en el free
  tier, y depende de la calidad de la traducción.
- **Glosario español↔inglés para expandir la consulta** — frágil y hay que mantenerlo a mano.
- **`multilingual-e5-large` (2,2 GB)** — probablemente más preciso, pero 10 veces más pesado para indexar y cargar.
  Queda como mejora si la precisión resulta insuficiente en la evaluación.
- **Traducir la ADA al español** — implica reproducir y modificar el texto con copyright; además no escala.

## Consecuencias

- Nueva dependencia: `fastembed` (usa `onnxruntime`, que ya estaba). Indexar el corpus completo tarda ~6 minutos en
  CPU la primera vez (antes ~2,5), y cada arranque carga el modelo (unos segundos).
- Los reportes pueden citar ahora fragmentos de la ADA en inglés. El validador de citas los verifica igual contra los
  fragmentos recuperados, pero el texto del reporte mezcla idiomas.
- La distancia coseno de este modelo tiene otra escala: el umbral `DISTANCE_THRESHOLD` (hoy sin filtro) se calibra
  cuando se retome F2-05.
- Los archivos de la ADA no se versionan (copyright): `data/guias/README.md` explica cómo obtenerlos y convertirlos.
