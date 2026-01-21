"""Pydantic schemas for API request/response documentation."""

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    """Request schema for movie search endpoint."""

    query: str = Field(
        ...,
        description="Natural language search query for movie recommendations",
        examples=["action movies similar to the dark knight", "romantic comedies from the 90s"],
    )
    top_k: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Number of movie results to return",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "query": "sci-fi movies about time travel",
                    "top_k": 5,
                },
                {
                    "query": "action movies similar to the dark knight",
                },
            ]
        }
    }


class MovieResult(BaseModel):
    """Individual movie result with scores."""

    imdb_id: str = Field(
        ...,
        description="IMDB identifier (e.g., tt0468569)",
        examples=["tt0468569"],
    )
    title: str = Field(
        ...,
        description="Movie title",
        examples=["The Dark Knight"],
    )
    genres: str | None = Field(
        None,
        description="Comma-separated genres",
        examples=["Action,Crime,Drama"],
    )
    imdb_rating: float | None = Field(
        None,
        description="IMDB rating (0-10)",
        examples=[9.0],
    )
    ltr_score: float = Field(
        ...,
        description="Learning-to-Rank model score (higher = more relevant)",
        examples=[18.45],
    )
    retrieval_score: float = Field(
        ...,
        description="Qdrant hybrid search score",
        examples=[0.89],
    )
    sim_embedding: float = Field(
        ...,
        description="Cosine similarity between query and movie embeddings",
        examples=[0.92],
    )


class SearchResponse(BaseModel):
    """Response schema for movie search endpoint."""

    movie_ids: list[str] = Field(
        ...,
        description="List of IMDB IDs for quick access",
        examples=[["tt0468569", "tt1345836", "tt0372784"]],
    )
    results: list[MovieResult] = Field(
        ...,
        description="Full movie results with metadata and scores",
    )
    count: int = Field(
        ...,
        description="Number of results returned",
        examples=[10],
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "movie_ids": ["tt0468569", "tt1345836", "tt0372784"],
                "results": [
                    {
                        "imdb_id": "tt0468569",
                        "title": "The Dark Knight",
                        "genres": "Action,Crime,Drama",
                        "imdb_rating": 9.0,
                        "ltr_score": 18.45,
                        "retrieval_score": 0.89,
                        "sim_embedding": 0.92,
                    }
                ],
                "count": 3,
            }
        }
    }


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = Field(
        ...,
        description="API health status",
        examples=["ok"],
    )
