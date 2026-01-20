"""
Synthetic Queries DAG - DSRP ML Pipeline

Generates synthetic queries and creates LTR dataset.
Can run as standalone script or Airflow DAG.
"""

import os
import json
import requests
from datetime import datetime, timedelta
from itertools import product
from pathlib import Path
from typing import List, Dict, Any

import numpy as np
import polars as pl

# Configuration from environment
DATA_DIR = os.environ.get("DSRP_DATA_DIR", str(Path(__file__).parent.parent.parent / "data"))
OLLAMA_URL = os.environ.get("DSRP_OLLAMA_URL", "http://localhost:11434/api/generate")
OLLAMA_MODEL = os.environ.get("DSRP_OLLAMA_MODEL", "llama3.2:3b")
EMBEDDING_MODEL = os.environ.get("DSRP_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
TOP_K_CANDIDATES = int(os.environ.get("LTR_TOP_K_CANDIDATES", "100"))
N_LABEL_BINS = int(os.environ.get("LTR_N_LABEL_BINS", "5"))


# =============================================================================
# Helper Functions
# =============================================================================

def query_ollama(prompt: str) -> str:
    """Query Ollama API and return generated text."""
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.8, "top_p": 0.9, "num_predict": 200},
    }
    try:
        response = requests.post(OLLAMA_URL, json=payload, timeout=30)
        response.raise_for_status()
        return response.json().get("response", "")
    except requests.exceptions.RequestException as e:
        print(f"Ollama error: {e}")
        return ""


def parse_queries_from_response(response: str) -> List[str]:
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
        if line and 5 < len(line) < 100:
            queries.append(line.lower())
    return queries


def normalize_embeddings(embs: np.ndarray) -> np.ndarray:
    """Normalize embeddings for cosine similarity."""
    norms = np.linalg.norm(embs, axis=1, keepdims=True)
    return embs / (norms + 1e-9)


# =============================================================================
# Task Functions
# =============================================================================

