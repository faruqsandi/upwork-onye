"""FastAPI routing endpoints for semantic search, FHIR bundles, and clinical intelligence."""

import base64
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status
from fastapi.responses import JSONResponse, Response

from src.ai.summarizer import ClinicalSummarizer
from src.fhir.bundle import BundleGenerator
from src.fhir.storage import FHIRSQLiteStorage
from src.ingestion.models import (
    CanonicalDiagnosticReport,
    CanonicalDocument,
    CanonicalPatient,
    GenderEnum,
)
from src.ingestion.parsers import IngestionPipeline
from src.queue.manager import QueueManager
from src.queue.worker import get_queue_worker
from src.search.models import SearchRequest, SearchResponse
from src.search.vector_store import ClinicalVectorStore
from .schemas import IngestionStatusResponse, PatientDetailResponse, PatientListItem

logger = logging.getLogger(__name__)

router = APIRouter()

# Shared services
storage = FHIRSQLiteStorage()
summarizer = ClinicalSummarizer()
vector_store = ClinicalVectorStore()
pipeline = IngestionPipeline()
queue_mgr = QueueManager()

# Cache of in-memory parsed canonical patients for quick lookup
canonical_cache: dict[str, Any] = {}
get_queue_worker().set_canonical_cache(canonical_cache)


def get_default_data_dir() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "data" / "raw"


def extract_numeric_id(val: Optional[str]) -> Optional[str]:
    if not val:
        return None
    match = re.search(r"(\d+)", str(val))
    return match.group(1).lstrip("0") or "0" if match else None


def reconstruct_patient_from_fhir_bundle(bundle_json_str: str) -> Optional[CanonicalPatient]:
    """Reconstructs a CanonicalPatient object from an HL7 FHIR R4 Bundle JSON stored in SQLite."""
    try:
        b = json.loads(bundle_json_str) if isinstance(bundle_json_str, str) else bundle_json_str
        patient_res = None
        docs: List[CanonicalDocument] = []
        diags: List[CanonicalDiagnosticReport] = []

        for entry in b.get("entry", []):
            res = entry.get("resource", {})
            rtype = res.get("resourceType")
            if rtype == "Patient":
                patient_res = res
            elif rtype == "DocumentReference":
                title = res.get("description")
                if not title:
                    cats = res.get("category", [{}])
                    if cats and "coding" in cats[0]:
                        title = cats[0]["coding"][0].get("display", "Clinical Note")
                    else:
                        title = "Clinical Note"
                date = res.get("date", "2024-01-01")
                content = ""
                for c in res.get("content", []):
                    att = c.get("attachment", {})
                    if att.get("data"):
                        try:
                            content = base64.b64decode(att["data"]).decode("utf-8", errors="replace")
                        except Exception:
                            pass
                docs.append(
                    CanonicalDocument(
                        doc_id=res.get("id", "DOC"),
                        title=title or "Clinical Note",
                        date=date,
                        content=content,
                    )
                )
            elif rtype == "DiagnosticReport":
                code_obj = res.get("code", {})
                codings = code_obj.get("coding", [{}])
                loinc = codings[0].get("code", "2888-6") if codings else "2888-6"
                test_name = codings[0].get("display") or code_obj.get("text") or "Diagnostic Test"
                date = res.get("effectiveDateTime", "2024-01-01")
                conclusion = res.get("conclusion", "")
                diags.append(
                    CanonicalDiagnosticReport(
                        report_id=res.get("id", "DIAG"),
                        test_name=test_name,
                        loinc_code=loinc,
                        effective_date=date,
                        conclusion=conclusion,
                    )
                )

        if not patient_res:
            return None

        name_obj = patient_res.get("name", [{}])[0]
        first = " ".join(name_obj.get("given", ["Unknown"]))
        last = name_obj.get("family", "Unknown")
        mrn = ""
        for id_obj in patient_res.get("identifier", []):
            if "mrn" in id_obj.get("system", "").lower() or id_obj.get("value", "").startswith("MRN:"):
                mrn = id_obj.get("value")
                break

        g_val = patient_res.get("gender", "unknown").lower()
        gender = (
            GenderEnum.MALE
            if g_val == "male"
            else (
                GenderEnum.FEMALE
                if g_val == "female"
                else (GenderEnum.OTHER if g_val == "other" else GenderEnum.UNKNOWN)
            )
        )
        pid = patient_res.get("id", "P-UNKNOWN")

        return CanonicalPatient(
            patient_id=pid,
            mrn=mrn or f"MRN:{pid.replace('P-', '')}",
            first_name=first,
            last_name=last,
            birth_date=patient_res.get("birthDate", "1980-01-01"),
            gender=gender,
            documents=docs,
            diagnostics=diags,
        )
    except Exception as e:
        logger.exception("Error reconstructing patient from FHIR bundle: %s", e)
        return None


