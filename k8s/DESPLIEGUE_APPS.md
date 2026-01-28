# Despliegue de apps en AKS (GitHub Container Registry)

Guía rápida para aplicar manifiestos y desplegar imágenes publicadas en GHCR.

## Comandos básicos de Kubernetes
- `kubectl apply -f <archivo>`: aplica/actualiza recursos.
- `kubectl get pods -n <ns>` y `kubectl get svc -n <ns>`: inventario de pods/servicios.
- `kubectl logs <pod> -n <ns>` y `kubectl describe pod <pod> -n <ns>`: depurar.
- `kubectl port-forward svc/<svc> 8080:80 -n <ns>`: exponer un servicio localmente.

## Despliegue del frontend
1) Asegúrate de tener la imagen en GHCR (workflow `frontend-docker.yml` genera `ghcr.io/<OWNER>/dsrp-frontend:latest`).
2) Edita `k8s/frontend.yaml` y reemplaza `ghcr.io/<OWNER>/dsrp-frontend:latest` con tu ruta real (usuario/org de GHCR). Si la imagen es privada, crea un pull secret y actívalo en `imagePullSecrets`.
3) Aplica el manifiesto:
```bash
kubectl apply -f k8s/frontend.yaml
```
4) Verifica estado e IP pública (Service tipo LoadBalancer):
```bash
kubectl get pods
kubectl get svc frontend
```
5) (Opcional) Asigna un hostname con DNS label en el public IP:
```bash
cd iac
task dns:set-label SERVICE=frontend LABEL=dsrp-frontend
```
Esto genera un FQDN tipo `<DNS_LABEL>.<region>.cloudapp.azure.com`.

6) Abre la IP/hostname del servicio `frontend` en el navegador.

> Nota: ajusta `replicas`, recursos y namespace en `k8s/frontend.yaml` según tu entorno.

---

## Despliegue de Qdrant (Vector Database)

Qdrant es una base de datos vectorial para búsqueda semántica y recomendaciones. El despliegue incluye almacenamiento persistente.

### Puertos expuestos
- **6333**: REST API y Dashboard web
- **6334**: gRPC API (para clientes de alto rendimiento)

### Instalación

1) Aplica el manifiesto:
```bash
kubectl apply -f k8s/qdrant.yaml
```

2) Verifica que el pod y el PVC estén correctos:
```bash
kubectl get pods -l app=qdrant
kubectl get pvc qdrant-storage
```

3) Obtener la IP pública del servicio:
```bash
kubectl get svc qdrant
```

4) Asigna un DNS label para evitar usar la IP directamente:
```bash
cd iac
task dns:set-label SERVICE=qdrant LABEL=qdrant-dsrp
```
Esto genera un FQDN tipo `qdrant-dsrp.<region>.cloudapp.azure.com`.

### Acceso

- **Dashboard web**: `http://<FQDN>/dashboard`
- **REST API**: `http://<FQDN>` (port 80 → 6333 internally)
- **gRPC**: `<FQDN>:6334`

Para acceso local via port-forward:
```bash
kubectl port-forward svc/qdrant 8080:80 6334:6334
# Dashboard: http://localhost:8080/dashboard
```

### Conexión desde Python

```python
from qdrant_client import QdrantClient

# Usando el DNS label (must specify :80 - qdrant_client defaults to 6333)
client = QdrantClient(
    url="http://qdrant-dsrp.<region>.cloudapp.azure.com:80",
    # grpc_port=6334,  # Para conexión gRPC
    # prefer_grpc=True,
)

# Verificar conexión
print(client.get_collections())
```

### Configuración de recursos

El manifiesto actual solicita:
- CPU: 200m (request) / 1000m (limit)
- Memoria: 512Mi (request) / 2Gi (limit)
- Almacenamiento: 10Gi (PVC)

Para ajustar, edita `k8s/qdrant.yaml` según tus necesidades.

### Troubleshooting

- **Pod en Pending**: Verificar que el PVC se haya aprovisionado
  ```bash
  kubectl describe pvc qdrant-storage
  ```

- **Pod reiniciando**: Verificar logs y eventos
  ```bash
  kubectl logs -l app=qdrant
  kubectl describe pod -l app=qdrant
  ```

- **Conexión rechazada**: Verificar que el LoadBalancer tenga IP asignada
  ```bash
  kubectl get svc qdrant -o wide
  ```

> Nota: Los datos persisten en un Azure Disk. Si eliminas el PVC, los datos se perderán.

---

## Despliegue de Apache Airflow 3 (ML Pipelines)

