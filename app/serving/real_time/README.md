# Movie Recommendation API

Real-time movie recommendation API using Lightning AI LitServe, LightGBM LTR model, and Qdrant hybrid search.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Movie Recommendation API                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Query ──► Embedding ──► Qdrant Search ──► LTR Rerank ──► Results│
│            (MiniLM)      (Hybrid RRF)     (LightGBM)             │
│                                                                  │
│  Components:                                                     │
│  • SentenceTransformer: Query embeddings                        │
│  • Qdrant: Hybrid search (dense + BM25 with RRF fusion)         │
│  • LightGBM: Learning-to-Rank re-ranking                        │
│  • Prometheus: Metrics for Grafana                              │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## API Documentation

### Endpoints

#### `POST /predict` - Search Movies

Search for movie recommendations based on a natural language query.

**Request:**
```json
{
  "query": "action movies similar to the dark knight",
  "top_k": 10
}
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `query` | string | Yes | - | Natural language search query |
| `top_k` | int | No | 10 | Number of results to return (1-100) |

**Response:**
```json
{
  "movie_ids": ["tt0468569", "tt1345836", "tt0372784", ...],
  "results": [
    {
      "imdb_id": "tt0468569",
      "title": "The Dark Knight",
      "genres": "Action,Crime,Drama",
      "imdb_rating": 9.0,
      "ltr_score": 18.45,
      "retrieval_score": 0.89,
      "sim_embedding": 0.92
    },
    ...
  ],
  "count": 10
}
```

| Field | Description |
|-------|-------------|
| `movie_ids` | List of IMDB IDs (for quick access) |
| `results` | Full result details including scores |
| `count` | Number of results returned |

---

#### `GET /health` - Health Check

Check API health status.

**Response:**
```json
{
  "status": "ok"
}
```

---

#### `GET /metrics` - Prometheus Metrics

Prometheus-formatted metrics for Grafana dashboards.

**Response:** Plain text Prometheus metrics format.

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| **Authentication** |
| `DAGSHUB_USER_TOKEN` | **Yes** | - | DagsHub API token ([Get token](https://dagshub.com/user/settings/tokens)) |
| `DAGSHUB_REPO_OWNER` | No | `abdala9512` | DagsHub repository owner |
| `DAGSHUB_REPO_NAME` | No | `dsrp-machine-learning-engineering-4` | Repository name |
| **Model** |
| `LTR_MODEL_NAME` | No | `ltr-dsrpflix-prd-ENE12` | MLflow model name |
| `LTR_MODEL_ALIAS` | No | `champion` | Model alias (champion/latest) |
| `EMBEDDING_MODEL` | No | `sentence-transformers/all-MiniLM-L6-v2` | Embedding model |
| **Qdrant** |
| `QDRANT_URL` | No | `http://qdrant-dsrp.eastus.cloudapp.azure.com:80` | Qdrant server URL |
| `QDRANT_COLLECTION` | No | `imdb-movies-hybrid` | Collection name |
| `MOCK_QDRANT` | No | `false` | Use mock retriever (returns random movies) |
| **Search** |
| `TOP_K_RETRIEVAL` | No | `100` | Candidates to retrieve from Qdrant |
| `TOP_K_FINAL` | No | `10` | Final results after re-ranking |
| **Data** |
| `MOVIES_DB_PATH` | No | `data/complete_imdb_database.parquet` | Movies database path |
| **Server** |
| `HOST` | No | `0.0.0.0` | Server host |
| `PORT` | No | `8000` | Server port |
| `WORKERS` | No | `1` | Number of worker processes |

---

## Local Development

### Prerequisites

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) package manager
- Movies database parquet file

### Setup

```bash
cd app/serving/real_time

# Install dependencies
uv sync

# Configure environment (copy and edit)
cp mlapi.env mlapi.env.local

# Edit mlapi.env and set your DAGSHUB_USER_TOKEN
# Also update MOVIES_DB_PATH to point to your data file
```

### Run the API

```bash
# Standard run
uv run python -m app.serving.real_time.api

# Or directly
uv run python api.py

# With mock Qdrant (for testing without Qdrant)
MOCK_QDRANT=true uv run python api.py
```

