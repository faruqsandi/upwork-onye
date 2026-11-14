"""Unit tests for Task 4: Semantic Vector Search and FastAPI Endpoints."""

import tempfile
import time
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from src.ai.models import ClinicalSummary
from src.api.app import app
from src.ingestion.models import (
    CanonicalDiagnosticReport,
    CanonicalDocument,
    CanonicalPatient,
    GenderEnum,
)
from src.search.models import SearchRequest
from src.search.vector_store import ClinicalVectorStore


@pytest.fixture
def populated_vector_store():
    """Initializes in-memory vector store with 50+ records to benchmark latency and quality."""
    with tempfile.TemporaryDirectory() as tmpdir:
        vstore = ClinicalVectorStore(persist_dir=Path(tmpdir) / "chroma_bench", in_memory=True)

        # Base clinical patients
        p1 = CanonicalPatient(
            patient_id="P-101",
            mrn="MRN:000101",
            first_name="Eleanor",
            last_name="Vance",
            birth_date="1964-08-12",
            gender=GenderEnum.FEMALE,
            documents=[
                CanonicalDocument(
                    doc_id="DOC-101-A",
                    title="Endocrine Clinic Note",
                    date="2023-11-04",
                    content="Patient Eleanor Vance (60 yo F) presents with bilateral foot numbness, tingling, and uncontrolled diabetes.",
                )
            ],
            diagnostics=[
                CanonicalDiagnosticReport(
                    report_id="DIAG-101-A",
                    test_name="Glycated Hemoglobin (HbA1c)",
                    loinc_code="4548-4",
                    effective_date="2023-11-04",
                    conclusion="HbA1c severely elevated at 10.4%. High risk for diabetic retinopathy and neuropathy.",
                )
            ],
        )
        s1 = ClinicalSummary(
            patient_id="P-101",
            chief_concern="Uncontrolled Type 2 Diabetes with peripheral neuropathy.",
            key_diagnoses=["Type 2 Diabetes Mellitus", "Neuropathy"],
            recent_media_and_labs=["HbA1c: 10.4%"],
            flagged_anomalies=["Critical HbA1c elevation"],
            full_summary_text="Uncontrolled diabetes with severe HbA1c elevation and neuropathy.",
            word_count=10,
        )

        p2 = CanonicalPatient(
            patient_id="P-102",
            mrn="MRN:000102",
            first_name="Marcus",
            last_name="Thorne",
            birth_date="1978-10-24",
            gender=GenderEnum.MALE,
            documents=[
                CanonicalDocument(
                    doc_id="DOC-102-A",
                    title="Emergency Department Note",
                    date="2024-01-15",
                    content="45-year-old male with acute substernal crushing chest pain radiating to left jaw, diaphoresis. ST elevations in leads V1-V4.",
                )
            ],
            diagnostics=[
                CanonicalDiagnosticReport(
                    report_id="DIAG-102-A",
                    test_name="Cardiac Troponin I",
                    loinc_code="10839-9",
                    effective_date="2024-01-15",
                    conclusion="Troponin I critically elevated at 14.80 ng/mL. Acute Anterior STEMI.",
                )
            ],
        )
        s2 = ClinicalSummary(
            patient_id="P-102",
            chief_concern="Acute STEMI with severe substernal chest pain.",
            key_diagnoses=["Acute Anterior STEMI"],
            recent_media_and_labs=["Cardiac Troponin I: 14.8 ng/mL"],
            flagged_anomalies=["Critically elevated troponin"],
            full_summary_text="Acute STEMI confirmed by critical troponin elevation.",
            word_count=8,
        )

        # Index primary patients
        vstore.index_patient(p1, s1)
        vstore.index_patient(p2, s2)

        # Populate up to 50+ records for benchmark requirements
        for i in range(25):
            synth_p = CanonicalPatient(
                patient_id=f"P-SYNTH-{i}",
                mrn=f"MRN:99{i:04d}",
                first_name=f"SyntheticPatient{i}",
                last_name="Cohort",
                birth_date="1980-01-01",
                gender=GenderEnum.UNKNOWN,
                documents=[
                    CanonicalDocument(
                        doc_id=f"DOC-SYNTH-{i}",
                        title="Routine Physical Examination",
                        date=f"2023-{(i%12)+1:02d}-15",
                        content=f"Synthetic patient evaluation #{i}. Vitals stable. No acute distress.",
                    )
                ],
                diagnostics=[
                    CanonicalDiagnosticReport(
                        report_id=f"DIAG-SYNTH-{i}",
                        test_name="Basic Metabolic Panel",
                        loinc_code="24323-8",
                        effective_date=f"2023-{(i%12)+1:02d}-15",
                        conclusion=f"Electrolytes within normal limits for cohort #{i}.",
                    )
                ],
            )
            synth_s = ClinicalSummary(
                patient_id=f"P-SYNTH-{i}",
                chief_concern="Routine preventive screening.",
                key_diagnoses=["Routine health maintenance"],
                recent_media_and_labs=["BMP normal"],
                flagged_anomalies=["None"],
                full_summary_text="Routine clinical observation.",
                word_count=4,
            )
            vstore.index_patient(synth_p, synth_s)

        yield vstore


