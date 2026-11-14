"""Background worker for asynchronous one-by-one ingestion queue processing."""

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.ai.summarizer import ClinicalSummarizer
from src.fhir.bundle import BundleGenerator
from src.fhir.storage import FHIRSQLiteStorage
from src.ingestion.cleaner import DataCleaner
from src.ingestion.parsers import IngestionPipeline
from src.queue.manager import QueueItem, QueueManager
from src.search.vector_store import ClinicalVectorStore

logger = logging.getLogger(__name__)


class BackgroundIngestionWorker:
    """Consumes items from SQLite ingestion_queue one by one in the background.

    Performs cleaning, FHIR R4 bundling, AI summarization, and vector indexing.
    Immediately updates ChromaDB vector store so search can find newly indexed records.
    """

    def __init__(
        self,
        queue_mgr: Optional[QueueManager] = None,
        pipeline: Optional[IngestionPipeline] = None,
        storage: Optional[FHIRSQLiteStorage] = None,
        summarizer: Optional[ClinicalSummarizer] = None,
        vector_store: Optional[ClinicalVectorStore] = None,
        canonical_cache: Optional[Dict[str, Any]] = None,
    ):
        self.queue_mgr = queue_mgr or QueueManager()
        self.pipeline = pipeline or IngestionPipeline()
        self.storage = storage or FHIRSQLiteStorage()
        self.summarizer = summarizer or ClinicalSummarizer()
        self.vector_store = vector_store or ClinicalVectorStore()
        self.canonical_cache = canonical_cache if canonical_cache is not None else {}

        self.should_run = False
        self._task: Optional[asyncio.Task] = None
        self._wake_event = asyncio.Event()

    def set_canonical_cache(self, cache_dict: Dict[str, Any]) -> None:
        self.canonical_cache = cache_dict

    def start(self) -> None:
        """Starts the background worker task if not already running."""
        if self._task is None or self._task.done():
            self.should_run = True
            try:
                loop = asyncio.get_running_loop()
                self._task = loop.create_task(self._worker_loop())
            except RuntimeError:
                # No active running loop (e.g. running in synchronous script/test)
                pass

    def stop(self) -> None:
        """Stops the background worker loop gracefully."""
        self.should_run = False
        self._wake_event.set()
        if self._task and not self._task.done():
            self._task.cancel()

    def notify(self) -> None:
        """Wakes up the worker immediately when new items are enqueued."""
        self._wake_event.set()

    async def _worker_loop(self) -> None:
        """Main async loop polling the queue."""
        while self.should_run:
            try:
                item = self.queue_mgr.get_next_pending()
                if not item:
                    self._wake_event.clear()
                    try:
                        await asyncio.wait_for(self._wake_event.wait(), timeout=1.0)
                    except asyncio.TimeoutError:
                        pass
                    continue

                # Run heavy synchronous operations in thread pool
                await asyncio.to_thread(self.process_single_item, item)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception("Unexpected error in background ingestion worker loop: %s", e)
                await asyncio.sleep(0.5)

    def process_single_item(self, item: QueueItem) -> bool:
        """Synchronously processes a single queue item. Returns True on success, False on error."""
        try:
            # 1. Parse records
            if item.file_content:
                patients = self.pipeline.parse_content(item.file_name, item.file_content)
            elif item.file_path:
                patients = self.pipeline.parse_file(Path(item.file_path))
            else:
                self.queue_mgr.mark_failed(item.id, "Neither file_path nor file_content provided.")
                return False

            if not patients:
                self.queue_mgr.mark_failed(item.id, "No valid patient records could be extracted from file.")
                return False

            last_patient_id = None
            for p in patients:
                last_patient_id = p.patient_id

                # Cache in canonical cache for rapid UI lookup
                self.canonical_cache[p.patient_id] = p

                # 2. FHIR Normalization & Persistence
                bundle, report = BundleGenerator.create_patient_bundle(p)
                self.storage.save_bundle(p.patient_id, p.mrn, bundle, report)

                # 3. Clinical Summarization (Cached or LLM)
                summary = self.summarizer.summarize_patient(p)

                # 4. Immediate ChromaDB Vector Indexing (Instantly searchable!)
                self.vector_store.index_patient(p, summary)

            self.queue_mgr.mark_completed(item.id, last_patient_id)
            return True

        except Exception as e:
            logger.exception("Failed processing queue item %d (%s): %s", item.id, item.file_name, e)
            self.queue_mgr.mark_failed(item.id, str(e))
            return False

    def drain_all_sync(self, max_items: int = 1000) -> int:
        """Synchronously drains all pending items. Highly useful for unit tests & initial seeding."""
        processed = 0
        while processed < max_items:
            item = self.queue_mgr.get_next_pending()
            if not item:
                break
            self.process_single_item(item)
            processed += 1
        return processed


# Global shared worker instance
_global_worker: Optional[BackgroundIngestionWorker] = None


def get_queue_worker() -> BackgroundIngestionWorker:
    global _global_worker
    if _global_worker is None:
        _global_worker = BackgroundIngestionWorker()
    return _global_worker
