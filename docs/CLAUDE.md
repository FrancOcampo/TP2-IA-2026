# CLAUDE.md

Guía para trabajar en este repositorio. Léela antes de tocar código.

> **⚠️ Mantené este archivo vivo (instrucción para Claude).** Cada vez que hagas un
> cambio que altere lo que describe este documento — agregar/implementar/vaciar un módulo,
> cambiar el stack o una dependencia, modificar una decisión de diseño, una convención o el
> reparto de trabajo — **actualizá `CLAUDE.md` en el mismo cambio**. Como mínimo, antes de
> cerrar la tarea revisá y, si corresponde, tocá: la tabla **Estado de implementación** (y su
> fecha), las secciones **Stack**, **Arquitectura del código**, **Decisiones de diseño** y
> **Próximos pasos**, y `docs/tareas_siguiente_iteracion.md` si la tarea movió el plan. El
> objetivo es que este archivo nunca quede desincronizado del código: es la fuente de contexto
> que se carga cada sesión.

## Qué es

Sistema **multi-agente de soporte clínico** para seguimiento de pacientes con diabetes
tipo 2 (TP2 de Inteligencia Artificial 2026). No emite diagnósticos: produce reportes de
soporte a la decisión médica. Tres agentes coordinados sobre LangGraph:

- **Orquestador** — enruta por inferencia de intención y gestiona el loop de refinamiento.
- **Monitor** — análisis cuantitativo con tools determinísticas (stats, metas de control DM2).
- **Clínico** — interpreta hallazgos con RAG sobre guías clínicas + historial del paciente.

Documentos fuente: [docs/TP_2 Agente.md](docs/TP_2%20Agente.md) (enunciado) y
[docs/TP_2.1 Definicion Conceptual.md](docs/TP_2.1%20Definicion%20Conceptual.md) (diseño).
La definición conceptual es la fuente de verdad del diseño; mantenerla sincronizada con el
código. Ver también [docs/logs.md](docs/logs.md) (cómo leer las trazas/observabilidad) y
[docs/plan_integrante_D.md](docs/plan_integrante_D.md) (plan detallado de interfaz + logging
+ evaluación).

## Stack y comandos

- **uv** gestiona el entorno (instalado en `C:\Users\marco\.local\bin`; en terminales
  nuevas ya está en el PATH).
- LLM: Groq `openai/gpt-oss-120b` por defecto (ADR-0014; free tier: 8000 tokens/min) (`LLM_PROVIDER`/`LLM_MODEL`; defaults en `agents/llm_factory.DEFAULT_MODELS`; Gemini acepta `GOOGLE_API_KEY` o `GEMINI_API_KEY`) · Embeddings: **locales en proceso** (ONNX MiniLM de ChromaDB; Ollama opcional vía `EMBEDDING_PROVIDER`, ADR-0006) · Vector store:
  ChromaDB (solo guías) · Historial: **SQLite local** por defecto, MongoDB opcional (`HISTORY_BACKEND`, ADR-0005) · Validación: Pydantic v2 ·
  Interfaz: **Gradio** (decisión del equipo; la dependencia `streamlit` sigue en
  `pyproject.toml` pero no se usa) · Observabilidad: **LangSmith + logging propio**
  (consola legible + `logs/agent.jsonl`).

```bash
uv sync                 # instalar/actualizar entorno
uv run python main.py   # bootstrap (historial SQLite + índice RAG si faltan) y UI en :7860
uv run pytest           # correr la suite (config en pyproject: pythonpath=["."], testpaths=["tests"])
uv lock                 # regenerar lockfile tras cambiar dependencias
```

## Arquitectura del código

- [orchestrator/state.py](orchestrator/state.py) — `AgentState` (TypedDict del grafo) y
  modelos Pydantic: `PatientMetrics`, `Alert`, `MonitorAnalysis`, `Medication`,
  `MetricStats`, `BloodPressureStats`, `CGMMetrics`, `TimeRange` (ventana de análisis del
  Monitor). **Archivo custodiado**: coordinar cualquier cambio con el grupo (es contrato
  compartido entre todos los nodos).
- [orchestrator/graph.py](orchestrator/graph.py) — grafo LangGraph. Entry en `orchestrator`;
  `monitor → clinical`; loop de refinamiento `clinical → monitor`. **Los nodos Monitor y
  Clínico son reales** (agentes ReAct + fallbacks determinísticos sin API key).