Apache Airflow es una plataforma de orquestacion de workflows. La version 3 incluye mejoras significativas en la UI y soporte nativo para Kubernetes.

### Componentes incluidos
- **Webserver**: UI para monitorear y ejecutar DAGs
- **Scheduler**: Programacion y ejecucion de tareas
- **Triggerer**: Soporte para operadores diferibles
- **PostgreSQL**: Base de datos para metadatos
- **KubernetesExecutor**: Ejecuta cada task como un pod

### Prerrequisitos
- Cluster AKS configurado y accesible via `kubectl`
- Helm 3.x instalado
- Al menos 2GB de RAM disponible en el cluster

### Instalacion paso a paso

1) Agregar el repositorio de Helm de Airflow:
```bash
helm repo add apache-airflow https://airflow.apache.org
helm repo update
```

2) Crear el namespace de Airflow:
```bash
kubectl apply -f k8s/airflow-namespace.yaml
```

3) Instalar Airflow con Helm:
```bash
helm install airflow apache-airflow/airflow \
    --namespace airflow \
    --values k8s/airflow-values.yaml \
    --timeout 10m
```

4) Verificar que todos los pods esten corriendo:
```bash
kubectl get pods -n airflow -w
```
Esperar hasta que todos los pods esten en estado `Running`:
- `airflow-api-server-*` (UI web)
- `airflow-scheduler-*` (scheduler)
- `airflow-triggerer-*` (triggerer)
- `airflow-postgresql-*` (base de datos)

5) Obtener la IP publica del servicio:
```bash
kubectl get svc -n airflow airflow-api-server
```

6) (Opcional) Asignar un DNS label:
```bash
cd iac
task dns:set-label SERVICE=airflow-api-server NS=airflow LABEL=airflow-dsrp
```

### Acceso a la UI de Airflow

Una vez desplegado, accede a la UI web:
- **URL**: `http://<IP_PUBLICA>` o `http://airflow-dsrp.<region>.cloudapp.azure.com`
- **Usuario**: `admin`
- **Password**: `admin123`

Para acceso local via port-forward:
```bash
kubectl port-forward svc/airflow-api-server 8080:80 -n airflow
# Acceder en: http://localhost:8080
```

### Subir DAGs al cluster

Airflow 3 facilita la gestion de DAGs. Hay varias opciones:

**Opcion 1: Usar Taskfile (recomendado para desarrollo)**
```bash
cd k8s

# Subir todos los DAGs del folder dags/
task airflow:dags:upload

# Subir un archivo especifico
task airflow:dags:upload:file FILE=../dags/mi_dag.py

# Listar DAGs actuales en el cluster
task airflow:dags:list

# Eliminar un DAG
task airflow:dags:delete FILE=mi_dag.py

# Ver logs del scheduler
task airflow:logs

# Ver estado de Airflow
task airflow:status
```

**Opcion 2: GitHub Actions (CI/CD)**

Los DAGs se despliegan automaticamente al hacer push a `dags/` en la rama `main`.
Requiere configurar estos secrets en GitHub:
- `AZURE_CREDENTIALS`
- `AKS_RESOURCE_GROUP`
- `AKS_CLUSTER_NAME`

**Opcion 3: Usar Git-Sync (sincronizacion automatica)**

Edita `k8s/airflow-values.yaml` y habilita git-sync:
```yaml
dags:
  gitSync:
    enabled: true
    repo: https://github.com/tu-usuario/tu-repo.git
    branch: main
    subPath: dags
    wait: 60
```

Luego actualiza el deployment:
```bash
helm upgrade airflow apache-airflow/airflow -n airflow -f k8s/airflow-values.yaml
```

### Ejemplo de DAG

```python
from datetime import datetime
from airflow import DAG
from airflow.operators.python import PythonOperator

def extract():
    print("Extrayendo datos...")
    return {"data": [1, 2, 3]}

def transform(ti):
    data = ti.xcom_pull(task_ids="extract")
    print(f"Transformando: {data}")
    return {"transformed": [x * 2 for x in data["data"]]}

def load(ti):
    data = ti.xcom_pull(task_ids="transform")
    print(f"Cargando: {data}")

with DAG(
    dag_id="ml_pipeline_example",
    start_date=datetime(2025, 1, 1),
    schedule="@daily",
    catchup=False,
) as dag:

    t1 = PythonOperator(task_id="extract", python_callable=extract)
    t2 = PythonOperator(task_id="transform", python_callable=transform)
    t3 = PythonOperator(task_id="load", python_callable=load)

    t1 >> t2 >> t3
```

### Configuracion del cliente (airflow)

Para desarrollar DAGs localmente:

