"""Unit tests for Task 2: FHIR R4 Normalization, Validation, and Storage."""

import tempfile
from pathlib import Path
import pytest
from fhir.resources.bundle import Bundle, BundleEntry
from fhir.resources.patient import Patient

from src.fhir.bundle import BundleGenerator
from src.fhir.mapper import FHIRMapper
from src.fhir.storage import FHIRSQLiteStorage
from src.fhir.validator import FHIRValidator
from src.ingestion.models import (
    CanonicalDiagnosticReport,
    CanonicalDocument,
    CanonicalEncounter,
    CanonicalPatient,
    EncounterClassEnum,
    GenderEnum,
)


@pytest.fixture
def sample_canonical_patient() -> CanonicalPatient:
    return CanonicalPatient(
        patient_id="P-101",
        mrn="MRN:000101",
        first_name="Eleanor",
        last_name="Vance",
        birth_date="1964-08-12",
        gender=GenderEnum.FEMALE,
        encounters=[
            CanonicalEncounter(
                encounter_id="ENC-101-1",
                encounter_class=EncounterClassEnum.AMB,
                period_start="2023-11-04T09:30:00Z",
                reason="Diabetic follow-up",
            )
        ],
        documents=[
            CanonicalDocument(
                doc_id="DOC-101-A",
                title="Progress Note",
                type_code="34108-1",
                date="2023-11-04T10:15:00Z",
                content="Patient reports bilateral foot numbness and tingling.",
                encounter_id="ENC-101-1",
            )
        ],
        diagnostics=[
            CanonicalDiagnosticReport(
                report_id="DIAG-101-A",
                test_name="Glycated Hemoglobin (HbA1c)",
                loinc_code="4548-4",
                effective_date="2023-11-04T11:00:00Z",
                conclusion="HbA1c elevated at 10.4%",
                encounter_id="ENC-101-1",
            )
        ],
    )


class TestFHIRMappingAndValidation:
    def test_fhir_mapping_creates_valid_resources(self, sample_canonical_patient):
        """Verify individual resource types satisfy FHIR R4 schema and reference conventions."""
        resources = FHIRMapper.map_all_resources(sample_canonical_patient)
        assert len(resources) == 4

        # Extract resource by type
        by_type = {r.get_resource_type(): r for r in resources}
        assert "Patient" in by_type
        assert "Encounter" in by_type
        assert "DocumentReference" in by_type
        assert "DiagnosticReport" in by_type

        # Verify Patient
        p = by_type["Patient"]
        assert p.id == "P-101"
        assert p.gender == "female"
        assert str(p.birthDate) == "1964-08-12"
        assert p.identifier[0].value == "MRN:000101"

        # Verify Encounter
        e = by_type["Encounter"]
        assert e.id == "ENC-101-1"
        assert e.subject.reference == "Patient/P-101"

        # Verify DocumentReference references
        d = by_type["DocumentReference"]
        assert d.id == "DOC-101-A"
        assert d.subject.reference == "Patient/P-101"
        assert d.context[0].reference == "Encounter/ENC-101-1"

        # Verify DiagnosticReport references
        r = by_type["DiagnosticReport"]
        assert r.id == "DIAG-101-A"
        assert r.subject.reference == "Patient/P-101"
        assert r.encounter.reference == "Encounter/ENC-101-1"

    def test_bundle_generation_and_validation(self, sample_canonical_patient):
        """Verify Bundle generation and automated validation report."""
        bundle, report = BundleGenerator.create_patient_bundle(sample_canonical_patient)

        assert bundle.get_resource_type() == "Bundle"
        assert bundle.type == "collection"
        assert len(bundle.entry) == 4
        assert report.is_valid is True
        assert len(report.errors) == 0
        assert report.resource_counts["Patient"] == 1
        assert report.resource_counts["Encounter"] == 1
        assert report.resource_counts["DocumentReference"] == 1
        assert report.resource_counts["DiagnosticReport"] == 1

    def test_validator_detects_missing_patient(self):
        """Verify that FHIRValidator flags bundles missing a Patient resource."""
        empty_bundle = Bundle(id="bundle-bad", type="collection", entry=[])
        report = FHIRValidator.validate_bundle(empty_bundle, patient_id="P-TEST")
        assert report.is_valid is False
        assert any("no resource entries" in err.lower() for err in report.errors)


class TestFHIRSQLiteStorage:
    def test_save_and_retrieve_bundle(self, sample_canonical_patient):
        """Verify persistence and exact round-trip deserialization from SQLite."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_fhir.db"
            storage = FHIRSQLiteStorage(db_path=db_path)

            bundle, report = BundleGenerator.create_patient_bundle(sample_canonical_patient)
            storage.save_bundle(
                patient_id=sample_canonical_patient.patient_id,
                mrn=sample_canonical_patient.mrn,
                bundle=bundle,
                report=report,
            )

            # Retrieve by patient ID
            retrieved = storage.get_bundle(sample_canonical_patient.patient_id)
            assert retrieved is not None
            assert retrieved.id == bundle.id
            assert len(retrieved.entry) == len(bundle.entry)

            # Retrieve by MRN
            by_mrn = storage.get_bundle_by_mrn(sample_canonical_patient.mrn)
            assert by_mrn is not None
            assert by_mrn.id == bundle.id

            # List bundles
            bundle_list = storage.list_bundles()
            assert len(bundle_list) == 1
            assert bundle_list[0]["patient_id"] == "P-101"
            assert bundle_list[0]["validation_status"] == "VALID"
            assert storage.count_bundles() == 1
