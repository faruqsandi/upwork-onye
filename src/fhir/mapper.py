"""FHIR R4 Mapper Engine.

Transforms clean canonical domain models into valid HL7 FHIR R4 resources.
"""

import base64
from typing import List, Tuple
from fhir.resources.patient import Patient
from fhir.resources.encounter import Encounter
from fhir.resources.documentreference import DocumentReference
from fhir.resources.diagnosticreport import DiagnosticReport
from fhir.resources.resource import Resource

from src.ingestion.models import CanonicalPatient


class FHIRMapper:
    """Stateless mapper transforming CanonicalPatient models into validated FHIR R4 resources."""

    @classmethod
    def map_patient(cls, canonical: CanonicalPatient) -> Patient:
        """Map canonical demographics to FHIR Patient resource."""
        return Patient(
            id=canonical.patient_id,
            identifier=[
                {
                    "system": "urn:oid:onye:epic:mrn",
                    "value": canonical.mrn,
                    "use": "official",
                }
            ],
            name=[
                {
                    "family": canonical.last_name,
                    "given": [canonical.first_name],
                    "text": canonical.full_name,
                    "use": "official",
                }
            ],
            gender=canonical.gender.value,
            birthDate=canonical.birth_date,
        )

    @classmethod
    def map_encounters(cls, canonical: CanonicalPatient) -> List[Encounter]:
        """Map canonical encounters to FHIR Encounter resources."""
        encounters: List[Encounter] = []
        for enc in canonical.encounters:
            class_code = enc.encounter_class.value
            display = {
                "AMB": "ambulatory",
                "IMP": "inpatient encounter",
                "EMER": "emergency",
                "VR": "virtual",
            }.get(class_code, "ambulatory")

            enc_res = Encounter(
                id=enc.encounter_id,
                status="completed",
                class_fhir=[
                    {
                        "coding": [
                            {
                                "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
                                "code": class_code,
                                "display": display,
                            }
                        ]
                    }
                ],
                subject={"reference": f"Patient/{canonical.patient_id}"},
            )
            encounters.append(enc_res)
        return encounters

    @classmethod
    def map_documents(
        cls, canonical: CanonicalPatient, default_encounter_id: str | None = None
    ) -> List[DocumentReference]:
        """Map canonical documents to FHIR DocumentReference resources."""
        documents: List[DocumentReference] = []
        for doc in canonical.documents:
            # Base64 encode document content for FHIR attachment
            encoded_bytes = doc.content.encode("utf-8")
            b64_content = base64.b64encode(encoded_bytes).decode("utf-8")

            enc_id = doc.encounter_id or default_encounter_id
            context_refs = [{"reference": f"Encounter/{enc_id}"}] if enc_id else None

            doc_res = DocumentReference(
                id=doc.doc_id,
                status="current",
                category=[
                    {
                        "coding": [
                            {
                                "system": "http://loinc.org",
                                "code": doc.type_code,
                                "display": doc.title,
                            }
                        ]
                    }
                ],
                subject={"reference": f"Patient/{canonical.patient_id}"},
                context=context_refs,
                content=[
                    {
                        "attachment": {
                            "contentType": doc.mime_type,
                            "data": b64_content,
                            "title": doc.title,
                        }
                    }
                ],
            )
            documents.append(doc_res)
        return documents

    @classmethod
    def map_diagnostics(
        cls, canonical: CanonicalPatient, default_encounter_id: str | None = None
    ) -> List[DiagnosticReport]:
        """Map canonical diagnostic reports to FHIR DiagnosticReport resources."""
        diagnostics: List[DiagnosticReport] = []
        for diag in canonical.diagnostics:
            enc_id = diag.encounter_id or default_encounter_id
            enc_ref = {"reference": f"Encounter/{enc_id}"} if enc_id else None

            diag_res = DiagnosticReport(
                id=diag.report_id,
                status="final",
                code={
                    "coding": [
                        {
                            "system": "http://loinc.org",
                            "code": diag.loinc_code,
                            "display": diag.test_name,
                        }
                    ]
                },
                subject={"reference": f"Patient/{canonical.patient_id}"},
                encounter=enc_ref,
                conclusion=diag.conclusion,
            )
            diagnostics.append(diag_res)
        return diagnostics

    @classmethod
    def map_all_resources(cls, canonical: CanonicalPatient) -> List[Resource]:
        """Convert a CanonicalPatient into a complete set of interconnected FHIR R4 resources."""
        resources: List[Resource] = []

        # 1. Patient
        patient_res = cls.map_patient(canonical)
        resources.append(patient_res)

        # 2. Encounters
        enc_resources = cls.map_encounters(canonical)
        # Ensure at least one default encounter exists if none provided
        default_enc_id = (
            enc_resources[0].id if enc_resources else f"ENC-{canonical.patient_id}-1"
        )
        if not enc_resources:
            fallback_enc = Encounter(
                id=default_enc_id,
                status="completed",
                class_fhir=[
                    {
                        "coding": [
                            {
                                "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
                                "code": "AMB",
                                "display": "ambulatory",
                            }
                        ]
                    }
                ],
                subject={"reference": f"Patient/{canonical.patient_id}"},
            )
            enc_resources.append(fallback_enc)
        resources.extend(enc_resources)

        # 3. Documents
        doc_resources = cls.map_documents(canonical, default_encounter_id=default_enc_id)
        resources.extend(doc_resources)

        # 4. Diagnostics
        diag_resources = cls.map_diagnostics(canonical, default_encounter_id=default_enc_id)
        resources.extend(diag_resources)

        return resources
