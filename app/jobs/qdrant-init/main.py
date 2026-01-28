"""
Qdrant Initialization Job

This script initializes Qdrant with the IMDB movies collection for hybrid search.
It downloads data from Azure Blob Storage, creates embeddings, and indexes into Qdrant.

Environment Variables:
  QDRANT_URL: Qdrant server URL (default: http://qdrant:80)
  COLLECTION_NAME: Collection name (default: imdb-movies-hybrid)
  AZURE_STORAGE_CONNECTION_STRING: Azure Blob Storage connection string
  AZURE_CONTAINER_NAME: Container name (default: ml-pipeline-data)
  BLOB_PATH: Path to parquet file in container
  EMBEDDING_MODEL: Sentence transformer model (default: sentence-transformers/all-MiniLM-L6-v2)
  BATCH_SIZE: Batch size for indexing (default: 500)
  FORCE_REINDEX: Force reindex even if collection has data (default: false)
"""

import os
import sys
from io import BytesIO

import polars as pl
from loguru import logger
from qdrant_client import QdrantClient, models
from sentence_transformers import SentenceTransformer

# =============================================================================
# Configuration
# =============================================================================

QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:80")
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "imdb-movies-hybrid")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
EMBEDDING_DIM = 384
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "500"))
FORCE_REINDEX = os.getenv("FORCE_REINDEX", "false").lower() == "true"

# Azure Storage
AZURE_CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING", "")
AZURE_CONTAINER_NAME = os.getenv("AZURE_CONTAINER_NAME", "ml-pipeline-data")
BLOB_PATH = os.getenv("BLOB_PATH", "airflow-prod/complete_imdb_database.parquet")


# =============================================================================
# Utility Functions
# =============================================================================

def tokenize_text(text: str) -> dict:
    """Tokenize text for sparse vectors (BM25-like)."""
    if not text:
        return {}

    words = text.lower().split()
    token_counts = {}
    for word in words:
        if len(word) > 2:
            idx = hash(word) % 100000
            token_counts[idx] = token_counts.get(idx, 0) + 1

    return token_counts


def load_movies_from_azure() -> pl.DataFrame:
    """Load movies database from Azure Blob Storage."""
    from azure.storage.blob import BlobServiceClient

    logger.info(f"Loading data from Azure Blob Storage: {AZURE_CONTAINER_NAME}/{BLOB_PATH}")

    blob_service_client = BlobServiceClient.from_connection_string(AZURE_CONNECTION_STRING)
    blob_client = blob_service_client.get_blob_client(
        container=AZURE_CONTAINER_NAME,
        blob=BLOB_PATH
    )

    data = blob_client.download_blob().readall()
    movies_db = pl.read_parquet(BytesIO(data))

    logger.info(f"Loaded {movies_db.height} movies from Azure")
    return movies_db


def prepare_movies_data(movies_db: pl.DataFrame) -> pl.DataFrame:
    """Prepare movies data with derived features and full text."""
    # Add derived features
    if "imdb_votes_log" not in movies_db.columns:
        movies_db = movies_db.with_columns([
            pl.col("imdb_votes").log1p().alias("imdb_votes_log"),
        ])

    # Create full text for embeddings
    movies_db = movies_db.with_columns([
        pl.concat_str(
            [pl.col("title"), pl.col("Plot")],
            separator=". ",
        ).fill_null("").alias("full_text"),
    ])

    return movies_db


def create_collection(client: QdrantClient) -> bool:
    """Create Qdrant collection for hybrid search."""
    collections = [c.name for c in client.get_collections().collections]
    logger.info(f"Existing collections: {collections}")

    if COLLECTION_NAME not in collections:
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config={
                "dense": models.VectorParams(
                    size=EMBEDDING_DIM,
                    distance=models.Distance.COSINE
                )
            },
            sparse_vectors_config={
                "bm25": models.SparseVectorParams(
                    modifier=models.Modifier.IDF,
                )
            }
        )
        logger.info(f"Collection '{COLLECTION_NAME}' created with dense and sparse vectors")
        return True
    else:
        logger.info(f"Collection '{COLLECTION_NAME}' already exists")
        return False


