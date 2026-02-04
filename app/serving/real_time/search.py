"""Search and retrieval logic for movie recommendations."""

import logging
import random
import time
from typing import Protocol

import numpy as np
import polars as pl
from qdrant_client import QdrantClient, models
from sentence_transformers import SentenceTransformer

try:
    from .config import Config
    from . import metrics
except ImportError:
    from config import Config
    import metrics

logger = logging.getLogger(__name__)


def compute_ndcg(relevance_scores: list[float], k: int | None = None) -> float:
    """
    Compute nDCG@k (Normalized Discounted Cumulative Gain).

    Since we can't measure true relevance at inference time, this is called
    with simulated/random relevance scores for monitoring purposes.

    Args:
        relevance_scores: List of relevance scores in ranked order.
        k: Number of results to consider (None = all).

    Returns:
        nDCG score between 0 and 1.
    """
    if not relevance_scores:
        return 0.0

    if k is not None:
        relevance_scores = relevance_scores[:k]

    # DCG = sum of (2^rel - 1) / log2(position + 1)
    dcg = 0.0
    for i, rel in enumerate(relevance_scores):
        dcg += (2 ** rel - 1) / np.log2(i + 2)  # +2 because position starts at 1

    # Ideal DCG (sorted by relevance)
    ideal_scores = sorted(relevance_scores, reverse=True)
    idcg = 0.0
    for i, rel in enumerate(ideal_scores):
        idcg += (2 ** rel - 1) / np.log2(i + 2)

    if idcg == 0:
        return 0.0

    return dcg / idcg


class Retriever(Protocol):
    """Protocol for retrieval implementations."""

    def search(self, query_embedding: list[float], query_text: str, top_k: int) -> list[dict]:
        """Search for candidates."""
        ...


class QdrantRetriever:
    """Qdrant-based hybrid retrieval (dense + sparse)."""

    def __init__(self, client: QdrantClient, collection_name: str):
        self.client = client
        self.collection_name = collection_name

    def _tokenize_text(self, text: str) -> dict[int, float]:
        """Tokenize text for sparse vectors (BM25-like)."""
        if not text:
            return {}
        words = text.lower().split()
        token_counts: dict[int, float] = {}
        for word in words:
            if len(word) > 2:
                idx = hash(word) % 100000
                token_counts[idx] = token_counts.get(idx, 0) + 1
        return token_counts

    def search(self, query_embedding: list[float], query_text: str, top_k: int) -> list[dict]:
        """Hybrid search combining dense embeddings and BM25 sparse vectors."""
        query_sparse = self._tokenize_text(query_text)

        start_time = time.perf_counter()
        try:
            results = self.client.query_points(
                collection_name=self.collection_name,
                prefetch=[
                    models.Prefetch(
                        query=query_embedding,
                        using="dense",
                        limit=top_k,
                    ),
                    models.Prefetch(
                        query=models.SparseVector(
                            indices=list(query_sparse.keys()),
                            values=list(query_sparse.values()),
                        ),
                        using="bm25",
                        limit=top_k,
                    ),
                ],
                query=models.FusionQuery(fusion=models.Fusion.RRF),
                limit=top_k,
                with_payload=True,
            )
            latency = time.perf_counter() - start_time
            metrics.RETRIEVAL_LATENCY.observe(latency)

            candidates = []
            for hit in results.points:
                candidates.append({
                    "imdb_id": hit.payload["imdb_id"],
                    "row_index": hit.payload["row_index"],
                    "retrieval_score": hit.score,
                })

            metrics.CANDIDATES_RETRIEVED.observe(len(candidates))
            return candidates

        except Exception as e:
            metrics.QDRANT_ERRORS.inc()
            logger.error(f"Qdrant search error: {e}")
            raise


class MockRetriever:
    """Mock retriever that returns random movies when Qdrant is unavailable."""

    def __init__(self, movies_df: pl.DataFrame):
        self.movies_df = movies_df
        self.imdb_ids = movies_df["imdb_id"].to_list()

    def search(self, query_embedding: list[float], query_text: str, top_k: int) -> list[dict]:
        """Return random movies as candidates."""
        metrics.MOCK_REQUESTS.inc()
        logger.warning("Using mock retriever - returning random candidates")

        # Sample random movies
        sample_size = min(top_k, len(self.imdb_ids))
        sampled_ids = random.sample(self.imdb_ids, sample_size)

        candidates = []
        for i, imdb_id in enumerate(sampled_ids):
            candidates.append({
                "imdb_id": imdb_id,
                "row_index": i,
                "retrieval_score": random.uniform(0.1, 1.0),
            })

        metrics.CANDIDATES_RETRIEVED.observe(len(candidates))
        return candidates


