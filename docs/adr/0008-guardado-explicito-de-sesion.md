# ADR-0008 · Guardado de sesión con señal explícita y nodo `save` que persiste

- **Estado:** Aceptado
- **Fecha:** 2026-09-24
- **Relacionado:** plan F1-04 / decisión D5 · Linear EAS-9 · [ADR-0005](0005-historial-en-sqlite-local.md), [ADR-0007](0007-reporte-y-respuesta-de-seguimiento-separados.md)

## Contexto

- La rama `save` del grafo terminaba en `END` sin escribir nada, y la UI mostraba "Confirmación recibida".
- `_CONFIRM_WORDS` incluía "si", "sí" y "yes". En un chat clínico "sí" es una respuesta frecuente y disparaba un
  guardado; "no" cancelaba.
- `update_patient_history` devolvía `"error: …"` en el mismo campo que el id de sesión: el llamador tenía que
  adivinar si era un id o un error.
- Al guardar, `query` ya era "confirmar". La consulta que originó el reporte se había perdido.

## Decisión

1. **Señal explícita:** `AgentState.save_requested` reemplaza a `awaiting_confirmation`. El botón de la UI la envía en
   el input. Por texto solo cuentan frases inequívocas y completas ("confirmar", "guardar sesión"); "cancelar"
   termina con el aviso "Guardado cancelado." y no guarda nada.
2. **Nodo `save`** (`orchestrator → save → END`): arma `session_data` (`build_session_data`: fecha, consulta del
   análisis, contexto del médico, reporte, alertas, `metrics_summary` con el último valor de cada métrica con datos,
   comparación longitudinal) y llama a `update_patient_history`. Sin reporte o sin análisis, no guarda. Al terminar
   **apaga `save_requested`** para que la señal persistida en el checkpointer no dispare otro guardado.
3. **Resultado tipado:** `update_patient_history(patient_id, session_data) -> {"ok", "session_id"? , "error"?}`, que
   nunca lanza. El nodo lo deja en `save_result` y en un mensaje para el médico. La UI muestra ese mensaje: nunca
   dice "guardado" si no se guardó.
4. `AgentState.analysis_query` guarda la consulta que originó el análisis vigente (la escribe el Orquestador en cada
   consulta nueva). Es la que se persiste.
5. El guardado opera sobre el **paciente activo** y nunca cambia de paciente, aunque el mensaje nombre otro id.

## Alternativas consideradas

- **Mantener la confirmación por texto con una lista más corta** — sigue dependiendo de interpretar texto libre para
  una acción con efecto persistente. El botón es la vía principal; el texto queda como atajo inequívoco.
- **Que el Clínico llame a `update_patient_history` como tool** — pondría una escritura en manos del LLM, sin
  garantía de que ocurra solo con confirmación del médico.
- **Guardar la consulta desde `conversation`** — la conversación no distingue qué mensaje originó el reporte.

## Consecuencias

- Contrato compartido modificado (`orchestrator/state.py`): `awaiting_confirmation` sale; entran `save_requested`,
  `save_result` y `analysis_query` (plan §8).
- `suggested_questions` se persiste vacío hasta F3-04. `execution_mode` se suma con F3-06.
- La comparación longitudinal ya tiene datos reales: la próxima sesión del mismo paciente ve la anterior
  (`tests/test_guardado.py`).
