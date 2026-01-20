"""
Data Collection DAG - DSRP ML Pipeline

Downloads and processes IMDB + OMDB data.
Can run as standalone script or Airflow DAG.
"""

import os
import json
import urllib.request
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any

import polars as pl
import aiohttp
import orjson

# Configuration from environment (works locally and in k8s)
DATA_DIR = os.environ.get("DSRP_DATA_DIR", str(Path(__file__).parent.parent.parent / "data"))
IMDB_BASICS_URL = "https://datasets.imdbws.com/title.basics.tsv.gz"
IMDB_RATINGS_URL = "https://datasets.imdbws.com/title.ratings.tsv.gz"
OMDB_API_URL = "https://www.omdbapi.com/"
MIN_VOTES_THRESHOLD = 1000
OMDB_CONCURRENCY = int(os.environ.get("OMDB_CONCURRENCY", "20"))
OMDB_MAX_RETRIES = 5


# =============================================================================
# Task Functions
# =============================================================================

def download_imdb_basics() -> str:
    """Download IMDB title.basics dataset."""
    output_path = os.path.join(DATA_DIR, "title.basics.tsv.gz")
    os.makedirs(DATA_DIR, exist_ok=True)

    print(f"Downloading IMDB basics to {output_path}")
    urllib.request.urlretrieve(IMDB_BASICS_URL, output_path)
    print(f"Downloaded: {os.path.getsize(output_path)} bytes")

    return output_path


def download_imdb_ratings() -> str:
    """Download IMDB title.ratings dataset."""
    output_path = os.path.join(DATA_DIR, "title.ratings.tsv.gz")
    os.makedirs(DATA_DIR, exist_ok=True)

    print(f"Downloading IMDB ratings to {output_path}")
    urllib.request.urlretrieve(IMDB_RATINGS_URL, output_path)
    print(f"Downloaded: {os.path.getsize(output_path)} bytes")

    return output_path


def process_imdb_data(basics_path: str = None, ratings_path: str = None) -> str:
    """Process and filter IMDB data."""
    basics_path = basics_path or os.path.join(DATA_DIR, "title.basics.tsv.gz")
    ratings_path = ratings_path or os.path.join(DATA_DIR, "title.ratings.tsv.gz")

    print(f"Loading IMDB basics from {basics_path}")
    basics = pl.read_csv(
        basics_path,
        separator="\t",
        null_values=["\\N"],
        quote_char=None,
    )

    print(f"Loading IMDB ratings from {ratings_path}")
    ratings = pl.read_csv(
        ratings_path,
        separator="\t",
        null_values=["\\N"],
        quote_char=None,
    )

    print("Processing and filtering movies...")
    movies = (
        basics
        .filter(pl.col("titleType") == "movie")
        .select([
            pl.col("tconst").alias("imdb_id"),
            pl.col("primaryTitle").alias("title"),
            pl.col("startYear").cast(pl.Int32).alias("year"),
            pl.col("genres"),
        ])
        .join(
            ratings.select(["tconst", "averageRating", "numVotes"]),
            left_on="imdb_id",
            right_on="tconst",
        )
        .rename({
            "averageRating": "imdb_rating",
            "numVotes": "imdb_votes",
        })
        .filter(pl.col("imdb_votes") >= MIN_VOTES_THRESHOLD)
    )

    output_path = os.path.join(DATA_DIR, "movies_base.parquet")
    movies.write_parquet(output_path)
    print(f"Saved {movies.height} movies to {output_path}")

    # Save movie IDs for OMDB fetching
    ids_path = os.path.join(DATA_DIR, "movie_ids.txt")
    with open(ids_path, "w") as f:
        for imdb_id in movies["imdb_id"].to_list():
            f.write(f"{imdb_id}\n")

    return output_path


async def fetch_omdb_record(
    session: aiohttp.ClientSession,
    imdb_id: str,
    api_key: str,
) -> Dict[str, Any] | None:
    """Fetch a single OMDB record."""
    params = {"i": imdb_id, "apikey": api_key, "plot": "full"}

    for retry in range(OMDB_MAX_RETRIES):
        try:
            async with session.get(OMDB_API_URL, params=params) as resp:
                if resp.status == 429:
                    await asyncio.sleep(5 * (retry + 1))
                    continue
                if resp.status >= 500:
                    await asyncio.sleep(3 * (retry + 1))
                    continue
                return {"imdb_id": imdb_id, "raw": await resp.json()}
        except (asyncio.TimeoutError, Exception):
            await asyncio.sleep(2 * (retry + 1))

    return None


