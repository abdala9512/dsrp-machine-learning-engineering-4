# DSRP - Ingenieria de Machine Learning 4

<img src="utils/LOGO-DSRP.png" width="50%">

Proyecto del curso de MLOps e Ingenieria de Software para ML de Data Science Research Peru (DSRP). Este sistema implementa un pipeline de recomendacion/ranking de peliculas usando datos de IMDB, con infraestructura desplegada en Azure Kubernetes Service (AKS).

## Descripcion del Proyecto

El proyecto construye un sistema de **Learning to Rank (LTR)** para peliculas que incluye:

- **Recoleccion de datos**: Ingesta de IMDB y enriquecimiento con API de OMDB
- **Feature Engineering**: Generacion de embeddings con Sentence Transformers
- **Modelado**: Entrenamiento de modelos LightGBM Ranker con optimizacion de hiperparametros
- **Tracking**: Seguimiento de experimentos con MLflow
- **Vector Store**: Almacenamiento y busqueda semantica con Qdrant
- **Orquestacion**: Pipelines de ML con Apache Airflow 3
- **Despliegue**: Frontend y servicios en Azure Kubernetes Service

## Arquitectura del Sistema

### AS-IS (Estado Actual)

Sistema simple donde el frontend consulta directamente la API de IMDB:

```
+----------+          +------------+      HTTP Request     +----------+
|          |          |            |  ------------------>  |          |
|  Usuario |--------->|  DSRPFlix  |        Query          | API IMDB |
|          |          |  Frontend  |  <------------------  |          |
+----------+          +------------+       Response        +----------+
```

### TO-BE (Arquitectura Objetivo)

Sistema con backend inteligente que incluye retrieval semantico y re-ranking con ML:

```
+----------+          +------------+        Query         +------------------+     GET IDs    +----------+
|          |          |            |  ----------------->  |  DSRP Backend    | ------------> |          |
|  Usuario |--------->|  DSRPFlix  |                      |  (Retrieve & RR) |               | API IMDB |
|          |          |  Frontend  |  <-----------------  |                  | <------------ |          |
+----------+          +------------+        Recs          +--------+---------+    Metadata   +----------+
                                                                  |
                           +--------------------------------------+--------------------------------------+
                           |                                      |                                      |
                  +--------v--------+                    +--------v--------+                    +--------v--------+
                  |    Ollama OSS   |                    |    Retrieval    |      cand         |   Re-ranking    |
                  | +-------------+ |       Query        |     Service     | ----------------> |     Service     |
                  | | Translation | |  ----------------> | +-------------+ |                   | +-------------+ |
                  | +-------------+ |                    | | Transformer | |                   | | LightGBM /  | |
                  | +-------------+ |                    | | Embeddings  | |       Top-K       | | XGBoost     | |
                  | | Query       | |                    | +-------------+ | <---------------- | +-------------+ |
                  | | Refinement  | |                    +-----------------+                   +-----------------+
                  | +-------------+ |                           |
                  +-----------------+                    +------v------+
                                                         |   Qdrant    |
                                                         | Vector Store|
                                                         +-------------+
```

### Flujo de Datos TO-BE

1. **Usuario** realiza una busqueda en DSRPFlix (ej: "peliculas similares a Inception")
2. **Ollama API** procesa la query:
   - Traduccion (si es necesario)
   - Refinamiento de query para mejor recall
3. **Retrieval Service** usa embeddings (Sentence Transformers) para buscar candidatos en Qdrant
4. **Re-ranking Service** aplica modelo LightGBM/XGBoost para ordenar los candidatos por relevancia
5. **DSRP Backend** consulta API IMDB para obtener metadata adicional de los Top-K resultados
6. **DSRPFlix** muestra las recomendaciones ordenadas al usuario

### Pipeline de ML (Offline)

