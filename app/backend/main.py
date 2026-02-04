"""
Backend API for DSRP Movie Recommendations.

This API orchestrates the flow between:
- Frontend: Receives search queries
- ML Service: Gets movie recommendations based on LTR model
- IMDB API: Fetches detailed movie information

The backend can operate in two modes:
1. ML Mode (default): Query -> ML Service -> IMDB API -> Response
2. Direct Mode: Query -> IMDB API -> Response (fallback or when ML disabled)
"""

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST, REGISTRY

from config import get_settings, Settings
from schemas import SearchRequest, SearchResponse, HealthResponse, MovieResult
from services import MLServiceClient, IMDBApiClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# Prometheus metrics (handle reload gracefully)
def get_or_create_counter(name, description, labels):
    """Get existing counter or create new one."""
    try:
        return Counter(name, description, labels)
    except ValueError:
        # Already registered, get from registry
        return REGISTRY._names_to_collectors[name]


def get_or_create_histogram(name, description, labels=None, buckets=None):
    """Get existing histogram or create new one."""
    try:
        kwargs = {}
        if labels:
            kwargs["labelnames"] = labels
        if buckets:
            kwargs["buckets"] = buckets
        return Histogram(name, description, **kwargs)
    except ValueError:
        return REGISTRY._names_to_collectors[name]


REQUEST_COUNT = get_or_create_counter(
    "backend_requests_total",
    "Total backend requests",
    ["endpoint", "status", "source"],
)
REQUEST_LATENCY = get_or_create_histogram(
    "backend_request_latency_seconds",
    "Request latency in seconds",
    labels=["endpoint"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)
ML_SERVICE_LATENCY = get_or_create_histogram(
    "backend_ml_service_latency_seconds",
    "ML service call latency",
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
)
IMDB_API_LATENCY = get_or_create_histogram(
    "backend_imdb_api_latency_seconds",
    "IMDB API call latency",
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    settings = get_settings()
    logger.info(f"Starting backend API...")
    logger.info(f"ML Service URL: {settings.ml_service_url}")
    logger.info(f"IMDB API URL: {settings.imdb_api_url}")
    logger.info(f"ML Service Enabled: {settings.enable_ml_service}")
    yield
    logger.info("Shutting down backend API...")


app = FastAPI(
    title="DSRP Movie Recommendations Backend",
    description="""
## Backend API for Movie Recommendations

Orchestrates the flow between frontend, ML service, and IMDB API.

### Modes of Operation

1. **ML Mode** (default): Uses the ML service for intelligent recommendations
   - Query → ML Service (LTR ranking) → IMDB API (details) → Response

2. **Direct Mode**: Searches IMDB directly (fallback)
   - Query → IMDB API (search) → Response

### Configuration

Set `ENABLE_ML_SERVICE=false` to disable ML recommendations and use direct IMDB search.
""",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS middleware
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_ml_client() -> MLServiceClient:
    """Get ML service client."""
    return MLServiceClient(get_settings())


def get_imdb_client() -> IMDBApiClient:
    """Get IMDB API client."""
    return IMDBApiClient(get_settings())


@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    """Check health of backend and dependent services."""
    settings = get_settings()
    ml_client = get_ml_client()
    imdb_client = get_imdb_client()

    ml_healthy = await ml_client.health_check() if settings.enable_ml_service else True
    imdb_healthy = await imdb_client.health_check()

    return HealthResponse(
        status="healthy" if (ml_healthy or not settings.enable_ml_service) and imdb_healthy else "degraded",
        ml_service="healthy" if ml_healthy else ("disabled" if not settings.enable_ml_service else "unhealthy"),
        imdb_api="healthy" if imdb_healthy else "unhealthy",
    )


@app.post("/search", response_model=SearchResponse, tags=["Search"])
async def search_movies(request: SearchRequest):
    """
    Search for movies using ML recommendations or direct IMDB search.

    The search flow depends on the `use_ml` parameter and server configuration:

    1. If `use_ml=True` and ML service is enabled:
       - Call ML service to get ranked movie IDs
       - Fetch movie details from IMDB API
       - Return results with ML scores

    2. If `use_ml=False` or ML service is disabled:
       - Search IMDB API directly
       - Return basic search results
    """
    start_time = time.perf_counter()
    settings = get_settings()

    try:
        # Determine if we should use ML service
        use_ml = request.use_ml and settings.enable_ml_service

        if use_ml:
            results = await _search_with_ml(request.query, request.limit)
            source = "ml"
        else:
            results = await _search_direct(request.query, request.limit)
            source = "imdb"

        REQUEST_COUNT.labels(endpoint="/search", status="success", source=source).inc()

        return SearchResponse(
            query=request.query,
            results=results,
            count=len(results),
            source=source,
        )

    except Exception as e:
        REQUEST_COUNT.labels(endpoint="/search", status="error", source="unknown").inc()
        logger.error(f"Search error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        latency = time.perf_counter() - start_time
        REQUEST_LATENCY.labels(endpoint="/search").observe(latency)


@app.get("/search", response_model=SearchResponse, tags=["Search"])
async def search_movies_get(
    query: str = Query(..., min_length=1, max_length=500, description="Search query"),
    limit: int = Query(default=10, ge=1, le=50, description="Max results"),
    use_ml: bool = Query(default=True, description="Use ML service"),
):
    """GET endpoint for search (convenience for browser testing)."""
    return await search_movies(SearchRequest(query=query, limit=limit, use_ml=use_ml))


async def _search_with_ml(query: str, limit: int) -> list[MovieResult]:
    """Search using ML service + IMDB API."""
    ml_client = get_ml_client()
    imdb_client = get_imdb_client()

    # Step 1: Get recommendations from ML service
    ml_start = time.perf_counter()
    try:
        ml_results, movie_ids = await ml_client.search(query, top_k=limit)
    except Exception as e:
        logger.warning(f"ML service failed, falling back to direct search: {e}")
        return await _search_direct(query, limit)
    finally:
        ML_SERVICE_LATENCY.observe(time.perf_counter() - ml_start)

    if not movie_ids:
        logger.warning("ML service returned no results, falling back to direct search")
        return await _search_direct(query, limit)

    # Step 2: Fetch movie details from IMDB API
    imdb_start = time.perf_counter()
    try:
        results = await imdb_client.get_movies_by_ids(movie_ids, ml_results)
    finally:
        IMDB_API_LATENCY.observe(time.perf_counter() - imdb_start)

    # Preserve ML ranking order
    id_to_result = {r.id: r for r in results}
    ordered_results = [id_to_result[mid] for mid in movie_ids if mid in id_to_result]

    return ordered_results


async def _search_direct(query: str, limit: int) -> list[MovieResult]:
    """Search IMDB directly without ML service."""
    imdb_client = get_imdb_client()

    imdb_start = time.perf_counter()
    try:
        results = await imdb_client.search_titles(query, limit)
    finally:
        IMDB_API_LATENCY.observe(time.perf_counter() - imdb_start)

    return results[:limit]


@app.get("/movie/{movie_id}", response_model=MovieResult, tags=["Movies"])
async def get_movie(movie_id: str):
    """Get details for a specific movie by IMDB ID."""
    imdb_client = get_imdb_client()

    movie_data = await imdb_client.get_movie_by_id(movie_id)
    if not movie_data:
        raise HTTPException(status_code=404, detail=f"Movie {movie_id} not found")

    return imdb_client._parse_imdb_response(movie_id, movie_data)


@app.get("/metrics", tags=["Monitoring"])
async def metrics():
    """Prometheus metrics endpoint."""
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
