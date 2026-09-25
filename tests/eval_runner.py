# tests/eval_runner.py
#
# Evaluación CUALITATIVA del sistema de agentes (ver docs/tests.md). NO es un test de
# pytest: corre los casos de tests/cases/*.json contra el grafo con LLM real y vuelca un
# artefacto JSON (esperado vs. obtenido) que la pestaña "Evaluación" de la interfaz Gradio
# lee para mostrar una comparación clara. El día de mañana, el juicio manual del desarrollador
# sobre ese JSON lo reemplaza un LLM-as-judge.
#
# El JSON es un HISTORIAL append-only: es un array donde cada ejecución agrega una "corrida"
# (un objeto con solo los casos que se evaluaron esa vez). Así podés correr de a un caso o
# categoría —para no agotar los tokens del proveedor de una sola vez— y conservar el historial
# completo de evaluaciones, sin importar qué casos corriste en cada corrida.
#
# Uso:
#   uv run python tests/eval_runner.py                      # todos los casos (nueva corrida)
#   uv run python tests/eval_runner.py -c happy             # solo happy_path
#   uv run python tests/eval_runner.py --case happy_01      # un solo caso
#   uv run python tests/eval_runner.py -c edge --case edge_03
#   uv run python tests/eval_runner.py --list               # lista los casos y sale
#   uv run python tests/eval_runner.py --overwrite          # descarta el historial y empieza de cero

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

# Permite ejecutarlo como script suelto (sin -m) resolviendo la raíz del proyecto.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# IMPORTANTE: load_dotenv() ANTES de importar llm_factory / orchestrator.graph. La fábrica de
# LLM resuelve el proveedor leyendo LLM_PROVIDER, así que el .env tiene que estar cargado antes
# de cualquier construcción del LLM (igual que en interface/app.py). De lo contrario, con un
# LLM_PROVIDER=gemini en el .env el evaluador podría terminar usando el proveedor por default.
from dotenv import load_dotenv

load_dotenv()

from agents.llm_factory import active_model, has_api_key
from orchestrator.graph import build_graph

CASES_DIR = Path(__file__).parent / "cases"
CATEGORIES = ["happy_path", "edge_cases", "adversarial"]
DEFAULT_OUT = Path(__file__).resolve().parent.parent / "logs" / "eval_report.json"

# Alias cómodos para -c/--category (acepta el nombre completo o el corto).
CATEGORY_ALIASES = {
    "happy": "happy_path", "happy_path": "happy_path",
    "edge": "edge_cases", "edge_case": "edge_cases", "edge_cases": "edge_cases",
    "adv": "adversarial", "adversarial": "adversarial",
}


def _load_all_cases() -> list[dict]:
    cases = []
    for category in CATEGORIES:
        cases.extend(json.loads((CASES_DIR / f"{category}.json").read_text(encoding="utf-8")))
    return cases


def _split_multi(values: list[str] | None) -> list[str]:
    """Aplana valores repetidos y/o separados por coma: ['a,b','c'] → ['a','b','c']."""
    out = []
    for v in values or []:
        out.extend(part.strip() for part in v.split(",") if part.strip())
    return out


def _select_cases(all_cases: list[dict], categories: list[str], ids: list[str]) -> list[dict]:
    """Filtra los casos por categoría e id (intersección si se pasan ambos)."""
    selected = all_cases
    if categories:
        norm = set()
        for c in categories:
            key = c.lower()
            if key not in CATEGORY_ALIASES:
                sys.exit(f"❌ Categoría desconocida: {c!r}. Válidas: {', '.join(CATEGORIES)} "
                         f"(o alias: happy, edge, adv).")
            norm.add(CATEGORY_ALIASES[key])
        selected = [c for c in selected if c["category"] in norm]
    if ids:
        wanted = set(ids)
        known = {c["id"] for c in all_cases}
        for cid in wanted - known:
            print(f"⚠️  Caso inexistente, se ignora: {cid}")
        selected = [c for c in selected if c["id"] in wanted]
    return selected


