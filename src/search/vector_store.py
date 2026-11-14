"""ChromaDB vector store with metadata filtering and sub-second semantic search."""

import time
from pathlib import Path
from typing import Any, Dict, List, Optional
import chromadb
from chromadb.config import Settings as ChromaSettings

from src.ai.models import ClinicalSummary
from src.config import settings
from src.ingestion.models import CanonicalPatient
from .embeddings import EmbeddingEngine
from .models import SearchRequest, SearchResponse, SearchResultItem


class ClinicalVectorStore:
    """Manages indexing and semantic retrieval of EHR clinical media and AI summaries."""

    def __init__(
        self,
        persist_dir: Optional[Path] = None,
        in_memory: bool = False,
        collection_name: str = "clinical_records",
    ):
        self.embedding_engine = EmbeddingEngine()

        if in_memory:
            self.client = chromadb.Client()
        else:
            persist_path = Path(persist_dir or settings.CHROMA_PERSIST_DIR)
            persist_path.mkdir(parents=True, exist_ok=True)
            self.client = chromadb.PersistentClient(path=str(persist_path))

        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def count(self) -> int:
        return self.collection.count()

    @staticmethod
    def _date_to_int(date_str: str) -> int:
        """Convert YYYY-MM-DD string to integer YYYYMMDD for ChromaDB numerical range filtering."""
        clean = "".join(c for c in date_str[:10] if c.isdigit())
        return int(clean) if clean else 0

    def index_patient(self, patient: CanonicalPatient, summary: ClinicalSummary) -> int:
        """Embeds and indexes all documents and diagnostic reports for a given patient."""
        ids: List[str] = []
        documents: List[str] = []
        metadatas: List[Dict[str, Any]] = []

        patient_header = (
            f"Patient: {patient.full_name} (MRN: {patient.mrn}, DOB: {patient.birth_date}, {patient.gender.value}). "
            f"Chief Concern: {summary.chief_concern}. Diagnoses: {', '.join(summary.key_diagnoses)}. "
        )

        # Index Documents
        for doc in patient.documents:
            doc_id = f"doc_{patient.patient_id}_{doc.doc_id}"
            full_text = f"{patient_header}\nDocument Title: {doc.title} ({doc.date})\nContent:\n{doc.content}"
            date_clean = doc.date[:10]

            ids.append(doc_id)
            documents.append(full_text)
            metadatas.append(
                {
                    "patient_id": patient.patient_id,
                    "patient_name": patient.full_name,
                    "mrn": patient.mrn,
                    "resource_type": "DocumentReference",
                    "record_date": date_clean,
                    "date_int": self._date_to_int(date_clean),
                    "record_id": doc.doc_id,
                    "title": doc.title,
                    "summary_snippet": summary.chief_concern,
                    "excerpt": doc.content[:300],
                }
            )

        # Index Diagnostics
        for diag in patient.diagnostics:
            diag_id = f"diag_{patient.patient_id}_{diag.report_id}"
            full_text = f"{patient_header}\nDiagnostic Test: {diag.test_name} ({diag.effective_date})\nConclusion:\n{diag.conclusion}"
            date_clean = diag.effective_date[:10]

            ids.append(diag_id)
            documents.append(full_text)
            metadatas.append(
                {
                    "patient_id": patient.patient_id,
                    "patient_name": patient.full_name,
                    "mrn": patient.mrn,
                    "resource_type": "DiagnosticReport",
                    "record_date": date_clean,
                    "date_int": self._date_to_int(date_clean),
                    "record_id": diag.report_id,
                    "title": diag.test_name,
                    "summary_snippet": summary.chief_concern,
                    "excerpt": diag.conclusion[:300],
                }
            )

        if not ids:
            return 0

        # Generate embeddings in batch
        embeddings = self.embedding_engine.embed_batch(documents)

        # Upsert into ChromaDB
        self.collection.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
        )
        return len(ids)

    def search(self, request: SearchRequest) -> SearchResponse:
        """Executes natural language semantic query with optional metadata filtering."""
        t0 = time.perf_counter()

        # Build metadata filter conditions
        where_clauses: List[Dict[str, Any]] = []

        if request.resource_type and request.resource_type in ["DocumentReference", "DiagnosticReport"]:
            where_clauses.append({"resource_type": {"$eq": request.resource_type}})

        if request.date_from:
            from_int = self._date_to_int(request.date_from)
            where_clauses.append({"date_int": {"$gte": from_int}})

        if request.date_to:
            to_int = self._date_to_int(request.date_to)
            where_clauses.append({"date_int": {"$lte": to_int}})

        where_filter = None
        if len(where_clauses) == 1:
            where_filter = where_clauses[0]
        elif len(where_clauses) > 1:
            where_filter = {"$and": where_clauses}

        # Embed query text
        query_vec = self.embedding_engine.embed_text(request.query)

        # Chroma query
        res = self.collection.query(
            query_embeddings=[query_vec],
            n_results=min(request.top_k, max(1, self.collection.count())),
            where=where_filter,
            include=["metadatas", "distances", "documents"],
        )

        execution_ms = round((time.perf_counter() - t0) * 1000, 2)

        results: List[SearchResultItem] = []
        if res and res["ids"] and len(res["ids"][0]) > 0:
            for i in range(len(res["ids"][0])):
                meta = res["metadatas"][0][i]
                dist = res["distances"][0][i] if res["distances"] else 0.5
                # Cosine distance to similarity score in [0.0, 1.0]
                relevance = max(0.0, min(1.0, round(1.0 - (dist / 2.0), 3)))

                results.append(
                    SearchResultItem(
                        record_id=meta["record_id"],
                        patient_id=meta["patient_id"],
                        patient_name=meta["patient_name"],
                        mrn=meta["mrn"],
                        resource_type=meta["resource_type"],
                        record_date=meta["record_date"],
                        relevance_score=relevance,
                        title=meta["title"],
                        summary_snippet=meta["summary_snippet"],
                        document_excerpt=meta["excerpt"],
                    )
                )

        return SearchResponse(
            query=request.query,
            total_matches=len(results),
            execution_time_ms=execution_ms,
            results=results,
        )
