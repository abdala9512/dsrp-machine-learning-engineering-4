# DSRP ML Pipeline - Local Airflow DAGs

This folder contains Apache Airflow 3 DAGs for the DSRP ML Pipeline. The DAGs can run:
1. **As standalone Python scripts** - for local development and testing
2. **With Airflow** - installed via pip (no Docker required)
3. **In Kubernetes** - deployed to AKS with Azure Blob Storage integration

## Quick Start - Standalone Scripts

The simplest way to run the pipeline locally without Airflow:

```bash
cd notebooks/local_dags/dags

# Set environment variables
export DSRP_DATA_DIR="../data"
export OMDB_API_KEY="your_key_here"

# Run individual DAGs as scripts
python data_collection_dag.py --step all
python feature_engineering_dag.py --step all
python embeddings_indexing_dag.py --step all
python synthetic_queries_dag.py --step all
python modeling_dag.py --step all

# Or run specific steps
python data_collection_dag.py --step download
python data_collection_dag.py --step process
```

## Airflow 3 Setup (No Docker)

### 1. Install Airflow

```bash
# Create a virtual environment (recommended)
python -m venv airflow-venv
source airflow-venv/bin/activate

# Set Airflow home
export AIRFLOW_HOME=~/airflow

# Install Airflow 3
pip install "apache-airflow==3.0.*" \
    --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-3.0.1/constraints-3.10.txt"

# Install ML dependencies
pip install polars sentence-transformers qdrant-client lightgbm \
    hyperopt mlflow aiohttp orjson azure-storage-blob
```

### 2. Initialize Airflow

```bash
# Initialize the database
airflow db migrate

# Create admin user
airflow users create \
    --username admin \
    --password admin \
    --firstname Admin \
    --lastname User \
    --role Admin \
    --email admin@example.com
```

### 3. Configure DAGs

```bash
# Link DAGs folder to Airflow
ln -s $(pwd)/dags $AIRFLOW_HOME/dags

# Or copy DAGs
cp -r dags/* $AIRFLOW_HOME/dags/
```

### 4. Set Environment Variables

Create `~/.airflow.env` or export directly:

```bash
export DSRP_DATA_DIR="$(pwd)/../data"
export OMDB_API_KEY="your_omdb_api_key"
export DSRP_QDRANT_URL="http://localhost:6333"
export DSRP_OLLAMA_URL="http://localhost:11434/api/generate"
export DSRP_OLLAMA_MODEL="llama3.2:3b"
export MLFLOW_TRACKING_URI=""  # Optional: remote MLflow server

# For Azure Blob Storage (optional)
export AZURE_STORAGE_CONNECTION_STRING="your_connection_string"
```

### 5. Start Airflow

```bash
# Terminal 1: Start webserver
airflow webserver --port 8080

# Terminal 2: Start scheduler
airflow scheduler

# Or run standalone (webserver + scheduler in one process)
airflow standalone
```

Access the UI at http://localhost:8080 (login: admin/admin if using `standalone`)

## Azure Blob Storage Integration

The `storage.py` module provides simple functions for Azure Blob Storage:

```python
from storage import upload_to_blob, download_from_blob, sync_to_azure, sync_from_azure

# Upload a file
upload_to_blob("data/movies.parquet", "movies.parquet")

# Download a file
download_from_blob("movies.parquet", "data/movies.parquet")

# Sync entire data directory
sync_to_azure("../data")
sync_from_azure("../data")
```

