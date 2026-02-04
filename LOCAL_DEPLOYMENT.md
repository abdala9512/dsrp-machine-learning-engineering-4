# Local Development Guide

This guide explains how to run the complete DSRP Movie Recommendations platform locally for development and testing.

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Prerequisites](#prerequisites)
3. [One-Time Setup](#one-time-setup)
4. [Quick Start](#quick-start)
5. [Detailed Setup](#detailed-setup)
6. [Monitoring & Dashboards](#monitoring--dashboards)
7. [Troubleshooting](#troubleshooting)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     Frontend (React + Vite)                      │
│                        Port 5173                                 │
│              http://localhost:5173                               │
└──────────────────────────┬──────────────────────────────────────┘
                           │ /search, /health, /movie
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Backend API (FastAPI)                        │
│                        Port 8080                                 │
│              http://localhost:8080                               │
│                                                                  │
│  • Orchestrates ML Service + IMDB API                           │
│  • Prometheus metrics at /metrics                                │
└──────────────────────────┬──────────────────────────────────────┘
                           │
          ┌────────────────┼────────────────┐
          ▼                                 ▼
┌─────────────────────┐         ┌─────────────────────┐
│   ML Service API    │         │     IMDB API        │
│     Port 8000       │         │   (External)        │
│                     │         │                     │
│ • LightGBM LTR      │         │ • Movie details     │
│ • Embeddings        │         │ • Poster images     │
│ • Qdrant search     │         │                     │
│ • nDCG metrics      │         │                     │
│ • Feature drift     │         │                     │
└─────────┬───────────┘         └─────────────────────┘
          │
          ▼
┌─────────────────────┐         ┌─────────────────────┐
│   Qdrant (Vector)   │         │   MLflow (DagsHub)  │
│     Port 6333       │         │     (Remote)        │
│                     │         │                     │
│ • Dense embeddings  │         │ • Model registry    │
│ • BM25 sparse       │         │ • Experiment logs   │
│ • Hybrid search     │         │                     │
└─────────────────────┘         └─────────────────────┘
```

### Components

| Component | Port | Description |
|-----------|------|-------------|
| **Frontend** | 5173 | React application for search UI |
| **Backend** | 8080 | API orchestration layer |
| **ML Service** | 8000 | LightGBM LTR model + embeddings |
| **Qdrant** | 6333 | Vector database for hybrid search |
| **Prometheus** | 9090 | Metrics collection |
| **Grafana** | 3000 | Monitoring dashboards |

---

## Prerequisites

### Required Software

| Software | Version | Installation |
|----------|---------|--------------|
| **Docker** | 20.10+ | [docker.com](https://docs.docker.com/get-docker/) |
| **uv** | 0.1+ | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| **Node.js** | 18+ | [nodejs.org](https://nodejs.org/) |
| **Task** | 3.0+ | `brew install go-task` or [taskfile.dev](https://taskfile.dev/installation/) |

### Verify Installation

```bash
docker --version      # Docker version 20.10+
uv --version          # uv 0.1+
node --version        # v18+
task --version        # Task version 3+
```

---

## One-Time Setup

### 1. Clone the Repository

```bash
git clone https://github.com/abdala9512/dsrp-machine-learning-engineering-4.git
cd dsrp-machine-learning-engineering-4
```

### 2. Configure DagsHub/MLflow Access

The ML Service loads the trained LightGBM model from MLflow (hosted on DagsHub). You need a DagsHub token to access the model registry.

1. **Get your DagsHub token**:
   - Go to [DagsHub](https://dagshub.com/user/settings/tokens)
   - Create a new token with read access

2. **Configure the environment**:
   ```bash
   cd app/serving/real_time
   cp mlapi.env.example mlapi.env  # If example exists, otherwise edit mlapi.env
   ```

3. **Edit `mlapi.env`** with your token:
   ```env
   # DagsHub Authentication (REQUIRED)
   DAGSHUB_USER_TOKEN=your_token_here
   DAGSHUB_REPO_OWNER=abdala9512
   DAGSHUB_REPO_NAME=dsrp-machine-learning-engineering-4

   # MLflow Model (these are the defaults)
   LTR_MODEL_NAME=ltr-dsrpflix-prd-ENE12
   LTR_MODEL_ALIAS=champion

   # Local Qdrant (will be set by Taskfile)
   QDRANT_URL=http://localhost:6333
   QDRANT_COLLECTION=imdb-movies-hybrid
   ```

### 3. Prepare the Movie Database

The system requires the IMDB movie database in parquet format. There are two options:

**Option A: Use existing data (recommended)**

If you have access to the notebooks data:
```bash
# The Taskfile will automatically find data in:
# - app/serving/real_time/complete_imdb_database.parquet
# - notebooks/data/complete_imdb_database.parquet
```

**Option B: Generate from scratch**

Run the data collection notebook:
```bash
cd notebooks
uv sync
uv run jupyter lab
# Open and run: data_collection.ipynb
```

This requires an OMDB API key in `notebooks/.env`:
```env
OMDB_API_KEY=your_omdb_api_key
```

### 4. Install Dependencies

```bash
# From repository root
task local:deps:install

# Or manually:
cd app/serving/real_time && uv sync
cd ../backend && uv sync
cd ../frontend && npm install
```

---

## Quick Start

Once the one-time setup is complete, you can start the entire stack with:

```bash
# Terminal 1: Start infrastructure (Qdrant + monitoring)
task local:start:all

# Terminal 2: Start ML Service
task local:api:start

# Terminal 3: Start Backend
task local:backend:start

# Terminal 4: Start Frontend
task local:frontend:start
```

**Access the application:**

| Service | URL |
|---------|-----|
| Frontend | http://localhost:5173 |
| Backend API | http://localhost:8080 |
| Backend Docs | http://localhost:8080/docs |
| ML Service API | http://localhost:8000 |
| ML Service Docs | http://localhost:8000/docs |
| Qdrant Dashboard | http://localhost:6333/dashboard |
| Prometheus | http://localhost:9090 |
| Grafana | http://localhost:3000 (admin/admin) |

---

## Detailed Setup

### ML Pipeline Dependencies

The ML Service depends on several upstream components that must be set up before the service can work properly.

#### 1. Model Training (MLflow)

The LightGBM LTR model must be trained and registered in MLflow before the service can load it.

**Training Pipeline:**

```
notebooks/data_collection.ipynb     → IMDB data
         ↓
notebooks/feature_engineering.ipynb → Feature extraction
         ↓
notebooks/synthetic_queries.ipynb   → LTR training data
         ↓
notebooks/modeling.ipynb            → Train & register model
```

**To train the model:**

```bash
cd notebooks
uv sync

# Install Jupyter
uv run pip install jupyterlab

# Start JupyterLab
uv run jupyter lab
```

Run the notebooks in order:

1. **`data_collection.ipynb`**: Downloads IMDB datasets and enriches with OMDB API
   - Output: `data/complete_imdb_database.parquet`
   - Requires: `OMDB_API_KEY` in `.env`

2. **`feature_engineering.ipynb`**: Creates embeddings and features
   - Output: Feature-enriched parquet files
   - Uses: `sentence-transformers/all-MiniLM-L6-v2`

3. **`synthetic_queries.ipynb`**: Generates LTR training data
   - Output: `data/ltr_synthetic_dataset.parquet`
   - Creates synthetic query-document pairs with relevance labels

4. **`modeling.ipynb`**: Trains LightGBM LTR model
   - Output: Model registered in MLflow as `ltr-dsrpflix-prd-ENE12`
   - Promotes best model to `@champion` alias
   - Logs nDCG@k metrics

**Model Configuration:**

```python
# Model features (from config.py)
feature_cols = ["sim_embedding", "imdb_rating", "imdb_votes_log"]

# Model URI
model_uri = "models:/ltr-dsrpflix-prd-ENE12@champion"
```

#### 2. Qdrant Initialization

After starting Qdrant, initialize it with movie embeddings:

```bash
# Start Qdrant container
task local:qdrant:start

# Initialize with movie data (creates collection + indexes)
task local:qdrant:init

# Verify initialization
task local:qdrant:status
```

**What the initialization does:**

1. Creates collection `imdb-movies-hybrid` with:
   - Dense vectors (384-dim sentence-transformer embeddings)
   - Sparse vectors (BM25-like for keyword search)

2. Indexes all movies (~47K) with:
   - Full text embeddings
   - Sparse token indices

3. Verifies with a test search

**Force re-index:**
```bash
task local:qdrant:init FORCE_REINDEX=true
```

### Service Startup Order

For proper operation, start services in this order:

```bash
# 1. Infrastructure (Qdrant must be ready before ML Service)
task local:qdrant:start
task local:qdrant:init       # First time only
task local:monitoring:start  # Optional, for dashboards

# 2. ML Service (must be ready before Backend)
task local:api:start

# 3. Backend (depends on ML Service)
task local:backend:start

# 4. Frontend (depends on Backend)
task local:frontend:start
```

### Configuration Reference

#### ML Service (`app/serving/real_time/mlapi.env`)

```env
# Server
HOST=0.0.0.0
PORT=8000
WORKERS=1

# DagsHub/MLflow (REQUIRED)
DAGSHUB_USER_TOKEN=your_token_here
DAGSHUB_REPO_OWNER=abdala9512
DAGSHUB_REPO_NAME=dsrp-machine-learning-engineering-4

# Model
LTR_MODEL_NAME=ltr-dsrpflix-prd-ENE12
LTR_MODEL_ALIAS=champion

# Embeddings
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2

# Qdrant
QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION=imdb-movies-hybrid
MOCK_QDRANT=false

# Search
TOP_K_RETRIEVAL=100
TOP_K_FINAL=10
```

#### Backend (`app/backend/`)

Environment variables (set by Taskfile):
```env
ML_SERVICE_URL=http://localhost:8000
HOST=0.0.0.0
PORT=8080
ENABLE_ML_SERVICE=true
CORS_ORIGINS=*
```

#### Frontend (`app/frontend/vite.config.ts`)

Proxies requests to backend:
```typescript
proxy: {
  "/search": "http://localhost:8080",
  "/health": "http://localhost:8080",
  "/movie": "http://localhost:8080",
}
```

---

## Monitoring & Dashboards

### Grafana Dashboards

Access Grafana at http://localhost:3000 (admin/admin)

| Dashboard | URL | Metrics |
|-----------|-----|---------|
| **ML Service** | `/d/movie-api-dashboard` | nDCG, feature distributions, LTR scores, pipeline latencies |
| **Backend** | `/d/backend-dashboard` | Request rates, ML/IMDB latencies, error rates |

### ML Service Metrics

The ML Service exposes these Prometheus metrics at `/metrics`:

**Quality Metrics:**
- `movie_api_ndcg_score` - Simulated nDCG@k per request
- `movie_api_ndcg_at_k` - nDCG distribution histogram

**Feature Drift:**
- `movie_api_feature_sim_embedding` - Cosine similarity distribution
- `movie_api_feature_imdb_rating` - Rating distribution
- `movie_api_feature_imdb_votes_log` - Vote count distribution
- `movie_api_ltr_score` - LTR model output distribution

**Latencies:**
- `movie_api_request_latency_seconds` - Total request latency
- `movie_api_embedding_latency_seconds` - Embedding generation
- `movie_api_retrieval_latency_seconds` - Qdrant search
- `movie_api_rerank_latency_seconds` - LTR re-ranking

### Backend Metrics

Available at http://localhost:8080/metrics:

- `backend_requests_total` - Request count by endpoint/status/source
- `backend_request_latency_seconds` - Overall latency
- `backend_ml_service_latency_seconds` - ML service call latency
- `backend_imdb_api_latency_seconds` - IMDB API call latency

---

## Task Reference

All tasks are available from the repository root with the `local:` prefix:

```bash
# Infrastructure
task local:start:all          # Start Qdrant + init + monitoring
task local:stop:all           # Stop all services
task local:status             # Check status of all services

# Qdrant
task local:qdrant:start       # Start Qdrant container
task local:qdrant:stop        # Stop Qdrant
task local:qdrant:init        # Initialize with movie data
task local:qdrant:status      # Check collection status
task local:qdrant:destroy     # Remove container and data

# ML Service (Port 8000)
task local:api:start          # Start ML service
task local:api:stop           # Stop ML service
task local:api:test           # Test with sample query

# Backend (Port 8080)
task local:backend:start      # Start backend
task local:backend:stop       # Stop backend
task local:backend:test       # Test backend API

# Frontend (Port 5173)
task local:frontend:start     # Start dev server
task local:frontend:stop      # Stop frontend
task local:frontend:build     # Build for production

# Monitoring
task local:monitoring:start   # Start Prometheus + Grafana
task local:monitoring:stop    # Stop monitoring
task local:monitoring:logs    # View logs

# Development
task local:dev                # Start API with mock data (no Qdrant)
task local:deps:check         # Check dependencies
task local:deps:install       # Install all dependencies
task local:load-test:api      # Run load test
```

---

## Troubleshooting

### Common Issues

#### 1. "DAGSHUB_USER_TOKEN not set"

```
Error: DAGSHUB_USER_TOKEN environment variable is required
```

**Solution:** Edit `app/serving/real_time/mlapi.env` with your DagsHub token.

#### 2. "Model not found in MLflow"

```
mlflow.exceptions.MlflowException: Could not find a registered model with name
```

**Solution:**
1. Verify model exists: Check https://dagshub.com/abdala9512/dsrp-machine-learning-engineering-4.mlflow
2. Run the training notebook: `notebooks/modeling.ipynb`
3. Ensure model has `@champion` alias

#### 3. "Qdrant connection refused"

```
qdrant_client.http.exceptions.ResponseHandlingException: Connection refused
```

**Solution:**
```bash
task local:qdrant:start
task local:qdrant:status
```

#### 4. "Collection not found" or "Empty results"

**Solution:**
```bash
task local:qdrant:init FORCE_REINDEX=true
```

#### 5. "Movies database not found"

```
FileNotFoundError: Movies database not found
```

**Solution:**
1. Run `notebooks/data_collection.ipynb` to generate data
2. Or copy existing parquet to `app/serving/real_time/complete_imdb_database.parquet`

#### 6. Frontend can't connect to backend

**Solution:** Ensure backend is running on port 8080:
```bash
task local:backend:start
curl http://localhost:8080/health
```

### Development Mode (No Qdrant)

For quick development without Qdrant:

```bash
task local:dev
# or
task local:api:start MOCK_QDRANT=true
```

This uses a mock retriever that returns random movies (useful for UI development).

### Logs

```bash
# View Qdrant logs
task local:qdrant:logs

# View monitoring logs
task local:monitoring:logs

# Check service status
task local:status
```

### Reset Everything

```bash
# Stop all services
task local:stop:all

# Destroy Qdrant data
task local:qdrant:destroy

# Clean generated files
task local:clean

# Fresh start
task local:start:all
```

---

## Development Workflow

### Typical Development Session

```bash
# 1. Start infrastructure (once per session)
task local:start:all

# 2. Start services in separate terminals
task local:api:start       # Terminal 2
task local:backend:start   # Terminal 3
task local:frontend:start  # Terminal 4

# 3. Make changes to code
# Services auto-reload on file changes

# 4. Test
task local:api:test        # Test ML service
task local:backend:test    # Test backend

# 5. Check metrics
open http://localhost:3000  # Grafana
```

### Running Tests

```bash
cd app/serving/real_time
task local:test            # Run pytest

# Load testing
task local:load-test:api REQUESTS=100 CONCURRENCY=10
```

---

## Additional Resources

- **MLflow Dashboard**: https://dagshub.com/abdala9512/dsrp-machine-learning-engineering-4.mlflow
- **Repository**: https://github.com/abdala9512/dsrp-machine-learning-engineering-4
- **Qdrant Docs**: https://qdrant.tech/documentation/
- **LightGBM Ranker**: https://lightgbm.readthedocs.io/en/latest/pythonapi/lightgbm.LGBMRanker.html
