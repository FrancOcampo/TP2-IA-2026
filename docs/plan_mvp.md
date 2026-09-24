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
| **MVP-01** | Historial de pacientes en SQLite local, detrás de una interfaz `HistoryStore` (Mongo queda como backend opcional) | F2-08 | ✅ |
| **MVP-02** | RAG sin Ollama: embeddings locales por defecto, ingesta idempotente con `--rebuild`, error claro si falta el índice | F2-06 (2, 3) | ✅ |
| **MVP-03** | Configuración del LLM: una sola constante de modelo, alias de la API key de Gemini, error claro sin key | F4-01 | ✅ |
| **MVP-04** | Arranque en un comando: `main.py` inicializa base + índice si faltan y lanza la UI; logs UTF-8 | F4-03 (`main.py`), F4-04 | ✅ |

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
| F2-06 (1) | Corpus ADA | MVP: si no se incorpora el contenido, **el prompt deja de pedir citas de ADA** | ⬜ |

### M4 · Verificación del MVP

| ID | Título | Estado |
|---|---|---|
| **MVP-05** | Smoke test e2e determinístico (base SQLite temporal): analizar → seguir → guardar → re-analizar ve la sesión | ⬜ |
| — | Corrida del `eval_runner` con LLM real, sin casos `error` | ⬜ |
| — | README con el camino de 3 comandos | ✅ |

## Fuera del MVP

F2-02 (PA/peso), F2-03 (episodios), F2-04 (clasificación longitudinal), F2-05 (contexto en RAG), toda la Fase 3
(orquestador LLM, loop real, reporte estructurado) y F4-02, F4-05, F4-06. Siguen en el plan de correcciones.

## Qué hace falta del equipo

- **Una API key de LLM**: Groq (gratis, `llama-3.3-70b-versatile`, el modelo del artículo) o Gemini.
- **Validación clínica** de la tabla de metas de F2-01 (no bloquea el MVP, sí su cierre formal).
