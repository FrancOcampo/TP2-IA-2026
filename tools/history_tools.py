# tools/history_tools.py
#
# Tools de historial del paciente para el Agente Clínico. Operan sobre el almacén
# configurado en tools/history_store.py (SQLite local por defecto; MongoDB opcional).
#
# get_patient_history            — perfil + historial de sesiones previas (para C)
# compare_with_previous_sessions — compara métricas actuales con la sesión anterior (para C)
# update_patient_history         — guarda la sesión actual (solo con confirmación del médico)

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from typing import Optional

from tools.history_store import get_store

logger = logging.getLogger(__name__)


# -------------------------------------------------------------------
# Tool 1 — get_patient_history
# -------------------------------------------------------------------

def get_patient_history(patient_id: str) -> dict:
    """
    Devuelve el documento completo del paciente, incluyendo el historial de
    sesiones anteriores guardadas (`sessions`).

    Usado por el Agente Clínico para contexto longitudinal: comparaciones entre
    consultas, evolución del tratamiento, etc.

    Nunca lanza (F2-07): un paciente inexistente devuelve `found: False` y un almacén caído
    `found: False` + `_history_unavailable`, ambos sin sesiones. Así la tool no tumba el loop
    ReAct del Clínico y el agente sigue sin datos longitudinales.
    """
    try:
        doc = get_store().get_patient(patient_id)
    except Exception as e:
        logger.warning("Historial no disponible, devolviendo historial vacío: %s", e)
        return {"patient_id": patient_id, "found": False, "sessions": [], "_history_unavailable": True}

    if doc is None:
        return {"patient_id": patient_id, "found": False, "sessions": []}
    return {**doc, "found": True}


# -------------------------------------------------------------------
# Tool 2 — compare_with_previous_sessions
# -------------------------------------------------------------------

def compare_with_previous_sessions(
    patient_id: str,
    current_metrics: Optional[dict] = None,
) -> dict:
    """
    Compara las métricas actuales con la sesión inmediatamente anterior guardada.

    `current_metrics` es un dict con las claves de métricas actuales
    (e.g. {"hba1c": 7.2, "glucose_fasting": 130.0, ...}).
    Si se omite o es None, devuelve la sesión anterior sin calcular deltas.

    Devuelve un dict con:
      - previous_session: dict con fecha y métricas de la última sesión guardada
        (None si no hay sesiones previas).
      - deltas: dict métrica → diferencia (actual − anterior), solo para las
        métricas presentes en ambos dicts.
      - sessions_count: cuántas sesiones tiene el paciente en total.

    Si no hay sesiones previas o el almacén no está disponible,
    `previous_session` es None y `deltas` es {}.
    """
    doc = get_patient_history(patient_id)
    sessions = doc.get("sessions", [])

    if not sessions:
        return {
            "previous_session": None,
            "deltas": {},
            "sessions_count": 0,
        }

    last_session = sessions[-1]
    prev_metrics = last_session.get("metrics_summary", {})

    effective_metrics = current_metrics or {}
    deltas = {
        metric: round(effective_metrics[metric] - prev_metrics[metric], 4)
        for metric in effective_metrics
        if metric in prev_metrics
    }

    return {
        "previous_session": {
            "date": last_session.get("date"),
            "metrics_summary": prev_metrics,
            "report_summary": last_session.get("report_summary"),
        },
        "deltas": deltas,
        "sessions_count": len(sessions),
    }


# -------------------------------------------------------------------
# Tool 3 — update_patient_history
# -------------------------------------------------------------------

def update_patient_history(patient_id: str, session_data: dict) -> dict:
    """
    Agrega la sesión actual al historial del paciente.

    IMPORTANTE: solo llamar con confirmación explícita del médico (el grafo lo controla con
    `save_requested` en el nodo `save`; esta función no verifica eso).

    `session_data` es el contenido de la sesión (ver `orchestrator.graph.build_session_data`):
    date, query, doctor_context, report, alerts, metrics_summary, longitudinal_comparison,
    suggested_questions. Se le agregan `session_id`, `saved_at` y `report_summary` (resumen
    corto para las comparaciones de `compare_with_previous_sessions`).

    Devuelve {"ok": True, "session_id": str} o {"ok": False, "error": str}; nunca lanza.
    """
    report = session_data.get("report") or ""
    session = {
        "date": date.today().isoformat(),
        **session_data,
        "session_id": str(uuid.uuid4()),
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "report_summary": report[:500],
    }
    try:
        get_store().add_session(patient_id, session)
    except KeyError:
        return {"ok": False, "error": f"El paciente '{patient_id}' no está en el historial."}
    except Exception as e:
        logger.warning("No se pudo guardar la sesión: %s", e)
        return {"ok": False, "error": f"Historial no disponible ({e})."}
    return {"ok": True, "session_id": session["session_id"]}
