"""
Qdrant Indexing DAG for Movie Search.

This DAG indexes movies into Qdrant for hybrid search (dense embeddings + BM25 sparse).
It creates or updates the collection and indexes all movies with their embeddings.

Prerequisites:
- complete_imdb_database.parquet in Azure Blob Storage
- Qdrant instance running and accessible

Note: Uses custom airflow-ml image with pre-installed dependencies.
"""

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.sdk import Variable
from kubernetes.client import models as k8s


# Standard resources for lightweight tasks
resource_requirements = k8s.V1ResourceRequirements(
    requests={"cpu": "500m", "memory": "1Gi", "ephemeral-storage": "2Gi"},
    limits={"cpu": "1000m", "memory": "4Gi", "ephemeral-storage": "6Gi"},
)

# Heavy ML resources for tasks requiring sentence-transformers
ml_resource_requirements = k8s.V1ResourceRequirements(
    requests={"cpu": "1000m", "memory": "4Gi", "ephemeral-storage": "4Gi"},
    limits={"cpu": "2000m", "memory": "8Gi", "ephemeral-storage": "10Gi"},
)


def generate_pod_config(resources: k8s.V1ResourceRequirements = None):
    """Generate Kubernetes pod configuration with resource limits."""
    pod_resources = resources if resources is not None else resource_requirements
    return k8s.V1Pod(
        spec=k8s.V1PodSpec(
            containers=[
                k8s.V1Container(
                    name="base",
                    resources=pod_resources
                )
            ]
        )
    )


default_args = {
    "owner": "dsrp",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}


# =============================================================================
# Configuration
# =============================================================================

EMBEDDINGS_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIM = 384
COLLECTION_NAME = "imdb-movies-hybrid"
BATCH_SIZE = 500


# =============================================================================
# Utility Functions
# =============================================================================

def get_blob_service_client():
    """Get Azure Blob Storage client from Airflow variables."""
    from azure.storage.blob import BlobServiceClient

    credentials = Variable.get("azure_storage_credentials")
    account_name = Variable.get("azure_storage_account_name")

    return BlobServiceClient(
        account_url=account_name,
        credential=credentials
    )


def read_parquet_from_blob(container: str, blob_name: str):
    """Read parquet file from Azure Blob Storage."""
    from io import BytesIO
    import polars as pl

    blob_service_client = get_blob_service_client()
    blob_client = blob_service_client.get_blob_client(
        container=container,
        blob=blob_name
    )
    return pl.read_parquet(BytesIO(blob_client.download_blob().readall()))


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


# =============================================================================
# Task Functions
# =============================================================================

def create_qdrant_collection():
    """Create or verify Qdrant collection for hybrid search."""
    from qdrant_client import QdrantClient, models
    from loguru import logger

    qdrant_url = Variable.get("qdrant_url")
    logger.info(f"Connecting to Qdrant at {qdrant_url}")

    client = QdrantClient(qdrant_url, check_compatibility=False)

    # Get existing collections
    collections = [c.name for c in client.get_collections().collections]
    logger.info(f"Existing collections: {collections}")

    if COLLECTION_NAME not in collections:
        # Create collection with hybrid search support
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
    else:
        logger.info(f"Collection '{COLLECTION_NAME}' already exists")

    # Get collection info
    collection_info = client.get_collection(COLLECTION_NAME)
    logger.info(f"Points in collection: {collection_info.points_count}")

    return f"Collection '{COLLECTION_NAME}' ready with {collection_info.points_count} points"


def index_movies_to_qdrant():
    """Index all movies to Qdrant with embeddings and BM25 vectors."""
    import polars as pl
    from qdrant_client import QdrantClient, models
    from sentence_transformers import SentenceTransformer
    from loguru import logger

    qdrant_url = Variable.get("qdrant_url")
    logger.info(f"Connecting to Qdrant at {qdrant_url}")

    client = QdrantClient(qdrant_url, check_compatibility=False)

    # Load movies database
    logger.info("Loading movies database...")
    movies_db = read_parquet_from_blob("ml-pipeline-data", "airflow-prod/complete_imdb_database.parquet")

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

    logger.info(f"Loaded {movies_db.height} movies")

    # Load embedding model
    logger.info(f"Loading embedding model: {EMBEDDINGS_MODEL}")
    embedding_model = SentenceTransformer(EMBEDDINGS_MODEL)

    # Check current collection state
    collection_info = client.get_collection(COLLECTION_NAME)
    current_count = collection_info.points_count

    if current_count > 0:
        logger.info(f"Clearing {current_count} existing points...")
        # Delete all points by scrolling and deleting in batches
        client.delete(
            collection_name=COLLECTION_NAME,
            points_selector=models.FilterSelector(
                filter=models.Filter(must=[])
            )
        )

    # Index movies in batches
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

    return f"Indexed {final_count} movies to Qdrant"


def verify_qdrant_index():
    """Verify the Qdrant index with a test search."""
    from qdrant_client import QdrantClient, models
    from sentence_transformers import SentenceTransformer
    from loguru import logger

    qdrant_url = Variable.get("qdrant_url")
    client = QdrantClient(qdrant_url, check_compatibility=False)

    # Verify collection
    collection_info = client.get_collection(COLLECTION_NAME)
    logger.info(f"Collection: {COLLECTION_NAME}")
    logger.info(f"Total points: {collection_info.points_count}")

    if collection_info.points_count == 0:
        raise ValueError("Collection is empty after indexing!")

    # Test search
    embedding_model = SentenceTransformer(EMBEDDINGS_MODEL)
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
    logger.info(f"Results: {len(results.points)} matches")

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

    return f"Index verified: {collection_info.points_count} points, search working"


# =============================================================================
# DAG Definition
# =============================================================================

with DAG(
    dag_id="qdrant_indexing_dag",
    default_args=default_args,
    description="Index movies to Qdrant for hybrid search",
    schedule=timedelta(days=7),  # Weekly, after feature engineering
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=["ml", "qdrant", "dsrp", "indexing"],
) as dag:

    create_collection_task = PythonOperator(
        task_id="create_qdrant_collection",
        python_callable=create_qdrant_collection,
        executor_config={"pod_override": generate_pod_config()},
    )

    index_movies_task = PythonOperator(
        task_id="index_movies_to_qdrant",
        python_callable=index_movies_to_qdrant,
        executor_config={"pod_override": generate_pod_config(resources=ml_resource_requirements)},
    )

    verify_index_task = PythonOperator(
        task_id="verify_qdrant_index",
        python_callable=verify_qdrant_index,
        executor_config={"pod_override": generate_pod_config(resources=ml_resource_requirements)},
    )

    create_collection_task >> index_movies_task >> verify_index_task
