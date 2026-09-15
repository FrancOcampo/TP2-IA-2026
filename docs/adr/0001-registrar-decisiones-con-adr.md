# ADR-0001 · Registrar las decisiones de arquitectura con ADRs

- **Estado:** Aceptado
- **Fecha:** 2026-09-15
- **Relacionado:** [plan de correcciones](../plan_correcciones.md) (decisiones D1–D10)

## Contexto

El proyecto pasa de un prototipo de entrega académica a una etapa de correcciones guiada por el artículo
*Articulo_JIT_2026* y por `docs/plan_correcciones.md`. Hasta ahora las decisiones de diseño quedaron dispersas
en `docs/CLAUDE.md` ("Decisiones de diseño"), en la definición conceptual y en comentarios del código, sin
fecha, sin alternativas descartadas y mezcladas con el estado de implementación. Con cuatro integrantes y un
artículo que tiene que reflejar lo implementado, hace falta saber **por qué** el sistema es como es.

## Decisión

- Cada decisión de arquitectura se registra como un ADR en `docs/adr/NNNN-slug.md`, con la plantilla de
  [README.md](README.md): contexto, decisión, alternativas y consecuencias.
- El ADR se escribe **en el mismo cambio** (rama/PR) que implementa la decisión, y se enlaza desde el ítem
  del plan y el issue de Linear correspondientes.
- Qué cuenta como decisión de arquitectura: contratos compartidos (`orchestrator/state.py`), flujo del grafo,
  separación de responsabilidades entre agentes, criterios clínicos (umbrales, clasificaciones), persistencia,
  integraciones externas y herramientas que afectan cómo trabaja todo el equipo.
- Las decisiones D1–D10 del plan se convierten en ADR a medida que se implementan.
- Los ADR no se editan para cambiar una decisión: se escribe uno nuevo y el anterior pasa a
  "Reemplazado por ADR-XXXX".

## Alternativas consideradas

- **Seguir registrando en `docs/CLAUDE.md`** — mezcla estado, guía de trabajo y decisiones; no conserva
  historia ni alternativas.
- **Solo descripciones de PR / issues de Linear** — quedan fuera del repositorio y no acompañan al código.

## Consecuencias

- Las decisiones quedan versionadas junto al código y son citables desde el artículo.
- Agrega un paso a cada cambio relevante; se mitiga con una plantilla corta.
- La sección "Decisiones de diseño" de `docs/CLAUDE.md` pasa a ser un resumen que apunta a los ADR
  (se sincroniza en F4-06).
