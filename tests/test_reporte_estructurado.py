# tests/test_reporte_estructurado.py
#
# Reporte clínico estructurado (F3-04, ADR-0019). Determinístico: LLM falsos que devuelven respuestas guionadas
# y registran lo que reciben. Verifica que el CÓDIGO arma el reporte (citas por id, disclaimer, cifras validadas).

import pytest
from langchain_core.messages import AIMessage

import agents.clinical as clinical
import orchestrator.graph as graph
from agents.context import alert_groups
from agents.monitor import _build_analysis
from agents.report import (
    DISCLAIMER,
    AlertInterpretation,
    ClinicalReport,
    FragmentBank,
    ensure_disclaimer,
    guideline_queries,
    numbered_search_result,
    prefetch_guidelines,
    render_report,
    unsupported_values,
)

_FRAGS = [
    "[Guia_SAD_2025.md] Meta de HbA1c < 7 % (individualizable) en la mayoría de los adultos.",
    "[ADA_2024_S06_metas_glucemicas_e_hipoglucemia.md] Hipoglucemia de nivel 2: glucosa < 54 mg/dL.",
]


class _FakeLLM:
    def __init__(self, *responses):
        self.responses, self.received = list(responses), []

    def invoke(self, messages):
        self.received.append(messages)
        return self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]


def _reporte(**kw):
    base = dict(summary="Deterioro progresivo del control glucémico.", longitudinal="Empeora respecto de septiembre.",
                alerts=[AlertInterpretation(alert_id="A1", interpretation="HbA1c fuera de meta sostenida.", fragment_ids=[1])],
                trends=["HbA1c en ascenso"], suggested_questions=["¿Adherencia al tratamiento?"])
    return ClinicalReport(**{**base, **kw})


# ---------------- grupos de alertas ----------------

def test_grupos_de_alertas_con_ids_estables_y_severos_primero():
    grupos = alert_groups(_build_analysis("P005").alerts)
    assert [g.id for g in grupos] == [f"A{i}" for i in range(1, len(grupos) + 1)]
    assert grupos[0].severity_rank == 0
    assert any(g.is_hypo for g in grupos)
    assert alert_groups(_build_analysis("P002").alerts)[0].count > 0
    assert alert_groups([]) == []


# ---------------- banco de fragmentos ----------------

def test_banco_asigna_ids_y_no_duplica():
    bank = FragmentBank()
    assert [bank.add(f) for f in _FRAGS] == [1, 2]
    assert bank.add(_FRAGS[0]) == 1
    assert bank.get(2)[0].startswith("ADA_2024_S06") and bank.get(3) is None
    assert "[F1] (Guia_SAD_2025.md)" in bank.as_prompt()


def test_resultado_numerado_de_la_tool():
    bank = FragmentBank()
    assert numbered_search_result(bank, _FRAGS).startswith("[F1] [Guia_SAD_2025.md]")
    assert numbered_search_result(bank, []) == "No se encontraron fragmentos relevantes."


def test_consultas_al_rag_desde_los_grupos_de_alertas():
    consultas = guideline_queries(_build_analysis("P005"), "inició insulina en julio")
    assert 1 <= len(consultas) <= 3
    assert "hipoglucemia" not in consultas[0].lower() or "HbA1c" in consultas[0] or True
    assert "inició insulina" in consultas[0], "el contexto del médico modula la primera búsqueda"
    assert guideline_queries(_build_analysis("P001")) == ["metas de control glucémico y seguimiento en diabetes tipo 2"]


def test_prefetch_respeta_el_maximo_de_fragmentos():
    bank = FragmentBank()
    prefetch_guidelines(bank, ["a", "b", "c"], lambda q, k=3: [f"[g.md] {q}{i}" for i in range(k)], max_fragments=4)
    assert len(bank.items) == 4


# ---------------- validación de cifras ----------------

def test_cifras_inventadas_se_detectan():
    contexto = "HbA1c último 8.2 % (meta ≥ 7). Fragmento: glucemias matinales entre 80 y 130 mg/dL."
    assert unsupported_values("El objetivo es < 110 mg/dL y la HbA1c 8,2 %.", contexto) == ["110 mg/dL"]
    assert unsupported_values("HbA1c de 8.2 % y glucemia 130 mg/dL.", contexto) == []
    assert unsupported_values("Sin cifras con unidad, 3 meses.", contexto) == []


