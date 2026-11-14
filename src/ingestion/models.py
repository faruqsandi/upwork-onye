"""Canonical intermediate representation models for cleaned EHR records.

Follows Pydantic v2 conventions and includes per-record audit logging.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, List, Optional
from pydantic import BaseModel, Field


class GenderEnum(str, Enum):
    MALE = "male"
    FEMALE = "female"
    OTHER = "other"
    UNKNOWN = "unknown"


class EncounterClassEnum(str, Enum):
    AMB = "AMB"  # Ambulatory / Outpatient
    IMP = "IMP"  # Inpatient
    EMER = "EMER"  # Emergency
    VR = "VR"  # Virtual


class AuditEntry(BaseModel):
    """Tracks field-level data quality transformations."""

    field_name: str
    original_value: Any
    cleaned_value: Any
    transformation_rule: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CanonicalEncounter(BaseModel):
    encounter_id: str
    encounter_class: EncounterClassEnum = EncounterClassEnum.AMB
    period_start: str  # ISO-8601 string: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SSZ
    period_end: Optional[str] = None
    reason: Optional[str] = None


class CanonicalDocument(BaseModel):
    doc_id: str
    title: str
    type_code: str = "34108-1"  # Default LOINC outpatient note
    date: str  # ISO-8601 string
    content: str
    mime_type: str = "text/plain"
    encounter_id: Optional[str] = None


class CanonicalDiagnosticReport(BaseModel):
    report_id: str
    test_name: str
    loinc_code: str
    effective_date: str  # ISO-8601 string
    conclusion: str
    encounter_id: Optional[str] = None


class CanonicalPatient(BaseModel):
    """Canonical patient record with aggregated encounters, media, labs, and audit diffs."""

    patient_id: str
    mrn: str  # Format: MRN:XXXXXX
    first_name: str
    last_name: str
    birth_date: str  # Format: YYYY-MM-DD
    gender: GenderEnum
    encounters: List[CanonicalEncounter] = Field(default_factory=list)
    documents: List[CanonicalDocument] = Field(default_factory=list)
    diagnostics: List[CanonicalDiagnosticReport] = Field(default_factory=list)
    audit_log: List[AuditEntry] = Field(default_factory=list)

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


class IngestionStats(BaseModel):
    """Execution telemetry and data quality counters for the ingestion pipeline."""

    total_ingested: int = 0
    successful: int = 0
    failed: int = 0
    skipped_duplicates: int = 0
    failures: List[str] = Field(default_factory=list)


