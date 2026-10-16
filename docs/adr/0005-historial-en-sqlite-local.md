# ADR-0005 · Historial de pacientes en SQLite local, detrás de una interfaz de almacén

- **Estado:** Aceptado
- **Fecha:** 2026-09-24
- **Relacionado:** [plan MVP](../plan_mvp.md) MVP-01 · absorbe F2-08 · decisión de diseño #2 de `docs/CLAUDE.md`

## Contexto

- El historial (perfil + sesiones guardadas) vivía en MongoDB. Para correr el sistema completo había que levantar
  Docker o un `mongod` nativo y cargar los datos a mano; sin eso, la comparación longitudinal y el guardado fallaban
  en silencio.
- El objetivo inmediato es un **MVP que corra en una máquina limpia con solo `uv`**. La migración a una base en la
  nube es un paso posterior y todavía no está elegido el motor.
- `tools/mongo_tools.py` además creaba un `MongoClient` por llamada sin cerrarlo y usaba `datetime.utcnow()` (F2-08).

## Decisión

1. **Interfaz única** `HistoryStore` (`tools/history_store.py`): `get_patient`, `upsert_patient`, `add_session`,
   `list_patient_ids`. Los agentes solo usan las tools de `tools/history_tools.py`, que hablan con esa interfaz.
2. **SQLite es el motor por defecto** (`data/tp2.db`, fuera de git; stdlib, sin dependencias). Dos tablas:
   `patients(patient_id, profile JSON)` y `sessions(session_id, patient_id, saved_at, data JSON)`. El schema del
   documento lo define el código, igual que en Mongo, así que cambiar de motor no cambia los datos.
3. **MongoDB queda como backend opcional** (`HISTORY_BACKEND=mongo` + `MONGO_URI`), con la misma interfaz. Es también
   la plantilla de cómo agregar un motor en la nube.
4. Instancia única por proceso (`get_store()`, cacheada); los tests la reemplazan por un SQLite temporal por test
   (`tests/conftest.py`), así que las tools de historial pasan a tener **tests determinísticos** sin infraestructura.
5. `data/load_history.py` reemplaza a `data/load_mongo.py`: deriva los pacientes de los CSV de `data/sample/`, es
   idempotente y **no borra las sesiones guardadas** al recargar perfiles.

## Alternativas consideradas

- **Seguir con MongoDB (Docker)** — obliga a instalar y levantar un servicio para una demo; es la fricción que el MVP
  quiere sacar.
- **TinyDB / archivo JSON** — dependencia extra y sin concurrencia segura; la UI de Gradio atiende pedidos en varios
  hilos.
- **mongita (Mongo embebido)** — mantendría la API de pymongo, pero es un proyecto poco mantenido y ata el código a la
  API de Mongo justo cuando el motor de la nube está abierto.
- **SQLAlchemy/ORM** — más infraestructura de la que pide un documento por paciente; si el motor en la nube es
  relacional (Postgres), `SQLiteHistoryStore` es el punto de partida natural.

## Consecuencias

- Contrato nuevo: todo motor futuro implementa `HistoryStore`. Migrar a la nube = nueva clase + variable de entorno.
- La conexión SQLite es compartida entre hilos con un lock: suficiente para un médico por instancia; para uso
  concurrente real hay que pasar a un motor servidor.
- `pymongo` sigue como dependencia (backend opcional). Docker pasa a ser opcional (`docker/README.md`).
- Los tests de historial de `test_clinico_tools.py` dejan de ser `integration`; los de RAG siguen siéndolo.
