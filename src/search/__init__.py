"""Semantic search vertical slice."""

from .models import SearchRequest, SearchResponse, SearchResultItem
from .embeddings import EmbeddingEngine
from .vector_store import ClinicalVectorStore

__all__ = [
    "SearchRequest",
    "SearchResponse",
    "SearchResultItem",
    "EmbeddingEngine",
    "ClinicalVectorStore",
]

