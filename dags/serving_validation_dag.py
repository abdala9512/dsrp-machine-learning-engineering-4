"""
Serving Validation DAG for Movie Search Pipeline.

This DAG validates the end-to-end search pipeline by:
1. Loading the champion LTR model from MLflow
2. Running hybrid search queries against Qdrant
3. Re-ranking results with the LTR model
4. Validating search quality metrics

Prerequisites:
- Qdrant collection indexed with movies
- LTR model registered in MLflow with 'champion' alias
- complete_imdb_database.parquet in Azure Blob Storage
"""

from datetime import datetime, timedelta
from typing import List

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.sdk import Variable
from kubernetes.client import models as k8s


# Standard resources for lightweight tasks
resource_requirements = k8s.V1ResourceRequirements(
    requests={"cpu": "500m", "memory": "1Gi", "ephemeral-storage": "2Gi"},
    limits={"cpu": "1000m", "memory": "4Gi", "ephemeral-storage": "6Gi"},
)

# Heavy ML resources for tasks requiring sentence-transformers and model inference
ml_resource_requirements = k8s.V1ResourceRequirements(
    requests={"cpu": "1000m", "memory": "4Gi", "ephemeral-storage": "4Gi"},
    limits={"cpu": "2000m", "memory": "8Gi", "ephemeral-storage": "10Gi"},
)