async def omdb_worker(
    session: aiohttp.ClientSession,
    queue: asyncio.Queue,
    jsonl_path: Path,
    write_lock: asyncio.Lock,
    checkpoint_path: Path,
    api_key: str,
):
    """Worker to fetch OMDB records."""
    while True:
        imdb_id = await queue.get()
        if imdb_id is None:
            queue.task_done()
            return

        result = await fetch_omdb_record(session, imdb_id, api_key)

        if result is not None:
            line = orjson.dumps(result).decode("utf-8") + "\n"
            async with write_lock:
                with open(jsonl_path, "a", encoding="utf-8") as f:
                    f.write(line)
                with open(checkpoint_path, "a") as f:
                    f.write(imdb_id + "\n")

        queue.task_done()


async def fetch_omdb_data_async(
    all_ids: List[str],
    output_file: str,
    checkpoint_file: str,
    api_key: str,
):
    """Main async function to fetch OMDB data."""
    jsonl_path = Path(output_file)
    checkpoint_path = Path(checkpoint_file)

    processed = set()
    if checkpoint_path.exists():
        with open(checkpoint_path, "r") as f:
            processed = set(line.strip() for line in f if line.strip())

    remaining = [i for i in all_ids if i not in processed]
    print(f"Total: {len(all_ids)}, Processed: {len(processed)}, Remaining: {len(remaining)}")

    if not remaining:
        return

    queue: asyncio.Queue = asyncio.Queue()
    write_lock = asyncio.Lock()

    for imdb_id in remaining:
        await queue.put(imdb_id)

    timeout = aiohttp.ClientTimeout(total=40)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        workers = [
            asyncio.create_task(
                omdb_worker(session, queue, jsonl_path, write_lock, checkpoint_path, api_key)
            )
            for _ in range(OMDB_CONCURRENCY)
        ]

        for _ in workers:
            await queue.put(None)

        await queue.join()

        for w in workers:
            w.cancel()

    print(f"Fetch complete. Results in {jsonl_path}")


def fetch_omdb_data() -> str:
    """Fetch OMDB data for all movies."""
    api_key = os.environ.get("OMDB_API_KEY")
    if not api_key:
        raise ValueError("OMDB_API_KEY environment variable not set")

    ids_path = os.path.join(DATA_DIR, "movie_ids.txt")
    with open(ids_path, "r") as f:
        all_ids = [line.strip() for line in f if line.strip()]

    output_path = os.path.join(DATA_DIR, "omdb_raw.jsonl")
    checkpoint_path = os.path.join(DATA_DIR, "processed_ids.txt")

    asyncio.run(fetch_omdb_data_async(all_ids, output_path, checkpoint_path, api_key))

    return output_path


def validate_data() -> Dict[str, Any]:
    """Validate the collected data."""
    movies = pl.read_parquet(os.path.join(DATA_DIR, "movies_base.parquet"))
    omdb = pl.read_ndjson(os.path.join(DATA_DIR, "omdb_raw.jsonl"))

    metrics = {
        "total_movies": movies.height,
        "total_omdb_records": omdb.height,
        "coverage": omdb.height / movies.height if movies.height > 0 else 0,
    }

    print(f"Validation: {json.dumps(metrics, indent=2)}")
    return metrics


# =============================================================================
# Airflow DAG (optional - only loads if Airflow is available)
# =============================================================================

try:
    from airflow import DAG
    from airflow.operators.python import PythonOperator

    default_args = {
        "owner": "dsrp-ml",
        "depends_on_past": False,
        "retries": 3,
        "retry_delay": timedelta(minutes=5),
    }

    with DAG(
        dag_id="data_collection",
        default_args=default_args,
        description="Collect and process IMDB + OMDB data",
        schedule=None,
        start_date=datetime(2024, 1, 1),
        catchup=False,
        tags=["dsrp", "data-collection"],
    ) as dag:

        t1 = PythonOperator(task_id="download_imdb_basics", python_callable=download_imdb_basics)
        t2 = PythonOperator(task_id="download_imdb_ratings", python_callable=download_imdb_ratings)
        t3 = PythonOperator(task_id="process_imdb_data", python_callable=process_imdb_data)
        t4 = PythonOperator(
            task_id="fetch_omdb_data",
            python_callable=fetch_omdb_data,
            execution_timeout=timedelta(hours=6),
        )
        t5 = PythonOperator(task_id="validate_data", python_callable=validate_data)

        [t1, t2] >> t3 >> t4 >> t5

except ImportError:
    dag = None


# =============================================================================
# Standalone execution
# =============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Data Collection Pipeline")
    parser.add_argument("--step", choices=["all", "download", "process", "omdb", "validate"], default="all")
    args = parser.parse_args()

    if args.step in ["all", "download"]:
        download_imdb_basics()
        download_imdb_ratings()

    if args.step in ["all", "process"]:
        process_imdb_data()

    if args.step in ["all", "omdb"]:
        fetch_omdb_data()

    if args.step in ["all", "validate"]:
        validate_data()
