# Guías clínicas del RAG

`rag/ingest.py` indexa todos los `.md` de esta carpeta (salvo los de `EXCLUDED_GUIDES`). El nombre del
archivo es la fuente que citan los reportes.

| Archivo | Guía | En git |
|---|---|---|
| `Guia_SAD_2025.md` | Sociedad Argentina de Diabetes 2025 | sí |
| `guia-nacional-practica-clinica-diabetes-mellitius-tipo2_2019.md` | Guía Nacional de Práctica Clínica DM2 2019 | sí |
| `ADA_2024_S02_diagnostico.md` | ADA *Standards of Care 2024*, sección 2 | **no** (copyright de la ADA) |
| `ADA_2024_S06_metas_glucemicas_e_hipoglucemia.md` | sección 6 | **no** |
| `ADA_2024_S09_tratamiento_farmacologico.md` | sección 9 | **no** |
| `ADA_2024_S10_riesgo_cardiovascular.md` | sección 10 | **no** |
| `ADA_2024.md` | solo introducción y metodología; excluido del índice | sí |

## Cómo obtener las secciones de la ADA

Las publica gratis *Diabetes Care* (vol. 47, suplemento 1): https://diabetesjournals.org/care/issue/47/Supplement_1

1. Abrí cada artículo (secciones 2, 6, 9 y 10) y guardalo desde el navegador
   (Ctrl+S → «Página web, solo HTML»), por ejemplo en `Descargas/`.
2. Convertilo a Markdown limpio (sin menús, figuras ni lista de referencias):

   ```bash
   uv run python scripts/html_a_markdown.py "Descargas/6. Glycemic Goals….html" \
       --out data/guias/ADA_2024_S06_metas_glucemicas_e_hipoglucemia.md
   ```

3. Revisá el resultado (títulos `##`/`###`, números de recomendación) y corré `uv run python main.py`:
   la huella del corpus detecta los archivos nuevos y reindexa sola
   ([ADR-0013](../../docs/adr/0013-corpus-sin-ada-y-huella-del-indice.md)).

Sin estos archivos el sistema funciona igual: las citas salen de las otras dos guías.
