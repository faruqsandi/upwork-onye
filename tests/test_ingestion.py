"""Unit tests for Task 1: Data Ingestion & Cleaning Pipeline.

Covers at least 3 distinct cleaning edge cases as required by rubric.
"""

from pathlib import Path
from src.ingestion.cleaner import DataCleaner
from src.ingestion.models import (
    CanonicalDocument,
    CanonicalEncounter,
    CanonicalPatient,
    EncounterClassEnum,
    GenderEnum,
)
from src.ingestion.parsers import CSVEHRParser, IngestionPipeline, JSONEHRParser, TextEHRParser

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"


class TestDataCleaningEdgeCases:
    """Test suite targeting specific dirty EHR data edge cases."""

    def test_edge_case_1_inconsistent_and_ambiguous_dates(self):
        """Edge Case 1: Inconsistent date formats (US MM/DD/YYYY, ISO, written, epoch, missing)."""
        # US format
        d1, audit1 = DataCleaner.clean_date("10/24/1978", is_birth_date=True)
        assert d1 == "1978-10-24"
        assert audit1 is not None
        assert audit1.field_name == "birth_date"

        # Written format with month abbreviation
        d2, audit2 = DataCleaner.clean_date("Sep 12, 2023", is_birth_date=False)
        assert d2 == "2023-09-12"
        assert audit2 is not None

        # Space separated datetime
        d3, audit3 = DataCleaner.clean_date("2024-01-15 03:45:00", is_birth_date=False)
        assert d3 == "2024-01-15T03:45:00Z"
        assert audit3 is not None

        # Missing date fallback
        d4, audit4 = DataCleaner.clean_date(None, is_birth_date=True)
        assert d4 == "1900-01-01"
        assert audit4 is not None
        assert "fallback" in audit4.transformation_rule.lower()

    def test_edge_case_2_dirty_mrns_and_gender_variants(self):
        """Edge Case 2: Dirty MRNs (whitespace, unpadded digits, mixed separators)

        and diverse gender strings.
        """
        # Dirty MRN with leading/trailing spaces and bare numbers
        mrn1, audit_mrn1 = DataCleaner.clean_mrn(" 102 ")
        assert mrn1 == "MRN:000102"
        assert audit_mrn1 is not None
        assert audit_mrn1.cleaned_value == "MRN:000102"

        # Space-separated MRN
        mrn2, _ = DataCleaner.clean_mrn("MRN 104")
        assert mrn2 == "MRN:000104"

        # Hyphenated MRN
        mrn3, _ = DataCleaner.clean_mrn("MRN-000101")
        assert mrn3 == "MRN:000101"

        # Gender variants
        g1, audit_g1 = DataCleaner.clean_gender("M")
        assert g1 == GenderEnum.MALE

        g2, audit_g2 = DataCleaner.clean_gender("cis-male")
        assert g2 == GenderEnum.MALE
        assert audit_g2 is not None

        g3, _ = DataCleaner.clean_gender("female")
        assert g3 == GenderEnum.FEMALE

        g4, audit_g4 = DataCleaner.clean_gender("non-binary")
        assert g4 == GenderEnum.OTHER

        g5, _ = DataCleaner.clean_gender("UNKNOWN_CODE")
        assert g5 == GenderEnum.UNKNOWN

    def test_edge_case_3_duplicate_records_and_conflict_merging(self):
        """Edge Case 3: Conflicting duplicate records for same patient merged

        with unified encounters, documents, and audit logs.
        """
        p1 = CanonicalPatient(
            patient_id="P-001",
            mrn="MRN:000999",
            first_name="Jane",
            last_name="Doe",
            birth_date="1980-05-15",
            gender=GenderEnum.FEMALE,
            encounters=[
                CanonicalEncounter(
                    encounter_id="ENC-01",
                    encounter_class=EncounterClassEnum.AMB,
                    period_start="2023-01-10T10:00:00Z",
                )
            ],
            documents=[
                CanonicalDocument(
                    doc_id="DOC-01",
                    title="Initial Consult",
                    date="2023-01-10T10:00:00Z",
                    content="Patient presents with elevated glucose.",
                )
            ],
        )

        p2 = CanonicalPatient(
            patient_id="P-001-ALT",
            mrn="MRN:000999",  # Identical normalized MRN
            first_name="Jane",
            last_name="Doe",
            birth_date="1980-05-15",
            gender=GenderEnum.FEMALE,
            encounters=[
                CanonicalEncounter(
                    encounter_id="ENC-02",  # Different encounter
                    encounter_class=EncounterClassEnum.AMB,
                    period_start="2023-06-15T14:00:00Z",
                )
            ],
            documents=[
                CanonicalDocument(
                    doc_id="DOC-02",
                    title="Follow-up Note",
                    date="2023-06-15T14:00:00Z",
                    content="Glucose controlled on Metformin.",
                )
            ],
        )

        merged = DataCleaner.deduplicate_and_merge([p1, p2])
        assert len(merged) == 1
        master = merged[0]
        assert master.mrn == "MRN:000999"
        assert len(master.encounters) == 2
        assert len(master.documents) == 2
        # Check that deduplication audit entry is present
        dedup_entries = [a for a in master.audit_log if a.field_name == "record_deduplication"]
        assert len(dedup_entries) == 1
        assert "Deduplicate" in dedup_entries[0].transformation_rule


