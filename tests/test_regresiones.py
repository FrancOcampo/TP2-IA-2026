# tests/test_regresiones.py
#
# Tests de regresión de los bugs de Fase 1 (plan: docs/plan_correcciones.md → F0-01).
#
# Cada test describe el comportamiento CORRECTO. Nacieron como
# `xfail(strict=True, raises=AssertionError)` y se les quitó la marca al corregir cada ítem
# (F1-01…F1-06, todos cerrados). Para reproducir un bug nuevo, marcarlo con `_xfail("F?-??")`:
#   - strict=True     → cuando el bug se corrige y el test pasa, la suite falla (XPASS) y
#                       obliga a quitar el xfail en el mismo cambio.
#   - raises=Assertion → solo cuenta como "fallo esperado" si falla por la aserción; una
#                       excepción de otro tipo (import roto, KeyError…) se reporta como fallo real.
#
# Modo determinístico (sin LLM), igual que el gate de tests/test_graph.py. Los tests del
# Monitor usan un LLM falso con tool calls guionadas.

import shutil
from datetime import date

import pytest
from langchain_core.messages import AIMessage

from orchestrator.graph import build_graph


def _xfail(item_id: str):
    return pytest.mark.xfail(strict=True, raises=AssertionError, reason=f"{item_id} pendiente")


@pytest.fixture(autouse=True)
def _force_fallback(monkeypatch):
    """Sin API key: el grafo corre con los fallbacks determinísticos."""
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)


@pytest.fixture
def app():
    return build_graph()


