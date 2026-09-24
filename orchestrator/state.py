from typing import TypedDict, Optional, Annotated
from pydantic import BaseModel, Field, model_validator
from datetime import date
import operator


# -------------------------------------------------------------------
# Modelos de datos — métricas del paciente
# -------------------------------------------------------------------

class CGMMetrics(BaseModel):   #SE DEFINE PERO NO SE USA, QUEDA FUERA DEL ALCANCE DEL TP
    """Métricas derivadas de monitoreo continuo de glucosa (CGM)."""
    time_in_range: float           # TIR: % lecturas entre 70-180 mg/dL
    time_below_range: float        # TBR: % lecturas < 70 mg/dL
    time_above_range: float        # TAR: % lecturas > 180 mg/dL
    coefficient_of_variation: float  # CV >= 36% indica alta variabilidad
    nocturnal_hypo_episodes: int   # episodios de hipoglucemia nocturna
    glucose_mean: float            # glucosa media del período
    estimated_hba1c: float         # HbA1c estimada a partir del CGM


class PatientMetrics(BaseModel):
    """Series temporales de métricas clínicas del paciente (EHR)."""
    dates: list[date]
    glucose_fasting: list[float]        # glucosa en ayunas (mg/dL)
    hba1c: list[float]                  # HbA1c (%)
    glucose_postprandial: list[float]   # glucosa postprandial (mg/dL)
    weight: list[float]                 # peso (kg)
    blood_pressure_systolic: list[float]   # presión sistólica (mmHg)
    blood_pressure_diastolic: list[float]  # presión diastólica (mmHg)
    cgm_series: Optional[list[float]] = None  # lecturas CGM crudas (cada 5-15 min)


class TimeRange(BaseModel):
    """
    Ventana temporal de análisis del Monitor (contrato A+C). Dos formas mutuamente
    excluyentes para acotar la serie:
      - `last_n_months`: int  → los últimos N registros mensuales (atajo cómodo).
      - `start` / `end`: date → rango explícito [start, end] inclusive (cualquier extremo opcional).
    Sin campos (todo None) ⇒ análisis GLOBAL sobre toda la serie. La aplica `window_metrics()`
    en tools/patient_tools.py; es el parámetro que el Agente Monitor (LLM) elige por consulta
    a partir de la consulta del médico y el doctor_context.
    """
    last_n_months: Optional[int] = None
    start: Optional[date] = None
    end: Optional[date] = None

    @model_validator(mode="after")
    def _validate_exclusivo(self) -> "TimeRange":
        if self.last_n_months is not None:
            if self.start is not None or self.end is not None:
                raise ValueError("TimeRange: usar last_n_months O (start/end), no ambos a la vez")
            if self.last_n_months < 1:
                raise ValueError("TimeRange: last_n_months debe ser >= 1")
        if self.start is not None and self.end is not None and self.start > self.end:
            raise ValueError("TimeRange: start no puede ser posterior a end")
        return self

    @property
    def is_global(self) -> bool:
        """True si no acota nada (análisis sobre toda la serie)."""
        return self.last_n_months is None and self.start is None and self.end is None


# -------------------------------------------------------------------
# Modelos de datos — medicación y estadísticas
# -------------------------------------------------------------------

class Medication(BaseModel):
    """Medicación activa del paciente (output de get_medication_schedule)."""
    name: str            # nombre del fármaco
    dose: str            # dosis (p. ej. "850mg")
    frequency: str       # frecuencia (p. ej. "cada 12h")


class MetricStats(BaseModel):
    """
    Estadísticas clínicamente accionables de una métrica (output de calculate_stats).

    Diseño (contrato A+C, ver "Flujo de métricas" en docs/CLAUDE.md): se prioriza lo que un
    médico realmente lee en un seguimiento de diabetes. Se quitaron `std` y la pendiente cruda
    (`trend`): la desviación estándar de mediciones puntuales aporta poco y la pendiente no es
    interpretable para el médico. En su lugar:
      - `last_value` + `direction` + `delta` → "cómo está hoy y hacia dónde va".
      - `min_value` / `max_value` → exponen EXTREMOS que la media esconde (p. ej. un episodio
        de hipoglucemia que el promedio diluiría).
    """
    last_value: float    # último valor registrado (lo más importante para el médico)
    mean: float          # media de la ventana (nivel promedio)
    min_value: float     # valor mínimo en la ventana (extremo bajo, p. ej. hipoglucemia)
    max_value: float     # valor máximo en la ventana (extremo alto, p. ej. pico glucémico)
    delta: float         # cambio neto en la ventana (último − primero)
    direction: str       # "subiendo" | "bajando" | "estable" (tendencia legible)