Set the environment variable:
```bash
export AZURE_STORAGE_CONNECTION_STRING="DefaultEndpointsProtocol=https;..."
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DSRP_DATA_DIR` | `../data` (relative to dags/) | Data storage path |
| `OMDB_API_KEY` | - | OMDB API key (required for data collection) |
| `DSRP_QDRANT_URL` | `http://localhost:6333` | Qdrant endpoint |
| `DSRP_QDRANT_COLLECTION` | `imdb-movies-hybrid` | Collection name |
| `DSRP_OLLAMA_URL` | `http://localhost:11434/api/generate` | Ollama API |
| `DSRP_OLLAMA_MODEL` | `llama3.2:3b` | LLM model |
| `DSRP_EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | Embedding model |
| `MLFLOW_TRACKING_URI` | - | MLflow server URI (optional) |
| `AZURE_STORAGE_CONNECTION_STRING` | - | Azure Storage (optional) |

## DAGs Overview

### 1. Data Collection (`data_collection_dag.py`)
Downloads and processes IMDB + OMDB data.

```bash
python data_collection_dag.py --step all
# Steps: download, process, omdb, validate
```

**Outputs:** `movies_base.parquet`, `omdb_raw.jsonl`

### 2. Feature Engineering (`feature_engineering_dag.py`)
Generates embeddings and derived features.

```bash
python feature_engineering_dag.py --step all
# Steps: combine, embeddings, features, metadata, validate
```

**Outputs:** `complete_imdb_database.parquet`, `movie_embs.npy`, `dataset_metadata.json`

### 3. Embeddings Indexing (`embeddings_indexing_dag.py`)
Indexes movies in Qdrant for hybrid search.

```bash
python embeddings_indexing_dag.py --step all
# Steps: connect, create, prepare, index, verify
```

**Requires:** Qdrant running locally or remotely

### 4. Synthetic Queries (`synthetic_queries_dag.py`)
Generates LTR dataset using Ollama and templates.

```bash
python synthetic_queries_dag.py --step all
# Steps: metadata, llm, template, combine, retrieve, score, validate
```

**Outputs:** `ltr_imdb_dataset.parquet`

### 5. Modeling (`modeling_dag.py`)
Trains and deploys LTR model with MLflow.

```bash
python modeling_dag.py --step all
# Steps: split, hyperopt, train, promote, summary
```

**Outputs:** MLflow model, `feature_importance.json`, `training_summary.json`

## Running Services Locally

### Qdrant

```bash
# Docker
docker run -p 6333:6333 qdrant/qdrant

# Or binary
curl -L https://github.com/qdrant/qdrant/releases/download/v1.12.1/qdrant-x86_64-apple-darwin.tar.gz | tar xz
./qdrant
```

### Ollama

```bash
# Install
curl -fsSL https://ollama.com/install.sh | sh

# Pull model
ollama pull llama3.2:3b

# Ollama runs automatically after install
```

### MLflow (optional)

```bash
pip install mlflow
mlflow server --host 0.0.0.0 --port 5000

# Set tracking URI
export MLFLOW_TRACKING_URI=http://localhost:5000
```

## Kubernetes Deployment

For k8s deployment, set environment variables in your deployment manifest:

```yaml
env:
  - name: DSRP_DATA_DIR
    value: /data
  - name: AZURE_STORAGE_CONNECTION_STRING
    valueFrom:
      secretKeyRef:
        name: azure-storage
        key: connection-string
  - name: DSRP_QDRANT_URL
    value: http://qdrant-service:6333
```

## File Structure

```
local_dags/
├── dags/
│   ├── data_collection_dag.py    # Data download and processing
│   ├── feature_engineering_dag.py # Embeddings and features
│   ├── embeddings_indexing_dag.py # Qdrant indexing
│   ├── synthetic_queries_dag.py   # LTR dataset generation
│   ├── modeling_dag.py            # Model training
│   ├── storage.py                 # Azure Blob Storage utilities
│   └── __init__.py
├── config/
│   └── pipeline_config.json       # Optional config file
├── .env.example
└── README.md
```

## Tips

### Running DAGs in Parallel
The DAGs are designed to run sequentially, but you can parallelize:
- Data Collection → Feature Engineering (sequential)
- Feature Engineering → Embeddings Indexing (sequential)
- Feature Engineering → Synthetic Queries (can run in parallel after Feature Engineering)
- Synthetic Queries → Modeling (sequential)

### Resuming Interrupted Runs
- Data Collection: OMDB fetch uses checkpoints (`processed_ids.txt`)
- Embeddings Indexing: Set `QDRANT_FORCE_REINDEX=true` to reindex

### Using with Docker Compose (optional)
The `docker-compose.yml` is still available if you prefer containerized setup.