1) Instalar airflow:
```bash
pip install apache-airflow
# o con uv:
uv add apache-airflow
```

2) Inicializar entorno local:
```bash
export AIRFLOW_HOME=~/airflow
airflow db init
airflow users create --username admin --password admin --firstname Admin --lastname User --role Admin --email admin@example.com
```

3) Ejecutar localmente:
```bash
airflow standalone
# Abre http://localhost:8080
```

### Desinstalacion

Para eliminar Airflow del cluster:
```bash
helm uninstall airflow -n airflow
kubectl delete namespace airflow
```

### Troubleshooting

- **Pods en CrashLoopBackOff**: Verificar recursos disponibles
  ```bash
  kubectl describe pod -l component=webserver -n airflow
  kubectl logs -l component=webserver -n airflow
  ```

- **Webserver no accesible**: Verificar que el LoadBalancer tenga IP
  ```bash
  kubectl get svc -n airflow
  ```

- **PostgreSQL no inicia**: Verificar PVC y recursos
  ```bash
  kubectl describe pvc -n airflow
  kubectl logs -l app.kubernetes.io/name=postgresql -n airflow
  ```

- **DAGs no aparecen**: Verificar permisos y ubicacion
  ```bash
  kubectl exec -it airflow-scheduler-0 -n airflow -- ls -la /opt/airflow/dags/
  ```

> Nota: Este es un despliegue educativo. Para produccion, considera usar PostgreSQL externo (Azure Database for PostgreSQL), configurar autenticacion robusta, y habilitar HTTPS via Ingress.

---

## Despliegue del Backend API

El Backend API es una capa de orquestacion que conecta el Frontend con el ML Service y la API de IMDB.

### Arquitectura

```
Frontend → Backend → ML Service → Qdrant
              ↓
          IMDB API
```

### Flujo de datos

1. Frontend envia query de busqueda al Backend
2. Backend llama al ML Service para obtener IDs de peliculas recomendadas
3. Backend llama a IMDB API para obtener detalles de cada pelicula
4. Backend retorna resultados enriquecidos al Frontend

### Modos de operacion

- **ML Mode** (default): Usa el ML Service para recomendaciones inteligentes
- **Direct Mode**: Busca en IMDB directamente (fallback)

### Instalacion

1) Aplica el manifiesto:
```bash
kubectl apply -f k8s/backend.yaml
```

2) Verifica el estado:
```bash
kubectl get pods -l app=backend
kubectl logs -l app=backend -f
```

3) Obtener la IP publica:
```bash
kubectl get svc backend
```

4) Asignar DNS label:
```bash
cd iac
task dns:set-label SERVICE=backend LABEL=dsrp-backend
```

### Endpoints

| Endpoint | Metodo | Descripcion |
|----------|--------|-------------|
| `/search` | POST | Busqueda de peliculas |
| `/search` | GET | Busqueda (query params) |
| `/movie/{id}` | GET | Detalles de una pelicula |
| `/health` | GET | Health check |
| `/metrics` | GET | Metricas Prometheus |
| `/docs` | GET | Documentacion OpenAPI |

### Ejemplo de uso

```bash
# Busqueda con ML
curl -X POST http://dsrp-backend.<region>.cloudapp.azure.com/search \
  -H "Content-Type: application/json" \
  -d '{"query": "action movies like the dark knight", "limit": 10, "use_ml": true}'

# Busqueda directa IMDB
curl -X POST http://dsrp-backend.<region>.cloudapp.azure.com/search \
  -H "Content-Type: application/json" \
  -d '{"query": "batman", "limit": 10, "use_ml": false}'
```

### Configuracion

Variables de entorno en el ConfigMap:

| Variable | Default | Descripcion |
|----------|---------|-------------|
| `ML_SERVICE_URL` | `http://model-serving:80` | URL del ML Service |
| `IMDB_API_URL` | `https://api.imdbapi.dev` | URL de IMDB API |
| `ENABLE_ML_SERVICE` | `true` | Habilitar ML Service |
| `ML_SERVICE_TIMEOUT` | `30.0` | Timeout ML Service (segundos) |
| `IMDB_API_TIMEOUT` | `10.0` | Timeout IMDB API (segundos) |

### Recursos

- CPU: 100m (request) / 500m (limit)
- Memoria: 128Mi (request) / 512Mi (limit)

---

## Despliegue del Model Serving API

API de recomendacion de peliculas usando LightGBM LTR, Qdrant y Sentence Transformers.

