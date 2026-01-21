"""
Airflow DAG for batch movie recommendation serving pipeline.

This DAG replicates the serving notebook functionality:
1. Initialize connections (Qdrant, MLflow)
2. Load models (Embeddings, LTR)
3. Load movies database
4. Process batch queries
5. Store results
"""

import json
import os
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.models import Variable

# Default DAG arguments
default_args = {
    "owner": "dsrp-mlops",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}


def init_dagshub(**context):
    """Initialize DagsHub for MLflow tracking."""
    import dagshub

    repo_owner = Variable.get("DAGSHUB_REPO_OWNER", default_var="abdala9512")
    repo_name = Variable.get(
        "DAGSHUB_REPO_NAME", default_var="dsrp-machine-learning-engineering-4"
    )

    dagshub.init(repo_owner=repo_owner, repo_name=repo_name, mlflow=True)
    print(f"DagsHub initialized for {repo_owner}/{repo_name}")


def load_embedding_model(**context):
    """Load the sentence transformer embedding model."""
    from sentence_transformers import SentenceTransformer

    model_name = Variable.get(
        "EMBEDDINGS_MODEL", default_var="sentence-transformers/all-MiniLM-L6-v2"
    )

    print(f"Loading embedding model: {model_name}")
    model = SentenceTransformer(model_name)
    print("Embedding model loaded successfully")

    # Store model path in XCom for downstream tasks
    context["ti"].xcom_push(key="embedding_model_name", value=model_name)


def load_ltr_model(**context):
    """Load the LTR model from MLflow."""
    import mlflow

    model_name = Variable.get("LTR_MODEL_NAME", default_var="ltr-dsrpflix-prd-ENE12")
    model_alias = Variable.get("LTR_MODEL_ALIAS", default_var="champion")

    model_uri = f"models:/{model_name}@{model_alias}"
    print(f"Loading LTR model: {model_uri}")

    try:
        model = mlflow.lightgbm.load_model(model_uri)
        print("LTR model loaded successfully")
    except Exception as e:
        print(f"Error loading model with alias: {e}")
        print("Falling back to latest version...")
        model_uri = f"models:/{model_name}/latest"
        model = mlflow.lightgbm.load_model(model_uri)
        print("LTR model (latest) loaded successfully")

    context["ti"].xcom_push(key="ltr_model_uri", value=model_uri)


def validate_qdrant_connection(**context):
    """Validate connection to Qdrant and check collection exists."""
    from qdrant_client import QdrantClient

    qdrant_url = Variable.get(
        "QDRANT_URL", default_var="http://qdrant-dsrp.eastus.cloudapp.azure.com:80"
    )
    collection_name = Variable.get("QDRANT_COLLECTION", default_var="imdb-movies-hybrid")

    print(f"Connecting to Qdrant at: {qdrant_url}")
    client = QdrantClient(qdrant_url)

    collections = [c.name for c in client.get_collections().collections]
    print(f"Available collections: {collections}")

    if collection_name not in collections:
        raise ValueError(
            f"Collection '{collection_name}' not found. "
            f"Run qdrant_indexing.ipynb first to create the collection."
        )

    collection_info = client.get_collection(collection_name)
    print(f"Collection '{collection_name}' has {collection_info.points_count} points")

    if collection_info.points_count == 0:
        raise ValueError(f"Collection '{collection_name}' is empty.")

    context["ti"].xcom_push(key="qdrant_url", value=qdrant_url)
    context["ti"].xcom_push(key="collection_name", value=collection_name)


def load_movies_database(**context):
    """Load the movies database from parquet file."""
    import polars as pl

    movies_path = Variable.get(
        "MOVIES_DB_PATH", default_var="data/complete_imdb_database.parquet"
    )

    print(f"Loading movies database from: {movies_path}")
    movies_db = pl.read_parquet(movies_path)

    # Add derived features
    if "imdb_votes_log" not in movies_db.columns:
        movies_db = movies_db.with_columns(
            [pl.col("imdb_votes").log1p().alias("imdb_votes_log")]
        )

    # Create full text for embeddings
    movies_db = movies_db.with_columns(
        [
            pl.concat_str([pl.col("title"), pl.col("Plot")], separator=". ")
            .fill_null("")
            .alias("full_text")
        ]
    )

    print(f"Loaded {movies_db.height} movies")
    context["ti"].xcom_push(key="movies_count", value=movies_db.height)
    context["ti"].xcom_push(key="movies_path", value=movies_path)


