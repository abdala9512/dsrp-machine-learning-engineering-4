"""Prometheus metrics for the movie recommendation API."""

from prometheus_client import Counter, Histogram, Gauge, Info, Summary

# API Info
api_info = Info("movie_api", "Movie Recommendation API information")
api_info.info({
    "version": "0.1.0",
    "model": "LightGBM LTR",
})

# =============================================================================
# ML Quality Metrics
# =============================================================================

# nDCG (Normalized Discounted Cumulative Gain) - simulated since we can't
# measure true relevance at inference time. Uses random relevance scores.
NDCG_SCORE = Summary(
    "movie_api_ndcg_score",
    "Simulated nDCG@k score per request (random relevance for monitoring)",
)

NDCG_AT_K = Histogram(
    "movie_api_ndcg_at_k",
    "Distribution of simulated nDCG@k scores",
    buckets=[0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
)

# =============================================================================
# Feature Distribution Metrics (for Drift Detection)
# =============================================================================

# sim_embedding: cosine similarity between query and movie embeddings (0-1)
FEATURE_SIM_EMBEDDING = Histogram(
    "movie_api_feature_sim_embedding",
    "Distribution of sim_embedding feature (cosine similarity)",
    buckets=[0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
)

# imdb_rating: movie rating (0-10 scale)
FEATURE_IMDB_RATING = Histogram(
    "movie_api_feature_imdb_rating",
    "Distribution of imdb_rating feature",
    buckets=[0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0],
)

# imdb_votes_log: log-transformed vote count
FEATURE_IMDB_VOTES_LOG = Histogram(
    "movie_api_feature_imdb_votes_log",
    "Distribution of imdb_votes_log feature",
    buckets=[0.0, 2.0, 4.0, 6.0, 8.0, 10.0, 12.0, 14.0, 16.0],
)

# LTR model prediction scores (for output drift detection)
LTR_SCORE_DISTRIBUTION = Histogram(
    "movie_api_ltr_score",
    "Distribution of LTR model prediction scores",
    buckets=[-10.0, -5.0, -2.0, -1.0, 0.0, 1.0, 2.0, 5.0, 10.0, 20.0],
)

# =============================================================================
# Drift Detection Summary Statistics
# =============================================================================

FEATURE_SIM_EMBEDDING_MEAN = Gauge(
    "movie_api_feature_sim_embedding_mean",
    "Rolling mean of sim_embedding feature per request batch",
)

FEATURE_IMDB_RATING_MEAN = Gauge(
    "movie_api_feature_imdb_rating_mean",
    "Rolling mean of imdb_rating feature per request batch",
)

FEATURE_IMDB_VOTES_LOG_MEAN = Gauge(
    "movie_api_feature_imdb_votes_log_mean",
    "Rolling mean of imdb_votes_log feature per request batch",
)

LTR_SCORE_MEAN = Gauge(
    "movie_api_ltr_score_mean",
    "Rolling mean of LTR scores per request batch",
)

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
