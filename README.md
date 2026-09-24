# TP2 — Sistema Multi-Agente de Soporte Clínico para Diabetes

Sistema multi-agente (LangGraph) de **soporte a la decisión clínica** para el seguimiento de
pacientes con diabetes tipo 2. Tres agentes coordinados —**Orquestador**, **Monitor** y
**Clínico**— analizan el historial del paciente, detectan valores fuera de rango y producen un
reporte estructurado consultando guías clínicas (RAG). **No emite diagnósticos.**


**Link del repositorio remoto**: https://github.com/MarcosDebona25/TP2-IA-2026.git

---

## Funcionalidades

| # | Funcionalidad | Descripción |
|---|---|---|
| 1 | **Pipeline multi-agente** | Orquestador enruta la consulta → Monitor (análisis) → Clínico (reporte), con loop de refinamiento. Orquestado con LangGraph. |
| 2 | **Análisis cuantitativo determinístico** | Estadísticas por métrica (último, media, mín, máx, Δ, dirección) y detección de umbrales ADA: hiper **e** hipoglucemia. |
| 3 | **RAG sobre guías clínicas** | El agente Clínico fundamenta el reporte con fragmentos de guías (ADA / SAD / Guía Nacional) recuperados de ChromaDB. |
| 4 | **Historial de pacientes** | Lectura del EHR (Electronic Health Record) y comparación entre sesiones guardadas (SQLite local; MongoDB opcional). |
| 5 | **Interfaz web (Gradio)** | Pestaña *Consulta clínica* (perfil del paciente, análisis, reporte, alertas, tendencias, chat de seguimiento) y *Observabilidad (dev)*. |
| 6 | **Observabilidad** | Logs en consola + `logs/agent.jsonl` estructurado, integrables con LangSmith. |
| 7 | **Modo fallback determinístico** | Si no hay API key de LLM, el grafo corre con resultados determinísticos y la UI lo indica. Permite probar todo sin infraestructura. |

---

## Inicio rápido (3 comandos)

Requisito único: **[uv](https://docs.astral.sh/uv/)** (instala Python 3.12+ automáticamente).
No hace falta Docker, MongoDB ni Ollama: el historial es un archivo SQLite local y los embeddings
del RAG corren en proceso ([plan MVP](docs/plan_mvp.md)).

```bash
uv sync                      # 1. instala dependencias (crea el .venv)
cp .env.example .env         # 2. crea el entorno (Windows: Copy-Item .env.example .env) y completá GROQ_API_KEY
uv run python main.py        # 3. prepara historial + índice de guías (solo lo que falte) y abre la UI
```

Abrí **http://127.0.0.1:7860**. La primera vez, `main.py` indexa las guías clínicas (~2-3 min y
~80 MB del modelo de embeddings); después arranca en segundos. Todo es idempotente: las sesiones
guardadas se conservan entre arranques.

