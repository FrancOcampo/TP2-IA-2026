# interface/app.py
#
# Interfaz Gradio del sistema multi-agente (tarea del Integrante D).
#
# Dos pestañas:
#   1. "Consulta clínica" — flujo del médico: seleccionar paciente → ver perfil → agregar
#      contexto → analizar → leer el reporte (panel principal) + chat de seguimiento → guardar.
#   2. "Observabilidad (dev)" — visor del log estructurado (logs/agent.jsonl) para desarrollo,
#      con filtro por tipo de evento, refresco y JSON crudo de cada traza.
#
# Conecta al grafo REAL (orchestrator.graph.app): con GROQ_API_KEY usa los agentes ReAct;
# sin ella, el grafo cae a sus fallbacks determinísticos. Los componentes de presentación
# viven en interface/components.py (funciones puras, testeables).

from dotenv import load_dotenv
load_dotenv()

import gradio as gr

from agents.llm_factory import has_api_key, llm_status
from orchestrator.graph import app as langgraph_app
from interface.logging_config import setup_logging, get_callbacks, tracing_status
from interface.components import (
    alerts_table,
    eval_case_choices,
    eval_case_view,
    eval_history_summary_md,
    eval_run_choices,
    eval_summary_md,
    find_eval_case,
    format_report,
    get_eval_run,
    list_patients,
    load_eval_history,
    load_log_entries,
    log_view_html,
    patient_profile,
    trends_view,
)
from tools.history_tools import get_patient_history
from tools.patient_tools import get_medication_schedule, load_patient_data

# Configura el logging propio (consola legible + logs/agent.jsonl) al iniciar.
setup_logging()

_thread_counter = 0


def _new_thread_id() -> str:
    """Nuevo thread_id de sesión para el checkpointer del grafo."""
    global _thread_counter
    _thread_counter += 1
    return f"session-{_thread_counter}"


def _last_assistant(conversation: list[dict]) -> str:
    """Último mensaje del asistente en la conversación acumulada del grafo."""
    for msg in reversed(conversation or []):
        if msg.get("role") == "assistant":
            return msg.get("content", "")
    return "(sin respuesta)"


def _config(thread_id: str) -> dict:
    """Config de invocación: thread_id de memoria + callbacks de observabilidad."""
    return {"configurable": {"thread_id": thread_id}, "callbacks": get_callbacks()}


# -------------------------------------------------------------------
# Callbacks de la UI — pestaña "Consulta clínica"
# -------------------------------------------------------------------

def on_patient_change(patient_id: str) -> str:
    """Carga el perfil resumido al seleccionar un paciente (paso 2 del flujo)."""
    metrics = meds = None
    if patient_id:
        try:
            metrics = load_patient_data(patient_id)
        except Exception:
            metrics = None
        try:
            meds = get_medication_schedule(patient_id)
        except Exception:
            meds = None
    history = get_patient_history(patient_id) if patient_id else None
    return patient_profile(patient_id, metrics, meds, history)


def analyze(patient_id: str, doctor_context: str):
    """Lanza el análisis completo (Monitor → Clínico) sobre un paciente nuevo."""
    if not patient_id:
        aviso = "Seleccioná un paciente antes de analizar."
        return [{"role": "assistant", "content": aviso}], "", format_report(None), alerts_table([]), trends_view(None)

    thread_id = _new_thread_id()
    state_input = {
        "patient_id": patient_id,
        "query": "Realizá un análisis clínico integral del paciente.",
        "doctor_context": doctor_context or "",
        "conversation": [],
    }
    try:
        out = langgraph_app.invoke(state_input, _config(thread_id))
    except Exception as e:
        err = f"⚠️ Error al ejecutar el análisis: {e}"
        return [{"role": "assistant", "content": err}], thread_id, format_report(None), alerts_table([]), trends_view(None)

    # Paciente sin datos en el EHR: se informa y no se muestran alertas ni tendencias (ADR-0003)
    error = out.get("error")
    if error:
        aviso = f"⚠️ {error}"
        sin_datos = "_Sin análisis: no hay datos del paciente en el EHR._"
        reporte = f"### {aviso}\n\nNo se generó reporte: el sistema no analiza pacientes sin datos."
        return [{"role": "assistant", "content": aviso}], thread_id, format_report(reporte), sin_datos, sin_datos

    analysis = out.get("analysis")
    alerts = analysis.alerts if analysis else []
    chat = [{
        "role": "assistant",
        "content": (
            f"✅ Análisis de **{patient_id}** completado: {len(alerts)} alerta(s). "
            "El reporte está en el panel principal. Hacé tu pregunta de seguimiento abajo."
        ),
    }]
    return chat, thread_id, format_report(out.get("report")), alerts_table(alerts), trends_view(analysis)