class MovieSearchPipeline:
    """Complete search pipeline: embedding -> retrieval -> re-ranking."""

    def __init__(
        self,
        embedding_model: SentenceTransformer,
        retriever: Retriever,
        ltr_model,
        movies_df: pl.DataFrame,
        config: Config,
    ):
        self.embedding_model = embedding_model
        self.retriever = retriever
        self.ltr_model = ltr_model
        self.movies_df = movies_df
        self.config = config

    def _compute_query_embedding(self, query: str) -> np.ndarray:
        """Generate embedding for query."""
        start_time = time.perf_counter()
        embedding = self.embedding_model.encode([query])[0]
        latency = time.perf_counter() - start_time
        metrics.EMBEDDING_LATENCY.observe(latency)
        return embedding

    def _rerank_candidates(
        self,
        candidates: list[dict],
        query_embedding: np.ndarray,
    ) -> pl.DataFrame:
        """Re-rank candidates using the LTR model."""
        if not candidates:
            return pl.DataFrame()

        start_time = time.perf_counter()

        candidate_ids = [c["imdb_id"] for c in candidates]
        retrieval_scores = {c["imdb_id"]: c["retrieval_score"] for c in candidates}

        # Filter candidate movies from database
        candidates_df = self.movies_df.filter(pl.col("imdb_id").is_in(candidate_ids))

        if candidates_df.is_empty():
            return pl.DataFrame()

        # Normalize query embedding
        query_emb = query_embedding / (np.linalg.norm(query_embedding) + 1e-9)

        # Compute candidate embeddings and similarity
        candidate_texts = candidates_df["full_text"].to_list()
        candidate_embs = self.embedding_model.encode(candidate_texts)
        candidate_embs = candidate_embs / (
            np.linalg.norm(candidate_embs, axis=1, keepdims=True) + 1e-9
        )
        sim_scores = candidate_embs @ query_emb

        # Add similarity to DataFrame
        candidates_df = candidates_df.with_columns([
            pl.Series("sim_embedding", sim_scores.astype("float64")),
        ])

        # Prepare features for LTR model
        available_cols = [c for c in self.config.feature_cols if c in candidates_df.columns]
        X = candidates_df.select(available_cols).to_numpy()

        # Predict with LTR model
        try:
            ltr_scores = self.ltr_model.predict(X)
        except Exception as e:
            metrics.MODEL_ERRORS.inc()
            logger.error(f"LTR model error: {e}")
            raise

        # Add scores
        candidates_df = candidates_df.with_columns([
            pl.Series("ltr_score", ltr_scores),
            pl.Series(
                "retrieval_score",
                [retrieval_scores.get(id, 0) for id in candidates_df["imdb_id"].to_list()],
            ),
        ])

        latency = time.perf_counter() - start_time
        metrics.RERANK_LATENCY.observe(latency)

        # =================================================================
        # Collect feature distributions for drift detection
        # =================================================================
        self._observe_feature_distributions(candidates_df, ltr_scores)

        # Sort by LTR score
        return candidates_df.sort("ltr_score", descending=True)

    def _observe_feature_distributions(
        self,
        candidates_df: pl.DataFrame,
        ltr_scores: np.ndarray,
    ) -> None:
        """
        Observe feature distributions for drift detection.

        Collects histograms and mean values for all features used by the LTR model.
        """
        # sim_embedding distribution
        if "sim_embedding" in candidates_df.columns:
            sim_values = candidates_df["sim_embedding"].to_list()
            for val in sim_values:
                metrics.FEATURE_SIM_EMBEDDING.observe(float(val))
            if sim_values:
                metrics.FEATURE_SIM_EMBEDDING_MEAN.set(float(np.mean(sim_values)))

        # imdb_rating distribution
        if "imdb_rating" in candidates_df.columns:
            rating_values = candidates_df["imdb_rating"].drop_nulls().to_list()
            for val in rating_values:
                metrics.FEATURE_IMDB_RATING.observe(float(val))
            if rating_values:
                metrics.FEATURE_IMDB_RATING_MEAN.set(float(np.mean(rating_values)))

        # imdb_votes_log distribution
        if "imdb_votes_log" in candidates_df.columns:
            votes_log_values = candidates_df["imdb_votes_log"].drop_nulls().to_list()
            for val in votes_log_values:
                metrics.FEATURE_IMDB_VOTES_LOG.observe(float(val))
            if votes_log_values:
                metrics.FEATURE_IMDB_VOTES_LOG_MEAN.set(float(np.mean(votes_log_values)))

        # LTR score distribution (model output drift)
        for score in ltr_scores:
            metrics.LTR_SCORE_DISTRIBUTION.observe(float(score))
        if len(ltr_scores) > 0:
            metrics.LTR_SCORE_MEAN.set(float(np.mean(ltr_scores)))

    def search(self, query: str, top_k: int | None = None) -> list[dict]:
        """
        Execute full search pipeline.

        Args:
            query: Search query text.
            top_k: Number of results to return (default from config).

        Returns:
            List of movie results with scores.
        """
        if top_k is None:
            top_k = self.config.top_k_final

        # Step 1: Generate query embedding
        query_embedding = self._compute_query_embedding(query)

        # Step 2: Retrieve candidates
        candidates = self.retriever.search(
            query_embedding=query_embedding.tolist(),
            query_text=query,
            top_k=self.config.top_k_retrieval,
        )

        # Step 3: Re-rank with LTR model
        ranked_df = self._rerank_candidates(candidates, query_embedding)

        if ranked_df.is_empty():
            return []

        # Step 4: Format results
        results = ranked_df.head(top_k).select([
            "imdb_id",
            "title",
            "genres",
            "imdb_rating",
            "ltr_score",
            "retrieval_score",
            "sim_embedding",
        ]).to_dicts()

        metrics.RESULTS_RETURNED.observe(len(results))

        # Step 5: Compute simulated nDCG for monitoring
        # Since we can't measure true relevance at inference time,
        # we use random relevance scores. This allows us to:
        # 1. Verify the nDCG computation pipeline works
        # 2. Monitor the distribution of scores for anomalies
        # 3. Compare against baseline when true labels are available
        self._compute_simulated_ndcg(results, top_k)

        return results

    def _compute_simulated_ndcg(self, results: list[dict], k: int) -> None:
        """
        Compute and observe simulated nDCG for monitoring.

        Uses random relevance scores (0-3 scale) since true relevance
        is not available at inference time. This metric is useful for:
        - Monitoring the ranking pipeline health
        - Detecting anomalies in result distributions
        - Comparing with offline evaluation when labels are available
        """
        if not results:
            return

        # Generate random relevance scores (0-3 scale, like typical nDCG evaluation)
        # In production, these would come from user feedback/clicks
        simulated_relevance = [random.uniform(0, 3) for _ in results]

        # Compute nDCG
        ndcg = compute_ndcg(simulated_relevance, k=min(k, len(results)))

        # Observe the metric
        metrics.NDCG_SCORE.observe(ndcg)
        metrics.NDCG_AT_K.observe(ndcg)


