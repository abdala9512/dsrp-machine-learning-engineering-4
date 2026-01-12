# Notebooks - ML Pipeline para Ranking de Peliculas

Este directorio contiene el pipeline completo de Machine Learning para el sistema de recomendacion/ranking de peliculas IMDB.

## Requisitos

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) para gestion de dependencias

```bash
# Instalar uv si no lo tienes
curl -LsSf https://astral.sh/uv/install.sh | sh

# Instalar dependencias
uv sync

# Iniciar JupyterLab
uv run jupyter lab
```

## Estructura de Notebooks

| Notebook | Descripcion | Entradas | Salidas |
|----------|-------------|----------|---------|
| `data_collection.ipynb` | Recoleccion de datos IMDB/OMDB | APIs externas | `movies_base.parquet`, `omdb_raw.jsonl` |
| `feature_engineering.ipynb` | Creacion de features y embeddings | Parquets base | `complete_imdb_database.parquet`, `movie_embs.npy` |
| `synthetic_queries.ipynb` | Generacion de queries para LTR | Embeddings | `ltr_imdb_dataset.parquet` |
| `modeling.ipynb` | Entrenamiento de modelos LightGBM | Dataset LTR | Modelos en MLflow |
| `qdrant_indexing.ipynb` | Indexacion en Qdrant | Database completa | Coleccion en Qdrant |
| `serving.ipynb` | Busqueda y recomendaciones | Qdrant | Resultados de busqueda |

## Orden de Ejecucion

```
1. data_collection.ipynb
        |
        v
2. feature_engineering.ipynb
        |
        v
3. synthetic_queries.ipynb
        |
        v
4. modeling.ipynb
        |
        v
5. qdrant_indexing.ipynb  (requiere Qdrant corriendo)
        |
        v
6. serving.ipynb          (consultas y recomendaciones)
```

## Descripcion Detallada

### 1. data_collection.ipynb

**Objetivo**: Recolectar y combinar datos de IMDB y OMDB API.

**Proceso**:
- Descarga datasets de IMDB (title.basics.tsv.gz, title.ratings.tsv.gz)
- Filtra peliculas (excluye series, cortos, etc.)
- Enriquece con datos de OMDB API (Plot, Director, Actors, Awards)
- Maneja rate limiting de la API

**Salidas**:
- `data/movies_base.parquet`: Datos base de IMDB
- `data/omdb_raw.jsonl`: Respuestas crudas de OMDB API

**Configuracion requerida**:
```bash
# .env
OMDB_API_KEY=tu_api_key_aqui
```

Obtener API key en: https://www.omdbapi.com/apikey.aspx

### 2. feature_engineering.ipynb

**Objetivo**: Crear features derivadas y embeddings para busqueda semantica.

**Proceso**:
- Combina datos IMDB + OMDB
- Genera embeddings con Sentence Transformers (`all-MiniLM-L6-v2`)
- Crea features derivadas:
  - `imdb_votes_log`: Log de votos para normalizar distribucion
  - `year_normalized`: Ano normalizado entre 0-1
  - `runtime_normalized`: Duracion normalizada
  - `genres_encoded`: Generos one-hot encoded

**Salidas**:
- `data/complete_imdb_database.parquet`: Base de datos completa
- `data/movie_embs.npy`: Embeddings de peliculas (N x 384 dims)

### 3. synthetic_queries.ipynb

**Objetivo**: Generar dataset de entrenamiento para Learning to Rank (LTR).

**Proceso**:
- Genera queries sinteticas usando plantillas y LLM (Ollama)
- Para cada query, recupera candidatos usando similitud de embeddings
- Calcula scores de relevancia basados en:
  - Similitud coseno con la query
  - Rating de IMDB
  - Popularidad (votos)
- Formatea datos para LightGBM Ranker

**Salidas**:
- `data/ltr_imdb_dataset.parquet`: Dataset con columnas:
  - `query_id`: ID unico de la query
  - `query_text`: Texto de la query
  - `imdb_id`: ID de la pelicula candidata
  - `relevance`: Score de relevancia (target)
  - Features numericas para ranking

### 4. modeling.ipynb

**Objetivo**: Entrenar y evaluar modelos de ranking.

**Proceso**:
- Carga dataset LTR
- Entrena LightGBM con objetivo `lambdarank`
- Evalua con metricas de ranking
- Tracking de experimentos con MLflow

**Metricas**:
- NDCG@5, NDCG@10, NDCG@20
- MAP (Mean Average Precision)
- Precision@K

**Salidas**:
- Modelos registrados en MLflow
- Metricas y parametros trackeados

### 5. qdrant_indexing.ipynb

**Objetivo**: Indexar peliculas en Qdrant para busqueda hibrida.

**Proceso**:
- Conecta a Qdrant (local o remoto)
- Crea coleccion con vectores:
  - **Dense**: Embeddings de Sentence Transformers (384 dims)
  - **Sparse**: Tokenizacion BM25-like para busqueda por keywords
- Indexa todas las peliculas en batches
- Verifica indexacion con busqueda de prueba

**Configuracion**:
```python
# Para Qdrant local (Docker o port-forward)
QDRANT_URL = "http://localhost:6333"

# Para Qdrant remoto (AKS)
export QDRANT_URL="http://qdrant-dsrp.eastus.cloudapp.azure.com:6333"
```

**Cuando ejecutar**:
- Primera vez que se despliega Qdrant
- Cuando se actualiza la base de datos de peliculas
- Cuando se necesita recrear el indice

