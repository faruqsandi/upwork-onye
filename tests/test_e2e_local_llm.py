"""End-to-end integration test for the entire pipeline powered by the local LLM.

Exercises:
1. Synthetic EHR data generation with LLMSyntheticGenerator (LM Studio / llama-3.2-1b-instruct).
2. Heterogeneous data ingestion, cleaning, and per-record audit trail tracking.
3. HL7 FHIR R4 normalization and bundle validation.
4. AI-powered clinical summarization using the 'local' LLM provider with SHA-256 caching.
5. Semantic vector indexing and sub-second natural language search via FastAPI.
"""

import tempfile
import uuid
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from data.llm_synthetic_generator import LLMSyntheticGenerator
from src.ai.cache import SummaryCache
from src.ai.summarizer import ClinicalSummarizer, LocalLMStudioClient
from src.api.app import app
from src.fhir.bundle import BundleGenerator
from src.fhir.storage import FHIRSQLiteStorage
from src.ingestion.parsers import IngestionPipeline
from src.search.models import SearchRequest
from src.search.vector_store import ClinicalVectorStore


class TestEndToEndLocalLLMPipeline:
    def test_complete_e2e_pipeline_with_local_llm(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_path = Path(tmpdir)
            data_dir = temp_path / "raw_data"
            db_path = temp_path / "test_e2e.db"
            chroma_dir = temp_path / "test_chroma"

            # ---------------------------------------------------------
            # Step 1: Generate synthetic records on the fly using local LLM
            # ---------------------------------------------------------
            generator = LLMSyntheticGenerator()
            generator.verify_connection()

            cohort = generator.generate_cohort(count=3)
            assert len(cohort) == 3
            generator.export_all_formats(cohort, output_dir=data_dir)

            assert len(list(data_dir.glob("*.*"))) == 3

            # ---------------------------------------------------------
            # Step 2: Data Ingestion & Cleaning
            # ---------------------------------------------------------
            pipeline = IngestionPipeline()
            cleaned_patients = pipeline.ingest_directory(data_dir)
            assert len(cleaned_patients) >= 3

            for p in cleaned_patients:
                assert p.mrn.startswith("MRN:")
                assert "-" in p.birth_date
                assert len(p.encounters) >= 1
                # Verify that cleaning audit trail logged transformations
                assert isinstance(p.audit_log, list)

            # ---------------------------------------------------------
            # Step 3: FHIR R4 Normalization & Bundle Generation
            # ---------------------------------------------------------
            storage = FHIRSQLiteStorage(db_path=db_path)
            patient_1 = cleaned_patients[0]
            bundle, report = BundleGenerator.create_patient_bundle(patient_1)

            assert bundle.get_resource_type() == "Bundle"
            assert report.is_valid is True
            assert report.resource_counts["Patient"] == 1
            assert report.resource_counts["Encounter"] >= 1

            storage.save_bundle(patient_1.patient_id, patient_1.mrn, bundle, report)
            retrieved_bundle = storage.get_bundle(patient_1.patient_id)
            assert retrieved_bundle is not None
            assert retrieved_bundle.id == bundle.id

            # ---------------------------------------------------------
            # Step 4: AI Summarization with 'local' provider & Cache
            # ---------------------------------------------------------
            cache = SummaryCache(db_path=db_path)
            local_client = LocalLMStudioClient()
            summarizer = ClinicalSummarizer(cache=cache, llm_client=local_client)

            # Initial generation via local LLM
            summary = summarizer.summarize_patient(patient_1)
            assert summary.patient_id == patient_1.patient_id
            assert summary.word_count < 200
            assert summary.chief_concern != ""
            assert len(summary.key_diagnoses) > 0
            assert summary.cached is False

            # Repeated call -> Deterministic Cache Hit
            summary_cached = summarizer.summarize_patient(patient_1)
            assert summary_cached.cached is True
            assert summary_cached.full_summary_text == summary.full_summary_text

            # ---------------------------------------------------------
            # Step 5: Semantic Vector Indexing & Sub-Second Search
            # ---------------------------------------------------------
            vstore = ClinicalVectorStore(
                persist_dir=chroma_dir,
                in_memory=True,
                collection_name=f"test_e2e_{uuid.uuid4().hex[:8]}",
            )
            for p in cleaned_patients:
                s = summarizer.summarize_patient(p)
                vstore.index_patient(p, s)

            assert vstore.count() >= len(cleaned_patients)

            # Search query
            search_req = SearchRequest(query="acute patient emergency condition or lab abnormalities", top_k=3)
            search_res = vstore.search(search_req)

            assert search_res.total_matches > 0
            assert search_res.execution_time_ms < 2000.0  # SLA < 2.0s
            assert len(search_res.results) <= 3
            top_match = search_res.results[0]
            assert top_match.relevance_score >= 0.0

            # ---------------------------------------------------------
            # Step 6: FastAPI HTTP Endpoint Verification
            # ---------------------------------------------------------
            client = TestClient(app)

            # Health check
            h_resp = client.get("/health")
            assert h_resp.status_code == 200
            assert h_resp.json()["status"] == "healthy"

            # Search API
            api_search_resp = client.post("/search", json={"query": "elevated diagnostic findings", "top_k": 3})
            assert api_search_resp.status_code == 200
            assert "execution_time_ms" in api_search_resp.json()
            assert api_search_resp.json()["execution_time_ms"] < 2000.0