def process_batch_queries(**context):
    """Process batch queries through the search pipeline."""
    import mlflow
    import polars as pl
    from qdrant_client import QdrantClient
    from sentence_transformers import SentenceTransformer

    from app.serving.batch.core import search_pipeline, load_movies_db

    # Get configuration from XCom and Variables
    ti = context["ti"]
    qdrant_url = ti.xcom_pull(key="qdrant_url", task_ids="validate_qdrant_connection")
    collection_name = ti.xcom_pull(
        key="collection_name", task_ids="validate_qdrant_connection"
    )
    embedding_model_name = ti.xcom_pull(
        key="embedding_model_name", task_ids="load_embedding_model"
    )
    ltr_model_uri = ti.xcom_pull(key="ltr_model_uri", task_ids="load_ltr_model")
    movies_path = ti.xcom_pull(key="movies_path", task_ids="load_movies_database")

    # Get batch queries from Variable or use defaults
    queries_json = Variable.get(
        "BATCH_QUERIES",
        default_var=json.dumps(
            [
                "similar to 12 years a slave but more hopeful",
                "action movies with good plot twists",
                "romantic comedies from the 90s",
            ]
        ),
    )
    queries = json.loads(queries_json)

    # Load components
    print("Loading components...")
    client = QdrantClient(qdrant_url)
    embedding_model = SentenceTransformer(embedding_model_name)
    ltr_model = mlflow.lightgbm.load_model(ltr_model_uri)
    movies_db = load_movies_db(movies_path)

    # Feature columns
    feature_cols = ["sim_embedding", "imdb_rating", "imdb_votes_log"]

    # Process each query
    all_results = []
    for query in queries:
        print(f"\nProcessing query: '{query}'")

        results = search_pipeline(
            query=query,
            client=client,
            collection_name=collection_name,
            embedding_model=embedding_model,
            ltr_model=ltr_model,
            movies_df=movies_db,
            feature_cols=feature_cols,
            top_k_retrieval=100,
            top_k_final=10,
            use_hybrid=True,
        )

        if not results.is_empty():
            results = results.with_columns([pl.lit(query).alias("query")])
            all_results.append(results)
            print(f"  Found {len(results)} results")

    # Combine all results
    if all_results:
        final_results = pl.concat(all_results)
        print(f"\nTotal results: {len(final_results)}")

        # Store results count
        context["ti"].xcom_push(key="total_results", value=len(final_results))
        context["ti"].xcom_push(key="queries_processed", value=len(queries))

        return final_results.to_dicts()

    return []


def store_results(**context):
    """Store batch results to output location."""
    import polars as pl
    from datetime import datetime

    ti = context["ti"]
    results_data = ti.xcom_pull(task_ids="process_batch_queries")

    if not results_data:
        print("No results to store")
        return

    results_df = pl.DataFrame(results_data)

    # Output path
    output_dir = Variable.get("BATCH_OUTPUT_DIR", default_var="data/batch_results")
    os.makedirs(output_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = f"{output_dir}/recommendations_{timestamp}.parquet"

    results_df.write_parquet(output_path)
    print(f"Results stored to: {output_path}")

    context["ti"].xcom_push(key="output_path", value=output_path)


# Create the DAG
with DAG(
    dag_id="movie_recommendation_batch_serving",
    default_args=default_args,
    description="Batch serving pipeline for movie recommendations",
    schedule_interval=timedelta(days=1),
    start_date=datetime(2025, 1, 1),
    catchup=False,
    tags=["mlops", "recommendations", "batch"],
) as dag:

    # Task 1: Initialize DagsHub
    init_dagshub_task = PythonOperator(
        task_id="init_dagshub",
        python_callable=init_dagshub,
    )

    # Task 2: Validate Qdrant connection
    validate_qdrant_task = PythonOperator(
        task_id="validate_qdrant_connection",
        python_callable=validate_qdrant_connection,
    )

    # Task 3: Load embedding model
    load_embedding_task = PythonOperator(
        task_id="load_embedding_model",
        python_callable=load_embedding_model,
    )

    # Task 4: Load LTR model
    load_ltr_task = PythonOperator(
        task_id="load_ltr_model",
        python_callable=load_ltr_model,
    )

    # Task 5: Load movies database
    load_movies_task = PythonOperator(
        task_id="load_movies_database",
        python_callable=load_movies_database,
    )

    # Task 6: Process batch queries
    process_queries_task = PythonOperator(
        task_id="process_batch_queries",
        python_callable=process_batch_queries,
    )

    # Task 7: Store results
    store_results_task = PythonOperator(
        task_id="store_results",
        python_callable=store_results,
    )

    # Define task dependencies
    # Parallel initialization
    init_dagshub_task >> load_ltr_task
    validate_qdrant_task >> process_queries_task
    load_embedding_task >> process_queries_task
    load_ltr_task >> process_queries_task
    load_movies_task >> process_queries_task

    # Sequential processing
    process_queries_task >> store_results_task
