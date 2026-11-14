"""Parsers for multi-format messy EHR data: JSON, CSV, and plain-text."""

import csv
import json
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Union

from .cleaner import DataCleaner
from .models import (
    AuditEntry,
    CanonicalDiagnosticReport,
    CanonicalDocument,
    CanonicalEncounter,
    CanonicalPatient,
    EncounterClassEnum,
    GenderEnum,
)


class BaseEHRParser(ABC):
    """Abstract Base Class for format-specific EHR record parsers."""

    @abstractmethod
    def parse(self, source: Union[str, Path]) -> List[CanonicalPatient]:
        """Parse source data into a list of CanonicalPatient instances."""
        pass


class JSONEHRParser(BaseEHRParser):
    """Parses JSON-exported EHR dumps (e.g. Epic Clarity/Caboodle simulated export)."""

    def parse(self, source: Union[str, Path]) -> List[CanonicalPatient]:
        path = Path(source)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, dict):
            raw_patients = [data]
        elif isinstance(data, list):
            raw_patients = data
        else:
            raise ValueError(f"Unsupported JSON root type: {type(data)}")

        results: List[CanonicalPatient] = []
        for raw in raw_patients:
            audits: List[AuditEntry] = []

            # 1. MRN
            raw_mrn = raw.get("MRN") or raw.get("mrn") or raw.get("patient_id")
            clean_mrn, mrn_audit = DataCleaner.clean_mrn(raw_mrn)
            if mrn_audit:
                audits.append(mrn_audit)

            # 2. Name
            raw_name = raw.get("full_name") or raw.get("name") or "Unknown"
            (first, last), name_audits = DataCleaner.clean_name(raw_name)
            audits.extend(name_audits)

            # 3. DOB
            raw_dob = raw.get("birth_date") or raw.get("dob")
            clean_dob, dob_audit = DataCleaner.clean_date(raw_dob, is_birth_date=True)
            if dob_audit:
                audits.append(dob_audit)

            # 4. Gender
            raw_gender = raw.get("gender_code") or raw.get("gender")
            clean_gender, gender_audit = DataCleaner.clean_gender(raw_gender)
            if gender_audit:
                audits.append(gender_audit)

            # 5. Encounters
            encounters: List[CanonicalEncounter] = []
            enc_id = f"ENC-{clean_mrn.replace('MRN:', '')}-1"
            if "encounter" in raw and isinstance(raw["encounter"], dict):
                e = raw["encounter"]
                enc_id = e.get("encounter_id", enc_id)
                e_class_str = e.get("class", "AMB").upper()
                e_class = EncounterClassEnum.__members__.get(e_class_str, EncounterClassEnum.AMB)

                p_start, start_audit = DataCleaner.clean_date(e.get("period_start"))
                if start_audit:
                    audits.append(start_audit)

                p_end = None
                if e.get("period_end"):
                    p_end, end_audit = DataCleaner.clean_date(e.get("period_end"))
                    if end_audit:
                        audits.append(end_audit)

                encounters.append(
                    CanonicalEncounter(
                        encounter_id=enc_id,
                        encounter_class=e_class,
                        period_start=p_start,
                        period_end=p_end,
                        reason=e.get("reason"),
                    )
                )

            # 6. Documents
            documents: List[CanonicalDocument] = []
            for d in raw.get("documents", []):
                d_date, d_audit = DataCleaner.clean_date(d.get("date"))
                if d_audit:
                    audits.append(d_audit)
                documents.append(
                    CanonicalDocument(
                        doc_id=d.get("doc_id", f"DOC-{len(documents)+1}"),
                        title=d.get("title", "Clinical Document"),
                        type_code=d.get("type_code", "34108-1"),
                        date=d_date,
                        content=d.get("content", ""),
                        mime_type=d.get("mime_type", "text/plain"),
                        encounter_id=enc_id,
                    )
                )

            # 7. Diagnostics
            diagnostics: List[CanonicalDiagnosticReport] = []
            for dg in raw.get("diagnostics", []):
                dg_date, dg_audit = DataCleaner.clean_date(dg.get("effective_date"))
                if dg_audit:
                    audits.append(dg_audit)
                diagnostics.append(
                    CanonicalDiagnosticReport(
                        report_id=dg.get("report_id", f"DIAG-{len(diagnostics)+1}"),
                        test_name=dg.get("test_name", "Diagnostic Test"),
                        loinc_code=dg.get("loinc_code", "24323-8"),
                        effective_date=dg_date,
                        conclusion=dg.get("conclusion", ""),
                        encounter_id=enc_id,
                    )
                )

            patient = CanonicalPatient(
                patient_id=raw.get("patient_id") or clean_mrn.replace("MRN:", "P-"),
                mrn=clean_mrn,
                first_name=first,
                last_name=last,
                birth_date=clean_dob,
                gender=clean_gender,
                encounters=encounters,
                documents=documents,
                diagnostics=diagnostics,
                audit_log=audits,
            )
            results.append(patient)

        return results


