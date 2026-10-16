# ADR-0014 · Modelo por defecto `openai/gpt-oss-120b` en Groq y tools con el nombre de los prompts

- **Estado:** Aceptado
- **Fecha:** 2026-09-25
- **Relacionado:** MVP-06 · Linear EAS-38 · F4-01 (EAS-27) · F4-06 (EAS-32)

## Contexto

- MVP-03 fijó `llama-3.3-70b-versatile` (el modelo del artículo) sin verificar disponibilidad. Groq lo **dio de baja**:
  toda llamada devolvía 404 `model_not_found` y los agentes caían al fallback determinístico **en silencio**.
- Los tests `llm` pasaban igual: sus aserciones son laxas y no verificaban que el LLM hubiera corrido.
- Modelos de chat con tool calling disponibles con la key del proyecto (2026-09-25): `openai/gpt-oss-120b`,
  `openai/gpt-oss-20b`, `qwen/qwen3.8-27b`.
- Con un modelo que valida las tool calls, apareció otro bug: los prompts nombran las tools `search_clinical_guidelines`,
  `calculate_stats`, etc., pero el código las registraba como `tool_*`. Groq rechazaba la llamada (400).

## Decisión

1. Default de Groq: **`openai/gpt-oss-120b`**, el modelo más capaz de los disponibles y el único que pasó los dos tests
   `llm` sin degradar. `LLM_MODEL` permite probar los otros sin tocar código.
2. Cada tool se registra con el **mismo nombre que usan los prompts** (`@tool("search_clinical_guidelines")`), y el
   código compara contra `tool.name` en lugar de strings literales.
3. Los tests `llm` fallan si algún agente cayó al fallback (fixture `sin_degradacion`, sobre los errores logueados por
   `orchestrator.graph`).

## Alternativas consideradas

- **`qwen/qwen3.8-27b` / `openai/gpt-oss-20b`** — en la prueba ambos superaron el límite de tokens por minuto del free
  tier en el seguimiento. Se pueden volver a evaluar tras reducir el tamaño de los prompts.
- **API paga** — descartada hasta que el MVP funcione con buena precisión (decisión del usuario).

## Consecuencias

- El artículo declara Llama 3.3 70B: hay que actualizarlo (F4-06).
- Medición en el free tier (8000 tokens/min): un análisis de P002 hace 11 llamadas al LLM (el Monitor pide una tool por
  paso y reenvía todo el historial) y tarda ~3,5 min por las esperas de rate limit; el prompt del Clínico (8265 tokens)
  supera el límite por sí solo. Hace falta reducir llamadas y tamaño de prompts antes de la evaluación (ver EAS-38).