```
                                    +------------------+
                                    |   Apache Airflow |
                                    |   (Orquestacion) |
                                    +--------+---------+
                                             |
              +------------------------------+------------------------------+
              |                              |                              |
    +---------v----------+       +-----------v-----------+       +----------v---------+
    |  Data Collection   |       |  Feature Engineering  |       |     Modeling       |
    |  (IMDB + OMDB API) |------>|  (Embeddings + LTR)   |------>|  (LightGBM + HP)   |
    +--------------------+       +-----------------------+       +----------+---------+
                                             |                              |
                                    +--------v--------+            +--------v--------+
                                    |     Qdrant      |            |     MLflow      |
                                    | (Vector Store)  |            |   (Tracking)    |
                                    +-----------------+            +-----------------+
```

## Estructura del Repositorio

```
.
├── app/
│   └── frontend/                  # Aplicacion React + Vite + TypeScript
├── iac/                           # Infraestructura como codigo (Terraform)
│   ├── README.md                  # Guia de despliegue de infraestructura
│   ├── Taskfile.yml               # Automatizacion de tareas (backend, DNS)
│   ├── aks.tf                     # Configuracion del cluster AKS
│   └── dsrp-values.tfvars         # Variables de configuracion (no en git)
├── k8s/                           # Manifiestos de Kubernetes
│   ├── DESPLIEGUE_APPS.md         # Guia de despliegue de aplicaciones
│   ├── frontend.yaml              # Deployment del frontend
│   ├── qdrant.yaml                # Deployment de Qdrant
│   ├── airflow-namespace.yaml     # Namespace de Airflow
│   └── airflow-values.yaml        # Configuracion Helm de Airflow
├── notebooks/                     # Pipeline de ML
│   ├── README.md                  # Documentacion del pipeline
│   ├── ml_utils.py                # Utilidades compartidas
│   ├── data_collection.ipynb      # Ingesta de datos IMDB/OMDB
│   ├── feature_engineering.ipynb  # Creacion de features y embeddings
│   ├── synthetic_queries.ipynb    # Generacion de queries LTR
│   ├── modeling.ipynb             # Entrenamiento de modelos
│   ├── serving.ipynb              # Servicio de inferencia
│   └── lgbm_ranker_hyperopt.py    # Optimizacion de hiperparametros
├── .github/
│   └── workflows/                 # CI/CD con GitHub Actions
│       └── frontend-docker.yml    # Build y push de imagen Docker
├── CLAUDE.md                      # Instrucciones para Claude Code
└── AGENTS.md                      # Configuracion de agentes
```

## Tech Stack

| Categoria | Tecnologias |
|-----------|-------------|
| **ML Pipeline** | Python 3.11+, Polars, LightGBM, Hyperopt, Sentence Transformers |
| **Experiment Tracking** | MLflow, DagsHub |
| **Vector Database** | Qdrant |
| **Orchestration** | Apache Airflow 3 (KubernetesExecutor) |
| **Frontend** | React, Vite, TypeScript, TailwindCSS |
| **Infrastructure** | Terraform, Azure AKS, Helm |
| **CI/CD** | GitHub Actions, GitHub Container Registry (GHCR) |
| **Package Management** | uv (Python), npm (Node.js) |

## Requisitos

