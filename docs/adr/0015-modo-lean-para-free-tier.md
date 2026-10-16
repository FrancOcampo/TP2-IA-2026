# ADR-0015 · Modo `lean` de los agentes para el free tier, con `react` listo para una API paga

- **Estado:** Aceptado
- **Fecha:** 2026-09-25
- **Relacionado:** MVP-06 (EAS-38) · F3-05 (EAS-24) · F3-03 (EAS-22) · F3-06 (EAS-25) · [ADR-0014](0014-modelo-groq-gpt-oss.md)

## Contexto

Medición con el LLM real, Groq free tier (`gpt-oss-120b`: 8.000 tokens/min y 200.000 tokens/día), analizando P002:

- **Monitor (ReAct):** 11 llamadas secuenciales, una tool por paso. Cada paso reenvía todo el historial, así que el
  prompt crece de 1k a 6k tokens. Unos 45k tokens y ~3,5 min por esperas de rate limit, hasta terminar en 429 y
  caer al fallback.
- **Clínico:** un solo request de **8.265 tokens**, por encima del límite por minuto (413). El análisis iba como
  `repr` de Pydantic (con 17 alertas y su fuente), y el historial incluía la serie mensual completa.
- Unas pocas corridas agotaron la cuota diaria del modelo.
- `gpt-oss` es un modelo de razonamiento. Sin límite de esfuerzo, gastó los 2.048 tokens de salida por defecto
  razonando y devolvió un **reporte vacío** (`finish_reason=length`).

El usuario decidió seguir en el free tier hasta que el MVP funcione con buena precisión, y pasar después a una API
paga.

## Decisión

1. **`AGENT_MODE`** (`agents/llm_factory.agent_mode()`), con dos modos:
   - **`lean` (default):**
     - El **Monitor** hace una sola llamada con salida estructurada (`MonitorPlan`: `last_n_months` y `rationale`).
       Decide la ventana, el *hasta cuándo* del contrato A+C, y el código calcula todo con las mismas tools
       determinísticas. El `rationale` queda en `MonitorAnalysis.monitor_notes`.
     - El **Clínico** recibe el historial y la comparación con la sesión anterior ya calculados por código (son
       búsquedas determinísticas, ahora con `current_metrics`, así que hay deltas reales). El LLM solo consulta
       las guías y redacta, en un máximo de 3 pasos.
   - **`react`:** los loops ReAct completos, tal como los describe el artículo. Se activa con `AGENT_MODE=react`
     al pasar a una API paga, sin tocar código.
2. **Contexto compacto en ambos modos** (`agents/context.py`, F3-05):
   - El análisis va como resumen legible, con las alertas agrupadas por métrica y lado.
   - El historial va sin la serie mensual y solo con las últimas 3 sesiones.
   - El seguimiento lleva los últimos 6 turnos, sin los mensajes del Monitor.
3. **Respuesta garantizada** (F3-06, parcial):
   - Si se agotan los pasos del loop, una última llamada sin tools fuerza la respuesta.
   - Una respuesta vacía lanza un error y el nodo cae al fallback. Nunca se guarda un reporte vacío.
4. **Salida de modelos de razonamiento:** `LLM_REASONING_EFFORT=low` (para `gpt-oss`) y `LLM_MAX_TOKENS=4096`,
   configurables.

## Alternativas consideradas

- **ReAct más liviano (varias tool calls por paso)** — estimado en 3–4 llamadas y ~15k tokens por análisis. Sigue
  rozando el límite por minuto y consume la cuota diaria en pocas corridas.
- **Monitor sin LLM** — el médico perdería la orientación temporal ("últimos 3 meses").
- **API paga ya** — el usuario la descartó hasta validar el MVP.

## Consecuencias

- Medido con `gpt-oss-20b`: el reporte de P002 pasa de ~16 llamadas y ~60k tokens (y fallaba) a **4 llamadas y
  ~11k tokens**, sin degradar. El seguimiento usa 1 llamada.
- El artículo describe el modo `react`. Hay que documentar `lean` como modo de despliegue con presupuesto de tokens
  (F4-06).
- La comparación longitudinal ya trae deltas contra la sesión anterior. La clasificación (mejorando / estable /
  deteriorando) sigue pendiente en F2-04.
- También se corrigió un exceso de rechazos: el control de alcance del seguimiento declinaba preguntas de dominio
  como "¿qué significa la HbA1c?". El prompt ahora da ejemplos de qué preguntas sí están en alcance.
