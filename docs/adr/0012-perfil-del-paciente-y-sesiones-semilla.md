# ADR-0012 · Perfil clínico del paciente, sesiones semilla y tools de historial que no lanzan

- **Estado:** Aceptado
- **Fecha:** 2026-09-24
- **Relacionado:** plan F2-07 · Linear EAS-18 · [ADR-0005](0005-historial-en-sqlite-local.md), [ADR-0008](0008-guardado-explicito-de-sesion.md)

## Contexto

- El artículo dice que `get_patient_history` recupera "diagnósticos, comorbilidades, medicación base y sesiones
  anteriores". El documento del paciente solo tenía métricas, medicación y `sessions: []`, así que en una demo la
  comparación longitudinal nunca tenía datos.
- `get_patient_history` lanzaba `ValueError` para un paciente inexistente. Dentro del loop ReAct eso tumbaba al
  Clínico y lo mandaba al fallback.

## Decisión

1. **Schema del documento:** `demographics {age, sex}`, `diagnoses [{code, label, since}]`, `comorbidities [str]`,
   `metrics_history`, `medications` (medicación de base) y `sessions`. Es igual en SQLite y MongoDB.
2. **Fixture** `data/sample/patients_profile.json` con el perfil sintético de P001–P005 y **sesiones semilla** para
   P002 (3) y P003 (2). Sus `metrics_summary` coinciden con los CSV del mes de cada consulta y el texto las marca
   como sintéticas (`seed: true`).
3. **Carga idempotente:** las sesiones semilla tienen id fijo y `HistoryStore.add_session` es idempotente por
   `session_id`. Recargar no duplica, y las sesiones que guarda el médico se conservan.
4. **Las tools de historial no lanzan:** `get_patient_history` devuelve `found: False` para un paciente inexistente o
   un almacén caído, y los wrappers del Clínico devuelven `{"error": ...}` en JSON ante cualquier excepción.
5. La UI muestra demografía, diagnósticos, comorbilidades y cantidad de sesiones previas en el perfil.

## Alternativas consideradas

- **Generar sesiones semilla con código al vuelo** — oculta los datos de demo. Un JSON versionado se revisa y se
  edita a mano.
- **Guardar el perfil en los CSV del EHR** — mezcla datos longitudinales (una fila por mes) con datos estáticos del
  paciente.

## Consecuencias

- La comparación longitudinal es demostrable desde el primer arranque: P002 tiene HbA1c 7.5 % en la última sesión
  semilla y 8.2 % actual.
- `compare_with_previous_sessions` sigue sin clasificar la evolución (F2-04), pero ya tiene datos contra los que
  comparar.
- Los datos del perfil son sintéticos y no clínicos. No reemplazan una historia clínica real.