def _cfg(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def _analizar(app, patient_id: str, thread_id: str) -> dict:
    return app.invoke(
        {"patient_id": patient_id, "query": f"Analizá al paciente {patient_id}", "conversation": []},
        _cfg(thread_id),
    )


# -------------------------------------------------------------------
# F1-01 · Paciente inexistente informado como "controlado"
# -------------------------------------------------------------------

def test_paciente_inexistente_no_reporta_controlado(app):
    out = _analizar(app, "PX99", "t-px99")

    report = (out.get("report") or "").lower()
    assert "controlado" not in report, "un paciente sin datos no puede figurar como controlado"
    assert out.get("analysis") is None, "no debe haber análisis con valores inventados"
    assert out.get("error"), "debe informarse explícitamente que no hay datos del paciente"


def test_paciente_inexistente_no_invoca_al_clinico(app):
    out = _analizar(app, "PX99", "t-px99-flow")

    assert out.get("report") is None, "sin datos no se genera reporte clínico"
    assert out["iteration"] == 0, "el Clínico no debe ejecutarse"


def test_datos_insuficientes_explicitos_p004(app):
    """P004 tiene un único registro: ninguna métrica permite evaluar evolución."""
    from tools.patient_tools import SERIES_METRICS

    analysis = _analizar(app, "P004", "t-p004-insuf")["analysis"]

    assert set(analysis.insufficient_data) == set(SERIES_METRICS)
    assert analysis.records_count == 1
    assert analysis.hba1c_stats.last_value == 6.5, "los valores reales del registro se conservan"


def test_ui_metricas_sin_datos_se_muestran_como_sin_datos():
    from interface.components import trends_view
    from orchestrator.state import BloodPressureStats, MonitorAnalysis

    analysis = MonitorAnalysis(
        blood_pressure_stats=BloodPressureStats(),
        alerts=[], medication=[], requires_rag=False, requires_longitudinal_comparison=False,
        insufficient_data={"hba1c": "sin registros"},
    )
    vista = trends_view(analysis)

    assert "sin datos" in vista
    assert "0.0" not in vista and "| 0 |" not in vista, "no se muestran valores inventados"
    assert "Datos insuficientes" in vista


# -------------------------------------------------------------------
# F1-02 · Contaminación de estado al cambiar de paciente
# -------------------------------------------------------------------

# P003 es el único paciente con glucosa en ayunas mínima de 55 mg/dL (episodio de
# hipoglucemia); P002 tiene mínimo 98. Sirve para saber de qué paciente es el análisis.
_P003_MIN_AYUNAS = 55.0


def test_cambio_de_paciente_limpia_estado(app):
    _analizar(app, "P002", "t-switch")
    out = app.invoke({"patient_id": "P003", "query": "Analizá al paciente P003"}, _cfg("t-switch"))

    assert out["is_followup"] is False, "cambiar de paciente es una consulta nueva, no un seguimiento"
    assert out["analysis"].glucose_fasting_stats.min_value == _P003_MIN_AYUNAS, \
        "el análisis debe ser del paciente nuevo (P003), no del anterior (P002)"


def test_cambio_de_paciente_desde_el_chat(app):
    """Mismo caso pero desde el chat: el mensaje nombra al paciente y no viene patient_id."""
    _analizar(app, "P002", "t-switch-chat")
    out = app.invoke({"query": "analizá al paciente P003"}, _cfg("t-switch-chat"))

    assert out["analysis"].glucose_fasting_stats.min_value == _P003_MIN_AYUNAS, \
        "el pipeline debe correr sobre P003, el paciente nombrado en el mensaje"


def test_cambio_de_paciente_conserva_solo_el_activo(app):
    """El estado derivado del paciente anterior no sobrevive al cambio."""
    _analizar(app, "P002", "t-scope")
    out = app.invoke({"query": "analizá al paciente P003"}, _cfg("t-scope"))

    assert out["patient_id"] == "P003"
    assert out["active_patient_id"] == "P003"
    assert "P002" not in (out.get("report") or ""), "el reporte no debe arrastrar al paciente anterior"


def test_mismo_paciente_sigue_siendo_seguimiento(app):
    """Nombrar al paciente activo no es un cambio: sigue siendo seguimiento."""
    _analizar(app, "P002", "t-same")
    out = app.invoke({"query": "¿Qué pasó con el paciente P002 en el último mes?"}, _cfg("t-same"))

    assert out["is_followup"] is True
    assert out["active_patient_id"] == "P002"


def test_reiniciar_vuelve_a_correr_el_pipeline(app):
    _analizar(app, "P002", "t-reset")
    out = app.invoke({"query": "reiniciar el análisis"}, _cfg("t-reset"))

    assert out["is_followup"] is False
    assert out["patient_id"] == "P002", "el reinicio conserva al paciente activo"
    assert out["iteration"] == 1, "el pipeline corre de nuevo desde la iteración 1"
    assert out["analysis"] is not None


# -------------------------------------------------------------------
# F1-03 · La respuesta de seguimiento sobrescribe el reporte
# -------------------------------------------------------------------

def test_seguimiento_no_pisa_reporte(app):
    reporte = _analizar(app, "P002", "t-followup")["report"]
    out = app.invoke({"query": "¿Qué significa la HbA1c?"}, _cfg("t-followup"))

    assert out["is_followup"] is True
    assert out.get("followup_answer"), "la respuesta de seguimiento va en followup_answer"
    assert out["report"] == reporte, "el reporte de la sesión no cambia al hacer seguimiento"


# -------------------------------------------------------------------
# F1-04 · Guardado de sesión
# -------------------------------------------------------------------

def test_si_no_dispara_guardado(app):
    _analizar(app, "P002", "t-si")
    out = app.invoke({"query": "si"}, _cfg("t-si"))

    assert not out.get("awaiting_confirmation"), "'si' en el chat no es una confirmación de guardado"
    assert not out.get("save_requested"), "'si' en el chat no es una confirmación de guardado"


def test_guardar_persiste(app, monkeypatch):
    llamadas: list[tuple[tuple, dict]] = []

    def fake_update(*args, **kwargs):
        llamadas.append((args, kwargs))
        return {"ok": True, "session_id": "test-session"}

    # Se parchea en el módulo de la tool y, si el grafo la importa directamente, también ahí.
    monkeypatch.setattr("tools.history_tools.update_patient_history", fake_update)
    monkeypatch.setattr("orchestrator.graph.update_patient_history", fake_update, raising=False)

    _analizar(app, "P002", "t-save")
    app.invoke({"save_requested": True, "query": "confirmar"}, _cfg("t-save"))

    assert len(llamadas) == 1, "confirmar el guardado debe persistir la sesión una vez"
    args, kwargs = llamadas[0]
    patient_id = kwargs.get("patient_id", args[0] if args else None)
    session_data = kwargs.get("session_data", args[1] if len(args) > 1 else None)
    assert patient_id == "P002"
    assert session_data["report"], "la sesión guardada incluye el reporte"
    assert session_data["alerts"], "la sesión guardada incluye las alertas"
    assert session_data["metrics_summary"]["hba1c"] == 8.2, \
        "metrics_summary guarda el último valor de cada métrica"


# -------------------------------------------------------------------
# F1-05 · Monitor: alertas duplicadas y ventanas mezcladas
# -------------------------------------------------------------------

class _ScriptedLLM:
    """LLM falso: devuelve en orden las respuestas guionadas (tool calls y cierre)."""

    def __init__(self, responses: list[AIMessage]):
        self._responses = list(responses)

    def invoke(self, messages):
        return self._responses.pop(0)


def _tool_call(name: str, call_id: str, **args) -> dict:
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}


