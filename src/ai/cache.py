"""SQLite caching layer for AI clinical summaries to eliminate redundant LLM calls."""

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.config import settings
from .models import ClinicalSummary


class SummaryCache:
    """Manages persistent caching of AI clinical summaries keyed by (patient_id, record_hash)."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path or settings.DATABASE_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS summary_cache (
                    patient_id TEXT NOT NULL,
                    record_hash TEXT NOT NULL,
                    summary_json TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (patient_id, record_hash)
                );
                """
            )
            conn.commit()

    @staticmethod
    def compute_record_hash(content: str) -> str:
        """Compute deterministic SHA-256 hash over document history."""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def get(self, patient_id: str, record_hash: str) -> Optional[ClinicalSummary]:
        """Retrieve cached summary if hash matches."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT summary_json FROM summary_cache WHERE patient_id = ? AND record_hash = ?;",
                (patient_id, record_hash),
            )
            row = cursor.fetchone()
            if not row:
                return None
            summary_dict = json.loads(row["summary_json"])
            summary_dict["cached"] = True
            return ClinicalSummary.model_validate(summary_dict)

    def set(self, patient_id: str, record_hash: str, summary: ClinicalSummary) -> None:
        """Store summary in cache."""
        summary_copy = summary.model_copy()
        summary_copy.cached = True
        summary_json = summary_copy.model_dump_json()

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO summary_cache (patient_id, record_hash, summary_json)
                VALUES (?, ?, ?)
                ON CONFLICT(patient_id, record_hash) DO UPDATE SET
                    summary_json = excluded.summary_json,
                    created_at = CURRENT_TIMESTAMP;
                """,
                (patient_id, record_hash, summary_json),
            )
            conn.commit()

    def clear(self) -> None:
        with self._get_connection() as conn:
            conn.execute("DELETE FROM summary_cache;")
            conn.commit()

