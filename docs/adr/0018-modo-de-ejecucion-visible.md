# ADR-0018 · Modo de ejecución visible: el estado registra si cada nodo usó el LLM o el fallback

- **Estado:** Aceptado
- **Fecha:** 2026-09-25
- **Relacionado:** F3-06 (EAS-25, parcial) · [ADR-0014](0014-modelo-groq-gpt-oss.md), [ADR-0016](0016-cadena-de-respaldo-de-modelos.md)

## Contexto

- Cuando el LLM falla (cuota agotada, modelo dado de baja, pedido demasiado grande) cada agente cae a su fallback
  determinístico. Esa caída solo quedaba en los logs. En la UI el médico veía un reporte pobre
  (`[Clinical fallback] …`) sin ninguna explicación.
- Pasó varias veces durante la evaluación con el free tier de Groq, y la primera vez costó tiempo entender que el LLM
  no había corrido. `LangChain.with_fallbacks` agrava esto: si todos los modelos fallan, reporta el error del
  **primero**, no el último.

## Decisión

1. `AgentState.execution_mode: dict[str, str]`: por nodo, `"llm"` o `"fallback:<motivo>"`, con motivo
   `no_api_key`, `rate_limit`, `too_large` o `error` (`_fallback_reason` lo deduce del error del proveedor).
   Cada nodo actualiza solo su clave (`_with_mode`), y se limpia al cambiar de paciente.
2. La UI (`components.execution_warning`) muestra un aviso cuando algún nodo cayó al fallback: qué nodo, por qué
   (en lenguaje llano) y que el resultado es básico y sin interpretación clínica. Aparece en el chat y arriba del
   panel de reporte, y también en las respuestas de seguimiento.

## Alternativas consideradas

- **Leer los logs desde la UI** — frágil y ya lo hace `eval_runner` (captura de errores del logger).
  `execution_mode` es el dato estructurado que debería usar en su lugar (queda para F3-06 completo).
- **Marcar el fallback solo en el texto del reporte** — obliga a parsear texto y no sirve para respuestas de
  seguimiento.

## Consecuencias

- Contrato compartido modificado (`orchestrator/state.py`): `execution_mode` (plan §8).
- Pendiente de F3-06: que `eval_runner` use `execution_mode` en lugar de capturar logs, y guardarlo en la sesión
  persistida (`session_data.execution_mode`).
- El motivo `error` es genérico. Mostrar el error real del último modelo de la cadena requiere envolver
  `with_fallbacks`; no se hizo.
