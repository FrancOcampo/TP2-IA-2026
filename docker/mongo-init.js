// docker/mongo-init.js
//
// Se ejecuta UNA sola vez: en el primer arranque del contenedor, cuando el volumen
// de datos (tp2-mongo-data) está vacío. Deja la base lista para que el agente conecte.
//
// La CARGA de los 4 pacientes NO se hace acá — la hace data/load_history.py:
//   uv run python data/load_history.py
//
// Este script solo crea la estructura (colección + índice único), de modo que la base
// exista apenas levanta el contenedor. Es idempotente con load_mongo.py (que también
// crea el índice), así que no hay conflicto si corrés ambos.

db = db.getSiblingDB('tp2_diabetes');

db.createCollection('patients');

// Búsqueda exacta por id; un documento por paciente. Coincide con data/load_history.py.
db.patients.createIndex({ patient_id: 1 }, { unique: true });

print('[mongo-init] Base "tp2_diabetes" lista: colección "patients" + índice único patient_id.');