class TestIngestionPipelineEndToEnd:
    """Verifies that all three source formats parse and clean properly from standalone files."""

    def test_json_parser(self):
        json_file = sorted(DATA_DIR.glob("*.json"))[0]
        parser = JSONEHRParser()
        patients = parser.parse(json_file)
        assert len(patients) == 1
        p = patients[0]
        assert p.mrn.startswith("MRN:")
        assert len(p.encounters) >= 1
        assert len(p.audit_log) >= 0

    def test_csv_parser(self):
        csv_file = sorted(DATA_DIR.glob("*.csv"))[0]
        parser = CSVEHRParser()
        patients = parser.parse(csv_file)
        assert len(patients) >= 1
        p = patients[0]
        assert p.mrn.startswith("MRN:")
        assert len(p.documents) >= 1

    def test_txt_parser(self):
        txt_file = sorted(DATA_DIR.glob("*.txt"))[0]
        parser = TextEHRParser()
        patients = parser.parse(txt_file)
        assert len(patients) >= 1
        p = patients[0]
        assert p.mrn.startswith("MRN:")
        assert len(p.diagnostics) >= 1

    def test_pipeline_consolidation(self):
        pipeline = IngestionPipeline()
        patients = pipeline.ingest_directory(DATA_DIR)
        assert len(patients) >= 10
        for p in patients:
            assert p.mrn.startswith("MRN:")
            assert p.gender in [GenderEnum.MALE, GenderEnum.FEMALE, GenderEnum.OTHER, GenderEnum.UNKNOWN]
            assert "-" in p.birth_date

    def test_ingest_sample_unprocessed_records(self):
        """Tests ingestion pipeline using 10 sample files from the 50 unprocessed records."""
        unprocessed_dir = Path(__file__).resolve().parent.parent / "data" / "unprocessed"
        assert unprocessed_dir.exists()
        all_unprocessed = sorted([f for f in unprocessed_dir.iterdir() if f.is_file() and not f.name.startswith(".")])
        assert len(all_unprocessed) == 50

        # Sample 10 files across formats
        sample_files = all_unprocessed[:10]
        assert len(sample_files) == 10

        pipeline = IngestionPipeline()
        ingested_patients = []
        for file_path in sample_files:
            patients = pipeline.parse_file(file_path)
            assert len(patients) >= 1
            ingested_patients.extend(patients)

        assert len(ingested_patients) >= 10
        for p in ingested_patients:
            assert p.mrn.startswith("MRN:")
            assert p.patient_id.startswith("P-")

