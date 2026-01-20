"""
ML utilities for movie recommendation pipeline.
DSRP - Machine Learning Engineering Course
"""

import json
from typing import List, Tuple
from itertools import product

import numpy as np
import polars as pl
import mlflow
from sentence_transformers import SentenceTransformer


# =============================================================================
# Default constants
# =============================================================================
DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_TOP_K_CANDIDATES = 100
DEFAULT_N_LABEL_BINS = 5


# =============================================================================
# Data loading functions
# =============================================================================
def load_imdb_database(
    movies_path: str = "data/movies_base.parquet",
    omdb_path: str = "data/omdb_raw.jsonl",
) -> pl.DataFrame:
    """Load and combine IMDB data with OMDB enrichment.

    Args:
        movies_path: Path to parquet with base movie data
        omdb_path: Path to JSONL with OMDB API data

    Returns:
        DataFrame with combined data
    """
    with open(omdb_path, 'r') as json_file:
        json_list = [json.loads(j) for j in json_file]

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
            ] for i in json_list
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

    movies_base = pl.read_parquet(movies_path)

    return movies_base.join(
        complementary_imdb_data,
        on="imdb_id"
    )


def add_derived_features(df: pl.DataFrame) -> pl.DataFrame:
    """Add derived features to movies DataFrame.

    Args:
        df: DataFrame with columns imdb_votes, year, Plot, genres

    Returns:
        DataFrame with additional features
    """
    return df.with_columns([
        pl.col("imdb_votes").log1p().alias("imdb_votes_log"),
        (
            (pl.col("year") - pl.col("year").mean()) / pl.col("year").std()
        ).alias("year_norm"),
        (2025 - pl.col("year")).alias("movie_age"),
        pl.col("Plot").str.len_chars().alias("plot_length"),
        pl.col("genres").str.contains("Action").cast(pl.Int8()).alias("genre_action"),
    ])


# =============================================================================
# Metadata extraction functions
# =============================================================================
def extract_top_genres(df: pl.DataFrame, top_n: int = 15) -> List[str]:
    """Extract most frequent genres from dataset.

    Args:
        df: DataFrame with 'genres' column (comma-separated)
        top_n: Number of genres to return

    Returns:
        List of genres ordered by frequency
    """
    genre_df = (
        df
        .select(pl.col("genres").str.split(",").alias("genres_list"))
        .explode("genres_list")
        .with_columns(
            pl.col("genres_list").str.strip_chars().alias("genre")
        )
        .filter(pl.col("genre").is_not_null() & (pl.col("genre") != ""))
    )

    top_genres = (
        genre_df
        .group_by("genre")
        .len()
        .sort("len", descending=True)
        .head(top_n)
        ["genre"]
        .to_list()
    )

    return top_genres


