# Infraestructura Docker — TP2

MongoDB **opcional** para el historial de pacientes. Por defecto el historial es un archivo
SQLite local y no hace falta Docker ([ADR-0005](../docs/adr/0005-historial-en-sqlite-local.md)).
Para usar Mongo, definí en `.env`:

```bash
HISTORY_BACKEND=mongo
MONGO_URI=mongodb://127.0.0.1:27017
```

> Requisito: **Docker Desktop** abierto y corriendo.

## Levantar MongoDB

Desde la **raíz del repositorio**:

```bash
docker compose -f docker/docker-compose.yml up -d
```

O desde **esta carpeta**:

```bash
cd docker
docker compose up -d
```

Esto:

- Levanta `mongo:7` en el puerto **27017** (contenedor `tp2-mongo`).
- Persiste los datos en el volumen `tp2-mongo-data` (sobreviven a reinicios y a `down`).
- Crea la base `tp2_diabetes` con la colección `patients` y su índice único
  (`docker/mongo-init.js`, solo en el primer arranque).

## Cargar los datos

Con el contenedor arriba y el entorno `uv` sincronizado:

```bash
HISTORY_BACKEND=mongo uv run python data/load_history.py   # carga los pacientes de data/sample/
```

## Comandos útiles

```bash
docker compose -f docker/docker-compose.yml ps        # estado del servicio
docker compose -f docker/docker-compose.yml logs -f   # ver logs en vivo
docker compose -f docker/docker-compose.yml stop      # pausar (sin borrar el contenedor)
docker compose -f docker/docker-compose.yml down      # detener y eliminar (CONSERVA datos)
docker compose -f docker/docker-compose.yml down -v   # detener y BORRAR los datos del volumen
```

## Alternativa: MongoDB local nativo (sin Docker)

Si preferís no usar Docker, podés correr el `mongod` de una instalación local (ver la
sección **Modo completo → MongoDB** del [README principal](../README.md)). El código se
conecta a `mongodb://localhost:27017` en ambos casos: cambiar de Docker a local nativo no
requiere tocar nada más que tener el servicio escuchando en ese puerto.

> En Windows, si la conexión se demora por la resolución IPv6 de `localhost`, definí
> `MONGO_URI=mongodb://127.0.0.1:27017` en tu `.env` (ya viene así por defecto).