def load_metadata() -> Dict[str, Any]:
    """Load dataset metadata for query generation."""
    metadata_path = os.path.join(DATA_DIR, "dataset_metadata.json")

    if os.path.exists(metadata_path):
        with open(metadata_path, "r") as f:
            metadata = json.load(f)
        print(f"Loaded metadata: {len(metadata.get('top_genres', []))} genres")
        return metadata

    print("Metadata not found, extracting from database...")
    db_path = os.path.join(DATA_DIR, "complete_imdb_database.parquet")
    movies_db = pl.read_parquet(db_path)

    genre_df = (
        movies_db
        .select(pl.col("genres").str.split(",").alias("genres_list"))
        .explode("genres_list")
        .with_columns(pl.col("genres_list").str.strip_chars().alias("genre"))
        .filter(pl.col("genre").is_not_null() & (pl.col("genre") != ""))
    )

    top_genres = genre_df.group_by("genre").len().sort("len", descending=True).head(15)["genre"].to_list()
    years = movies_db["year"].drop_nulls()
    decades = sorted({int(y) // 10 * 10 for y in years})

    return {"top_genres": top_genres, "decades": decades, "total_movies": movies_db.height}


def generate_llm_queries(metadata: Dict[str, Any] = None) -> str:
    """Generate queries using Ollama LLM."""
    metadata = metadata or load_metadata()
    top_genres = metadata.get("top_genres", [])[:8]

    test_response = query_ollama("Say 'OK' in one word.")
    ollama_available = bool(test_response)
    print(f"Ollama available: {ollama_available}")

    llm_queries = []

    if ollama_available:
        print("Generating genre-based queries...")
        for genre in top_genres:
            prompt = f"""Generate 5 diverse movie search queries for: {genre} movies
Requirements: Natural language, 3-12 words, numbered list only.
Generate 5 queries:"""
            response = query_ollama(prompt)
            for q in parse_queries_from_response(response)[:5]:
                llm_queries.append({
                    "query_text": q, "intent_type": "llm_generated",
                    "category": f"{genre} movies", "emphasis": "neutral",
                    "genre": genre, "decade": None,
                })

        print("Generating mood-based queries...")
        moods = ["relaxing weekend", "date night", "family movie night", "mind-bending", "adrenaline rush"]
        for mood in moods:
            prompt = f"""Generate 5 diverse movie search queries for: {mood}
Requirements: Natural language, 3-12 words, numbered list only.
Generate 5 queries:"""
            response = query_ollama(prompt)
            for q in parse_queries_from_response(response)[:5]:
                llm_queries.append({
                    "query_text": q, "intent_type": "llm_generated",
                    "category": mood, "emphasis": "neutral",
                    "genre": None, "decade": None,
                })

    print(f"Generated {len(llm_queries)} LLM queries")

    output_path = os.path.join(DATA_DIR, "llm_queries.json")
    with open(output_path, "w") as f:
        json.dump(llm_queries, f, indent=2)

    return output_path


def generate_template_queries(metadata: Dict[str, Any] = None) -> str:
    """Generate template-based queries."""
    metadata = metadata or load_metadata()
    top_genres = metadata.get("top_genres", [])
    decades = metadata.get("decades", [])

    queries = []

    templates_genre = [
        ("best {genre} movies", "genre_only", "rating"),
        ("top rated {genre} movies", "genre_only", "rating"),
        ("popular {genre} movies", "genre_only", "popularity"),
        ("classic {genre} films", "genre_only", "neutral"),
    ]

    for g in top_genres:
        for tpl, intent_type, emphasis in templates_genre:
            queries.append({
                "query_text": tpl.format(genre=g.lower()),
                "intent_type": intent_type, "genre": g,
                "decade": None, "emphasis": emphasis, "category": "template",
            })

    templates_genre_decade = [
        ("best {genre} movies from the {decade}s", "genre_decade", "rating"),
        ("popular {genre} films of the {decade}s", "genre_decade", "popularity"),
    ]

    for g, d in product(top_genres[:10], decades[-5:]):
        for tpl, intent_type, emphasis in templates_genre_decade:
            queries.append({
                "query_text": tpl.format(genre=g.lower(), decade=d),
                "intent_type": intent_type, "genre": g,
                "decade": d, "emphasis": emphasis, "category": "template",
            })

    print(f"Generated {len(queries)} template queries")

    output_path = os.path.join(DATA_DIR, "template_queries.json")
    with open(output_path, "w") as f:
        json.dump(queries, f, indent=2)

    return output_path


def combine_queries() -> str:
    """Combine and deduplicate queries."""
    llm_path = os.path.join(DATA_DIR, "llm_queries.json")
    template_path = os.path.join(DATA_DIR, "template_queries.json")

    with open(llm_path, "r") as f:
        llm_queries = json.load(f)
    with open(template_path, "r") as f:
        template_queries = json.load(f)

    all_queries = llm_queries + template_queries

    seen = set()
    unique_queries = []
    for q in all_queries:
        text = q["query_text"].lower().strip()
        if text not in seen:
            seen.add(text)
            unique_queries.append(q)

    for i, q in enumerate(unique_queries, start=1):
        q["query_id"] = i

    print(f"Combined {len(all_queries)} queries, {len(unique_queries)} unique")

    output_path = os.path.join(DATA_DIR, "all_queries.json")
    with open(output_path, "w") as f:
        json.dump(unique_queries, f, indent=2)

    return output_path


def retrieve_candidates() -> str:
    """Retrieve top-K candidates for each query."""
    from sentence_transformers import SentenceTransformer

    queries_path = os.path.join(DATA_DIR, "all_queries.json")
    with open(queries_path, "r") as f:
        queries = json.load(f)

    db_path = os.path.join(DATA_DIR, "complete_imdb_database.parquet")
    emb_path = os.path.join(DATA_DIR, "movie_embs.npy")

    movies_db = pl.read_parquet(db_path)
    if "imdb_votes_log" not in movies_db.columns:
        movies_db = movies_db.with_columns(pl.col("imdb_votes").log1p().alias("imdb_votes_log"))

    embeddings = np.load(emb_path).astype("float32")
    emb_norm = normalize_embeddings(embeddings)

    model = SentenceTransformer(EMBEDDING_MODEL)

    print(f"Retrieving top-{TOP_K_CANDIDATES} candidates for {len(queries)} queries...")

    all_candidates = []
    for i, q in enumerate(queries):
        if (i + 1) % 50 == 0:
            print(f"  Processing query {i + 1}/{len(queries)}")

        q_emb = model.encode([q["query_text"]]).astype("float32")[0]
        q_emb = q_emb / (np.linalg.norm(q_emb) + 1e-9)

        scores = emb_norm @ q_emb
        k = min(TOP_K_CANDIDATES, scores.shape[0])
        idxs = np.argpartition(-scores, k)[:k]
        idxs = idxs[np.argsort(-scores[idxs])]

        for idx in idxs:
            row = movies_db.row(idx, named=True)
            all_candidates.append({
                "query_id": q["query_id"],
                "query_text": q["query_text"],
                "emphasis": q.get("emphasis", "neutral"),
                "imdb_id": row["imdb_id"],
                "title": row["title"],
                "sim_embedding": float(scores[idx]),
                "imdb_rating": row["imdb_rating"],
                "imdb_votes_log": row.get("imdb_votes_log", 0),
                "year": row["year"],
                "genres": row["genres"],
            })

    print(f"Retrieved {len(all_candidates)} total candidates")

    output_path = os.path.join(DATA_DIR, "ltr_candidates.parquet")
    pl.DataFrame(all_candidates).write_parquet(output_path)

    return output_path


def compute_relevance_scores() -> str:
    """Compute relevance scores and assign labels."""
    candidates_path = os.path.join(DATA_DIR, "ltr_candidates.parquet")
    candidates_df = pl.read_parquet(candidates_path)

    def compute_score(emphasis: str) -> pl.Expr:
        w_sim, w_rating, w_votes = 0.4, 0.4, 0.2
        if emphasis == "rating":
            w_sim, w_rating, w_votes = 0.3, 0.5, 0.2
        elif emphasis == "popularity":
            w_sim, w_rating, w_votes = 0.3, 0.2, 0.5
        return (
            w_sim * pl.col("sim_embedding") +
            w_rating * (pl.col("imdb_rating") / 10.0) +
            w_votes * (pl.col("imdb_votes_log") / 15.0)
        )

    ltr_chunks = []
    for emphasis in ["neutral", "rating", "popularity"]:
        chunk = candidates_df.filter(pl.col("emphasis") == emphasis)
        if not chunk.is_empty():
            chunk = chunk.with_columns(compute_score(emphasis).alias("rel_score"))
            ltr_chunks.append(chunk)

    ltr_df = pl.concat(ltr_chunks) if ltr_chunks else candidates_df.with_columns(compute_score("neutral").alias("rel_score"))

    print("Assigning relevance labels...")
    final_chunks = []

    for qid in ltr_df["query_id"].unique().to_list():
        q_df = ltr_df.filter(pl.col("query_id") == qid)
        q_df = q_df.sort("rel_score", descending=True).with_row_index("rank")

        n = q_df.height
        if n == 0:
            continue

        bin_size = max(1, n // N_LABEL_BINS)
        bucket_expr = pl.col("rank") // bin_size
        bucket_expr = pl.when(bucket_expr > (N_LABEL_BINS - 1)).then(N_LABEL_BINS - 1).otherwise(bucket_expr)

        q_df = q_df.with_columns(bucket_expr.alias("bucket"))
        q_df = q_df.with_columns((N_LABEL_BINS - 1 - pl.col("bucket")).cast(pl.Int32).alias("label")).drop(["rank", "bucket"])

        final_chunks.append(q_df)

    final_df = pl.concat(final_chunks).drop("emphasis")

    output_path = os.path.join(DATA_DIR, "ltr_imdb_dataset.parquet")
    final_df.write_parquet(output_path)

    print(f"Created LTR dataset: {final_df.height} samples, {final_df['query_id'].n_unique()} queries")
    return output_path


def validate_ltr_dataset() -> Dict[str, Any]:
    """Validate the generated LTR dataset."""
    dataset_path = os.path.join(DATA_DIR, "ltr_imdb_dataset.parquet")
    ltr_df = pl.read_parquet(dataset_path)

    label_dist = ltr_df.group_by("label").len().sort("label").to_dicts()

    validation = {
        "total_samples": ltr_df.height,
        "unique_queries": ltr_df["query_id"].n_unique(),
        "candidates_per_query": ltr_df.height // ltr_df["query_id"].n_unique(),
        "label_distribution": label_dist,
    }

    print(f"Validation: {json.dumps(validation, indent=2)}")
    return validation


# =============================================================================
# Airflow DAG (optional)
# =============================================================================

try:
    from airflow import DAG
    from airflow.operators.python import PythonOperator

    default_args = {
        "owner": "dsrp-ml",
        "depends_on_past": False,
        "retries": 2,
        "retry_delay": timedelta(minutes=5),
    }

    with DAG(
        dag_id="synthetic_queries",
        default_args=default_args,
        description="Generate synthetic queries and LTR dataset",
        schedule=None,
        start_date=datetime(2024, 1, 1),
        catchup=False,
        tags=["dsrp", "ltr", "synthetic-data"],
    ) as dag:

        t1 = PythonOperator(task_id="load_metadata", python_callable=load_metadata)
        t2 = PythonOperator(task_id="generate_llm_queries", python_callable=generate_llm_queries, execution_timeout=timedelta(hours=1))
        t3 = PythonOperator(task_id="generate_template_queries", python_callable=generate_template_queries)
        t4 = PythonOperator(task_id="combine_queries", python_callable=combine_queries)
        t5 = PythonOperator(task_id="retrieve_candidates", python_callable=retrieve_candidates, execution_timeout=timedelta(hours=2))
        t6 = PythonOperator(task_id="compute_relevance_scores", python_callable=compute_relevance_scores)
        t7 = PythonOperator(task_id="validate_ltr_dataset", python_callable=validate_ltr_dataset)

        t1 >> [t2, t3] >> t4 >> t5 >> t6 >> t7

except ImportError:
    dag = None


# =============================================================================
# Standalone execution
# =============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Synthetic Queries Pipeline")
    parser.add_argument("--step", choices=["all", "metadata", "llm", "template", "combine", "retrieve", "score", "validate"], default="all")
    args = parser.parse_args()

    metadata = None
    if args.step in ["all", "metadata", "llm", "template"]:
        metadata = load_metadata()

    if args.step in ["all", "llm"]:
        generate_llm_queries(metadata)

    if args.step in ["all", "template"]:
        generate_template_queries(metadata)

    if args.step in ["all", "combine"]:
        combine_queries()

    if args.step in ["all", "retrieve"]:
        retrieve_candidates()

    if args.step in ["all", "score"]:
        compute_relevance_scores()

    if args.step in ["all", "validate"]:
        validate_ltr_dataset()
