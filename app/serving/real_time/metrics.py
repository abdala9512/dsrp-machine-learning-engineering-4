"""Prometheus metrics for the movie recommendation API."""

from prometheus_client import Counter, Histogram, Gauge, Info

# API Info
api_info = Info("movie_api", "Movie Recommendation API information")
api_info.info({
    "version": "0.1.0",
    "model": "LightGBM LTR",
})

# Request metrics
REQUEST_COUNT = Counter(
    "movie_api_requests_total",
    "Total number of API requests",
    ["endpoint", "status"],
)

REQUEST_LATENCY = Histogram(
    "movie_api_request_latency_seconds",
    "Request latency in seconds",
    ["endpoint"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

# Search pipeline metrics
RETRIEVAL_LATENCY = Histogram(
    "movie_api_retrieval_latency_seconds",
    "Qdrant retrieval latency in seconds",
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0],
)

RERANK_LATENCY = Histogram(
    "movie_api_rerank_latency_seconds",
    "LTR re-ranking latency in seconds",
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0],
)

EMBEDDING_LATENCY = Histogram(
    "movie_api_embedding_latency_seconds",
    "Embedding generation latency in seconds",
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5],
)

# Result metrics
CANDIDATES_RETRIEVED = Histogram(
    "movie_api_candidates_retrieved",
    "Number of candidates retrieved from Qdrant",
    buckets=[10, 25, 50, 75, 100, 150, 200],
)

RESULTS_RETURNED = Histogram(
    "movie_api_results_returned",
    "Number of results returned to client",
    buckets=[1, 5, 10, 15, 20, 25, 50],
)

# Component status
QDRANT_AVAILABLE = Gauge(
    "movie_api_qdrant_available",
    "Whether Qdrant is available (1=yes, 0=no/mock)",
)

MODEL_LOADED = Gauge(
    "movie_api_model_loaded",
    "Whether the LTR model is loaded (1=yes, 0=no)",
)

EMBEDDING_MODEL_LOADED = Gauge(
    "movie_api_embedding_model_loaded",
    "Whether the embedding model is loaded (1=yes, 0=no)",
)

# Error metrics
QDRANT_ERRORS = Counter(
    "movie_api_qdrant_errors_total",
    "Total number of Qdrant errors",
)

MODEL_ERRORS = Counter(
    "movie_api_model_errors_total",
    "Total number of model inference errors",
)

MOCK_REQUESTS = Counter(
    "movie_api_mock_requests_total",
    "Total number of requests served with mock data",
)
