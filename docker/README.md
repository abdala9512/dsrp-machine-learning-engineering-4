# Docker Compose - DSRP Movie Recommendation Stack

This directory contains Docker Compose configuration for running the complete ML pipeline locally.

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Frontend  │────▶│   Backend   │────▶│  ML Service │
│  (React)    │     │  (FastAPI)  │     │  (LitServe) │
└─────────────┘     └─────────────┘     └──────┬──────┘
                           │                   │
                           ▼                   ▼
                    ┌─────────────┐     ┌─────────────┐
                    │  IMDB API   │     │   Qdrant    │
                    │ (External)  │     │  (Vectors)  │
                    └─────────────┘     └─────────────┘

┌─────────────┐     ┌─────────────┐
│ Prometheus  │────▶│   Grafana   │
│  (Metrics)  │     │  (Dashboards)│
└─────────────┘     └─────────────┘
```

## Quick Start

### Option 1: Full ML Pipeline (Recommended)

```bash
# Set your DagsHub token (required for ML model)
export DAGSHUB_USER_TOKEN="your-token-here"

# Start all services with ML pipeline
docker compose --profile ml up -d

# View logs
docker compose logs -f
```

### Option 2: Standalone Frontend (No ML)

```bash
# Start frontend with direct IMDB API access
docker compose --profile standalone up -d
```

### Option 3: Frontend + Backend (Without Qdrant)

```bash
# Use mock mode for ML service (no real Qdrant needed)
export MOCK_QDRANT=true
docker compose up frontend backend ml-service prometheus grafana -d
```

## Services

| Service | Port | Description |
|---------|------|-------------|
| Frontend | 3000 | React app for movie search |
| Backend | 8080 | FastAPI orchestration layer |
| ML Service | 8000 | LightGBM LTR model serving |
| Qdrant | 6333, 6334 | Vector database |
| Prometheus | 9090 | Metrics collection |
| Grafana | 3001 | Dashboards (admin/admin123) |

## Environment Variables

### Required for ML Service

| Variable | Description |
|----------|-------------|
| `DAGSHUB_USER_TOKEN` | DagsHub API token for MLflow model access |

### Optional

| Variable | Default | Description |
|----------|---------|-------------|
| `QDRANT_URL` | `http://qdrant:6333` | Qdrant connection URL |
| `MOCK_QDRANT` | `false` | Use mock data instead of Qdrant |

## Development Workflow

### Building Images Locally

```bash
# Build all images
docker compose build

# Build specific service
docker compose build frontend
docker compose build backend
docker compose build ml-service
```

### Viewing Logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f backend
docker compose logs -f ml-service
```

### Restarting Services

```bash
# Restart all
docker compose restart

# Restart specific service
docker compose restart backend
```

### Stopping

```bash
# Stop all services
docker compose down

# Stop and remove volumes (clean slate)
docker compose down -v
```

## Accessing Services

- **Frontend**: http://localhost:3000
- **Backend API**: http://localhost:8080/docs
- **ML Service API**: http://localhost:8000/docs
- **Prometheus**: http://localhost:9090
- **Grafana**: http://localhost:3001 (admin/admin123)
- **Qdrant Dashboard**: http://localhost:6333/dashboard

## API Modes

The frontend can operate in two modes:

### 1. Backend Mode (ML Recommendations)

```bash
# Set in docker-compose or environment
VITE_API_MODE=backend
VITE_BACKEND_URL=http://backend:8080
```

Flow: Frontend → Backend → ML Service → IMDB API

### 2. Direct IMDB Mode (Simple Search)

```bash
# Set in docker-compose or environment
VITE_API_MODE=imdb
VITE_IMDB_API_BASE_URL=https://api.imdbapi.dev
```

Flow: Frontend → IMDB API (direct)

## Troubleshooting

### ML Service Won't Start

1. Check DagsHub token is set:
   ```bash
   echo $DAGSHUB_USER_TOKEN
   ```

2. Check logs:
   ```bash
   docker compose logs ml-service
   ```

3. Try mock mode:
   ```bash
   export MOCK_QDRANT=true
   docker compose up ml-service -d
   ```

### Backend Can't Connect to ML Service

1. Check ML service health:
   ```bash
   curl http://localhost:8000/health
   ```

2. Check backend logs:
   ```bash
   docker compose logs backend
   ```

### Frontend Shows No Results

1. Check backend health:
   ```bash
   curl http://localhost:8080/health
   ```

2. Test search directly:
   ```bash
   curl -X POST http://localhost:8080/search \
     -H "Content-Type: application/json" \
     -d '{"query": "action movies", "limit": 5}'
   ```

## Network

All services are on the `dsrp-network` Docker network and can communicate using service names as hostnames.
