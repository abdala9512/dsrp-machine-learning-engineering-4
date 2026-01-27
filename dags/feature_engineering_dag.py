"""
Feature Engineering DAG for DSRP MLOps project.

This DAG processes raw IMDB data and generates features for the ML pipeline.
It includes:
1. Loading and combining base movie data with OMDB enrichment
2. Generating text embeddings using sentence-transformers
3. Creating derived features for LTR training

Note: Uses custom airflow-ml image with pre-installed dependencies.
"""

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.sdk import Variable
from kubernetes.client import models as k8s


# Standard resources for lightweight tasks (data loading, basic transformations)
resource_requirements = k8s.V1ResourceRequirements(
    requests={"cpu": "500m", "memory": "1Gi", "ephemeral-storage": "2Gi"},
    limits={"cpu": "1000m", "memory": "4Gi", "ephemeral-storage": "6Gi"},
)

# Heavy ML resources for tasks requiring sentence-transformers, embeddings, etc.
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
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}


# =============================================================================
# Utility Functions
# =============================================================================

def get_blob_service_client():
    """Get Azure Blob Storage client from environment."""
    from azure.storage.blob import BlobServiceClient

    credentials = Variable.get("azure_storage_credentials")
    account_name = Variable.get("azure_storage_account_name")

    return BlobServiceClient(
        account_url=account_name,
        credential=credentials
    )


def load_data_from_blob():
    """Load data from blob storage."""
    from io import BytesIO
    import polars as pl

    blob_service_client = get_blob_service_client()
    blob_client = blob_service_client.get_blob_client(
        container="ml-pipeline-data",
        blob="ltr_imdb_dataset.parquet"
    )
    return pl.read_parquet(BytesIO(blob_client.download_blob().readall()))


def write_data_to_blob(data, blob_name: str):
    """Write data to blob storage."""
    from io import BytesIO

    blob_service_client = get_blob_service_client()
    blob_client = blob_service_client.get_blob_client(
        container="ml-pipeline-data",
        blob=f"airflow-prod/{blob_name}.parquet"
    )
    buffer = BytesIO()
    data.write_parquet(buffer)
    blob_client.upload_blob(buffer.getvalue(), overwrite=True)


# =============================================================================
# Task Functions
# =============================================================================

def check_dependencies():
    """Check if the dependencies are installed."""
    try:
        from azure.storage.blob import BlobServiceClient  # noqa: F401
        import polars as pl  # noqa: F401
        from loguru import logger

        logger.info("Dependencies checked successfully")

    except Exception as e:
        print(f"Error checking dependencies: {e}")
        return False

    return True


def load_base_movies_data():
    """Load base data from blob storage."""
    from io import BytesIO
    import polars as pl
    import json
    from loguru import logger

    blob_service_client = get_blob_service_client()
    movies_base_blob_client = blob_service_client.get_blob_client(
        container="ml-pipeline-data",
        blob="movies_base.parquet"
    )
    omdb_blob_client = blob_service_client.get_blob_client(
        container="ml-pipeline-data",
        blob="omdb_raw.jsonl"
    )

    logger.info("Loading movies_base.parquet...")
    movies_base = pl.read_parquet(BytesIO(movies_base_blob_client.download_blob().readall()))

    logger.info("Loading omdb_raw.jsonl...")
    omdb_raw = [json.loads(line) for line in BytesIO(omdb_blob_client.download_blob().readall())]

    complementary_imdb_data = pl.DataFrame(
        [
            [
                i["imdb_id"],
                i["raw"].get("Runtime"),
                i["raw"].get("Director"),
                i["raw"].get("Actors"),
                i["raw"].get("Plot"),
                i["raw"].get("Country"),
                i["raw"].get("Language"),
            ] for i in omdb_raw
        ],
        schema={
            "imdb_id": str,
            "Runtime": str,
            "Director": str,
            "Actors": str,
            "Plot": str,
            "Country": str,
            "Language": str
        },
        orient="row"
    )

    complete_db = movies_base.join(complementary_imdb_data, on="imdb_id")

    logger.info(f"Complete database shape: {complete_db.shape}")
    write_data_to_blob(complete_db, "complete_imdb_database")

    return "Base data loaded and written to blob storage. Location: airflow-prod/complete_imdb_database.parquet"


