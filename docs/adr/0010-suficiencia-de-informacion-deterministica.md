# ADR-0010 · Suficiencia de información con un criterio determinístico sobre el análisis

- **Estado:** Aceptado
- **Fecha:** 2026-09-24
- **Relacionado:** plan F1-06 / decisión D6 · Linear EAS-11 · [ADR-0003](0003-no-inventar-valores-clinicos.md), [ADR-0009](0009-ventana-principal-del-monitor.md)

## Contexto

- El fallback del Clínico marcaba "información insuficiente" con `if patient_id == "P004" and iteration < 3`. El loop
  de refinamiento funcionaba solo para ese id.
- El Clínico real buscaba la palabra *insuficiente* en su propio texto. "Control glucémico insuficiente" disparaba
  refinamientos falsos.
- Volver al Monitor no cambiaba nada: recalculaba lo mismo hasta el guardrail de 3 vueltas.

## Decisión

1. `information_sufficient_for(analysis)` en `orchestrator/graph.py`, usado por el Clínico real y por el fallback. La
   información es insuficiente **solo si** hay métricas en `insufficient_data` **y** existe una acción de
   refinamiento posible: hoy, ampliar una `analysis_window` acotada a la serie global. Si la ventana ya es global,
   se informa con la limitación explícita.
2. El nodo Clínico fija `information_sufficient` con ese criterio. Nunca se infiere del texto del LLM, y el prompt
   ya no le pide al LLM que lo declare: le pide que explicite la limitación.
3. En el refinamiento (`iteration >= 1`), el nodo Monitor re-analiza **de forma determinística con la ventana global**
   (`_monitor_refinement`), sin volver a llamar al LLM.

## Alternativas consideradas

- **Pedirle al LLM una salida estructurada con la evaluación** — es F3-02 (`ClinicalAssessment` +
  `RefinementRequest`). Este criterio queda como fallback determinístico de esa versión.
- **Refinar siempre que haya `insufficient_data`** — con la ventana global no hay nada más que pedir. Eso
  reproduce las 3 vueltas idénticas.

## Consecuencias

- P004 se informa en una vuelta, con la limitación en el reporte. El loop de refinamiento se ejercita con una
  ventana acotada (`test_refinamiento_amplia_ventana_acotada`: 1 mes → global, `iteration == 2`).
- La única acción de refinamiento es "ampliar a global". Pedidos más finos (otra métrica, otro rango) llegan con
  F3-02.
- El guardrail de 3 iteraciones sigue igual en `decide_next`.