def ensure_canonical_cache() -> None:
    """Populates the in-memory canonical patient cache from data/raw and data/unprocessed without heavy batch summarization."""
    if not canonical_cache:
        dirs_to_check = [
            Path(__file__).resolve().parent.parent.parent / "data" / "raw",
            Path(__file__).resolve().parent.parent.parent / "data" / "unprocessed",
        ]
        for d in dirs_to_check:
            if d.exists():
                try:
                    patients, _ = pipeline.ingest_directory_with_stats(d)
                    for p in patients:
                        canonical_cache[p.patient_id] = p
                except Exception as e:
                    logger.warning("Error ingesting directory %s into cache: %s", d, e)


def find_patient_in_cache_or_storage(patient_id: str) -> Optional[CanonicalPatient]:
    """Finds a patient by ID, MRN, normalized zero-padded/unpadded ID, or reconstructs from stored FHIR bundle."""
    if not canonical_cache:
        ensure_canonical_cache()

    clean_id = patient_id.strip()
    clean_id_upper = clean_id.upper()
    target_digits = extract_numeric_id(clean_id)

    # 1. Exact match in canonical_cache
    if clean_id in canonical_cache:
        return canonical_cache[clean_id]
    if clean_id_upper in canonical_cache:
        return canonical_cache[clean_id_upper]

    # 2. Iterate canonical_cache by ID, MRN, or numeric digits
    for p in list(canonical_cache.values()):
        if not isinstance(p, CanonicalPatient):
            continue
        if p.patient_id == clean_id or p.patient_id.upper() == clean_id_upper:
            canonical_cache[clean_id] = p
            return p
        if p.mrn == clean_id or p.mrn.upper() == clean_id_upper:
            canonical_cache[clean_id] = p
            return p
        if target_digits:
            p_digits = extract_numeric_id(p.patient_id)
            mrn_digits = extract_numeric_id(p.mrn)
            if target_digits == p_digits or target_digits == mrn_digits:
                canonical_cache[clean_id] = p
                return p

    # 3. Check SQLite fhir_bundles table
    bundle_json = storage.get_bundle_json(clean_id)
    if not bundle_json:
        bundle = storage.get_bundle_by_mrn(clean_id)
        if bundle:
            bundle_json = bundle.model_dump_json() if hasattr(bundle, "model_dump_json") else bundle.json()

    if not bundle_json and target_digits:
        try:
            with storage._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT patient_id, mrn, bundle_json FROM fhir_bundles;")
                for row in cursor.fetchall():
                    r_pid_digits = extract_numeric_id(row["patient_id"])
                    r_mrn_digits = extract_numeric_id(row["mrn"])
                    if target_digits == r_pid_digits or target_digits == r_mrn_digits:
                        bundle_json = row["bundle_json"]
                        break
        except Exception as e:
            logger.warning("Error searching fhir_bundles by digits: %s", e)

    if bundle_json:
        patient = reconstruct_patient_from_fhir_bundle(bundle_json)
        if patient:
            canonical_cache[patient.patient_id] = patient
            canonical_cache[clean_id] = patient
            return patient

    return None