def load_and_write_data():
    """Load and write data to a file."""
    from loguru import logger

    data = load_data_from_blob()
    write_data_to_blob(data, "test")
    logger.info("Data loaded and written to blob storage")
    return "Data loaded and written to blob storage"


def generate_embeddings():
    """Generate embeddings for movie texts using sentence-transformers."""
    from sentence_transformers import SentenceTransformer
    from io import BytesIO
    import polars as pl
    import numpy as np
    from loguru import logger

    blob_service_client = get_blob_service_client()

    complete_database_blob_client = blob_service_client.get_blob_client(
        container="ml-pipeline-data",
        blob="airflow-prod/complete_imdb_database.parquet"
    )

    logger.info("Loading complete_imdb_database.parquet...")
    complete_database = pl.read_parquet(BytesIO(complete_database_blob_client.download_blob().readall()))

    logger.info("Loading sentence-transformers model...")
    model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

    texts = (complete_database["title"] + ". " + complete_database["Plot"].fill_null("")).to_list()

    logger.info(f"Generating embeddings for {len(texts)} movies...")
    embs = model.encode(texts, batch_size=64, show_progress_bar=True)
    embs = np.asarray(embs, dtype="float32")

    logger.info(f"Embeddings shape: {embs.shape}")
    logger.info(f"Model: sentence-transformers/all-MiniLM-L6-v2")
    logger.info(f"Embedding dimension: {model.get_sentence_embedding_dimension()}")

    blob_client = blob_service_client.get_blob_client(
        container="ml-pipeline-data",
        blob="airflow-prod/movie_embs.npy"
    )
    buffer = BytesIO()
    np.save(buffer, embs)
    blob_client.upload_blob(buffer.getvalue(), overwrite=True)

    logger.info("Embeddings saved to airflow-prod/movie_embs.npy")
    return f"Generated embeddings for {len(texts)} movies"


def generate_new_features():
    """Generate derived features for the movies database."""
    from io import BytesIO
    import polars as pl
    from loguru import logger

    blob_service_client = get_blob_service_client()

    complete_database_blob_client = blob_service_client.get_blob_client(
        container="ml-pipeline-data",
        blob="airflow-prod/complete_imdb_database.parquet"
    )

    logger.info("Loading complete_imdb_database.parquet...")
    complete_database = pl.read_parquet(BytesIO(complete_database_blob_client.download_blob().readall()))

    logger.info("Generating derived features...")
    features = complete_database.with_columns([
        pl.col("imdb_votes").log1p().alias("imdb_votes_log"),
        (
            (pl.col("year") - pl.col("year").mean()) / pl.col("year").std()
        ).alias("year_norm"),
        (2025 - pl.col("year")).alias("movie_age"),
        pl.col("Plot").str.len_chars().alias("plot_length"),
        pl.col("genres").str.contains("Action").cast(pl.Int8()).alias("genre_action"),
    ])

    logger.info(f"Features generated. Shape: {features.shape}")
    write_data_to_blob(features, "featured_movies_database")

    return "Features generated and saved to airflow-prod/featured_movies_database.parquet"


# =============================================================================
# DAG Definition
# =============================================================================

with DAG(
    dag_id="feature_engineering_dag",
    default_args=default_args,
    description="Feature engineering pipeline for DSRP ML project",
    schedule=timedelta(days=1),
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=["ml", "dsrp", "feature-engineering"],
) as dag:

    check_dependencies_task = PythonOperator(
        task_id="check_dependencies",
        python_callable=check_dependencies,
        executor_config={"pod_override": generate_pod_config()},
    )

    load_and_write_data_task = PythonOperator(
        task_id="load_and_write_data",
        python_callable=load_and_write_data,
        executor_config={"pod_override": generate_pod_config()},
    )

    load_base_movies_data_task = PythonOperator(
        task_id="load_base_movies_data",
        python_callable=load_base_movies_data,
        executor_config={"pod_override": generate_pod_config()}
    )

    generate_embeddings_task = PythonOperator(
        task_id="generate_embeddings",
        python_callable=generate_embeddings,
        executor_config={"pod_override": generate_pod_config(resources=ml_resource_requirements)}
    )

    generate_features_task = PythonOperator(
        task_id="generate_features",
        python_callable=generate_new_features,
        executor_config={"pod_override": generate_pod_config()}
    )

    check_dependencies_task >> [load_and_write_data_task, load_base_movies_data_task >> generate_embeddings_task] >> generate_features_task
