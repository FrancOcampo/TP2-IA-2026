# main.py
#
# Punto de entrada del MVP (docs/plan_mvp.md): prepara lo local que falte y abre la UI.
#
#   uv run python main.py              # http://127.0.0.1:7860
#   uv run python main.py --no-ui      # solo prepara historial + índice (útil en CI)
#
# Pasos (todos idempotentes):
#   1. Historial: carga/actualiza los pacientes de data/sample/ (conserva sesiones guardadas).
#   2. Índice RAG: indexa las guías si falta o si cambió el embedding (~2.5 min la primera vez).
#   3. Informa si hay LLM configurado o si los agentes correrán en modo determinístico.

import argparse
import sys

from dotenv import load_dotenv

load_dotenv()


def bootstrap(ingest_if_missing: bool = True) -> None:
    from agents.llm_factory import llm_status
    from data.load_history import load_all
    from rag.ingest import index_ready, ingest
    from tools.history_store import get_store

    store = get_store()
    n = load_all(store, verbose=False)
    print(f"[1/3] Historial listo ({type(store).__name__}): {n} paciente(s).")

    if index_ready():
        print("[2/3] Índice de guías clínicas listo.")
    elif ingest_if_missing:
        print("[2/3] Indexando guías clínicas (solo la primera vez, ~2-3 min)…")
        ingest()
    else:
        print("[2/3] ⚠️ Sin índice de guías: los reportes saldrán sin citas (uv run python rag/ingest.py).")

    print(f"[3/3] {llm_status()}")


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Monitor Clínico · Diabetes tipo 2 (MVP)")
    parser.add_argument("--no-ui", action="store_true", help="solo preparar historial e índice")
    parser.add_argument("--skip-index", action="store_true", help="no indexar las guías si falta el índice")
    parser.add_argument("--port", type=int, default=None, help="puerto de la UI (default 7860)")
    args = parser.parse_args()

    bootstrap(ingest_if_missing=not args.skip_index)
    if args.no_ui:
        return

    from interface.app import launch
    launch(server_port=args.port)


if __name__ == "__main__":
    main()
