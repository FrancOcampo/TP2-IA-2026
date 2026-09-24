# tests/test_monitor_ensamblado.py
#
# Ensamblado determinístico del MonitorAnalysis (F1-05, D7): una ventana principal,
# completado con la misma ventana, ventanas secundarias separadas y alertas sin duplicar.
# Se simulan las tool calls del LLM con CollectedResults.track (sin LLM).

from datetime import date

from agents.monitor import (
    CollectedResults,
    _build_analysis,
    tool_calculate_stats,
    tool_detect_threshold_violations,
)
from orchestrator.state import TimeRange


def _llm_llama(collected: CollectedResults, tool, **args) -> None:
    collected.track(tool.name, args, tool.invoke(args))


def test_sin_llamadas_la_ventana_es_global():
    analysis = _build_analysis("P002")
    assert analysis.analysis_window.is_global
    assert analysis.records_count == 12
    assert analysis.extra_windows == {}


def test_lo_que_falta_se_completa_con_la_ventana_elegida():
    """El LLM pidió hba1c con 3 meses → glucosa en ayunas también se evalúa con 3 meses."""
    collected = CollectedResults()
    _llm_llama(collected, tool_calculate_stats, patient_id="P002", metric="hba1c", last_n_months=3)
    analysis = _build_analysis("P002", collected)

    assert analysis.analysis_window == TimeRange(last_n_months=3)
    assert analysis.records_count == 3
    assert all(a.date >= date(2025, 10, 1) for a in analysis.alerts)
    assert {a.metric for a in analysis.alerts} >= {"glucose_fasting", "hba1c"}


def test_ventana_secundaria_va_a_extra_windows():
    collected = CollectedResults()
    _llm_llama(collected, tool_calculate_stats, patient_id="P002", metric="hba1c", last_n_months=3)
    _llm_llama(collected, tool_calculate_stats, patient_id="P002", metric="hba1c")
    _llm_llama(collected, tool_detect_threshold_violations, patient_id="P002", metric="hba1c")
    analysis = _build_analysis("P002", collected)

    assert set(analysis.extra_windows) == {"hba1c@global"}
    assert analysis.extra_windows["hba1c@global"].min_value < analysis.hba1c_stats.min_value
    assert all(a.date >= date(2025, 10, 1) for a in analysis.alerts), \
        "las alertas de la ventana global no se mezclan con las de 3 meses"


def test_deteccion_sin_alertas_cuenta_como_hecha():
    """P001 no tiene alertas: una detección vacía no debe re-ejecutarse con otra ventana."""
    collected = CollectedResults()
    _llm_llama(collected, tool_detect_threshold_violations, patient_id="P001", metric="hba1c", last_n_months=2)
    assert ("hba1c", "2m") in collected.checked
    assert _build_analysis("P001", collected).alerts == []


def test_insuficiencia_se_evalua_en_la_ventana():
    """Con 1 mes de ventana ninguna métrica tiene tendencia evaluable (ADR-0003)."""
    collected = CollectedResults()
    _llm_llama(collected, tool_calculate_stats, patient_id="P002", metric="hba1c", last_n_months=1)
    analysis = _build_analysis("P002", collected)

    assert len(analysis.insufficient_data) == 6
    assert "ventana 1m" in analysis.insufficient_data["hba1c"]
