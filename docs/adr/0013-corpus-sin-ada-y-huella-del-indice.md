# ADR-0013 · ADA fuera del corpus hasta tener contenido clínico, e índice con huella del corpus

- **Estado:** Aceptado
- **Fecha:** 2026-09-24
- **Relacionado:** plan F2-06 (punto 1) · Linear EAS-17 · [ADR-0006](0006-embeddings-locales-sin-ollama.md), [ADR-0011](0011-metas-de-control-dm2.md)

## Contexto

- `data/guias/ADA_2024.md` tiene 39 líneas: la introducción y la metodología de los *Standards of Care 2024*
  (S1–S4). No hay umbrales, metas ni hipoglucemia.
- El prompt del Clínico ponía `[ADA_2024.md]` como ejemplo de cita. El RAG podía recuperar chunks de esa
  introducción y el LLM citarlos como respaldo de umbrales que no contienen.
- Incorporar las secciones 2, 6, 9 y 10 de los *Standards* implica copiar al repositorio texto con derechos de autor
  de la ADA. Es una decisión del equipo, no algo para resolver de oficio.
- `main.py` solo reindexaba si faltaba el índice o cambiaba el embedding. Un cambio en las guías o en el chunking
  dejaba un índice viejo marcado como listo.

## Decisión

1. `ADA_2024.md` queda **excluida de la ingesta** (`EXCLUDED_GUIDES` en `rag/ingest.py`, con motivo). El archivo se
   conserva para cuando tenga contenido clínico.
2. El prompt del Clínico solo permite citar fuentes que figuren en los fragmentos recuperados y usa
   `[Guia_SAD_2025.md]` como ejemplo.
3. **Huella del índice** (`corpus_fingerprint`): hash de las guías incluidas (nombre y contenido) y de los parámetros
   de chunking, guardado en la metadata de la colección **al terminar** la ingesta. `index_ready()` la compara, así
   que `main.py` reindexa solo cuando algo cambió. La ingesta borra los chunks de guías que ya no se indexan.

## Alternativas consideradas

- **Incorporar las secciones de ADA ahora** — pendiente de decisión del equipo por derechos de autor. Si se hace,
  alcanza con quitar la guía de `EXCLUDED_GUIDES` (la huella dispara la reindexación).
- **Borrar `ADA_2024.md`** — se pierde la referencia de qué versión de los *Standards* se tomó.
- **Reindexar en cada arranque** — 2,5 minutos por arranque sin necesidad.

## Consecuencias

- La hipoglucemia (< 70 / < 54 mg/dL) sigue citando a ADA en la tabla de umbrales (ADR-0011), pero el RAG no puede
  respaldarla: el reporte se apoya en SAD y la Guía Nacional. Queda anotado para la validación 🩺.
- El artículo debe dejar de afirmar que las alertas se contrastan con ADA mientras la guía esté excluida (F4-06).
- El criterio de aceptación de F2-06 "la query de hipoglucemia nivel 2 devuelve un fragmento de ADA" queda abierto
  hasta que se incorpore el contenido.
