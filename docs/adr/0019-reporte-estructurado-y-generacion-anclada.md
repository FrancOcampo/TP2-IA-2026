# ADR-0019 · Reporte clínico estructurado con generación anclada (citas por id, cifras validadas)

- **Estado:** Aceptado
- **Fecha:** 2026-09-25
- **Relacionado:** F3-04 (EAS-23) · decisión D8 · [ADR-0015](0015-modo-lean-para-free-tier.md), [ADR-0017](0017-embeddings-multilingues-y-balance-de-fuentes.md)

## Contexto

La evaluación con el LLM real mostró que el reporte en texto libre inventaba cosas que ningún validador posterior
resolvía de raíz:

- **Metas inventadas:** "objetivo < 110 mg/dL", "meta HbA1c < 9 %", atribuidas a una guía que no las dice (edge_01,
  edge_02, edge_06).
- **Citas inventadas o mal atribuidas:** el LLM escribía el "fragmento citado" a mano. El validador de citas
  (texto entre comillas contra los fragmentos recuperados) detectaba unas y dejaba pasar las que no iban entre
  comillas.
- **Evaluación longitudinal sin sesión previa** y disclaimer que dependía de que el modelo lo escribiera.

## Decisión

**El LLM interpreta; el código escribe los hechos.** Generación anclada (*grounded generation*) en `agents/report.py`:

1. **Fragmentos con id.** Todo fragmento recuperado de las guías entra a un `FragmentBank` con id estable (F1, F2…),
   sea por búsqueda en código (`AGENT_MODE=lean`) o por la tool del loop ReAct (`react`, que devuelve `[F#] …`).
2. **Alertas con id.** El análisis agrupa las alertas por métrica y lado con ids A1, A2… (`alert_groups`), en orden
   estable y con las severas primero.
3. **Una llamada con salida estructurada** (`ClinicalReport`): resumen, evaluación longitudinal, y por cada grupo de
   alertas (`alert_id`) una interpretación de 1–2 oraciones con los `fragment_ids` que la respaldan. El prompt le
   prohíbe escribir metas o umbrales: el sistema los agrega.
4. **El código arma el Markdown** (`render_report`):
   - valores, períodos y umbrales de cada alerta salen de los datos determinísticos;
   - las citas se resuelven por id contra el banco (fuente + texto recuperado); un id inexistente se marca
     `⚠️ cita no verificada`;
   - las cifras con unidad (mg/dL, %) que el LLM escriba y no figuren en su contexto se marcan
     `⚠️ cifra sin respaldo en los datos` (`unsupported_values`). Es lo que delata una meta inventada;
   - los grupos que el modelo no interpretó se muestran igual, marcados;
   - la evaluación longitudinal solo se muestra si existe una sesión anterior real;
   - los datos insuficientes salen de `insufficient_data`, no del texto del modelo;
   - el disclaimer lo agrega siempre `ensure_disclaimer` (D8), también en seguimientos y en los fallbacks.
5. **Seguimiento:** conserva el loop ReAct con las tools. La respuesta pasa por el validador de citas y de cifras, y
   por `ensure_disclaimer`.
6. **Modo `lean`: 2 llamadas por análisis** (Monitor + Clínico) en lugar de 4; la búsqueda de guías, el historial y la
   comparación los hace el código. El modo `react` mantiene el loop y suma el paso estructurado final.
7. `AgentState.report_structured` (dict) guarda el `ClinicalReport`. El guardado persiste sus
   `suggested_questions` y el `execution_mode` de la corrida.

## Alternativas consideradas

- **Seguir con texto libre y más validadores** — cada validador cubre un patrón de error; el conjunto de errores
  posibles no tiene fin. Anclar por construcción elimina la clase de error.
- **Que el LLM devuelva el fragmento citado (`Citation.fragment`, como decía el plan)** — reintroduce el texto libre.
  Con el id, el texto citado sale del banco y no puede diferir de lo recuperado.
- **Validar cada afirmación con otro LLM** — costoso en tokens (el recurso escaso) y no determinístico.

## Consecuencias

- Contrato compartido modificado (`orchestrator/state.py`): `report_structured`.
- La cifra sin respaldo es una heurística sobre números con unidad: no detecta afirmaciones sin número. Lo que el
  prompt no impide, el validador no lo ve.
- Las citas se muestran truncadas a ~280 caracteres del fragmento recuperado.
- Los fragmentos de la ADA están en inglés: el reporte mezcla idiomas en las citas (ADR-0017).
- Pendiente para validar con el modelo real: cuántas cifras/citas marca el validador en las corridas de evaluación
  (depende de la cuota del proveedor).
