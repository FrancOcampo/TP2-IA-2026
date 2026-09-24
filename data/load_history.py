# data/load_history.py
#
# Carga los pacientes sintéticos de data/sample/ en el almacén de historial
# (SQLite local por defecto, o MongoDB con HISTORY_BACKEND=mongo; ver tools/history_store.py).
# Es idempotente: reemplaza el perfil de cada paciente y conserva sus sesiones guardadas.
#
# Ejecutar: uv run python data/load_history.py

import csv
import json
import sys
from pathlib import Path

# Permite correrlo como script (`python data/load_history.py`) además de importarlo.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.history_store import HistoryStore, get_store  # noqa: E402

SAMPLE_DIR = Path(__file__).resolve().parent / "sample"


def patient_ids() -> list[str]:
    """Pacientes disponibles: uno por CSV en data/sample/."""
    return sorted(p.stem for p in SAMPLE_DIR.glob("*.csv"))


def _load_csv(patient_id: str) -> list[dict]:
    path = SAMPLE_DIR / f"{patient_id}.csv"
    with path.open(encoding="utf-8") as f:
        return [
            {"date": row["date"], **{k: float(v) for k, v in row.items() if k != "date"}}
            for row in csv.DictReader(f)
        ]


def _load_medications() -> dict[str, list[dict]]:
    with (SAMPLE_DIR / "medications.json").open(encoding="utf-8") as f:
        return json.load(f)


def build_patient_doc(patient_id: str, metrics: list[dict], medications: list[dict]) -> dict:
    """
    Schema del documento de paciente (igual en SQLite y MongoDB).

    {
      patient_id: str,
      metrics_history: [ { date, glucose_fasting, hba1c, glucose_postprandial,
                           weight, blood_pressure_systolic, blood_pressure_diastolic } ],
      medications: [ { name, dose, frequency } ],
      sessions: [ ... ]   # las agrega update_patient_history(); la carga no las toca
    }
    """
    return {"patient_id": patient_id, "metrics_history": metrics, "medications": medications}


def load_all(store: HistoryStore, verbose: bool = True) -> int:
    medications_map = _load_medications()
    ids = patient_ids()
    for pid in ids:
        metrics = _load_csv(pid)
        meds = medications_map.get(pid, [])
        store.upsert_patient(build_patient_doc(pid, metrics, meds))
        if verbose:
            print(f"  {pid} — {len(metrics)} registro(s), {len(meds)} medicamento(s)")
    return len(ids)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    store = get_store()
    print(f"Cargando pacientes en {type(store).__name__}…")
    load_all(store)
    print(f"Listo. Pacientes: {', '.join(store.list_patient_ids())}")


if __name__ == "__main__":
    main()