### 6. serving.ipynb

**Objetivo**: Probar busquedas y recomendaciones (solo cliente, no indexa).

**Proceso**:
- Conecta a Qdrant existente (valida que la coleccion exista)
- Realiza busquedas hibridas (dense + BM25)
- Muestra resultados formateados con metadata

**Modos de busqueda**:
- **Busqueda semantica**: Usando solo embeddings densos
- **Busqueda hibrida**: Combinando embeddings + BM25 (Reciprocal Rank Fusion)

**Nota**: Este notebook NO indexa datos. Para indexar, usar `qdrant_indexing.ipynb`.

## Scripts Standalone

### lgbm_ranker_hyperopt.py

Script para optimizacion de hiperparametros usando Hyperopt + MLflow.

```bash
# Ejecutar optimizacion
uv run python lgbm_ranker_hyperopt.py \
  --data-path data/ltr_imdb_dataset.parquet \
  --max-evals 25

# Todas las opciones
uv run python lgbm_ranker_hyperopt.py \
  --data-path data/ltr_imdb_dataset.parquet \
  --max-evals 50 \
  --k 10 \
  --valid-frac 0.2 \
  --seed 42 \
  --experiment-name "LTR Hyperopt" \
  --tracking-uri http://localhost:5000
```

**Parametros optimizados**:
- `num_leaves`: 20-150
- `learning_rate`: 0.01-0.3
- `min_data_in_leaf`: 10-100
- `lambda_l1`, `lambda_l2`: Regularizacion L1/L2
- `feature_fraction`: Subsampling de features
- `bagging_fraction`: Subsampling de datos

### ml_utils.py

Utilidades compartidas entre notebooks:
- Funciones de preprocesamiento
- Metricas de evaluacion
- Helpers de MLflow

## Datos

Los datos se almacenan en `notebooks/data/` (no incluidos en git):

```
data/
├── movies_base.parquet           # Datos base IMDB (~200k peliculas)
├── omdb_raw.jsonl                # Respuestas OMDB API
├── complete_imdb_database.parquet # Base de datos completa con plots
├── movie_embs.npy                # Embeddings (N x 384)
└── ltr_imdb_dataset.parquet      # Dataset para LTR
```

## MLflow Tracking

El proyecto usa MLflow para tracking de experimentos.

```bash
# Opcion 1: MLflow local
mlflow ui  # Abre http://localhost:5000

# Opcion 2: DagsHub (remoto)
export MLFLOW_TRACKING_URI=https://dagshub.com/usuario/repo.mlflow
export MLFLOW_TRACKING_USERNAME=usuario
export MLFLOW_TRACKING_PASSWORD=token
```

## Conexion a Qdrant

### Qdrant Local (Desarrollo)

```bash
# Opcion 1: Docker
docker run -p 6333:6333 -p 6334:6334 qdrant/qdrant

# Opcion 2: Port-forward desde AKS
kubectl port-forward svc/qdrant 6333:6333
```

### Qdrant Remoto (AKS)

```bash
# Configurar variable de entorno
export QDRANT_URL="http://qdrant-dsrp.eastus.cloudapp.azure.com:6333"

# Los notebooks detectan automaticamente QDRANT_URL
```

Dashboard web: `http://<QDRANT_URL>/dashboard`

## Dependencias Principales

| Libreria | Version | Uso |
|----------|---------|-----|
| `polars` | >=0.20 | Procesamiento de datos (rapido, eficiente) |
| `lightgbm` | >=4.0 | Modelos de ranking (LambdaRank) |
| `sentence-transformers` | >=2.2 | Generacion de embeddings |
| `qdrant-client` | >=1.7 | Cliente para Qdrant |
| `hyperopt` | >=0.2 | Optimizacion de hiperparametros |
| `mlflow` | >=2.10 | Tracking de experimentos |
| `httpx` | >=0.26 | Cliente HTTP async para APIs |
| `python-dotenv` | >=1.0 | Carga de variables de entorno |

## Troubleshooting

### Error: "OMDB API key not found"
```bash
# Crear archivo .env en notebooks/
echo "OMDB_API_KEY=tu_key" > .env
```

### Error: "Cannot connect to Qdrant"
```bash
# Verificar que Qdrant este corriendo
curl http://localhost:6333/health

# Si esta en AKS, verificar el servicio
kubectl get svc qdrant

# Iniciar localmente con Docker
docker run -p 6333:6333 qdrant/qdrant
```

### Error: "Collection not found" en serving.ipynb
```bash
# Ejecutar primero qdrant_indexing.ipynb para crear la coleccion
# O verificar que QDRANT_URL apunte al servidor correcto
```

### Error: "MLflow tracking failed"
```bash
# Verificar configuracion
echo $MLFLOW_TRACKING_URI

# Usar tracking local si hay problemas
unset MLFLOW_TRACKING_URI
mlflow ui
```

### Memoria insuficiente para embeddings
```python
# En feature_engineering.ipynb, reducir batch size
BATCH_SIZE = 100  # Reducir si hay OOM

# O procesar en chunks
for chunk in df.iter_slices(n_rows=1000):
    embeddings = model.encode(chunk["text"].to_list())
```

### Qdrant indexacion lenta
```python
# En qdrant_indexing.ipynb, ajustar batch size
BATCH_SIZE = 500  # Incrementar para mayor velocidad (requiere mas RAM)
```
