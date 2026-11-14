"""FastAPI routing endpoints for semantic search, FHIR bundles, and clinical intelligence."""

from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import JSONResponse, Response

from src.ai.summarizer import ClinicalSummarizer
from src.fhir.bundle import BundleGenerator
from src.fhir.storage import FHIRSQLiteStorage
from src.ingestion.parsers import IngestionPipeline
from src.search.models import SearchRequest, SearchResponse
from src.search.vector_store import ClinicalVectorStore
from .schemas import IngestionStatusResponse, PatientDetailResponse, PatientListItem

router = APIRouter()

# Shared services
storage = FHIRSQLiteStorage()
summarizer = ClinicalSummarizer()
vector_store = ClinicalVectorStore()
pipeline = IngestionPipeline()

# Cache of in-memory parsed canonical patients for quick lookup
canonical_cache: dict[str, Any] = {}


def get_default_data_dir() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "data" / "raw"


@router.post("/search", response_model=SearchResponse, summary="Semantic Natural Language Search")
def semantic_search(request: SearchRequest) -> SearchResponse:
    """Executes natural language semantic search across clinical records, diagnostic labs,

    and AI summaries with sub-2s latency and optional metadata filtering.
    """
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty.")

    # If vector store is empty, attempt initial ingest from raw data
    if vector_store.count() == 0:
        run_ingestion()

    return vector_store.search(request)


@router.get("/patients", response_model=List[PatientListItem], summary="List Ingested Patients")
def list_patients() -> List[PatientListItem]:
    """Returns a list of all normalized patients with demographic badges and summary snippets."""
    if not canonical_cache:
        run_ingestion()

    items: List[PatientListItem] = []
    for p in canonical_cache.values():
        summary = summarizer.summarize_patient(p)
        items.append(
            PatientListItem(
                patient_id=p.patient_id,
                mrn=p.mrn,
                name=p.full_name,
                birth_date=p.birth_date,
                gender=p.gender.value,
                document_count=len(p.documents),
                diagnostic_count=len(p.diagnostics),
                chief_concern=summary.chief_concern,
            )
        )
    return items


@router.get("/patients/{patient_id}", response_model=PatientDetailResponse, summary="Get Patient Details")
def get_patient_detail(patient_id: str) -> PatientDetailResponse:
    """Returns full patient details, synthesized AI summary, and the per-record cleaning audit trail."""
    if not canonical_cache:
        run_ingestion()

    patient = canonical_cache.get(patient_id)
    if not patient:
        # Fallback search by MRN
        for p in canonical_cache.values():
            if p.mrn == patient_id:
                patient = p
                break
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient '{patient_id}' not found.")

    summary = summarizer.summarize_patient(patient)
    return PatientDetailResponse(
        patient_id=patient.patient_id,
        mrn=patient.mrn,
        name=patient.full_name,
        birth_date=patient.birth_date,
        gender=patient.gender.value,
        summary=summary,
        documents=[d.model_dump() for d in patient.documents],
        diagnostics=[dg.model_dump() for dg in patient.diagnostics],
        audit_log=patient.audit_log,
    )


@router.get("/bundles/{patient_id}", summary="Get Raw FHIR R4 Bundle")
def get_fhir_bundle(patient_id: str):
    """Retrieves the official HL7 FHIR R4 Bundle JSON for the specified patient."""
    bundle_json = storage.get_bundle_json(patient_id)
    if not bundle_json:
        # Check by MRN
        bundle = storage.get_bundle_by_mrn(patient_id)
        if bundle:
            bundle_json = bundle.model_dump_json() if hasattr(bundle, "model_dump_json") else bundle.json()

    if not bundle_json:
        # If in canonical cache, generate on the fly
        patient = canonical_cache.get(patient_id)
        if patient:
            bundle, report = BundleGenerator.create_patient_bundle(patient)
            storage.save_bundle(patient.patient_id, patient.mrn, bundle, report)
            bundle_json = bundle.model_dump_json() if hasattr(bundle, "model_dump_json") else bundle.json()

    if not bundle_json:
        raise HTTPException(status_code=404, detail=f"FHIR Bundle for '{patient_id}' not found.")

    return Response(content=bundle_json, media_type="application/json")


@router.post("/ingest", response_model=IngestionStatusResponse, summary="Trigger Data Ingestion Pipeline")
def run_ingestion() -> IngestionStatusResponse:
    """Runs ingestion across raw JSON, CSV, and text EHR sources, normalizes to FHIR R4,

    persists to SQLite, generates AI summaries, and builds vector search index.
    """
    data_dir = get_default_data_dir()
    json_path = data_dir / "simulated_ehr_export.json"
    csv_path = data_dir / "scanned_notes.csv"
    txt_path = data_dir / "lab_results.txt"

    patients = pipeline.ingest_sources(
        json_path=json_path if json_path.exists() else None,
        csv_path=csv_path if csv_path.exists() else None,
        txt_path=txt_path if txt_path.exists() else None,
    )

    indexed_count = 0
    bundles_count = 0

    for p in patients:
        canonical_cache[p.patient_id] = p
        # 1. FHIR Normalization & Storage
        bundle, report = BundleGenerator.create_patient_bundle(p)
        storage.save_bundle(p.patient_id, p.mrn, bundle, report)
        bundles_count += 1

        # 2. AI Summarization & Vector Indexing
        summary = summarizer.summarize_patient(p)
        indexed_count += vector_store.index_patient(p, summary)

    return IngestionStatusResponse(
        status="success",
        patients_processed=len(patients),
        bundles_stored=bundles_count,
        vectors_indexed=indexed_count,
        message="EHR records successfully cleaned, mapped to FHIR R4, summarized, and indexed.",
    )


@router.get("/health", summary="Health Check")
def health_check():
    return {
        "status": "healthy",
        "bundles_stored": storage.count_bundles(),
        "vectors_indexed": vector_store.count(),
        "environment": "production",
    }
