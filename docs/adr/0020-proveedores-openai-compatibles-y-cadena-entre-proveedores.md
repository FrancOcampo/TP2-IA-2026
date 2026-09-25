# ADR-0020 · Proveedores compatibles con OpenAI (OpenRouter) y cadena de respaldo entre proveedores

- **Estado:** Aceptado
- **Fecha:** 2026-09-25
- **Relacionado:** MVP-06 (EAS-38) · [ADR-0014](0014-modelo-groq-gpt-oss.md), [ADR-0015](0015-modo-lean-para-free-tier.md), [ADR-0016](0016-cadena-de-respaldo-de-modelos.md)

## Contexto

- El free tier de Groq (200k tokens/día por modelo) obligó a recortar el sistema al modo `lean` y agotaba su cuota en pocas
  corridas de evaluación.
- El equipo quiere modelos reales al menor costo. El pago en OpenRouter con tarjeta argentina fue rechazado varias veces;
  finalmente se obtuvo una key con 1 USD de crédito. Otros proveedores baratos (DeepSeek directo) solo aceptan PayPal o
  pagos chinos, y los planes gratuitos suelen usar los datos para mejorar sus productos.
- Precios reales consultados en la API pública de OpenRouter (2026-09-25): DeepSeek V4 Flash 0,049 / 0,098 USD por
  millón de tokens (entrada/salida), gpt-oss-20b 0,018 / 0,09, Llama 3.3 70B 0,10 / 0,32. Un análisis en modo `lean`
  usa ~5k tokens de entrada y ~1,2k de salida.

## Decisión

1. **Dos proveedores nuevos** en `agents/llm_factory.py`, sobre `langchain-openai` (que ya era dependencia):
   - `openrouter` (`OPENROUTER_API_KEY`): modelo por defecto `deepseek/deepseek-v4-flash`. Se envía
     `provider: {data_collection: "deny"}` por defecto, para usar solo proveedores que no guardan ni entrenan con los
     datos (`OPENROUTER_DATA_COLLECTION=allow` lo relaja para pruebas con datos sintéticos).
   - `openai_compat` (`LLM_API_KEY` + `LLM_BASE_URL`): cualquier API compatible con OpenAI (DeepSeek, Cerebras, Mistral,
     OpenCode Zen, Ollama local). Cambiar de proveedor de pago es solo configuración.
2. **Salida estructurada** con `method="function_calling"` para estos proveedores (el más ampliamente soportado).
3. **Cadena de respaldo entre proveedores:** las entradas de `LLM_FALLBACK_MODELS` pueden ser `proveedor:modelo`
   (los ids de OpenRouter llevan `:`, así que solo se separa si el prefijo es un proveedor conocido). Las entradas de un
   proveedor sin API key se omiten. Por defecto, OpenRouter respalda en `groq:openai/gpt-oss-120b`: si se acaba el saldo
   (HTTP 402) o el proveedor falla, el sistema sigue funcionando con el free tier de Groq.
4. `_fallback_exceptions()` captura también los errores de `openai` y de Google.
5. **Tiempo máximo por llamada** (`LLM_TIMEOUT_S`, 45 s por defecto): en una corrida real un análisis tardó 248 s por un
   proveedor lento, contra 28–33 s en las demás.

## Mediciones (OpenRouter + DeepSeek V4 Flash, datos sintéticos)

- Análisis completo de P002 (Monitor + Clínico, 2 llamadas): 28–33 s; ~0,0005 USD. Un análisis y dos seguimientos:
  0,00117 USD. Con 1 USD, cientos de sesiones.
- Velocidad de generación: 60–90 tokens/s. El razonamiento del modelo no es la causa de la latencia.
- Con `data_collection=deny` el modelo respondió sin problemas.

## Alternativas consideradas

- **Gemini gratis como principal** — la key ya existía y la cuota es amplia, pero Google puede usar el contenido del plan
  gratuito para mejorar sus productos. Queda como respaldo opcional, no por defecto.
- **OpenCode Zen** — pago con saldo precargado de 20 USD (mismo problema de tarjeta) y sus modelos gratis pueden usar los
  datos para entrenar.
- **Modelo local (Ollama)** — 15 GB de RAM y sin GPU dedicada: solo modelos chicos y lentos. Cubierto por `openai_compat`
  si se quisiera.

## Consecuencias

- El crédito es limitado: conviene un tope de gasto en la key de OpenRouter y, más adelante, un contador de consumo con
  presupuesto diario (pendiente).
- Con un proveedor de pago ya no hay razón técnica para el modo `lean`: `AGENT_MODE=react` y las decisiones agénticas del
  Orquestador y el refinamiento (F3-01, F3-02) pasan a poder probarse con datos reales.
- Los modelos y sus precios cambian: la elección del modelo por defecto debe salir de la evaluación con los casos, no de
  la lista de precios.
