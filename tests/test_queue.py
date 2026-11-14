"""Unit and integration tests for SQLite-backed ingestion queue and background worker."""

import json
import tempfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from src.api.app import app
from src.fhir.storage import FHIRSQLiteStorage
from src.ingestion.parsers import IngestionPipeline
from src.queue.manager import QueueManager
from src.queue.worker import BackgroundIngestionWorker


@pytest.fixture
def temp_queue_mgr(tmp_path):
    db_path = tmp_path / "test_queue.db"
    return QueueManager(db_path=db_path)


class TestQueueManager:
    """Verifies SQLite queue table creation, enqueueing, atomic claiming, and telemetry stats."""

    def test_queue_initialization_and_empty_stats(self, temp_queue_mgr):
        stats = temp_queue_mgr.get_stats()
        assert stats.total == 0
        assert stats.unprocessed == 0
        assert stats.in_processing == 0
        assert stats.successful == 0
        assert stats.skipped_duplicates == 0
        assert stats.failed == 0
        assert not stats.is_active

    def test_enqueue_file_and_duplicate_detection(self, temp_queue_mgr, tmp_path):
        sample_file = tmp_path / "p-test-01.json"
        sample_file.write_text('{"patient_id": "P-Q-01", "name": "Queue Test", "mrn": "MRN-Q-01"}')

        # First enqueue -> PENDING
        item_id, status = temp_queue_mgr.enqueue_file(sample_file)
        assert item_id > 0
        assert status == "PENDING"

        stats = temp_queue_mgr.get_stats()
        assert stats.total == 1
        assert stats.unprocessed == 1
        assert stats.is_active

        # Atomic claim
        item = temp_queue_mgr.get_next_pending()
        assert item is not None
        assert item.id == item_id
        assert item.status == "PROCESSING"

        stats_processing = temp_queue_mgr.get_stats()
        assert stats_processing.unprocessed == 0
        assert stats_processing.in_processing == 1
        assert stats_processing.is_active

        # Mark completed
        temp_queue_mgr.mark_completed(item_id, "P-Q-01")
        stats_completed = temp_queue_mgr.get_stats()
        assert stats_completed.successful == 1
        assert stats_completed.in_processing == 0
        assert not stats_completed.is_active

        # Re-enqueue identical file -> SKIPPED_DUPLICATE
        dup_id, dup_status = temp_queue_mgr.enqueue_file(sample_file)
        assert dup_status == "SKIPPED_DUPLICATE"

        stats_dup = temp_queue_mgr.get_stats()
        assert stats_dup.successful == 1
        assert stats_dup.skipped_duplicates == 1
        assert stats_dup.total == 2

    def test_enqueue_upload_raw_content(self, temp_queue_mgr):
        raw_bytes = b'{"patient_id": "P-UP-01", "name": "Upload Test", "mrn": "MRN-UP-01"}'
        item_id, status = temp_queue_mgr.enqueue_upload("upload_01.json", raw_bytes)
        assert item_id > 0
        assert status == "PENDING"

        stats = temp_queue_mgr.get_stats()
        assert stats.total == 1
        assert stats.unprocessed == 1

        # Mark failure
        temp_queue_mgr.mark_failed(item_id, "Syntax error simulation")
        stats_failed = temp_queue_mgr.get_stats()
        assert stats_failed.failed == 1
        assert stats_failed.unprocessed == 0

    def test_batch_scoped_progress_tracking(self, temp_queue_mgr, tmp_path):
        """Verifies that progress percentage and batch numbers strictly track the active batch,
        not historical completed or duplicate records from previous runs.
        """
        # Batch 1: 5 files
        b1_files = []
        for i in range(5):
            f = tmp_path / f"b1-{i}.json"
            f.write_text(f'{{"patient_id": "P-B1-{i}", "mrn": "MRN-B1-{i}"}}')
            b1_files.append(f)

        # Enqueue and complete Batch 1
        b1_id = temp_queue_mgr.create_batch_id()
        for f in b1_files:
            item_id, _ = temp_queue_mgr.enqueue_file(f, batch_id=b1_id)
            temp_queue_mgr.mark_completed(item_id, f"P-B1-{item_id}")

        stats_b1 = temp_queue_mgr.get_stats()
        assert stats_b1.successful == 5
        assert stats_b1.total == 5
        assert not stats_b1.is_active

        # Now start Batch 2: 10 files
        b2_files = []
        b2_id = temp_queue_mgr.create_batch_id()
        for i in range(10):
            f = tmp_path / f"b2-{i}.json"
            f.write_text(f'{{"patient_id": "P-B2-{i}", "mrn": "MRN-B2-{i}"}}')
            b2_files.append(f)
            temp_queue_mgr.enqueue_file(f, batch_id=b2_id)

        stats_b2_start = temp_queue_mgr.get_stats()
        assert stats_b2_start.is_active
        # Active batch has 10 items, 0 done so progress must be 0%, NOT 5/15 (33%)!
        assert stats_b2_start.batch_total == 10
        assert stats_b2_start.batch_done == 0
        assert stats_b2_start.progress_percent == 0.0

        # Process 2 items from Batch 2
        item1 = temp_queue_mgr.get_next_pending()
        temp_queue_mgr.mark_completed(item1.id, "P-B2-1")
        item2 = temp_queue_mgr.get_next_pending()
        temp_queue_mgr.mark_completed(item2.id, "P-B2-2")

        stats_b2_mid = temp_queue_mgr.get_stats()
        # Batch done must be 2, batch total 10, progress 20.0%, NOT 7/15!
        assert stats_b2_mid.batch_total == 10
        assert stats_b2_mid.batch_done == 2
        assert stats_b2_mid.progress_percent == 20.0
        assert "2/10 complete · 20.0%" in stats_b2_mid.message


