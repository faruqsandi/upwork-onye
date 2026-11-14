"""Script to pre-index exactly the 50 clinical records in data/raw."""

import time
import shutil
from pathlib import Path

# Wipe old databases
db_path = Path("ehr_intelligence.db")
if db_path.exists():
    db_path.unlink()

chroma_dir = Path("chroma_data")
if chroma_dir.exists():
    shutil.rmtree(chroma_dir)

from src.fhir.storage import FHIRSQLiteStorage
from src.fhir.bundle import BundleGenerator
from src.ai.summarizer import ClinicalSummarizer
from src.search.vector_store import ClinicalVectorStore
from src.queue.manager import QueueManager
from src.ingestion.parsers import IngestionPipeline

print("Starting clean pre-indexing of 50 records in data/raw...")
t0 = time.time()
queue_mgr = QueueManager()
storage = FHIRSQLiteStorage()
summarizer = ClinicalSummarizer()
vector_store = ClinicalVectorStore()
pipeline = IngestionPipeline()

raw_dir = Path("data/raw")
files = sorted(list(raw_dir.glob("p-2*.*")))
print(f"Found {len(files)} files to pre-index.")

# Enqueue all 50
queue_mgr.enqueue_directory(raw_dir)

processed = 0
for f in files:
    item = queue_mgr.get_next_pending()
    if not item:
        break
    try:
        patients = pipeline.parse_file(Path(item.file_path))
        for p in patients:
            bundle, report = BundleGenerator.create_patient_bundle(p)
            storage.save_bundle(p.patient_id, p.mrn, bundle, report)
            summary = summarizer.summarize_patient(p)
            vector_store.index_patient(p, summary)
            queue_mgr.mark_completed(item.id, p.patient_id)
        processed += 1
        if processed % 10 == 0:
            print(f"Pre-indexed {processed}/{len(files)} in {round(time.time() - t0, 1)}s")
    except Exception as e:
        queue_mgr.mark_failed(item.id, str(e))
        print(f"Failed {f.name}: {e}")

print(f"Pre-indexing complete! {processed} records processed in {round(time.time() - t0, 1)}s")
print("Bundles in SQLite:", storage.count_bundles())
print("Vectors in ChromaDB:", vector_store.count())
print("Queue stats:", queue_mgr.get_stats())

