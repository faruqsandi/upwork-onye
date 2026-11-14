"""FHIR R4 Bundle Assembly Engine."""

from datetime import datetime, timezone
from typing import List, Tuple
import uuid
from fhir.resources.bundle import Bundle, BundleEntry
from fhir.resources.resource import Resource

from src.ingestion.models import CanonicalPatient
from .mapper import FHIRMapper
from .validator import FHIRValidator, ValidationReport


class BundleGenerator:
    """Constructs valid HL7 FHIR R4 Bundles from CanonicalPatient domain models."""

    @classmethod
    def create_patient_bundle(
        cls, canonical: CanonicalPatient, bundle_type: str = "collection"
    ) -> Tuple[Bundle, ValidationReport]:
        """Maps canonical records to FHIR resources, constructs a Bundle, and validates integrity."""
        resources: List[Resource] = FHIRMapper.map_all_resources(canonical)

        entries = []
        for res in resources:
            entry = BundleEntry(
                fullUrl=f"urn:uuid:{uuid.uuid4()}",
                resource=res,
            )
            entries.append(entry)

        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        bundle = Bundle(
            id=f"bundle-{canonical.patient_id.lower()}",
            type=bundle_type,
            timestamp=now_iso,
            entry=entries,
        )

        # Run validation
        report = FHIRValidator.validate_bundle(bundle, patient_id=canonical.patient_id)
        return bundle, report