class TestBackgroundWorker:
    """Verifies that the worker processes items one by one and indexes them."""

    def test_worker_single_item_processing(self, tmp_path):
        db_path = tmp_path / "worker_test.db"
        queue_mgr = QueueManager(db_path=db_path)
        storage = FHIRSQLiteStorage(db_path=db_path)
        canonical_cache = {}

        worker = BackgroundIngestionWorker(
            queue_mgr=queue_mgr,
            storage=storage,
            canonical_cache=canonical_cache,
        )

        test_file = tmp_path / "p-worker-1.json"
        test_file.write_text(
            json.dumps(
                {
                    "patient_id": "P-W-1",
                    "full_name": "Worker Jane Doe",
                    "mrn": "MRN-W-100",
                    "birth_date": "1985-04-12",
                    "gender": "Female",
                    "documents": [
                        {
                            "document_id": "DOC-W1",
                            "title": "Progress Note",
                            "date": "2024-01-15",
                            "content": "Patient reports stable blood pressure on lisinopril.",
                        }
                    ],
                }
            )
        )

        queue_mgr.enqueue_file(test_file)
        stats_before = queue_mgr.get_stats()
        assert stats_before.unprocessed == 1

        # Drain queue synchronously
        drained = worker.drain_all_sync()
        assert drained == 1

        stats_after = queue_mgr.get_stats()
        assert stats_after.successful == 1
        assert stats_after.unprocessed == 0

        # Verify bundle was created and persisted in SQLite
        bundle = storage.get_bundle("P-W-1")
        assert bundle is not None
        assert bundle.get_resource_type() == "Bundle"

        # Verify cached in canonical cache
        assert "P-W-1" in canonical_cache


class TestQueueAPIEndpoints:
    """Verifies queue endpoints via FastAPI test client."""

    def test_queue_status_endpoint(self):
        client = TestClient(app)
        resp = client.get("/queue/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "unprocessed" in data
        assert "in_processing" in data
        assert "successful" in data
        assert "failed" in data
        assert "skipped_duplicates" in data
        assert "total_ingested" in data
        assert "is_active" in data
        assert "progress_percent" in data

    def test_post_ingest_triggers_queue(self):
        client = TestClient(app)
        resp = client.post("/ingest")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_ingested"] >= 10
        assert data["successful"] >= 10
        assert "Ingestion complete" in data["message"]
