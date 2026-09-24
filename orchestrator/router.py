# orchestrator/router.py
#
# Lógica de routing del Orquestador, separada del grafo para poder testearla
# de forma aislada y reemplazarla luego por una clasificación vía LLM.

import re

from orchestrator.state import AgentState

# Palabras clave de confirmación / cancelación del guardado de sesión
_CONFIRM_WORDS = {"confirmar", "confirm", "sí", "si", "yes"}
_CANCEL_WORDS = {"cancelar", "cancel", "no"}

# Id de paciente mencionado en un mensaje (P001, P123…)
_PATIENT_ID_RE = re.compile(r"\bP\d{3,}\b", re.IGNORECASE)

# Frases que piden empezar de cero sobre el paciente activo
_RESET_PHRASES = ("reiniciar", "reinicia", "nuevo análisis", "nuevo analisis",
                  "analizá de nuevo", "analiza de nuevo", "analizar de nuevo")


def extract_patient_id(message: str) -> str | None:
    """Devuelve el primer id de paciente (p. ej. 'P003') mencionado en el mensaje, o None."""
    match = _PATIENT_ID_RE.search(message or "")
    return match.group(0).upper() if match else None


def is_reset_message(message: str) -> bool:
    """Detecta si el médico pide reiniciar el análisis del paciente activo."""
    text = (message or "").lower()
    return any(phrase in text for phrase in _RESET_PHRASES)


def is_followup_message(state: AgentState, message: str) -> bool:
    """
    Determina si el mensaje es un follow-up sobre el reporte ya generado (hay reporte
    en el estado) o una consulta nueva que requiere el pipeline completo.

    No decide el cambio de paciente ni el reinicio: eso lo resuelve el Orquestador
    (`orchestrator_node`) comparando contra `active_patient_id`, porque acá
    `state["patient_id"]` ya fue pisado por el input de la invocación (F1-02).

    TODO: reemplazar con clasificación vía LLM del Orquestador.
    """
    return bool(state.get("report"))


def is_confirmation_message(message: str) -> bool:
    """Detecta si el médico confirmó guardar la sesión."""
    return message.strip().lower() in _CONFIRM_WORDS


def is_cancellation_message(message: str) -> bool:
    """Detecta si el médico canceló el guardado de la sesión."""
    return message.strip().lower() in _CANCEL_WORDS
