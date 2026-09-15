# Estado del Proyecto TP2-IA — Análisis al 26/06/2026

> **Contexto:** La 2ª entrega (22/06) ya pasó. La **entrega final es el 29/06** (en 3 días).
> El backend está completo y el pipeline corre end-to-end con agentes reales. La evaluación
> (incluida la cualitativa de la IA) ya está armada; ver [docs/tests.md](tests.md).

---

## 📊 Resumen rápido por integrante

| Integrante | Responsabilidad | Progreso | Bloqueante |
|---|---|---|---|
| **A** | Orquestador + Monitor agéntico | 🟢 ~90% | Ninguno. Falta solo (opcional) router por LLM y el nodo de persistencia `save`. |
| **B** | RAG + Datos + MongoDB | 🟢 ~100% | Ninguno. RAG (ingest+retriever), MongoDB (schema+carga, **Docker y local**) y datos sintéticos en `main`. |
| **C** | Tools Monitor + Clínico | 🟢 ~95% | Ninguno. Agente Clínico real conectado a Mongo+RAG reales. |
| **D** | Interfaz + Observabilidad + Evaluación | 🟢 ~100% | Ninguno. Evaluación cualitativa + tests por objetivo completos ([docs/tests.md](tests.md)). |

---

## 🧰 Entorno y dependencias (cómo correr el proyecto)

Todo el stack de **Python** lo gestiona **uv** desde `pyproject.toml` (`uv sync`): incluye
`langchain`, `langgraph`, `langchain-groq`, `chromadb`, `pymongo`, `gradio`, `pydantic`,
`ollama` (cliente), etc. **No hace falta instalar paquetes a mano.**

| Programa / servicio | ¿Cuándo se necesita? | Estado típico |
|---|---|---|
| **uv** | Siempre (entorno + dependencias). | Instalado en `C:\Users\marco\.local\bin`. |
| **Groq API key** | Modo completo (agentes ReAct reales). | En `.env` (`GROQ_API_KEY`). |
| **MongoDB** (Docker o local) | Modo completo (historial de pacientes). | Ver abajo: **Docker Compose** o local nativo. |
| **Ollama** + `nomic-embed-text` | Modo completo (embeddings del RAG / ChromaDB). | **Externo**: instalar desde ollama.com y `ollama pull nomic-embed-text`. |
| **ChromaDB** | Modo completo (vector store de guías). | Lib Python (vía `uv`); persiste en `data/chroma_db/`. Requiere Ollama para indexar. |

- **Modo básico** (sin servicios externos): solo `uv`. El grafo cae a fallbacks
  determinísticos y la UI corre sobre el fixture `data/sample/`. Ideal para verificar que
  arranca. Ver *Inicio rápido* en el [README](../README.md).
- **Modo completo**: `uv` + Groq + MongoDB + Ollama (embeddings) + ChromaDB indexado.

### MongoDB: Docker Compose **o** local nativo

El historial de pacientes vive en MongoDB (`mongodb://localhost:27017`, db `tp2_diabetes`,
colección `patients`). Hay dos formas de levantarlo, intercambiables (el código no cambia):

- **Docker Compose (recomendado).** Con Docker Desktop abierto:
  ```bash
  docker compose -f docker/docker-compose.yml up -d   # levanta mongo:7 (contenedor tp2-mongo)
  uv run python data/load_mongo.py                     # carga P001–P004
  ```
  Persiste en el volumen `tp2-mongo-data` y crea la base + índice vía `docker/mongo-init.js`.
  Comandos completos en [docker/README.md](../docker/README.md).
- **Local nativo (sin Docker).** Iniciar el `mongod` de una instalación local en el puerto
  27017 (en Windows, con `--setParameter diagnosticDataCollectionEnabled=false` para evitar
  crashes). Ver la sección *Modo completo → MongoDB* del [README](../README.md).

> En Windows, `MONGO_URI=mongodb://127.0.0.1:27017` (ya viene en `.env`/`.env.example`)
> evita demoras por la resolución IPv6 de `localhost`. Si MongoDB no está disponible, las
> tools de Mongo degradan con gracia (historial vacío) y el pipeline sigue corriendo.

---

## 🔍 Estado detallado por integrante (verificado contra el código)

### Integrante A — Orquestador + Agente Monitor

