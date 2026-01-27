# Airflow ML Worker Image
# Pre-installed ML dependencies for DSRP pipeline DAGs
#
# Based on: apache/airflow:3.0.1
# Usage: Used by KubernetesExecutor for worker pods

FROM apache/airflow:3.0.1

USER root

# Install system dependencies for ML libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

USER airflow

# Install all ML pipeline dependencies in a single layer
# Grouped by functionality:
#
# Core: polars, loguru
# Azure: azure-storage-blob, dsrp-ml-utils[azure]
# Embeddings: sentence-transformers
# Vector DB: qdrant-client
# ML Training: lightgbm, hyperopt, scikit-learn
# MLflow: mlflow, dagshub
# Utils: requests, numpy

RUN pip install --no-cache-dir \
    # Core data processing
    "polars>=1.35.2" \
    "loguru>=0.7.3" \
    "numpy>=1.24.0" \
    # Azure storage
    "azure-storage-blob" \
    "dsrp-ml-utils[azure]" \
    # Embeddings (sentence-transformers pulls torch)
    "sentence-transformers>=5.1.2" \
    # Vector database
    "qdrant-client>=1.9.0" \
    # ML training
    "lightgbm>=4.0.0" \
    "hyperopt" \
    "scikit-learn" \
    # MLflow tracking
    "mlflow>=2.0.0" \
    "dagshub" \
    # HTTP requests (for Groq API)
    "requests"

# Verify key installations
RUN python -c "import polars; import sentence_transformers; import qdrant_client; import lightgbm; import mlflow; print('All dependencies installed successfully')"