class BloodPressureStats(BaseModel):
    """Estadísticas de presión arterial (dos series: sistólica y diastólica). None = sin registros."""
    systolic: Optional[MetricStats] = None
    diastolic: Optional[MetricStats] = None


# -------------------------------------------------------------------
# Modelos de datos — análisis y alertas
# -------------------------------------------------------------------

class Alert(BaseModel):
    """Alerta generada por el Agente Monitor."""
    metric: str
    value: float
    severity: str        # "leve" | "moderada" | "severa"
    date: date           # fecha del registro donde se detectó el valor
    description: str


class MonitorAnalysis(BaseModel):
    """
    Output estructurado del Agente Monitor.

    Nunca se inventan valores (ADR-0003): una métrica sin registros tiene stats `None`, y las
    métricas con menos de 2 registros (sin tendencia evaluable) figuran en `insufficient_data`.
    """
    glucose_fasting_stats: Optional[MetricStats] = None
    hba1c_stats: Optional[MetricStats] = None
    glucose_postprandial_stats: Optional[MetricStats] = None
    weight_stats: Optional[MetricStats] = None
    blood_pressure_stats: BloodPressureStats
    cgm_metrics: Optional[CGMMetrics] = None  # None si el paciente no tiene CGM
    alerts: list[Alert]
    medication: list[Medication]
    requires_rag: bool                    # hay alertas moderadas o severas
    requires_longitudinal_comparison: bool  # hay métricas que ameritan comparar con sesiones anteriores
    insufficient_data: dict[str, str] = Field(default_factory=dict)  # métrica → motivo
    records_count: int = 0                # registros del EHR analizados (dentro de analysis_window)
    # Ventana principal del análisis (D7): stats, alertas e insufficient_data la usan toda.
    analysis_window: TimeRange = Field(default_factory=TimeRange)
    # Stats pedidas por el LLM con otra ventana, sin mezclarse con las principales ("metric@ventana").
    extra_windows: dict[str, MetricStats] = Field(default_factory=dict)


# -------------------------------------------------------------------
# Estado del grafo
# -------------------------------------------------------------------

class AgentState(TypedDict):

    # -- Identificación del paciente --
    patient_id: str
    active_patient_id: Optional[str]  # paciente del análisis en curso; lo escribe SOLO el Orquestador (D4)

    # -- Mensaje actual del médico --
    query: str            # consulta/pregunta actual (consumida por los templates)

    # -- Datos cargados desde EHR --
    metrics_history: Optional[PatientMetrics]
    medication: Optional[list[Medication]]

    # -- Historial acumulativo desde MongoDB --
    patient_history: Optional[dict]   # documento completo del paciente

    # -- Output del Agente Monitor --
    analysis: Optional[MonitorAnalysis]

    # -- Comparación longitudinal (Agente Clínico) --
    longitudinal_comparison: Optional[dict]

    # -- Contexto RAG recuperado por el Agente Clínico --
    rag_context: Optional[list[str]]

    # -- Reporte generado por el Agente Clínico --
    # has_report se deriva de (report is not None) al formatear el template del Orquestador
    report: Optional[str]           # reporte de la sesión: SOLO lo escribe el modo reporte (D3)
    followup_answer: Optional[str]  # respuesta del modo seguimiento; nunca pisa `report` (D3)

    # -- Control del grafo --
    iteration: int        # contador para el guardrail (máx 3)
    is_followup: bool     # True si es pregunta de seguimiento, False si es consulta nueva
    save_requested: bool  # señal EXPLÍCITA de guardado (botón o "confirmar"/"guardar sesión"); D5
    save_result: Optional[dict]  # {"ok": bool, "session_id"?: str, "error"?: str} del último guardado
    analysis_query: Optional[str]  # consulta que originó el análisis/reporte vigente (se persiste al guardar)
    information_sufficient: bool  # señal del Clínico: False → el Orquestador reenvía al Monitor (loop de refinamiento)
    error: Optional[str]  # error de dominio para el médico (p. ej. paciente sin datos); corta el flujo (ADR-0003)

    # -- Conversación médico ↔ sistema --
    conversation: Annotated[list[dict], operator.add]

    # -- Contexto clínico adicional ingresado por el médico --
    doctor_context: Optional[str]   # orientación o contexto libre del médico