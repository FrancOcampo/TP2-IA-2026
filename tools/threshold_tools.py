# tools/threshold_tools.py
#
# Tool determinística del Agente Monitor: detección de valores fuera de las metas de control.
# Sigue el mismo lineamiento que patient_tools.py (ver "Flujo de métricas" en docs/CLAUDE.md):
# se invoca por `patient_id` + `metric` + `timerange`, carga y recorta los datos con el helper
# de ventaneo único, y delega en un núcleo puro (`_detect_violations`) testeable con listas.
# Devuelve list[Alert] (modelo de orchestrator/state.py).
#
# Umbrales (D1, ADR-0011): todos los pacientes del sistema YA tienen DM2, así que las alertas se
# evalúan contra METAS DE CONTROL (DM2_CONTROL_THRESHOLDS), no contra criterios diagnósticos.
# HbA1c 6.1 % es buen control, no una alerta. Los criterios diagnósticos quedan en
# ADA_DIAGNOSTIC_THRESHOLDS, sin uso por defecto.
#
# Cada métrica tiene banda ALTA (hiperglucemia) y/o BAJA (hipoglucemia). Cada banda declara su
# comparador explícito (">", ">=", "<"): las guías mezclan límites estrictos y no estrictos.
# Se evalúa primero la severidad mayor. Solo se emiten "moderada"/"severa" ("leve" reservada).
# Peso y presión arterial no tienen umbral todavía (F2-02) → devuelven [].
#
# 🩺 La tabla es una PROPUESTA pendiente de validación clínica del equipo (plan F2-01).

from __future__ import annotations

import operator
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

from orchestrator.state import Alert, TimeRange
from tools.patient_tools import get_metric_series, load_patient_data, window_metrics

_COMPARATORS = {">": operator.gt, ">=": operator.ge, "<": operator.lt, "<=": operator.le}


@dataclass(frozen=True)
class Band:
    """Un umbral: `value <comparator> threshold` → alerta de `severity` del lado `side`."""
    severity: str      # "moderada" | "severa"
    side: str          # "alta" (hiperglucemia) | "baja" (hipoglucemia)
    comparator: str    # ">", ">=", "<", "<="
    threshold: float
    source: str        # cita de la guía que respalda el umbral

    def matches(self, value: float) -> bool:
        return _COMPARATORS[self.comparator](value, self.threshold)


_SAD = "Guía SAD 2025"
_NACIONAL = "Guía Nacional de Práctica Clínica DM2 2019"
_ADA_HIPO = "ADA Standards of Care 2024 §6 (niveles de hipoglucemia; fuera del corpus, ver F2-06)"

# Hipoglucemia (igual para ayunas y postprandial): nivel 1 < 70, nivel 2 < 54 mg/dL.
_HYPO_BANDS = (
    Band("severa", "baja", "<", 54.0, _ADA_HIPO),
    Band("moderada", "baja", "<", 70.0, _ADA_HIPO),
)

# -------------------------------------------------------------------
# Metas de control para personas con DM2 (usadas por defecto) — D1
# -------------------------------------------------------------------

# metric -> {"label", "unit", "bands": (Band, ...)} con las bandas ordenadas de mayor a menor severidad
DM2_CONTROL_THRESHOLDS: dict[str, dict] = {
    "hba1c": {
        "label": "HbA1c", "unit": "%",
        "bands": (
            Band("severa", "alta", ">", 9.0, f"{_NACIONAL}: adición de insulina si HbA1c > 9 %"),
            Band("moderada", "alta", ">=", 7.0, f"{_SAD}: meta de HbA1c < 7 % (individualizable)"),
        ),
    },
    "glucose_fasting": {
        "label": "glucosa en ayunas", "unit": "mg/dL",
        "bands": (
            Band("severa", "alta", ">", 300.0, f"{_SAD}: glucemias > 300 mg/dl y/o HbA1c > 10 %"),
            Band("moderada", "alta", ">", 130.0, f"{_SAD}: glucemias matinales entre 80 y 130 mg/dl"),
            *_HYPO_BANDS,
        ),
    },
    "glucose_postprandial": {
        "label": "glucosa postprandial", "unit": "mg/dL",
        "bands": (
            Band("severa", "alta", ">", 300.0, f"{_SAD}: glucemias > 300 mg/dl"),
            Band("moderada", "alta", ">=", 180.0, f"{_SAD}: hasta lograr glucemias < 180 mg/dl"),
            *_HYPO_BANDS,
        ),
    },
}