### Componentes
- **LitServe**: Framework de alto rendimiento para servir modelos ML
- **Sentence Transformers**: Generacion de embeddings para queries
- **Qdrant**: Busqueda hibrida (densa + BM25)
- **LightGBM LTR**: Re-ranking de resultados
- **Prometheus metrics**: Endpoint `/metrics` para monitoreo

### Prerrequisitos
- Qdrant desplegado y con la coleccion `imdb-movies-hybrid` indexada
- Token de DagsHub para acceder al modelo LTR en MLflow
- Imagen publicada en GHCR (workflow `model-serving-docker.yml`)

### Instalacion

1) Actualiza el secret con tu token de DagsHub:
```bash
# Opcion 1: Editar el secret directamente
kubectl edit secret model-serving-secrets

# Opcion 2: Crear el secret con el token
kubectl create secret generic model-serving-secrets \
  --from-literal=DAGSHUB_USER_TOKEN="tu-token-aqui" \
  --dry-run=client -o yaml | kubectl apply -f -
```

2) Aplica el manifiesto:
```bash
kubectl apply -f k8s/model-serving.yaml
```

3) Verifica el estado:
```bash
kubectl get pods -l app=model-serving
kubectl logs -l app=model-serving -f
```

4) Obtener la IP publica:
```bash
kubectl get svc model-serving
```

5) Asignar DNS label:
```bash
cd iac
task dns:set-label SERVICE=model-serving LABEL=dsrp-model-serving
```

### Endpoints

| Endpoint | Metodo | Descripcion |
|----------|--------|-------------|
| `/predict` | POST | Busqueda de peliculas |
| `/health` | GET | Health check |
| `/metrics` | GET | Metricas Prometheus |
| `/docs` | GET | Documentacion OpenAPI |

### Ejemplo de uso

```python
import requests

url = "http://dsrp-model-serving.<region>.cloudapp.azure.com/predict"

response = requests.post(url, json={
    "query": "action movies similar to the dark knight",
    "top_k": 10
})

results = response.json()
print(f"Found {results['count']} movies:")
for movie in results['results']:
    print(f"  - {movie['title']} (score: {movie['ltr_score']:.2f})")
```

### Configuracion

Variables de entorno configurables en el ConfigMap:

| Variable | Default | Descripcion |
|----------|---------|-------------|
| `QDRANT_URL` | `http://qdrant:80` | URL del servicio Qdrant |
| `QDRANT_COLLECTION` | `imdb-movies-hybrid` | Nombre de la coleccion |
| `LTR_MODEL_NAME` | `ltr-dsrpflix-prd-ENE12` | Nombre del modelo en MLflow |
| `LTR_MODEL_ALIAS` | `champion` | Alias del modelo |
| `TOP_K_RETRIEVAL` | `100` | Candidatos a recuperar |
| `TOP_K_FINAL` | `10` | Resultados finales |
| `WORKERS` | `2` | Workers de LitServe |

### Recursos

El manifiesto actual solicita:
- CPU: 500m (request) / 2000m (limit)
- Memoria: 2Gi (request) / 4Gi (limit)

> Nota: El modelo de embeddings se descarga al iniciar (~90MB). El primer request puede tardar mientras se carga el modelo LTR desde MLflow.

---

## Despliegue de Prometheus (Monitoreo)

Prometheus recolecta metricas del Model Serving API y otros servicios del cluster.

### Instalacion

1) Aplica el manifiesto:
```bash
kubectl apply -f k8s/prometheus.yaml
```

2) Verifica el estado:
```bash
kubectl get pods -l app=prometheus
```

3) Obtener la IP publica:
```bash
kubectl get svc prometheus
```

4) Asignar DNS label:
```bash
cd iac
task dns:set-label SERVICE=prometheus LABEL=dsrp-prometheus
```

### Acceso

- **UI Web**: `http://dsrp-prometheus.<region>.cloudapp.azure.com`
- **API**: `http://dsrp-prometheus.<region>.cloudapp.azure.com/api/v1/...`

Para acceso local:
```bash
kubectl port-forward svc/prometheus 9090:80
# Acceder en: http://localhost:9090
```

### Targets configurados

| Job | Target | Descripcion |
|-----|--------|-------------|
| `prometheus` | `localhost:9090` | Metricas de Prometheus |
| `model-serving` | `model-serving:80` | API de recomendaciones |
| `qdrant` | `qdrant:6333` | Base de datos vectorial |

### Queries utiles

```promql
# Request rate (requests/sec)
sum(rate(movie_api_requests_total[1m]))

# P95 latency
histogram_quantile(0.95, sum(rate(movie_api_request_latency_seconds_bucket[5m])) by (le))

# Error rate
sum(rate(movie_api_requests_total{status="error"}[5m])) / sum(rate(movie_api_requests_total[5m]))

# Model loaded status
movie_api_model_loaded

# Qdrant available status
movie_api_qdrant_available
```

