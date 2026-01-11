# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MLOps course project for Data Science Research Peru (DSRP). The system implements a movie recommendation/ranking pipeline using IMDB data, with infrastructure deployed to Azure Kubernetes Service (AKS).

## Key Commands

### Infrastructure (iac/)
```bash
# Setup Terraform backend (creates Azure Storage for state)
cd iac && task backend:setup

# Initialize Terraform with remote backend
terraform init -backend-config=backend.hcl

# Plan and apply infrastructure
terraform plan -var-file=dsrp-values.tfvars
terraform apply -var-file=dsrp-values.tfvars

# Assign DNS label to frontend LoadBalancer IP
task dns:set-label SERVICE_NAME=frontend SERVICE_NS=default DNS_LABEL=dsrp-frontend
```

### ML Notebooks (notebooks/)
```bash
cd notebooks

# Install dependencies with uv
uv sync

# Run hyperparameter optimization for LightGBM ranker
uv run python lgbm_ranker_hyperopt.py --data-path data/ltr_imdb_dataset.parquet --max-evals 25

# Start JupyterLab
uv run jupyter lab
```

### Frontend (app/frontend/)
```bash
cd app/frontend
npm install
npm run dev      # Development server
npm run build    # Production build
npm run lint     # TypeScript check (tsc --noEmit)
```

### Kubernetes Deployment
```bash
# Deploy frontend to AKS
kubectl apply -f k8s/frontend.yaml

# Verify deployment
kubectl get pods
kubectl get svc frontend
```

## Architecture

### ML Pipeline (notebooks/)
- **data_collection.ipynb**: Downloads IMDB datasets (title.basics, title.ratings) and enriches with OMDB API data. Outputs parquet files.
- **feature_engineering.ipynb**: Creates embeddings and similarity features for learning-to-rank (LTR).
- **modeling.ipynb**: Trains LightGBM ranker models with MLflow tracking.
- **lgbm_ranker_hyperopt.py**: Standalone hyperparameter optimization script using Hyperopt + MLflow.

Key libraries: polars (data), lightgbm (ranking), hyperopt (tuning), mlflow (tracking), qdrant-client (vector storage), sentence-transformers (embeddings).

### Infrastructure (iac/)
Terraform configuration for AKS cluster on Azure:
- `aks.tf`: AKS cluster with auto-scaling node pool
- `network.tf`: VNet and subnet configuration
- `log_analytics.tf`: Optional monitoring workspace
- `Taskfile.yml`: Task runner for backend setup and DNS configuration

### Frontend (app/frontend/)
React + Vite + TypeScript application. Containerized with multi-stage Docker build (Node for build, nginx for serving). Image published to GHCR via GitHub Actions.

### CI/CD (.github/workflows/)
- `frontend-docker.yml`: Builds and pushes frontend image to ghcr.io on changes to `app/frontend/` or the workflow itself.

## Environment Requirements

- **notebooks/**: Requires `.env` file with `OMDB_API_KEY` for data collection.
- **iac/**: Requires `dsrp-values.tfvars` with Azure configuration (see iac/README.md for template). Excluded from git.
