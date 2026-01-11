# DSRP - Ingeniería de Machine Learning 4

<img src="utils/LOGO-DSRP.png" width="50%">

Proyecto del curso de MLOps e Ingeniería de Software para ML de Data Science Research Peru (DSRP). Este sistema implementa un pipeline de recomendación/ranking de películas usando datos de IMDB, con infraestructura desplegada en Azure Kubernetes Service (AKS).

## Descripción del Proyecto

El proyecto construye un sistema de Learning to Rank (LTR) para películas que incluye:
- Recolección de datos de IMDB y enriquecimiento con la API de OMDB
- Generación de embeddings con Sentence Transformers
- Entrenamiento de modelos LightGBM Ranker con optimización de hiperparámetros
- Seguimiento de experimentos con MLflow
- Almacenamiento vectorial con Qdrant
- Frontend desplegado en Kubernetes

## Estructura del Repositorio

```
.
├── app/
│   └── frontend/          # Aplicación React + Vite + TypeScript
├── iac/                   # Infraestructura como código (Terraform para AKS)
│   ├── README.md          # Guía de despliegue de infraestructura
│   └── Taskfile.yml       # Automatización de tareas
├── k8s/                   # Manifiestos de Kubernetes
│   ├── DESPLIEGUE_APPS.md # Guía de despliegue de aplicaciones
│   └── frontend.yaml      # Deployment y Service del frontend
├── notebooks/             # Pipeline de ML
│   ├── data_collection.ipynb      # Ingesta de datos IMDB/OMDB
│   ├── feature_engineering.ipynb  # Creación de features y embeddings
│   ├── modeling.ipynb             # Entrenamiento de modelos
│   └── lgbm_ranker_hyperopt.py    # Optimización de hiperparámetros
└── .github/
    └── workflows/         # CI/CD con GitHub Actions
```

## Requisitos

- Python 3.11+ con [uv](https://github.com/astral-sh/uv)
- Node.js 18+
- Azure CLI, Terraform y kubectl (para infraestructura)
- Docker (para contenedores)

## Inicio Rápido

### Pipeline de ML (notebooks/)

```bash
cd notebooks

# Instalar dependencias
uv sync

# Iniciar JupyterLab
uv run jupyter lab

# Ejecutar optimización de hiperparámetros
uv run python lgbm_ranker_hyperopt.py --data-path data/ltr_imdb_dataset.parquet --max-evals 25
```

### Frontend (app/frontend/)

```bash
cd app/frontend

npm install
npm run dev      # Servidor de desarrollo
npm run build    # Build de producción
npm run lint     # Verificación de TypeScript
```

### Infraestructura (iac/)

```bash
cd iac

# Configurar backend de Terraform
task backend:setup

# Inicializar y desplegar
terraform init -backend-config=backend.hcl
terraform plan -var-file=dsrp-values.tfvars
terraform apply -var-file=dsrp-values.tfvars
```

### Despliegue en Kubernetes

```bash
# Desplegar frontend
kubectl apply -f k8s/frontend.yaml

# Verificar
kubectl get pods
kubectl get svc frontend
```

## Configuración

### Variables de Entorno

El proyecto requiere los siguientes archivos de configuración (no incluidos en git):

- `notebooks/.env`: Contiene `OMDB_API_KEY` para la recolección de datos
- `iac/dsrp-values.tfvars`: Configuración de Azure (ver `iac/README.md` para plantilla)

## Documentación Adicional

- [Despliegue de AKS con Terraform](iac/README.md)
- [Despliegue de Apps en Kubernetes](k8s/DESPLIEGUE_APPS.md)
- [Pipeline de ML](notebooks/README.md)

## Tecnologías Principales

| Componente | Tecnologías |
|------------|-------------|
| ML Pipeline | Polars, LightGBM, Hyperopt, MLflow, Sentence Transformers |
| Vector Store | Qdrant |
| Frontend | React, Vite, TypeScript |
| Infraestructura | Terraform, Azure AKS |
| CI/CD | GitHub Actions, GHCR |
