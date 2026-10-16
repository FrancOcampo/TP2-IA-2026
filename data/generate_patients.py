# data/generate_patients.py
#
# Genera los CSVs sintéticos de pacientes en data/sample/.
# Cada CSV tiene una fila por mes con métricas clínicas de un paciente ficticio.
# Los 5 perfiles cubren los escenarios de test: controlado, tendencia ascendente,
# episodio de hipoglucemia, datos insuficientes y descompensación severa.
# Las alertas se evalúan contra METAS DE CONTROL de DM2 (tools/threshold_tools.py, ADR-0011).
#
# Ejecutar: uv run python data/generate_patients.py

import csv
from pathlib import Path

OUTPUT_DIR = Path(__file__).resolve().parent / "sample"

COLUMNS = [
    "date",
    "glucose_fasting",
    "hba1c",
    "glucose_postprandial",
    "weight",
    "blood_pressure_systolic",
    "blood_pressure_diastolic",
]

# Fechas de los 12 meses de 2025 (día 15 de cada mes)
DATES_2025 = [f"2025-{m:02d}-15" for m in range(1, 13)]


def write_csv(patient_id: str, rows: list[dict]) -> None:
    path = OUTPUT_DIR / f"{patient_id}.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"  {path.name} — {len(rows)} fila(s)")


def generate_p001() -> None:
    """
    P001 — Paciente controlado.
    Todos los valores dentro de las metas de control durante todo el año → sin alertas.
    HbA1c 5.2 (< 7.0), glucosa en ayunas 88 (80–130), postprandial 125 (< 180).
    """
    rows = []
    for date in DATES_2025:
        rows.append({
            "date": date,
            "glucose_fasting": 88.0,
            "hba1c": 5.2,
            "glucose_postprandial": 125.0,
            "weight": 72.0,
            "blood_pressure_systolic": 118.0,
            "blood_pressure_diastolic": 76.0,
        })
    write_csv("P001", rows)


def generate_p002() -> None:
    """
    P002 — Tendencia ascendente (descompensación progresiva).
    HbA1c sube de 6.0 a 8.2 a lo largo del año (delta = 2.2, direction = 'subiendo').
    Empieza en meta y sale de ella en el segundo semestre. Glucosa en ayunas y postprandial
    también suben con la HbA1c.

    Valores clave que los tests verifican (metas de control):
      - hba1c[0] = 6.0, hba1c[-1] = 8.2  → delta = 2.2
      - 17 alertas moderadas, 0 severas: ayunas > 130 (5) · HbA1c ≥ 7.0 (6) · postprandial ≥ 180 (6).
      - Los primeros 3 meses están en meta → sin alertas en esa ventana.
    """
    hba1c_values =    [6.0, 6.2, 6.4, 6.5, 6.7, 6.9, 7.1, 7.3, 7.5, 7.7, 8.0, 8.2]
    glucose_fasting = [98,  102, 108, 115, 120, 125, 128, 132, 138, 142, 148, 155]
    glucose_post =    [135, 145, 155, 162, 168, 175, 180, 185, 192, 198, 202, 210]
    weight =          [85,  85,  86,  86,  87,  87,  88,  88,  89,  89,  90,  90 ]
    bp_sys =          [125, 126, 127, 128, 129, 130, 131, 132, 133, 134, 135, 136]
    bp_dia =          [82,  82,  83,  83,  84,  84,  85,  85,  86,  86,  87,  87 ]

    rows = []
    for i, date in enumerate(DATES_2025):
        rows.append({
            "date": date,
            "glucose_fasting": float(glucose_fasting[i]),
            "hba1c": hba1c_values[i],
            "glucose_postprandial": float(glucose_post[i]),
            "weight": float(weight[i]),
            "blood_pressure_systolic": float(bp_sys[i]),
            "blood_pressure_diastolic": float(bp_dia[i]),
        })
    write_csv("P002", rows)


def generate_p003() -> None:
    """
    P003 — Episodio de hipoglucemia.
    HbA1c estable en 6.1: buen control (< 7.0), no genera alerta.
    Un solo mes (agosto, índice 7) tiene glucose_fasting = 55.0 mg/dL:
      - 55 < 70 → hipoglucemia moderada (nivel 1 ADA).
      - El resto de los meses tiene glucosa en ayunas normal (~90 mg/dL).
      - La media del año queda alrededor de 88 (el 55 queda 'diluido'),
        pero min_value = 55.0 lo expone. Esto es lo que el test verifica.

    Tests que deben pasar:
      - detect_threshold_violations("P003", "glucose_fasting") → exactamente 1 alerta,
        value=55.0, severity="moderada", description contiene "hipoglucemia".
    """
    glucose_fasting = [90, 92, 88, 91, 89, 93, 90, 55, 91, 88, 92, 90]  # índice 7 = agosto

    rows = []
    for i, date in enumerate(DATES_2025):
        rows.append({
            "date": date,
            "glucose_fasting": float(glucose_fasting[i]),
            "hba1c": 6.1,
            "glucose_postprandial": 138.0,
            "weight": 68.0,
            "blood_pressure_systolic": 122.0,
            "blood_pressure_diastolic": 79.0,
        })
    write_csv("P003", rows)


def generate_p004() -> None:
    """
    P004 — Datos insuficientes.
    Una sola fila, todos los valores en meta → sin alertas.
    Con un solo registro no hay tendencia evaluable: el Monitor declara las 6 métricas en
    insufficient_data y el reporte explicita la limitación (ADR-0003, ADR-0010).
    """
    rows = [{
        "date": "2025-06-15",
        "glucose_fasting": 118.0,
        "hba1c": 6.5,
        "glucose_postprandial": 162.0,
        "weight": 78.0,
        "blood_pressure_systolic": 128.0,
        "blood_pressure_diastolic": 82.0,
    }]
    write_csv("P004", rows)


def generate_p005() -> None:
    """
    P005 — Descompensación severa.
    HbA1c de 9.2 a 10.4 (todas > 9.0 → severas). Se inicia insulina basal y en agosto hay una
    hipoglucemia de 48 mg/dL (< 54, nivel 2 → severa); después vuelve a descompensarse con
    glucemias en ayunas > 300 (severas). Ejercita la severidad "severa" en ambos lados, que con
    las metas de control ningún otro paciente alcanza.
    """
    hba1c_values =    [9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 9.8, 9.9, 10.0, 10.1, 10.2, 10.4]
    glucose_fasting = [215, 228, 240, 252, 268, 284, 296, 48,  288,  305,  312,  326]
    glucose_post =    [260, 272, 280, 290, 298, 305, 312, 150, 300,  318,  325,  340]
    weight =          [92,  92,  91,  91,  90,  90,  89,  89,  89,   88,   88,   88 ]
    bp_sys =          [138, 138, 139, 140, 140, 141, 142, 138, 142,  143,  144,  145]
    bp_dia =          [88,  88,  88,  89,  89,  90,  90,  86,  90,   91,   91,   92 ]

    rows = []
    for i, date in enumerate(DATES_2025):
        rows.append({
            "date": date,
            "glucose_fasting": float(glucose_fasting[i]),
            "hba1c": hba1c_values[i],
            "glucose_postprandial": float(glucose_post[i]),
            "weight": float(weight[i]),
            "blood_pressure_systolic": float(bp_sys[i]),
            "blood_pressure_diastolic": float(bp_dia[i]),
        })
    write_csv("P005", rows)


if __name__ == "__main__":
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Generando CSVs en {OUTPUT_DIR}/")
    generate_p001()
    generate_p002()
    generate_p003()
    generate_p004()
    generate_p005()
    print("Listo.")