def follow_up(message: str, history: list, thread_id: str):
    """Pregunta de seguimiento sobre el reporte ya generado (va directo al Clínico)."""
    message = (message or "").strip()
    if not message:
        return history, ""
    if not thread_id:
        history = history + [
            {"role": "user", "content": message},
            {"role": "assistant", "content": "Primero analizá un paciente con **Analizar paciente**."},
        ]
        return history, ""

    try:
        out = langgraph_app.invoke({"query": message}, _config(thread_id))
        reply = _last_assistant(out.get("conversation", []))
    except Exception as e:
        reply = f"⚠️ Error: {e}"

    history = history + [
        {"role": "user", "content": message},
        {"role": "assistant", "content": reply},
    ]
    return history, ""


def save_session(thread_id: str, history: list):
    """Confirma el guardado de la sesión (rama 'save' del Orquestador)."""
    if not thread_id:
        return history + [{"role": "assistant", "content": "No hay sesión activa para guardar."}]
    try:
        # Señal explícita (D5): no depende de interpretar texto.
        out = langgraph_app.invoke({"save_requested": True, "query": "guardar sesión"}, _config(thread_id))
        msg = _last_assistant(out.get("conversation", []))
    except Exception as e:
        msg = f"⚠️ Error al guardar: {e}"
    return history + [
        {"role": "user", "content": "💾 Guardar sesión"},
        {"role": "assistant", "content": msg},
    ]


def reset_session():
    """Limpia la sesión para empezar una consulta nueva."""
    return [], "", format_report(None), alerts_table([]), trends_view(None), ""


# -------------------------------------------------------------------
# Callbacks de la UI — pestaña "Observabilidad (dev)"
# -------------------------------------------------------------------

# Tope de filas que se renderizan en el visor de logs. 50 trazas recientes alcanzan para
# el diagnóstico y mantienen la pestaña ágil aunque el .jsonl haya acumulado miles.
_LOG_VIEW_LIMIT = 50


def refresh_logs(event_filter: str) -> str:
    """Recarga las trazas del log y las devuelve como HTML para el visor."""
    entries = load_log_entries(
        None if event_filter == "todos" else event_filter,
        limit=_LOG_VIEW_LIMIT,
    )
    return log_view_html(entries)


def _langsmith_md() -> str:
    st = tracing_status()
    activo = st["langsmith_enabled"] and st["has_api_key"]
    estado = "✅ activo" if activo else "⚠️ inactivo (sin LANGSMITH_API_KEY o tracing off)"
    proj = st.get("project") or "—"
    return (
        f"**LangSmith:** {estado} · proyecto `{proj}` · "
        "[Abrir dashboard](https://smith.langchain.com)\n\n"
        "Las trazas también se registran localmente en `logs/agent.jsonl` (tabla de abajo)."
    )


# -------------------------------------------------------------------
# Callbacks de la UI — pestaña "Evaluación"
# -------------------------------------------------------------------

def _eval_case_panels(run, case_id=None):
    """(case_dd update, contexto, esperado, obtenido) para una corrida y caso dados."""
    case_choices = eval_case_choices(run)
    first = find_eval_case(run, case_id)
    case_id = first.get("id") if first else None
    context, expected, obtained = eval_case_view(run, case_id)
    return gr.update(choices=case_choices, value=case_id), context, expected, obtained