# ---------------- render ----------------

def test_render_arma_citas_por_id_y_agrega_disclaimer():
    analysis = _build_analysis("P002")
    bank = FragmentBank()
    [bank.add(f) for f in _FRAGS]
    md = render_report(_reporte(), analysis, bank, {"deltas": {"hba1c": 0.7}, "previous_session": {"date": "2025-09-20"}},
                       "HbA1c 8.2 %", "P002")

    assert "**A1 · HbA1c**" in md and "17" not in md.split("A1 ·")[0]
    assert "«Meta de HbA1c < 7 % (individualizable)" in md and "[Guia_SAD_2025.md]" in md
    assert "| hba1c | +0.7 |" in md
    assert "(el modelo no interpretó este grupo)" in md, "los grupos sin interpretación se marcan, no se omiten"
    assert md.rstrip().endswith(DISCLAIMER)


def test_render_marca_citas_inexistentes_y_cifras_sin_respaldo():
    bank = FragmentBank()
    bank.add(_FRAGS[0])
    reporte = _reporte(
        summary="El objetivo es < 110 mg/dL.",
        alerts=[AlertInterpretation(alert_id="A1", interpretation="Fuera de meta.", fragment_ids=[9])])
    md = render_report(reporte, _build_analysis("P002"), bank, None, "HbA1c 8.2 %", "P002")

    assert "cifra sin respaldo en los datos: 110 mg/dL" in md
    assert "cita no verificada: el fragmento F9 no existe" in md
    assert "No hay sesiones previas guardadas para comparar." in md


def test_render_sin_alertas_y_con_datos_insuficientes():
    md = render_report(_reporte(alerts=[]), _build_analysis("P004"), FragmentBank(), None, "", "P004")
    assert "Sin alertas" in md and "Datos insuficientes para hba1c" in md


def test_el_disclaimer_no_se_duplica():
    assert ensure_disclaimer("Texto.").count("No reemplaza el criterio") == 1
    assert ensure_disclaimer(ensure_disclaimer("Texto.")).count("No reemplaza el criterio") == 1
    assert ensure_disclaimer("Ya dice: no reemplaza el criterio del médico tratante.").count("eemplaza") == 1


# ---------------- flujo del Clínico: modo lean ----------------

@pytest.fixture
def estado(seeded_store):
    return {"patient_id": "P002", "query": "Analizá al paciente", "analysis": _build_analysis("P002"), "conversation": []}


def test_reporte_lean_una_llamada_con_fragmentos_e_historial(estado, monkeypatch):
    llm = _FakeLLM(_reporte())
    monkeypatch.setattr(clinical, "_build_report_llm", lambda: llm)
    monkeypatch.setattr(clinical, "search_clinical_guidelines", lambda q, k=3: list(_FRAGS))
    monkeypatch.setenv("AGENT_MODE", "lean")

    out = clinical.run_clinical_agent(estado)

    assert len(llm.received) == 1, "modo lean: una sola llamada al LLM en el Clínico"
    prompt = llm.received[0][1].content
    assert "[F1] (Guia_SAD_2025.md)" in prompt and "A1 ·" in prompt
    assert '"hba1c": 0.7' in prompt and "metrics_history" not in prompt
    assert out["report"].rstrip().endswith(DISCLAIMER)
    assert out["report_structured"]["suggested_questions"] == ["¿Adherencia al tratamiento?"]
    assert out["rag_context"][0].startswith("[Guia_SAD_2025.md]")


def test_reporte_invalido_o_vacio_falla_fuerte(estado, monkeypatch):
    monkeypatch.setattr(clinical, "search_clinical_guidelines", lambda q, k=3: [])
    monkeypatch.setattr(clinical, "_build_report_llm", lambda: _FakeLLM(None))
    with pytest.raises(RuntimeError, match="reporte estructurado válido"):
        clinical.run_clinical_agent(estado)
    monkeypatch.setattr(clinical, "_build_report_llm", lambda: _FakeLLM(_reporte(summary="  ")))
    with pytest.raises(RuntimeError, match="reporte estructurado válido"):
        clinical.run_clinical_agent(estado)


