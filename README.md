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
| 4 | **Historial de pacientes** | Lectura del EHR (Electronic Health Record) y comparación entre sesiones desde MongoDB. |
| 5 | **Interfaz web (Gradio)** | Pestaña *Consulta clínica* (perfil del paciente, análisis, reporte, alertas, tendencias, chat de seguimiento) y *Observabilidad (dev)*. |
| 6 | **Observabilidad** | Logs en consola + `logs/agent.jsonl` estructurado, integrables con LangSmith. |
| 7 | **Modo fallback determinístico** | Si no hay `GROQ_API_KEY` ni servicios externos, el grafo corre con resultados determinísticos. Permite probar todo sin infraestructura. |

---

## Inicio rápido (modo básico, < 10 min)

Este modo **no requiere servicios externos** (ni LLM, ni base de datos): el grafo cae a los
fallbacks determinísticos y la UI funciona sobre el fixture local `data/sample/`. Es la vía más
rápida para verificar que el proyecto arranca y se comporta como se espera.

### Requisito previo

- **[uv](https://docs.astral.sh/uv/)** (gestor de entorno y dependencias). Instala Python 3.12+
  automáticamente. No hace falta nada más en este modo.

### Pasos

```bash
uv sync                              # 1. instala dependencias (crea el .venv)
cp .env.example .env                 # 2. crea el archivo de entorno (Windows: Copy-Item .env.example .env)
uv run pytest -m "not integration and not llm"   # 3. solo gate determinístico, sin infra ni LLM (~2 s)
uv run python -m interface.app       # 4. levanta la interfaz web
```

Abrí **http://127.0.0.1:7860** en el navegador.

---

## Cómo verificar que funciona

### 1. Tests

```bash
uv run pytest -m "not integration and not llm"
```

**Esperado:** `49 passed, 9 deselected, 8 xfailed`. Los 8 xfailed son los tests de regresión de `tests/test_regresiones.py` (bugs pendientes de `docs/plan_correcciones.md`). Los 9 deselected son los 8 tests de integración
(requieren la infraestructura del modo completo, ver abajo) + 1 test estocástico que invoca
el LLM real. Estrategia de testing completa en [docs/tests.md](docs/tests.md).

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

## Modo completo (LLM + datos reales)

Opcional. Activa los **agentes ReAct reales** (en vez de los fallbacks) y consultas reales a
historial y al RAG. Requiere, además de `uv`:

- **Groq API key** — LLM (`llama-3.3-70b`) de los agentes Monitor y Clínico.
- **[Ollama](https://ollama.com/)** con el modelo `nomic-embed-text` — embeddings del RAG.
- **LangSmith API key** *(opcional)* — observabilidad en la nube.

### Preparación

**1. Credenciales.** Completá `GROQ_API_KEY` (y, opcionalmente, `LANGSMITH_*`) en `.env`.

**2. Historial de pacientes.** Por defecto es un archivo **SQLite local** (`data/tp2.db`, fuera de
git): no hay que instalar nada. Para usar **MongoDB** (Docker o nube) definí
`HISTORY_BACKEND=mongo` y `MONGO_URI` en `.env`; ver [docker/README.md](docker/README.md) y
[ADR-0005](docs/adr/0005-historial-en-sqlite-local.md).

**3. Ollama (embeddings del RAG).** Instalá [Ollama](https://ollama.com/), asegurate de que el
servicio esté corriendo (`http://localhost:11434`) y descargá el modelo:

```bash
ollama pull nomic-embed-text
```

**4. Cargar datos e indexar guías** (una sola vez):

```bash
uv run python data/load_history.py  # carga los pacientes en el historial (SQLite por defecto)
uv run python rag/ingest.py         # indexa las guías clínicas en ChromaDB
```

> **Nota sobre la ingesta del RAG.** `data/chroma_db/` está en `.gitignore`, así que un clon
> nuevo no lo trae: hay que correr `rag/ingest.py` al menos una vez. El proceso de indexación
> está optimizado para subir los chunks a ChromaDB en lotes (batches de 50) y se completa en 
> menos de 30 segundos. Si `data/chroma_db/` ya está poblado, no es necesario re-ejecutarlo.

### Verificación del modo completo

```bash
uv run pytest -m integration        # requiere Ollama + ChromaDB indexado
```

Con la infraestructura activa, al **Analizar** un paciente en la UI verás reportes redactados por
el LLM y, en la pestaña *Observabilidad*, la secuencia completa `node_start → tool_* → llm_*`.

### Arranque con todo ya instalado e indexado

Una vez hecha la instalación y la carga inicial (pasos 1–4 de arriba), en el uso cotidiano
**normalmente alcanza con un solo comando**:

```bash
uv run python -m interface.app    # interfaz web (modo completo) → http://127.0.0.1:7860
```

Ollama (app de Windows) se auto-inicia al encender la PC, así que casi siempre solo hace falta ese comando.

**No** hay que repetir `data/load_history.py` ni `rag/ingest.py`: se corren **una sola vez** (los
datos persisten en `data/tp2.db` y en `data/chroma_db/`). Solo se re-ejecutan si cambian
los datos de los pacientes o las guías clínicas.

---

## Estructura del repo

```
orchestrator/   state.py (estado + modelos) · graph.py (grafo LangGraph) · router.py (routing)
agents/         prompts.py · monitor.py (ReAct) · clinical.py (ReAct)
tools/          patient_tools.py · threshold_tools.py · history_store.py · history_tools.py · rag_tools.py
rag/            ingest.py (indexa en ChromaDB) · retriever.py (búsqueda)
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