def load_eval():
    """
    Lee el historial de logs/eval_report.json y prepara la pestaña: resumen del historial,
    selector de corrida (última seleccionada), selector de caso y la comparación del primer
    caso de esa corrida. Se dispara al entrar a la pestaña y al refrescar.
    """
    history = load_eval_history()
    run_choices = eval_run_choices(history)
    latest_idx = (len(history) - 1) if history else None
    run = get_eval_run(history, latest_idx)
    case_dd_upd, context, expected, obtained = _eval_case_panels(run)
    return (
        history,                                          # eval_state
        eval_history_summary_md(history),                 # eval_history_summary
        gr.update(choices=run_choices, value=latest_idx), # eval_run_dd
        eval_summary_md(run),                             # eval_summary (de la corrida)
        case_dd_upd,                                      # eval_case_dd
        context, expected, obtained,                      # paneles
    )


def select_run(history, run_idx):
    """Al elegir otra corrida: re-renderiza su resumen, su selector de casos y el primer caso."""
    run = get_eval_run(history, run_idx)
    case_dd_upd, context, expected, obtained = _eval_case_panels(run)
    return eval_summary_md(run), case_dd_upd, context, expected, obtained


def show_eval_case(history, run_idx, case_id):
    """Re-renderiza la comparación al elegir otro caso dentro de la corrida actual."""
    run = get_eval_run(history, run_idx)
    return eval_case_view(run, case_id)


# -------------------------------------------------------------------
# Construcción de la UI
# -------------------------------------------------------------------

# -------------------------------------------------------------------
# Identidad visual: tema formal (serif) + CSS de la app
# -------------------------------------------------------------------
# Tema pensado para uso clínico: tipografía SERIF (Cambria → Georgia → Times New
# Roman como cascada del sistema), paleta azul-pizarra sobria y esquinas poco
# redondeadas para un aire institucional y formal. En Gradio 6 el `theme` y el
# `css` se pasan a launch() (ya no al constructor de Blocks).
_THEME = gr.themes.Default(
    primary_hue=gr.themes.colors.blue,
    secondary_hue=gr.themes.colors.sky,
    neutral_hue=gr.themes.colors.slate,
    text_size=gr.themes.sizes.text_md,
    spacing_size=gr.themes.sizes.spacing_md,
    radius_size=gr.themes.sizes.radius_md,
    # Fuentes del sistema (serif) envueltas en gr.themes.Font: pasarlas como str
    # crudo rompe la comparación interna de temas en launch() (Font.__eq__ vs str).
    font=[
        gr.themes.Font("Cambria"),
        gr.themes.Font("Georgia"),
        gr.themes.Font("Times New Roman"),
        gr.themes.Font("serif"),
    ],
    font_mono=[
        gr.themes.Font("ui-monospace"),
        gr.themes.Font("Consolas"),
        gr.themes.Font("SFMono-Regular"),
        gr.themes.Font("monospace"),
    ],
).set(
    block_title_text_weight="600",
    block_label_text_weight="600",
    block_shadow="0 1px 2px rgba(15, 23, 42, 0.04)",
    button_large_radius="*radius_md",
    button_small_radius="*radius_md",
    button_primary_background_fill="*primary_600",
    button_primary_background_fill_hover="*primary_700",
    button_primary_text_color="white",
)

