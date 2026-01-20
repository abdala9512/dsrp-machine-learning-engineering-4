"""
DSRP ML Utils - Utility library for ML pipelines.
DSRP - Machine Learning Engineering Course
"""

from dsrp_ml_utils.ml_utils import (
    # Constants
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_TOP_K_CANDIDATES,
    DEFAULT_N_LABEL_BINS,
    # Data loading
    load_imdb_database,
    add_derived_features,
    # Metadata extraction
    extract_top_genres,
    extract_decades,
    # Query generation
    generate_template_queries,
    # Candidate retrieval
    normalize_embeddings,
    get_candidates_for_query,
    # Relevance scoring
    compute_relevance_score,
    assign_relevance_labels,
    # MLflow utilities
    search_best_model,
    get_artifact_uri_production,
)

from dsrp_ml_utils.storage import (
    get_blob_service_client,
    upload_to_blob,
    download_from_blob,
    blob_exists,
    list_blobs,
    sync_to_azure,
    sync_from_azure,
)

__version__ = "0.1.0"

__all__ = [
    # Constants
    "DEFAULT_EMBEDDING_MODEL",
    "DEFAULT_TOP_K_CANDIDATES",
    "DEFAULT_N_LABEL_BINS",
    # Data loading
    "load_imdb_database",
    "add_derived_features",
    # Metadata extraction
    "extract_top_genres",
    "extract_decades",
    # Query generation
    "generate_template_queries",
    # Candidate retrieval
    "normalize_embeddings",
    "get_candidates_for_query",
    # Relevance scoring
    "compute_relevance_score",
    "assign_relevance_labels",
    # MLflow utilities
    "search_best_model",
    "get_artifact_uri_production",
    # Storage utilities
    "get_blob_service_client",
    "upload_to_blob",
    "download_from_blob",
    "blob_exists",
    "list_blobs",
    "sync_to_azure",
    "sync_from_azure",
]
