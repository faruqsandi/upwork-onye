"""FHIR R4 Schema Validator and Structured Error Reporting Engine."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from fhir.resources.bundle import Bundle
from fhir.resources.patient import Patient
from fhir.resources.encounter import Encounter
from fhir.resources.documentreference import DocumentReference
from fhir.resources.diagnosticreport import DiagnosticReport


class ValidationReport(BaseModel):
    """Structured report detailing validation status, issues, and resource distribution."""

    patient_id: str
    is_valid: bool = True
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    resource_counts: Dict[str, int] = Field(default_factory=dict)

    def add_error(self, message: str) -> None:
        self.is_valid = False
        self.errors.append(message)

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)


class FHIRValidator:
    """Validates FHIR R4 resources against standard schema rules and reference integrity."""

    @classmethod
    def validate_bundle(cls, bundle: Bundle, patient_id: str) -> ValidationReport:
        report = ValidationReport(patient_id=patient_id)

        if not bundle.entry:
            report.add_error("Bundle contains no resource entries.")
            return report

        patient_found = False
        known_patient_ids = set()
        known_encounter_ids = set()

        # Pass 1: Catalog IDs and count resource types
        for entry in bundle.entry:
            res = entry.resource
            if not res:
                report.add_error("Bundle entry missing resource payload.")
                continue

            res_type = getattr(res, "get_resource_type", lambda: getattr(res, "__resource_type__", type(res).__name__))()
            report.resource_counts[res_type] = report.resource_counts.get(res_type, 0) + 1

            if res_type == "Patient":
                patient_found = True
                if res.id:
                    known_patient_ids.add(f"Patient/{res.id}")
            elif res_type == "Encounter" and res.id:
                known_encounter_ids.add(f"Encounter/{res.id}")

        if not patient_found:
            report.add_error("Bundle must contain at least one Patient resource.")

        # Pass 2: Verify reference integrity
        for idx, entry in enumerate(bundle.entry):
            res = entry.resource
            if not res:
                continue

            res_type = getattr(res, "get_resource_type", lambda: getattr(res, "__resource_type__", type(res).__name__))()

            # Check Patient reference on Encounter
            if res_type == "Encounter":
                if not getattr(res, "subject", None) or not res.subject.reference:
                    report.add_error(f"Encounter (index {idx}) missing subject reference to Patient.")
                elif res.subject.reference not in known_patient_ids:
                    report.add_warning(
                        f"Encounter subject reference '{res.subject.reference}' not found within bundle."
                    )

            # Check DocumentReference references
            elif res_type == "DocumentReference":
                if not getattr(res, "subject", None) or not res.subject.reference:
                    report.add_error(f"DocumentReference (index {idx}) missing subject reference to Patient.")
                elif res.subject.reference not in known_patient_ids:
                    report.add_warning(
                        f"DocumentReference subject reference '{res.subject.reference}' not found within bundle."
                    )

                if getattr(res, "context", None):
                    for ctx_ref in res.context:
                        if ctx_ref.reference and ctx_ref.reference not in known_encounter_ids:
                            report.add_warning(
                                f"DocumentReference context encounter '{ctx_ref.reference}' not found within bundle."
                            )

            # Check DiagnosticReport references
            elif res_type == "DiagnosticReport":
                if not getattr(res, "subject", None) or not res.subject.reference:
                    report.add_error(f"DiagnosticReport (index {idx}) missing subject reference to Patient.")
                elif res.subject.reference not in known_patient_ids:
                    report.add_warning(
                        f"DiagnosticReport subject reference '{res.subject.reference}' not found within bundle."
                    )

                if getattr(res, "encounter", None) and res.encounter.reference:
                    if res.encounter.reference not in known_encounter_ids:
                        report.add_warning(
                            f"DiagnosticReport encounter reference '{res.encounter.reference}' not found within bundle."
                        )

        return report