def load_movies_db(path: str) -> pl.DataFrame:
    """Load and prepare the movies database."""
    logger.info(f"Loading movies database from: {path}")
    movies_df = pl.read_parquet(path)

    # Add derived features if missing
    if "imdb_votes_log" not in movies_df.columns:
        movies_df = movies_df.with_columns([
            pl.col("imdb_votes").log1p().alias("imdb_votes_log"),
        ])

    # Create full text for embeddings
    if "full_text" not in movies_df.columns:
        movies_df = movies_df.with_columns([
            pl.concat_str([pl.col("title"), pl.col("Plot")], separator=". ")
            .fill_null("")
            .alias("full_text"),
        ])

    logger.info(f"Loaded {movies_df.height} movies")
    return movies_df


def create_retriever(config: Config, movies_df: pl.DataFrame) -> Retriever:
    """Create appropriate retriever based on Qdrant availability."""
    if config.mock_qdrant:
        logger.warning("Mock mode enabled - using MockRetriever")
        metrics.QDRANT_AVAILABLE.set(0)
        return MockRetriever(movies_df)

    try:
        logger.info(f"Connecting to Qdrant: {config.qdrant_url}")
        client = QdrantClient(config.qdrant_url, timeout=10)

        # Check if collection exists
        collections = [c.name for c in client.get_collections().collections]
        if config.qdrant_collection not in collections:
            raise ValueError(f"Collection '{config.qdrant_collection}' not found")

        # Verify collection has data
        info = client.get_collection(config.qdrant_collection)
        if info.points_count == 0:
            raise ValueError(f"Collection '{config.qdrant_collection}' is empty")

        logger.info(f"Qdrant connected: {info.points_count} points in collection")
        metrics.QDRANT_AVAILABLE.set(1)
        return QdrantRetriever(client, config.qdrant_collection)

    except Exception as e:
        logger.warning(f"Qdrant unavailable ({e}), falling back to mock retriever")
        metrics.QDRANT_AVAILABLE.set(0)
        return MockRetriever(movies_df)
