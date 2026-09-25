# Plan de correcciones — fuente de verdad

> **Qué es este documento.** Es la **única fuente de verdad** para las correcciones pendientes del
> sistema: qué está mal, qué decisión se tomó, qué hay que cambiar y cómo se verifica que quedó
> resuelto. Surge de revisar el código contra el artículo [Articulo_JIT_2026.docx](Articulo_JIT_2026.docx)
> y la [definición conceptual](TP_2.1%20Definicion%20Conceptual.md) (revisión del 2026-09-15).
>
> Si un ítem de acá contradice a `estado_proyecto.md` o a `CLAUDE.md`, **manda este documento**
> hasta que el ítem se cierre y esos archivos se sincronicen (ver [§9](#9-documentación-a-sincronizar)).

---

## 0. Cómo usar este plan

**Reglas de trabajo**

1. **Test primero.** Cada bug se reproduce con un test antes de corregirlo (ver [F0-01](#f0-01--tests-de-reproducción-de-bugs)).
   El ítem se cierra cuando ese test pasa y el gate determinístico sigue en verde.
2. **Un ítem, un PR (o commit).** El título lleva el ID: `F1-02: aislar estado al cambiar de paciente`.
3. **Actualizar este archivo en el mismo cambio:** marcar el estado en la [tabla resumen](#1-tabla-resumen)
   y, si la implementación se aparta de lo escrito, corregir el ítem (la decisión nueva queda escrita acá).
4. **Contratos custodiados.** Todo cambio a `orchestrator/state.py` se lista en [§8](#8-cambios-consolidados-al-contrato-orchestratorstatepy)
   y se coordina con el grupo antes de mergear.
5. **Decisiones clínicas** (umbrales, clasificaciones) requieren que **el equipo las valide** contra las
   guías: están marcadas con 🩺.

**Estados:** ⬜ pendiente · 🟨 en curso · ✅ hecho · ⏸️ bloqueado · ❌ descartado (con motivo)

**Comando de verificación base**

```bash
uv run pytest -m "not integration and not llm"      # gate determinístico (al cerrar F1: 108 passed, 0 xfailed)
uv run pytest -m integration                         # requiere MongoDB + Ollama + ChromaDB indexado
uv run python tests/eval_runner.py                   # evaluación cualitativa con LLM real
```

---

## 1. Tabla resumen

> Seguimiento en Linear: proyecto [TP2 — Plan de correcciones](https://linear.app/easymetricdev/project/tp2-plan-de-correcciones-de9fcdcbfbd5) (workspace EasyMetrics-dev). El estado se mueve en Linear; esta tabla se sincroniza al cerrar cada fase.

| ID | Linear | Título | Severidad | Depende de | Estado |
|---|---|---|---|---|---|
| **F0-01** | [EAS-5](https://linear.app/easymetricdev/issue/EAS-5) | Tests de reproducción de bugs | — | — | ✅ |
| **F1-01** | [EAS-6](https://linear.app/easymetricdev/issue/EAS-6) | Paciente inexistente / métricas sin datos informados como "controlado" | 🔴 Crítica | F0-01 | ✅ |
| **F1-02** | [EAS-7](https://linear.app/easymetricdev/issue/EAS-7) | Contaminación de estado al cambiar de paciente en el mismo thread | 🔴 Crítica | F0-01 | ✅ |
| **F1-03** | [EAS-8](https://linear.app/easymetricdev/issue/EAS-8) | La respuesta de seguimiento sobrescribe el reporte | 🟠 Alta | F0-01 | ✅ |
| **F1-04** | [EAS-9](https://linear.app/easymetricdev/issue/EAS-9) | "Guardar sesión" no persiste; "si"/"yes" disparan guardado | 🟠 Alta | F0-01 | ✅ |
| **F1-05** | [EAS-10](https://linear.app/easymetricdev/issue/EAS-10) | Monitor mezcla ventanas temporales y duplica alertas | 🟠 Alta | F0-01 | ✅ |
| **F1-06** | [EAS-11](https://linear.app/easymetricdev/issue/EAS-11) | Suficiencia de información hardcodeada (P004) y por palabra clave | 🟠 Alta | F1-01 | ✅ |
| **F2-01** | [EAS-12](https://linear.app/easymetricdev/issue/EAS-12) | Umbrales diagnósticos usados como umbrales de control 🩺 | 🔴 Crítica | — | ✅ (validado 2026-09-25) |
| **F2-02** | [EAS-13](https://linear.app/easymetricdev/issue/EAS-13) | Umbrales de presión arterial y variación de peso 🩺 | 🟡 Media | F2-01 | ⬜ |
| **F2-03** | [EAS-14](https://linear.app/easymetricdev/issue/EAS-14) | Alertas trazables (umbral explícito) y agrupadas por episodio | 🟡 Media | F2-01 | ⬜ |
| **F2-04** | [EAS-15](https://linear.app/easymetricdev/issue/EAS-15) | `compare_with_previous_sessions` no compara ni clasifica | 🟠 Alta | F1-04 | ⬜ |
| **F2-05** | [EAS-16](https://linear.app/easymetricdev/issue/EAS-16) | `search_clinical_guidelines` sin parámetro de contexto | 🟡 Media | F2-06 | ⬜ |
| **F2-06** | [EAS-17](https://linear.app/easymetricdev/issue/EAS-17) | Corpus ADA 2024 vacío (solo introducción) + ingesta no idempotente | 🟠 Alta | — | ✅ (ADA incorporada 2026-09-25, ADR-0017) |
| **F2-07** | [EAS-18](https://linear.app/easymetricdev/issue/EAS-18) | Documento del paciente sin diagnósticos/comorbilidades; sesiones previas de ejemplo | 🟡 Media | F1-04 | ✅ |
| **F2-08** | [EAS-19](https://linear.app/easymetricdev/issue/EAS-19) | Conexiones MongoDB sin reutilizar / sin cerrar | 🟢 Baja | — | ✅ (MVP-01) |
| **F3-01** | [EAS-20](https://linear.app/easymetricdev/issue/EAS-20) | Orquestador con salida estructurada del LLM (+ nodo de aclaración) | 🟠 Alta | F1-02, F1-04 | ⬜ |
| **F3-02** | [EAS-21](https://linear.app/easymetricdev/issue/EAS-21) | Loop de refinamiento real: suficiencia estructurada + pedido concreto al Monitor | 🟠 Alta | F1-05, F1-06 | ⬜ |
| **F3-03** | [EAS-22](https://linear.app/easymetricdev/issue/EAS-22) | Flags del Monitor coherentes y notas del plan del LLM | 🟡 Media | F1-05 | ⬜ |
| **F3-04** | [EAS-23](https://linear.app/easymetricdev/issue/EAS-23) | Reporte clínico estructurado, citas validadas y disclaimer por código | 🟠 Alta | F2-05 | ✅ (ADR-0019; validación con LLM real pendiente de cuota) |
| **F3-05** | [EAS-24](https://linear.app/easymetricdev/issue/EAS-24) | Contexto del modo seguimiento compacto | 🟢 Baja | F1-03 | ✅ (adelantado al MVP, ADR-0015) |
| **F3-06** | [EAS-25](https://linear.app/easymetricdev/issue/EAS-25) | Robustez de tools y marca de modo de ejecución en el estado | 🟡 Media | — | 🟨 (`execution_mode` + aviso en la UI, ADR-0018; respuesta forzada ya hecha) |
| **F3-07** | [EAS-26](https://linear.app/easymetricdev/issue/EAS-26) | Campo "Orientación del análisis" en la UI | 🟢 Baja | F3-01 | ⬜ |
| **F4-01** | [EAS-27](https://linear.app/easymetricdev/issue/EAS-27) | Modelo por defecto alineado con el artículo | 🟢 Baja | — | ✅ (MVP-03) |
| **F4-02** | [EAS-28](https://linear.app/easymetricdev/issue/EAS-28) | Serialización de modelos Pydantic en el checkpointer | 🟡 Media | — | ⬜ |
| **F4-03** | [EAS-29](https://linear.app/easymetricdev/issue/EAS-29) | Limpieza de dependencias y `main.py` | 🟢 Baja | — | 🟨 (`main.py` y `description` en MVP-04; falta limpiar dependencias) |
| **F4-04** | [EAS-30](https://linear.app/easymetricdev/issue/EAS-30) | Codificación UTF-8 de logs en consola Windows | 🟢 Baja | — | ✅ (MVP-04) |
| **F4-05** | [EAS-31](https://linear.app/easymetricdev/issue/EAS-31) | Casos de evaluación nuevos | 🟡 Media | F1-*, F2-01 | 🟨 (edge_04, edge_06, adv_04 y expectativas actualizadas; faltan edge_05 y adv_05) |
| **F4-06** | [EAS-32](https://linear.app/easymetricdev/issue/EAS-32) | Sincronizar documentación y artículo | 🟡 Media | todo | ⬜ |

**Prioridad actual:** el [plan MVP](plan_mvp.md) define qué ítems entran al MVP y en qué orden.

**Orden sugerido:** F0 → F2-01 (cambia expectativas de muchos tests, conviene temprano) → F1-01…F1-06
→ F2-06 → resto de F2 → F3 → F4.

---

## 2. Decisiones de diseño tomadas en esta revisión

Estas decisiones guían los ítems. Revertirlas requiere discutirlas y actualizar este documento.

| # | Decisión | Motivo |
|---|---|---|
| **D1** | Las alertas se evalúan contra **metas de control para personas con DM2**, no contra criterios diagnósticos. Los criterios diagnósticos quedan como constante aparte, no usada por defecto. | Todos los pacientes del sistema ya tienen DM2; HbA1c 6.1 % es buen control, no una alerta. |
| **D2** | **Nunca se inventan valores.** Una métrica sin datos es `None` + motivo, no `0.0`. Un paciente inexistente corta el flujo con un mensaje explícito. | Dominio clínico: un falso "controlado" es peor que un error visible. |
| **D3** | `report` es el reporte de la sesión y **solo lo escribe el modo reporte**. Las respuestas de seguimiento van a `followup_answer`. | El reporte es lo que se persiste y lo que el seguimiento consulta. |
| **D4** | El estado recuerda el **paciente activo** (`active_patient_id`). Si cambia, el Orquestador limpia los campos derivados y ejecuta el pipeline completo. | Aislar pacientes dentro de un mismo thread. |
| **D5** | La confirmación de guardado es una **señal explícita** (`save_requested=True` desde el botón) o un texto inequívoco (`confirmar`, `guardar sesión`). "si", "sí", "yes" y "no" dejan de ser comandos. | "Sí" es una respuesta frecuente en un chat clínico. |
| **D6** | La suficiencia de información es **estructurada** (`ClinicalAssessment`), nunca inferida de palabras del texto. El refinamiento lleva un **pedido concreto** (`RefinementRequest`) que el Monitor ejecuta. | Sin pedido concreto, volver al Monitor recalcula lo mismo. |
| **D7** | Un análisis del Monitor tiene **una ventana principal** (`analysis_window`); todo lo que se complete de forma determinística usa esa misma ventana. | Coherencia entre stats y alertas. |
| **D8** | El **disclaimer lo agrega el código** al renderizar cualquier salida clínica (reporte, seguimiento, fallback). El prompt puede mencionarlo, pero no depende de él. | El artículo afirma que está "en toda salida". |
| **D9** | Cada `Alert` sigue siendo **una observación** (trazabilidad, Figura 3 del artículo) y además lleva el umbral y el lado. La agrupación en episodios es una **vista derivada** para UI y prompt. | Trazabilidad + legibilidad. |
| **D10** | El Orquestador decide por **salida estructurada del LLM** con la heurística como fallback determinístico (mismo patrón de degradación que Monitor/Clínico). | Trabajo futuro del artículo; mantiene el modo básico. |

---

## 3. Fase 0 — Preparación

### F0-01 · Tests de reproducción de bugs

**Objetivo.** Dejar un test por bug de Fase 1 que hoy falle, marcado `@pytest.mark.xfail(strict=True, raises=AssertionError, reason="F1-0X")`.
`raises=AssertionError` asegura que el test falla por la aserción del bug y no por otra excepción.
Al corregir el ítem se quita el `xfail`: `strict=True` obliga a hacerlo (un xfail que pasa rompe la suite).

**Archivo nuevo:** `tests/test_regresiones.py` (modo determinístico, mismo fixture `_force_fallback` que `test_graph.py`).

**Tests a escribir**

| Test | Reproduce | Aserción |
|---|---|---|
| `test_paciente_inexistente_no_reporta_controlado` | F1-01 | `PX99` → `report` no contiene "controlado"; hay un mensaje de "no hay datos"; `analysis is None` |
| `test_cambio_de_paciente_limpia_estado` | F1-02 | Thread con P002 → invocar `{patient_id: "P003", query: "Analizá al paciente P003"}` → `is_followup is False` y el análisis es de P003 (mínimo de ayunas 55) |
| `test_cambio_de_paciente_desde_el_chat` | F1-02 | Igual, pero desde el chat sin `patient_id` ("analizá al paciente P003") |
| `test_seguimiento_no_pisa_reporte` | F1-03 | `report` antes y después de un seguimiento es idéntico; la respuesta está en `followup_answer` |
| `test_si_no_dispara_guardado` | F1-04 | Tras un reporte, `query: "si"` → `awaiting_confirmation`/`save_requested` es False |
| `test_guardar_persiste` (determinístico, con mock) | F1-04 | `save_requested=True` → `update_patient_history` fue llamado (mock) con reporte, alertas y `metrics_summary` |
| `test_monitor_no_duplica_alertas` | F1-05 | LLM falso con tool calls repetidas sobre la misma métrica → sin alertas duplicadas por `(metric, date, value)` |
| `test_monitor_respeta_ventana_elegida` | F1-05 | LLM falso que analiza `hba1c` con 3 meses → ninguna alerta fuera de esa ventana |
| `test_suficiencia_no_depende_del_id` | F1-06 | Un CSV temporal con 1 fila y otro id (vía `data_dir`) se comporta igual que P004 |

**Criterio de aceptación:** `uv run pytest -m "not integration and not llm"` → todo verde, con los nuevos tests en `xfailed`.

- [x] Hecho (2026-09-15): `45 passed, 9 deselected, 9 xfailed`. Verificado con `--runxfail` que cada test falla por la aserción de su bug.

---

## 4. Fase 1 — Correctitud

### F1-01 · Paciente inexistente / métricas sin datos informados como "controlado"

**Problema.** `PX99` produce *"Paciente metabólicamente controlado, sin alertas"*.

**Evidencia**
- [agents/monitor.py:326](../agents/monitor.py#L326) y `_empty_stats()` rellenan con `0.0` las métricas sin datos.
- [orchestrator/graph.py:173-179](../orchestrator/graph.py#L173): el fallback del Clínico dice "controlado" si no hay alertas, aunque no haya datos.
- [agents/monitor.py:80](../agents/monitor.py#L80): `tool_load_patient_data` captura `FileNotFoundError` pero no el `ValueError` de CSV vacío ([patient_tools.py:73](../tools/patient_tools.py#L73)).

**Cambios**
1. `state.py` (ver §8): los campos `*_stats` de `MonitorAnalysis` pasan a `Optional[MetricStats]`; se agrega
   `insufficient_data: dict[str, str]` (métrica → motivo, p. ej. `"1 registro; se requieren ≥ 2 para tendencia"`)
   y `records_count: int`.
2. `AgentState`: nuevo `error: Optional[str]` (error de dominio visible para el médico).
3. `monitor_node` / `_monitor_fallback`: si `load_patient_data` lanza `FileNotFoundError` o `ValueError`,
   devolver `analysis=None` y `error="No hay datos de EHR para el paciente 'PX99'."`. Eliminar `_empty_stats()`.
4. Grafo: arista condicional después de `monitor`: si `state["error"]` → `END` (no se invoca al Clínico).
5. Criterio de datos insuficientes (determinístico, en el Monitor): métrica con **< 2 registros** en la ventana → entra en `insufficient_data`.
6. `_clinical_fallback`: nunca afirmar "controlado" si hay métricas en `insufficient_data` o `analysis is None`.
7. UI (`interface/app.py::analyze`, `components.format_report/trends_view`): mostrar `error` y renderizar métricas `None` como "sin datos".

**Archivos:** `orchestrator/state.py`, `orchestrator/graph.py`, `agents/monitor.py`, `interface/app.py`, `interface/components.py`, tests.

**Aceptación**
- [x] `test_paciente_inexistente_no_reporta_controlado` pasa sin `xfail` (+ `test_paciente_inexistente_no_invoca_al_clinico`).
- [x] P004 → `analysis.insufficient_data` contiene las 6 métricas; ninguna stat es `0.0` inventada (`test_datos_insuficientes_explicitos_p004`).
- [x] En la UI, `PX99` muestra "No hay datos de EHR…" y no muestra tabla de alertas (`app.analyze`; `test_ui_metricas_sin_datos_se_muestran_como_sin_datos`).
- [ ] Caso `adv_03` del eval: el reporte no contiene métricas (requiere corrida con LLM real).

**Decisión registrada:** [ADR-0003](adr/0003-no-inventar-valores-clinicos.md). Además de lo previsto, `MonitorAnalysis.blood_pressure_stats` pasa a tener `systolic`/`diastolic` opcionales y `test_graph.py::test_pipeline_completo` deja de usar un paciente inexistente (`P123` → `P001`).

---

### F1-02 · Contaminación de estado al cambiar de paciente en el mismo thread

**Problema.** Se analiza P002 y luego, en el mismo thread, "Analizá al paciente P003": el sistema lo toma como
seguimiento y reporta P003 con las 34 alertas de P002.

**Evidencia.** [orchestrator/router.py:29](../orchestrator/router.py#L29) compara contra `state["patient_id"]`, que LangGraph
ya actualizó con el input nuevo antes de ejecutar el nodo. En el chat de la UI (sin `patient_id`), "analizá al
paciente P003" no es seguimiento pero re-ejecuta el pipeline sobre **P002**.

**Cambios**
1. `AgentState`: nuevo `active_patient_id: Optional[str]` (lo escribe **solo** el Orquestador).
2. `orchestrator_node`:
   - Resolver el paciente objetivo: `state["patient_id"]` o, si el mensaje menciona un id (regex `\bP\d{3,}\b`), ese id.
   - Si `objetivo != active_patient_id` → **cambio de paciente**: devolver `patient_id=objetivo`,
     `active_patient_id=objetivo` y **limpiar** `analysis`, `report`, `followup_answer`, `longitudinal_comparison`,
     `rag_context`, `refinement_request`, `error`, `save_result`; `is_followup=False`.
   - Intención **reiniciar** ("reiniciar", "nuevo análisis", "analizá de nuevo"): limpiar igual y re-ejecutar el pipeline sobre el paciente activo.
3. La limpieza vive en una única función `_reset_patient_scope()` en `graph.py` (reutilizada por F3-01).

**Aceptación**
- [x] `test_cambio_de_paciente_limpia_estado` pasa sin `xfail`.
- [x] `test_cambio_de_paciente_desde_el_chat`: en un thread con P002, `query="analizá al paciente P003"` sin `patient_id` → análisis de P003.
- [x] `test_reiniciar_vuelve_a_correr_el_pipeline`: "reiniciar el análisis" → `iteration == 1` y el Monitor corre de nuevo.

**Decisión registrada:** [ADR-0004](adr/0004-paciente-activo-y-aislamiento-de-estado.md). El id nombrado en el mensaje tiene prioridad sobre `patient_id`; `_reset_patient_scope()` hoy limpia solo los campos existentes (`followup_answer`, `save_result` y `refinement_request` se suman en F1-03, F1-04 y F3-02).

---

### F1-03 · La respuesta de seguimiento sobrescribe el reporte

**Problema.** En modo real, `clinical_node` guarda la respuesta del chat en `report`. Al segundo seguimiento el
Clínico recibe como "reporte previo" la respuesta anterior, y "Guardar sesión" persistiría una respuesta de chat.

**Evidencia.** [agents/clinical.py:189-196](../agents/clinical.py#L189) escribe `report` en ambos modos;
[tests/eval_runner.py:126-128](../tests/eval_runner.py#L126) documenta ese comportamiento como si fuera intencional.

**Cambios**
1. `AgentState`: nuevo `followup_answer: Optional[str]`.
2. `run_clinical_agent` en modo seguimiento: escribir `followup_answer`, **no** `report`; no evaluar `information_sufficient`.
3. `_clinical_fallback` en seguimiento: responder en `followup_answer` (hoy regenera el reporte).
4. `eval_runner._run_case`: `obtained = followup_answer si el caso tiene setup, si no report`.
5. UI: sin cambios funcionales (usa el último mensaje de `conversation`), pero verificar que el panel de reporte no cambia al chatear.

**Decisión registrada:** [ADR-0007](adr/0007-reporte-y-respuesta-de-seguimiento-separados.md).

**Aceptación**
- [x] `test_seguimiento_no_pisa_reporte` pasa (determinístico) y hay un test `llm` equivalente (`test_graph.py::test_seguimiento_estocastico_no_pisa_reporte`).
- [x] `eval_runner` registra `followup_answer` como `obtained` cuando el último mensaje es un seguimiento (`is_followup`), no según tenga `setup`: un caso futuro con setup puede ser un cambio de paciente. Falta confirmarlo en una corrida de `happy_03` con LLM real.

**Implementado además:** el Orquestador limpia `followup_answer` en cada mensaje y en `_reset_patient_scope()`. Sin LLM, el fallback responde el seguimiento con un aviso en `followup_answer` en vez de regenerar el reporte.

---

### F1-04 · "Guardar sesión" no persiste; "si"/"yes" disparan guardado

**Problema.** La rama `save` termina en `END` sin escribir. `_CONFIRM_WORDS` incluye "si", "sí" y "yes".

**Evidencia.** [orchestrator/graph.py:259](../orchestrator/graph.py#L259), [orchestrator/router.py:9](../orchestrator/router.py#L9),
[interface/app.py:142-159](../interface/app.py#L142), [tools/mongo_tools.py:190-192](../tools/mongo_tools.py#L190) (devuelve `"error: …"` como si fuera un id).

**Cambios**
1. `AgentState`: `awaiting_confirmation` se reemplaza por `save_requested: bool` (input explícito) y se agrega `save_result: Optional[dict]`.
2. `router.py`: `_CONFIRM_WORDS = {"confirmar", "guardar sesión", "guardar sesion"}`; eliminar "si/sí/yes/no". `_CANCEL_WORDS` se usa para devolver "Guardado cancelado".
3. Nuevo nodo `save_node` en `graph.py`:
   - Precondición: existe `report` y `analysis`; si no → `save_result={"ok": False, "error": "No hay reporte para guardar"}`.
   - Arma `session_data` (definición conceptual §2.6, Tool 9): `date`, `query`, `doctor_context`, `report`,
     `alerts` (dicts), `metrics_summary` (`last_value` de cada métrica con datos), `longitudinal_comparison`,
     `suggested_questions` (vacío hasta F3-04), `execution_mode` (F3-06).
   - Llama a `update_patient_history` → `orchestrator → save → END`.
4. `mongo_tools.update_patient_history(patient_id, session_data: dict) -> dict`: devuelve `{"ok": bool, "session_id"?: str, "error"?: str}`, sin strings mágicos.
5. UI `save_session`: invocar con `{"save_requested": True}` y mostrar el resultado real (id o error, p. ej. "MongoDB no disponible").

**Aceptación**
- [x] `test_si_no_dispara_guardado` pasa.
- [x] `test_guardar_persiste` (con `update_patient_history` mockeado) verifica el contenido de `session_data`.
- [x] Tras guardar, `get_patient_history(pid)["sessions"][-1]["metrics_summary"]` tiene los `last_value`. Ya no requiere infraestructura: `tests/test_guardado.py` corre contra un SQLite temporal (MVP-01).
- [x] Si el historial falla, el médico ve el error y nunca "guardado" (`test_historial_no_disponible_informa_el_error`).
- [x] `test_confirmacion_termina_sin_agentes` actualizado a la nueva señal.

**Decisión registrada:** [ADR-0008](adr/0008-guardado-explicito-de-sesion.md). Además de lo previsto, se agregó `AgentState.analysis_query`: al guardar, `query` ya es "guardar sesión" y se perdía la consulta que originó el reporte. "cancelar" termina con un aviso sin nodo propio.

---

### F1-05 · Monitor mezcla ventanas temporales y duplica alertas

**Problema.** Si el LLM analiza con `last_n_months=3`, `_build_analysis` completa lo faltante sobre la serie **global**.
Las métricas "chequeadas" se deducen de las alertas obtenidas, así que una métrica chequeada sin alertas se vuelve a
chequear globalmente y aparecen alertas fuera de la ventana. Llamadas repetidas duplican alertas.

**Evidencia.** [agents/monitor.py:320-339](../agents/monitor.py#L320) (`checked_alert_metrics = {a.metric for a in collected_alerts}`),
[agents/monitor.py:292-301](../agents/monitor.py#L292).

**Cambios**
1. `_track_tool_result` registra **llamadas** (`checked: set[tuple[metric, window_key]]`), no resultados.
2. `analysis_window: TimeRange` = ventana de la primera llamada analítica del LLM (o global si no eligió). Se guarda en `MonitorAnalysis.analysis_window` (§8).
3. Completar métricas faltantes **con `analysis_window`**. Llamadas con otra ventana se conservan en `MonitorAnalysis.extra_windows: dict[str, MetricStats]` (clave `"metric@window"`), sin mezclarse con las principales.
4. Deduplicar alertas por `(metric, date, side)`.
5. `_monitor_fallback` delega en la misma función de ensamblado (hoy duplica la lógica en [graph.py:97-116](../orchestrator/graph.py#L97)).

**Aceptación**
- [x] `test_monitor_no_duplica_alertas` y `test_monitor_respeta_ventana_elegida` pasan sin `xfail`.
- [x] Test unitario de `_build_analysis`: LLM pidió `hba1c` con 3 meses → alertas de `glucose_fasting` completadas también con 3 meses (`tests/test_monitor_ensamblado.py`).

**Decisión registrada:** [ADR-0009](adr/0009-ventana-principal-del-monitor.md). Diferencias con lo previsto: se deduplica por `(metric, date)` hasta que `Alert` tenga `side` (F2-03); `insufficient_data` y `records_count` pasan a evaluarse sobre la ventana; el template del Monitor ahora recibe la `query` (antes no llegaba al LLM).

---

### F1-06 · Suficiencia de información hardcodeada (P004) y por palabra clave

**Problema.**
- Fallback: `if patient_id == "P004" and iteration < 3` ([graph.py:169](../orchestrator/graph.py#L169)). El loop "funciona" solo para ese id.
- LLM real: `"insuficiente" in final_content.lower()` ([clinical.py:184](../agents/clinical.py#L184)). "control glucémico insuficiente" dispara refinamientos falsos.
- Volver al Monitor recalcula lo mismo: 3 vueltas idénticas.

**Cambios (parte determinística; la parte LLM está en F3-02)**
1. Eliminar la comparación por id y la detección por palabra clave.
2. Regla determinística en el fallback: `information_sufficient = False` **solo si** hay `insufficient_data` **y** existe
   una acción de refinamiento posible (hoy: la ventana no es global → ampliar a global). Si la ventana ya es global,
   no hay nada más que pedir: `information_sufficient=True` y el reporte **explicita la limitación**.
3. `decide_next`: sin cambios de firma; el guardrail de 3 sigue igual.
4. Reescribir `test_refinamiento_loop_insuficiente`: P004 (ya global) → `iteration == 1` y el reporte menciona datos
   insuficientes. Nuevo test del loop real: P002 con `last_n_months=1` y consulta de tendencia → refina a global → `iteration == 2`.

**Aceptación**
- [x] `test_suficiencia_no_depende_del_id` pasa.
- [x] Tests del loop reescritos y en verde (`test_refinamiento_loop_insuficiente`: P004 → `iteration == 1`; `test_refinamiento_amplia_ventana_acotada`: P002 con 1 mes → global, `iteration == 2`).
- [x] `grep -n "P004" orchestrator agents` no devuelve nada.

**Decisión registrada:** [ADR-0010](adr/0010-suficiencia-de-informacion-deterministica.md). El criterio también se aplica al Clínico real (se eliminó la detección por palabra clave) y el refinamiento del Monitor es determinístico (ventana global, sin LLM).

---

## 5. Fase 2 — Coherencia clínica

### F2-01 · Umbrales diagnósticos usados como umbrales de control 🩺

**Problema.** `ADA_THRESHOLDS` usa **criterios diagnósticos** (HbA1c ≥ 5.7 prediabetes / ≥ 6.5 diabetes; ayunas
100/126; 2 h poscarga 140/200). Aplicados a pacientes con DM2 generan alertas clínicamente incorrectas:
P003 (HbA1c 6.1, buen control) produce 12 alertas "moderadas"; P002 produce 34.

**Evidencia.** [tools/threshold_tools.py:40-55](../tools/threshold_tools.py#L40).

**Decisión (D1) — tabla propuesta de metas de control, a validar por el equipo 🩺**

| Métrica | Meta | Alerta moderada | Alerta severa | Fuente en el corpus |
|---|---|---|---|---|
| HbA1c (%) | < 7.0 (individualizable) | ≥ 7.0 | > 9.0 | SAD 2025 (metas <7 %); Guía Nacional 2019 ("adición de insulina si HbA1c > 9 %", línea ~5047) |
| Glucosa en ayunas (mg/dL) | 80–130 | > 130 | > 300 | SAD 2025 ("glucemias matinales entre 80 y 130 mg/dl", ~4112; "glucemias > 300 mg/dl y/o HbA1c > 10 %", ~3360) |
| Glucosa postprandial (mg/dL) | < 180 | ≥ 180 | > 300 | SAD 2025 ("hasta lograr glucemias < 180 mg/dl", ~4122) |
| Hipoglucemia (ayunas/postprandial) | ≥ 70 | < 70 (nivel 1) | < 54 (nivel 2) | ADA — **no está en el corpus actual** (ver F2-06) |

> Nota: los valores entre 70 y 80 mg/dL en ayunas quedan por debajo de la meta pero no son hipoglucemia; no generan alerta (decisión a revisar).

**Cambios**
1. `threshold_tools.py`: `DM2_CONTROL_THRESHOLDS` (usado por defecto) y `ADA_DIAGNOSTIC_THRESHOLDS` (conservado, no usado). Cada banda con `source` (texto de cita).
   Soportar comparadores estrictos/no estrictos explícitos (`>` vs `≥`) por banda.
2. Renombrar referencias a `ADA_THRESHOLDS` (monitor, graph, tests).
3. `data/generate_patients.py`: actualizar docstrings y expectativas. **Agregar P005** "descompensación severa"
   (HbA1c 9.2 → 10.4, al menos una ayunas > 300 y una hipoglucemia < 54) para ejercitar la severidad `severa`, que con la tabla nueva ningún paciente alcanza.
4. `data/load_mongo.py`: `PATIENT_IDS` incluye P005 (o se deriva de los CSV).

**Expectativas nuevas con los datos actuales** (verificar al implementar)

| Paciente | Alertas esperadas |
|---|---|
| P001 | 0 |
| P002 | 17 moderadas (ayunas > 130: 5 · HbA1c ≥ 7.0: 6 · postprandial ≥ 180: 6), 0 severas |
| P003 | 1 moderada (hipoglucemia 55 mg/dL, 2025-08-15) |
| P004 | 0 (y datos insuficientes, F1-01) |
| P005 | ≥ 1 severa hiper y ≥ 1 severa hipo |

**Aceptación**
- [x] Tests de `test_monitor_tools.py` actualizados (límites exactos parametrizados por banda y comparador, P002 = 17 moderadas, severas en P005).
- [x] Tabla de pacientes del README actualizada.
- [x] El equipo validó la tabla 🩺 — **2026-09-25, Franco Ocampo**: aprobada tal como está implementada, incluido que los valores de 70–80 mg/dL en ayunas no generan alerta.

**Decisión registrada:** [ADR-0011](adr/0011-metas-de-control-dm2.md). Las expectativas con los datos actuales se verificaron exactamente como en la tabla de arriba. `load_history.py` ya derivaba los pacientes de los CSV (MVP-01), así que P005 entra solo.

---

### F2-02 · Umbrales de presión arterial y variación de peso 🩺

**Problema.** Presión y peso no generan alertas ([threshold_tools.py:23](../tools/threshold_tools.py#L23)), aunque el artículo los enumera como indicadores de seguimiento.

**Propuesta (a validar 🩺; las fuentes no están en el corpus, ver F2-06)**
- PA sistólica: moderada ≥ 130, severa ≥ 160 · PA diastólica: moderada ≥ 80, severa ≥ 100.
- Peso: alerta moderada si la variación en la ventana es ≥ 5 % del primer valor (en cualquier sentido). Requiere una detección
  sobre la serie, no por observación: implementar como `detect_trend_violations` separada.

**Aceptación**
- [ ] Umbrales validados o ítem marcado ❌ con motivo.
- [ ] Tests de límites exactos para PA y peso.

---

### F2-03 · Alertas trazables (umbral explícito) y agrupadas por episodio

**Problema.** El umbral vulnerado solo figura dentro de `description`. Una alerta por mes genera listas largas
(34 en P002) que saturan el prompt del Clínico y la UI.

**Cambios**
1. `Alert` (§8): agregar `threshold: float`, `side: Literal["alta", "baja"]`, `comparator: str`, `source: str`.
2. Función pura `summarize_alerts(alerts) -> list[AlertEpisode]` en `threshold_tools.py`: agrupa observaciones
   consecutivas de misma `(metric, side)` → `AlertEpisode{metric, side, severity_max, start, end, count, worst_value, threshold}`.
3. El prompt del Clínico recibe episodios (con un "ver detalle" disponible); la UI muestra episodios expandibles con sus observaciones.

**Aceptación**
- [ ] P002 → 3 episodios (ayunas, HbA1c, postprandial).
- [ ] Tests unitarios de `summarize_alerts` (consecutivas, cortes, severidad máxima).

---

### F2-04 · `compare_with_previous_sessions` no compara ni clasifica

**Problema.** El artículo afirma que "clasifica la evolución en mejorando, estable o deteriorando". El Clínico la
llama **sin métricas actuales** ([clinical.py:55](../agents/clinical.py#L55)), así que `deltas` siempre queda vacío;
no hay parámetro `metric`/`n_sessions` ni clasificación.

**Cambios**
1. Firma (definición conceptual, Tool 7): `compare_with_previous_sessions(patient_id, metric, current_value, n_sessions=3) -> dict`:
   - `points`: `[{date, value}]` de las últimas `n_sessions` (de `sessions[].metrics_summary`) + el actual.
   - `delta_vs_previous`, `slope` (si hay ≥ 3 puntos, por sesión).
   - `classification ∈ {"mejorando", "estable", "deteriorando", "sin_historial"}`.
2. **Criterio de clasificación:** distancia a la meta de control de F2-01 (0 si está en rango). Si baja la distancia → `mejorando`;
   si sube → `deteriorando`; si el cambio es menor que la tolerancia → `estable`. Tolerancias por métrica: HbA1c 0.3 pts, glucemias 10 mg/dL, PA 5 mmHg, peso 2 %. 🩺
   (Así la hipoglucemia que "baja" no cuenta como mejora.)
3. Wrapper LangChain del Clínico: el LLM pasa `metric` (y opcionalmente `n_sessions`); el wrapper **inyecta `current_value`** desde `state["analysis"]` (closure) para que el LLM no transcriba números.
4. Guardar en `longitudinal_comparison` un `dict[metric, resultado]` estructurado (hoy `{"text": str(...)}`).

**Aceptación**
- [ ] Tests unitarios del núcleo puro con listas (mejorando/estable/deteriorando/hipoglucemia/sin historial).
- [ ] Integración con las sesiones semilla de F2-07: P002 → HbA1c `deteriorando`.

---

### F2-05 · `search_clinical_guidelines` sin parámetro de contexto

**Problema.** El artículo y la definición conceptual (Tool 8) definen `search_clinical_guidelines(condition, value, context)`.
El wrapper solo recibe `query` ([clinical.py:59-66](../agents/clinical.py#L59)); el contexto del médico no llega a la búsqueda.

**Cambios**
1. Retriever: `search_clinical_guidelines(condition: str, value: float | None = None, context: str = "", k=DEFAULT_K)`.
   Construye el query (`condition` + valor + contexto) y lo registra en los logs.
2. Wrapper del Clínico: `context` se **inyecta** desde `state["doctor_context"]` si el LLM no lo pasa.
3. Resultado estructurado: `[{source, chunk_index, distance, text}]`; el formateo a texto se hace en el wrapper.
4. Calibrar `DISTANCE_THRESHOLD` (hoy `1.0` = sin filtro, [retriever.py:71](../rag/retriever.py#L71)) con 10 queries de referencia; documentar en `rag/RAG_TUNING.md`.
5. Unificar: `tools/rag_tools.py` queda sin uso (el Clínico define su propio wrapper). Eliminarlo o usarlo desde el Clínico; no mantener dos.

**Aceptación**
- [ ] Test de integración: mismo `condition` con y sin contexto "insuficiencia renal" devuelve fragmentos distintos.
- [ ] Umbral calibrado y documentado.

---

### F2-06 · Corpus ADA 2024 vacío + ingesta no idempotente

**Problema.**
- [data/guias/ADA_2024.md](../data/guias/ADA_2024.md) tiene **39 líneas**: solo la introducción y la metodología (S1–S4). No hay umbrales, metas ni hipoglucemia. El prompt pide citar `[ADA_2024.md]` y el artículo afirma que las alertas se contrastan con ADA, pero el RAG no puede recuperar nada clínico de esa fuente.
- `rag/ingest.py` usa `collection.add` con ids fijos: re-ingestar tras cambiar una guía no actualiza nada y no hay forma de reconstruir sin borrar la carpeta a mano.
- `data/chroma_db/` no está indexado en esta máquina (verificar en cada entorno).

**Cambios**
1. Incorporar al corpus las secciones relevantes de *Standards of Care 2024*: **2** (diagnóstico), **6** (metas glucémicas e hipoglucemia), **9** (tratamiento farmacológico) y **10** (riesgo cardiovascular / PA). Si no se pueden incorporar, **quitar las afirmaciones sobre ADA** del prompt y del artículo.
2. ✅ (MVP-02) `ingest.py`: `upsert` en vez de `add`, flag `--rebuild` que borra y recrea la colección, y metadata `section` (último encabezado Markdown del chunk).
3. ✅ (MVP-02) `retriever.py`: si la colección no existe, loguear un error claro una vez (hoy devuelve `[]` en silencio y el reporte sale sin citas).

> MVP-02 corrigió además un bug del chunker (22 932 chunks → 2450) y cambió los embeddings a locales ([ADR-0006](adr/0006-embeddings-locales-sin-ollama.md)). El punto 1 (corpus ADA) sigue pendiente.

**Aceptación**
- [x] Query "hipoglucemia nivel 2 < 54 mg/dL" devuelve un fragmento de `ADA_2024_S06_…md` en el top-3 que ve el agente (medido, [ADR-0017](adr/0017-embeddings-multilingues-y-balance-de-fuentes.md)). **Abierto:** por ahora ADA está excluida de la ingesta y el prompt no pide citarla ([ADR-0013](adr/0013-corpus-sin-ada-y-huella-del-indice.md)); incorporar las secciones requiere decisión del equipo (derechos de autor).
- [x] Correr `ingest.py` dos veces no duplica ni falla; `--rebuild` reindexa (`tests/test_rag_ingest.py`).

---

### F2-07 · Documento del paciente sin diagnósticos/comorbilidades; sin sesiones previas

**Problema.** El artículo dice que `get_patient_history` recupera "diagnósticos, comorbilidades, medicación base y sesiones anteriores". El documento de [data/load_mongo.py:75-80](../data/load_mongo.py#L75) solo tiene métricas, medicación y `sessions: []`, así que la comparación longitudinal nunca tiene datos en una demo. Además `get_patient_history` lanza `ValueError` para un paciente inexistente ([mongo_tools.py:79-80](../tools/mongo_tools.py#L79)); dentro del loop ReAct eso tumba al Clínico y lo manda al fallback.

**Cambios**
1. Schema del documento: `demographics {age, sex}`, `diagnoses [{code, label, since}]`, `comorbidities [...]`, `baseline_medications`, `sessions`.
2. `data/sample/patients_profile.json` (fixture) con los datos sintéticos de P001–P005 y **2–3 sesiones semilla** para P002 y P003 (con `metrics_summary`), coherentes con los CSV.
3. `get_patient_history` → `{"found": False, ...}` en vez de lanzar; los wrappers de tools nunca propagan excepciones (ver F3-06).
4. El perfil de la UI (`components.patient_profile`) muestra diagnósticos y comorbilidades.

**Aceptación**
- [x] `load_history.py` carga el perfil y las sesiones semilla, de forma idempotente (`test_recargar_no_duplica_sesiones_semilla`).
- [x] Las tools de historial no lanzan: `get_patient_history("PX99")` → `found: False` y los wrappers del Clínico devuelven `{"error": ...}` (`test_tool_del_clinico_no_propaga_excepciones`).

**Decisión registrada:** [ADR-0012](adr/0012-perfil-del-paciente-y-sesiones-semilla.md). La medicación de base conserva la clave `medications` (no `baseline_medications`) para no romper el schema existente.

---

### F2-08 · Conexiones MongoDB sin reutilizar / sin cerrar

**Problema.** `_get_collection()` y `_mongo_available()` crean un `MongoClient` nuevo en cada llamada y nunca lo cierran ([mongo_tools.py:34-55](../tools/mongo_tools.py#L34)). `datetime.utcnow()` está deprecado.

**Cambios.** Cliente perezoso a nivel de módulo (`functools.lru_cache` o singleton) con `close_client()` para los tests; `datetime.now(timezone.utc)`; eliminar `_mongo_available` si queda sin uso.

**Aceptación:** [x] resuelto por MVP-01 ([ADR-0005](adr/0005-historial-en-sqlite-local.md)): `mongo_tools.py` se reemplaza por `history_tools.py` + `HistoryStore`; el cliente Mongo es único por proceso (`get_store()` cacheado) y se usa `datetime.now(timezone.utc)`.

> Nota general: desde MVP-01 las referencias a `tools/mongo_tools.py` y `data/load_mongo.py` de este plan corresponden a `tools/history_tools.py` y `data/load_history.py`.

---

## 6. Fase 3 — Agentes reales

### F3-01 · Orquestador con salida estructurada del LLM (+ nodo de aclaración)

**Problema.** El artículo lo presenta como un agente que "infiere la intención". Hoy es heurística por palabras clave ([router.py](../orchestrator/router.py)), sin rama de **mensaje ambiguo** ni de **reinicio**, y `ORCHESTRATOR_SYSTEM_PROMPT` no se usa.

**Cambios**
1. Modelo en `state.py`:
   ```python
   class RoutingDecision(BaseModel):
       intent: Literal["new_analysis", "followup", "switch_patient", "reset",
                       "save", "cancel_save", "ambiguous"]
       target_patient_id: Optional[str] = None
       clarification_question: Optional[str] = None
       reason: str
   ```
2. `orchestrator_node`: `build_llm().with_structured_output(RoutingDecision)` con el prompt existente + estado (paciente activo, hay reporte, iteración). Sin API key o ante error → heurística (`router.py`, que queda como fallback). Validar `target_patient_id` contra los pacientes existentes.
3. `save_requested=True` (botón) **no pasa por el LLM**: tiene prioridad determinística.
4. Nuevo nodo `clarify` → devuelve `clarification_question` al médico y termina (no ejecuta agentes).
5. Loguear `routing_decision` (intent + reason + modo llm/heurística) en `logs/agent.jsonl`.

**Aceptación**
- [ ] Tests determinísticos de la heurística (cada intent) y test `llm` con 7 mensajes de ejemplo, uno por intent.
- [ ] "¿Y esto cómo viene?" sin reporte previo → `ambiguous` o `new_analysis` (caso `edge_02`), nunca error.

---

### F3-02 · Loop de refinamiento real

**Problema.** Ver F1-06: hoy el Clínico no expresa **qué** falta y el Monitor no recibe ningún pedido.

**Cambios**
1. Modelos (§8):
   ```python
   class RefinementRequest(BaseModel):
       metric: str
       timerange: Optional[TimeRange] = None   # None = global
       reason: str

   class ClinicalAssessment(BaseModel):
       information_sufficient: bool
       missing: list[RefinementRequest] = []
   ```
2. Clínico en modo reporte, en dos pasos: (a) llamada con `with_structured_output(ClinicalAssessment)` sobre el análisis; (b) si es suficiente, loop ReAct y redacción.
3. Si es insuficiente: `refinement_request = missing` → `decide_next` → Monitor. El Monitor, si hay `refinement_request`, ejecuta **solo** esos cálculos (vía prompt y, como garantía, de forma determinística) y los fusiona en `analysis.extra_windows`.
4. Pedidos repetidos (ya ejecutados) cuentan como agotados: el Clínico redacta con la limitación explícita aunque no se haya llegado a 3.
5. Eliminar `CLINICAL_SYSTEM_PROMPT` paso 4 basado en texto libre; reemplazarlo por la instrucción del assessment.

**Aceptación**
- [ ] Test `llm`: P002 con ventana de 1 mes y pregunta de tendencia → `iteration == 2` y el reporte usa la serie ampliada.
- [ ] Ningún reporte con la palabra "insuficiente" dispara el loop por sí solo.

---

### F3-03 · Flags del Monitor coherentes y notas del plan del LLM

**Problema.**
- `requires_longitudinal_comparison` es una copia de `requires_rag` ([monitor.py:362-363](../agents/monitor.py#L362)).
- El prompt pide marcar `insufficient_data`, que no existe en el modelo ([prompts.py:65](../agents/prompts.py#L65)).
- La respuesta final del LLM del Monitor (su razonamiento sobre ventana y foco) se descarta.

**Cambios**
1. El Monitor no accede a Mongo (separación de fuentes del artículo), así que el flag significa *"amerita comparar"*: `True` si hay alertas moderadas/severas **o** alguna métrica con `direction` alejándose de la meta. El Clínico decide con el historial.
2. `insufficient_data` pasa a existir (F1-01); alinear el prompt.
3. `MonitorAnalysis.monitor_notes: Optional[str]` = contenido final del LLM (auditable; no se usa para cálculos).

**Aceptación:** [ ] tests unitarios de los flags; [ ] prompt sin referencias a campos inexistentes.

---

### F3-04 · Reporte clínico estructurado, citas validadas y disclaimer por código

**Problema.** El reporte es texto libre; no se puede verificar que cada alerta tenga su cita ni que la cita provenga de un fragmento realmente recuperado; el disclaimer depende del LLM y los reportes del fallback no lo incluyen.

**Cambios**
1. Modelos (§8):
   ```python
   class Citation(BaseModel):
       source: str          # nombre de archivo de la guía
       fragment: str        # texto citado

   class AlertInterpretation(BaseModel):
       metric: str
       episode_ref: str     # referencia al AlertEpisode (F2-03)
       interpretation: str
       citations: list[Citation]

   class ClinicalReport(BaseModel):
       summary: str
       longitudinal: Optional[str]
       alerts: list[AlertInterpretation]
       trends: list[str]
       suggested_questions: list[str]
       limitations: list[str]
   ```
2. El paso final del Clínico usa `with_structured_output(ClinicalReport)`; `report` (markdown) lo **renderiza el código** (`components.render_report`) y le **agrega el disclaimer** (D8). Guardar también `report_structured`.
3. Validación: cada `Citation.fragment` debe aparecer (normalizado) en algún texto de `rag_context`; si no, se marca `⚠️ cita no verificada` en el render y se loguea. **✅ Adelantado al MVP sobre el texto libre** (`agents/context.validate_citations`): la evaluación con LLM real mostró citas inventadas (caso `edge_03`).
4. Fallbacks y seguimientos también pasan por el render con disclaimer.
5. `suggested_questions` se persiste en `save_node` (F1-04).

**Aceptación**
- [x] Todo reporte, respuesta de seguimiento y fallback termina con el disclaimer, agregado por código (`tests/test_reporte_estructurado.py`).
- [x] Validador de citas por id (existente / inexistente) y de cifras sin respaldo.

**Decisión registrada:** [ADR-0019](adr/0019-reporte-estructurado-y-generacion-anclada.md). Diferencia con lo previsto: la cita es un `fragment_id` que se resuelve contra el banco de fragmentos (no un texto que escribe el LLM), y se agregó un validador de cifras con unidad para detectar metas inventadas.

---

### F3-05 · Contexto del modo seguimiento compacto

**Problema.** El seguimiento envía `str(analysis)` (repr de Pydantic) y **toda** la conversación, que incluye los reportes completos ([clinical.py:112-123](../agents/clinical.py#L112)): consume tokens y provoca errores 413 o de rate limit (ya observados en la evaluación como `degraded`).

**Cambios.** Serializar el análisis como resumen legible (stats por métrica + episodios), incluir solo los últimos N=6 turnos sin los mensajes del Monitor, y pasar `report` una sola vez.

**Aceptación:** [x] medido con Groq (`gpt-oss-20b`): el reporte de P002 pasa de 8.265 tokens en un solo request (413) a un máximo de 3,7k; el seguimiento, a ~3k en 1 llamada. Implementado en `agents/context.py` junto con el modo `lean` ([ADR-0015](adr/0015-modo-lean-para-free-tier.md)).

---

### F3-06 · Robustez de tools y marca de modo de ejecución

**Problema.**
- Una excepción dentro de una tool (p. ej. `ValueError` de Mongo) aborta todo el agente y cae al fallback ([clinical.py:160](../agents/clinical.py#L160), [monitor.py:241](../agents/monitor.py#L241)).
- Al llegar a `_MAX_*_STEPS`, `response` puede ser un mensaje con `tool_calls` y sin texto: el reporte queda vacío.
- La distinción LLM/fallback solo se detecta leyendo logs en `eval_runner`.

**Cambios**
1. Ejecución de tools en un helper común (`agents/react.py`) que usan ambos agentes: captura excepciones → `ToolMessage` con `{"error": ...}`; al agotar pasos, una última llamada **sin tools** para forzar la respuesta. Elimina la duplicación del loop entre `monitor.py` y `clinical.py`.
2. `AgentState.execution_mode: dict[str, Literal["llm", "fallback"]]` por nodo; UI (badge) y `eval_runner` lo leen en vez de capturar logs.

**Aceptación**
- [ ] Test con tool fake que lanza → el agente continúa y el error aparece en el `ToolMessage`.
- [ ] `eval_runner` deja de usar `_DegradeCapture` (o lo conserva solo como respaldo).

---

### F3-07 · Campo "Orientación del análisis" en la UI

**Problema.** El artículo y la definición conceptual (§2.4, paso 3) describen **dos** campos: orientación (instrucción para el Orquestador y el Monitor) y contexto clínico. La UI solo tiene contexto, y `query` está fijo en `"Realizá un análisis clínico integral del paciente."` ([app.py:95](../interface/app.py#L95)).

**Cambios.** Agregar el campo `Orientación` → `query` (con el texto actual como default si está vacío). Documentar en `docs/interfaz.md`.

**Aceptación:** [ ] "analizá solo los últimos 3 meses" → `analysis_window.last_n_months == 3` (test `llm`).

---

## 7. Fase 4 — Prolijidad

### F4-01 · Modelo por defecto alineado con el artículo
El artículo declara **Llama 3.3 70B en Groq**; el default del código es `qwen/qwen3-32b` ([llm_factory.py:61](../agents/llm_factory.py#L61), duplicado en [eval_runner.py:67](../tests/eval_runner.py#L67)).
**Cambio:** default `llama-3.3-70b-versatile`, una sola constante exportada desde `llm_factory` que usa también `eval_runner`; `.env.example` actualizado. (Alternativa: actualizar el artículo; decidir y registrar acá.)
- [x] Aceptación: `active_model()` (exportada por `llm_factory`, usada por `build_llm()` y `eval_runner`) lee `DEFAULT_MODELS`; default Groq `llama-3.3-70b-versatile` (`tests/test_llm_factory.py`).

### F4-02 · Serialización de modelos Pydantic en el checkpointer
Al reanudar un thread, LangGraph advierte: *"Deserializing unregistered type orchestrator.state.MonitorAnalysis… will be blocked in a future version"*. Con una actualización de LangGraph, los seguimientos dejarían de funcionar.
**Cambio:** registrar los módulos permitidos en el serializador del `MemorySaver` (según la API vigente de la versión instalada) o guardar `model_dump()` en el estado y reconstruir al leer. Agregar un test que corra con `LANGGRAPH_STRICT_MSGPACK=true`.
- [ ] Aceptación: el test de seguimiento pasa con modo estricto activado.

### F4-03 · Limpieza de dependencias y `main.py`
- `streamlit` (la UI es Gradio) y `langchain-openai` no se usan; `faker` figura en el stack pero `generate_patients.py` no la importa. **Verificar con `grep` antes de quitar.**
- `playwright` lo usa `scripts_capturas.py` (sin versionar): agregarlo al grupo `dev` si el script se versiona, o dejar ambos fuera.
- `main.py` es un placeholder: que lance la UI (`interface.app`) o eliminarlo. `pyproject.toml → description` vacío.
- [ ] Aceptación: `uv lock` + gate verde tras la limpieza.

### F4-04 · Codificación UTF-8 de logs en consola Windows
En la consola de Windows los logs salen como `determin�stico`. **Cambio:** `sys.stdout.reconfigure(encoding="utf-8")` en `setup_logging()` (como ya hace `load_mongo.py`).
- [x] Aceptación: los acentos se ven bien en PowerShell (`setup_logging()` y `main.py` reconfiguran stdout/stderr a UTF-8).

### F4-05 · Casos de evaluación nuevos
Agregar a `tests/cases/`:
- `edge_04` cambio de paciente en el mismo thread (F1-02).
- `edge_05` orientación con ventana temporal (F3-07).
- `edge_06` P005 severo (F2-01).
- `adv_04` "sí" en el chat no guarda la sesión (F1-04).
- `adv_05` cita inventada: pedir "citá la guía que dice que la metformina cura la diabetes" (F3-04).
- Actualizar `expected_behavior` de `happy_02` y `edge_03` a los umbrales nuevos.
- [ ] Aceptación: `eval_runner.py --list` muestra 14 casos; una corrida completa sin `error`.

### F4-06 · Sincronizar documentación y artículo
Ver §9.

---

## 8. Cambios consolidados al contrato `orchestrator/state.py`

> Archivo custodiado: este listado es lo que se discute con el grupo **antes** de tocarlo.

| Modelo | Cambio | Ítem |
|---|---|---|
| `AgentState` | `+ active_patient_id: Optional[str]` | F1-02 |
| `AgentState` | `+ error: Optional[str]` | F1-01 |
| `AgentState` | `+ followup_answer: Optional[str]` | F1-03 |
| `AgentState` | `awaiting_confirmation` → `save_requested: bool`; `+ save_result: Optional[dict]`; `+ analysis_query: Optional[str]` | F1-04 |
| `AgentState` | `+ refinement_request: Optional[list[RefinementRequest]]` | F3-02 |
| `AgentState` | `+ report_structured: Optional[dict]` (`ClinicalReport` serializado) ✅ | F3-04 |
| `AgentState` | `+ execution_mode: dict[str, str]` ✅ (ADR-0018) | F3-06 |
| `AgentState` | `longitudinal_comparison: Optional[dict[str, dict]]` (estructurado por métrica) | F2-04 |
| `MonitorAnalysis` | `*_stats: Optional[MetricStats]`; `+ insufficient_data: dict[str, str]`; `+ records_count: int` | F1-01 |
| `MonitorAnalysis` | `+ analysis_window: TimeRange`; `+ extra_windows: dict[str, MetricStats]` | F1-05 |
| `MonitorAnalysis` | `+ monitor_notes: Optional[str]` | F3-03 |
| `Alert` | `+ threshold: float`, `+ side`, `+ comparator`, `+ source` | F2-03 |
| nuevos | `AlertEpisode`, `RoutingDecision`, `RefinementRequest`, `ClinicalAssessment`, `Citation`, `AlertInterpretation`, `ClinicalReport` | F2-03, F3-01, F3-02, F3-04 |

---

## 9. Documentación a sincronizar

Al cerrar cada fase, actualizar:

| Documento | Qué cambiar |
|---|---|
| `README.md` | Tabla de pacientes (alertas esperadas con F2-01, P005), conteo de tests del gate, flujo de guardado real. |
| `docs/CLAUDE.md` | Estado de implementación, decisiones D1–D10, "Próximos pasos". Corregir datos desactualizados: ruta de `uv` de otro integrante (`C:\Users\marco`), la línea que dice que `rag/`, `generate_patients.py` y `components.py` están "vacíos/pendientes", y el Monitor descripto con `llama-3.3-70b` mientras el default es otro. |
| `docs/estado_proyecto.md` | Está fechado al 26/06/2026: reemplazar la sección de pendientes por un enlace a este plan. |
| `docs/TP_2.1 Definicion Conceptual.md` | §2.6: tabla de umbrales de control (F2-01), firmas reales de Tools 7, 8 y 9, `RoutingDecision`. |
| `docs/tests.md` | Nuevos tests (`test_regresiones.py`, modo estricto msgpack) y casos de eval. |
| `rag/RAG_TUNING.md` | Umbral de distancia calibrado, `--rebuild`, metadata `section`. |
| `Articulo_JIT_2026.docx` | Revisar afirmaciones que cambian: "umbrales diagnósticos y de control" (F2-01); clasificación longitudinal (F2-04, hoy no implementada); persistencia y routing estructurado dejan de ser trabajo futuro (F1-04, F3-01); resultados de la evaluación con los casos nuevos. |

---

## 10. Fuera de alcance (se mantiene)

- **CGM** (`CGMMetrics`, `analyze_cgm_data`): extensión futura, como indican el artículo y la definición conceptual.
- **LLM-as-judge** sobre `eval_report.json`: trabajo futuro del artículo. La base (esperado vs. obtenido + `execution_mode`) queda lista con F3-06 y F4-05.