- [orchestrator/router.py](orchestrator/router.py) — lógica de routing (heurística por
  ahora; reemplazar por clasificación vía LLM).
- [agents/prompts.py](agents/prompts.py) — system + human prompts de los 3 agentes.
- [agents/monitor.py](agents/monitor.py) — Agente Monitor real (Integrante A). Loop ReAct:
  wrappea las 4 tools de C como `@tool` de LangChain, las bindea a `ChatGroq`
  (default en `llm_factory.DEFAULT_MODELS`), ejecuta el loop de razonamiento, y ensambla `MonitorAnalysis`
  programáticamente. Si no hay `GROQ_API_KEY`, cae a un fallback determinístico
  (ejecuta las tools directamente sin LLM).
- [interface/logging_config.py](interface/logging_config.py) — observabilidad (Integrante D).
  `setup_logging()` (consola legible + `logs/agent.jsonl` vía `RotatingFileHandler`) y
  `LoggingCallbackHandler` (`BaseCallbackHandler`) que registra nodos/routing hoy y
  `llm_*`/`tool_*` en cuanto existan agentes/tools reales. Se engancha al grafo con
  `config={"callbacks": get_callbacks()}`. LangSmith se activa solo vía env vars.
- [interface/app.py](interface/app.py) — UI Gradio que ya invoca `orchestrator.graph.app`
  real con `thread_id` por sesión y callbacks de logging. Esqueleto funcional (chat +
  reporte); falta el layout completo y la pestaña de observabilidad (ver plan de D).
- [tools/patient_tools.py](tools/patient_tools.py) — tools determinísticas del Monitor sobre
  el EHR. Se invocan **por `patient_id`** (cargan + recortan internamente; el LLM no mueve
  arrays): `load_patient_data` (→ `PatientMetrics`), `calculate_stats(patient_id, metric,
  timerange=None)` (→ `MetricStats`: `last_value`, `mean`, `min_value`, `max_value`, `delta`,
  `direction`; stdlib, sin numpy), `get_medication_schedule` (→ `list[Medication]`).
  `window_metrics` es el **único** lugar del recorte temporal; `_compute_stats` es el núcleo
  puro testeable con listas. Leen de `data/sample/` hasta que B entregue Mongo/generador real.
- [tools/threshold_tools.py](tools/threshold_tools.py) — `detect_threshold_violations(patient_id,
  metric, timerange=None)` (→ `list[Alert]`) con `THRESHOLDS` = `DM2_CONTROL_THRESHOLDS` (metas de
  control, ADR-0011; bandas `Band` con comparador y fuente; `ADA_DIAGNOSTIC_THRESHOLDS` sin uso). Detecta **hiper
  e hipoglucemia**: bandas alta y baja, severidad `moderada`/`severa`. Núcleo puro
  `_detect_violations(metric, values, dates)`. Glucemias con ambas bandas; HbA1c solo alta;
  peso/presión sin umbral (ver caveats en el README).
