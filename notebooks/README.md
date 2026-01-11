# Pipeline de Machine Learning

Este directorio contiene el pipeline completo de Machine Learning para el sistema de ranking de películas.

## Estructura

```
notebooks/
├── data_collection.ipynb      # Ingesta de datos IMDB/OMDB
├── feature_engineering.ipynb  # Creación de features y embeddings
├── modeling.ipynb             # Entrenamiento de modelos
├── serving.ipynb              # Servicio de modelos
├── lgbm_ranker_hyperopt.py    # Script de optimización de hiperparámetros
├── ml_utils.py                # Utilidades para MLflow
├── data/                      # Datos procesados (no en git)
├── qdrant_data/               # Almacenamiento de vectores Qdrant
└── pyproject.toml             # Dependencias del proyecto
```

## Instalación

El proyecto usa [uv](https://github.com/astral-sh/uv) para gestión de dependencias:

```bash
# Instalar uv si no lo tienes
curl -LsSf https://astral.sh/uv/install.sh | sh

# Instalar dependencias
uv sync

# Activar entorno (opcional, uv run lo hace automáticamente)
source .venv/bin/activate
```

## Configuración

Crea un archivo `.env` con tu API key de OMDB:

```bash
OMDB_API_KEY=tu_api_key_aqui
```

Obtén tu API key en: https://www.omdbapi.com/apikey.aspx

## Notebooks

### 1. Recolección de Datos (`data_collection.ipynb`)

Descarga y procesa datos de películas:
- Descarga datasets de IMDB (title.basics, title.ratings)
- Enriquece con metadatos de la API de OMDB (poster, plot, director, etc.)
- Filtra películas con al menos 1000 votos
- Guarda en formato Parquet

### 2. Ingeniería de Features (`feature_engineering.ipynb`)

Prepara los datos para el modelo de ranking:
- Genera embeddings de texto con Sentence Transformers
- Calcula similitud coseno entre consultas y películas
- Crea features numéricas (rating, votos, etc.)
- Construye el dataset LTR (Learning to Rank)

### 3. Modelado (`modeling.ipynb`)

Entrena y evalúa modelos de ranking:
- LightGBM Ranker con objetivo lambdarank
- Métricas: NDCG@k, Precision@k, MAP
- Seguimiento de experimentos con MLflow

### 4. Servicio (`serving.ipynb`)

Implementa el servicio de recomendaciones:
- Almacenamiento de embeddings en Qdrant
- Búsqueda por similitud semántica
- Re-ranking con el modelo entrenado

## Script de Optimización

El script `lgbm_ranker_hyperopt.py` ejecuta búsqueda de hiperparámetros:

```bash
uv run python lgbm_ranker_hyperopt.py \
    --data-path data/ltr_imdb_dataset.parquet \
    --max-evals 25 \
    --k 10 \
    --experiment-name "LTR Hyperopt" \
    --tracking-uri http://localhost:5000
```

Parámetros:
- `--data-path`: Ruta al dataset LTR en formato Parquet
- `--max-evals`: Número de evaluaciones de Hyperopt
- `--k`: Cutoff para métricas NDCG/Precision
- `--valid-frac`: Fracción de queries para validación (default: 0.2)
- `--seed`: Semilla aleatoria
- `--experiment-name`: Nombre del experimento en MLflow
- `--tracking-uri`: URI del servidor MLflow (opcional)

## Dependencias Principales

| Librería | Uso |
|----------|-----|
| polars | Procesamiento de datos |
| lightgbm | Modelo de ranking |
| hyperopt | Optimización de hiperparámetros |
| mlflow | Seguimiento de experimentos |
| sentence-transformers | Embeddings de texto |
| qdrant-client | Base de datos vectorial |
| fastembed | Embeddings rápidos |

## Datos Generados

Los siguientes archivos se generan durante la ejecución (no incluidos en git):

- `data/movies_base.parquet`: Dataset base de películas
- `data/omdb_raw.jsonl`: Datos crudos de OMDB
- `data/complete_imdb_database.parquet`: Base de datos completa
- `data/ltr_imdb_dataset.parquet`: Dataset para LTR
- `data/movie_embs.npy`: Embeddings de películas
- `qdrant_storage/`: Datos de Qdrant