### Test Requests

```bash
# Health check
curl http://localhost:8000/health

# Search request
curl -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{"query": "action movies similar to the dark knight", "top_k": 5}'

# Get metrics
curl http://localhost:8000/metrics
```

**Example Response:**
```json
{
  "movie_ids": ["tt0468569", "tt1345836", "tt0372784", "tt2975590", "tt1877830"],
  "results": [
    {
      "imdb_id": "tt0468569",
      "title": "The Dark Knight",
      "genres": "Action,Crime,Drama",
      "imdb_rating": 9.0,
      "ltr_score": 18.45,
      "retrieval_score": 0.89,
      "sim_embedding": 0.92
    }
  ],
  "count": 5
}
```

---

## Prometheus Metrics

The API exposes the following metrics at `/metrics`:

### Request Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| ` c` | Counter | endpoint, status | Total API requests |
| `movie_api_request_latency_seconds` | Histogram | endpoint | Request latency |

### Pipeline Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `movie_api_retrieval_latency_seconds` | Histogram | Qdrant retrieval latency |
| `movie_api_rerank_latency_seconds` | Histogram | LTR re-ranking latency |
| `movie_api_embedding_latency_seconds` | Histogram | Embedding generation latency |
| `movie_api_candidates_retrieved` | Histogram | Candidates from Qdrant |
| `movie_api_results_returned` | Histogram | Results returned to client |

### Component Status

| Metric | Type | Description |
|--------|------|-------------|
| `movie_api_qdrant_available` | Gauge | Qdrant availability (1=yes, 0=mock) |
| `movie_api_model_loaded` | Gauge | LTR model loaded |
| `movie_api_embedding_model_loaded` | Gauge | Embedding model loaded |

### Error Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `movie_api_qdrant_errors_total` | Counter | Qdrant errors |
| `movie_api_model_errors_total` | Counter | Model inference errors |
| `movie_api_mock_requests_total` | Counter | Requests served with mock data |

---

## Grafana Dashboard

### Setup Prometheus Scrape Config

```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'movie-api'
    static_configs:
      - targets: ['movie-api:8000']
    metrics_path: '/metrics'
    scrape_interval: 15s
```

### Example Dashboard Panels

**Request Rate:**
```promql
rate(movie_api_requests_total[5m])
```

**P95 Latency:**
```promql
histogram_quantile(0.95, rate(movie_api_request_latency_seconds_bucket[5m]))
```

**Error Rate:**
```promql
rate(movie_api_requests_total{status="error"}[5m]) / rate(movie_api_requests_total[5m])
```

**Qdrant Availability:**
```promql
movie_api_qdrant_available
```

**Mock Request Ratio:**
```promql
rate(movie_api_mock_requests_total[5m]) / rate(movie_api_requests_total[5m])
```

---

## Kubernetes Deployment

### 1. Create Secrets

```bash
kubectl create secret generic movie-api-secrets \
  --from-literal=DAGSHUB_USER_TOKEN=your_token_here
```

### 2. Deployment Manifest

```yaml
# k8s/movie-api.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: movie-api
  labels:
    app: movie-api
spec:
  replicas: 2
  selector:
    matchLabels:
      app: movie-api
  template:
    metadata:
      labels:
        app: movie-api
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "8000"
        prometheus.io/path: "/metrics"
    spec:
      containers:
      - name: movie-api
        image: ghcr.io/your-org/movie-api:latest
        ports:
        - containerPort: 8000
          name: http
        env:
        - name: DAGSHUB_USER_TOKEN
          valueFrom:
            secretKeyRef:
              name: movie-api-secrets
              key: DAGSHUB_USER_TOKEN
        - name: QDRANT_URL
          value: "http://qdrant:6333"
        - name: MOVIES_DB_PATH
          value: "/data/complete_imdb_database.parquet"
        volumeMounts:
        - name: data
          mountPath: /data
        resources:
          requests:
            memory: "1Gi"
            cpu: "500m"
          limits:
            memory: "2Gi"
            cpu: "1000m"
        readinessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 60
          periodSeconds: 10
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 120
          periodSeconds: 30
      volumes:
      - name: data
        persistentVolumeClaim:
          claimName: movie-data-pvc
---
apiVersion: v1
kind: Service
metadata:
  name: movie-api
  labels:
    app: movie-api
spec:
  selector:
    app: movie-api
  ports:
  - port: 80
    targetPort: 8000
    name: http
  type: ClusterIP
---
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: movie-api
  labels:
    app: movie-api
spec:
  selector:
    matchLabels:
      app: movie-api
  endpoints:
  - port: http
    path: /metrics
    interval: 15s
```

