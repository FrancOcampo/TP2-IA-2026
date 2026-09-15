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
