"""Configuration for the movie recommendation API."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Load environment variables
env_path = Path(__file__).parent / "mlapi.env"
load_dotenv(env_path)


@dataclass
class Config:
    """API configuration loaded from environment variables."""

    # Server
    host: str = field(default_factory=lambda: os.getenv("HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: int(os.getenv("PORT", "8000")))
    workers: int = field(default_factory=lambda: int(os.getenv("WORKERS", "1")))

    # DagsHub/MLflow
    dagshub_token: str = field(
        default_factory=lambda: os.getenv("DAGSHUB_USER_TOKEN", "")
    )
    dagshub_repo_owner: str = field(
        default_factory=lambda: os.getenv("DAGSHUB_REPO_OWNER", "abdala9512")
    )
    dagshub_repo_name: str = field(
        default_factory=lambda: os.getenv(
            "DAGSHUB_REPO_NAME", "dsrp-machine-learning-engineering-4"
        )
    )

    # LTR Model
    ltr_model_name: str = field(
        default_factory=lambda: os.getenv("LTR_MODEL_NAME", "ltr-dsrpflix-prd-ENE12")
    )
    ltr_model_alias: str = field(
        default_factory=lambda: os.getenv("LTR_MODEL_ALIAS", "champion")
    )

    # Embedding Model
    embedding_model: str = field(
        default_factory=lambda: os.getenv(
            "EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
        )
    )

    # Qdrant
    qdrant_url: str = field(
        default_factory=lambda: os.getenv(
            "QDRANT_URL", "http://qdrant-dsrp.eastus.cloudapp.azure.com:80"
        )
    )
    qdrant_collection: str = field(
        default_factory=lambda: os.getenv("QDRANT_COLLECTION", "imdb-movies-hybrid")
    )

    # Search parameters
    top_k_retrieval: int = field(
        default_factory=lambda: int(os.getenv("TOP_K_RETRIEVAL", "100"))
    )
    top_k_final: int = field(
        default_factory=lambda: int(os.getenv("TOP_K_FINAL", "10"))
    )

    # Data
    movies_db_path: str = field(
        default_factory=lambda: os.getenv(
            "MOVIES_DB_PATH", "data/complete_imdb_database.parquet"
        )
    )

    # Feature columns for LTR model
    feature_cols: list[str] = field(
        default_factory=lambda: ["sim_embedding", "imdb_rating", "imdb_votes_log"]
    )

    # Mock mode (when Qdrant is unavailable)
    mock_qdrant: bool = field(
        default_factory=lambda: os.getenv("MOCK_QDRANT", "false").lower() == "true"
    )

    @property
    def mlflow_tracking_uri(self) -> str:
        return f"https://dagshub.com/{self.dagshub_repo_owner}/{self.dagshub_repo_name}.mlflow"

    @property
    def ltr_model_uri(self) -> str:
        return f"models:/{self.ltr_model_name}@{self.ltr_model_alias}"

    def setup_mlflow_auth(self) -> None:
        """Configure MLflow authentication environment variables."""
        if self.dagshub_token:
            os.environ["MLFLOW_TRACKING_USERNAME"] = self.dagshub_token
            os.environ["MLFLOW_TRACKING_PASSWORD"] = self.dagshub_token
            os.environ["MLFLOW_TRACKING_URI"] = self.mlflow_tracking_uri


# Global config instance
config = Config()
config.setup_mlflow_auth()
