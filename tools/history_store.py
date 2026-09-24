# tools/history_store.py
#
# Almacén del historial de pacientes (perfil + sesiones guardadas), detrás de una
# interfaz única para poder cambiar de motor sin tocar a los agentes (ADR-0005).
#
#   HISTORY_BACKEND=sqlite (default) → archivo local, sin servicios externos (MVP).
#   HISTORY_BACKEND=mongo            → MongoDB en MONGO_URI (Docker o nube).
#
# El documento de paciente tiene el mismo schema en ambos motores:
#   { patient_id, metrics_history: [...], medications: [...], sessions: [...] }
# En SQLite las sesiones viven en su propia tabla y se recomponen al leer.

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from functools import lru_cache
from pathlib import Path
from typing import Optional, Protocol

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

DEFAULT_SQLITE_PATH = Path(__file__).resolve().parent.parent / "data" / "tp2.db"


class HistoryStore(Protocol):
    """Contrato del almacén de historial. Toda implementación devuelve dicts planos (JSON)."""

    def get_patient(self, patient_id: str) -> Optional[dict]:
        """Documento del paciente con `sessions` en orden cronológico, o None si no existe."""

    def upsert_patient(self, doc: dict) -> None:
        """Crea o reemplaza el perfil del paciente. No borra sus sesiones."""

    def add_session(self, patient_id: str, session: dict) -> None:
        """
        Agrega una sesión al paciente. Idempotente por `session_id` (volver a agregar la misma
        sesión no la duplica). Lanza KeyError si el paciente no existe.
        """

    def list_patient_ids(self) -> list[str]:
        """Ids de todos los pacientes cargados, ordenados."""


# -------------------------------------------------------------------
# SQLite (default)
# -------------------------------------------------------------------

class SQLiteHistoryStore:
    """
    Historial en un archivo SQLite. El perfil y cada sesión se guardan como JSON:
    el schema del documento lo define el código, no la base (igual que en Mongo).
    """

    _SCHEMA = """
        CREATE TABLE IF NOT EXISTS patients (
            patient_id TEXT PRIMARY KEY,
            profile    TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            patient_id TEXT NOT NULL REFERENCES patients(patient_id),
            saved_at   TEXT NOT NULL,
            data       TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_sessions_patient ON sessions(patient_id, saved_at);
    """

    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        # Gradio atiende pedidos en varios hilos: una conexión compartida protegida por lock.
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._lock = threading.Lock()
        with self._lock, self._conn:
            self._conn.executescript(self._SCHEMA)

    def get_patient(self, patient_id: str) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT profile FROM patients WHERE patient_id = ?", (patient_id,)
            ).fetchone()
            if row is None:
                return None
            sessions = self._conn.execute(
                "SELECT data FROM sessions WHERE patient_id = ? ORDER BY saved_at, rowid",
                (patient_id,),
            ).fetchall()
        doc = json.loads(row[0])
        doc["patient_id"] = patient_id
        doc["sessions"] = [json.loads(s[0]) for s in sessions]
        return doc

    def upsert_patient(self, doc: dict) -> None:
        profile = {k: v for k, v in doc.items() if k not in ("patient_id", "sessions")}
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO patients (patient_id, profile) VALUES (?, ?) "
                "ON CONFLICT(patient_id) DO UPDATE SET profile = excluded.profile",
                (doc["patient_id"], json.dumps(profile, ensure_ascii=False)),
            )

    def add_session(self, patient_id: str, session: dict) -> None:
        with self._lock, self._conn:
            exists = self._conn.execute(
                "SELECT 1 FROM patients WHERE patient_id = ?", (patient_id,)
            ).fetchone()
            if exists is None:
                raise KeyError(f"Paciente '{patient_id}' no encontrado")
            self._conn.execute(
                "INSERT INTO sessions (session_id, patient_id, saved_at, data) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(session_id) DO NOTHING",
                (session["session_id"], patient_id, session["saved_at"],
                 json.dumps(session, ensure_ascii=False)),
            )

    def list_patient_ids(self) -> list[str]:
        with self._lock:
            rows = self._conn.execute("SELECT patient_id FROM patients ORDER BY patient_id").fetchall()
        return [r[0] for r in rows]

    def close(self) -> None:
        self._conn.close()


# -------------------------------------------------------------------
# MongoDB (opcional)
# -------------------------------------------------------------------

class MongoHistoryStore:
    """Historial en MongoDB: un documento por paciente con `sessions` embebidas."""

    DB_NAME = "tp2_diabetes"
    COLLECTION = "patients"
    _TIMEOUT_MS = 3000

    def __init__(self, uri: str):
        from pymongo import ASCENDING, MongoClient

        self._client = MongoClient(uri, serverSelectionTimeoutMS=self._TIMEOUT_MS,
                                   connectTimeoutMS=self._TIMEOUT_MS)
        self._col = self._client[self.DB_NAME][self.COLLECTION]
        self._col.create_index([("patient_id", ASCENDING)], unique=True)

    def get_patient(self, patient_id: str) -> Optional[dict]:
        return self._col.find_one({"patient_id": patient_id}, {"_id": 0})

    def upsert_patient(self, doc: dict) -> None:
        profile = {k: v for k, v in doc.items() if k != "sessions"}
        self._col.update_one(
            {"patient_id": doc["patient_id"]},
            {"$set": profile, "$setOnInsert": {"sessions": []}},
            upsert=True,
        )

    def add_session(self, patient_id: str, session: dict) -> None:
        if self._col.count_documents({"patient_id": patient_id}, limit=1) == 0:
            raise KeyError(f"Paciente '{patient_id}' no encontrado")
        # Solo se agrega si no hay otra sesión con el mismo id (idempotente).
        self._col.update_one(
            {"patient_id": patient_id, "sessions.session_id": {"$ne": session["session_id"]}},
            {"$push": {"sessions": session}},
        )

    def list_patient_ids(self) -> list[str]:
        return sorted(self._col.distinct("patient_id"))

    def close(self) -> None:
        self._client.close()


# -------------------------------------------------------------------
# Selección del motor
# -------------------------------------------------------------------

@lru_cache(maxsize=1)
def get_store() -> HistoryStore:
    """
    Instancia única del almacén según HISTORY_BACKEND. Los tests la reemplazan con
    `get_store.cache_clear()` + variables de entorno (p. ej. HISTORY_DB_PATH temporal).
    """
    backend = os.getenv("HISTORY_BACKEND", "sqlite").lower()
    if backend == "mongo":
        uri = os.getenv("MONGO_URI", "mongodb://127.0.0.1:27017")
        logger.info("Historial en MongoDB (%s)", uri)
        return MongoHistoryStore(uri)
    path = os.getenv("HISTORY_DB_PATH") or str(DEFAULT_SQLITE_PATH)
    logger.info("Historial en SQLite (%s)", path)
    return SQLiteHistoryStore(path)