def _run_monitor(monkeypatch, patient_id: str, tool_calls: list[dict]):
    from agents import monitor

    script = [AIMessage(content="", tool_calls=tool_calls), AIMessage(content="Análisis listo.")]
    monkeypatch.setenv("AGENT_MODE", "react")  # estos tests guionan el loop ReAct (ADR-0015)
    monkeypatch.setattr(monitor, "_build_monitor_llm", lambda: _ScriptedLLM(script))
    return monitor.run_monitor_agent({"patient_id": patient_id, "query": "", "doctor_context": ""})


def test_monitor_no_duplica_alertas(monkeypatch):
    # El LLM pide dos veces la misma detección (P003 tiene una hipoglucemia en ayunas).
    analysis = _run_monitor(monkeypatch, "P003", [
        _tool_call("detect_threshold_violations", "c1", patient_id="P003", metric="glucose_fasting"),
        _tool_call("detect_threshold_violations", "c2", patient_id="P003", metric="glucose_fasting"),
    ])

    claves = [(a.metric, a.date, a.value) for a in analysis.alerts]
    assert len(claves) == len(set(claves)), "la misma observación no puede generar dos alertas"


def test_monitor_respeta_ventana_elegida(monkeypatch):
    # El LLM analiza solo los últimos 3 meses; lo que se complete debe usar la misma ventana.
    analysis = _run_monitor(monkeypatch, "P002", [
        _tool_call("calculate_stats", "c1", patient_id="P002", metric="hba1c", last_n_months=3),
        _tool_call("detect_threshold_violations", "c2", patient_id="P002", metric="hba1c", last_n_months=3),
    ])

    inicio_ventana = date(2025, 10, 15)  # P002: registros mensuales de 2025; últimos 3 = oct–dic
    fuera = [a for a in analysis.alerts if a.date < inicio_ventana]
    assert not fuera, f"hay {len(fuera)} alerta(s) fuera de la ventana de 3 meses elegida"


# -------------------------------------------------------------------
# F1-06 · Suficiencia de información hardcodeada por id
# -------------------------------------------------------------------

def test_suficiencia_no_depende_del_id(app, monkeypatch, tmp_path):
    import tools.patient_tools as patient_tools

    # Copia del fixture + un paciente nuevo con los mismos datos que P004 (una sola fila).
    for f in patient_tools.SAMPLE_DATA_DIR.iterdir():
        if f.is_file():
            shutil.copy(f, tmp_path / f.name)
    shutil.copy(tmp_path / "P004.csv", tmp_path / "P900.csv")
    monkeypatch.setattr(patient_tools, "SAMPLE_DATA_DIR", tmp_path)

    out_p004 = _analizar(app, "P004", "t-p004")
    out_p900 = _analizar(app, "P900", "t-p900")

    assert out_p900["iteration"] == out_p004["iteration"], \
        "dos pacientes con los mismos datos deben recorrer el mismo flujo"
    assert out_p900["information_sufficient"] == out_p004["information_sufficient"]
    assert "insuficiente" in (out_p900.get("report") or "").lower(), \
        "con un solo registro el reporte debe explicitar que los datos son insuficientes"