def find_bundle_json(patient_id: str) -> Optional[str]:
    """Finds raw FHIR bundle JSON by ID, MRN, or normalized zero-padded/unpadded ID."""
    clean_id = patient_id.strip()
    # 1. Exact match by patient_id
    bundle_json = storage.get_bundle_json(clean_id)
    if bundle_json:
        return bundle_json

    # 2. Exact match by MRN
    bundle = storage.get_bundle_by_mrn(clean_id)
    if bundle:
        return bundle.model_dump_json() if hasattr(bundle, "model_dump_json") else bundle.json()

    # 3. Search SQLite by digits
    target_digits = extract_numeric_id(clean_id)
    if target_digits:
        try:
            with storage._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT patient_id, mrn, bundle_json FROM fhir_bundles;")
                for row in cursor.fetchall():
                    r_pid_digits = extract_numeric_id(row["patient_id"])
                    r_mrn_digits = extract_numeric_id(row["mrn"])
                    if target_digits == r_pid_digits or target_digits == r_mrn_digits:
                        return row["bundle_json"]
        except Exception as e:
            logger.warning("Error searching fhir_bundles by digits: %s", e)

    # 4. Generate bundle from cached/storage patient if not yet in SQLite
    patient = find_patient_in_cache_or_storage(clean_id)
    if patient:
        new_bundle, report = BundleGenerator.create_patient_bundle(patient)
        storage.save_bundle(patient.patient_id, patient.mrn, new_bundle, report)
        return new_bundle.model_dump_json() if hasattr(new_bundle, "model_dump_json") else new_bundle.json()

    return None


@router.post("/search", response_model=SearchResponse, summary="Semantic Natural Language Search")
def semantic_search(request: SearchRequest) -> SearchResponse:
    """Executes natural language semantic search across clinical records, diagnostic labs,
    and AI summaries with sub-2s latency and optional metadata filtering.

    Immediately searches whatever records are currently indexed in ChromaDB without blocking.
    """
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty.")

    return vector_store.search(request)


@router.get("/patients", response_model=List[PatientListItem], summary="List Ingested Patients")
def list_patients() -> List[PatientListItem]:
    """Returns a list of all normalized patients with demographic badges and summary snippets."""
    if len(canonical_cache) < 10:
        ensure_canonical_cache()

    unique_patients: Dict[str, CanonicalPatient] = {}
    for p in canonical_cache.values():
        if isinstance(p, CanonicalPatient):
            unique_patients[p.patient_id] = p

    items: List[PatientListItem] = []
    for p in unique_patients.values():
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
    patient = find_patient_in_cache_or_storage(patient_id)
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
    bundle_json = find_bundle_json(patient_id)
    if not bundle_json:
        raise HTTPException(status_code=404, detail=f"FHIR Bundle for '{patient_id}' not found.")

    return Response(content=bundle_json, media_type="application/json")


@router.get("/queue/status", response_model=IngestionStatusResponse, summary="Get Ingestion Queue Telemetry")
@router.get("/ingest/status", response_model=IngestionStatusResponse, summary="Get Ingestion Queue Telemetry (Alias)")
def get_queue_telemetry() -> IngestionStatusResponse:
    """Returns real-time telemetry counters for the background ingestion queue."""
    stats = queue_mgr.get_stats()
    return IngestionStatusResponse(
        status="success",
        total_ingested=stats.total,
        successful=stats.successful,
        failed=stats.failed,
        skipped_duplicates=stats.skipped_duplicates,
        patients_processed=stats.successful,
        bundles_stored=stats.successful,
        vectors_indexed=stats.successful,
        message=stats.message,
        unprocessed=stats.unprocessed,
        in_processing=stats.in_processing,
        is_active=stats.is_active,
        progress_percent=stats.progress_percent,
        current_file=stats.current_file,
        batch_total=stats.batch_total,
        batch_done=stats.batch_done,
        batch_remaining=stats.batch_remaining,
    )


