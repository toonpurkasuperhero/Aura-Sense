"""Pydantic models: telemetry from the edge, machine profiles, cases, and the
structured outputs each Gemma agent must return (used as Ollama JSON schemas)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- telemetry
class AxisRMS(BaseModel):
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


class FFTPeak(BaseModel):
    hz: float
    amp: float


class Vibration(BaseModel):
    rms_g: AxisRMS = AxisRMS()
    peak_g: float = 0.0
    crest: float = 0.0
    kurtosis: Optional[float] = None
    fft_peaks: list[FFTPeak] = []
    baseline_rms: Optional[float] = None  # learned on-device (combined RMS)
    zscore: Optional[float] = None


class Telemetry(BaseModel):
    node_id: str
    ts: Optional[datetime] = None
    status: Literal["LEARNING", "OK", "WARN", "ALERT"] = "OK"
    reason: Optional[str] = None  # why the edge raised WARN/ALERT
    vib: Vibration = Vibration()
    temp_c: Optional[float] = None
    temp_baseline_c: Optional[float] = None
    sound_level: Optional[float] = None
    sound_baseline: Optional[float] = None
    current_a: Optional[float] = None
    current_baseline_a: Optional[float] = None
    humidity_pct: Optional[float] = None    # DHT11 relative humidity
    humidity_raw: Optional[float] = None    # optional analog humidity / moisture module (raw ADC)
    moisture_pct: Optional[float] = None    # moisture module mapped to 0-100 % (uncalibrated)
    flame: Optional[bool] = None            # IR flame sensor digital output
    flame_level: Optional[float] = None     # IR intensity index 0-100 from the flame sensor AO
    sound_event: Optional[bool] = None      # sound module DO tripped (loud bang/squeal)
    rpm_hint: Optional[float] = None
    fw: Optional[str] = None
    buffered: bool = False  # true if replayed from the offline buffer


# ---------------------------------------------------------------- machines
class MachineProfile(BaseModel):
    node_id: str
    name: str
    machine_type: Literal["motor", "fan", "pump", "compressor", "gearbox", "other"] = "motor"
    location: str = ""
    rated_rpm: Optional[float] = None
    power_kw: Optional[float] = None
    line_hz: float = 50.0
    criticality: Literal["low", "medium", "high"] = "medium"
    downtime_cost_per_hour_inr: Optional[float] = None
    manuals: list[str] = []  # manual file names relevant to this machine
    notes: str = ""
    baseline_image: Optional[str] = None  # relative path in uploads
    baseline_audio: Optional[str] = None


# ---------------------------------------------------------------- agent outputs
class IntakeReport(BaseModel):
    transcript: str = Field(description="Verbatim transcript of the technician's voice note")
    language: str = Field(description="Language spoken, e.g. English, Hindi, Kannada")
    english_translation: str = Field(description="English translation (same as transcript if already English)")
    symptoms: list[str] = Field(description="Concrete symptoms mentioned, in English")


class FaultCandidate(BaseModel):
    fault: str
    likelihood: float = Field(ge=0, le=1)
    reasons: list[str]


class SignalReport(BaseModel):
    key_observations: list[str] = Field(description="Most important facts from the telemetry, with numbers")
    candidates: list[FaultCandidate] = Field(description="Top 3 candidate faults, most likely first")
    trend: str = Field(description="Is the condition stable, slowly degrading or rapidly degrading, and why")
    inspection_requests: list[str] = Field(description="What photos/sounds the technician should capture to confirm")


class ModalityVote(BaseModel):
    modality: Literal["telemetry", "image", "audio", "voice_note", "baseline", "manual", "history"]
    stance: Literal["supports", "contradicts", "neutral", "not_provided"]
    note: str


class Differential(BaseModel):
    fault: str
    why_less_likely: str


class Part(BaseModel):
    part: str
    qty: int = 1
    note: str = ""


class ManualRef(BaseModel):
    doc: str
    page: int
    section: str = ""
    quote: str = Field(default="", description="Short exact phrase from the excerpt that supports the step")


class Diagnosis(BaseModel):
    fault: str = Field(description="Most likely root-cause fault, e.g. 'Rotor imbalance'")
    component: str = Field(description="Where exactly, e.g. 'Drive-end bearing', 'Fan hub'")
    fault_category: Literal["mechanical", "electrical", "thermal", "lubrication", "fluid", "structural", "none", "unknown"]
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    confidence: float = Field(ge=0, le=1)
    time_to_failure: Literal["hours", "days", "weeks", "months", "not_applicable"]
    evidence_telemetry: str
    evidence_image: str
    evidence_audio: str
    evidence_baseline: str
    roi_findings: str = Field(default="", description="Findings inside the technician-marked region, if any")
    cross_modal_reasoning: str = Field(description="How the modalities agree or conflict, and how the conflict was resolved")
    modality_votes: list[ModalityVote]
    differential: list[Differential]
    immediate_action: str
    repair_steps: list[str]
    parts_needed: list[Part]
    manual_refs: list[ManualRef]


class SafetyAudit(BaseModel):
    verdict: Literal["APPROVE", "REVISE"]
    issues: list[str] = Field(description="Concrete problems with the diagnosis or repair steps (empty if none)")
    added_safety_steps: list[str] = Field(description="Safety steps to insert before repair, e.g. LOTO, verify zero energy")
    ppe: list[str]
    loto_required: bool
    can_run_until_repair: bool = Field(description="Is it safe to keep the machine running until the repair?")
    hazard_notes: str


class WorkOrderPart(BaseModel):
    part: str
    qty: int = 1
    est_cost_inr: float = 0


class WorkOrder(BaseModel):
    title: str
    priority: Literal["P1-Immediate", "P2-24h", "P3-This week", "P4-Planned"]
    est_downtime_hours: float
    skills_needed: list[str]
    tasks: list[str]
    parts: list[WorkOrderPart]
    est_total_cost_inr: float
    service_centre_id: str = Field(description="id of the chosen repair centre from the list, or 'in_house'")
    service_centre_reason: str
    vendor_message: str = Field(description="Short WhatsApp message to the repair centre, ready to send")


class FiveWhy(BaseModel):
    why: str
    answer: str


class CaseReport(BaseModel):
    shift_log_entry: str
    five_whys: list[FiveWhy]
    root_cause_statement: str
    preventive_actions: list[str]
    operator_message_en: str = Field(description="2-3 simple sentences for a machine operator")
    operator_message_local: str = Field(description="Same operator message in the requested local language")


class RegionAnswer(BaseModel):
    region_description: str
    defects_found: list[str]
    severity: Literal["NONE", "LOW", "MEDIUM", "HIGH", "CRITICAL"]
    answer: str
    recommended_check: str


# ---------------------------------------------------------------- cases
CaseStatus = Literal["ALERT", "INVESTIGATING", "DIAGNOSING", "DIAGNOSED", "APPROVED", "RESOLVED", "ERROR"]


class TraceEvent(BaseModel):
    ts: datetime = Field(default_factory=utcnow)
    agent: str
    kind: Literal["start", "message", "tool", "critique", "revision", "output", "error", "done", "info"]
    content: str
    data: Optional[dict] = None
    duration_s: Optional[float] = None


class Evidence(BaseModel):
    images: list[str] = []          # relative upload paths
    audio: Optional[str] = None     # machine sound
    voice_note: Optional[str] = None
    roi: Optional[list[float]] = None  # [x0,y0,x1,y1] fractions on images[0]
    roi_question: str = ""
    notes: str = ""
    language: str = "English"


class Feedback(BaseModel):
    correct: bool
    actual_cause: str = ""
    notes: str = ""
    downtime_avoided_hours: float = 0


class Case(BaseModel):
    id: str
    node_id: str
    status: CaseStatus = "ALERT"
    opened_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    trigger: Optional[dict] = None   # telemetry snapshot that opened the case
    trigger_reason: str = ""
    evidence: Evidence = Evidence()
    intake: Optional[dict] = None
    signal_report: Optional[dict] = None
    acoustic: Optional[dict] = None
    manual_hits: list[dict] = []
    diagnosis: Optional[dict] = None
    first_diagnosis: Optional[dict] = None
    audit: Optional[dict] = None
    work_order: Optional[dict] = None
    report: Optional[dict] = None
    health_score: Optional[int] = None
    rul: Optional[dict] = None
    trace: list[TraceEvent] = []
    feedback: Optional[Feedback] = None
    approved_by: Optional[str] = None
    notifications: list[dict] = []
    error: Optional[str] = None