| Archivo | Estado | Detalle |
|---|---|---|
| state.py | ✅ Hecho | Modelos Pydantic completos (`AgentState`, `PatientMetrics`, `Alert`, `MonitorAnalysis`, `MetricStats`, `Medication`, `TimeRange`, etc.). Contrato compartido custodiado. |
| graph.py | ✅ Hecho | Grafo end-to-end con Monitor y Clínico **reales** (ReAct) + fallbacks determinísticos sin API key. Loop de refinamiento (guardrail 3 iteraciones). |
| router.py | 🟡 Heurística | Routing por keywords. **Opcional**: reemplazar por clasificación vía LLM (queda heurística como fallback). |
| prompts.py | ✅ Hecho | System + human prompts de los 3 agentes. |
| monitor.py | ✅ Hecho | Agente Monitor ReAct (ChatGroq + 4 tools LangChain), ensambla `MonitorAnalysis`. |
| threshold_tools.py | ✅ Hecho (con C) | Umbrales ADA, hiper **e** hipoglucemia. |

**Lo que falta de A (no bloqueante):**
1. ⬜ Router por LLM en `orchestrator/router.py` (opcional).
2. ⬜ **Nodo de persistencia (`save`)** — ver nota dedicada abajo.

> [!NOTE]
> **Estado de "Guardar sesión" (botón de la UI).** Al confirmar el guardado, hoy el grafo
> enruta a la rama `save`, que **termina en `END` sin escribir nada** ([graph.py](../orchestrator/graph.py),
> `route_from_orchestrator` → `"save": END`). Por eso la UI avisa que la persistencia "todavía
> no está activa".
>
> **Reparto del trabajo (para que quede claro de quién es):**
> - La **tool de escritura** `tools/mongo_tools.update_patient_history` **ya está implementada**
>   (la entregó B/C, opera sobre MongoDB real). **No es un pendiente.**
> - Lo único que falta es **cablear el nodo `save`** en `orchestrator/graph.py` para que llame a
>   esa tool con el reporte, las alertas y el `metrics_summary` de la sesión, y luego termine.
>   Eso es **trabajo del Orquestador (Integrante A)**, no de B ni de D. Marcado con `TODO` en el
>   código ([graph.py](../orchestrator/graph.py), en `route_from_orchestrator`).

---

### Integrante B — RAG + Datos + MongoDB

| Archivo | Estado | Detalle |
|---|---|---|
| generate_patients.py | ✅ Hecho | 4 perfiles sintéticos (P001–P004) en CSV. |
| ingest.py | ✅ Hecho | Chunking + embeddings `nomic-embed-text` (Ollama) → ChromaDB en `data/chroma_db/`. Ingesta por lotes (batches de 50), < 30 s. |
| retriever.py | ✅ Hecho | `search_clinical_guidelines()` y `get_rag_fragment()`. |
| rag_tools.py | ✅ Hecho | Wrappers LangChain (`search_clinical_guidelines_tool`, `get_rag_context_tool`). |
| mongo_tools.py | ✅ Hecho | `get_patient_history`, `compare_with_previous_sessions`, `update_patient_history` sobre MongoDB real, con degradación si Mongo no está disponible. |
| MongoDB (infra) | ✅ Hecho | **Docker Compose** (`docker/docker-compose.yml`, contenedor `tp2-mongo`, volumen persistente, init script) **y** local nativo. `data/load_mongo.py` carga `tp2_diabetes.patients`. |

**Lo que falta de B:** nada bloqueante. El modo completo requiere MongoDB, Ollama y la
ingesta de ChromaDB levantados (ver sección de entorno y README).

---

### Integrante C — Tools del Monitor + Agente Clínico

| Archivo | Estado | Detalle |
|---|---|---|
| patient_tools.py | ✅ Hecho | `load_patient_data`, `calculate_stats`, `get_medication_schedule`, `window_metrics`, `_compute_stats`. Determinístico sobre el EHR. |
| threshold_tools.py | ✅ Hecho (con A) | Completo. |
| clinical.py | ✅ Hecho | Agente Clínico ReAct (modos Reporte y Seguimiento), conectado a `tools/mongo_tools.py` y `rag/retriever.py` reales (stubs eliminados). |

**Lo que falta de C:** nada bloqueante. Recomendado: validar el Clínico end-to-end con
MongoDB + ChromaDB reales levantados.

---

### Integrante D — Interfaz + Observabilidad + Evaluación

