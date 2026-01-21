# Monitoring Setup for Movie Recommendation API

This folder contains Prometheus + Grafana setup for monitoring the Movie Recommendation API.

## Quick Start

### 1. Start the API

```bash
cd /Users/miguelarquezabdala/repos/dsrp-machine-learning-engineering-4/app/serving/real_time
uv run python api.py
```

### 2. Start Prometheus & Grafana

```bash
cd monitoring
docker-compose up -d
```

### 3. Access Dashboards

| Service | URL | Credentials |
|---------|-----|-------------|
| **Grafana** | http://localhost:3000 | admin / admin |
| **Prometheus** | http://localhost:9090 | - |
| **API Metrics** | http://localhost:8000/metrics | - |

### 4. Run Load Test

```bash
cd ..
uv run python client.py -n 1000 -c 50
```

### 5. View Dashboard

Open Grafana at http://localhost:3000 and navigate to:
- **Dashboards** → **Movie Recommendation API**

## Architecture

```
┌─────────────────┐      ┌─────────────────┐      ┌─────────────────┐
│   Movie API     │      │   Prometheus    │      │    Grafana      │
│  localhost:8000 │─────►│  localhost:9090 │─────►│  localhost:3000 │
│    /metrics     │scrape│                 │query │                 │
└─────────────────┘      └─────────────────┘      └─────────────────┘
```

## Dashboard Panels

The pre-configured dashboard includes:

### Status Row
- **Requests (5m)**: Total requests in last 5 minutes
- **P95 Latency**: 95th percentile response time
- **Qdrant Status**: UP/DOWN indicator
- **LTR Model Status**: LOADED/NOT LOADED indicator
- **Error Rate**: Percentage of failed requests

### Charts
- **Request Rate**: Requests per second over time
- **Request Latency Percentiles**: P50, P90, P95, P99 latencies
- **Pipeline Stage Latency**: Embedding, Retrieval, Rerank times
- **Requests by Status**: Success vs Error breakdown
- **Search Results**: Candidates retrieved and results returned

## Prometheus Queries

Useful PromQL queries:

```promql
# Request rate
rate(movie_api_requests_total[5m])

# P95 latency
histogram_quantile(0.95, rate(movie_api_request_latency_seconds_bucket[5m]))

# Error rate
sum(rate(movie_api_requests_total{status="error"}[5m])) / sum(rate(movie_api_requests_total[5m]))

# Qdrant availability
movie_api_qdrant_available

# Pipeline stage latencies
histogram_quantile(0.95, rate(movie_api_embedding_latency_seconds_bucket[5m]))
histogram_quantile(0.95, rate(movie_api_retrieval_latency_seconds_bucket[5m]))
histogram_quantile(0.95, rate(movie_api_rerank_latency_seconds_bucket[5m]))

# Mock requests (when Qdrant is down)
rate(movie_api_mock_requests_total[5m])
```

## Files

```
monitoring/
├── docker-compose.yml              # Prometheus + Grafana services
├── prometheus.yml                  # Prometheus scrape config
├── provisioning/
│   ├── datasources/
│   │   └── prometheus.yml          # Auto-configure Prometheus datasource
│   └── dashboards/
│       ├── dashboards.yml          # Dashboard provisioning config
│       └── movie-api.json          # Pre-built dashboard
└── README.md                       # This file
```

## Commands

```bash
# Start monitoring stack
docker-compose up -d

# View logs
docker-compose logs -f

# Stop monitoring stack
docker-compose down

# Stop and remove volumes (reset data)
docker-compose down -v

# Restart after config changes
docker-compose restart
```

## Troubleshooting

### Prometheus can't reach the API

If running on macOS/Windows, the API runs on the host machine. The docker-compose uses `host.docker.internal` to reach it.

Check in Prometheus UI (http://localhost:9090/targets) that the `movie-api` target is UP.

### No data in Grafana

1. Ensure the API is running and returning metrics:
   ```bash
   curl http://localhost:8000/metrics
   ```

2. Check Prometheus is scraping:
   - Go to http://localhost:9090/targets
   - Verify `movie-api` target is UP

3. Wait a few seconds for data to appear

### Dashboard not showing

The dashboard is auto-provisioned. If it's not appearing:

```bash
docker-compose restart grafana
```

## Kubernetes Deployment

For K8s, use ServiceMonitor (if using Prometheus Operator):

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: movie-api
spec:
  selector:
    matchLabels:
      app: movie-api
  endpoints:
  - port: http
    path: /metrics
    interval: 15s
```

Or add pod annotations for auto-discovery:

```yaml
annotations:
  prometheus.io/scrape: "true"
  prometheus.io/port: "8000"
  prometheus.io/path: "/metrics"
```
