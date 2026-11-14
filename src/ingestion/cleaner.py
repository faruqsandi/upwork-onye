"""Data cleaning, sanitization, and deduplication engine."""

import re
from datetime import datetime, timezone
from typing import Any, List, Optional, Tuple
from dateutil import parser as date_parser

from .models import (
    AuditEntry,
    CanonicalPatient,
    CanonicalEncounter,
    CanonicalDocument,
    CanonicalDiagnosticReport,
    GenderEnum,
)


class DataCleaner:
    """Provides stateless, deterministic data sanitization and audit logging."""

    @staticmethod
    def clean_mrn(raw_mrn: Any) -> Tuple[str, Optional[AuditEntry]]:
        """Normalize MRN to standard 'MRN:XXXXXX' format."""
        orig_str = str(raw_mrn) if raw_mrn is not None else ""
        cleaned = orig_str.strip()

        # Extract numeric core or alphanumeric identifier
        # Match patterns like MRN-123, MRN:123, MRN 123, or raw 123
        digits_match = re.search(r"(\d+)", cleaned)
        if digits_match:
            digits = digits_match.group(1)
            # Pad to 6 digits if shorter
            padded = digits.zfill(6)
            normalized = f"MRN:{padded}"
        else:
            # Fallback for alphanumeric codes
            clean_token = re.sub(r"[^A-Za-z0-9]", "", cleaned).upper()
            normalized = f"MRN:{clean_token}" if clean_token else "MRN:000000"

        audit = None
        if orig_str != normalized:
            audit = AuditEntry(
                field_name="mrn",
                original_value=raw_mrn,
                cleaned_value=normalized,
                transformation_rule="Sanitize and zero-pad MRN into MRN:XXXXXX format",
            )
        return normalized, audit

    @staticmethod
    def clean_date(raw_date: Any, is_birth_date: bool = False) -> Tuple[str, Optional[AuditEntry]]:
        """Normalize diverse date inputs into standard ISO-8601 strings.

        is_birth_date=True outputs 'YYYY-MM-DD'.
        Otherwise outputs 'YYYY-MM-DDTHH:MM:SSZ' or 'YYYY-MM-DD' if time is not present.
        """
        orig_str = str(raw_date).strip() if raw_date is not None else ""
        if not orig_str or orig_str.lower() in ("none", "null", "unknown", "n/a"):
            fallback = "1900-01-01" if is_birth_date else datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00Z")
            audit = AuditEntry(
                field_name="date",
                original_value=raw_date,
                cleaned_value=fallback,
                transformation_rule="Impute missing date with fallback timestamp",
            )
            return fallback, audit

        try:
            # Check if numeric epoch timestamp
            if re.match(r"^\d{9,12}(\.\d+)?$", orig_str):
                dt = datetime.fromtimestamp(float(orig_str), tz=timezone.utc)
            else:
                dt = date_parser.parse(orig_str)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)

            if is_birth_date:
                normalized = dt.strftime("%Y-%m-%d")
            else:
                # If original didn't have time information, keep YYYY-MM-DD
                has_time = any(token in orig_str for token in [":", "T", "AM", "PM", "am", "pm"])
                normalized = dt.strftime("%Y-%m-%dT%H:%M:%SZ") if has_time else dt.strftime("%Y-%m-%d")

        except Exception:
            fallback = "1900-01-01" if is_birth_date else "2020-01-01T00:00:00Z"
            return fallback, AuditEntry(
                field_name="date",
                original_value=raw_date,
                cleaned_value=fallback,
                transformation_rule="Failed date parse; set safe sentinel fallback",
            )

        audit = None
        if orig_str != normalized:
            audit = AuditEntry(
                field_name="birth_date" if is_birth_date else "date",
                original_value=raw_date,
                cleaned_value=normalized,
                transformation_rule="Standardize date representation to ISO-8601 format",
            )
        return normalized, audit

    @staticmethod
    def clean_gender(raw_gender: Any) -> Tuple[GenderEnum, Optional[AuditEntry]]:
        """Normalize heterogeneous gender descriptions to FHIR AdministrativeGender."""
        orig_str = str(raw_gender).strip() if raw_gender is not None else ""
        g_lower = orig_str.lower()

        if g_lower in ("m", "male", "cis-male", "cis male", "man"):
            normalized = GenderEnum.MALE
        elif g_lower in ("f", "female", "cis-female", "cis female", "woman"):
            normalized = GenderEnum.FEMALE
        elif g_lower in ("o", "other", "non-binary", "enby"):
            normalized = GenderEnum.OTHER
        else:
            normalized = GenderEnum.UNKNOWN

        audit = None
        if orig_str != normalized.value:
            audit = AuditEntry(
                field_name="gender",
                original_value=raw_gender,
                cleaned_value=normalized.value,
                transformation_rule="Map demographic gender code to FHIR AdministrativeGender",
            )
        return normalized, audit

    @staticmethod
    def clean_name(raw_name: Any) -> Tuple[Tuple[str, str], List[AuditEntry]]:
        """Normalize patient name string into (first_name, last_name)."""
        audits = []
        orig_str = str(raw_name).strip() if raw_name is not None else "Unknown Unknown"

        # Remove single or double quote nicknames, e.g. Robert 'Bob' Sterling -> Robert Sterling
        cleaned = re.sub(r"['\"].*?['\"]", "", orig_str)
        # Collapse multiple spaces
        cleaned = re.sub(r"\s+", " ", cleaned).strip()

        # Split into tokens
        tokens = cleaned.split(" ")
        if len(tokens) == 1:
            first, last = tokens[0].capitalize(), "Unknown"
        else:
            first = tokens[0].capitalize()
            last = " ".join(t.capitalize() for t in tokens[1:])

        normalized_full = f"{first} {last}".strip()
        if orig_str != normalized_full:
            audits.append(
                AuditEntry(
                    field_name="patient_name",
                    original_value=raw_name,
                    cleaned_value=normalized_full,
                    transformation_rule="Normalize name casing and strip embedded nickname quotes",
                )
            )
        return (first, last), audits

    @classmethod
    def deduplicate_and_merge(cls, patients: List[CanonicalPatient]) -> List[CanonicalPatient]:
        """Group records by normalized MRN, merge associated encounters/documents/diagnostics,

        and append deduplication audit entries.
        """
        by_mrn: dict[str, CanonicalPatient] = {}

        for p in patients:
            if p.mrn not in by_mrn:
                by_mrn[p.mrn] = p
            else:
                existing = by_mrn[p.mrn]
                # Merge encounters by encounter_id
                enc_ids = {e.encounter_id for e in existing.encounters}
                for enc in p.encounters:
                    if enc.encounter_id not in enc_ids:
                        existing.encounters.append(enc)
                        enc_ids.add(enc.encounter_id)

                # Merge documents by doc_id
                doc_ids = {d.doc_id for d in existing.documents}
                for doc in p.documents:
                    if doc.doc_id not in doc_ids:
                        existing.documents.append(doc)
                        doc_ids.add(doc.doc_id)

                # Merge diagnostics by report_id
                diag_ids = {dg.report_id for dg in existing.diagnostics}
                for diag in p.diagnostics:
                    if diag.report_id not in diag_ids:
                        existing.diagnostics.append(diag)
                        diag_ids.add(diag.report_id)

                # Append existing audit logs from p
                existing.audit_log.extend(p.audit_log)
                existing.audit_log.append(
                    AuditEntry(
                        field_name="record_deduplication",
                        original_value=f"Duplicate record merged for patient_id={p.patient_id}",
                        cleaned_value=f"Consolidated into master patient_id={existing.patient_id}",
                        transformation_rule="Deduplicate clinical patient records by normalized MRN",
                    )
                )

        return list(by_mrn.values())

