"""Core functions for batch serving pipeline."""

import numpy as np
import polars as pl
from qdrant_client import QdrantClient, models
from sentence_transformers import SentenceTransformer


def tokenize_text(text: str) -> dict[int, float]:
    """
    Tokenize text for sparse vectors (BM25-like).

    Args:
        text: Input text to tokenize.

    Returns:
        Dictionary mapping token indices to counts.
    """
    if not text:
        return {}

    words = text.lower().split()
    token_counts: dict[int, float] = {}
    for word in words:
        if len(word) > 2:
            idx = hash(word) % 100000
            token_counts[idx] = token_counts.get(idx, 0) + 1

    return token_counts


def hybrid_search(
    query: str,
    client: QdrantClient,
    collection_name: str,
    embedding_model: SentenceTransformer,
    top_k: int = 100,
) -> list[dict]:
    """
    Hybrid search combining dense embeddings and BM25 sparse vectors.

    Args:
        query: Search text.
        client: Qdrant client.
        collection_name: Name of the collection.
        embedding_model: Sentence transformer model for embeddings.
        top_k: Number of results to return.

    Returns:
        List of candidates with imdb_id, row_index, and retrieval_score.
    """
    # Generate query embedding
    query_embedding = embedding_model.encode([query])[0].tolist()

    # Tokenize query for BM25
    query_sparse = tokenize_text(query)

    # Hybrid search using prefetch and RRF (Reciprocal Rank Fusion)
    results = client.query_points(
        collection_name=collection_name,
        prefetch=[
            # Dense search (semantic)
            models.Prefetch(
                query=query_embedding,
                using="dense",
                limit=top_k,
            ),
            # Sparse search (BM25-like)
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

    # Extract results
    candidates = []
    for hit in results.points:
        candidates.append(
            {
                "imdb_id": hit.payload["imdb_id"],
                "row_index": hit.payload["row_index"],
                "retrieval_score": hit.score,
            }
        )

    return candidates


def semantic_search_only(
    query: str,
    client: QdrantClient,
    collection_name: str,
    embedding_model: SentenceTransformer,
    top_k: int = 100,
) -> list[dict]:
    """
    Search using only dense embeddings.

    Args:
        query: Search text.
        client: Qdrant client.
        collection_name: Name of the collection.
        embedding_model: Sentence transformer model for embeddings.
        top_k: Number of results to return.

    Returns:
        List of candidates with imdb_id, row_index, and retrieval_score.
    """
    query_embedding = embedding_model.encode([query])[0].tolist()

    results = client.query_points(
        collection_name=collection_name,
        query=query_embedding,
        using="dense",
        limit=top_k,
        with_payload=True,
    )

    candidates = []
    for hit in results.points:
        candidates.append(
            {
                "imdb_id": hit.payload["imdb_id"],
                "row_index": hit.payload["row_index"],
                "retrieval_score": hit.score,
            }
        )

    return candidates


def rerank_candidates(
    candidates: list[dict],
    query: str,
    movies_df: pl.DataFrame,
    embedding_model: SentenceTransformer,
    ltr_model,
    feature_cols: list[str],
    top_k: int = 10,
) -> pl.DataFrame:
    """
    Re-rank candidates using the LTR model.

    Args:
        candidates: List of candidates from retrieval.
        query: Original query.
        movies_df: DataFrame with movie information.
        embedding_model: Sentence transformer model.
        ltr_model: LTR model from MLflow.
        feature_cols: Feature columns for the model.
        top_k: Number of final results.

    Returns:
        DataFrame with ranked results.
    """
    if not candidates:
        return pl.DataFrame()

    # Get candidate IDs
    candidate_ids = [c["imdb_id"] for c in candidates]
    retrieval_scores = {c["imdb_id"]: c["retrieval_score"] for c in candidates}

    # Filter candidate movies
    candidates_df = movies_df.filter(pl.col("imdb_id").is_in(candidate_ids))

    if candidates_df.is_empty():
        return pl.DataFrame()

    # Calculate query-document embedding similarity
    query_emb = embedding_model.encode([query])[0]
    query_emb = query_emb / (np.linalg.norm(query_emb) + 1e-9)

    # Calculate candidate embeddings and similarity
    candidate_texts = candidates_df["full_text"].to_list()
    candidate_embs = embedding_model.encode(candidate_texts)
    candidate_embs = candidate_embs / (
        np.linalg.norm(candidate_embs, axis=1, keepdims=True) + 1e-9
    )

    sim_scores = candidate_embs @ query_emb

    # Add similarity to DataFrame
    candidates_df = candidates_df.with_columns(
        [
            pl.Series("sim_embedding", sim_scores.astype("float64")),
        ]
    )

    # Prepare features for the model
    available_cols = [c for c in feature_cols if c in candidates_df.columns]
    X = candidates_df.select(available_cols).to_numpy()

    # Predict scores with LTR model
    ltr_scores = ltr_model.predict(X)

    # Add scores to DataFrame
    candidates_df = candidates_df.with_columns(
        [
            pl.Series("ltr_score", ltr_scores),
            pl.Series(
                "retrieval_score",
                [
                    retrieval_scores.get(id, 0)
                    for id in candidates_df["imdb_id"].to_list()
                ],
            ),
        ]
    )

    # Sort by LTR score
    results = candidates_df.sort("ltr_score", descending=True).head(top_k)

    return results


def search_pipeline(
    query: str,
    client: QdrantClient,
    collection_name: str,
    embedding_model: SentenceTransformer,
    ltr_model,
    movies_df: pl.DataFrame,
    feature_cols: list[str],
    top_k_retrieval: int = 100,
    top_k_final: int = 10,
    use_hybrid: bool = True,
) -> pl.DataFrame:
    """
    Complete search pipeline: Retrieval + Re-ranking.

    Args:
        query: Search text.
        client: Qdrant client.
        collection_name: Name of the collection.
        embedding_model: Sentence transformer model.
        ltr_model: LTR model from MLflow.
        movies_df: DataFrame with movie information.
        feature_cols: Feature columns for the model.
        top_k_retrieval: Number of candidates from retrieval.
        top_k_final: Number of final results.
        use_hybrid: If True, use hybrid search (embeddings + BM25).

    Returns:
        DataFrame with ranked results.
    """
    # Step 1: Retrieval
    if use_hybrid:
        candidates = hybrid_search(
            query=query,
            client=client,
            collection_name=collection_name,
            embedding_model=embedding_model,
            top_k=top_k_retrieval,
        )
    else:
        candidates = semantic_search_only(
            query=query,
            client=client,
            collection_name=collection_name,
            embedding_model=embedding_model,
            top_k=top_k_retrieval,
        )

    # Step 2: Re-ranking
    results = rerank_candidates(
        candidates=candidates,
        query=query,
        movies_df=movies_df,
        embedding_model=embedding_model,
        ltr_model=ltr_model,
        feature_cols=feature_cols,
        top_k=top_k_final,
    )

    return results


def load_movies_db(path: str) -> pl.DataFrame:
    """
    Load and prepare the movies database.

    Args:
        path: Path to the parquet file.

    Returns:
        DataFrame with prepared movie data.
    """
    movies_db = pl.read_parquet(path)

    # Add derived features
    if "imdb_votes_log" not in movies_db.columns:
        movies_db = movies_db.with_columns(
            [
                pl.col("imdb_votes").log1p().alias("imdb_votes_log"),
            ]
        )

    # Create full text for embeddings
    movies_db = movies_db.with_columns(
        [
            pl.concat_str(
                [pl.col("title"), pl.col("Plot")],
                separator=". ",
            )
            .fill_null("")
            .alias("full_text"),
        ]
    )

    return movies_db
