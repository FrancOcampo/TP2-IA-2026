# ADR-0011 · Alertas contra metas de control de DM2, no criterios diagnósticos

- **Estado:** Aceptado. La tabla está pendiente de validación clínica del equipo 🩺.
- **Fecha:** 2026-09-24
- **Relacionado:** plan F2-01 / decisión D1 · Linear EAS-12 · [ADR-0009](0009-ventana-principal-del-monitor.md)

## Contexto

- `ADA_THRESHOLDS` usaba **criterios diagnósticos**: HbA1c ≥ 5.7 prediabetes y ≥ 6.5 diabetes, ayunas 100/126,
  2 h poscarga 140/200. Todos los pacientes del sistema **ya tienen DM2**, así que aplicarlos generaba alertas
  clínicamente incorrectas: P003 (HbA1c 6.1, buen control) tenía 12 alertas "moderadas" y P002 tenía 34.
- Los límites de las guías mezclan comparadores estrictos ("> 9 %") y no estrictos ("< 7 %"). La tabla vieja los
  aplicaba todos como `>=`.
- El umbral vulnerado no dejaba rastro de su fuente.

## Decisión

1. **Metas de control por defecto** (`DM2_CONTROL_THRESHOLDS`, alias `THRESHOLDS`):

   | Métrica | Moderada | Severa | Fuente |
   |---|---|---|---|
   | HbA1c | ≥ 7.0 % | > 9.0 % | SAD 2025 (meta < 7 %); Guía Nacional 2019 (insulina si > 9 %) |
   | Glucosa en ayunas | > 130 mg/dL | > 300 mg/dL | SAD 2025 (80–130 matinal; > 300) |
   | Glucosa postprandial | ≥ 180 mg/dL | > 300 mg/dL | SAD 2025 (< 180) |
   | Hipoglucemia (ambas glucemias) | < 70 mg/dL | < 54 mg/dL | ADA 2024 §6 (fuera del corpus, F2-06) |

2. Cada banda es un `Band(severity, side, comparator, threshold, source)` con comparador **explícito**. La
   descripción de la alerta incluye umbral, comparador y fuente.
3. Los criterios diagnósticos se conservan como `ADA_DIAGNOSTIC_THRESHOLDS`, **sin uso por defecto**. El núcleo
   `_detect_violations` acepta la tabla como parámetro.
4. **P005** ("descompensación severa") ejercita la severidad `severa` en ambos lados, que con la tabla nueva ningún
   otro paciente alcanza.

## Alternativas consideradas

- **Mantener los criterios diagnósticos** — contradice D1 y satura el reporte con falsos positivos.
- **Metas individualizadas por paciente** (p. ej. HbA1c < 8 % en adultos mayores) — requiere datos del perfil que
  todavía no existen (F2-07). La tabla admite esa extensión cuando existan.
- **Guardar umbral y fuente como campos de `Alert`** — es F2-03 y cambia el contrato. Por ahora la trazabilidad va
  en la descripción.

## Consecuencias

- Alertas con los datos actuales: P001 0 · P002 17 moderadas · P003 1 (hipoglucemia) · P004 0 · P005 severas hiper
  e hipo (verificado en `tests/test_monitor_tools.py`).
- Los valores de 70–80 mg/dL en ayunas quedan bajo la meta pero no son hipoglucemia: no generan alerta. Es una
  decisión a revisar en la validación clínica.
- **Validación 🩺 pendiente:** el cierre formal de F2-01 exige que el equipo valide la tabla y deje constancia
  (fecha y quién) en el plan.
- Los casos de evaluación `happy_02` y `edge_03` deben actualizar su comportamiento esperado (F4-05).