class CSVEHRParser(BaseEHRParser):
    """Parses tabular/CSV scanned clinical notes and outpatient consults."""

    def parse(self, source: Union[str, Path]) -> List[CanonicalPatient]:
        path = Path(source)
        results: List[CanonicalPatient] = []

        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for idx, row in enumerate(reader):
                audits: List[AuditEntry] = []

                # MRN
                raw_mrn = row.get("Pt_MRN") or row.get("mrn") or row.get("MRN")
                clean_mrn, mrn_audit = DataCleaner.clean_mrn(raw_mrn)
                if mrn_audit:
                    audits.append(mrn_audit)

                # Name
                raw_name = row.get("patient_name") or row.get("name")
                (first, last), name_audits = DataCleaner.clean_name(raw_name)
                audits.extend(name_audits)

                # DOB
                raw_dob = row.get("dob") or row.get("birth_date")
                clean_dob, dob_audit = DataCleaner.clean_date(raw_dob, is_birth_date=True)
                if dob_audit:
                    audits.append(dob_audit)

                # Gender
                raw_gender = row.get("gender") or row.get("gender_code")
                clean_gender, gender_audit = DataCleaner.clean_gender(raw_gender)
                if gender_audit:
                    audits.append(gender_audit)

                # Encounter
                enc_id = row.get("encounter_id") or f"ENC-{clean_mrn.replace('MRN:', '')}-1"
                raw_class = row.get("enc_class", "AMB").upper()
                enc_class = EncounterClassEnum.__members__.get(raw_class, EncounterClassEnum.AMB)
                enc_date, date_audit = DataCleaner.clean_date(row.get("enc_date"))
                if date_audit:
                    audits.append(date_audit)

                encounter = CanonicalEncounter(
                    encounter_id=enc_id,
                    encounter_class=enc_class,
                    period_start=enc_date,
                    reason=row.get("note_type", "Outpatient Consultation"),
                )

                # Document note
                note_content = row.get("note_content") or row.get("content") or ""
                doc = CanonicalDocument(
                    doc_id=f"DOC-CSV-{clean_mrn.replace('MRN:', '')}-{idx+1}",
                    title=row.get("note_type", "Clinical Progress Note"),
                    type_code="34108-1",
                    date=enc_date,
                    content=note_content,
                    mime_type="text/plain",
                    encounter_id=enc_id,
                )

                patient = CanonicalPatient(
                    patient_id=clean_mrn.replace("MRN:", "P-"),
                    mrn=clean_mrn,
                    first_name=first,
                    last_name=last,
                    birth_date=clean_dob,
                    gender=clean_gender,
                    encounters=[encounter],
                    documents=[doc],
                    diagnostics=[],
                    audit_log=audits,
                )
                results.append(patient)

        return results


