# ADR-0004 · El Orquestador recuerda el paciente activo y aísla el estado al cambiar

- **Estado:** Aceptado
- **Fecha:** 2026-09-24
- **Relacionado:** plan F1-02 / decisión D4 · Linear EAS-7 · [ADR-0003](0003-no-inventar-valores-clinicos.md)

## Contexto

- En un mismo thread se analizaba P002 y luego "Analizá al paciente P003": el sistema lo trataba como seguimiento y
  reportaba P003 con las 34 alertas de P002.
- `is_followup_message` comparaba el mensaje contra `state["patient_id"]`, pero LangGraph ya había fusionado el input
  de la invocación en el estado antes de ejecutar el nodo: el "paciente anterior" ya no estaba disponible.
- Desde el chat de la UI no viaja `patient_id`; el mensaje nombra al paciente y el estado conserva el del análisis
  previo, así que el pipeline se re-ejecutaba sobre el paciente equivocado.
- En un sistema clínico, mezclar datos de dos pacientes es un error grave (el médico puede leer alertas ajenas).

## Decisión

1. `AgentState.active_patient_id` guarda el paciente del análisis en curso. **Lo escribe solo el Orquestador.**
2. El paciente objetivo se resuelve así: id nombrado en el mensaje (`\bP\d{3,}\b`) → `patient_id` del input →
   `active_patient_id`. **El id del mensaje manda** porque en el chat `patient_id` es el del análisis anterior.
3. Si el objetivo difiere del activo (y el mensaje no es una confirmación de guardado), es un **cambio de paciente**:
   se limpian los campos derivados (`_reset_patient_scope()` en `graph.py`), `is_followup=False` y corre el pipeline
   completo. Un pedido de reinicio ("reiniciar", "nuevo análisis", "analizá de nuevo") hace lo mismo sobre el
   paciente activo.
4. `is_followup_message` deja de mirar al paciente: solo indica si hay reporte. La decisión de cambio/reinicio es del
   Orquestador, que es quien conoce el paciente activo.

## Alternativas consideradas

- **Un thread por paciente en la UI** — no cubre el chat libre ni otros clientes (`eval_runner`, API), y la protección
  quedaría fuera del grafo.
- **Guardar el paciente anterior en un campo y compararlo en el router** — es lo mismo que `active_patient_id`, pero
  sin dejar claro quién lo escribe.
- **Que `patient_id` del input siempre gane sobre el mensaje** — reintroduce el bug del chat, donde `patient_id`
  persistido es el viejo.

## Consecuencias

- Contrato compartido modificado (`orchestrator/state.py`): campo nuevo `active_patient_id` (plan §8).
- `conversation` usa el reducer `operator.add`, así que **no se limpia** al cambiar de paciente: los turnos del
  paciente anterior siguen en el historial que ve el Clínico en seguimiento. Mitigación en F3-05 (solo los últimos N
  turnos, sin reportes completos); si hace falta, un marcador de paciente por turno.
- Un mensaje que menciona a otro paciente sin intención de cambiarlo ("comparalo con P003") se toma hoy como cambio.
  Se resuelve con la clasificación estructurada del Orquestador (F3-01, `switch_patient` vs. `followup`).
- `_reset_patient_scope()` debe ampliarse cuando existan `followup_answer` (F1-03), `save_result` (F1-04) y
  `refinement_request` (F3-02).
