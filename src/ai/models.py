"""Domain models for structured AI clinical summaries."""

from typing import List
from pydantic import BaseModel, Field

DEFAULT_DISCLAIMER = (
    "CLINICAL SAFETY DISCLAIMER: This summary is automatically synthesized by an AI assistant "
    "from available EHR records for clinical workflow support only. It does not constitute a "
    "definitive medical diagnosis and must not replace licensed professional clinical judgment."
)


class ClinicalSummary(BaseModel):
    """Clinician-grade structured summary of a patient's document and diagnostic history."""

    patient_id: str
    chief_concern: str
    key_diagnoses: List[str] = Field(default_factory=list)
    recent_media_and_labs: List[str] = Field(default_factory=list)
    flagged_anomalies: List[str] = Field(default_factory=list)
    full_summary_text: str
    word_count: int
    confidence_score: float = Field(default=0.95, ge=0.0, le=1.0)
    disclaimer: str = DEFAULT_DISCLAIMER
    cached: bool = False
