"""
Embeddings Indexing DAG - DSRP ML Pipeline

Indexes embeddings in Qdrant for hybrid search.
Can run as standalone script or Airflow DAG.
"""

import os
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any

import numpy as np
import polars as pl

# Configuration from environment
DATA_DIR = os.environ.get("DSRP_DATA_DIR", str(Path(__file__).parent.parent.parent / "data"))
QDRANT_URL = os.environ.get("DSRP_QDRANT_URL", "http://localhost:6333")
QDRANT_COLLECTION = os.environ.get("DSRP_QDRANT_COLLECTION", "imdb-movies-hybrid")
EMBEDDING_MODEL = os.environ.get("DSRP_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
EMBEDDING_DIM = int(os.environ.get("DSRP_EMBEDDING_DIM", "384"))
INDEXING_BATCH_SIZE = int(os.environ.get("QDRANT_BATCH_SIZE", "500"))


# =============================================================================
# Task Functions
# =============================================================================

def connect_to_qdrant() -> Dict[str, Any]:
    """Connect to Qdrant and verify connectivity."""
    from qdrant_client import QdrantClient

    print(f"Connecting to Qdrant at {QDRANT_URL}")
    client = QdrantClient(QDRANT_URL, timeout=30)

    collections = [c.name for c in client.get_collections().collections]
    print(f"Existing collections: {collections}")

    return {"url": QDRANT_URL, "collections": collections, "connected": True}


def create_collection() -> Dict[str, Any]:
    """Create or verify the Qdrant collection."""
    from qdrant_client import QdrantClient, models

    client = QdrantClient(QDRANT_URL, timeout=30)
    collections = [c.name for c in client.get_collections().collections]

    if QDRANT_COLLECTION in collections:
        print(f"Collection '{QDRANT_COLLECTION}' already exists")
        info = client.get_collection(QDRANT_COLLECTION)
        return {"collection": QDRANT_COLLECTION, "created": False, "points_count": info.points_count}

    print(f"Creating collection '{QDRANT_COLLECTION}'")
    client.create_collection(
        collection_name=QDRANT_COLLECTION,
        vectors_config={
            "dense": models.VectorParams(size=EMBEDDING_DIM, distance=models.Distance.COSINE)
        },
        sparse_vectors_config={
            "bm25": models.SparseVectorParams(modifier=models.Modifier.IDF)
        },
    )

    print(f"Collection '{QDRANT_COLLECTION}' created")
    return {"collection": QDRANT_COLLECTION, "created": True, "points_count": 0}


def prepare_data_for_indexing() -> str:
    """Prepare movie data for indexing."""
    db_path = os.path.join(DATA_DIR, "complete_imdb_database.parquet")
    embeddings_path = os.path.join(DATA_DIR, "movie_embs.npy")

    print(f"Loading database from {db_path}")
    movies_db = pl.read_parquet(db_path)

    print(f"Loading embeddings from {embeddings_path}")
    embeddings = np.load(embeddings_path)

    if "imdb_votes_log" not in movies_db.columns:
        movies_db = movies_db.with_columns(pl.col("imdb_votes").log1p().alias("imdb_votes_log"))

    movies_db = movies_db.with_columns(
        pl.concat_str([pl.col("title"), pl.col("Plot")], separator=". ").fill_null("").alias("full_text")
    )

    prepared_path = os.path.join(DATA_DIR, "movies_for_indexing.parquet")
    movies_db.write_parquet(prepared_path)

    print(f"Prepared {movies_db.height} movies, embeddings: {embeddings.shape}")
    return prepared_path


def tokenize_text(text: str) -> Dict[int, float]:
    """Simple tokenizer for BM25 sparse vectors."""
    if not text:
        return {}
    words = text.lower().split()
    token_counts = {}
    for word in words:
        if len(word) > 2:
            idx = hash(word) % 100000
            token_counts[idx] = token_counts.get(idx, 0) + 1
    return token_counts


def index_embeddings(force_reindex: bool = False) -> Dict[str, Any]:
    """Index movie embeddings in Qdrant."""
    from qdrant_client import QdrantClient, models

    prepared_path = os.path.join(DATA_DIR, "movies_for_indexing.parquet")
    embeddings_path = os.path.join(DATA_DIR, "movie_embs.npy")

    client = QdrantClient(QDRANT_URL, timeout=60)
    movies_db = pl.read_parquet(prepared_path)
    embeddings = np.load(embeddings_path)

    info = client.get_collection(QDRANT_COLLECTION)
    current_points = info.points_count

    force_reindex = force_reindex or os.environ.get("QDRANT_FORCE_REINDEX", "false") == "true"

    if current_points > 0 and not force_reindex:
        print(f"Collection has {current_points} points. Set QDRANT_FORCE_REINDEX=true to reindex.")
        return {"indexed": False, "points_count": current_points}

    if current_points > 0 and force_reindex:
        print(f"Clearing {current_points} existing points")
        client.delete(
            collection_name=QDRANT_COLLECTION,
            points_selector=models.FilterSelector(filter=models.Filter(must=[])),
        )

    print(f"Indexing {movies_db.height} movies...")

    texts = movies_db["full_text"].to_list()
    imdb_ids = movies_db["imdb_id"].to_list()
    total_batches = (len(texts) + INDEXING_BATCH_SIZE - 1) // INDEXING_BATCH_SIZE

    for batch_idx in range(total_batches):
        start = batch_idx * INDEXING_BATCH_SIZE
        end = min(start + INDEXING_BATCH_SIZE, len(texts))

        points = []
        for i in range(start, end):
            sparse_tokens = tokenize_text(texts[i])
            points.append(models.PointStruct(
                id=i,
                vector={
                    "dense": embeddings[i].tolist(),
                    "bm25": models.SparseVector(
                        indices=list(sparse_tokens.keys()),
                        values=list(sparse_tokens.values()),
                    ),
                },
                payload={"imdb_id": imdb_ids[i], "row_index": i},
            ))

        client.upsert(collection_name=QDRANT_COLLECTION, points=points)

        if (batch_idx + 1) % 20 == 0 or batch_idx == total_batches - 1:
            print(f"  Batch {batch_idx + 1}/{total_batches}")

    final_count = client.get_collection(QDRANT_COLLECTION).points_count
    print(f"Indexing complete. Total points: {final_count}")

    return {"indexed": True, "points_count": final_count}


def verify_indexing() -> Dict[str, Any]:
    """Verify indexing with test queries."""
    from qdrant_client import QdrantClient
    from sentence_transformers import SentenceTransformer

    client = QdrantClient(QDRANT_URL, timeout=30)
    model = SentenceTransformer(EMBEDDING_MODEL)

    test_queries = [
        "action movies with car chases",
        "romantic comedy set in New York",
        "sci-fi movies about artificial intelligence",
    ]

    results = []
    for query in test_queries:
        query_embedding = model.encode([query])[0].tolist()
        search_results = client.query_points(
            collection_name=QDRANT_COLLECTION,
            query=query_embedding,
            using="dense",
            limit=5,
            with_payload=True,
        )
        results.append({
            "query": query,
            "hits": len(search_results.points),
            "top_score": search_results.points[0].score if search_results.points else 0,
        })

    verification = {
        "test_queries": results,
        "all_returned_results": all(r["hits"] > 0 for r in results),
    }

    print(f"Verification: {json.dumps(verification, indent=2)}")
    return verification


# =============================================================================
# Airflow DAG (optional)
# =============================================================================

try:
    from airflow import DAG
    from airflow.operators.python import PythonOperator

    default_args = {
        "owner": "dsrp-ml",
        "depends_on_past": False,
        "retries": 3,
        "retry_delay": timedelta(minutes=2),
    }

    with DAG(
        dag_id="embeddings_indexing",
        default_args=default_args,
        description="Index embeddings in Qdrant",
        schedule=None,
        start_date=datetime(2024, 1, 1),
        catchup=False,
        tags=["dsrp", "indexing", "qdrant"],
    ) as dag:

        t1 = PythonOperator(task_id="connect_to_qdrant", python_callable=connect_to_qdrant)
        t2 = PythonOperator(task_id="create_collection", python_callable=create_collection)
        t3 = PythonOperator(task_id="prepare_data_for_indexing", python_callable=prepare_data_for_indexing)
        t4 = PythonOperator(
            task_id="index_embeddings",
            python_callable=index_embeddings,
            execution_timeout=timedelta(hours=1),
        )
        t5 = PythonOperator(task_id="verify_indexing", python_callable=verify_indexing)

        t1 >> t2
        t3 >> t4
        [t2, t3] >> t4 >> t5

except ImportError:
    dag = None


# =============================================================================
# Standalone execution
# =============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Embeddings Indexing Pipeline")
    parser.add_argument("--step", choices=["all", "connect", "create", "prepare", "index", "verify"], default="all")
    parser.add_argument("--force-reindex", action="store_true", help="Force reindex even if collection has data")
    args = parser.parse_args()

    if args.step in ["all", "connect"]:
        connect_to_qdrant()

    if args.step in ["all", "create"]:
        create_collection()

    if args.step in ["all", "prepare"]:
        prepare_data_for_indexing()

    if args.step in ["all", "index"]:
        index_embeddings(force_reindex=args.force_reindex)

    if args.step in ["all", "verify"]:
        verify_indexing()