def index_movies(client: QdrantClient, movies_db: pl.DataFrame, embedding_model: SentenceTransformer):
    """Index movies to Qdrant with embeddings and BM25 vectors."""
    collection_info = client.get_collection(COLLECTION_NAME)
    current_count = collection_info.points_count

    if current_count > 0 and not FORCE_REINDEX:
        logger.info(f"Collection already has {current_count} points. Skipping indexing.")
        logger.info("Set FORCE_REINDEX=true to re-index.")
        return current_count

    if current_count > 0:
        logger.info(f"Clearing {current_count} existing points...")
        client.delete(
            collection_name=COLLECTION_NAME,
            points_selector=models.FilterSelector(
                filter=models.Filter(must=[])
            )
        )

    texts = movies_db["full_text"].to_list()
    imdb_ids = movies_db["imdb_id"].to_list()

    total_batches = (len(texts) + BATCH_SIZE - 1) // BATCH_SIZE
    logger.info(f"Indexing {len(texts)} movies in {total_batches} batches...")

    for batch_idx in range(total_batches):
        start = batch_idx * BATCH_SIZE
        end = min(start + BATCH_SIZE, len(texts))

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
                        values=list(sparse_tokens.values())
                    )
                },
                payload={
                    "imdb_id": imdb_id,
                    "row_index": start + i,
                }
            )
            points.append(point)

        # Upsert batch
        client.upsert(collection_name=COLLECTION_NAME, points=points)

        if (batch_idx + 1) % 20 == 0 or batch_idx == total_batches - 1:
            logger.info(f"Batch {batch_idx + 1}/{total_batches} completed")

    final_count = client.get_collection(COLLECTION_NAME).points_count
    logger.info(f"Indexing completed. Total points: {final_count}")
    return final_count


def verify_index(client: QdrantClient, embedding_model: SentenceTransformer) -> bool:
    """Verify the index with a test search."""
    collection_info = client.get_collection(COLLECTION_NAME)

    if collection_info.points_count == 0:
        logger.error("Collection is empty after indexing!")
        return False

    # Test dense search
    test_query = "action movies with explosions"
    query_embedding = embedding_model.encode([test_query])[0].tolist()

    results = client.query_points(
        collection_name=COLLECTION_NAME,
        query=query_embedding,
        using="dense",
        limit=5,
        with_payload=True,
    )

    logger.info(f"Test query: '{test_query}'")
    logger.info(f"Dense search results: {len(results.points)} matches")

    for hit in results.points:
        logger.info(f"  - IMDB ID: {hit.payload['imdb_id']}, Score: {hit.score:.4f}")

    # Test hybrid search
    sparse_tokens = tokenize_text(test_query)

    hybrid_results = client.query_points(
        collection_name=COLLECTION_NAME,
        prefetch=[
            models.Prefetch(
                query=query_embedding,
                using="dense",
                limit=10,
            ),
            models.Prefetch(
                query=models.SparseVector(
                    indices=list(sparse_tokens.keys()),
                    values=list(sparse_tokens.values())
                ),
                using="bm25",
                limit=10,
            ),
        ],
        query=models.FusionQuery(fusion=models.Fusion.RRF),
        limit=5,
        with_payload=True,
    )

    logger.info(f"Hybrid search results: {len(hybrid_results.points)} matches")

    return len(results.points) > 0


def main():
    """Main entry point for Qdrant initialization."""
    logger.info("=" * 60)
    logger.info("Qdrant Initialization Job")
    logger.info("=" * 60)
    logger.info(f"Qdrant URL: {QDRANT_URL}")
    logger.info(f"Collection: {COLLECTION_NAME}")
    logger.info(f"Embedding model: {EMBEDDING_MODEL}")
    logger.info(f"Force reindex: {FORCE_REINDEX}")
    logger.info("=" * 60)

    try:
        # Connect to Qdrant
        logger.info("Connecting to Qdrant...")
        client = QdrantClient(QDRANT_URL, check_compatibility=False)

        # Create collection
        logger.info("Creating/verifying collection...")
        create_collection(client)

        # Load data
        logger.info("Loading movies data...")
        movies_db = load_movies_from_azure()
        movies_db = prepare_movies_data(movies_db)

        # Load embedding model
        logger.info(f"Loading embedding model: {EMBEDDING_MODEL}")
        embedding_model = SentenceTransformer(EMBEDDING_MODEL)

        # Index movies
        logger.info("Indexing movies...")
        indexed_count = index_movies(client, movies_db, embedding_model)

        # Verify index
        logger.info("Verifying index...")
        if verify_index(client, embedding_model):
            logger.info("=" * 60)
            logger.info(f"SUCCESS: Indexed {indexed_count} movies to Qdrant")
            logger.info("=" * 60)
            sys.exit(0)
        else:
            logger.error("Index verification failed!")
            sys.exit(1)

    except Exception as e:
        logger.exception(f"Job failed with error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
