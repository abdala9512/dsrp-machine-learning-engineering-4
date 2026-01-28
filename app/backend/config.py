"""Configuration for the backend API."""

import os
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Backend configuration loaded from environment variables."""

    # Server
    host: str = "0.0.0.0"
    port: int = 8080
    debug: bool = False

    # ML Service
    ml_service_url: str = "http://localhost:8000"
    ml_service_timeout: float = 30.0

    # IMDB API
    imdb_api_url: str = "https://api.imdbapi.dev"
    imdb_api_timeout: float = 10.0

    # Feature flags
    enable_ml_service: bool = True  # If False, skip ML service and search IMDB directly

    # Caching
    cache_ttl: int = 300  # 5 minutes

    # CORS
    cors_origins: str = "*"

    class Config:
        env_prefix = ""
        case_sensitive = False


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
