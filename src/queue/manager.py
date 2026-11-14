"""SQLite-backed ingestion queue manager for asynchronous patient record processing."""

import hashlib
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel

from src.config import settings


class QueueItem(BaseModel):
    id: int
    batch_id: Optional[str] = None
    source_type: str
    file_path: Optional[str] = None
    file_name: str
    file_content: Optional[str] = None
    content_hash: str
    status: str
    error_message: Optional[str] = None
    patient_id: Optional[str] = None
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class QueueStats(BaseModel):
    unprocessed: int = 0
    in_processing: int = 0
    successful: int = 0
    skipped_duplicates: int = 0
    failed: int = 0
    total: int = 0
    is_active: bool = False
    progress_percent: float = 0.0
    current_file: Optional[str] = None
    message: str = "Ingestion queue is idle."

    # Active batch counters
    batch_total: int = 0
    batch_done: int = 0
    batch_remaining: int = 0


class QueueManager:
    """Manages persistent SQLite queue for asynchronous EHR record ingestion."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path or settings.DATABASE_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Initializes the ingestion_queue table."""
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ingestion_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    batch_id TEXT,
                    source_type TEXT NOT NULL,
                    file_path TEXT,
                    file_name TEXT NOT NULL,
                    file_content TEXT,
                    content_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error_message TEXT,
                    patient_id TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    started_at TIMESTAMP,
                    completed_at TIMESTAMP
                );
                """
            )
            # Add batch_id column if migrating from older schema
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(ingestion_queue);")
            cols = [row["name"] for row in cursor.fetchall()]
            if "batch_id" not in cols:
                conn.execute("ALTER TABLE ingestion_queue ADD COLUMN batch_id TEXT;")
                conn.execute("UPDATE ingestion_queue SET batch_id = 'batch_init' WHERE batch_id IS NULL;")

            conn.execute("CREATE INDEX IF NOT EXISTS idx_queue_status ON ingestion_queue(status);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_queue_hash ON ingestion_queue(content_hash);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_queue_batch ON ingestion_queue(batch_id);")

            # Recover any orphaned items left in PROCESSING state from a previous crashed process
            conn.execute(
                """
                UPDATE ingestion_queue
                SET status = 'FAILED', error_message = 'Interrupted by process restart'
                WHERE status = 'PROCESSING';
                """
            )
            conn.commit()

    def create_batch_id(self, prefix: str = "batch") -> str:
        """Generates a unique timestamped batch identifier."""
        return f"{prefix}_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"

    def compute_content_hash(self, content_bytes: bytes) -> str:
        return hashlib.sha256(content_bytes).hexdigest()

    def enqueue_file(
        self,
        file_path: Path,
        source_type: str = "directory",
        batch_id: Optional[str] = None,
    ) -> Tuple[int, str]:
        """Enqueues a file from disk into the ingestion queue.
        Detects if content hash was already completed or skipped.
        """
        path = Path(file_path)
        content_bytes = path.read_bytes()
        content_hash = self.compute_content_hash(content_bytes)
        now = datetime.now(timezone.utc).isoformat()
        b_id = batch_id or self.create_batch_id()

        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Check if identical content hash is already pending or in-processing
            cursor.execute(
                "SELECT id, status FROM ingestion_queue WHERE content_hash = ? AND status IN ('PENDING', 'PROCESSING');",
                (content_hash,),
            )
            existing = cursor.fetchone()
            if existing:
                return existing["id"], existing["status"]

            # Check if this exact content hash was previously COMPLETED
            cursor.execute(
                "SELECT id, patient_id FROM ingestion_queue WHERE content_hash = ? AND status = 'COMPLETED';",
                (content_hash,),
            )
            completed_prev = cursor.fetchone()
            if completed_prev:
                # Enqueue as SKIPPED_DUPLICATE to record in current batch telemetry
                cursor.execute(
                    """
                    INSERT INTO ingestion_queue (
                        batch_id, source_type, file_path, file_name, content_hash, status, patient_id, completed_at
                    ) VALUES (?, ?, ?, ?, ?, 'SKIPPED_DUPLICATE', ?, ?);
                    """,
                    (b_id, source_type, str(path), path.name, content_hash, completed_prev["patient_id"], now),
                )
                conn.commit()
                return cursor.lastrowid, "SKIPPED_DUPLICATE"

            # New unique record -> PENDING
            cursor.execute(
                """
                INSERT INTO ingestion_queue (
                    batch_id, source_type, file_path, file_name, content_hash, status, created_at
                ) VALUES (?, ?, ?, ?, ?, 'PENDING', ?);
                """,
                (b_id, source_type, str(path), path.name, content_hash, now),
            )
            conn.commit()
            return cursor.lastrowid, "PENDING"

    def enqueue_upload(
        self,
        file_name: str,
        content_bytes: bytes,
        batch_id: Optional[str] = None,
    ) -> Tuple[int, str]:
        """Enqueues raw file bytes from frontend drag-and-drop / upload."""
        content_hash = self.compute_content_hash(content_bytes)
        content_str = content_bytes.decode("utf-8", errors="replace")
        now = datetime.now(timezone.utc).isoformat()
        b_id = batch_id or self.create_batch_id(prefix="upload")

        with self._get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute(
                "SELECT id, status FROM ingestion_queue WHERE content_hash = ? AND status IN ('PENDING', 'PROCESSING');",
                (content_hash,),
            )
            existing = cursor.fetchone()
            if existing:
                return existing["id"], existing["status"]

            cursor.execute(
                "SELECT id, patient_id FROM ingestion_queue WHERE content_hash = ? AND status = 'COMPLETED';",
                (content_hash,),
            )
            completed_prev = cursor.fetchone()
            if completed_prev:
                cursor.execute(
                    """
                    INSERT INTO ingestion_queue (
                        batch_id, source_type, file_name, file_content, content_hash, status, patient_id, completed_at
                    ) VALUES (?, 'upload', ?, ?, ?, 'SKIPPED_DUPLICATE', ?, ?);
                    """,
                    (b_id, file_name, content_str, content_hash, completed_prev["patient_id"], now),
                )
                conn.commit()
                return cursor.lastrowid, "SKIPPED_DUPLICATE"

            cursor.execute(
                """
                INSERT INTO ingestion_queue (
                    batch_id, source_type, file_name, file_content, content_hash, status, created_at
                ) VALUES (?, 'upload', ?, ?, ?, 'PENDING', ?);
                """,
                (b_id, file_name, content_str, content_hash, now),
            )
            conn.commit()
            return cursor.lastrowid, "PENDING"

    def enqueue_directory(
        self,
        dir_path: Path,
        reset_previous: bool = False,
        batch_id: Optional[str] = None,
    ) -> Dict[str, int]:
        """Scans directory and enqueues all supported clinical data files."""
        path = Path(dir_path)
        if not path.exists():
            return {"enqueued": 0, "duplicates": 0, "total": 0}

        if reset_previous:
            with self._get_connection() as conn:
                conn.execute("DELETE FROM ingestion_queue;")
                conn.commit()

        b_id = batch_id or self.create_batch_id(prefix="dir")
        files = [
            f
            for f in sorted(path.iterdir())
            if f.is_file() and not f.name.startswith(".") and f.suffix.lower() in [".json", ".csv", ".txt", ".text"]
        ]

        enqueued_count = 0
        skipped_count = 0

        for f in files:
            _, status = self.enqueue_file(f, source_type="directory", batch_id=b_id)
            if status == "PENDING":
                enqueued_count += 1
            elif status == "SKIPPED_DUPLICATE":
                skipped_count += 1

        return {
            "enqueued": enqueued_count,
            "duplicates": skipped_count,
            "total": len(files),
        }

    def get_next_pending(self) -> Optional[QueueItem]:
        """Atomically fetches and marks the oldest PENDING item as PROCESSING."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, batch_id, source_type, file_path, file_name, file_content, content_hash,
                       status, error_message, patient_id, created_at, started_at, completed_at
                FROM ingestion_queue
                WHERE status = 'PENDING'
                ORDER BY id ASC
                LIMIT 1;
                """
            )
            row = cursor.fetchone()
            if not row:
                return None

            item_id = row["id"]
            now = datetime.now(timezone.utc).isoformat()
            cursor.execute(
                """
                UPDATE ingestion_queue
                SET status = 'PROCESSING', started_at = ?
                WHERE id = ? AND status = 'PENDING';
                """,
                (now, item_id),
            )
            conn.commit()

            return QueueItem(
                id=row["id"],
                batch_id=row["batch_id"],
                source_type=row["source_type"],
                file_path=row["file_path"],
                file_name=row["file_name"],
                file_content=row["file_content"],
                content_hash=row["content_hash"],
                status="PROCESSING",
                error_message=row["error_message"],
                patient_id=row["patient_id"],
                created_at=row["created_at"],
                started_at=now,
                completed_at=row["completed_at"],
            )

    def mark_completed(self, item_id: int, patient_id: Optional[str] = None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE ingestion_queue
                SET status = 'COMPLETED', completed_at = ?, patient_id = ?
                WHERE id = ?;
                """,
                (now, patient_id, item_id),
            )
            conn.commit()

    def mark_skipped_duplicate(self, item_id: int, patient_id: Optional[str] = None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE ingestion_queue
                SET status = 'SKIPPED_DUPLICATE', completed_at = ?, patient_id = ?
                WHERE id = ?;
                """,
                (now, patient_id, item_id),
            )
            conn.commit()

    def mark_failed(self, item_id: int, error_message: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE ingestion_queue
                SET status = 'FAILED', completed_at = ?, error_message = ?
                WHERE id = ?;
                """,
                (now, error_message, item_id),
            )
            conn.commit()

    def get_stats(self) -> QueueStats:
        """Calculates current telemetry counters across queue states.
        
        Progress percent and active counts are scoped strictly to the current active
        ingestion batch, preventing historical completed records from inflating totals.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT status, COUNT(*) as cnt
                FROM ingestion_queue
                GROUP BY status;
                """
            )
            counts = {row["status"]: row["cnt"] for row in cursor.fetchall()}

            unprocessed = counts.get("PENDING", 0)
            in_processing = counts.get("PROCESSING", 0)
            successful = counts.get("COMPLETED", 0)
            skipped = counts.get("SKIPPED_DUPLICATE", 0)
            failed = counts.get("FAILED", 0)
            total = unprocessed + in_processing + successful + skipped + failed

            cursor.execute(
                """
                SELECT file_name FROM ingestion_queue
                WHERE status = 'PROCESSING'
                ORDER BY id ASC LIMIT 1;
                """
            )
            curr = cursor.fetchone()
            current_file = curr["file_name"] if curr else None

            is_active = (unprocessed > 0 or in_processing > 0)

            if is_active:
                # Find all batch IDs actively being processed
                cursor.execute(
                    """
                    SELECT DISTINCT batch_id FROM ingestion_queue
                    WHERE status IN ('PENDING', 'PROCESSING') AND batch_id IS NOT NULL;
                    """
                )
                active_batches = [row["batch_id"] for row in cursor.fetchall()]

                if active_batches:
                    placeholders = ",".join("?" for _ in active_batches)
                    cursor.execute(
                        f"""
                        SELECT
                            COUNT(*) as b_total,
                            SUM(CASE WHEN status IN ('COMPLETED', 'SKIPPED_DUPLICATE', 'FAILED') THEN 1 ELSE 0 END) as b_done
                        FROM ingestion_queue
                        WHERE batch_id IN ({placeholders});
                        """,
                        active_batches,
                    )
                    b_row = cursor.fetchone()
                    batch_total = b_row["b_total"] or (unprocessed + in_processing)
                    batch_done = b_row["b_done"] or 0
                else:
                    batch_total = unprocessed + in_processing
                    batch_done = 0

                batch_remaining = max(0, batch_total - batch_done)
                progress_pct = round((batch_done / batch_total * 100), 1) if batch_total > 0 else 0.0

                if current_file:
                    msg = f"Processing {current_file} ({batch_done}/{batch_total} complete · {progress_pct}%)..."
                else:
                    msg = f"Processing records ({batch_done}/{batch_total} complete · {progress_pct}%)..."

            else:
                batch_total = 0
                batch_done = 0
                batch_remaining = 0
                progress_pct = 100.0 if total > 0 else 0.0

                # Check stats of the latest completed batch
                cursor.execute(
                    """
                    SELECT batch_id FROM ingestion_queue
                    WHERE batch_id IS NOT NULL
                    ORDER BY id DESC LIMIT 1;
                    """
                )
                latest_b = cursor.fetchone()
                if latest_b and latest_b["batch_id"]:
                    cursor.execute(
                        """
                        SELECT
                            COUNT(*) as b_tot,
                            SUM(CASE WHEN status = 'COMPLETED' THEN 1 ELSE 0 END) as b_succ,
                            SUM(CASE WHEN status = 'SKIPPED_DUPLICATE' THEN 1 ELSE 0 END) as b_skip,
                            SUM(CASE WHEN status = 'FAILED' THEN 1 ELSE 0 END) as b_fail
                        FROM ingestion_queue
                        WHERE batch_id = ?;
                        """,
                        (latest_b["batch_id"],),
                    )
                    b_info = cursor.fetchone()
                    b_succ = b_info["b_succ"] or 0
                    b_skip = b_info["b_skip"] or 0
                    b_fail = b_info["b_fail"] or 0
                    b_tot = b_info["b_tot"] or 0

                    if b_tot > 0:
                        parts = []
                        if b_succ > 0:
                            parts.append(f"{b_succ} indexed")
                        if b_skip > 0:
                            parts.append(f"{b_skip} duplicate(s) skipped")
                        if b_fail > 0:
                            parts.append(f"{b_fail} failed")
                        summary_str = ", ".join(parts) if parts else "0 processed"
                        msg = f"Ingestion complete: {summary_str}."
                    else:
                        msg = "Ingestion queue is idle."
                elif total > 0:
                    msg = f"Ingestion complete: {successful} indexed, {failed} failed, {skipped} duplicate(s) skipped."
                else:
                    msg = "Ingestion queue is idle."

            return QueueStats(
                unprocessed=unprocessed,
                in_processing=in_processing,
                successful=successful,
                skipped_duplicates=skipped,
                failed=failed,
                total=total,
                is_active=is_active,
                progress_percent=progress_pct,
                current_file=current_file,
                message=msg,
                batch_total=batch_total,
                batch_done=batch_done,
                batch_remaining=batch_remaining,
            )

    def clear(self) -> None:
        """Clears all queue items."""
        with self._get_connection() as conn:
            conn.execute("DELETE FROM ingestion_queue;")
            conn.commit()
