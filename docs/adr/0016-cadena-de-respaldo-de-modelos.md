# ADR-0016 · Cadena de respaldo de modelos LLM

- **Estado:** Aceptado
- **Fecha:** 2026-09-25
- **Relacionado:** MVP-06 (EAS-38) · [ADR-0014](0014-modelo-groq-gpt-oss.md), [ADR-0015](0015-modo-lean-para-free-tier.md)

## Contexto

- En el free tier de Groq cada modelo tiene **cuotas independientes**: 8.000 tokens/min y 200.000 tokens/día para
  `gpt-oss-120b` y `gpt-oss-20b`. Al agotarse la cuota diaria del modelo principal, **todas** las consultas caían al
  fallback determinístico. Pasó durante la evaluación: 11 de 12 casos degradados.
- Un modelo dado de baja (ADR-0014) tiene el mismo efecto: 404 y fallback silencioso.
- `qwen/qwen3.8-27b` tiene cuota libre, pero su límite de **1.000 tokens de salida por minuto** no alcanza para un
  reporte clínico (~1.000 tokens).

## Decisión

1. `build_llm()` devuelve el modelo principal con una **cadena de respaldo** (`Runnable.with_fallbacks` de
   LangChain). Ante un error HTTP del proveedor (`groq.APIStatusError`: 429 de cuota, 413 de tamaño, 404 de modelo
   inexistente), la llamada se reintenta con el siguiente modelo.
2. El respaldo por defecto en Groq es `openai/gpt-oss-20b`, que genera reportes completos (verificado). Se configura
   con `LLM_FALLBACK_MODELS` (lista separada por comas; vacío = sin respaldo).
3. La cadena aplica igual a tools (`bind_tools`) y a salida estructurada (`build_llm(structured_output=...)`), porque
   cada modelo se configura antes de encadenarlo.
4. Reintentos: `max_retries=1` en los modelos intermedios (pasar rápido al respaldo) y 4 en el **último** de la
   cadena, que respeta el `retry-after` del proveedor. Sin esto, cuando el principal falla rápido, todos los pasos
   caen sobre el respaldo en el mismo minuto y agotan su límite por minuto (eval `edge_04`).
5. `llm_status()` (banner de la UI) muestra el principal y el respaldo.

## Alternativas consideradas

- **Proxy tipo LiteLLM** — agrega un servicio. `with_fallbacks` resuelve lo mismo dentro del proceso.
- **Rotar varias API keys** — va contra los términos de uso del proveedor.
- **Incluir qwen en la cadena** — generaría reportes truncados. Mejor un fallback determinístico explícito que un
  reporte cortado.

## Consecuencias

- El presupuesto diario del free tier pasa a ~400.000 tokens, unos 35 análisis en modo `lean`.
- Un reporte puede venir de un modelo menos capaz (20b) sin que el médico lo note. El modelo que respondió queda en
  `response_metadata`. Marcarlo en el estado y en la UI es parte de F3-06 (`execution_mode`).
- Con una API paga se puede poner un modelo de otro proveedor como respaldo, cuando exista el proveedor genérico
  compatible con la API de OpenAI.