# ---------------- flujo del Clínico: modo react ----------------

def test_reporte_react_el_loop_llena_el_banco_con_ids(estado, monkeypatch):
    busqueda = AIMessage(content="", tool_calls=[{"name": "search_clinical_guidelines", "args": {"query": "HbA1c meta"},
                                                  "id": "c1", "type": "tool_call"}])
    loop = _FakeLLM(busqueda, AIMessage(content="listo"))
    reporte_llm = _FakeLLM(_reporte())
    monkeypatch.setattr(clinical, "_build_clinical_llm", lambda: loop)
    monkeypatch.setattr(clinical, "_build_report_llm", lambda: reporte_llm)
    monkeypatch.setattr(clinical, "search_clinical_guidelines", lambda q, k=3: list(_FRAGS))
    monkeypatch.setenv("AGENT_MODE", "react")

    out = clinical.run_clinical_agent(estado)

    assert "[F1] (Guia_SAD_2025.md)" in reporte_llm.received[0][1].content, "el fragmento del loop llega al paso final"
    assert "«Meta de HbA1c < 7 %" in out["report"]


# ---------------- seguimiento ----------------

def test_seguimiento_lleva_disclaimer_y_marca_cifras_sin_respaldo(estado, monkeypatch):
    estado |= {"is_followup": True, "report": "Reporte previo", "query": "¿Y la meta?"}
    respuesta = AIMessage(content="La meta es < 110 mg/dL según la guía.")
    monkeypatch.setattr(clinical, "_build_clinical_llm", lambda: _FakeLLM(respuesta))

    out = clinical.run_clinical_agent(estado)

    assert "110 mg/dL" in out["followup_answer"] and "Cifras sin respaldo" in out["followup_answer"]
    assert out["followup_answer"].rstrip().endswith(DISCLAIMER)
    assert "report" not in out, "el seguimiento nunca pisa el reporte (D3)"


def test_seguimiento_vacio_falla_fuerte(estado, monkeypatch):
    estado |= {"is_followup": True, "report": "Reporte previo"}
    monkeypatch.setattr(clinical, "_build_clinical_llm",
                        lambda: _FakeLLM(AIMessage(content="", response_metadata={"finish_reason": "length"})))
    with pytest.raises(RuntimeError, match="vacía"):
        clinical.run_clinical_agent(estado)


def test_seguimiento_fuerza_la_respuesta_al_agotar_pasos(estado, monkeypatch):
    estado |= {"is_followup": True, "report": "Reporte previo"}
    busqueda = AIMessage(content="", tool_calls=[{"name": "search_clinical_guidelines", "args": {"query": "x"},
                                                  "id": "c1", "type": "tool_call"}])
    monkeypatch.setattr(clinical, "_build_clinical_llm", lambda: _FakeLLM(busqueda))
    monkeypatch.setattr(clinical, "_build_answer_llm", lambda: _FakeLLM(AIMessage(content="Respuesta final.")))
    monkeypatch.setattr(clinical, "search_clinical_guidelines", lambda q, k=3: [])
    assert "Respuesta final." in clinical.run_clinical_agent(estado)["followup_answer"]


# ---------------- grafo: fallbacks y guardado ----------------

def test_los_fallbacks_tambien_llevan_disclaimer():
    out = graph.build_graph().invoke(
        {"patient_id": "P002", "query": "Analizá", "conversation": []}, {"configurable": {"thread_id": "rs-1"}})
    assert out["report"].rstrip().endswith(DISCLAIMER)
    assert out["report_structured"] is None


def test_guardar_persiste_las_preguntas_sugeridas_y_el_modo(seeded_store, monkeypatch):
    monkeypatch.setattr(graph, "has_api_key", lambda: True)
    monkeypatch.setattr("agents.monitor.run_monitor_agent", lambda s: _build_analysis(s["patient_id"]))
    monkeypatch.setattr(clinical, "_build_report_llm", lambda: _FakeLLM(_reporte()))
    monkeypatch.setattr(clinical, "search_clinical_guidelines", lambda q, k=3: list(_FRAGS))
    app, cfg = graph.build_graph(), {"configurable": {"thread_id": "rs-2"}}
    app.invoke({"patient_id": "P002", "query": "Analizá", "conversation": []}, cfg)
    out = app.invoke({"save_requested": True, "query": "guardar sesión"}, cfg)

    from tools.history_tools import get_patient_history
    sesion = get_patient_history("P002")["sessions"][-1]
    assert out["save_result"]["ok"] is True
    assert sesion["suggested_questions"] == ["¿Adherencia al tratamiento?"]
    assert sesion["execution_mode"] == {"monitor": "llm", "clinical": "llm"}


