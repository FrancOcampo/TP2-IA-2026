# tests/test_modo_lean.py
#
# AGENT_MODE=lean (ADR-0015) y contexto compacto para los LLM (F3-05). Determinístico: LLM
# falsos que devuelven respuestas guionadas y registran lo que reciben.

import pytest
from langchain_core.messages import AIMessage

import agents.clinical as clinical
import agents.monitor as monitor
from agents.context import compact_history, recent_conversation, summarize_analysis
from agents.monitor import MonitorPlan, _build_analysis
from orchestrator.graph import build_graph
from tools.history_tools import get_patient_history


@pytest.fixture(autouse=True)
def _lean(monkeypatch):
    monkeypatch.setenv("AGENT_MODE", "lean")


class _FakeLLM:
    """Devuelve las respuestas guionadas en orden y guarda los mensajes recibidos."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.received = []

    def invoke(self, messages):
        self.received.append(messages)
        return self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]


# ------------------------------------------------------------------
# Contexto compacto
# ------------------------------------------------------------------

def test_resumen_del_analisis_agrupa_alertas_y_no_es_repr():
    texto = summarize_analysis(_build_analysis("P002"))
    assert "MetricStats(" not in texto and "Alert(" not in texto
    assert "Alertas (17 en total, agrupadas):" in texto
    assert sum(1 for l in texto.splitlines() if l.startswith("- ") and "registro(s) [" in l) == 3
    assert len(texto) < 2500, "el resumen debe ser mucho más chico que el repr del análisis"


def test_resumen_marca_hipoglucemia_y_datos_insuficientes():
    assert "(hipoglucemia)" in summarize_analysis(_build_analysis("P003"))
    assert "Datos insuficientes" in summarize_analysis(_build_analysis("P004"))


def test_historial_compacto_sin_serie_mensual(seeded_store):
    doc = compact_history(get_patient_history("P002"))
    assert "metrics_history" not in doc
    assert doc["sessions_count"] == 3 and len(doc["last_sessions"]) == 3
    assert compact_history(get_patient_history("PX99")) == {"patient_id": "PX99", "found": False, "sessions": []}


def test_conversacion_reciente_sin_monitor_y_truncada():
    conv = [{"role": "assistant", "content": "[Monitor] análisis"}] + [
        {"role": "user" if i % 2 else "assistant", "content": f"m{i} " + "x" * 1000} for i in range(10)
    ]
    texto = recent_conversation(conv, max_turns=4, max_chars=50)
    assert "[Monitor]" not in texto
    assert texto.count("\n") == 3 and "m9" in texto and "m5" not in texto
    assert all(len(l) < 80 for l in texto.splitlines())


# ------------------------------------------------------------------
# Monitor lean: una llamada estructurada
# ------------------------------------------------------------------

def test_monitor_lean_usa_la_ventana_del_plan(monkeypatch):
    plan_llm = _FakeLLM([MonitorPlan(last_n_months=3, rationale="El médico pidió el último trimestre.")])
    monkeypatch.setattr(monitor, "_build_plan_llm", lambda: plan_llm)

    analysis = monitor.run_monitor_agent({"patient_id": "P002", "query": "últimos 3 meses"})

    assert len(plan_llm.received) == 1, "modo lean: una sola llamada al LLM"
    assert "últimos 3 meses" in plan_llm.received[0][1].content
    assert analysis.analysis_window.last_n_months == 3
    assert analysis.monitor_notes == "El médico pidió el último trimestre."


# ------------------------------------------------------------------
# Grafo en modo lean: refinamiento con la ventana elegida por el plan
# ------------------------------------------------------------------

def test_refinamiento_lean_amplia_ventana(seeded_store, monkeypatch):
    import orchestrator.graph as graph

    monkeypatch.setattr(graph, "has_api_key", lambda: True)
    monkeypatch.setattr(monitor, "_build_plan_llm",
                        lambda: _FakeLLM([MonitorPlan(last_n_months=1, rationale="último mes")]))

    def _sin_llm(state):
        raise RuntimeError("sin LLM: fallback del Clínico")

    monkeypatch.setattr(clinical, "run_clinical_agent", _sin_llm)
    out = build_graph().invoke(
        {"patient_id": "P002", "query": "¿Cómo le fue el último mes?", "conversation": []},
        {"configurable": {"thread_id": "lean-refine"}},
    )
    assert out["iteration"] == 2
    assert out["analysis"].analysis_window.is_global



def test_resumen_no_muestra_tendencia_con_datos_insuficientes():
    """eval edge_01: con 1 registro el resumen no puede decir "Δ +0 · estable"."""
    texto = summarize_analysis(_build_analysis("P004"))
    assert "estable" not in texto and "Δ" not in texto
    assert texto.count("SIN tendencia evaluable") == 6


def test_resumen_de_alertas_sin_fuente_citable():
    """eval edge_03: la fuente del umbral no va al prompt (el LLM la citaba como fragmento)."""
    texto = summarize_analysis(_build_analysis("P002"))
    assert "Guía SAD" not in texto and ">= 7 %" in texto


def test_resumen_incluye_periodo_de_datos():
    assert "2025-01-15 a 2025-12-15" in summarize_analysis(_build_analysis("P002"), "2025-01-15 a 2025-12-15")


def test_validacion_de_citas():
    from agents.context import validate_citations

    rag = ["[Guia_SAD_2025.md] ...con el objetivo de glucemias matinales entre 80 y 130 mg/dl..."]
    reporte = ('Meta: “glucemias matinales entre 80 y 130 mg/dl” [Guia_SAD_2025.md]. '
               'Otra: "Hipoglucemia, moderada: < 70 mg/dL" [guia.md].')
    marcado, n = validate_citations(reporte, rag)
    assert n == 1
    assert "130 mg/dl” [Guia" in marcado, "la cita real queda intacta"
    assert '< 70 mg/dL" ⚠️ (cita no verificada)' in marcado


def test_resumen_incluye_metas_del_sistema():
    """eval edge_01/edge_06: sin las metas explícitas el LLM las inventaba."""
    texto = summarize_analysis(_build_analysis("P005"))
    assert "HbA1c (%): alerta si severa > 9, moderada >= 7" in texto
    assert "hipoglucemia severa < 54" in texto


def test_resumen_da_primero_y_ultimo_ya_calculados():
    """eval edge_06: el LLM invertía la cuenta con último + Δ. P005: peso 92 → 88, PA sistólica 138 → 145."""
    texto = summarize_analysis(_build_analysis("P005"))
    assert "Peso (kg): primero 92 → último 88 (Δ -4, bajando)" in texto
    assert "PA sistólica (mmHg): primero 138 → último 145 (Δ +7, subiendo)" in texto
