# `data/sample/` — datos de ejemplo (provisionales)

CSVs y medicación de ejemplo para **desarrollar y testear las tools determinísticas del
Monitor sin esperar a que B termine** el generador real (`data/generate_patients.py`) y
MongoDB. **Esto NO es el dataset final**: es un fixture que materializa el **contrato #1**
(schema del CSV del EHR) de forma ejecutable. Cuando B entregue, su generador debe producir
este mismo schema; coordinar cualquier cambio de columnas con el grupo.

## Schema del CSV (contrato #1)

Una fila por mes. Columnas — mapean 1:1 a `PatientMetrics` en
[orchestrator/state.py](../../orchestrator/state.py):

| Columna | Campo `PatientMetrics` | Unidad |
|---|---|---|
| `date` | `dates` (ISO `YYYY-MM-DD`) | — |
| `glucose_fasting` | `glucose_fasting` | mg/dL |
| `hba1c` | `hba1c` | % |
| `glucose_postprandial` | `glucose_postprandial` | mg/dL |
| `weight` | `weight` | kg |
| `blood_pressure_systolic` | `blood_pressure_systolic` | mmHg |
| `blood_pressure_diastolic` | `blood_pressure_diastolic` | mmHg |

`cgm_series` queda fuera de alcance (extensión futura).

`medications.json` mapea `patient_id → list[Medication]` (`name`, `dose`, `frequency`).

`patients_profile.json` tiene el perfil sintético de cada paciente (demografía, diagnósticos,
comorbilidades) y las **sesiones semilla** de P002 y P003 para demostrar la comparación longitudinal
([ADR-0012](../../docs/adr/0012-perfil-del-paciente-y-sesiones-semilla.md)). Lo carga `data/load_history.py`.

## Perfiles incluidos

| ID | Perfil | Qué ejercita |
|---|---|---|
| `P001` | **Controlado** | Sin violaciones de umbral → happy path "sin alertas". |
| `P002` | **Tendencia ascendente** | Las 3 métricas suben de `alerta` a `crítico` → alertas moderadas/severas + `direction = "subiendo"`. |
| `P003` | **Episodio de hipoglucemia** | HbA1c en banda `alerta`; un mes con glucosa en ayunas = 55 mg/dL → **alerta de hipoglucemia moderada** (`min_value` lo expone aunque la media lo diluya). |
| `P004` | **Datos insuficientes** | Una sola fila → las 6 métricas en `insufficient_data`; el reporte explicita la limitación. |
| `P005` | **Descompensación severa** | HbA1c 9.2 → 10.4, ayunas > 300 y una hipoglucemia de 48 mg/dL (tras iniciar insulina) → alertas **severas** en ambos lados. |

## Notas sobre los umbrales (importante)

- Las alertas se evalúan contra **metas de control de DM2** (`DM2_CONTROL_THRESHOLDS` en
  `tools/threshold_tools.py`, [ADR-0011](../../docs/adr/0011-metas-de-control-dm2.md)), no contra los
  criterios diagnósticos (que quedan como `ADA_DIAGNOSTIC_THRESHOLDS`, sin uso). Alertas esperadas:
  P001 0 · P002 17 moderadas · P003 1 (hipoglucemia) · P004 0 · P005 severas hiper e hipo.
- `detect_threshold_violations` cubre **hiper e hipoglucemia**: bandas altas (alerta/crítico)
  y bandas bajas (hipoglucemia `< 70` moderada, `< 54` severa) para las glucemias. Por eso el
  episodio de 55 mg/dL de `P003` se reporta como alerta de hipoglucemia.
- `weight` y la presión arterial no tienen umbrales en §2.6 → no generan alertas por ahora
  (sí se calculan sus estadísticas: `last_value`, `mean`, `min_value`, `max_value`, `delta`,
  `direction`).