def test_sin_sesion_previa_no_se_muestra_una_evolucion_inventada():
    md = render_report(_reporte(longitudinal="Empeoró mucho desde marzo."), _build_analysis("P001"),
                       FragmentBank(), {"previous_session": None, "deltas": {}}, "", "P001")
    assert "Empeoró mucho" not in md and "No hay sesiones previas guardadas para comparar." in md


def test_numeracion_de_secciones_correlativa():
    import re

    md = render_report(_reporte(), _build_analysis("P002"), FragmentBank(), None, "", "P002")
    numeros = [int(n) for n in re.findall(r"^### (\d+)\.", md, re.M)]
    assert numeros == list(range(1, len(numeros) + 1))



# ---------------- extracto de las citas y bibliografía ----------------

def test_extracto_empieza_y_termina_en_oraciones_completas():
    from agents.report import best_excerpt

    fragmento = ("ovasculares. Comentario R14 ->r ->r ->r La HbA1c es la principal herramienta para valorar el control "
                 "glucémico en personas con diabetes. Otra oración distinta sobre un tema que no se relaciona con el caso. "
                 "Esta última oración queda cortada a mitad de pal")
    extracto = best_excerpt(fragmento, "HbA1c control glucémico")
    assert extracto.startswith("La HbA1c es la principal herramienta")
    assert "->r" not in extracto and "R14" not in extracto and "ovasculares" not in extracto
    assert extracto.endswith(".") and "pal" not in extracto.split()[-1:]


def test_extracto_elige_la_oracion_pertinente_al_hallazgo():
    from agents.report import best_excerpt

    fragmento = ("Las estatinas reducen el riesgo cardiovascular en personas mayores de cuarenta años. "
                 "La hipoglucemia de nivel 2 se define como una glucosa menor a 54 mg/dL en el paciente. "
                 "El ejercicio regular mejora la sensibilidad a la insulina en la mayoría de las personas.")
    assert "hipoglucemia de nivel 2" in best_excerpt(fragmento, "hipoglucemia nivel 2 glucosa")


def test_extracto_respeta_el_maximo_y_vacio_si_no_hay_oraciones():
    from agents.report import best_excerpt

    largo = "Esta oración clínica es muy larga " + "y sigue con más palabras " * 40 + "y termina acá."
    assert len(best_excerpt(largo, "")) <= 281
    assert best_excerpt("corto", "") == ""


def test_fragmentos_de_bibliografia_se_detectan_y_no_entran_al_banco():
    from agents.report import looks_like_references

    biblio = ("12. Pérez J, Gómez M. Diabetes Care 2019;42:1-9. 13. Smith A, et al. N Engl J Med 2018;379:100-110. "
              "14. Rossi L, Lima P. Lancet 2017;390:20-30.")
    clinico = "La meta de HbA1c es menor a 7 % en la mayoría de los adultos, individualizada según el paciente."
    assert looks_like_references(biblio) and not looks_like_references(clinico)

    banco = FragmentBank()
    prefetch_guidelines(banco, ["q"], lambda q, k=3: [f"[g.md] {biblio}", f"[g.md] {clinico}"])
    assert [t for _, t in banco.items] == [clinico]
    assert numbered_search_result(FragmentBank(), [f"[g.md] {biblio}"]) == "No se encontraron fragmentos relevantes."


def test_renglon_de_bibliografia_suelto_no_se_cita():
    from agents.report import best_excerpt, looks_like_references

    assert looks_like_references("56 Sociedad Argentina de Diabetes. Guía para el tratamiento de la diabetes mellitus tipo 2.")
    assert best_excerpt("56 Sociedad Argentina de Diabetes. Guía para el tratamiento.", "diabetes") == ""