| Archivo | Estado | Detalle |
|---|---|---|
| logging_config.py | ✅ Hecho | `setup_logging()` + `LoggingCallbackHandler`, dual output (consola + `logs/agent.jsonl`). Captura `llm_*`/`tool_*` (tokens + nombre de tool). |
| app.py | ✅ Hecho | UI Gradio: **Consulta clínica** (perfil, contexto, análisis, reporte, alertas/tendencias, chat de seguimiento), **Observabilidad (dev)** (visor de log + JSON crudo) y **Evaluación** (comparación esperado vs. obtenido desde `logs/eval_report.json`). |
| components.py | ✅ Hecho | Funciones puras de render (`severity_badge`, `alerts_table`, `trends_view`, `patient_profile`, `format_report`, `list_patients`, `load_log_entries`, y el visor de evaluación: `load_eval_history`, `eval_history_summary_md`, `eval_run_choices`, `get_eval_run`, `eval_summary_md`, `eval_case_choices`, `eval_case_view`). |
| test_clinico_tools.py | ✅ Hecho | Tools del Clínico (mongo_tools + RAG), integración (`@pytest.mark.integration`); requieren MongoDB + Ollama + ChromaDB. |
| test_graph.py / test_monitor_tools.py | ✅ Hecho (A/C) | Plomería del grafo (2 modos) + tools del Monitor. Ver [docs/tests.md](tests.md). |
| `tests/cases/*.json` + `tests/eval_runner.py` | ✅ Hecho | Evaluación **cualitativa** de la IA (9 casos: 3 happy / 3 edge / 3 adversarial). Script (no pytest) → `logs/eval_report.json`, comparable desde la pestaña **Evaluación** de la UI. Ver [docs/tests.md](tests.md). |

**Lo que falta de D:** nada bloqueante. La evaluación quedó completa.

> [!NOTE]
> **Decisión de testing:** los tests se organizan **por objetivo** (tools / plomería del grafo /
> calidad de la IA), no por taxonomía unit-vs-integración. La evaluación de los ejes
> happy/edge/adversarial es **cualitativa y manual** (`eval_runner.py`), no un test de pytest.
> Detalle y fundamentos en **[docs/tests.md](tests.md)**.
>
> **Brecha A/C (no de tests):** el Agente Clínico real considera 1 fila (P004) como información
> suficiente, así que el loop de refinamiento solo se dispara en el fallback. El gate de
> `test_graph.py` corre en modo determinístico (no se rompe); cerrar la detección en el agente
> real queda como mejora de comportamiento.

---

## ✅ Cómo verificar el estado actual

```bash
uv sync                              # entorno (147 paquetes; idempotente)
uv run pytest -m "not integration and not llm"   # gate determinístico: 45 passed, 9 deselected, 9 xfailed
uv run python -m interface.app       # UI en http://127.0.0.1:7860
```

Para el modo completo, además: `.env` con `GROQ_API_KEY`, MongoDB arriba (Docker o local) +
`uv run python data/load_mongo.py`, Ollama con `nomic-embed-text` + `uv run python rag/ingest.py`,
y luego `uv run pytest -m integration`.

---

## 🎯 Siguientes pasos prioritarios para el 29/06

| # | Tarea | Resp. | Prioridad |
|---|---|---|---|
| 1 | Detección de "datos insuficientes" en el Agente Clínico real (hoy solo en el fallback) | A/C | 🟡 Media |
| 2 | Nodo de persistencia `save` → `update_patient_history` | A | 🟡 Media |
| 3 | Router por LLM en `router.py` (queda heurística como fallback) | A | 🟢 Baja (opcional) |

---

## ⏰ Resumen de riesgos para el 29/06

| Riesgo | Severidad | Mitigación |
|---|---|---|
| **Evaluación cualitativa sin correr con LLM** | 🟢 Bajo | Los casos y el `eval_runner.py` están listos; falta solo ejecutarlo con API key y puntuar el artefacto antes del coloquio. |
| **Modo completo no reproducible en otra máquina** | 🟢 Bajo | Mitigado: MongoDB vía Docker Compose (`docker/`), `uv sync` para deps, README con pasos de Ollama/ChromaDB. |
| **Pipeline no corre sin infraestructura** | 🟢 Resuelto | El modo básico corre 100% con fallbacks determinísticos; las tools de Mongo degradan con gracia. |