# -------------------------------------------------------------------
# Criterios DIAGNÓSTICOS ADA — conservados como referencia, NO se usan por defecto
# -------------------------------------------------------------------

_ADA_DIAG = "ADA Standards of Care 2024 §2 (criterios diagnósticos)"
ADA_DIAGNOSTIC_THRESHOLDS: dict[str, dict] = {
    "hba1c": {
        "label": "HbA1c", "unit": "%",
        "bands": (
            Band("severa", "alta", ">=", 6.5, f"{_ADA_DIAG}: diabetes"),
            Band("moderada", "alta", ">=", 5.7, f"{_ADA_DIAG}: prediabetes"),
        ),
    },
    "glucose_fasting": {
        "label": "glucosa en ayunas", "unit": "mg/dL",
        "bands": (
            Band("severa", "alta", ">=", 126.0, f"{_ADA_DIAG}: diabetes"),
            Band("moderada", "alta", ">=", 100.0, f"{_ADA_DIAG}: glucemia alterada en ayunas"),
            *_HYPO_BANDS,
        ),
    },
    "glucose_postprandial": {
        "label": "glucosa postprandial", "unit": "mg/dL",
        "bands": (
            Band("severa", "alta", ">=", 200.0, f"{_ADA_DIAG}: diabetes (2 h poscarga)"),
            Band("moderada", "alta", ">=", 140.0, f"{_ADA_DIAG}: tolerancia alterada"),
            *_HYPO_BANDS,
        ),
    },
}

# Tabla activa: la que usan la tool y el Monitor.
THRESHOLDS = DM2_CONTROL_THRESHOLDS


# -------------------------------------------------------------------
# Tool 3 — detect_threshold_violations  (wrapper) + núcleo puro
# -------------------------------------------------------------------

def detect_threshold_violations(
    patient_id: str,
    metric: str,
    timerange: Optional[TimeRange] = None,
    data_dir: Path | None = None,
) -> list[Alert]:
    """
    Valores de `metric` fuera de las metas de control (THRESHOLDS) para `patient_id` sobre la ventana `timerange`
    (global si None). Carga y recorta los datos (mismo ventaneo que calculate_stats) y delega
    en `_detect_violations`. Métricas sin umbral definido (peso, presión) devuelven [].
    """
    if metric not in THRESHOLDS:
        return []
    metrics = window_metrics(load_patient_data(patient_id, data_dir), timerange)
    values = get_metric_series(metrics, metric)
    return _detect_violations(metric, values, metrics.dates)


def _detect_violations(
    metric: str,
    values: list[float],
    dates: list[date],
    table: dict[str, dict] = THRESHOLDS,
) -> list[Alert]:
    """
    Núcleo determinístico: compara cada valor contra las bandas de `metric` en `table` (metas
    de control DM2 por defecto) y devuelve una Alert por registro fuera de rango (con fecha,
    valor, severidad y descripción con el umbral vulnerado). `values` y `dates` deben tener el
    mismo largo (series alineadas).

    NOTA(contrato A+C): §2.6 definía `detect_threshold_violations(metric, values)`; Alert
    requiere la fecha del registro, así que el núcleo recibe `dates`. Ratificado por A y C.
    """
    spec = table.get(metric)
    if spec is None:
        return []
    if len(values) != len(dates):
        raise ValueError(
            f"values ({len(values)}) y dates ({len(dates)}) deben tener el mismo largo para '{metric}'"
        )

    alertas: list[Alert] = []
    for value, registro_date in zip(values, dates):
        band = _classify(value, spec["bands"])
        if band is None:
            continue
        alertas.append(Alert(
            metric=metric, value=value, severity=band.severity, date=registro_date,
            description=_describe(spec, value, band),
        ))
    return alertas


def _classify(value: float, bands: tuple[Band, ...]) -> Band | None:
    """Primera banda (de mayor a menor severidad, por lado) que el valor vulnera; None si está en meta."""
    return next((band for band in bands if band.matches(value)), None)


def _describe(spec: dict, value: float, band: Band) -> str:
    unit = spec["unit"]
    what = "hipoglucemia" if band.side == "baja" else "fuera de la meta de control"
    return (f"{spec['label']} = {value} {unit} ({what}, {band.severity}: "
            f"{band.comparator} {band.threshold:g} {unit}; {band.source})")
