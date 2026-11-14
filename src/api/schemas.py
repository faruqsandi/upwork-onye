"""API schemas for patient queries and ingestion status."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel
from src.ai.models import ClinicalSummary
from src.ingestion.models import AuditEntry


class PatientListItem(BaseModel):
    patient_id: str
    mrn: str
    name: str
    birth_date: str
    gender: str
    document_count: int
    diagnostic_count: int
    chief_concern: Optional[str] = None


class PatientDetailResponse(BaseModel):
    patient_id: str
    mrn: str
    name: str
    birth_date: str
    gender: str
    summary: ClinicalSummary
    documents: List[Dict[str, Any]]
    diagnostics: List[Dict[str, Any]]
    audit_log: List[AuditEntry]


class IngestionStatusResponse(BaseModel):
    status: str
    total_ingested: int = 0
    successful: int = 0
    failed: int = 0
    skipped_duplicates: int = 0
    patients_processed: int = 0
    bundles_stored: int = 0
    vectors_indexed: int = 0
    files_uploaded: Optional[int] = None
    message: str
    failures: List[str] = []

