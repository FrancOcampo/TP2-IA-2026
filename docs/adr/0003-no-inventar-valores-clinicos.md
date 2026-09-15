# ADR-0003 · No inventar valores clínicos: datos faltantes explícitos y corte del flujo

- **Estado:** Aceptado
- **Fecha:** 2026-09-15
- **Relacionado:** plan F1-01 / decisión D2 · Linear EAS-6

## Contexto

- Analizar un paciente inexistente (`PX99`) producía *"Paciente metabólicamente controlado, sin alertas"*.
  `_build_analysis` rellenaba con `0.0` (`_empty_stats()`) toda métrica que no podía calcular, y el fallback del
  Clínico interpretaba "sin alertas" como "controlado", aunque no hubiera ni un registro.
- El mismo problema, más sutil, afectaba a pacientes con datos escasos: con un solo registro (P004) no hay
  tendencia evaluable, pero nada lo marcaba en el análisis.
- En un sistema de soporte clínico un falso "controlado" es más peligroso que un error visible: el médico puede
  tomarlo como evidencia de buen control.

## Decisión

1. **Nunca se inventan valores.** En `MonitorAnalysis` las estadísticas por métrica son `Optional[MetricStats]`:
   una métrica sin registros queda en `None`. Se elimina `_empty_stats()`.
2. **Los datos escasos se declaran.** `MonitorAnalysis.insufficient_data: dict[str, str]` (métrica → motivo) lista las
   métricas con menos de 2 registros (criterio determinístico del Monitor, `_MIN_RECORDS_FOR_TREND`), y
   `records_count` informa cuántos registros se analizaron. Los valores reales que sí existen se conservan.
3. **Sin datos del paciente, el flujo se corta.** El nodo Monitor verifica el EHR antes de analizar. Si no hay datos
   (`FileNotFoundError`) o el archivo está vacío (`ValueError`), devuelve `analysis=None` y
   `AgentState.error` con un mensaje para el médico, y la arista condicional `route_after_monitor` termina el grafo
   **sin invocar al Clínico**. El Orquestador limpia `error` en cada mensaje nuevo.
4. **La presentación no suaviza la ausencia de datos.** El fallback del Clínico no dice "controlado" si hay
   `insufficient_data`; el prompt del Clínico prohíbe completar o estimar valores; la UI muestra el error sin tabla de
   alertas y renderiza las métricas sin stats como "sin datos".

## Alternativas consideradas

- **Mantener los placeholders con un flag `is_placeholder`** — cada consumidor tendría que acordarse de mirar el flag;
  un olvido vuelve a mostrar `0.0` como dato.
- **Lanzar una excepción y dejar que la capture la UI** — el grafo no dejaría rastro en el estado ni en la
  conversación, y el modo evaluación (`eval_runner`) lo registraría como caso roto en vez de comportamiento esperado.
- **Invocar igual al Clínico y que él explique la falta de datos** — gasta una llamada al LLM para no decir nada
  útil y reintroduce el riesgo de que el modelo rellene valores.

## Consecuencias

- Contrato compartido modificado (`orchestrator/state.py`): todo consumidor de `MonitorAnalysis` debe tolerar stats
  `None` (`interface/components.py` ya lo hace).
- `tests/test_graph.py::test_pipeline_completo` usaba un paciente inexistente (`P123`) como caso feliz; pasa a `P001`.
- Riesgo transitorio en modo LLM: el Clínico real detecta "información insuficiente" buscando la palabra
  *insuficiente* en su texto (`agents/clinical.py`). Al pedirle que explicite datos insuficientes, P004 puede disparar
  el loop de refinamiento hasta el guardrail. Se resuelve en F1-06 / F3-02 (suficiencia estructurada, D6).
- El criterio de "menos de 2 registros" es global sobre la serie; cuando el Monitor use ventanas temporales
  coherentes (F1-05) debe evaluarse sobre la ventana analizada.
