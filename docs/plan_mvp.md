# Plan MVP — sistema funcionando de punta a punta en local

> **Qué es este documento.** Ordena el trabajo para llegar a un MVP usable. No reemplaza al
> [plan de correcciones](plan_correcciones.md): lo **prioriza** (qué ítems entran al MVP y en qué orden) y agrega
> los ítems de infraestructura `MVP-0X` que el plan original no tenía. Cada ítem tiene su issue en Linear.

## Definición de "MVP funcionando"

En una máquina limpia (Windows/macOS/Linux), con **solo** `uv` instalado:

```bash
uv sync
cp .env.example .env        # completar UNA API key de LLM
uv run python main.py       # crea la base local, indexa las guías si falta y abre la UI
```

y en la UI el médico puede:

1. Elegir un paciente (P001–P005) y obtener un reporte generado por el **LLM real**, con alertas contra
   **metas de control** de DM2 (no criterios diagnósticos) y citas de las guías recuperadas por RAG.
2. Hacer preguntas de seguimiento sin que se pise el reporte ni se mezclen pacientes.
3. **Guardar la sesión** con el botón y verla reflejada en la próxima consulta (comparación con la sesión anterior).
4. Ver un error claro (no un reporte inventado) si el paciente no existe o falta la API key.

**Sin Docker, sin MongoDB y sin Ollama.** La persistencia es un archivo SQLite local (`data/tp2.db`) y los
embeddings corren en proceso. Ambos quedan detrás de una interfaz para migrar a la nube después.

## Hitos

Estados: ⬜ pendiente · 🟨 en curso · ✅ hecho

### M1 · Infraestructura local (sin servicios externos)

