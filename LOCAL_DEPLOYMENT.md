# Guía de Desarrollo Local

Esta guía explica cómo ejecutar la plataforma completa de Recomendaciones de Películas DSRP localmente para desarrollo y pruebas.

## Tabla de Contenidos

1. [Arquitectura General](#arquitectura-general)
2. [Requisitos Previos](#requisitos-previos)
3. [Configuración Inicial](#configuración-inicial)
4. [Inicio Rápido](#inicio-rápido)
5. [Configuración Detallada](#configuración-detallada)
6. [Monitoreo y Dashboards](#monitoreo--dashboards)
7. [Solución de Problemas](#solución-de-problemas)

---

## Arquitectura General

```
┌─────────────────────────────────────────────────────────────────┐
│                     Frontend (React + Vite)                      │
│                        Puerto 5173                               │
│              http://localhost:5173                               │
└──────────────────────────┬──────────────────────────────────────┘
                           │ /search, /health, /movie
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Backend API (FastAPI)                        │
│                        Puerto 8080                               │
│              http://localhost:8080                               │
│                                                                  │
│  • Orquesta Servicio ML + API IMDB                              │
│  • Métricas Prometheus en /metrics                               │
└──────────────────────────┬──────────────────────────────────────┘
                           │
          ┌────────────────┼────────────────┐
          ▼                                 ▼
┌─────────────────────┐         ┌─────────────────────┐
│   Servicio ML API   │         │     API IMDB        │
│     Puerto 8000     │         │   (Externo)         │
│                     │         │                     │
│ • LightGBM LTR      │         │ • Detalles películas│
│ • Embeddings        │         │ • Imágenes pósters  │
│ • Búsqueda Qdrant   │         │                     │
│ • Métricas nDCG     │         │                     │
│ • Drift de features │         │                     │
└─────────┬───────────┘         └─────────────────────┘
          │
          ▼
┌─────────────────────┐         ┌─────────────────────┐
│   Qdrant (Vectores) │         │   MLflow (DagsHub)  │
│     Puerto 6333     │         │     (Remoto)        │
│                     │         │                     │
│ • Embeddings densos │         │ • Registro modelos  │
│ • BM25 disperso     │         │ • Logs experimentos │
│ • Búsqueda híbrida  │         │                     │
└─────────────────────┘         └─────────────────────┘
```

### Componentes

| Componente | Puerto | Descripción |
|-----------|------|-------------|
| **Frontend** | 5173 | Aplicación React para la interfaz de búsqueda |
| **Backend** | 8080 | Capa de orquestación de API |
| **Servicio ML** | 8000 | Modelo LightGBM LTR + embeddings |
| **Qdrant** | 6333 | Base de datos vectorial para búsqueda híbrida |
| **Prometheus** | 9090 | Recolección de métricas |
| **Grafana** | 3000 | Dashboards de monitoreo |

---

## Requisitos Previos

### Software Requerido

| Software | Versión | Instalación |
|----------|---------|--------------|
| **Docker** | 20.10+ | [docker.com](https://docs.docker.com/get-docker/) |
| **uv** | 0.1+ | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| **Node.js** | 18+ | [nodejs.org](https://nodejs.org/) |
| **Task** | 3.0+ | `brew install go-task` o [taskfile.dev](https://taskfile.dev/installation/) |

### Verificar Instalación

```bash
docker --version      # Docker version 20.10+
uv --version          # uv 0.1+
node --version        # v18+
task --version        # Task version 3+
```

---

## Configuración Inicial

### 1. Clonar el Repositorio

```bash
git clone https://github.com/abdala9512/dsrp-machine-learning-engineering-4.git
cd dsrp-machine-learning-engineering-4
```

### 2. Configurar Acceso a DagsHub/MLflow

El Servicio ML carga el modelo LightGBM entrenado desde MLflow (alojado en DagsHub). Necesitas un token de DagsHub para acceder al registro de modelos.

1. **Obtén tu token de DagsHub**:
   - Ve a [DagsHub](https://dagshub.com/user/settings/tokens)
   - Crea un nuevo token con acceso de lectura

2. **Configura el entorno**:
   ```bash
   cd app/serving/real_time
   cp mlapi.env.example mlapi.env  # Si el ejemplo existe, sino edita mlapi.env
   ```

3. **Edita `mlapi.env`** con tu token:
   ```env
   # Autenticación DagsHub (REQUERIDO)
   DAGSHUB_USER_TOKEN=tu_token_aqui
   DAGSHUB_REPO_OWNER=abdala9512
   DAGSHUB_REPO_NAME=dsrp-machine-learning-engineering-4

   # Modelo MLflow (estos son los valores por defecto)
   LTR_MODEL_NAME=ltr-dsrpflix-prd-ENE12
   LTR_MODEL_ALIAS=champion

   # Qdrant local (será configurado por Taskfile)
   QDRANT_URL=http://localhost:6333
   QDRANT_COLLECTION=imdb-movies-hybrid
   ```

### 3. Preparar la Base de Datos de Películas

El sistema requiere la base de datos de películas IMDB en formato parquet. Hay dos opciones:

**Opción A: Usar datos existentes (recomendado)**

Si tienes acceso a los datos de los notebooks:
```bash
# El Taskfile encontrará automáticamente los datos en:
# - app/serving/real_time/complete_imdb_database.parquet
# - notebooks/data/complete_imdb_database.parquet
```

**Opción B: Generar desde cero**

Ejecuta el notebook de recolección de datos:
```bash
cd notebooks
uv sync
uv run jupyter lab
# Abre y ejecuta: data_collection.ipynb
```

Esto requiere una clave de API de OMDB en `notebooks/.env`:
```env
OMDB_API_KEY=tu_clave_api_omdb
```

### 4. Instalar Dependencias

```bash
# Desde la raíz del repositorio
task local:deps:install

# O manualmente:
cd app/serving/real_time && uv sync
cd ../backend && uv sync
cd ../frontend && npm install
```

---

## Inicio Rápido

Una vez completada la configuración inicial, puedes iniciar toda la pila con:

```bash
# Terminal 1: Iniciar infraestructura (Qdrant + monitoreo)
task local:start:all

# Terminal 2: Iniciar Servicio ML
task local:api:start

# Terminal 3: Iniciar Backend
task local:backend:start

# Terminal 4: Iniciar Frontend
task local:frontend:start
```

**Acceder a la aplicación:**

| Servicio | URL |
|---------|-----|
| Frontend | http://localhost:5173 |
| Backend API | http://localhost:8080 |
| Docs del Backend | http://localhost:8080/docs |
| Servicio ML API | http://localhost:8000 |
| Docs del Servicio ML | http://localhost:8000/docs |
| Dashboard Qdrant | http://localhost:6333/dashboard |
| Prometheus | http://localhost:9090 |
| Grafana | http://localhost:3000 (admin/admin) |

---

## Configuración Detallada

### Dependencias del Pipeline ML

El Servicio ML depende de varios componentes que deben configurarse antes de que el servicio funcione correctamente.

#### 1. Entrenamiento del Modelo (MLflow)

El modelo LightGBM LTR debe ser entrenado y registrado en MLflow antes de que el servicio pueda cargarlo.

**Pipeline de Entrenamiento:**

```
notebooks/data_collection.ipynb     → Datos IMDB
         ↓
notebooks/feature_engineering.ipynb → Extracción de features
         ↓
notebooks/synthetic_queries.ipynb   → Datos de entrenamiento LTR
         ↓
notebooks/modeling.ipynb            → Entrenar y registrar modelo
```

**Para entrenar el modelo:**

```bash
cd notebooks
uv sync

# Instalar Jupyter
uv run pip install jupyterlab

# Iniciar JupyterLab
uv run jupyter lab
```

Ejecuta los notebooks en orden:

1. **`data_collection.ipynb`**: Descarga datasets de IMDB y enriquece con la API de OMDB
   - Salida: `data/complete_imdb_database.parquet`
   - Requiere: `OMDB_API_KEY` en `.env`

2. **`feature_engineering.ipynb`**: Crea embeddings y features
   - Salida: Archivos parquet enriquecidos con features
   - Usa: `sentence-transformers/all-MiniLM-L6-v2`

3. **`synthetic_queries.ipynb`**: Genera datos de entrenamiento LTR
   - Salida: `data/ltr_synthetic_dataset.parquet`
   - Crea pares sintéticos consulta-documento con etiquetas de relevancia

4. **`modeling.ipynb`**: Entrena modelo LightGBM LTR
   - Salida: Modelo registrado en MLflow como `ltr-dsrpflix-prd-ENE12`
   - Promueve el mejor modelo al alias `@champion`
   - Registra métricas nDCG@k

**Configuración del Modelo:**

```python
# Features del modelo (de config.py)
feature_cols = ["sim_embedding", "imdb_rating", "imdb_votes_log"]

# URI del modelo
model_uri = "models:/ltr-dsrpflix-prd-ENE12@champion"
```

#### 2. Inicialización de Qdrant

Después de iniciar Qdrant, inicialízalo con los embeddings de películas:

```bash
# Iniciar contenedor de Qdrant
task local:qdrant:start

# Inicializar con datos de películas (crea colección + índices)
task local:qdrant:init

# Verificar inicialización
task local:qdrant:status
```

**Qué hace la inicialización:**

1. Crea la colección `imdb-movies-hybrid` con:
   - Vectores densos (embeddings de sentence-transformer de 384 dimensiones)
   - Vectores dispersos (tipo BM25 para búsqueda por palabras clave)

2. Indexa todas las películas (~47K) con:
   - Embeddings de texto completo
   - Índices de tokens dispersos

3. Verifica con una búsqueda de prueba

**Forzar re-indexación:**
```bash
task local:qdrant:init FORCE_REINDEX=true
```

### Orden de Inicio de Servicios

Para un funcionamiento correcto, inicia los servicios en este orden:

```bash
# 1. Infraestructura (Qdrant debe estar listo antes del Servicio ML)
task local:qdrant:start
task local:qdrant:init       # Solo la primera vez
task local:monitoring:start  # Opcional, para dashboards

# 2. Servicio ML (debe estar listo antes del Backend)
task local:api:start

# 3. Backend (depende del Servicio ML)
task local:backend:start

# 4. Frontend (depende del Backend)
task local:frontend:start
```

### Referencia de Configuración

#### Servicio ML (`app/serving/real_time/mlapi.env`)

```env
# Servidor
HOST=0.0.0.0
PORT=8000
WORKERS=1

# DagsHub/MLflow (REQUERIDO)
DAGSHUB_USER_TOKEN=tu_token_aqui
DAGSHUB_REPO_OWNER=abdala9512
DAGSHUB_REPO_NAME=dsrp-machine-learning-engineering-4

# Modelo
LTR_MODEL_NAME=ltr-dsrpflix-prd-ENE12
LTR_MODEL_ALIAS=champion

# Embeddings
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2

# Qdrant
QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION=imdb-movies-hybrid
MOCK_QDRANT=false

# Búsqueda
TOP_K_RETRIEVAL=100
TOP_K_FINAL=10
```

#### Backend (`app/backend/`)

Variables de entorno (configuradas por Taskfile):
```env
ML_SERVICE_URL=http://localhost:8000
HOST=0.0.0.0
PORT=8080
ENABLE_ML_SERVICE=true
CORS_ORIGINS=*
```

#### Frontend (`app/frontend/vite.config.ts`)

Redirige peticiones al backend:
```typescript
proxy: {
  "/search": "http://localhost:8080",
  "/health": "http://localhost:8080",
  "/movie": "http://localhost:8080",
}
```

---

## Monitoreo y Dashboards

### Dashboards de Grafana

Accede a Grafana en http://localhost:3000 (admin/admin)

| Dashboard | URL | Métricas |
|-----------|-----|---------|
| **Servicio ML** | `/d/movie-api-dashboard` | nDCG, distribuciones de features, scores LTR, latencias del pipeline |
| **Backend** | `/d/backend-dashboard` | Tasas de peticiones, latencias ML/IMDB, tasas de error |

### Métricas del Servicio ML

El Servicio ML expone estas métricas de Prometheus en `/metrics`:

**Métricas de Calidad:**
- `movie_api_ndcg_score` - nDCG@k simulado por petición
- `movie_api_ndcg_at_k` - Histograma de distribución de nDCG

**Drift de Features:**
- `movie_api_feature_sim_embedding` - Distribución de similitud coseno
- `movie_api_feature_imdb_rating` - Distribución de ratings
- `movie_api_feature_imdb_votes_log` - Distribución de cantidad de votos
- `movie_api_ltr_score` - Distribución de salida del modelo LTR

**Latencias:**
- `movie_api_request_latency_seconds` - Latencia total de petición
- `movie_api_embedding_latency_seconds` - Generación de embeddings
- `movie_api_retrieval_latency_seconds` - Búsqueda en Qdrant
- `movie_api_rerank_latency_seconds` - Re-ranking LTR

### Métricas del Backend

Disponibles en http://localhost:8080/metrics:

- `backend_requests_total` - Conteo de peticiones por endpoint/estado/fuente
- `backend_request_latency_seconds` - Latencia general
- `backend_ml_service_latency_seconds` - Latencia de llamadas al servicio ML
- `backend_imdb_api_latency_seconds` - Latencia de llamadas a la API IMDB

---

## Referencia de Tareas

Todas las tareas están disponibles desde la raíz del repositorio con el prefijo `local:`:

```bash
# Infraestructura
task local:start:all          # Iniciar Qdrant + init + monitoreo
task local:stop:all           # Detener todos los servicios
task local:status             # Verificar estado de todos los servicios

# Qdrant
task local:qdrant:start       # Iniciar contenedor de Qdrant
task local:qdrant:stop        # Detener Qdrant
task local:qdrant:init        # Inicializar con datos de películas
task local:qdrant:status      # Verificar estado de la colección
task local:qdrant:destroy     # Eliminar contenedor y datos

# Servicio ML (Puerto 8000)
task local:api:start          # Iniciar servicio ML
task local:api:stop           # Detener servicio ML
task local:api:test           # Probar con consulta de ejemplo

# Backend (Puerto 8080)
task local:backend:start      # Iniciar backend
task local:backend:stop       # Detener backend
task local:backend:test       # Probar API del backend

# Frontend (Puerto 5173)
task local:frontend:start     # Iniciar servidor de desarrollo
task local:frontend:stop      # Detener frontend
task local:frontend:build     # Compilar para producción

# Monitoreo
task local:monitoring:start   # Iniciar Prometheus + Grafana
task local:monitoring:stop    # Detener monitoreo
task local:monitoring:logs    # Ver logs

# Desarrollo
task local:dev                # Iniciar API con datos mock (sin Qdrant)
task local:deps:check         # Verificar dependencias
task local:deps:install       # Instalar todas las dependencias
task local:load-test:api      # Ejecutar prueba de carga
```

---

## Solución de Problemas

### Problemas Comunes

#### 1. "DAGSHUB_USER_TOKEN not set"

```
Error: DAGSHUB_USER_TOKEN environment variable is required
```

**Solución:** Edita `app/serving/real_time/mlapi.env` con tu token de DagsHub.

#### 2. "Model not found in MLflow"

```
mlflow.exceptions.MlflowException: Could not find a registered model with name
```

**Solución:**
1. Verifica que el modelo existe: Revisa https://dagshub.com/abdala9512/dsrp-machine-learning-engineering-4.mlflow
2. Ejecuta el notebook de entrenamiento: `notebooks/modeling.ipynb`
3. Asegúrate de que el modelo tenga el alias `@champion`

#### 3. "Qdrant connection refused"

```
qdrant_client.http.exceptions.ResponseHandlingException: Connection refused
```

**Solución:**
```bash
task local:qdrant:start
task local:qdrant:status
```

#### 4. "Collection not found" o "Resultados vacíos"

**Solución:**
```bash
task local:qdrant:init FORCE_REINDEX=true
```

#### 5. "Movies database not found"

```
FileNotFoundError: Movies database not found
```

**Solución:**
1. Ejecuta `notebooks/data_collection.ipynb` para generar los datos
2. O copia el parquet existente a `app/serving/real_time/complete_imdb_database.parquet`

#### 6. El frontend no puede conectarse al backend

**Solución:** Asegúrate de que el backend esté corriendo en el puerto 8080:
```bash
task local:backend:start
curl http://localhost:8080/health
```

### Modo de Desarrollo (Sin Qdrant)

Para desarrollo rápido sin Qdrant:

```bash
task local:dev
# o
task local:api:start MOCK_QDRANT=true
```

Esto usa un retriever mock que retorna películas aleatorias (útil para desarrollo de UI).

### Logs

```bash
# Ver logs de Qdrant
task local:qdrant:logs

# Ver logs de monitoreo
task local:monitoring:logs

# Verificar estado de servicios
task local:status
```

### Reiniciar Todo

```bash
# Detener todos los servicios
task local:stop:all

# Destruir datos de Qdrant
task local:qdrant:destroy

# Limpiar archivos generados
task local:clean

# Inicio limpio
task local:start:all
```

---

## Flujo de Trabajo de Desarrollo

### Sesión de Desarrollo Típica

```bash
# 1. Iniciar infraestructura (una vez por sesión)
task local:start:all

# 2. Iniciar servicios en terminales separadas
task local:api:start       # Terminal 2
task local:backend:start   # Terminal 3
task local:frontend:start  # Terminal 4

# 3. Hacer cambios en el código
# Los servicios se recargan automáticamente al detectar cambios

# 4. Probar
task local:api:test        # Probar servicio ML
task local:backend:test    # Probar backend

# 5. Revisar métricas
open http://localhost:3000  # Grafana
```

### Ejecutar Pruebas

```bash
cd app/serving/real_time
task local:test            # Ejecutar pytest

# Pruebas de carga
task local:load-test:api REQUESTS=100 CONCURRENCY=10
```

---

## Recursos Adicionales

- **Dashboard MLflow**: https://dagshub.com/abdala9512/dsrp-machine-learning-engineering-4.mlflow
- **Repositorio**: https://github.com/abdala9512/dsrp-machine-learning-engineering-4
- **Documentación Qdrant**: https://qdrant.tech/documentation/
- **LightGBM Ranker**: https://lightgbm.readthedocs.io/en/latest/pythonapi/lightgbm.LGBMRanker.html
