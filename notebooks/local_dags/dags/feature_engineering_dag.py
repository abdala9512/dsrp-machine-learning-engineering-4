"""
Feature Engineering DAG - DSRP ML Pipeline

Generates embeddings and derived features.
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
EMBEDDING_MODEL = os.environ.get("DSRP_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
EMBEDDING_BATCH_SIZE = int(os.environ.get("EMBEDDING_BATCH_SIZE", "64"))


# =============================================================================
# Task Functions
# =============================================================================

def load_and_combine_data() -> str:
    """Load and combine IMDB base data with OMDB enriched data."""
    movies_path = os.path.join(DATA_DIR, "movies_base.parquet")
    omdb_path = os.path.join(DATA_DIR, "omdb_raw.jsonl")

    print(f"Loading movies from {movies_path}")
    movies_base = pl.read_parquet(movies_path)

    print(f"Loading OMDB data from {omdb_path}")
    with open(omdb_path, "r") as f:
        omdb_records = [json.loads(line) for line in f if line.strip()]

    omdb_data = pl.DataFrame(
        [
            [
                r["imdb_id"],
                r["raw"].get("Runtime"),
                r["raw"].get("Director"),
                r["raw"].get("Actors"),
                r["raw"].get("Plot"),
                r["raw"].get("Country"),
                r["raw"].get("Language"),
            ]
            for r in omdb_records
        ],
        schema={
            "imdb_id": str,
            "Runtime": str,
            "Director": str,
            "Actors": str,
            "Plot": str,
            "Country": str,
            "Language": str,
        },
        orient="row",
    )

    complete_db = movies_base.join(omdb_data, on="imdb_id")
    print(f"Combined {complete_db.height} movies")

    output_path = os.path.join(DATA_DIR, "complete_imdb_database.parquet")
    complete_db.write_parquet(output_path)
    print(f"Saved to {output_path}")

    return output_path


def generate_embeddings(db_path: str = None) -> str:
    """Generate embeddings using sentence-transformers."""
    from sentence_transformers import SentenceTransformer

    db_path = db_path or os.path.join(DATA_DIR, "complete_imdb_database.parquet")

    print(f"Loading database from {db_path}")
    movies_db = pl.read_parquet(db_path)

    print(f"Loading embedding model: {EMBEDDING_MODEL}")
    model = SentenceTransformer(EMBEDDING_MODEL)
    print(f"Embedding dimension: {model.get_sentence_embedding_dimension()}")

    texts = (movies_db["title"] + ". " + movies_db["Plot"].fill_null("")).to_list()

    print(f"Generating embeddings for {len(texts)} movies...")
    embeddings = model.encode(texts, batch_size=EMBEDDING_BATCH_SIZE, show_progress_bar=True)
    embeddings = np.asarray(embeddings, dtype="float32")

    output_path = os.path.join(DATA_DIR, "movie_embs.npy")
    np.save(output_path, embeddings)
    print(f"Saved embeddings {embeddings.shape} to {output_path}")

    return output_path


def add_derived_features(db_path: str = None) -> str:
    """Add derived features to the movie database."""
    db_path = db_path or os.path.join(DATA_DIR, "complete_imdb_database.parquet")

    print(f"Loading database from {db_path}")
    movies_db = pl.read_parquet(db_path)

    current_year = datetime.now().year

    print("Adding derived features...")
    movies_with_features = movies_db.with_columns([
        pl.col("imdb_votes").log1p().alias("imdb_votes_log"),
        ((pl.col("year") - pl.col("year").mean()) / pl.col("year").std()).alias("year_norm"),
        (current_year - pl.col("year")).alias("movie_age"),
        pl.col("Plot").str.len_chars().fill_null(0).alias("plot_length"),
        pl.col("genres").str.contains("Action").cast(pl.Int8).alias("genre_action"),
    ])

    output_path = os.path.join(DATA_DIR, "complete_imdb_database_features.parquet")
    movies_with_features.write_parquet(output_path)
    print(f"Saved database with features to {output_path}")

    return output_path


def extract_metadata(db_path: str = None) -> Dict[str, Any]:
    """Extract metadata for query generation."""
    db_path = db_path or os.path.join(DATA_DIR, "complete_imdb_database_features.parquet")

    print(f"Loading database from {db_path}")
    movies_db = pl.read_parquet(db_path)

    genre_df = (
        movies_db
        .select(pl.col("genres").str.split(",").alias("genres_list"))
        .explode("genres_list")
        .with_columns(pl.col("genres_list").str.strip_chars().alias("genre"))
        .filter(pl.col("genre").is_not_null() & (pl.col("genre") != ""))
    )

    top_genres = (
        genre_df.group_by("genre").len().sort("len", descending=True).head(15)["genre"].to_list()
    )

    years = movies_db["year"].drop_nulls()
    decades = sorted({int(y) // 10 * 10 for y in years})

    popular_movies = (
        movies_db
        .filter(pl.col("imdb_votes") > 50000)
        .sort("imdb_rating", descending=True)
        .head(50)
        .select(["imdb_id", "title", "genres", "year"])
        .to_dicts()
    )

    metadata = {
        "top_genres": top_genres,
        "decades": decades,
        "popular_movies": popular_movies,
        "total_movies": movies_db.height,
        "year_range": [int(movies_db["year"].min()), int(movies_db["year"].max())],
    }

    metadata_path = os.path.join(DATA_DIR, "dataset_metadata.json")
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2)
    print(f"Saved metadata to {metadata_path}")

    return metadata


def validate_features() -> Dict[str, Any]:
    """Validate feature engineering outputs."""
    features_path = os.path.join(DATA_DIR, "complete_imdb_database_features.parquet")
    embeddings_path = os.path.join(DATA_DIR, "movie_embs.npy")

    movies_db = pl.read_parquet(features_path)
    embeddings = np.load(embeddings_path)

    validation = {
        "movies_count": movies_db.height,
        "embeddings_shape": list(embeddings.shape),
        "embeddings_match": movies_db.height == embeddings.shape[0],
        "null_plots": movies_db.filter(pl.col("Plot").is_null()).height,
    }

    print(f"Validation: {json.dumps(validation, indent=2)}")

    if not validation["embeddings_match"]:
        raise ValueError("Embeddings count does not match movies count!")

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
        dag_id="feature_engineering",
        default_args=default_args,
        description="Generate embeddings and derived features",
        schedule=None,
        start_date=datetime(2024, 1, 1),
        catchup=False,
        tags=["dsrp", "feature-engineering"],
    ) as dag:

        t1 = PythonOperator(task_id="load_and_combine_data", python_callable=load_and_combine_data)
        t2 = PythonOperator(
            task_id="generate_embeddings",
            python_callable=generate_embeddings,
            execution_timeout=timedelta(hours=2),
        )
        t3 = PythonOperator(task_id="add_derived_features", python_callable=add_derived_features)
        t4 = PythonOperator(task_id="extract_metadata", python_callable=extract_metadata)
        t5 = PythonOperator(task_id="validate_features", python_callable=validate_features)

        t1 >> [t2, t3]
        t3 >> t4
        [t2, t3] >> t5

except ImportError:
    dag = None


# =============================================================================
# Standalone execution
# =============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Feature Engineering Pipeline")
    parser.add_argument("--step", choices=["all", "combine", "embeddings", "features", "metadata", "validate"], default="all")
    args = parser.parse_args()

    if args.step in ["all", "combine"]:
        load_and_combine_data()

    if args.step in ["all", "embeddings"]:
        generate_embeddings()

    if args.step in ["all", "features"]:
        add_derived_features()

    if args.step in ["all", "metadata"]:
        extract_metadata()

    if args.step in ["all", "validate"]:
        validate_features()
