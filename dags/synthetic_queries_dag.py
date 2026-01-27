"""
Synthetic Queries Generation DAG for LTR Dataset.

This DAG generates synthetic movie search queries using Groq API (qwen/qwen3-32b),
retrieves candidates via embedding similarity, and calculates relevance scores.

Prerequisites:
- complete_imdb_database.parquet in Azure Blob Storage
- movie_embs.npy embeddings in Azure Blob Storage
- GROQ_API_KEY in Airflow Variables

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

# Heavy ML resources for tasks requiring sentence-transformers, embeddings
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

GROQ_MODEL = "qwen/qwen3-32b"
TOP_K_CANDIDATES = 100
N_LABEL_BINS = 5


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


def write_parquet_to_blob(data, container: str, blob_name: str):
    """Write parquet file to Azure Blob Storage."""
    from io import BytesIO

    blob_service_client = get_blob_service_client()
    blob_client = blob_service_client.get_blob_client(
        container=container,
        blob=blob_name
    )
    buffer = BytesIO()
    data.write_parquet(buffer)
    blob_client.upload_blob(buffer.getvalue(), overwrite=True)


# =============================================================================
# Task Functions
# =============================================================================

def generate_queries_with_groq():
    """Generate synthetic movie search queries using Groq API with qwen/qwen3-32b."""
    import requests
    import polars as pl
    from loguru import logger
    from dsrp_ml_utils import extract_top_genres, extract_decades, generate_template_queries

    logger.info("Starting synthetic query generation with Groq API")

    # Load movies database
    movies_df = read_parquet_from_blob("ml-pipeline-data", "airflow-prod/complete_imdb_database.parquet")
    logger.info(f"Loaded {movies_df.height} movies")

    # Extract metadata
    top_genres = extract_top_genres(movies_df, top_n=15)
    decades = extract_decades(movies_df)
    logger.info(f"Top genres: {top_genres}")
    logger.info(f"Decades: {decades}")

    # Get sample popular movies for context
    sample_movies = (
        movies_df
        .filter(pl.col("imdb_votes") > 50000)
        .sort("imdb_rating", descending=True)
        .head(50)
        .select(["title", "genres", "year"])
    )
    sample_titles = sample_movies["title"].to_list()[:20]

    # Groq API configuration
    groq_api_key = Variable.get("groq_api_key")
    groq_url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {groq_api_key}",
        "Content-Type": "application/json"
    }

    def query_groq(prompt: str) -> str:
        """Query Groq API with qwen/qwen3-32b model."""
        payload = {
            "model": GROQ_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.8,
            "max_tokens": 200,
        }
        try:
            response = requests.post(groq_url, json=payload, headers=headers, timeout=30)
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"Groq API error: {e}")
            return ""

    def parse_queries_from_response(response: str) -> list[str]:
        """Parse numbered list of queries from LLM response."""
        queries = []
        for line in response.strip().split("\n"):
            line = line.strip()
            if line and line[0].isdigit():
                parts = line.split(".", 1) if "." in line[:3] else line.split(")", 1)
                if len(parts) > 1:
                    line = parts[1].strip()
            elif line.startswith("- "):
                line = line[2:].strip()

            line = line.strip("\"'")
            if line and len(line) > 5 and len(line) < 100:
                queries.append(line.lower())
        return queries

    def generate_llm_queries(category: str, context: str, num_queries: int = 5) -> list[dict]:
        """Generate diverse queries using LLM for a specific category."""
        prompt = f"""You are helping create a movie search dataset. Generate {num_queries} diverse, natural movie search queries for: {category}

Context: {context}

Requirements:
- Each query should be how a real user would search for movies
- Vary the phrasing (some formal, some casual)
- Include different intents: browsing, specific mood, recommendations
- Keep queries between 3-12 words
- Output ONLY the queries as a numbered list, nothing else

