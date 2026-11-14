"""Embedding engine wrapper for SentenceTransformers all-MiniLM-L6-v2."""

from typing import List
from sentence_transformers import SentenceTransformer
from src.config import settings


class EmbeddingEngine:
    """Singleton wrapper around SentenceTransformer for local sub-second vector generation."""

    _instance: "EmbeddingEngine | None" = None
    _model: SentenceTransformer | None = None

    def __new__(cls) -> "EmbeddingEngine":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._model = SentenceTransformer(settings.EMBEDDING_MODEL_NAME)
        return cls._instance

    def embed_text(self, text: str) -> List[float]:
        """Generate normalized 384-dimensional embedding for a single text."""
        assert self._model is not None
        vec = self._model.encode(text, normalize_embeddings=True)
        return vec.tolist()

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate normalized embeddings for a batch of texts."""
        assert self._model is not None
        if not texts:
            return []
        vecs = self._model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return vecs.tolist()