def extract_decades(df: pl.DataFrame) -> List[int]:
    """Extract decades present in the dataset.

    Args:
        df: DataFrame with 'year' column

    Returns:
        Sorted list of decades
    """
    years = df["year"].drop_nulls()
    return sorted({int(y) // 10 * 10 for y in years})


# =============================================================================
# Synthetic query generation functions
# =============================================================================
def generate_template_queries(
    top_genres: List[str],
    decades: List[int],
    n_genres_for_decade: int = 10,
    n_recent_decades: int = 5,
) -> List[dict]:
    """Generate queries using templates for systematic coverage.

    Args:
        top_genres: List of main genres
        decades: List of available decades
        n_genres_for_decade: Genres to use for decade queries
        n_recent_decades: Recent decades to use

    Returns:
        List of dictionaries with queries
    """
    queries = []

    # Genre-only templates
    templates_genre = [
        ("best {genre} movies", "genre_only", "rating"),
        ("top rated {genre} movies", "genre_only", "rating"),
        ("popular {genre} movies", "genre_only", "popularity"),
        ("classic {genre} films", "genre_only", "neutral"),
        ("must watch {genre} movies", "genre_only", "rating"),
        ("highly acclaimed {genre} movies", "genre_only", "rating"),
    ]

    for g in top_genres:
        for tpl, intent_type, emphasis in templates_genre:
            queries.append({
                "query_text": tpl.format(genre=g.lower()),
                "intent_type": intent_type,
                "genre": g,
                "decade": None,
                "emphasis": emphasis,
                "category": "template",
            })

    # Genre + decade queries
    templates_genre_decade = [
        ("best {genre} movies from the {decade}s", "genre_decade", "rating"),
        ("popular {genre} films of the {decade}s", "genre_decade", "popularity"),
        ("{decade}s {genre} classics", "genre_decade", "neutral"),
    ]

    for g, d in product(top_genres[:n_genres_for_decade], decades[-n_recent_decades:]):
        for tpl, intent_type, emphasis in templates_genre_decade:
            queries.append({
                "query_text": tpl.format(genre=g.lower(), decade=d),
                "intent_type": intent_type,
                "genre": g,
                "decade": d,
                "emphasis": emphasis,
                "category": "template",
            })

    # Mood-based templates
    mood_templates = [
        ("feel good {genre} movies", "mood_feel_good"),
        ("dark {genre} movies", "mood_dark"),
        ("family friendly {genre} movies", "mood_family"),
        ("intense {genre} films", "mood_intense"),
    ]

    for g in top_genres[:n_genres_for_decade]:
        for tpl, mood_tag in mood_templates:
            queries.append({
                "query_text": tpl.format(genre=g.lower()),
                "intent_type": mood_tag,
                "genre": g,
                "decade": None,
                "emphasis": "neutral",
                "category": "template",
            })

    return queries


# =============================================================================
# Candidate retrieval functions
# =============================================================================
def normalize_embeddings(embs: np.ndarray) -> np.ndarray:
    """Normalize embeddings for cosine similarity.

    Args:
        embs: Array of embeddings (N, dim)

    Returns:
        Normalized embeddings
    """
    norms = np.linalg.norm(embs, axis=1, keepdims=True)
    return embs / (norms + 1e-9)


def get_candidates_for_query(
    query_id: int,
    query_text: str,
    movies_df: pl.DataFrame,
    movie_embs_norm: np.ndarray,
    model: SentenceTransformer,
    k: int = DEFAULT_TOP_K_CANDIDATES,
) -> pl.DataFrame:
    """Retrieve top-K candidate movies for a query.

    Args:
        query_id: Query ID
        query_text: Query text
        movies_df: Movies DataFrame
        movie_embs_norm: Normalized movie embeddings
        model: Embedding model
        k: Number of candidates to return

    Returns:
        DataFrame with candidates and scores
    """
    # Encode query
    q_emb = model.encode([query_text]).astype("float32")[0]
    q_emb = q_emb / (np.linalg.norm(q_emb) + 1e-9)

    # Calculate cosine similarity
    scores = movie_embs_norm @ q_emb

    # Get top-K indices
    k = min(k, scores.shape[0])
    idxs = np.argpartition(-scores, k)[:k]
    idxs = idxs[np.argsort(-scores[idxs])]

    # Build candidates DataFrame
    cand = movies_df[idxs].with_columns(
        pl.Series("sim_embedding", scores[idxs].astype("float32")),
        pl.lit(query_id).cast(pl.Int32).alias("query_id"),
        pl.lit(query_text).alias("query_text"),
    )

    # Select columns
    cols = ["query_id", "query_text", "imdb_id", "title", "sim_embedding"]
    for extra in ["imdb_rating", "imdb_votes_log", "year", "genres"]:
        if extra in cand.columns:
            cols.append(extra)

    return cand.select(cols)


# =============================================================================
# Relevance scoring functions
# =============================================================================
def compute_relevance_score(
    cand: pl.DataFrame,
    emphasis: str = "neutral",
) -> pl.DataFrame:
    """Calculate relevance score based on query emphasis.

    Args:
        cand: Candidates DataFrame with sim_embedding, imdb_rating, imdb_votes_log
        emphasis: Emphasis type ("rating", "popularity", "neutral")

    Returns:
        DataFrame with rel_score column added
    """
    # Base weights
    w_sim, w_rating, w_votes = 0.4, 0.4, 0.2

    # Adjust based on emphasis
    if emphasis == "rating":
        w_sim, w_rating, w_votes = 0.3, 0.5, 0.2
    elif emphasis == "popularity":
        w_sim, w_rating, w_votes = 0.3, 0.2, 0.5

    return cand.with_columns(
        (
            w_sim * pl.col("sim_embedding") +
            w_rating * (pl.col("imdb_rating") / 10.0) +
            w_votes * (pl.col("imdb_votes_log") / 15.0)
        ).alias("rel_score")
    )


def assign_relevance_labels(
    cand: pl.DataFrame,
    n_bins: int = DEFAULT_N_LABEL_BINS
) -> pl.DataFrame:
    """Convert continuous rel_score to discrete labels.

    Args:
        cand: DataFrame with rel_score column
        n_bins: Number of bins (labels 0 to n_bins-1)

    Returns:
        DataFrame with label column added
    """
    cand = cand.sort("rel_score", descending=True).with_row_index("rank")
    n = cand.height
    if n == 0:
        return cand

    bin_size = max(1, n // n_bins)

    # Assign bucket based on rank
    bucket_expr = pl.col("rank") // bin_size
    bucket_expr = pl.when(bucket_expr > (n_bins - 1)).then(n_bins - 1).otherwise(bucket_expr)

    cand = cand.with_columns(bucket_expr.alias("bucket"))

    # Invert so best items have highest label
    cand = cand.with_columns(
        (n_bins - 1 - pl.col("bucket")).cast(pl.Int32).alias("label")
    ).drop(["rank", "bucket"])

    return cand


# =============================================================================
# MLflow functions
# =============================================================================
def search_best_model(
    experiment_names: List[str] = [],
    metric_name: str = "ndcg5"
) -> Tuple[str, str]:
    """Search for best Run ID from given experiments.

    Args:
        experiment_names: List of experiment names
        metric_name: Metric to sort by

    Returns:
        Tuple (run_id, artifact_uri)
    """
    runs_ = mlflow.search_runs(experiment_names=experiment_names)
    best_run = runs_.loc[runs_[f'metrics.{metric_name}'].idxmax()]

    return best_run['run_id'], best_run["artifact_uri"]


def get_artifact_uri_production(model_name: str, tracking_uri: str) -> str:
    """Get artifact URI for production model.

    Args:
        model_name: Registered model name
        tracking_uri: MLflow server URI

    Returns:
        Artifact URI
    """
    mlflow.set_tracking_uri(tracking_uri)

    client = mlflow.MlflowClient()
    production_model = None

    for mv in client.search_model_versions(f"name='{model_name}'"):
        model = dict(mv)
        if model["current_stage"] == "Production":
            production_model = model
            break

    if production_model is None:
        raise ValueError(f"No production model found for {model_name}")

    _run_id = production_model.get("run_id")
    return mlflow.get_run(_run_id).info.artifact_uri
