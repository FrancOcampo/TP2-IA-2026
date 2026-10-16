# ADR-0007 · El reporte de la sesión y la respuesta de seguimiento viven en campos separados

- **Estado:** Aceptado
- **Fecha:** 2026-09-24
- **Relacionado:** plan F1-03 / decisión D3 · Linear EAS-8 · [ADR-0004](0004-paciente-activo-y-aislamiento-de-estado.md)

## Contexto

- En modo seguimiento, `clinical_node` guardaba la respuesta del chat en `report`. En el segundo seguimiento el
  Clínico recibía como "reporte previo" la respuesta anterior, y "Guardar sesión" habría persistido una respuesta de
  chat en lugar del reporte.
- El fallback sin LLM regeneraba el reporte completo ante cualquier pregunta de seguimiento.
- `eval_runner` documentaba la sobrescritura como comportamiento esperado y la usaba como "salida obtenida".

## Decisión

1. `report` es el reporte de la sesión y **solo lo escribe el modo reporte**.
2. `AgentState.followup_answer` guarda la respuesta del modo seguimiento. El Orquestador lo limpia en cada mensaje
   nuevo y al cambiar de paciente (`_reset_patient_scope()`).
3. En seguimiento, el Clínico no evalúa suficiencia de información: el loop de refinamiento es solo del modo reporte.
4. `eval_runner` toma como salida `followup_answer` cuando el último mensaje fue un seguimiento (`is_followup`), y
   `report` si no.

## Alternativas consideradas

- **Guardar el reporte original aparte (`original_report`) y seguir pisando `report`** — invierte el significado del
  campo que persisten el guardado y la UI. Cada consumidor tendría que saber cuál leer.
- **Leer la respuesta solo del último mensaje de `conversation`** — funciona para la UI, pero no deja un campo
  tipado que los tests y la evaluación puedan verificar.

## Consecuencias

- Contrato compartido modificado (`orchestrator/state.py`): campo nuevo `followup_answer` (plan §8).
- La UI no cambia: el chat muestra el último mensaje del asistente y el panel de reporte usa `report`.
- Sin LLM, las preguntas de seguimiento reciben un aviso explícito en lugar de un reporte regenerado.