### Recursos

- CPU: 100m (request) / 500m (limit)
- Memoria: 256Mi (request) / 1Gi (limit)
- Retencion: 15 dias

---

## Despliegue de Grafana (Visualizacion)

Grafana proporciona dashboards para visualizar las metricas de Prometheus.

### Instalacion

1) Aplica el manifiesto:
```bash
kubectl apply -f k8s/grafana.yaml
```

2) Verifica el estado:
```bash
kubectl get pods -l app=grafana
```

3) Obtener la IP publica:
```bash
kubectl get svc grafana
```

4) Asignar DNS label:
```bash
cd iac
task dns:set-label SERVICE=grafana LABEL=dsrp-grafana
```

### Acceso

- **URL**: `http://dsrp-grafana.<region>.cloudapp.azure.com`
- **Usuario**: `admin`
- **Password**: `admin123`

Para acceso local:
```bash
kubectl port-forward svc/grafana 3000:80
# Acceder en: http://localhost:3000
```

### Dashboards incluidos

**Movie Recommendation API** - Dashboard pre-configurado con:
- Request rate y latencia (P50, P90, P95, P99)
- Estado de componentes (Qdrant, LTR Model)
- Error rate
- Pipeline stage latency (Embedding, Retrieval, Rerank)
- Requests by status (success/error)

### Agregar dashboards personalizados

1) Accede a Grafana
2) Click en "+" > "Import"
3) Pega el JSON del dashboard o usa un ID de Grafana.com
4) Selecciona "Prometheus" como datasource

### Recursos

- CPU: 100m (request) / 500m (limit)
- Memoria: 128Mi (request) / 512Mi (limit)

---

## Despliegue rapido del stack completo

Para desplegar todo el stack de monitoreo de una vez:

```bash
# Desde el directorio iac/
cd iac

# Desplegar Prometheus y Grafana
task monitoring:deploy

# Desplegar Model Serving API (requiere DAGSHUB_TOKEN)
task model-serving:deploy DAGSHUB_TOKEN="tu-token-aqui"

# Configurar DNS para todos los servicios
task dns:setup-all PREFIX=dsrp

# Ver todas las URLs
task dns:show-urls
```

### Orden de despliegue recomendado

1. **Qdrant** - Base de datos vectorial
2. **Model Serving** - API de recomendaciones
3. **Prometheus** - Recoleccion de metricas
4. **Grafana** - Visualizacion

```bash
# 1. Qdrant
kubectl apply -f k8s/qdrant.yaml

# 2. Model Serving (despues de configurar el secret)
kubectl apply -f k8s/model-serving.yaml

# 3. Prometheus
kubectl apply -f k8s/prometheus.yaml

# 4. Grafana
kubectl apply -f k8s/grafana.yaml

# 5. Frontend (opcional)
kubectl apply -f k8s/frontend.yaml

# 6. Configurar DNS para todos
cd iac && task dns:setup-all PREFIX=dsrp
```

### Verificar el stack completo

```bash
# Ver todos los pods
kubectl get pods

# Ver todos los servicios
kubectl get svc

# Ver URLs con DNS
cd iac && task dns:show-urls
```

### URLs finales (ejemplo)

| Servicio | URL |
|----------|-----|
| Frontend | `http://dsrp-frontend.eastus.cloudapp.azure.com` |
| Model Serving | `http://dsrp-model-serving.eastus.cloudapp.azure.com` |
| Prometheus | `http://dsrp-prometheus.eastus.cloudapp.azure.com` |
| Grafana | `http://dsrp-grafana.eastus.cloudapp.azure.com` |
| Qdrant | `http://dsrp-qdrant.eastus.cloudapp.azure.com` |

---

## Troubleshooting general

### Pods en estado Pending
```bash
kubectl describe pod <pod-name>
# Verificar eventos y recursos disponibles
```

### LoadBalancer sin IP
```bash
kubectl get svc <service-name> -o wide
# Esperar unos minutos, Azure puede tardar en asignar IP
```

### Verificar logs
```bash
kubectl logs -l app=<app-name> -f
kubectl logs <pod-name> --previous  # logs del container anterior si crasheo
```

### Reiniciar deployment
```bash
kubectl rollout restart deployment/<deployment-name>
kubectl rollout status deployment/<deployment-name>
```

### Eliminar y recrear
```bash
kubectl delete -f k8s/<manifest>.yaml
kubectl apply -f k8s/<manifest>.yaml
```