Generate {num_queries} queries:"""

        response = query_groq(prompt)
        queries = parse_queries_from_response(response)

        return [
            {
                "query_text": q,
                "intent_type": "llm_generated",
                "category": category,
                "emphasis": "neutral",
                "genre": None,
                "decade": None,
            }
            for q in queries[:num_queries]
        ]

    # Generate LLM queries
    llm_queries = []

    # Genre-based queries
    logger.info("Generating genre-based queries...")
    for genre in top_genres[:8]:
        queries = generate_llm_queries(
            category=f"{genre} movies",
            context=f"Genre: {genre}. Popular examples exist in our database.",
            num_queries=5
        )
        for q in queries:
            q["genre"] = genre
        llm_queries.extend(queries)

    # Mood-based queries
    logger.info("Generating mood-based queries...")
    moods = [
        ("relaxing weekend", "Movies for a relaxing weekend"),
        ("date night", "Romantic or engaging movies for couples"),
        ("family movie night", "Family-friendly movies"),
        ("mind-bending", "Complex, thought-provoking films"),
        ("adrenaline rush", "Action-packed, exciting movies"),
        ("hidden gems", "Underrated quality films"),
    ]

    for mood, context in moods:
        queries = generate_llm_queries(category=mood, context=context, num_queries=5)
        llm_queries.extend(queries)

    # Similarity queries
    logger.info("Generating similarity queries...")
    for title in sample_titles[:8]:
        queries = generate_llm_queries(
            category=f"movies similar to {title}",
            context=f"Reference movie: {title}",
            num_queries=3
        )
        for q in queries:
            q["intent_type"] = "similarity_search"
        llm_queries.extend(queries)

    logger.info(f"Total LLM queries generated: {len(llm_queries)}")

    # Generate template queries
    template_queries = generate_template_queries(top_genres, decades)
    logger.info(f"Template queries generated: {len(template_queries)}")

    # Combine and deduplicate
    all_queries = llm_queries + template_queries
    seen = set()
    unique_queries = []
    for q in all_queries:
        text = q["query_text"].lower().strip()
        if text not in seen:
            seen.add(text)
            unique_queries.append(q)

    # Assign query IDs
    for i, q in enumerate(unique_queries, start=1):
        q["query_id"] = i

    # Create DataFrame
    queries_df = pl.DataFrame(
        unique_queries,
        schema={
            "query_text": pl.Utf8,
            "intent_type": pl.Utf8,
            "category": pl.Utf8,
            "emphasis": pl.Utf8,
            "genre": pl.Utf8,
            "decade": pl.Int64,
            "query_id": pl.Int64,
        }
    )

    logger.info(f"Total unique queries: {queries_df.height}")

    # Save queries to blob
    write_parquet_to_blob(
        queries_df,
        "ml-pipeline-data",
        "airflow-prod/synthetic_queries.parquet"
    )

    return f"Generated {queries_df.height} unique synthetic queries"


def retrieve_candidates_and_score():
    """Retrieve candidates for each query and compute relevance scores."""
    import numpy as np
    import polars as pl
    from io import BytesIO
    from sentence_transformers import SentenceTransformer
    from loguru import logger
    from dsrp_ml_utils import (
        normalize_embeddings,
        get_candidates_for_query,
        compute_relevance_score,
        assign_relevance_labels,
        DEFAULT_EMBEDDING_MODEL,
    )

    logger.info("Loading data and models...")

    # Load queries
    queries_df = read_parquet_from_blob("ml-pipeline-data", "airflow-prod/synthetic_queries.parquet")
    logger.info(f"Loaded {queries_df.height} queries")

    # Load movies database
    movies_df = read_parquet_from_blob("ml-pipeline-data", "airflow-prod/complete_imdb_database.parquet")

    # Add imdb_votes_log if not present
    if "imdb_votes_log" not in movies_df.columns:
        movies_df = movies_df.with_columns(
            pl.col("imdb_votes").log1p().alias("imdb_votes_log")
        )

    # Load embeddings
    blob_service_client = get_blob_service_client()
    emb_blob_client = blob_service_client.get_blob_client(
        container="ml-pipeline-data",
        blob="airflow-prod/movie_embs.npy"
    )
    movie_embs = np.load(BytesIO(emb_blob_client.download_blob().readall())).astype("float32")
    movie_embs_norm = normalize_embeddings(movie_embs)
    logger.info(f"Loaded embeddings: {movie_embs.shape}")

    # Load sentence transformer model
    model = SentenceTransformer(DEFAULT_EMBEDDING_MODEL)
    logger.info(f"Loaded model: {DEFAULT_EMBEDDING_MODEL}")

    # Retrieve candidates for each query
    logger.info(f"Retrieving top-{TOP_K_CANDIDATES} candidates for {queries_df.height} queries...")

    all_candidates = []
    for q_row in queries_df.iter_rows(named=True):
        cand = get_candidates_for_query(
            query_id=q_row["query_id"],
            query_text=q_row["query_text"],
            movies_df=movies_df,
            movie_embs_norm=movie_embs_norm,
            model=model,
            k=TOP_K_CANDIDATES,
        )
        all_candidates.append(cand)

    candidates_df = pl.concat(all_candidates)
    logger.info(f"Total candidates: {candidates_df.height}")

    # Compute relevance scores
    logger.info("Computing relevance scores and labels...")

    queries_by_id = {row["query_id"]: row for row in queries_df.iter_rows(named=True)}
    ltr_chunks = []

    for qid, q_row in queries_by_id.items():
        cand = candidates_df.filter(pl.col("query_id") == qid)
        if cand.is_empty():
            continue

        # Add relevance score
        cand = compute_relevance_score(cand, emphasis=q_row.get("emphasis", "neutral"))

        # Add discrete labels
        cand = assign_relevance_labels(cand, n_bins=N_LABEL_BINS)

        ltr_chunks.append(cand)

    ltr_df = pl.concat(ltr_chunks)
    logger.info(f"LTR dataset size: {ltr_df.height}")

    # Save LTR dataset
    write_parquet_to_blob(
        ltr_df,
        "ml-pipeline-data",
        "airflow-prod/ltr_synthetic_dataset.parquet"
    )

    return f"Created LTR dataset with {ltr_df.height} query-document pairs"


# =============================================================================
# DAG Definition
# =============================================================================

with DAG(
    dag_id="synthetic_queries_dag",
    default_args=default_args,
    description="Generate synthetic queries and LTR dataset using Groq API",
    schedule=timedelta(days=7),  # Weekly
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=["ml", "ltr", "dsrp", "groq"],
) as dag:

    generate_queries_task = PythonOperator(
        task_id="generate_queries_with_groq",
        python_callable=generate_queries_with_groq,
        executor_config={"pod_override": generate_pod_config()},
    )

    retrieve_and_score_task = PythonOperator(
        task_id="retrieve_candidates_and_score",
        python_callable=retrieve_candidates_and_score,
        executor_config={"pod_override": generate_pod_config(resources=ml_resource_requirements)},
    )

    generate_queries_task >> retrieve_and_score_task
