"""Unit tests for Task 3: AI-Powered Clinical Summarization and Caching."""

import tempfile
from pathlib import Path
import pytest
from src.ai.cache import SummaryCache
from src.ai.models import DEFAULT_DISCLAIMER
from src.ai.summarizer import ClinicalSummarizer, MockLLMClient
from src.fhir.bundle import BundleGenerator
from src.ingestion.models import (
    CanonicalDiagnosticReport,
    CanonicalDocument,
    CanonicalEncounter,
    CanonicalPatient,
    EncounterClassEnum,
    GenderEnum,
)


@pytest.fixture
def sample_patient() -> CanonicalPatient:
    return CanonicalPatient(
        patient_id="P-102",
        mrn="MRN:000102",
        first_name="Marcus",
        last_name="Thorne",
        birth_date="1978-10-24",
        gender=GenderEnum.MALE,
        encounters=[
            CanonicalEncounter(
                encounter_id="ENC-102-1",
                encounter_class=EncounterClassEnum.EMER,
                period_start="2024-01-15T03:45:00Z",
                reason="Crushing chest pain radiating to jaw",
            )
        ],
        documents=[
            CanonicalDocument(
                doc_id="DOC-102-A",
                title="ED Admission Note",
                date="2024-01-15T04:15:00Z",
                content="45 yo male with acute crushing chest pain, diaphoresis. ST elevations in V1-V4 consistent with STEMI.",
            )
        ],
        diagnostics=[
            CanonicalDiagnosticReport(
                report_id="DIAG-102-A",
                test_name="Cardiac Troponin I",
                loinc_code="10839-9",
                effective_date="2024-01-15T04:00:00Z",
                conclusion="Troponin I critically elevated at 14.80 ng/mL. Acute Myocardial Infarction.",
            )
        ],
    )


class TestClinicalSummarizer:
    def test_summary_structure_and_word_count_limit(self, sample_patient):
        """Verify summary contains all required clinical fields and is under 200 words."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = SummaryCache(db_path=Path(tmpdir) / "test_cache.db")
            summarizer = ClinicalSummarizer(cache=cache, llm_client=MockLLMClient())

            summary = summarizer.summarize_patient(sample_patient)

            # Assert word count limit
            assert summary.word_count < 200, f"Word count exceeded 200: {summary.word_count}"
            assert len(summary.full_summary_text.split()) < 200

            # Assert required sections
            assert summary.chief_concern != ""
            assert "stemi" in summary.chief_concern.lower() or "chest" in summary.chief_concern.lower()
            assert len(summary.key_diagnoses) > 0
            assert any("stemi" in d.lower() or "infarction" in d.lower() for d in summary.key_diagnoses)
            assert len(summary.recent_media_and_labs) > 0
            assert len(summary.flagged_anomalies) > 0
            assert any("troponin" in a.lower() for a in summary.flagged_anomalies)

            # Assert safety disclaimer and confidence
            assert summary.disclaimer == DEFAULT_DISCLAIMER
            assert 0.0 <= summary.confidence_score <= 1.0

    def test_deterministic_caching_behavior(self, sample_patient):
        """Verify cache hit on repeated call with identical record hash."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = SummaryCache(db_path=Path(tmpdir) / "test_cache.db")
            summarizer = ClinicalSummarizer(cache=cache, llm_client=MockLLMClient())

            # First run: cache miss
            summary1 = summarizer.summarize_patient(sample_patient)
            assert summary1.cached is False

            # Second run: cache hit
            summary2 = summarizer.summarize_patient(sample_patient)
            assert summary2.cached is True
            assert summary2.chief_concern == summary1.chief_concern
            assert summary2.full_summary_text == summary1.full_summary_text

    def test_cache_invalidation_on_data_change(self, sample_patient):
        """Verify that updating clinical record invalidates cache key."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = SummaryCache(db_path=Path(tmpdir) / "test_cache.db")
            summarizer = ClinicalSummarizer(cache=cache, llm_client=MockLLMClient())

            summary1 = summarizer.summarize_patient(sample_patient)

            # Add new diagnostic report
            sample_patient.diagnostics.append(
                CanonicalDiagnosticReport(
                    report_id="DIAG-NEW",
                    test_name="Echocardiogram",
                    loinc_code="10230-1",
                    effective_date="2024-01-16T10:00:00Z",
                    conclusion="Anterior wall hypokinesis. LVEF 40%.",
                )
            )

            # Second call should be a cache miss due to content hash difference
            summary2 = summarizer.summarize_patient(sample_patient)
            assert summary2.cached is False

    def test_summarize_from_fhir_bundle(self, sample_patient):
        """Verify that summarizer can synthesize directly from a FHIR R4 Bundle."""
        bundle, _ = BundleGenerator.create_patient_bundle(sample_patient)

        with tempfile.TemporaryDirectory() as tmpdir:
            cache = SummaryCache(db_path=Path(tmpdir) / "test_cache.db")
            summarizer = ClinicalSummarizer(cache=cache, llm_client=MockLLMClient())

            summary = summarizer.summarize_bundle(bundle, patient_id=sample_patient.patient_id)
            assert summary.patient_id == sample_patient.patient_id
            assert summary.word_count < 200
            assert len(summary.key_diagnoses) > 0