class TextEHRParser(BaseEHRParser):
    """Parses semi-structured plain-text diagnostic lab and pathology reports."""

    def parse(self, source: Union[str, Path]) -> List[CanonicalPatient]:
        path = Path(source)
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        # Split on record delimiters
        record_blocks = re.findall(r"--- RECORD START ---(.*?)--- RECORD END ---", content, re.DOTALL)
        results: List[CanonicalPatient] = []

        for idx, block in enumerate(record_blocks):
            audits: List[AuditEntry] = []

            # Extract fields via regex patterns
            mrn_match = re.search(r"PATIENT IDENTIFIER:\s*(.+)", block)
            name_match = re.search(r"PATIENT NAME:\s*(.+)", block)
            dob_match = re.search(r"DOB:\s*(.+)", block)
            gender_match = re.search(r"GENDER:\s*(.+)", block)
            enc_match = re.search(r"ENCOUNTER REF:\s*(.+)", block)
            date_match = re.search(r"COLLECTION DATE:\s*(.+)", block)
            panel_match = re.search(r"TEST PANEL:\s*(.+)", block)
            findings_match = re.search(r"FINDINGS:\s*(.*?)(?=CLINICAL IMPRESSION:|$)", block, re.DOTALL)
            impression_match = re.search(r"CLINICAL IMPRESSION:\s*(.*)", block, re.DOTALL)

            raw_mrn = mrn_match.group(1).strip() if mrn_match else f"TXT-{idx+1}"
            clean_mrn, mrn_audit = DataCleaner.clean_mrn(raw_mrn)
            if mrn_audit:
                audits.append(mrn_audit)

            raw_name = name_match.group(1).strip() if name_match else "Unknown"
            (first, last), name_audits = DataCleaner.clean_name(raw_name)
            audits.extend(name_audits)

            raw_dob = dob_match.group(1).strip() if dob_match else None
            clean_dob, dob_audit = DataCleaner.clean_date(raw_dob, is_birth_date=True)
            if dob_audit:
                audits.append(dob_audit)

            raw_gender = gender_match.group(1).strip() if gender_match else None
            clean_gender, gender_audit = DataCleaner.clean_gender(raw_gender)
            if gender_audit:
                audits.append(gender_audit)

            # Encounter
            raw_enc = enc_match.group(1).strip() if enc_match else f"ENC-TXT-{idx+1}"
            enc_id = raw_enc.split(" ")[0]
            enc_class = EncounterClassEnum.EMER if "emergency" in raw_enc.lower() else EncounterClassEnum.AMB

            raw_date = date_match.group(1).strip() if date_match else None
            clean_date, date_audit = DataCleaner.clean_date(raw_date)
            if date_audit:
                audits.append(date_audit)

            encounter = CanonicalEncounter(
                encounter_id=enc_id,
                encounter_class=enc_class,
                period_start=clean_date,
                reason="Diagnostic Laboratory and Imaging Evaluation",
            )

            # Test details
            raw_panel = panel_match.group(1).strip() if panel_match else "Diagnostic Laboratory Panel"
            loinc = "24323-8"
            loinc_match = re.search(r"LOINC:\s*([\d-]+)", raw_panel)
            if loinc_match:
                loinc = loinc_match.group(1)

            findings = findings_match.group(1).strip() if findings_match else ""
            impression = impression_match.group(1).strip() if impression_match else ""
            full_conclusion = f"{findings}\n\nClinical Impression:\n{impression}".strip()

            diag = CanonicalDiagnosticReport(
                report_id=f"DIAG-TXT-{idx+1}",
                test_name=raw_panel,
                loinc_code=loinc,
                effective_date=clean_date,
                conclusion=full_conclusion,
                encounter_id=enc_id,
            )

            patient = CanonicalPatient(
                patient_id=clean_mrn.replace("MRN:", "P-"),
                mrn=clean_mrn,
                first_name=first,
                last_name=last,
                birth_date=clean_dob,
                gender=clean_gender,
                encounters=[encounter],
                documents=[],
                diagnostics=[diag],
                audit_log=audits,
            )
            results.append(patient)

        return results


class IngestionPipeline:
    """Orchestrates parsing of multi-format EHR sources and runs consolidation & deduplication."""

    def __init__(self):
        self.json_parser = JSONEHRParser()
        self.csv_parser = CSVEHRParser()
        self.txt_parser = TextEHRParser()

    def ingest_sources(
        self,
        json_path: Union[str, Path, None] = None,
        csv_path: Union[str, Path, None] = None,
        txt_path: Union[str, Path, None] = None,
    ) -> List[CanonicalPatient]:
        all_patients: List[CanonicalPatient] = []

        if json_path and Path(json_path).exists():
            all_patients.extend(self.json_parser.parse(json_path))

        if csv_path and Path(csv_path).exists():
            all_patients.extend(self.csv_parser.parse(csv_path))

        if txt_path and Path(txt_path).exists():
            all_patients.extend(self.txt_parser.parse(txt_path))

        # Consolidate and deduplicate records by normalized MRN
        consolidated = DataCleaner.deduplicate_and_merge(all_patients)
        return consolidated

