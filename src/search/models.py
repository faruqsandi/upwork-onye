"""Search domain and request/response models."""

from typing import List, Optional
from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    """Semantic search query request with optional clinical filters."""

    query: str = Field(..., description="Natural language clinical search query")
    resource_type: Optional[str] = Field(
        None, description="Filter by FHIR resource type: 'DocumentReference' or 'DiagnosticReport'"
    )
    date_from: Optional[str] = Field(None, description="ISO date YYYY-MM-DD start filter")
    date_to: Optional[str] = Field(None, description="ISO date YYYY-MM-DD end filter")
    top_k: int = Field(5, ge=1, le=50, description="Maximum number of matches to return")


class SearchResultItem(BaseModel):
    """Ranked patient clinical match with relevance score and excerpts."""

    record_id: str
    patient_id: str
    patient_name: str
    mrn: str
    resource_type: str
    record_date: str
    relevance_score: float = Field(..., ge=0.0, le=1.0)
    title: str
    summary_snippet: str
    document_excerpt: str


class SearchResponse(BaseModel):
    """API response model for POST /search."""

    query: str
    total_matches: int
    execution_time_ms: float
    results: List[SearchResultItem]
