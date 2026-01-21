"""Configuration for batch serving pipeline."""

import os
from dataclasses import dataclass, field


@dataclass
class ServingConfig:
    """Configuration for the movie recommendation serving pipeline."""

    # MLflow model
    model_name: str = "ltr-dsrpflix-prd-ENE12"
    model_alias: str = "champion"

    # Embeddings model
    embeddings_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dim: int = 384

    # Qdrant
    qdrant_url: str = field(
        default_factory=lambda: os.getenv(
            "QDRANT_URL", "http://qdrant-dsrp.eastus.cloudapp.azure.com:80"
        )
    )
    collection_name: str = "imdb-movies-hybrid"

    # Retrieval parameters
    top_k_retrieval: int = 100
    top_k_final: int = 10

    # Features for LTR model
    feature_cols: list[str] = field(
        default_factory=lambda: [
            "sim_embedding",
            "imdb_rating",
            "imdb_votes_log",
        ]
    )

    # Data paths
    movies_db_path: str = field(
        default_factory=lambda: os.getenv(
            "MOVIES_DB_PATH", "data/complete_imdb_database.parquet"
        )
    )

    # DagsHub/MLflow
    dagshub_repo_owner: str = "abdala9512"
    dagshub_repo_name: str = "dsrp-machine-learning-engineering-4"

    @property
    def model_uri(self) -> str:
        """Get the full MLflow model URI."""
        return f"models:/{self.model_name}@{self.model_alias}"