class _DegradeCapture(logging.Handler):
    """
    Captura los errores que loguean los nodos del grafo cuando el LLM falla y caen al
    fallback determinístico (ver monitor_node/clinical_node en orchestrator/graph.py).

    Es la única forma de enterarse: el nodo atrapa la excepción del LLM internamente, así
    que `app.invoke` NO la propaga y la corrida "termina bien" con una salida del fallback
    sin LLM. Si no lo detectáramos, guardaríamos esa salida estática como si fuera del modelo
    e invalidaríamos en silencio la evaluación cualitativa del caso.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        msg = record.getMessage()
        if "fallback" in msg.lower():
            self.messages.append(msg)


def _run_case(case: dict) -> dict:
    """
    Corre setup + input sobre un thread aislado y devuelve la salida obtenida más
    metadatos del caso (reporte final, nº de alertas, duración, status y error si lo hubo).

    La "salida obtenida" es `followup_answer` si el último mensaje fue un seguimiento
    (`is_followup`) y `report` si no: el seguimiento nunca pisa el reporte (D3, F1-03).

    `status`: "ok" si corrió todo con LLM; "degraded" si algún nodo cayó al fallback
    determinístico (el LLM falló: rate limit, 413, timeout…) y la salida NO refleja al modelo.
    """
    app = build_graph()
    cfg = {"configurable": {"thread_id": f"eval-{case['id']}"}}

    invocations = list(case.get("setup", [])) + [case["input"]]
    invocations[0] = {"conversation": [], **invocations[0]}

    # Escuchamos los errores de fallback que emite el logger del grafo durante esta corrida.
    capture = _DegradeCapture()
    graph_logger = logging.getLogger("orchestrator.graph")
    graph_logger.addHandler(capture)
    try:
        start = time.perf_counter()
        final = None
        for payload in invocations:
            final = app.invoke(payload, cfg)
        duration = round(time.perf_counter() - start, 2)
    finally:
        graph_logger.removeHandler(capture)

    analysis = (final or {}).get("analysis")
    degraded = bool(capture.messages)
    return {
        # Un error de dominio (p. ej. paciente sin datos, ADR-0003) ES la salida que ve el médico.
        "obtained": (final or {}).get("error")
                    or (final or {}).get("followup_answer" if (final or {}).get("is_followup") else "report")
                    or "(sin respuesta)",
        "alerts_count": len(analysis.alerts) if analysis else None,
        "duration_s": duration,
        "status": "degraded" if degraded else "ok",
        "error": " | ".join(capture.messages) if degraded else None,
    }


def _load_history(path: Path) -> list[dict]:
    """
    Lee el historial de corridas previo (el array de objetos-corrida). Devuelve [] si no
    existe. Migra el formato viejo (un único objeto-reporte) envolviéndolo en una lista.
    Si está corrupto, aborta para no pisar el historial (usar --overwrite para empezar de cero).
    """
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        sys.exit(f"❌ {path} está corrupto y no se puede leer. Revisalo o usá --overwrite "
                 "para descartar el historial y empezar de cero.")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):  # formato viejo (un solo reporte) → una corrida
        return [data]
    return []


def _build_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Evaluación cualitativa: corre casos contra el grafo con LLM real y "
                    "agrega una corrida al historial JSON.",
    )
    p.add_argument("-c", "--category", action="append", metavar="CAT",
                   help="Categoría(s) a correr: happy_path|edge_cases|adversarial "
                        "(alias: happy/edge/adv). Repetible o separada por coma.")
    p.add_argument("--case", "--id", action="append", dest="case", metavar="ID",
                   help="ID(s) de caso a correr (ej. happy_01,edge_03). Repetible o separada por coma.")
    p.add_argument("-o", "--output", type=Path, default=DEFAULT_OUT,
                   help=f"Ruta del JSON de salida (default: {DEFAULT_OUT}).")
    p.add_argument("--overwrite", action="store_true",
                   help="Descarta el historial previo y empieza de cero (en vez de agregar una corrida).")
    p.add_argument("-l", "--list", action="store_true",
                   help="Lista los casos disponibles y sale (no necesita API key).")
    return p.parse_args()


def main() -> None:
    args = _build_args()
    all_cases = _load_all_cases()

    if args.list:
        print(f"Casos disponibles ({len(all_cases)}):")
        for c in all_cases:
            print(f"  · [{c['category']:<11}] {c['id']:<9} — {c['description']}")
        return

    selected = _select_cases(all_cases, _split_multi(args.category), _split_multi(args.case))
    if not selected:
        sys.exit("❌ Ningún caso coincide con el filtro. Probá --list para ver los disponibles.")

    # Mostramos en consola los WARNING+ del grafo/agentes —incluida la caída al fallback cuando
    # el LLM falla—. Hace falta un handler explícito en el root porque _DegradeCapture agrega un
    # handler al logger del grafo, y eso anula el `lastResort` de Python que antes imprimía solo
    # estos errores. Con basicConfig vuelven a verse (además de quedar marcados como `degraded`).
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s · %(name)s · %(message)s")

    if not has_api_key():
        print("⚠️  No hay API key: el grafo correría en fallback determinístico y la "
              "evaluación cualitativa no tendría sentido. Configurá GROQ_API_KEY/GOOGLE_API_KEY.")
        sys.exit(1)

    provider, model = active_model()
    out_path = args.output

    # Historial append-only: cargamos las corridas previas (salvo --overwrite) y al final
    # agregamos esta corrida con SOLO los casos que se evaluaron ahora.
    history = [] if args.overwrite else _load_history(out_path)

    print(f"Evaluando {len(selected)}/{len(all_cases)} caso(s) con LLM real "
          f"({provider} · {model}) → nueva corrida #{len(history) + 1}…")

    cases_result = []
    for case in selected:
        print(f"  · {case['id']}…")
        try:
            outcome = _run_case(case)
        except Exception as e:  # un caso roto no debe frenar la evaluación completa
            outcome = {
                "obtained": f"(ERROR: {type(e).__name__}: {e})",
                "alerts_count": None,
                "duration_s": None,
                "status": "error",
                "error": f"{type(e).__name__}: {e}",
            }
        cases_result.append({
            "id": case["id"],
            "category": case["category"],
            "description": case["description"],
            "input": case["input"],
            "setup": case.get("setup"),
            "expected_behavior": case["expected_behavior"],
            **outcome,
        })

    degraded_count = sum(1 for r in cases_result if r.get("status") == "degraded")
    error_count = sum(1 for r in cases_result if r.get("status") == "error")
    run = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "provider": provider,
        "model": model,
        "case_count": len(cases_result),
        "degraded_count": degraded_count,
        "error_count": error_count,
        "cases": cases_result,
    }
    history.append(run)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(history, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(f"✅ Corrida #{len(history)} agregada a {out_path} "
          f"({len(cases_result)} caso(s); {len(history)} corrida(s) en el historial).")
    if degraded_count or error_count:
        print(f"⚠️  {degraded_count} caso(s) degradado(s) al fallback (LLM falló) y "
              f"{error_count} con error: su salida NO refleja al modelo. Revisalos en la UI.")
    print("   Abrila en la pestaña «Evaluación» de la interfaz para comparar esperado vs. obtenido.")


if __name__ == "__main__":
    main()