### 3. Deploy

```bash
kubectl apply -f k8s/movie-api.yaml

# Verify
kubectl get pods -l app=movie-api
kubectl logs -l app=movie-api -f
```

---

## Docker

### Build

```bash
docker build -t movie-api:latest .
```

### Run

```bash
docker run -p 8000:8000 \
  -e DAGSHUB_USER_TOKEN=your_token \
  -e MOCK_QDRANT=true \
  -v /path/to/data:/data \
  movie-api:latest
```

---

## Usage Examples

### Python

```python
import httpx

# Search for movies
response = httpx.post(
    "http://localhost:8000/predict",
    json={
        "query": "sci-fi movies about time travel",
        "top_k": 5
    }
)

data = response.json()
print(f"Found {data['count']} movies")

for movie in data["results"]:
    print(f"  {movie['title']} ({movie['imdb_rating']}) - Score: {movie['ltr_score']:.2f}")
```

### cURL

```bash
# Simple search
curl -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{"query": "romantic comedies from the 90s"}'

# With custom top_k
curl -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{"query": "horror movies", "top_k": 20}'
```

### JavaScript

```javascript
const response = await fetch("http://localhost:8000/predict", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    query: "animated movies for kids",
    top_k: 10
  })
});

const { movie_ids, results, count } = await response.json();
console.log(`Found ${count} movies:`, movie_ids);
```

---

## Mock Mode

When Qdrant is unavailable (network issues, maintenance), the API automatically falls back to mock mode:

- Returns random movies from the database
- LTR re-ranking still applied
- `movie_api_mock_requests_total` metric increments
- `movie_api_qdrant_available` gauge shows 0

To force mock mode:
```bash
MOCK_QDRANT=true uv run python api.py
```

---

## Troubleshooting

### "DAGSHUB_USER_TOKEN environment variable is required"

Get your token at https://dagshub.com/user/settings/tokens and set it:
```bash
export DAGSHUB_USER_TOKEN=your_token
```

### Model loading fails with 401

- Verify token is valid
- Check repository access permissions
- Ensure `DAGSHUB_REPO_OWNER` and `DAGSHUB_REPO_NAME` are correct

### Qdrant connection fails

The API will automatically fall back to mock mode. Check:
- `QDRANT_URL` is correct
- Qdrant is running and accessible
- Collection exists and has data

### High latency

Check metrics to identify bottleneck:
- `movie_api_retrieval_latency_seconds` - Qdrant slow
- `movie_api_embedding_latency_seconds` - Embedding slow
- `movie_api_rerank_latency_seconds` - LTR slow

---

## Project Structure

```
app/serving/real_time/
├── __init__.py      # Package exports
├── api.py           # LitServe API endpoints
├── config.py        # Configuration management
├── metrics.py       # Prometheus metrics definitions
├── search.py        # Search pipeline (retrieval + reranking)
├── mlapi.env        # Environment variables template
├── pyproject.toml   # Dependencies
├── Dockerfile       # Container build
└── README.md        # This file
```

---

## References

- [LitServe Documentation](https://github.com/Lightning-AI/LitServe)
- [DagsHub MLflow Integration](https://dagshub.com/docs/integration_guide/mlflow_tracking/)
- [Qdrant Hybrid Search](https://qdrant.tech/documentation/concepts/hybrid-queries/)
- [Prometheus Python Client](https://github.com/prometheus/client_python)
- [LightGBM Ranker](https://lightgbm.readthedocs.io/en/latest/pythonapi/lightgbm.LGBMRanker.html)
