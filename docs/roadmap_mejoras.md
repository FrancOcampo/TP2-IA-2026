# Hoja de ruta — Mejoras post-entrega

> Generado el 2026-08-10 a partir de un relevamiento contra el código real (no solo la doc,
> que tenía ~6 semanas de desfasaje respecto al estado del repo) más research externo sobre
> prácticas 2026 para agentes multi-agente y evaluación. Ir tildando a medida que se resuelva
> cada punto; si algo deja de aplicar o cambia el diseño, actualizar este archivo en el mismo
> commit (mismo criterio que `docs/CLAUDE.md`).

---

## 0. Poner en marcha el modo completo (bloqueante para probar el resto)

- [ ] **Cambiar `LLM_PROVIDER=gemini`** en `.env`. La app ya soporta este branch nativamente
      (`agents/llm_factory.py`); usa la misma `GOOGLE_API_KEY` que ya está configurada y
      funcionando (la que se armó para `graphify`). Free tier de Gemini (1500 req/día, 1M TPM)
      es más holgado que el de Groq (30 RPM / ~14K req/día).
- [ ] **Corregir `GROQ_API_KEY`** — hoy tiene un valor inválido (placeholder de 1 carácter). No
      es bloqueante si se usa el punto anterior, pero conviene limpiarla o completarla bien
      para no confundir a quien clone el repo.
- [ ] **Levantar MongoDB**: `docker compose -f docker/docker-compose.yml up -d` +
      `uv run python data/load_mongo.py`.
- [ ] **Instalar Ollama + `nomic-embed-text`** (o resolver el punto 3 de la sección de mejoras
      para evitar esta dependencia) y correr `uv run python rag/ingest.py`.
- [ ] Verificar con `uv run pytest -m integration` (requiere Mongo + Ollama + ChromaDB activos).

---

## 1. Nodo de persistencia `save` (prioridad alta)

**Estado:** `orchestrator/graph.py` (`route_from_orchestrator`, rama `"save"` → `END`) no
persiste nada — hay un `TODO` explícito en el código (líneas ~205-209, ~259).

- [ ] Cablear un nodo `save` en `orchestrator/graph.py` que llame a
      `tools/mongo_tools.update_patient_history` (ya implementada, no hay que escribirla) con
      el reporte, las alertas y el `metrics_summary` de la sesión.
- [ ] Actualizar la UI (`interface/app.py`) para que deje de avisar que "la persistencia
      todavía no está activa" una vez cableado.
- [ ] Test de integración que confirme que el documento en Mongo se actualiza tras confirmar
      guardado.

---

## 2. Router por LLM en vez de heurística (prioridad media)

**Estado:** `orchestrator/router.py` decide por palabras clave (`_CONFIRM_WORDS`,
`is_followup_message` mirando substrings). Documentado como pendiente en `CLAUDE.md`.

- [ ] Reemplazar `is_followup_message` / detección de confirmación por una clasificación real
      del LLM del Orquestador.
- [ ] Usar **salida estructurada** (Pydantic + `with_structured_output` / function calling), no
      parseo de texto libre — ver punto 5.
- [ ] Mantener la heurística actual como fallback determinístico si no hay API key (mismo
      patrón que ya usan Monitor/Clínico).

---

## 3. RAG desacoplado de Ollama (prioridad media)

**Estado:** `rag/ingest.py` y `rag/retriever.py` están *hardcodeados* a
`OllamaEmbeddingFunction` / `nomic-embed-text`. Es la única pieza que sigue obligando a
instalar y correr Ollama localmente para el modo completo.

- [ ] Agregar un branch de embeddings **Gemini** (`models/text-embedding-004`, gratis) en
      `rag/ingest.py` y `rag/retriever.py`, seleccionable por env var (mismo patrón que
      `agents/llm_factory.py` con `LLM_PROVIDER`).
- [ ] Con esto, "modo completo" pasaría a requerir solo `GOOGLE_API_KEY` + Mongo — sin
      instalar nada adicional en la máquina.
- [ ] Ojo: cambiar de embedding model invalida el índice existente en `data/chroma_db/` — hay
      que re-correr `rag/ingest.py` tras el cambio (documentarlo en el README).

---

## 4. Detección de "información insuficiente" vía salida estructurada (prioridad media)

**Estado:** `agents/clinical.py:184` detecta `information_sufficient = False` buscando el
string `"insuficiente"` en la respuesta de texto libre del LLM. Frágil: si el LLM cambia de
fraseo, el loop de refinamiento no se dispara (brecha ya documentada: hoy el agente real
considera 1 fila —P004— como información suficiente, cosa que el fallback sí detecta).

- [ ] Migrar `information_sufficient` (y otros campos de control que hoy se infieren de texto)
      a salida estructurada del LLM (Pydantic / function calling), en vez de parsear substrings.
- [ ] Mismo criterio aplicable al punto 2 (router): evitar decisiones de control basadas en
      parseo de lenguaje natural.

---

## 5. Evaluación en capas (prioridad baja / mejora de robustez)

**Estado:** `tests/eval_runner.py` + `tests/cases/*.json` ya cubren 9 casos (happy/edge/
adversarial) con comparación manual "esperado vs obtenido" en la pestaña Evaluación de la UI.
Es el "germen del LLM-as-judge" (texto propio de `CLAUDE.md`), pero hoy es 100% manual.

- [ ] **Capa 1 (gratis, determinística, sobre el 100% de los casos):** validaciones
      automáticas — ¿el JSON parsea?, ¿está el disclaimer obligatorio?, ¿las alertas están
      dentro de los umbrales ADA esperados?, ¿`information_sufficient` coincide con lo
      esperado?
- [ ] **Capa 2 (LLM-as-judge barato, con el mismo Gemini gratis):** puntuar *faithfulness*
      del reporte del Clínico contra los fragmentos RAG recuperados y contra el
      `MonitorAnalysis` — para pescar alucinaciones clínicas, que es el riesgo más caro en
      este dominio.
- [ ] Automatizar la escritura de un veredicto por caso (`ok`/`degraded`/`error` ya existe;
      sumar algo tipo `useful`/`corrected`) en vez de que el juicio quede solo en la lectura
      manual de la pestaña Evaluación.

---

## Referencias del research (2026)

- Free tier Groq: 30 RPM / 6K TPM / ~14.4K req/día — https://tokenmix.ai/blog/groq-free-tier-limits-2026
- Free tier Gemini: 1500 req/día / 1M TPM (Flash) — https://tokenmix.ai/blog/gemini-api-free-tier-limits
- Evaluación de agentes / LLM-as-judge — https://langfuse.com/guides/cookbook/example_pydantic_ai_mcp_agent_evaluation
- Agent evaluation (tools, trayectorias, LLM-as-judge) — https://medium.com/@vinodkrane/chapter-8-agent-evaluation-for-llms-how-to-test-tools-trajectories-and-llm-as-judge-788f6f3e0d52

## Orden sugerido

`0 (setup)` → `1 (save)` → `2 y 4 (control estructurado)` → `3 (RAG sin Ollama)` → `5 (eval en capas)`.
