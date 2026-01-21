"""
Movie Recommendation API with LightGBM LTR model.

This package provides a real-time movie recommendation API using:
- Sentence Transformers for query embeddings
- Qdrant for hybrid search (dense + BM25)
- LightGBM LTR model for re-ranking
- Prometheus metrics for Grafana monitoring
"""

from .api import MovieRecommendationAPI, create_app, main
from .config import Config, config
from .search import MovieSearchPipeline, QdrantRetriever, MockRetriever

__version__ = "0.1.0"

__all__ = [
    "MovieRecommendationAPI",
    "MovieSearchPipeline",
    "QdrantRetriever",
    "MockRetriever",
    "Config",
    "config",
    "create_app",
    "main",
]
