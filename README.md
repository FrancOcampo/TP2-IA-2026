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

**Esperado:** `45 passed, 9 deselected, 9 xfailed`. Los 9 xfailed son los tests de regresión de `tests/test_regresiones.py` (bugs pendientes de `docs/plan_correcciones.md`). Los 9 deselected son los 8 tests de integración
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
MongoDB y al RAG. Requiere, además de `uv`:

- **Groq API key** — LLM (`llama-3.3-70b`) de los agentes Monitor y Clínico.
- **[Ollama](https://ollama.com/)** con el modelo `nomic-embed-text` — embeddings del RAG.
- **MongoDB** local (Docker es lo más simple) — historial de pacientes.
- **LangSmith API key** *(opcional)* — observabilidad en la nube.

### Preparación

**1. Credenciales.** Completá `GROQ_API_KEY` (y, opcionalmente, `LANGSMITH_*`) en `.env`.

**2. MongoDB (vía Docker o Local Nativo).** Levantá una instancia en el puerto `27017`:

*   **Opción A (Docker Compose — recomendado):** con **Docker Desktop** abierto, desde la
    raíz del repo:
    ```bash
    docker compose -f docker/docker-compose.yml up -d
    ```
    Levanta `mongo:7` (contenedor `tp2-mongo`), persiste en el volumen `tp2-mongo-data` y
    crea la base `tp2_diabetes` con su índice. Detalle de comandos en
    [docker/README.md](docker/README.md). *(Equivalente en un solo comando sin Compose:
    `docker run -d --name tp2-mongo -p 27017:27017 -v tp2-mongo-data:/data/db mongo:7`.)*
*   **Opción B (Local Nativo - Windows):** Si no usás Docker, podés iniciar MongoDB localmente con los binarios de tu instalación ejecutando:
    ```powershell
    & ".local\mongodb\bin\mongod.exe" --dbpath ".local\mongodb\data" --port 27017 --bind_ip_all --setParameter diagnosticDataCollectionEnabled=false
    ```
    *(El parámetro `--setParameter diagnosticDataCollectionEnabled=false` es fundamental en entornos Windows para prevenir crashes vinculados a la colección de datos de diagnóstico).*

El código se conecta a `mongodb://localhost:27017` por defecto (db `tp2_diabetes`, colección `patients`). Si estás en Windows y experimentás problemas o demoras en la conexión por la resolución IPv6 de localhost, definí `MONGO_URI=mongodb://127.0.0.1:27017` en tu `.env`.

**3. Ollama (embeddings del RAG).** Instalá [Ollama](https://ollama.com/), asegurate de que el
servicio esté corriendo (`http://localhost:11434`) y descargá el modelo:

```bash
ollama pull nomic-embed-text
```

**4. Cargar datos e indexar guías** (una sola vez):

```bash
uv run python data/load_mongo.py    # carga los 4 pacientes en MongoDB
uv run python rag/ingest.py         # indexa las guías clínicas en ChromaDB
```

> **Nota sobre la ingesta del RAG.** `data/chroma_db/` está en `.gitignore`, así que un clon
> nuevo no lo trae: hay que correr `rag/ingest.py` al menos una vez. El proceso de indexación
> está optimizado para subir los chunks a ChromaDB en lotes (batches de 50) y se completa en 
> menos de 30 segundos. Si `data/chroma_db/` ya está poblado, no es necesario re-ejecutarlo.

### Verificación del modo completo

```bash
uv run pytest -m integration        # requiere MongoDB + Ollama + ChromaDB activos
```

Con la infraestructura activa, al **Analizar** un paciente en la UI verás reportes redactados por
el LLM y, en la pestaña *Observabilidad*, la secuencia completa `node_start → tool_* → llm_*`.

### Arranque con todo ya instalado e indexado

Una vez hecha la instalación y la carga inicial (pasos 1–4 de arriba), en el uso cotidiano
**normalmente alcanza con un solo comando**:

```bash
uv run python -m interface.app    # interfaz web (modo completo) → http://127.0.0.1:7860
```

Ollama (app de Windows) y el contenedor de Mongo (`restart: unless-stopped`) se auto-inician al
encender la PC / abrir Docker Desktop, así que casi siempre solo hace falta ese comando. Si Mongo no quedó levantado, primero:

```bash
docker compose -f docker/docker-compose.yml up -d
```

**No** hay que repetir `data/load_mongo.py` ni `rag/ingest.py`: se corren **una sola vez** (los
datos persisten en el volumen de MongoDB y en `data/chroma_db/`). Solo se re-ejecutan si cambian
los datos de los pacientes o las guías clínicas.

---

## Estructura del repo

```
orchestrator/   state.py (estado + modelos) · graph.py (grafo LangGraph) · router.py (routing)
agents/         prompts.py · monitor.py (ReAct) · clinical.py (ReAct)
tools/          patient_tools.py · threshold_tools.py · mongo_tools.py · rag_tools.py
rag/            ingest.py (indexa en ChromaDB) · retriever.py (búsqueda)
data/           generate_patients.py · load_mongo.py · guias/ · sample/ (fixture P001-P004)
interface/      app.py (UI Gradio) · components.py (render) · logging_config.py (logs)
tests/          test_graph.py · test_monitor_tools.py · test_clinico_tools.py (integración) · eval_runner.py · cases/ · ver docs/tests.md
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
