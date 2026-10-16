# Estrategia de testing

Esta es la fuente de verdad de **cómo y por qué** se organizan los tests del proyecto.
Los encabezados de cada archivo de test solo apuntan acá para no duplicar información.

## Principio: organizar por OBJETIVO, no por taxonomía

No separamos "tests unitarios" de "tests de integración" como estructura. Organizamos por
**qué se está validando**, porque eso es lo que importa para este sistema: que las **tools**
sean correctas, que el **grafo** coordine bien, y que el **resultado final de la IA** sea de
buena calidad. La distinción unit/integración sobrevive únicamente como **marcador de
ejecución** (`integration`, `llm`), para poder correr el subconjunto que no necesita
infraestructura ni LLM cuando no se cuenta con ellos.

## Los cuatro objetivos

| Archivo | Objetivo | Determinismo | Cómo correr |
|---|---|---|---|
| [`tests/test_monitor_tools.py`](../tests/test_monitor_tools.py) | Tools del Monitor (stats, umbrales ADA) | Determinístico, sin infra | siempre |
| [`tests/test_clinico_tools.py`](../tests/test_clinico_tools.py) | Tools del Clínico (MongoDB, RAG) | Integración (`integration`) | con infra |
| [`tests/test_graph.py`](../tests/test_graph.py) | Plomería: grafo, nodos, comunicación, guardrail | Determinístico (default) **+** estocástico (`llm`) | gate siempre; `llm` con API key |
| [`tests/eval_runner.py`](../tests/eval_runner.py) | **Calidad del output final de la IA** | Cualitativo, manual | `uv run python tests/eval_runner.py` |

### 1. Tools — `test_monitor_tools.py` y `test_clinico_tools.py`
Verifican **determinísticamente** que las funciones que usan los agentes calculan lo correcto
(mismo input → mismo output). Las del Monitor son puras (corren sin nada). Las del Clínico
cruzan I/O (ChromaDB indexado), así que son de integración; no agregamos una capa
"offline mockeada" porque levantar la infra es trivial y los mocks no aportarían valor real.

### 2. Plomería — `test_graph.py` (dos modos explícitos)
- **Determinístico** (gate de CI): un fixture autouse **fuerza el fallback sin LLM** quitando
  las API keys. Es rápido y reproducible, y no depende de si hay una key en el entorno.
- **Estocástico** (marcador `llm`): invoca el **LLM real** y valida que los agentes se cablean
  y el grafo termina, con **aserciones laxas/estructurales** (no resultados exactos, que serían
  no determinísticos). La calidad del contenido NO se juzga acá.

### 3. Calidad de la IA — `eval_runner.py` (NO es pytest)
Los tres ejes del enunciado (happy path / edge cases / adversarial) evalúan el **resultado
final del flujo agéntico**, y eso es **cualitativo**: no se puede afirmar `assert` sobre la
redacción de un LLM. Por eso:
- **No** testea tools, funciones ni pasos intermedios — solo el output final.
- **No** es un test de pytest (no tiene sentido un pass/fail sobre calidad subjetiva). Es un
  **script** que corre los casos de [`tests/cases/*.json`](../tests/cases/) con LLM real y vuelca
  un artefacto JSON (`logs/eval_report.json`, *esperado vs. obtenido*) que la pestaña
  **Evaluación** de la interfaz Gradio lee para que un humano compare y puntúe.
- A futuro, ese juicio manual se reemplaza por un **LLM-as-judge**.
- Inevitablemente, al necesitar el resultado final, ejercita de forma indirecta toda la
  integración y la comunicación entre agentes — pero validar la plomería en sí es trabajo de
  `test_graph.py`, no de acá.

Los casos siguen el schema: `{ id, category, description, setup?, input, expected_behavior }`.

## Comandos

```bash
uv run pytest -m "not integration and not llm"   # gate determinístico (rápido, sin infra/LLM)
uv run pytest tests/test_clinico_tools.py         # tools del Clínico, todos (requiere infra)
uv run pytest -m llm                              # plomería con LLM real (requiere API key)
uv run python tests/eval_runner.py                # evaluación cualitativa → logs/eval_report.json (se lee en la pestaña «Evaluación»)
```

La evaluación acepta flags para correr un subconjunto y **no agotar los tokens** del proveedor de
una sola vez. El JSON es un **historial append-only**: cada ejecución agrega una "corrida" (un
objeto con solo los casos evaluados esa vez) al array, conservando el historial completo:

```bash
uv run python tests/eval_runner.py --list                 # lista los casos y sale (sin API key)
uv run python tests/eval_runner.py -c happy               # una categoría (alias: happy/edge/adv) → nueva corrida
uv run python tests/eval_runner.py --case happy_01        # un único caso → nueva corrida
uv run python tests/eval_runner.py -c edge --case edge_03 # intersección categoría ∩ id
uv run python tests/eval_runner.py --overwrite            # descarta el historial y empieza de cero
```

La pestaña **Evaluación** de la UI tiene un selector de **corrida** (más reciente arriba) y, dentro
de ella, un selector de **caso** con la comparación esperado vs. obtenido lado a lado.

Cada caso lleva un `status`: `ok`, `degraded` o `error`. **`degraded`** marca que el LLM falló
durante la corrida (rate limit, 413, timeout…) y el grafo cayó a su **fallback determinístico**:
la salida existe pero **no refleja al modelo**, así que no hay que puntuarla como si lo hiciera.
El runner lo detecta capturando los errores de fallback que loguea `orchestrator.graph`, y la UI lo
señala (🟠 en el selector y un aviso en el panel de salida). `error` = el caso crasheó entero.