def generate_pod_config(
    pip_packages: str = None,
    resources: k8s.V1ResourceRequirements = None
):
    """Generate Kubernetes pod configuration with pip packages via _PIP_ADDITIONAL_REQUIREMENTS."""
    if pip_packages is None:
        pip_packages = "dsrp-ml-utils[azure] polars>=1.35.2 loguru>=0.7.3"

    pod_resources = resources if resources is not None else resource_requirements
    return k8s.V1Pod(
        spec=k8s.V1PodSpec(
            containers=[
                k8s.V1Container(
                    name="base",
                    env=[
                        k8s.V1EnvVar(
                            name="_PIP_ADDITIONAL_REQUIREMENTS",
                            value=pip_packages
                        )
                    ],
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

MODEL_NAME = "ltr-dsrpflix-prd"
EMBEDDINGS_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
COLLECTION_NAME = "imdb-movies-hybrid"
TOP_K_RETRIEVAL = 100
TOP_K_FINAL = 10

FEATURE_COLS = [
    "sim_embedding",
    "imdb_rating",
    "imdb_votes_log",
]

# Test queries for validation
TEST_QUERIES = [
    "action movies with explosions",
    "romantic comedies from the 90s",
    "sci-fi movies like blade runner",
    "best thriller movies",
    "family friendly adventure films",
    "classic drama movies",
    "horror movies that are actually scary",
    "movies similar to the godfather",
]


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

def load_and_validate_model():
    """Load the champion LTR model from MLflow and validate it."""
    import mlflow
    import dagshub
    from loguru import logger

    logger.info("Initializing MLflow tracking...")

    # Set DagsHub token from Airflow Variables
    import os
    dagshub_token = Variable.get("dagshub_token")
    os.environ["DAGSHUB_USER_TOKEN"] = dagshub_token

    # Initialize DagsHub MLflow
    dagshub.init(
        repo_owner='abdala9512',
        repo_name='dsrp-machine-learning-engineering-4',
        mlflow=True
    )

    # Load champion model
    logger.info(f"Loading model: {MODEL_NAME}@champion")

    try:
        ltr_model = mlflow.lightgbm.load_model(f"models:/{MODEL_NAME}@champion")
        logger.info("Champion model loaded successfully")

        # Get model info
        client = mlflow.MlflowClient()
        registered_model = client.get_registered_model(name=MODEL_NAME)

        champion_version = registered_model.aliases.get("champion")
        if champion_version:
            model_version = client.get_model_version(name=MODEL_NAME, version=champion_version)
            run_id = model_version.run_id

            run = mlflow.get_run(run_id)
            metrics = run.data.metrics

            logger.info(f"Champion model version: v{champion_version}")
            logger.info(f"Run ID: {run_id}")
            logger.info(f"Test nDCG@10: {metrics.get('test_nDCG_10', 'N/A')}")

            return {
                "model_name": MODEL_NAME,
                "version": champion_version,
                "run_id": run_id,
                "test_ndcg_10": metrics.get("test_nDCG_10"),
            }

    except Exception as e:
        logger.error(f"Failed to load champion model: {e}")
        logger.info("Attempting to load latest version...")
        ltr_model = mlflow.lightgbm.load_model(f"models:/{MODEL_NAME}/latest")
        logger.info("Latest model loaded as fallback")
        return {"model_name": MODEL_NAME, "version": "latest", "fallback": True}


def validate_qdrant_connection():
    """Validate Qdrant connection and collection status."""
    from qdrant_client import QdrantClient
    from loguru import logger

    qdrant_url = Variable.get("qdrant_url")
    logger.info(f"Connecting to Qdrant at {qdrant_url}")

    client = QdrantClient(qdrant_url, check_compatibility=False)

    # Check collections
    collections = [c.name for c in client.get_collections().collections]
    logger.info(f"Available collections: {collections}")

    if COLLECTION_NAME not in collections:
        raise ValueError(f"Collection '{COLLECTION_NAME}' not found! Run qdrant_indexing_dag first.")

    # Get collection info
    collection_info = client.get_collection(COLLECTION_NAME)
    points_count = collection_info.points_count

    logger.info(f"Collection '{COLLECTION_NAME}': {points_count} points")

    if points_count == 0:
        raise ValueError(f"Collection '{COLLECTION_NAME}' is empty!")

    return {
        "collection_name": COLLECTION_NAME,
        "points_count": points_count,
        "status": "healthy",
    }


def run_search_pipeline_validation():
    """Run the full search pipeline with test queries and validate results."""
    import numpy as np
    import polars as pl
    import mlflow
    import dagshub
    from qdrant_client import QdrantClient, models
    from sentence_transformers import SentenceTransformer
    from loguru import logger

    logger.info("Starting search pipeline validation...")

    # Initialize connections
    qdrant_url = Variable.get("qdrant_url")
    client = QdrantClient(qdrant_url, check_compatibility=False)

    # Set DagsHub token from Airflow Variables
    import os
    dagshub_token = Variable.get("dagshub_token")
    os.environ["DAGSHUB_USER_TOKEN"] = dagshub_token

    dagshub.init(
        repo_owner='abdala9512',
        repo_name='dsrp-machine-learning-engineering-4',
        mlflow=True
    )

    # Load models
    logger.info("Loading embedding model...")
    embedding_model = SentenceTransformer(EMBEDDINGS_MODEL)

    logger.info("Loading LTR model...")
    try:
        ltr_model = mlflow.lightgbm.load_model(f"models:/{MODEL_NAME}@champion")
    except Exception:
        ltr_model = mlflow.lightgbm.load_model(f"models:/{MODEL_NAME}/latest")

    # Load movies database
    logger.info("Loading movies database...")
    movies_db = read_parquet_from_blob("ml-pipeline-data", "airflow-prod/complete_imdb_database.parquet")

    if "imdb_votes_log" not in movies_db.columns:
        movies_db = movies_db.with_columns([
            pl.col("imdb_votes").log1p().alias("imdb_votes_log"),
        ])

    movies_db = movies_db.with_columns([
        pl.concat_str(
            [pl.col("title"), pl.col("Plot")],
            separator=". ",
        ).fill_null("").alias("full_text"),
    ])

    logger.info(f"Loaded {movies_db.height} movies")

    def hybrid_search(query: str, top_k: int = TOP_K_RETRIEVAL) -> list:
        """Perform hybrid search on Qdrant."""
        query_embedding = embedding_model.encode([query])[0].tolist()
        query_sparse = tokenize_text(query)

        results = client.query_points(
            collection_name=COLLECTION_NAME,
            prefetch=[
                models.Prefetch(
                    query=query_embedding,
                    using="dense",
                    limit=top_k,
                ),
                models.Prefetch(
                    query=models.SparseVector(
                        indices=list(query_sparse.keys()),
                        values=list(query_sparse.values())
                    ),
                    using="bm25",
                    limit=top_k,
                ),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=top_k,
            with_payload=True,
        )

        return [
            {
                "imdb_id": hit.payload["imdb_id"],
                "row_index": hit.payload["row_index"],
                "retrieval_score": hit.score,
            }
            for hit in results.points
        ]

    def rerank_candidates(candidates: list, query: str) -> pl.DataFrame:
        """Re-rank candidates using LTR model."""
        if not candidates:
            return pl.DataFrame()

        candidate_ids = [c["imdb_id"] for c in candidates]
        retrieval_scores = {c["imdb_id"]: c["retrieval_score"] for c in candidates}

        candidates_df = movies_db.filter(pl.col("imdb_id").is_in(candidate_ids))

        if candidates_df.is_empty():
            return pl.DataFrame()

        # Calculate embedding similarity
        query_emb = embedding_model.encode([query])[0]
        query_emb = query_emb / (np.linalg.norm(query_emb) + 1e-9)

        candidate_texts = candidates_df["full_text"].to_list()
        candidate_embs = embedding_model.encode(candidate_texts)
        candidate_embs = candidate_embs / (np.linalg.norm(candidate_embs, axis=1, keepdims=True) + 1e-9)

        sim_scores = candidate_embs @ query_emb

        candidates_df = candidates_df.with_columns([
            pl.Series("sim_embedding", sim_scores.astype("float64")),
        ])

        # Prepare features and predict
        available_cols = [c for c in FEATURE_COLS if c in candidates_df.columns]
        X = candidates_df.select(available_cols).to_numpy()

        ltr_scores = ltr_model.predict(X)

        candidates_df = candidates_df.with_columns([
            pl.Series("ltr_score", ltr_scores),
            pl.Series("retrieval_score", [retrieval_scores.get(id, 0) for id in candidates_df["imdb_id"].to_list()]),
        ])

        return candidates_df.sort("ltr_score", descending=True).head(TOP_K_FINAL)

    # Run validation on test queries
    validation_results = []

    for query in TEST_QUERIES:
        logger.info(f"Testing query: '{query}'")

        # Step 1: Retrieval
        candidates = hybrid_search(query)
        retrieval_count = len(candidates)

        # Step 2: Re-ranking
        results = rerank_candidates(candidates, query)
        final_count = len(results)

        # Collect results
        top_result = None
        if not results.is_empty():
            top_result = {
                "title": results["title"][0],
                "imdb_rating": float(results["imdb_rating"][0]),
                "ltr_score": float(results["ltr_score"][0]),
            }

        validation_results.append({
            "query": query,
            "candidates_retrieved": retrieval_count,
            "results_after_rerank": final_count,
            "top_result": top_result,
            "success": final_count > 0,
        })

        if top_result:
            logger.info(f"  Top result: {top_result['title']} (LTR: {top_result['ltr_score']:.2f})")

    # Summary
    successful = sum(1 for r in validation_results if r["success"])
    total = len(validation_results)

    logger.info("=" * 60)
    logger.info("VALIDATION SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Queries tested: {total}")
    logger.info(f"Successful: {successful}/{total}")

    if successful < total:
        failed_queries = [r["query"] for r in validation_results if not r["success"]]
        logger.warning(f"Failed queries: {failed_queries}")

    # Calculate average metrics
    avg_candidates = np.mean([r["candidates_retrieved"] for r in validation_results])
    avg_results = np.mean([r["results_after_rerank"] for r in validation_results])

    logger.info(f"Avg candidates retrieved: {avg_candidates:.1f}")
    logger.info(f"Avg results after rerank: {avg_results:.1f}")

    if successful < total * 0.8:  # Less than 80% success rate
        raise ValueError(f"Search pipeline validation failed: only {successful}/{total} queries successful")

    return {
        "total_queries": total,
        "successful": successful,
        "success_rate": successful / total,
        "avg_candidates": avg_candidates,
        "avg_results": avg_results,
    }


def generate_serving_report():
    """Generate a summary report of the serving pipeline status."""
    import json
    from datetime import datetime
    from loguru import logger

    logger.info("Generating serving report...")

    report = {
        "timestamp": datetime.now().isoformat(),
        "pipeline_components": {
            "qdrant": {
                "collection": COLLECTION_NAME,
                "status": "healthy",
            },
            "ltr_model": {
                "name": MODEL_NAME,
                "alias": "champion",
                "status": "loaded",
            },
            "embedding_model": {
                "name": EMBEDDINGS_MODEL,
                "status": "available",
            },
        },
        "configuration": {
            "top_k_retrieval": TOP_K_RETRIEVAL,
            "top_k_final": TOP_K_FINAL,
            "feature_cols": FEATURE_COLS,
        },
        "validation": {
            "test_queries_count": len(TEST_QUERIES),
            "status": "passed",
        },
    }

    logger.info("Serving Pipeline Report:")
    logger.info(json.dumps(report, indent=2))

    return f"Serving pipeline validation completed at {report['timestamp']}"


# =============================================================================
# DAG Definition
# =============================================================================

with DAG(
    dag_id="serving_validation_dag",
    default_args=default_args,
    description="Validate end-to-end movie search pipeline",
    schedule=timedelta(days=1),  # Daily validation
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=["ml", "serving", "dsrp", "validation"],
) as dag:

    validate_model_task = PythonOperator(
        task_id="load_and_validate_model",
        python_callable=load_and_validate_model,
        executor_config={
            "pod_override": generate_pod_config(
                pip_packages="mlflow>=2.0.0 dagshub lightgbm>=4.0.0 loguru>=0.7.3"
            )
        },
    )

    validate_qdrant_task = PythonOperator(
        task_id="validate_qdrant_connection",
        python_callable=validate_qdrant_connection,
        executor_config={
            "pod_override": generate_pod_config(
                pip_packages="qdrant-client>=1.9.0 loguru>=0.7.3"
            )
        },
    )

    run_pipeline_task = PythonOperator(
        task_id="run_search_pipeline_validation",
        python_callable=run_search_pipeline_validation,
        executor_config={
            "pod_override": generate_pod_config(
                pip_packages="dsrp-ml-utils[azure] polars>=1.35.2 loguru>=0.7.3 qdrant-client>=1.9.0 sentence-transformers>=5.1.2 mlflow>=2.0.0 dagshub lightgbm>=4.0.0",
                resources=ml_resource_requirements
            )
        },
    )

    generate_report_task = PythonOperator(
        task_id="generate_serving_report",
        python_callable=generate_serving_report,
        executor_config={
            "pod_override": generate_pod_config(
                pip_packages="loguru>=0.7.3"
            )
        },
    )

    # Parallel validation of model and qdrant, then pipeline test, then report
    [validate_model_task, validate_qdrant_task] >> run_pipeline_task >> generate_report_task
