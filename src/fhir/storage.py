"""SQLite persistence layer for FHIR R4 Bundles and validation audit logs."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from fhir.resources.bundle import Bundle

from src.config import settings
from .validator import ValidationReport


class FHIRSQLiteStorage:
    """Manages transactional persistence of FHIR Bundles in a local SQLite database."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path or settings.DATABASE_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Create bundles table if it does not already exist."""
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS fhir_bundles (
                    patient_id TEXT PRIMARY KEY,
                    mrn TEXT NOT NULL,
                    bundle_json TEXT NOT NULL,
                    resource_count INTEGER NOT NULL,
                    validation_status TEXT NOT NULL,
                    validation_errors TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_bundles_mrn ON fhir_bundles (mrn);")
            conn.commit()

    def save_bundle(
        self,
        patient_id: str,
        mrn: str,
        bundle: Bundle,
        report: ValidationReport,
    ) -> None:
        """Upsert a FHIR Bundle and its validation status."""
        bundle_json = bundle.model_dump_json() if hasattr(bundle, "model_dump_json") else bundle.json()
        status = "VALID" if report.is_valid else "INVALID"
        errors_json = json.dumps(report.errors) if report.errors else ""
        res_count = len(bundle.entry) if bundle.entry else 0
        now = datetime.now(timezone.utc).isoformat()

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO fhir_bundles (
                    patient_id, mrn, bundle_json, resource_count,
                    validation_status, validation_errors, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(patient_id) DO UPDATE SET
                    mrn = excluded.mrn,
                    bundle_json = excluded.bundle_json,
                    resource_count = excluded.resource_count,
                    validation_status = excluded.validation_status,
                    validation_errors = excluded.validation_errors,
                    updated_at = excluded.updated_at;
                """,
                (patient_id, mrn, bundle_json, res_count, status, errors_json, now),
            )
            conn.commit()

    def get_bundle(self, patient_id: str) -> Optional[Bundle]:
        """Fetch and deserialize a FHIR Bundle by patient_id."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT bundle_json FROM fhir_bundles WHERE patient_id = ?;", (patient_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return Bundle.model_validate_json(row["bundle_json"])

    def get_bundle_json(self, patient_id: str) -> Optional[str]:
        """Fetch raw JSON representation of a Bundle."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT bundle_json FROM fhir_bundles WHERE patient_id = ?;", (patient_id,))
            row = cursor.fetchone()
            return row["bundle_json"] if row else None

    def get_bundle_by_mrn(self, mrn: str) -> Optional[Bundle]:
        """Fetch and deserialize a FHIR Bundle by MRN."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT bundle_json FROM fhir_bundles WHERE mrn = ?;", (mrn,))
            row = cursor.fetchone()
            if not row:
                return None
            return Bundle.model_validate_json(row["bundle_json"])

    def list_bundles(self) -> List[Dict[str, Any]]:
        """List summary metadata for all stored bundles."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT patient_id, mrn, resource_count, validation_status,
                       validation_errors, updated_at
                FROM fhir_bundles
                ORDER BY patient_id ASC;
                """
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def count_bundles(self) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM fhir_bundles;")
            return cursor.fetchone()[0]
