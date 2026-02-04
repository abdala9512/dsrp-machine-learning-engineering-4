#!/usr/bin/env python3
"""
Qdrant Initialization Script

Indexes the IMDB movie database into Qdrant for hybrid search.
Creates both dense vectors (embeddings) and sparse vectors (BM25-like).

Usage:
    python qdrant_init.py --data-path /path/to/movies.parquet
    python qdrant_init.py --force-reindex  # Re-index even if collection exists
"""

import argparse
import logging
import sys
from pathlib import Path

import polars as pl
from qdrant_client import QdrantClient, models
from sentence_transformers import SentenceTransformer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def tokenize_text(text: str) -> dict[int, float]:
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


def create_collection(
    client: QdrantClient,
    collection_name: str,
    embedding_dim: int = 384,
) -> None:
    """Create Qdrant collection with hybrid search support."""
    collections = [c.name for c in client.get_collections().collections]

    if collection_name in collections:
        logger.info(f"Collection '{collection_name}' already exists")
        return

    logger.info(f"Creating collection '{collection_name}'...")
    client.create_collection(
        collection_name=collection_name,
        vectors_config={
            "dense": models.VectorParams(
                size=embedding_dim,
                distance=models.Distance.COSINE,
            )
        },
        sparse_vectors_config={
            "bm25": models.SparseVectorParams(
                modifier=models.Modifier.IDF,
            )
        },
    )
    logger.info(f"Collection '{collection_name}' created")


def load_movies(data_path: str) -> pl.DataFrame:
    """Load and prepare the movies database."""
    logger.info(f"Loading movies from: {data_path}")

    movies_df = pl.read_parquet(data_path)

    # Add derived features if missing
    if "imdb_votes_log" not in movies_df.columns:
        movies_df = movies_df.with_columns([
            pl.col("imdb_votes").log1p().alias("imdb_votes_log"),
        ])

    # Create full text for embeddings
    if "full_text" not in movies_df.columns:
        movies_df = movies_df.with_columns([
            pl.concat_str(
                [pl.col("title"), pl.col("Plot")],
                separator=". ",
            )
            .fill_null("")
            .alias("full_text"),
        ])

    logger.info(f"Loaded {movies_df.height} movies")
    return movies_df


def index_movies(
    client: QdrantClient,
    collection_name: str,
    movies_df: pl.DataFrame,
    embedding_model: SentenceTransformer,
    batch_size: int = 500,
    force_reindex: bool = False,
) -> None:
    """Index movies into Qdrant with dense and sparse vectors."""
    collection_info = client.get_collection(collection_name)

    if collection_info.points_count > 0 and not force_reindex:
        logger.info(
            f"Collection already has {collection_info.points_count} points. "
            "Use --force-reindex to re-index."
        )
        return

    if force_reindex and collection_info.points_count > 0:
        logger.info(f"Deleting {collection_info.points_count} existing points...")
        # Delete all points by recreating the collection
        client.delete_collection(collection_name)
        create_collection(client, collection_name)

    logger.info(f"Indexing {movies_df.height} movies...")

    texts = movies_df["full_text"].to_list()
    imdb_ids = movies_df["imdb_id"].to_list()

    total_batches = (len(texts) + batch_size - 1) // batch_size

    for batch_idx in range(total_batches):
        start = batch_idx * batch_size
        end = min(start + batch_size, len(texts))

        batch_texts = texts[start:end]
        batch_ids = imdb_ids[start:end]

        # Generate dense embeddings
        dense_embeddings = embedding_model.encode(batch_texts, show_progress_bar=False)

        # Create points
        points = []
        for i, (text, imdb_id) in enumerate(zip(batch_texts, batch_ids)):
            sparse_tokens = tokenize_text(text)

            point = models.PointStruct(
                id=start + i,
                vector={
                    "dense": dense_embeddings[i].tolist(),
                    "bm25": models.SparseVector(
                        indices=list(sparse_tokens.keys()),
                        values=list(sparse_tokens.values()),
                    ),
                },
                payload={
                    "imdb_id": imdb_id,
                    "row_index": start + i,
                },
            )
            points.append(point)

        # Upsert batch
        client.upsert(collection_name=collection_name, points=points)

        if (batch_idx + 1) % 10 == 0 or batch_idx == total_batches - 1:
            logger.info(f"  Batch {batch_idx + 1}/{total_batches} completed")

    final_count = client.get_collection(collection_name).points_count
    logger.info(f"Indexing completed. Total points: {final_count}")


def verify_index(
    client: QdrantClient,
    collection_name: str,
    embedding_model: SentenceTransformer,
    movies_df: pl.DataFrame,
) -> bool:
    """Verify the index with a test search."""
    logger.info("Verifying index with test search...")

    test_query = "action movies like the dark knight"
    query_embedding = embedding_model.encode([test_query])[0].tolist()

    results = client.query_points(
        collection_name=collection_name,
        query=query_embedding,
        using="dense",
        limit=5,
        with_payload=True,
    )

    if not results.points:
        logger.error("Test search returned no results!")
        return False

    logger.info(f"Test query: '{test_query}'")
    logger.info(f"Results: {len(results.points)}")

    for hit in results.points:
        imdb_id = hit.payload["imdb_id"]
        movie = movies_df.filter(pl.col("imdb_id") == imdb_id)
        if not movie.is_empty():
            logger.info(f"  - {movie['title'][0]} (score: {hit.score:.4f})")

    logger.info("Index verification passed!")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Initialize Qdrant with movie data for hybrid search"
    )
    parser.add_argument(
        "--qdrant-url",
        default="http://localhost:6333",
        help="Qdrant server URL",
    )
    parser.add_argument(
        "--collection",
        default="imdb-movies-hybrid",
        help="Qdrant collection name",
    )
    parser.add_argument(
        "--data-path",
        required=True,
        help="Path to the movies parquet file",
    )
    parser.add_argument(
        "--embedding-model",
        default="sentence-transformers/all-MiniLM-L6-v2",
        help="Sentence transformer model name",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Batch size for indexing",
    )
    parser.add_argument(
        "--force-reindex",
        action="store_true",
        help="Force re-indexing even if collection has data",
    )

    args = parser.parse_args()

    # Validate data path
    data_path = Path(args.data_path)
    if not data_path.exists():
        logger.error(f"Data file not found: {data_path}")
        sys.exit(1)

    # Connect to Qdrant
    logger.info(f"Connecting to Qdrant at {args.qdrant_url}...")
    try:
        client = QdrantClient(args.qdrant_url, timeout=30)
        # Test connection
        client.get_collections()
        logger.info("Connected to Qdrant")
    except Exception as e:
        logger.error(f"Failed to connect to Qdrant: {e}")
        sys.exit(1)

    # Load embedding model
    logger.info(f"Loading embedding model: {args.embedding_model}...")
    embedding_model = SentenceTransformer(args.embedding_model)
    embedding_dim = embedding_model.get_sentence_embedding_dimension()
    logger.info(f"Embedding dimension: {embedding_dim}")

    # Create collection
    create_collection(client, args.collection, embedding_dim)

    # Load movies
    movies_df = load_movies(str(data_path))

    # Index movies
    index_movies(
        client=client,
        collection_name=args.collection,
        movies_df=movies_df,
        embedding_model=embedding_model,
        batch_size=args.batch_size,
        force_reindex=args.force_reindex,
    )

    # Verify
    if not verify_index(client, args.collection, embedding_model, movies_df):
        sys.exit(1)

    logger.info("Qdrant initialization completed successfully!")


if __name__ == "__main__":
    main()