class TestSemanticSearchEngine:
    def test_search_latency_sub_2_seconds_for_50_records(self, populated_vector_store):
        """Verify performance SLA: sub-2 second query execution across 50+ records."""
        total_records = populated_vector_store.count()
        assert total_records >= 50, f"Expected at least 50 records for benchmark, got {total_records}"

        req = SearchRequest(query="elevated HbA1c diabetic retinopathy", top_k=5)

        t0 = time.perf_counter()
        response = populated_vector_store.search(req)
        elapsed_sec = time.perf_counter() - t0

        # Sub-2 second assertion
        assert elapsed_sec < 2.0, f"Search took {elapsed_sec:.3f}s (exceeded 2.0s SLA)"
        assert response.execution_time_ms < 2000.0
        assert len(response.results) == 5

    def test_semantic_query_ranking(self, populated_vector_store):
        """Verify top ranked result aligns with clinical concept query."""
        # Query for diabetes
        res_diabetes = populated_vector_store.search(
            SearchRequest(query="patients with uncontrolled blood sugar or foot numbness", top_k=3)
        )
        assert res_diabetes.results[0].patient_id == "P-101"
        assert res_diabetes.results[0].relevance_score > 0.6

        # Query for cardiac
        res_cardiac = populated_vector_store.search(
            SearchRequest(query="acute myocardial infarction ST elevation chest pain", top_k=3)
        )
        assert res_cardiac.results[0].patient_id == "P-102"
        assert res_cardiac.results[0].relevance_score > 0.6

    def test_resource_type_filter(self, populated_vector_store):
        """Verify filtering by FHIR resource type."""
        res = populated_vector_store.search(
            SearchRequest(
                query="blood sugar and troponin tests",
                resource_type="DiagnosticReport",
                top_k=5,
            )
        )
        for item in res.results:
            assert item.resource_type == "DiagnosticReport"

    def test_date_range_filter(self, populated_vector_store):
        """Verify filtering by record date range."""
        res_2024 = populated_vector_store.search(
            SearchRequest(
                query="chest pain or emergency note",
                date_from="2024-01-01",
                date_to="2024-12-31",
                top_k=5,
            )
        )
        assert len(res_2024.results) > 0
        for item in res_2024.results:
            assert item.record_date.startswith("2024")


class TestFastAPISearchEndpoint:
    @pytest.fixture
    def client(self):
        return TestClient(app)

    def test_post_search_api_endpoint(self, client):
        """Verify POST /search endpoint returns top-5 matches with execution time."""
        payload = {
            "query": "uncontrolled diabetes and elevated HbA1c",
            "top_k": 5,
        }
        resp = client.post("/search", json=payload)
        assert resp.status_code == 200
        data = resp.json()

        assert "results" in data
        assert "execution_time_ms" in data
        assert data["execution_time_ms"] < 2000.0
        assert len(data["results"]) <= 5
        assert data["total_matches"] > 0
        top_match = data["results"][0]
        assert "patient_id" in top_match
        assert "relevance_score" in top_match
        assert 0.0 <= top_match["relevance_score"] <= 1.0

    def test_health_endpoint(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "healthy"