- [data/sample/](data/sample/) — **fixture provisional** (contrato #1): 4 CSVs
  (`P001`–`P004`) + `medications.json`. **No es el dataset final**; B debe respetar su schema.
  Ver [data/sample/README.md](data/sample/README.md).
- `rag/`, `data/generate_patients.py` y `interface/components.py` — **vacíos/pendientes**.

## Flujo de métricas (contrato A+C)

Cómo se cargan y analizan las métricas en cada consulta. El **Monitor es un agente ReAct**:
el LLM razona el *qué* y el *hasta cuándo*; el cálculo es 100% determinístico en las tools.

1. **Carga (una vez por consulta).** El nodo Monitor llama `load_patient_data(patient_id)` →
   serie **completa** en `state["metrics_history"]` (`PatientMetrics`, una fila por mes).
2. **El LLM elige la ventana y el foco.** A partir de `query` + `doctor_context` decide:
   - el `TimeRange` (ej. "últimos 3 meses" → `last_n_months=3`; un rango → `start`/`end`;
     nada dicho → **global**), y
   - qué métricas analizar (todas por default; un subconjunto si el médico orienta).
   El LLM **no** calcula nada: solo traduce lenguaje natural a parámetros y orquesta.
3. **Tools determinísticas, finas y por `patient_id`.** El LLM invoca `calculate_stats` y
   `detect_threshold_violations` (tools separadas, §2.6) pasando `patient_id`, `metric` y el
   `timerange`. Cada tool **recarga + recorta** internamente con `window_metrics` (el LLM
   nunca mueve arrays) y delega en su núcleo puro. El recorte vive en **un solo lugar**.
4. **Loop ReAct.** Tras observar resultados, el LLM decide si pide otra métrica/ventana o
   cierra; ensambla el `MonitorAnalysis`. Conecta con `information_sufficient` del refinamiento.

> Separación clave: las **tools** son el *qué* (cálculo exacto, auditable en los logs por
> `patient_id`/`metric`/`timerange`); el **LLM** es el *sobre qué y hasta cuándo*. Eso es lo
> que justifica un agente y no un wrapper. `TimeRange`: `last_n_months` (atajo) **o**
> `start`/`end` (excluyentes); sin campos = global. La aplica `window_metrics`.

## Decisiones de diseño (no revertir sin discutir)

1. **Routing por inferencia de intención**, no por skills `/monitor` `/clinico`. El
   Orquestador lee `state["query"]` + estado y decide: pipeline completo / seguimiento
   directo al Clínico / reset / confirmación / aclaración.
2. **Historial del paciente en un almacén documental** (documento por paciente, búsqueda exacta por id,
   **sin RAG**). Motor detrás de `HistoryStore`: SQLite local por defecto, MongoDB opcional (ADR-0005). RAG es exclusivo de las guías clínicas.
3. **CGM = extensión futura/opcional**. `CGMMetrics`/`cgm_series` están definidos pero
   fuera del alcance de la implementación actual; marcado así en la def. conceptual.
4. **Loop de refinamiento**: `information_sufficient` lo fija el nodo Clínico con un criterio
   determinístico sobre el análisis (ADR-0010: hay `insufficient_data` y la ventana es acotada);
   si es `False` e `iteration < 3`, el grafo vuelve al Monitor (`decide_next`), que re-analiza con
   la ventana global. Guardrail = 3 iteraciones.
   El contador se reinicia en el Orquestador en cada mensaje nuevo (por eso el loop NO
   vuelve por el nodo orquestador, para no resetear `iteration`).
5. **Modelos tipados** en vez de `dict`/`list[str]`: `Medication`, `MetricStats`,
   `BloodPressureStats`.
6. **Memoria de sesión** vía `MemorySaver` (checkpointer): toda invocación requiere
   `config={"configurable": {"thread_id": ...}}`.
7. **Monitor agéntico + tools determinísticas** (contrato A+C): el LLM razona ventana/foco/
   loop; el cálculo es 100% determinístico. Tools **finas y separadas** (§2.6, no fusionadas)
   e invocadas **por `patient_id`** (no pasando arrays). Ver "Flujo de métricas".
8. **`TimeRange` + ventaneo único**: el subrango temporal se modela con `TimeRange`
   (`last_n_months` **o** `start`/`end`; nada = global) y se aplica **solo** en
   `window_metrics`. Las tools no reimplementan el filtrado. Núcleo puro (`_compute_stats`,
   `_detect_violations`) separado del wrapper para poder testear con listas.
9. **`detect_threshold_violations` recibe `dates`** (además de `metric`/`values` en el núcleo):
   `Alert` exige la fecha del registro. Ratificado por A y C (refina la firma de §2.6).
10. **`MetricStats` clínicamente accionable** (contrato A+C): se quitaron `std` y la pendiente
    cruda (`trend`) — la desviación de mediciones puntuales aporta poco y una pendiente no es
    legible para el médico. Campos: `last_value`, `mean`, `min_value`, `max_value`, `delta`
    (cambio neto) y `direction` ("subiendo"/"bajando"/"estable", con banda muerta del 3%). Los
    **extremos** (`min`/`max`) son clave: exponen eventos que la media esconde (p. ej. una
    hipoglucemia puntual en un promedio normal).
11. **Detección de hipoglucemia** (contrato A+C): `detect_threshold_violations` cubre banda
    BAJA además de la alta. Hipoglucemia ADA: `< 70` mg/dL → `moderada`, `< 54` → `severa`
    (glucemias en ayunas y postprandial; HbA1c no tiene banda baja). Vigilar hipoglucemias es
    central en el seguimiento de un diabético y antes el sistema era ciego a ellas.
12. **Metas de control, no criterios diagnósticos** (D1, ADR-0011): todos los pacientes ya tienen
    DM2, así que la banda alta usa metas de control (HbA1c ≥ 7 / > 9, ayunas > 130 / > 300,
    postprandial ≥ 180 / > 300). Cada banda declara comparador y fuente. 🩺 Pendiente de
    validación clínica del equipo.

## Convenciones

- Match el estilo del código circundante; comentarios y prompts en español.
- Los stubs llevan `TODO:` indicando con qué se reemplazan.
- Toda salida clínica incluye el disclaimer obligatorio (ver `prompts.py`).
- Las tools del Monitor son **determinísticas**; validarlas con tests determinísticos.

## Estado de implementación (al 2026-06-28)

| Módulo | Estado |
|---|---|
| `state.py`, `prompts.py` | ✅ completos y verificados |
| `graph.py`, `router.py` | ✅ grafo funcional end-to-end; Monitor y Clínico reales; routing heurístico con **paciente activo** (`active_patient_id`): el cambio de paciente o el reinicio limpian el estado derivado (ADR-0004) |
| `agents/monitor.py` | ✅ **Agente Monitor real**: loop ReAct (ChatGroq + 4 tools LangChain), fallback determinístico sin API key, produce `MonitorAnalysis` |
| `agents/clinical.py` | ✅ **Agente Clínico real**: loop ReAct (ChatGroq + 3 tools LangChain), fallback determinístico sin API key, modos reporte/seguimiento |
| Tools del Monitor (EHR/umbrales) + `data/sample/` | ✅ `patient_tools.py` y `threshold_tools.py` listos y testeados; envueltas como `@tool` LangChain en `agents/monitor.py`; CSVs P001–P005 creados |
| Testing (estrategia) | ✅ organizado por objetivo; ver **[docs/tests.md](docs/tests.md)** (tools / plomería / calidad de la IA) |
| `tests/test_graph.py` | ✅ plomería del grafo en 2 modos: determinístico (fallback forzado, gate de CI) + estocástico (`llm`, LLM real, aserciones laxas) |
| `tests/test_monitor_tools.py` | ✅ tools del Monitor, determinístico sobre `data/sample/*.csv` |
| `pyproject.toml`, entorno uv | ✅ deps, entorno uv y tests funcionando listos |
| Observabilidad (`interface/logging_config.py`) | ✅ logging dual (consola + JSONL) + LangSmith; tracea nodos, routing, `llm_*` y `tool_*` (con nombre de tool y tokens) |
| `interface/app.py` (Gradio) | ✅ UI completa: 3 pestañas (Consulta clínica + Observabilidad dev + Evaluación) contra el grafo real |
| `tests/conftest.py`, `.env.example` (LangSmith) | ✅ `load_dotenv` + vars de tracing |
| Tools de historial (`get_patient_history`, `compare_*`, `update_*`) | ✅ `tools/history_tools.py` sobre `HistoryStore` (`tools/history_store.py`: SQLite por defecto, Mongo opcional; ADR-0005); conectado al Agente Clínico |
| `data/generate_patients.py` | ✅ 5 perfiles sintéticos (P001–P005; P005 = descompensación severa) generando CSVs en `data/sample/` |
| Historial (schema + carga) | ✅ `data/load_history.py` carga los pacientes de `data/sample/` en el almacén (`data/tp2.db` por defecto; idempotente, conserva sesiones). MongoDB opcional vía Docker Compose (`docker/`) |
| RAG — ingestión (`rag/ingest.py`) | ✅ chunking (con tamaño mínimo por corte) + embeddings locales + ChromaDB persistido en `data/chroma_db/`; idempotente (upsert) y `--rebuild`; metadata `section`; config compartida en `rag/config.py`; parámetros en `rag/RAG_TUNING.md` |
| RAG — retrieval (`rag/retriever.py`) | ✅ `search_clinical_guidelines()` + `get_rag_fragment()`; probar con `uv run python rag/retriever.py` |
| RAG — tools LangChain (`tools/rag_tools.py`) | ✅ `search_clinical_guidelines_tool` y `get_rag_context_tool` listos para el Agente Clínico (C) |
| `interface/components.py` | ✅ funciones puras de render (alertas, tendencias, perfil, reporte, visor de logs, visor de evaluación); testeables sin Gradio |
| `tests/test_clinico_tools.py`, `tests/test_history_store.py` | ✅ historial determinístico (SQLite temporal por test, `conftest.py`); RAG como integración (`@pytest.mark.integration`, requiere el índice de ChromaDB); ingesta determinística en `tests/test_rag_ingest.py` |
| `tests/cases/*.json` + `tests/eval_runner.py` | ✅ evaluación **cualitativa** de la IA (9 casos: 3 happy / 3 edge / 3 adversarial); script (no pytest) que vuelca `logs/eval_report.json` con esperado vs. obtenido; se lee desde la pestaña **Evaluación** de la UI Gradio (selector de corrida + caso) para comparar a ojo (germen del LLM-as-judge). Flags `-c/--category`, `--case`, `--list`, `--overwrite`; el JSON es un **historial append-only** (cada corrida = un elemento del array) para correr de a un caso sin agotar tokens. Cada caso lleva `status` (`ok`/`degraded`/`error`): **`degraded`** = el LLM falló y el grafo cayó al fallback determinístico (salida que NO refleja al modelo), detectado capturando los errores de `orchestrator.graph` |

## División de trabajo

Ver [docs/division_trabajo.md](docs/division_trabajo.md). Resumen:

- **A — Orquestador + Monitor**: `graph.py` (**Monitor y Clínico reales ya integrados**, falta
  router LLM), `router.py` (LLM pendiente), custodia de `state.py`,
  `agents/monitor.py` (**✅ implementado**), `tools/threshold_tools.py` (✅).
- **B — RAG + datos + MongoDB**: `rag/ingest.py`, `rag/retriever.py`,
  `data/generate_patients.py`, schema e instancia de MongoDB, `tools/rag_tools.py`.
- **C — Tools del Monitor + Clínico**: `tools/patient_tools.py` (5 funciones; stubs de Mongo
  eliminados tras integrar B), `agents/clinical.py` (**✅ implementado**, modos reporte y
  seguimiento; conectado a `tools/mongo_tools.py` y `rag/retriever.py` reales).
- **D — Interfaz + observabilidad + evaluación**: `interface/*.py` (**✅ UI completa**),
  `tests/test_clinico_tools.py` (✅), evaluación cualitativa `tests/eval_runner.py` + `tests/cases/*.json` (✅; ver [docs/tests.md](docs/tests.md)).

Coordinación crítica:
- **A ↔ C** sincronizados: A integra en el grafo lo que C implementa; cualquier cambio de
  firma de una tool se coordina antes de commitear.
- **B desbloquea a C**: prioridad de B la primera semana = schema de MongoDB + datos
  sintéticos antes que el RAG.
- **D independiente** hasta la integración (Streamlit con mocks, luego conecta al grafo).
- Si C va sobrecargado, `compare_with_previous_sessions()` y `update_patient_history()`
  pueden pasar a B (operan sobre MongoDB).

## Próximos pasos

> **Fuente de verdad de las correcciones pendientes: [docs/plan_correcciones.md](plan_correcciones.md)**
> (revisión del 2026-09-15, fases F0–F4). Si esta lista lo contradice, manda el plan.
> **Prioridad actual: [docs/plan_mvp.md](plan_mvp.md)** (qué entra al MVP y en qué orden).

1. ~~Reemplazar el stub del Monitor por agente real~~ **✅ HECHO**
2. ~~Implementar `agents/clinical.py` (Agente Clínico real) e integrar en `graph.py`~~ **✅ HECHO**
3. ~~Conectar MongoDB real y RAG real (B)~~ **✅ HECHO** (merge `dev/B`; stubs eliminados).
4. ~~Completar la interfaz Gradio + `interface/components.py`~~ **✅ HECHO** (merge UI).
5. ~~Agregar el nodo de persistencia~~ **✅ HECHO** (F1-04, ADR-0008): nodo `save` → `update_patient_history`.
6. Reemplazar la heurística de `router.py` por clasificación vía LLM.
7. ~~Completar el harness de evaluación de D~~ **✅ HECHO**: evaluación cualitativa con `tests/eval_runner.py` + `tests/cases/*.json` (ver [docs/tests.md](docs/tests.md)).
8. ~~Detección de "datos insuficientes" en el Agente Clínico real~~ **✅ HECHO** (F1-06, ADR-0010): criterio determinístico común (`information_sufficient_for`); la versión estructurada con LLM es F3-02.
```
