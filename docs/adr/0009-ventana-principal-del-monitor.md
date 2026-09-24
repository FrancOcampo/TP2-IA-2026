# ADR-0009 · El Monitor analiza con una ventana principal y registra llamadas, no resultados

- **Estado:** Aceptado
- **Fecha:** 2026-09-24
- **Relacionado:** plan F1-05 / decisión D7 · Linear EAS-10 · [ADR-0003](0003-no-inventar-valores-clinicos.md)

## Contexto

- Si el LLM del Monitor analizaba una métrica con `last_n_months=3`, `_build_analysis` completaba el resto sobre la
  serie **global**. El análisis mezclaba stats de 3 meses con alertas de todo el año.
- Las métricas "chequeadas" se deducían de las alertas obtenidas. Una detección que no daba alertas se repetía
  globalmente y aparecían alertas fuera de la ventana elegida. Llamadas repetidas duplicaban alertas.
- `insufficient_data` se evaluaba sobre la serie completa aunque el análisis fuera de un mes (pendiente anotado en
  ADR-0003).
- El LLM no recibía la consulta del médico (el template solo tenía `patient_id` y `doctor_context`), así que no
  podía elegir la ventana a partir de "analizá los últimos 3 meses".

## Decisión

1. `CollectedResults` registra las **llamadas** analíticas del LLM por `(métrica, ventana)`. Una detección vacía
   también cuenta como hecha.
2. **Ventana principal** (`MonitorAnalysis.analysis_window`): la de la primera llamada analítica, o global si el LLM
   no eligió ninguna. Todo lo que falta se completa **con esa ventana**, y `insufficient_data` y `records_count` se
   calculan sobre ella.
3. Las stats pedidas con otra ventana se guardan en `MonitorAnalysis.extra_windows` (`"métrica@ventana"`). Sus
   alertas no se suman a las principales (se loguea cuántas quedaron afuera).
4. Las alertas se deduplican por `(métrica, fecha)`: un registro no puede violar la banda alta y la baja a la vez.
   Pasará a `(métrica, fecha, lado)` cuando `Alert` tenga `side` (F2-03).
5. El fallback sin LLM usa el mismo ensamblado (ventana global). El template del Monitor incluye la consulta, y el
   prompt explica la regla de la ventana principal.

## Alternativas consideradas

- **Que el LLM declare la ventana en su respuesta final** — depende de parsear texto libre. La primera llamada es
  una señal estructurada que ya existe.
- **Guardar todas las ventanas al mismo nivel** — el Clínico y la UI no sabrían qué stats corresponden a las
  alertas.
- **Descartar las llamadas con otra ventana** — pierde información útil para comparar (p. ej. 3 meses contra el
  año) y el loop de refinamiento (F3-02) justamente pide ventanas adicionales.

## Consecuencias

- Contrato compartido modificado (`orchestrator/state.py`): `analysis_window` y `extra_windows` en `MonitorAnalysis`
  (plan §8).
- Con una ventana corta, más métricas caen en `insufficient_data`. Es lo que necesita F1-06 para decidir si ampliar
  la ventana.
- El criterio de `requires_longitudinal_comparison` sigue copiando a `requires_rag` hasta F3-03.
