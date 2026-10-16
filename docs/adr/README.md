# Architecture Decision Records (ADR)

Registro de las decisiones de arquitectura del proyecto: qué se decidió, por qué y qué consecuencias tiene.
Complementa al [plan de correcciones](../plan_correcciones.md), que dice **qué** hay que hacer; los ADR explican
**por qué** se hace de esa forma. Proceso definido en [ADR-0001](0001-registrar-decisiones-con-adr.md).

## Índice

| ADR | Título | Estado | Fecha | Relacionado |
|---|---|---|---|---|
| [0001](0001-registrar-decisiones-con-adr.md) | Registrar las decisiones de arquitectura con ADRs | Aceptado | 2026-09-15 | — |
| [0002](0002-graphify-para-navegacion-del-codigo.md) | graphify como grafo de conocimiento del proyecto, portable y acotado | Aceptado | 2026-09-15 | — |
| [0003](0003-no-inventar-valores-clinicos.md) | No inventar valores clínicos: datos faltantes explícitos y corte del flujo | Aceptado | 2026-09-15 | F1-01 / D2 · EAS-6 |
| [0004](0004-paciente-activo-y-aislamiento-de-estado.md) | El Orquestador recuerda el paciente activo y aísla el estado al cambiar | Aceptado | 2026-09-24 | F1-02 / D4 · EAS-7 |
| [0005](0005-historial-en-sqlite-local.md) | Historial de pacientes en SQLite local, detrás de una interfaz de almacén | Aceptado | 2026-09-24 | MVP-01 · F2-08 |
| [0006](0006-embeddings-locales-sin-ollama.md) | Embeddings locales en proceso por defecto y chunking con tamaño mínimo | Aceptado | 2026-09-24 | MVP-02 · F2-06 |
| [0007](0007-reporte-y-respuesta-de-seguimiento-separados.md) | El reporte de la sesión y la respuesta de seguimiento viven en campos separados | Aceptado | 2026-09-24 | F1-03 / D3 · EAS-8 |
| [0008](0008-guardado-explicito-de-sesion.md) | Guardado de sesión con señal explícita y nodo `save` que persiste | Aceptado | 2026-09-24 | F1-04 / D5 · EAS-9 |
| [0009](0009-ventana-principal-del-monitor.md) | El Monitor analiza con una ventana principal y registra llamadas, no resultados | Aceptado | 2026-09-24 | F1-05 / D7 · EAS-10 |
| [0010](0010-suficiencia-de-informacion-deterministica.md) | Suficiencia de información con un criterio determinístico sobre el análisis | Aceptado | 2026-09-24 | F1-06 / D6 · EAS-11 |
| [0011](0011-metas-de-control-dm2.md) | Alertas contra metas de control de DM2, no criterios diagnósticos | Aceptado (validado 2026-09-25) | 2026-09-24 | F2-01 / D1 · EAS-12 |
| [0012](0012-perfil-del-paciente-y-sesiones-semilla.md) | Perfil clínico del paciente, sesiones semilla y tools de historial que no lanzan | Aceptado | 2026-09-24 | F2-07 · EAS-18 |
| [0013](0013-corpus-sin-ada-y-huella-del-indice.md) | ADA fuera del corpus hasta tener contenido clínico, e índice con huella del corpus | Aceptado | 2026-09-24 | F2-06 · EAS-17 |
| [0014](0014-modelo-groq-gpt-oss.md) | Modelo por defecto `openai/gpt-oss-120b` en Groq y tools con el nombre de los prompts | Aceptado | 2026-09-25 | MVP-06 · EAS-38 |
| [0017](0017-embeddings-multilingues-y-balance-de-fuentes.md) | Embeddings multilingües locales y recuperación balanceada entre guías | Aceptado | 2026-09-25 | F2-06 · EAS-17 |
| [0018](0018-modo-de-ejecucion-visible.md) | Modo de ejecución visible: el estado registra si cada nodo usó el LLM o el fallback | Aceptado | 2026-09-25 | F3-06 parcial · EAS-25 |
| [0019](0019-reporte-estructurado-y-generacion-anclada.md) | Reporte clínico estructurado con generación anclada (citas por id, cifras validadas) | Aceptado | 2026-09-25 | F3-04 · EAS-23 |
| [0020](0020-proveedores-openai-compatibles-y-cadena-entre-proveedores.md) | Proveedores compatibles con OpenAI (OpenRouter) y cadena de respaldo entre proveedores | Aceptado | 2026-09-25 | MVP-06 · EAS-38 |
| [0015](0015-modo-lean-para-free-tier.md) | Modo `lean` de los agentes para el free tier, con `react` listo para una API paga | Aceptado | 2026-09-25 | MVP-06 · F3-05 · EAS-38/24 |
| [0016](0016-cadena-de-respaldo-de-modelos.md) | Cadena de respaldo de modelos LLM | Aceptado | 2026-09-25 | MVP-06 · EAS-38 |

## Plantilla

Copiar en `docs/adr/NNNN-slug-en-kebab-case.md` (número siguiente, sin reutilizar números):

```markdown
# ADR-NNNN · Título corto en forma de decisión

- **Estado:** Propuesto | Aceptado | Reemplazado por ADR-XXXX | Obsoleto
- **Fecha:** AAAA-MM-DD
- **Relacionado:** ítem del plan (p. ej. F1-01 / D2) · issue de Linear (EAS-N) · otros ADR

## Contexto
Qué problema o fuerza obliga a decidir. Hechos verificables (archivos, comportamiento observado).

## Decisión
Lo que se decidió, en términos concretos y verificables.

## Alternativas consideradas
- **Alternativa** — por qué no se eligió.

## Consecuencias
- Positivas, negativas y lo que queda pendiente o hay que vigilar.
```