| ID | Título | Absorbe | Estado |
|---|---|---|---|
| **MVP-01** ([EAS-33](https://linear.app/easymetricdev/issue/EAS-33)) | Historial de pacientes en SQLite local, detrás de una interfaz `HistoryStore` (Mongo queda como backend opcional) | F2-08 | ✅ |
| **MVP-02** ([EAS-34](https://linear.app/easymetricdev/issue/EAS-34)) | RAG sin Ollama: embeddings locales por defecto, ingesta idempotente con `--rebuild`, error claro si falta el índice | F2-06 (2, 3) | ✅ |
| **MVP-03** ([EAS-35](https://linear.app/easymetricdev/issue/EAS-35)) | Configuración del LLM: una sola constante de modelo, alias de la API key de Gemini, error claro sin key | F4-01 | ✅ |
| **MVP-04** ([EAS-36](https://linear.app/easymetricdev/issue/EAS-36)) | Arranque en un comando: `main.py` inicializa base + índice si faltan y lanza la UI; logs UTF-8 | F4-03 (`main.py`), F4-04 | ✅ |

### M2 · Correctitud del flujo (ya planificado)

| ID | Título | Estado |
|---|---|---|
| F1-02 | Aislar estado al cambiar de paciente | ✅ |
| F1-03 | La respuesta de seguimiento no pisa el reporte | ✅ |
| F1-04 | "Guardar sesión" persiste (en `HistoryStore`); "sí" no dispara guardado | ✅ |
| F1-05 | Monitor con una ventana coherente y sin alertas duplicadas | ✅ |
| F1-06 | Suficiencia de información sin hardcodeo por id | ✅ |

### M3 · Coherencia clínica mínima

| ID | Título | Nota | Estado |
|---|---|---|---|
| F2-01 | Metas de control DM2 + paciente P005 | Se implementa con la tabla propuesta; la validación 🩺 del equipo queda como check aparte | ✅ (🩺 pendiente) |
| F2-07 | Perfil del paciente (diagnósticos, comorbilidades) + sesiones semilla; `found: False` en vez de excepción | Hace demostrable la comparación longitudinal | ✅ |
| F2-06 (1) | Corpus ADA | MVP: si no se incorpora el contenido, **el prompt deja de pedir citas de ADA** | ✅ (ADA excluida, ADR-0013) |

### M4 · Verificación del MVP

| ID | Título | Estado |
|---|---|---|
| **MVP-05** ([EAS-37](https://linear.app/easymetricdev/issue/EAS-37)) | Smoke test e2e determinístico (base SQLite temporal): analizar → seguir → guardar → re-analizar ve la sesión | ✅ (`tests/test_smoke_mvp.py`) |
| **MVP-06** ([EAS-38](https://linear.app/easymetricdev/issue/EAS-38)) | Corrida del `eval_runner` con LLM real, sin casos `error` (bloqueado: falta API key) | ⬜ |
| — | README con el camino de 3 comandos | ✅ |

### M5 · Funcionar con el LLM real en el free tier (surgió al correr MVP-06)

| ID | Título | Estado |
|---|---|---|
| — | Modelo disponible en Groq (`gpt-oss-120b`), tools con el nombre de los prompts, tests `llm` que detectan fallback ([ADR-0014](adr/0014-modelo-groq-gpt-oss.md)) | ✅ |
| F3-04 (parcial) | Precisión del reporte según la evaluación: sin tendencia con datos insuficientes, período de datos explícito, fuente del umbral fuera del prompt y **validador de citas** | ✅ |
| — | Cadena de respaldo de modelos (`gpt-oss-120b` → `gpt-oss-20b`): duplica la cuota diaria del free tier ([ADR-0016](adr/0016-cadena-de-respaldo-de-modelos.md)) | ✅ |
| F3-05 | Contexto compacto + `AGENT_MODE=lean` (Monitor en 1 llamada, Clínico con historial precargado) + razonamiento `low` ([ADR-0015](adr/0015-modo-lean-para-free-tier.md)) | ✅ |

## Fuera del MVP

F2-02 (PA/peso), F2-03 (episodios), F2-04 (clasificación longitudinal), F2-05 (contexto en RAG), toda la Fase 3
(orquestador LLM, loop real, reporte estructurado) y F4-02, F4-05, F4-06. Siguen en el plan de correcciones.

## Qué hace falta del equipo

Estado al 2026-09-24: M1, M2 y M3 hechos y mergeados en `develop` (sin push). Gate: 139 passed.

| # | Pendiente | Quién | Bloquea |
|---|---|---|---|
| 1 | ~~API key de LLM~~ ✅ Groq configurada. **Falta la corrida final de MVP-06 (EAS-38)** con cuota disponible (el free tier da 200k tokens/día por modelo; se agotaron en el diagnóstico del 2026-09-25). Correr de a un caso: `uv run python tests/eval_runner.py --case <id>` (12 casos, `--list`). Última corrida válida: 9/9 sin degradar con `gpt-oss-20b`; los 4 problemas de precisión que mostró ya están corregidos | Franco | Cierre del MVP |
| 2 | ~~Autorizar Linear y sincronizar~~ ✅ 2026-09-24: EAS-6…11, 18, 19, 27, 30 en Done; EAS-12, 17, 29 en In Progress (con lo que falta comentado); MVP-01…06 = EAS-33…38 | Franco | — |
| 3 | **Validación clínica 🩺** de la tabla de metas de control ([ADR-0011](adr/0011-metas-de-control-dm2.md)), dejando fecha y quién en F2-01 | Equipo | Cierre formal de F2-01 |
| 4 | **Contenido ADA**: decidir si se incorporan las secciones 2/6/9/10 de los *Standards 2024* (derechos de autor) o se quitan las menciones a ADA del artículo ([ADR-0013](adr/0013-corpus-sin-ada-y-huella-del-indice.md)) | Equipo | Cierre de F2-06 |
| 5 | **Push** de `develop` a `origin` | Franco | Que el equipo vea los cambios |

Después del MVP, el orden sigue el [plan de correcciones](plan_correcciones.md): F2-02…F2-05, Fase 3, Fase 4.
