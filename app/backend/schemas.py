"""Pydantic schemas for the backend API."""

from pydantic import BaseModel, Field
from typing import Optional


class SearchRequest(BaseModel):
    """Search request from frontend."""

    query: str = Field(..., min_length=1, max_length=500, description="Search query")
    limit: int = Field(default=10, ge=1, le=50, description="Max results to return")
    use_ml: bool = Field(default=True, description="Use ML service for recommendations")


class MovieResult(BaseModel):
    """Movie result with details from IMDB API."""

    id: str
    title: str
    url: Optional[str] = None
    year: Optional[int] = None
    image: Optional[str] = None
    rating: Optional[float] = None
    ratingVotes: Optional[int] = None
    type: Optional[str] = None
    # ML-specific fields (only present when use_ml=True)
    ltr_score: Optional[float] = None
    retrieval_score: Optional[float] = None
    sim_embedding: Optional[float] = None


class SearchResponse(BaseModel):
    """Search response to frontend."""

    query: str
    results: list[MovieResult]
    count: int
    source: str = Field(description="'ml' for ML service, 'imdb' for direct IMDB search")


class MLServiceRequest(BaseModel):
    """Request to ML service."""

    query: str
    top_k: int = 10


class MLServiceResponse(BaseModel):
    """Response from ML service."""

    movie_ids: list[str]
    results: list[dict]
    count: int


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    ml_service: str
    imdb_api: str