**Sin API key** el sistema funciona igual en **modo determinístico** (fallbacks sin LLM) y la UI
lo avisa arriba. Con `GROQ_API_KEY` (gratis en [console.groq.com](https://console.groq.com/keys))
los agentes Monitor y Clínico usan `llama-3.3-70b-versatile`; para Gemini, ver `.env.example`.

| Dónde vive | Qué | Cómo se regenera |
|---|---|---|
| `data/tp2.db` | Historial de pacientes y sesiones guardadas (SQLite) | `uv run python data/load_history.py` (conserva sesiones) |
| `data/chroma_db/` | Índice de las guías clínicas | `uv run python rag/ingest.py --rebuild` |
| `logs/agent.jsonl` | Trazas estructuradas | se crea solo |

Opciones: `main.py --port 7861`, `--skip-index` (no indexar), `--no-ui` (solo preparar).
Para usar MongoDB u Ollama: [ADR-0005](docs/adr/0005-historial-en-sqlite-local.md),
[ADR-0006](docs/adr/0006-embeddings-locales-sin-ollama.md), [docker/README.md](docker/README.md).

---

## Cómo verificar que funciona

### 1. Tests

```bash
uv run pytest -m "not integration and not llm"   # gate determinístico, sin LLM (~5 s)
uv run pytest -m integration                      # retrieval real (requiere el índice de guías)
```

**Esperado del gate:** todo en verde; los `xfailed` son los tests de regresión de
`tests/test_regresiones.py` (bugs pendientes de [docs/plan_correcciones.md](docs/plan_correcciones.md)).
Los `deselected` son los de integración + el test estocástico que invoca al LLM real.
Estrategia de testing completa en [docs/tests.md](docs/tests.md).

### 2. Interfaz — Consulta clínica

En la pestaña **Consulta clínica**: elegí un paciente, opcionalmente escribí un contexto
clínico (información adicional para que el agente tenga en cuenta), y presioná **Analizar paciente**. El sistema devuelve **reporte + alertas + tendencias**.
Cada paciente del fixture ejercita un caso distinto:

| Paciente | Caso | Comportamiento esperado |
|---|---|---|
| **P001** | Controlado | Reporte **sin alertas** (happy path). |
| **P002** | Tendencia ascendente | Alertas **moderadas/severas** y dirección `subiendo` en las métricas. |
| **P003** | Episodio de hipoglucemia | **Alerta de hipoglucemia moderada** (un mes con glucosa en ayunas = 55 mg/dL; el `mín` lo expone aunque la media lo diluya). |
| **P004** | Datos insuficientes | Una sola fila → dispara la rama de información insuficiente. |

El **chat de seguimiento** responde preguntas sobre el reporte ya generado (van directo al Clínico).

### 3. Interfaz — Observabilidad (dev)

En la pestaña **Observabilidad (dev)**: presioná **Refrescar** tras una consulta. Vas a ver la
traza estructurada del grafo. En modo básico aparecen eventos `node_start` y `routing`; en modo
completo se suman `llm_*` y `tool_*` (con tokens y nombre de tool).

También desde la terminal:

```bash
cat logs/agent.jsonl | jq
```

Detalle de los campos y eventos: [docs/logs.md](docs/logs.md). Más sobre la UI: [docs/interfaz.md](docs/interfaz.md).

---

## Estructura del repo

```
main.py         punto de entrada: bootstrap (historial + índice) y UI
orchestrator/   state.py (estado + modelos) · graph.py (grafo LangGraph) · router.py (routing)
agents/         prompts.py · monitor.py (ReAct) · clinical.py (ReAct)
tools/          patient_tools.py · threshold_tools.py · history_store.py · history_tools.py · rag_tools.py
rag/            config.py (embeddings) · ingest.py (indexa en ChromaDB) · retriever.py (búsqueda)
data/           generate_patients.py · load_history.py · guias/ · sample/ (fixture P001-P004)
interface/      app.py (UI Gradio) · components.py (render) · logging_config.py (logs)
tests/          test_graph.py · test_monitor_tools.py · test_clinico_tools.py · test_history_store.py · eval_runner.py · cases/ · ver docs/tests.md
docs/           definición conceptual, arquitectura (CLAUDE.md), interfaz, logs
```

---

## Comandos útiles

```bash
uv sync                              # instalar / actualizar el entorno
uv run pytest -m "not integration and not llm"   # gate determinístico (sin infra ni LLM)
uv run pytest                        # toda la suite (requiere modo completo: infra + API key)
uv run python -m interface.app       # levantar la interfaz web
uv lock                              # regenerar el lockfile tras cambiar dependencias
```

---

## Herramientas de desarrollo: graphify

El repo trae configurado [graphify](https://github.com/Graphify-Labs/graphify) para asistentes de código
(skill en `.claude/skills/graphify/` y hooks en `.claude/settings.json`). Los hooks llaman a `graphify`
por PATH, así que **cada integrante tiene que instalarlo** (si no, el asistente muestra un error no
bloqueante en cada lectura). Decisión y detalles: [ADR-0002](docs/adr/0002-graphify-para-navegacion-del-codigo.md).

```bash
uv tool install "graphifyy[office]"        # paquete oficial en PyPI (ojo: doble "y"; [office] lee .docx)
graphify install --project --platform claude   # (re)instala skill + hooks si hace falta
```

Construir el índice completo (código + documentos + diagramas) desde Claude Code:

```
/graphify .            # primera vez: AST local + paso semántico con subagentes del asistente
/graphify . --update   # después: re-extrae solo lo que cambió (docs incluidos)
```

Mantenimiento y consultas desde la terminal (sin costo de LLM):

```bash
graphify update .                          # refresca SOLO el código tras cambios
graphify query "¿qué nodos usan AgentState?"
```

Punto de entrada para navegar: `graphify-out/wiki/index.md`. Qué queda afuera del grafo (guías clínicas,
capturas, archivos de la skill): ver `.graphifyignore`.

`graphify-out/` no se versiona: es un artefacto regenerable.
