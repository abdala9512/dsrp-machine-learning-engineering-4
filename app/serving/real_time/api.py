"""
Movie Recommendation API using Lightning AI LitServe.

This API provides movie recommendations using:
- Sentence Transformers for query embeddings
- Qdrant for hybrid search (dense + BM25)
- LightGBM LTR model for re-ranking
- Prometheus metrics for Grafana monitoring
"""

import logging
import time
import os
import litserve as ls
import mlflow
from fastapi import Response
from prometheus_client import multiprocess, generate_latest, CONTENT_TYPE_LATEST, CollectorRegistry
from sentence_transformers import SentenceTransformer

try:
    from .config import config
    from . import metrics
    from .search import (
        MovieSearchPipeline,
        create_retriever,
        load_movies_db,
    )
    from .schemas import SearchRequest
except ImportError:
    from config import config
    import metrics
    from search import (
        MovieSearchPipeline,
        create_retriever,
        load_movies_db,
    )
    from schemas import SearchRequest

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class MovieRecommendationAPI(ls.LitAPI):
    """LitServe API for movie recommendations."""

    def setup(self, device: str) -> None:
        """Initialize all components."""
        logger.info("Initializing Movie Recommendation API...")

        # Validate token
        if not config.dagshub_token:
            raise ValueError(
                "DAGSHUB_USER_TOKEN environment variable is required. "
                "Get your token at: https://dagshub.com/user/settings/tokens"
            )

        # Load movies database
        self.movies_df = load_movies_db(config.movies_db_path)

        # Load embedding model
        logger.info(f"Loading embedding model: {config.embedding_model}")
        self.embedding_model = SentenceTransformer(config.embedding_model)
        metrics.EMBEDDING_MODEL_LOADED.set(1)
        logger.info("Embedding model loaded")

        # Load LTR model from MLflow
        logger.info(f"Loading LTR model: {config.ltr_model_uri}")
        try:
            self.ltr_model = mlflow.lightgbm.load_model(config.ltr_model_uri)
            metrics.MODEL_LOADED.set(1)
            logger.info("LTR model loaded successfully")
        except Exception as e:
            logger.warning(f"Error loading model with alias: {e}")
            fallback_uri = f"models:/{config.ltr_model_name}/latest"
            self.ltr_model = mlflow.lightgbm.load_model(fallback_uri)
            metrics.MODEL_LOADED.set(1)
            logger.info("LTR model (latest) loaded")

        # Create retriever (Qdrant or mock)
        self.retriever = create_retriever(config, self.movies_df)

        # Create search pipeline
        self.pipeline = MovieSearchPipeline(
            embedding_model=self.embedding_model,
            retriever=self.retriever,
            ltr_model=self.ltr_model,
            movies_df=self.movies_df,
            config=config,
        )

        logger.info("Movie Recommendation API initialized")

    def decode_request(self, request: dict) -> SearchRequest:
        """
        Decode and validate incoming request.

        Args:
            request: Raw request dict with 'query' and optional 'top_k'.

        Returns:
            Validated SearchRequest object.
        """
        return SearchRequest(
            query=request.get("query", ""),
            top_k=request.get("top_k", config.top_k_final),
        )

    def predict(self, request: SearchRequest) -> list[dict]:
        """
        Execute movie search pipeline.

        Args:
            request: Validated search request with query and top_k.

        Returns:
            List of movie results with scores.
        """
        if not request.query:
            return []

        start_time = time.perf_counter()
        try:
            results = self.pipeline.search(query=request.query, top_k=request.top_k)
            metrics.REQUEST_COUNT.labels(endpoint="/predict", status="success").inc()
            return results
        except Exception as e:
            metrics.REQUEST_COUNT.labels(endpoint="/predict", status="error").inc()
            logger.error(f"Search error: {e}")
            raise
        finally:
            latency = time.perf_counter() - start_time
            metrics.REQUEST_LATENCY.labels(endpoint="/predict").observe(latency)

    def encode_response(self, results: list[dict]) -> dict:
        """Format response."""
        # Extract just movie IDs for simple response
        movie_ids = [r["imdb_id"] for r in results]

        return {
            "movie_ids": movie_ids,
            "results": results,
            "count": len(results),
        }


def create_app():
    """Create the LitServe application."""
    server = ls.LitServer(
        MovieRecommendationAPI(),
        accelerator="auto",
        workers_per_device=config.workers,
        api_path="/predict",
    )

    # Customize OpenAPI documentation
    server.app.title = "Movie Recommendation API"
    server.app.description = """
## Movie Recommendation API

Search for movie recommendations using natural language queries.

### Pipeline
1. **Query Embedding**: Convert query to vector using SentenceTransformer
2. **Hybrid Search**: Retrieve candidates from Qdrant (dense + BM25)
3. **LTR Re-ranking**: Score candidates with LightGBM ranker

### Request Format
```json
{
    "query": "action movies similar to the dark knight",
    "top_k": 10
}
```

### Response Format
```json
{
    "movie_ids": ["tt0468569", "tt1345836"],
    "results": [
        {
            "imdb_id": "tt0468569",
            "title": "The Dark Knight",
            "genres": "Action,Crime,Drama",
            "imdb_rating": 9.0,
            "ltr_score": 18.45,
            "retrieval_score": 0.89,
            "sim_embedding": 0.92
        }
    ],
    "count": 2
}
```

### Parameters
| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `query` | string | Yes | - | Natural language search query |
| `top_k` | int | No | 10 | Number of results (1-100) |
"""
    server.app.version = "0.1.0"

    # Add Prometheus metrics endpoint
    @server.app.get("/metrics", tags=["Monitoring"])
    async def get_metrics():
        """Prometheus metrics endpoint for Grafana integration."""
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
        data = generate_latest(registry)
        return Response(
            content=data,
            media_type=CONTENT_TYPE_LATEST,
        )

    return server


def main():
    """Run the API server."""
    metrics_dir = "prometheus_multiproc_dir"
    if os.path.exists(metrics_dir):
        shutil.rmtree(metrics_dir)
    os.makedirs(metrics_dir)
    os.environ["PROMETHEUS_MULTIPROC_DIR"] = metrics_dir
    logger.info(f"Starting server on {config.host}:{config.port}")
    server = create_app()
    server.run(port=config.port, host=config.host, generate_client_file=False)


if __name__ == "__main__":
    main()