# CSS de toda la app. Reforzamos la tipografía serif en el contenido Markdown,
# damos un look de tarjeta a los paneles, estilamos tablas (alertas/tendencias) y
# la cabecera institucional. Usamos variables del tema (--primary-*, --border-color-*,
# etc.) para que todo respete claro/oscuro automáticamente. Al final van los estilos
# del visor de logs (clase tp2-logs que emite components.log_view_html).
_APP_CSS = """
/* ===== Tipografía serif en todo el contenido ===== */
.gradio-container, .gradio-container .prose,
.gradio-container input, .gradio-container textarea,
.gradio-container button, .gradio-container select, .gradio-container label {
  font-family: "Cambria", "Georgia", "Times New Roman", serif;
}
/* Mantener monoespaciado donde corresponde (código, logs) */
.gradio-container .prose code, .gradio-container .prose pre,
.gradio-container code, .tp2-logs, .tp2-logs * { font-family: var(--font-mono); }

/* Legibilidad del contenido: interlineado cómodo y separadores sutiles */
.gradio-container .prose { line-height: 1.65; }
.gradio-container .prose p { margin: 0.5em 0; }
.gradio-container .prose ul, .gradio-container .prose ol { margin: 0.35em 0 0.7em; }
.gradio-container .prose li { margin: 0.15em 0; }
.gradio-container .prose hr { border: none; height: 1px; margin: 1.15em 0;
  background: var(--border-color-primary); opacity: 0.55; }

/* ===== Cabecera institucional ===== */
.tp2-header-wrap { border: none !important; background: transparent !important;
  box-shadow: none !important; padding: 0 !important; }
#tp2-header { background: linear-gradient(135deg, var(--primary-700), var(--primary-500));
  border: 1px solid var(--primary-800); border-radius: 14px; padding: 26px 30px;
  box-shadow: 0 6px 18px rgba(15, 23, 42, 0.18); }
#tp2-header .tp2-title { margin: 0; color: #fff; font-size: 1.95rem; font-weight: 700;
  letter-spacing: 0.2px; line-height: 1.2; }
#tp2-header .tp2-subtitle { margin: 8px 0 0; color: rgba(255, 255, 255, 0.92);
  font-size: 1.05rem; }
#tp2-header .tp2-disclaimer { display: inline-block; margin-top: 14px; padding: 5px 14px;
  font-size: 0.85rem; font-style: italic; color: #fff; background: rgba(255, 255, 255, 0.16);
  border: 1px solid rgba(255, 255, 255, 0.28); border-radius: 999px; }

/* ===== Tarjetas / paneles =====
   Usamos gr.Column (no gr.Group) para evitar divisores internos y dobles bordes.
   La tarjeta tiene fondo propio + sombra suave en capas → profundidad sin líneas duras.
   Los Markdown internos de Gradio ya son transparentes, así que el contenido vive
   directamente sobre la tarjeta (sin efecto "caja dentro de caja"). */
.tp2-card { background: var(--block-background-fill);
  border: 1px solid var(--border-color-primary); border-radius: 16px;
  padding: 18px 22px;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04), 0 6px 18px rgba(15, 23, 42, 0.06); }
.tp2-toolbar { padding-bottom: 20px; }

/* Perfil del paciente: tarjeta fina con borde neutro uniforme */
.tp2-profile { padding: 12px 18px !important; border: 1px solid var(--border-color-primary);
  border-radius: 12px;
  background: var(--block-background-fill);
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04); }

/* ===== Encabezados de contenido del agente (reporte) ===== */
.gradio-container .prose h1 { font-size: 1.45rem; margin: 0.2em 0 0.5em; }
.gradio-container .prose h2 { font-size: 1.2rem; color: var(--body-text-color);
  border-bottom: 1px solid var(--border-color-primary); padding-bottom: 5px;
  margin: 1em 0 0.6em; }
.gradio-container .prose h3 { font-size: 1.08rem; margin: 0.9em 0 0.4em; }
.gradio-container .prose blockquote { border-left: 3px solid var(--primary-500);
  background: var(--background-fill-secondary); padding: 10px 16px; border-radius: 10px;
  font-style: italic; color: var(--body-text-color-subdued); margin: 0.8em 0; }

/* ===== Títulos de sección: texto de alto contraste + filete de acento =====
   (van DESPUÉS de las reglas de .prose para ganar el empate de especificidad). */
.gradio-container .tp2-section-title h2, .gradio-container .tp2-section-title h3,
.gradio-container .tp2-section-title h4 { color: var(--body-text-color); font-weight: 700;
  letter-spacing: 0.2px; border: none; border-bottom: 2px solid var(--primary-500);
  display: inline-block; padding: 0 2px 5px 0; margin: 0 0 14px; }

/* ===== Pestañas ===== */
.gradio-container button[role="tab"] { font-size: 1.02rem; font-weight: 600;
  letter-spacing: 0.2px; }
.gradio-container button[role="tab"][aria-selected="true"] { font-weight: 700; }

/* ===== Tablas (alertas / tendencias / reporte) ===== */
.gradio-container .prose table { border-collapse: collapse; width: 100%;
  margin: 0.4rem 0 0.9rem; font-size: 0.93rem; border: 1px solid var(--border-color-primary); }
.gradio-container .prose thead th { background: var(--background-fill-secondary);
  color: var(--body-text-color); font-weight: 700; text-align: left; padding: 9px 12px;
  border-bottom: 2px solid var(--border-color-primary); white-space: nowrap; }
.gradio-container .prose tbody td { padding: 8px 12px; vertical-align: top;
  border-bottom: 1px solid var(--border-color-primary); }
.gradio-container .prose tbody tr:nth-child(even) td {
  background: color-mix(in srgb, var(--background-fill-secondary) 45%, transparent); }
.gradio-container .prose tbody tr:hover td {
  background: color-mix(in srgb, var(--primary-100) 50%, transparent); }

/* ===== Botones primarios (degradado sobrio + leve elevación al hover) ===== */
.gradio-container button.primary { font-weight: 700; letter-spacing: 0.3px; border: none;
  background: linear-gradient(135deg, var(--primary-500), var(--primary-700));
  transition: transform 0.12s ease, box-shadow 0.12s ease, filter 0.12s ease; }
.gradio-container button.primary:hover { transform: translateY(-1px); filter: brightness(1.04);
  box-shadow: 0 6px 16px color-mix(in srgb, var(--primary-600) 38%, transparent); }

/* ===== Visor de logs (pestaña Observabilidad) ===== */
.tp2-logs { font-size: 12px; max-height: 460px; overflow-y: auto;
  border: 1px solid var(--border-color-primary); border-radius: 6px; }
.tp2-head, .tp2-cells { display: grid; gap: 8px; align-items: center;
  grid-template-columns: 96px 84px 150px 1fr; padding: 5px 10px; }
.tp2-head { position: sticky; top: 0; z-index: 1; font-weight: 600;
  background: var(--background-fill-secondary);
  border-bottom: 1px solid var(--border-color-primary); }
.tp2-row { border-bottom: 1px solid var(--border-color-primary); }
.tp2-row > summary { cursor: pointer; list-style: none; }
.tp2-row > summary::-webkit-details-marker { display: none; }
.tp2-row > summary:hover { background: var(--background-fill-secondary); }
.tp2-ts::before { content: "▸ "; color: var(--body-text-color-subdued); }
.tp2-row[open] > summary .tp2-ts::before { content: "▾ "; }
.tp2-nm, .tp2-sm { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tp2-ev { color: var(--body-text-color-subdued); }
.tp2-raw { margin: 0; padding: 8px 12px; white-space: pre-wrap; word-break: break-word;
  font-size: 11px; background: var(--background-fill-secondary); }
.tp2-empty { padding: 14px; color: var(--body-text-color-subdued); }

/* ===== Evaluación (pestaña de comparación esperado vs. obtenido) ===== */
/* Tira de contexto del caso: tarjeta fina con borde neutro uniforme, igual que el perfil. */
.tp2-eval-context { padding: 12px 18px !important; border: 1px solid var(--border-color-primary);
  border-radius: 12px;
  background: var(--block-background-fill);
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04); margin: 6px 0 4px; }
.tp2-eval-context h4 { margin: 0 0 6px; }
/* Las dos columnas a la misma altura, con scroll interno para reportes largos. */
.tp2-eval-panel { height: 100%; }
.tp2-eval-expected, .tp2-eval-obtained { max-height: 540px; overflow-y: auto;
  padding: 4px; }
"""