@router.post("/ingest", response_model=IngestionStatusResponse, summary="Trigger Data Ingestion Pipeline")
def run_ingestion(sync: bool = False) -> IngestionStatusResponse:
    """Enqueues all raw directory files into the SQLite queue for asynchronous background processing.
    When running under a synchronous test harness without a live event loop, drains synchronously.
    """
    data_dir = get_default_data_dir()
    queue_mgr.enqueue_directory(data_dir)

    worker = get_queue_worker()
    worker.start()
    worker.notify()

    # If sync requested or worker loop isn't running asynchronously (e.g. TestClient test)
    if sync or not worker.should_run or worker._task is None:
        worker.drain_all_sync()

    stats = queue_mgr.get_stats()
    return IngestionStatusResponse(
        status="success",
        total_ingested=stats.total,
        successful=stats.successful,
        failed=stats.failed,
        skipped_duplicates=stats.skipped_duplicates,
        patients_processed=stats.successful,
        bundles_stored=stats.successful,
        vectors_indexed=stats.successful,
        message=stats.message,
        unprocessed=stats.unprocessed,
        in_processing=stats.in_processing,
        is_active=stats.is_active,
        progress_percent=stats.progress_percent,
        current_file=stats.current_file,
        batch_total=stats.batch_total,
        batch_done=stats.batch_done,
        batch_remaining=stats.batch_remaining,
    )


@router.post("/upload", response_model=IngestionStatusResponse, summary="Upload & Ingest Clinical Record Files")
async def upload_and_ingest(
    files: List[UploadFile] = File(...),
    sync: bool = False,
) -> IngestionStatusResponse:
    """Accepts uploaded individual EHR files (.json, .csv, .txt), enqueues them into the SQLite queue,
    and signals the background worker to process them one-by-one.
    """
    data_dir = get_default_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)

    batch_id = queue_mgr.create_batch_id(prefix="upload")
    saved_count = 0
    upload_errors: List[str] = []
    for file in files:
        if not file.filename:
            continue
        safe_filename = Path(file.filename).name
        dest = data_dir / safe_filename
        try:
            content = await file.read()
            with open(dest, "wb") as f:
                f.write(content)
            queue_mgr.enqueue_upload(safe_filename, content, batch_id=batch_id)
            saved_count += 1
        except Exception as e:
            upload_errors.append(f"{safe_filename}: {str(e)}")

    worker = get_queue_worker()
    worker.start()
    worker.notify()

    if sync or not worker.should_run or worker._task is None:
        worker.drain_all_sync()

    stats = queue_mgr.get_stats()
    failures = upload_errors.copy()
    return IngestionStatusResponse(
        status="success",
        total_ingested=stats.total,
        successful=stats.successful,
        failed=stats.failed + len(upload_errors),
        skipped_duplicates=stats.skipped_duplicates,
        patients_processed=stats.successful,
        bundles_stored=stats.successful,
        vectors_indexed=stats.successful,
        files_uploaded=saved_count,
        failures=failures,
        message=stats.message if stats.is_active else f"Uploaded {saved_count} file(s) into queue. {stats.message}",
        unprocessed=stats.unprocessed,
        in_processing=stats.in_processing,
        is_active=stats.is_active,
        progress_percent=stats.progress_percent,
        current_file=stats.current_file,
        batch_total=stats.batch_total,
        batch_done=stats.batch_done,
        batch_remaining=stats.batch_remaining,
    )


@router.post("/clear", response_model=IngestionStatusResponse, summary="Clear All Stored and Indexed Clinical Data")
def clear_all_data() -> IngestionStatusResponse:
    """Purges all stored FHIR bundles, AI summaries, vector embeddings, and queue state,
    returning the system to an empty initial state.
    """
    storage.clear()
    summarizer.cache.clear()
    queue_mgr.clear()
    vector_store.clear()
    canonical_cache.clear()

    return IngestionStatusResponse(
        status="success",
        total_ingested=0,
        successful=0,
        failed=0,
        skipped_duplicates=0,
        patients_processed=0,
        bundles_stored=0,
        vectors_indexed=0,
        message="All patient records, FHIR bundles, summaries, vector embeddings, and queue items cleared.",
        unprocessed=0,
        in_processing=0,
        is_active=False,
        progress_percent=0.0,
        current_file=None,
    )


@router.get("/health", summary="Health Check")
def health_check():
    return {
        "status": "healthy",
        "bundles_stored": storage.count_bundles(),
        "vectors_indexed": vector_store.count(),
        "queue_stats": queue_mgr.get_stats().model_dump(),
        "environment": "production",
    }