- Python 3.11+ con [uv](https://github.com/astral-sh/uv)
- Node.js 18+
- Azure CLI, Terraform y kubectl (para infraestructura)
- Helm 3.x (para Airflow y otros charts)
- Docker (para contenedores)

## Inicio Rapido

### Opcion 1: Despliegue Completo con Taskfile (Recomendado)

El proyecto incluye un Taskfile que automatiza todo el despliegue:

```bash
# Instalar task (go-task) si no lo tienes
# macOS: brew install go-task
# Linux: sh -c "$(curl --location https://taskfile.dev/install.sh)" -- -d

# Ver todas las tareas disponibles
task --list

# Despliegue completo: infraestructura + aplicaciones + DNS
task deploy:all

# O ejecutar pasos individuales:
task deploy:infra          # Solo infraestructura (backend + Terraform)
task deploy:apps           # Solo aplicaciones
task dns:configure         # Solo configuracion DNS
```

#### Comandos Principales del Taskfile

| Comando | Descripcion |
|---------|-------------|
| `task deploy:all` | Despliegue completo desde cero |
| `task deploy:infra` | Backend de Terraform + AKS |
| `task deploy:apps` | Desplegar todas las aplicaciones |
| `task deploy:app APP=<name>` | Desplegar una aplicacion especifica |
| `task dns:configure` | Configurar DNS para todas las apps |
| `task status` | Ver estado de todos los componentes |
| `task apps:list` | Listar aplicaciones registradas |

#### Utilidades

| Comando | Descripcion |
|---------|-------------|
| `task logs APP=<name>` | Ver logs de una aplicacion |
| `task port-forward APP=<name>` | Port-forward local |
| `task status:app APP=<name>` | Estado detallado de una app |
| `task destroy:app APP=<name>` | Eliminar una aplicacion |
| `task destroy:all` | Eliminar todas las aplicaciones |
| `task destroy:infra` | Destruir infraestructura (requiere confirmacion) |

#### Agregar Nuevas Aplicaciones

Para agregar una nueva aplicacion, edita la variable `APPLICATIONS` en `Taskfile.yml`:

```yaml
# Formato: nombre|namespace|manifest|service|dns_label|tipo
APPLICATIONS: |
  frontend|default|k8s/frontend.yaml|frontend|dsrp-frontend|kubectl
  qdrant|default|k8s/qdrant.yaml|qdrant|qdrant-dsrp|kubectl
  airflow|airflow|k8s/airflow-values.yaml|airflow-api-server|airflow-dsrp|helm
  mi-app|default|k8s/mi-app.yaml|mi-app|mi-app-dsrp|kubectl  # Nueva app
```

### Opcion 2: Despliegue Manual Paso a Paso

#### 2.1 Pipeline de ML (notebooks/)

```bash
cd notebooks

# Instalar dependencias
uv sync

# Iniciar JupyterLab
uv run jupyter lab

# Ejecutar notebooks en orden:
# 1. data_collection.ipynb
# 2. feature_engineering.ipynb
# 3. synthetic_queries.ipynb
# 4. modeling.ipynb
# 5. qdrant_indexing.ipynb (indexar en Qdrant)
# 6. serving.ipynb (probar busquedas)

# O ejecutar optimizacion de hiperparametros directamente
uv run python lgbm_ranker_hyperopt.py --data-path data/ltr_imdb_dataset.parquet --max-evals 25
```

#### 2.2 Frontend (app/frontend/)

```bash
cd app/frontend

npm install
npm run dev      # Servidor de desarrollo (http://localhost:5173)
npm run build    # Build de produccion
npm run lint     # Verificacion de TypeScript
```

#### 2.3 Infraestructura (iac/)

```bash
cd iac

# Configurar backend de Terraform
task backend:setup

# Inicializar y desplegar
terraform init -backend-config=backend.hcl
terraform plan -var-file=dsrp-values.tfvars
terraform apply -var-file=dsrp-values.tfvars

# Configurar acceso al cluster
az aks get-credentials --resource-group rg-aks-dsrp4-prod2025 --name aks-cluster-dsrp4
```

#### 2.4 Despliegue en Kubernetes

```bash
# Desplegar frontend
kubectl apply -f k8s/frontend.yaml

# Desplegar Qdrant
kubectl apply -f k8s/qdrant.yaml

# Desplegar Airflow
kubectl apply -f k8s/airflow-namespace.yaml
helm repo add apache-airflow https://airflow.apache.org
helm install airflow apache-airflow/airflow -n airflow -f k8s/airflow-values.yaml

# Verificar deployments
kubectl get pods --all-namespaces
kubectl get svc --all-namespaces
```

#### 2.5 Configurar DNS (opcional)

```bash
cd iac

# Asignar DNS labels a los servicios
task dns:set-label SERVICE=frontend LABEL=dsrp-frontend
task dns:set-label SERVICE=qdrant LABEL=qdrant-dsrp
task dns:set-label SERVICE=airflow-api-server NS=airflow LABEL=airflow-dsrp
```

## Configuracion

### Variables de Entorno

El proyecto requiere los siguientes archivos de configuracion (no incluidos en git):

| Archivo | Descripcion |
|---------|-------------|
| `notebooks/.env` | Contiene `OMDB_API_KEY` para recoleccion de datos |
| `iac/dsrp-values.tfvars` | Configuracion de Azure (ver `iac/README.md`) |
| `iac/backend.hcl` | Configuracion del backend de Terraform |

### Ejemplo de .env

```bash
# notebooks/.env
OMDB_API_KEY=tu_api_key_aqui
MLFLOW_TRACKING_URI=https://dagshub.com/usuario/repo.mlflow
```

## Documentacion

| Documento | Descripcion |
|-----------|-------------|
| [iac/README.md](iac/README.md) | Despliegue de infraestructura AKS con Terraform |
| [k8s/DESPLIEGUE_APPS.md](k8s/DESPLIEGUE_APPS.md) | Guia de despliegue de aplicaciones (Frontend, Qdrant, Airflow) |
| [notebooks/README.md](notebooks/README.md) | Documentacion del pipeline de ML |
| [CLAUDE.md](CLAUDE.md) | Instrucciones para Claude Code |

## URLs de Produccion

Una vez desplegado, los servicios estan disponibles en:

| Servicio | URL |
|----------|-----|
| Frontend | `http://dsrp-frontend.<region>.cloudapp.azure.com` |
| Qdrant Dashboard | `http://qdrant-dsrp.<region>.cloudapp.azure.com:6333/dashboard` |
| Airflow UI | `http://airflow-dsrp.<region>.cloudapp.azure.com` |

## Pipeline de ML

El pipeline de ML sigue estos pasos:

1. **Data Collection** (`data_collection.ipynb`)
   - Descarga datasets de IMDB (title.basics, title.ratings)
   - Enriquece con datos de OMDB API (Plot, Director, Actors)
   - Genera `movies_base.parquet` y `omdb_raw.jsonl`

2. **Feature Engineering** (`feature_engineering.ipynb`)
   - Combina datos IMDB + OMDB
   - Genera embeddings con Sentence Transformers
   - Crea features derivadas (log votes, year norm, etc.)
   - Guarda `complete_imdb_database.parquet` y `movie_embs.npy`

3. **Synthetic Queries** (`synthetic_queries.ipynb`)
   - Genera queries sinteticas con plantillas y LLM (Ollama)
   - Recupera candidatos usando similitud de embeddings
   - Calcula scores de relevancia
   - Genera dataset LTR (`ltr_imdb_dataset.parquet`)

4. **Modeling** (`modeling.ipynb`)
   - Entrena modelos LightGBM Ranker
   - Tracking con MLflow
   - Evaluacion con NDCG@K

5. **Hyperparameter Optimization** (`lgbm_ranker_hyperopt.py`)
   - Optimizacion con Hyperopt + MLflow
   - Busqueda automatica de mejores parametros

## Contribucion

Este proyecto es parte del curso de Ingenieria de ML de DSRP. Para contribuir:

1. Fork el repositorio
2. Crea una rama (`git checkout -b feature/nueva-funcionalidad`)
3. Commit los cambios (`git commit -m 'Agrega nueva funcionalidad'`)
4. Push a la rama (`git push origin feature/nueva-funcionalidad`)
5. Abre un Pull Request

## Licencia

Proyecto educativo de Data Science Research Peru (DSRP).