def build_demo() -> gr.Blocks:
    with gr.Blocks(title="Monitor Clínico — Diabetes") as demo:
        gr.HTML(
            "<div id='tp2-header'>"
            "<h1 class='tp2-title'>🩺 Monitor Clínico · Diabetes tipo 2</h1>"
            "<p class='tp2-subtitle'>Sistema multiagente de soporte a la decisión clínica</p>"
            "<span class='tp2-disclaimer'>"
            "Este sistema no emite diagnósticos, es solo un insumo para el médico tratante."
            "</span></div>",
            elem_classes="tp2-header-wrap",
        )
        # Modo de ejecución visible: sin API key los reportes son de los fallbacks determinísticos.
        gr.Markdown(("🟢 " if has_api_key() else "⚠️ ") + llm_status())

        thread_state = gr.State("")

        with gr.Tabs():
            # ---------------- Pestaña 1: Consulta clínica ----------------
            with gr.Tab("🗂  Consulta clínica"):
                with gr.Column(elem_classes="tp2-card tp2-toolbar"):
                    gr.Markdown("#### Nueva consulta", elem_classes="tp2-section-title")
                    with gr.Row():
                        patient_dd = gr.Dropdown(
                            choices=list_patients(), label="Paciente", scale=2,
                            info="Datos cargados desde el EHR (data/sample/).",
                        )
                        context_tb = gr.Textbox(
                            label="Contexto clínico adicional (opcional)", scale=3, lines=2,
                            placeholder="Síntomas recientes, eventos intercurrentes, adherencia referida…",
                        )
                        analyze_btn = gr.Button(
                            "Analizar paciente", variant="primary", scale=1, size="lg",
                        )

                profile_md = gr.Markdown(
                    "_Seleccioná un paciente para ver su perfil._",
                    elem_classes="tp2-profile",
                )

                with gr.Row():
                    # Panel principal: reporte clínico
                    with gr.Column(scale=2):
                        with gr.Column(elem_classes="tp2-card"):
                            gr.Markdown("### Reporte clínico", elem_classes="tp2-section-title")
                            report_md = gr.Markdown(format_report(None))
                        with gr.Accordion("🔔  Alertas detectadas", open=True):
                            alerts_md = gr.Markdown(alerts_table([]))
                        with gr.Accordion("📈  Tendencias por métrica", open=False):
                            trends_md = gr.Markdown(trends_view(None))

                    # Panel secundario: chat de seguimiento
                    with gr.Column(scale=1):
                        with gr.Column(elem_classes="tp2-card"):
                            gr.Markdown("### Seguimiento", elem_classes="tp2-section-title")
                            chatbot = gr.Chatbot(
                                label="Conversación", height=380, buttons=["copy_all"],
                                placeholder="El chat se habilita tras analizar un paciente.",
                            )
                            query_tb = gr.Textbox(
                                show_label=False, submit_btn=True,
                                placeholder="Pregunta de seguimiento sobre el reporte…",
                            )
                            with gr.Row():
                                save_btn = gr.Button("💾  Guardar sesión", variant="secondary")
                                reset_btn = gr.Button("Nueva sesión")

            # ---------------- Pestaña 2: Observabilidad (dev) ----------------
            with gr.Tab("🛠  Observabilidad (dev)") as obs_tab:
                langsmith_md = gr.Markdown(_langsmith_md())
                with gr.Row():
                    event_filter_dd = gr.Dropdown(
                        choices=["todos", "node", "routing", "llm", "tool"],
                        value="todos", label="Filtrar por tipo de evento", scale=3,
                    )
                    refresh_btn = gr.Button("🔄 Refrescar", scale=1)
                gr.Markdown(
                    "_Trazas (`logs/agent.jsonl`) — hacé clic en una fila para ver su JSON crudo:_"
                )
                # Visor liviano: HTML estático con filas expandibles (components.log_view_html).
                # Reemplaza al gr.Dataframe, cuyo montaje en el navegador congelaba la pestaña
                # ~15 s la primera vez que se abría. El HTML se pinta en milisegundos.
                logs_html = gr.HTML(log_view_html([]))

            # ---------------- Pestaña 3: Evaluación (dev) ----------------
            # Lee el artefacto logs/eval_report.json (lo produce tests/eval_runner.py) y muestra
            # una comparación clara esperado vs. obtenido por caso, para puntuar la calidad a ojo.
            with gr.Tab("🧪  Evaluación") as eval_tab:
                eval_state = gr.State([])  # historial de corridas cargado (lista)
                with gr.Row():
                    eval_history_summary = gr.Markdown(eval_history_summary_md(None), scale=4)
                    eval_refresh_btn = gr.Button("🔄 Refrescar", scale=1)
                with gr.Row():
                    eval_run_dd = gr.Dropdown(
                        choices=[], label="Corrida", scale=2,
                        info="Cada ejecución de eval_runner.py agrega una corrida al historial.",
                    )
                    eval_case_dd = gr.Dropdown(
                        choices=[], label="Caso de evaluación", scale=3,
                        info="Casos evaluados en la corrida seleccionada.",
                    )
                eval_summary = gr.Markdown(eval_summary_md(None))
                eval_context_md = gr.Markdown(
                    "_Seleccioná un caso para ver la comparación._",
                    elem_classes="tp2-eval-context",
                )
                with gr.Row(equal_height=True):
                    with gr.Column(scale=1):
                        with gr.Column(elem_classes="tp2-card tp2-eval-panel"):
                            gr.Markdown("### ✅ Comportamiento esperado",
                                        elem_classes="tp2-section-title")
                            eval_expected_md = gr.Markdown("", elem_classes="tp2-eval-expected")
                    with gr.Column(scale=1):
                        with gr.Column(elem_classes="tp2-card tp2-eval-panel"):
                            gr.Markdown("### 🔍 Salida obtenida",
                                        elem_classes="tp2-section-title")
                            eval_obtained_md = gr.Markdown("", elem_classes="tp2-eval-obtained")

        # ---------------- Wiring de eventos ----------------
        patient_dd.change(on_patient_change, inputs=patient_dd, outputs=profile_md)

        analyze_btn.click(
            analyze,
            inputs=[patient_dd, context_tb],
            outputs=[chatbot, thread_state, report_md, alerts_md, trends_md],
        )

        query_tb.submit(
            follow_up,
            inputs=[query_tb, chatbot, thread_state],
            outputs=[chatbot, query_tb],
        )

        save_btn.click(save_session, inputs=[thread_state, chatbot], outputs=chatbot)

        reset_btn.click(
            reset_session,
            outputs=[chatbot, thread_state, report_md, alerts_md, trends_md, context_tb],
        )

        # Observabilidad: cargar las trazas al ENTRAR a la pestaña (no en el arranque de la
        # app, para no leer el log si el médico nunca abre la vista dev), más refresco manual
        # y al cambiar el filtro. El detalle crudo de cada traza se ve expandiendo su fila.
        for trigger in (refresh_btn.click, event_filter_dd.change, obs_tab.select):
            trigger(refresh_logs, inputs=event_filter_dd, outputs=logs_html)

        # Evaluación: al ENTRAR a la pestaña y al refrescar, cargar el historial (resumen +
        # selector de corrida + selector de caso + comparación del primer caso de la última
        # corrida). Al cambiar de corrida se re-arma su resumen/casos; al cambiar de caso, solo
        # la comparación.
        eval_load_outputs = [
            eval_state, eval_history_summary, eval_run_dd, eval_summary, eval_case_dd,
            eval_context_md, eval_expected_md, eval_obtained_md,
        ]
        for trigger in (eval_refresh_btn.click, eval_tab.select):
            trigger(load_eval, outputs=eval_load_outputs)

        eval_run_dd.change(
            select_run,
            inputs=[eval_state, eval_run_dd],
            outputs=[eval_summary, eval_case_dd,
                     eval_context_md, eval_expected_md, eval_obtained_md],
        )

        eval_case_dd.change(
            show_eval_case,
            inputs=[eval_state, eval_run_dd, eval_case_dd],
            outputs=[eval_context_md, eval_expected_md, eval_obtained_md],
        )

    return demo


demo = build_demo()


def launch(**kwargs) -> None:
    """Lanza la UI. En Gradio 6 css y theme se pasan a launch() (ya no al constructor de Blocks)."""
    demo.launch(theme=_THEME, css=_APP_CSS, **kwargs)


if __name__ == "__main__":
    launch()
