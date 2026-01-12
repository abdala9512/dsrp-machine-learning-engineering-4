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

- **Dashboard web**: `http://<FQDN>:6333/dashboard`
- **REST API**: `http://<FQDN>:6333`
- **gRPC**: `<FQDN>:6334`

Para acceso local via port-forward:
```bash
kubectl port-forward svc/qdrant 6333:6333 6334:6334
# Dashboard: http://localhost:6333/dashboard
```

### Conexión desde Python

```python
from qdrant_client import QdrantClient

# Usando el DNS label
client = QdrantClient(
    host="qdrant-dsrp.<region>.cloudapp.azure.com",
    port=6333,
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
- `airflow-webserver-*` (UI web)
- `airflow-scheduler-*` (scheduler)
- `airflow-triggerer-*` (triggerer)
- `airflow-postgresql-*` (base de datos)

5) Obtener la IP publica del servicio:
```bash
kubectl get svc -n airflow airflow-webserver
```

6) (Opcional) Asignar un DNS label:
```bash
cd iac
task dns:set-label SERVICE=airflow-webserver NS=airflow LABEL=airflow-dsrp
```

### Acceso a la UI de Airflow

Una vez desplegado, accede a la UI web:
- **URL**: `http://<IP_PUBLICA>` o `http://airflow-dsrp.<region>.cloudapp.azure.com`
- **Usuario**: `admin`
- **Password**: `admin123`

Para acceso local via port-forward:
```bash
kubectl port-forward svc/airflow-webserver 8080:80 -n airflow
# Acceder en: http://localhost:8080
```

### Subir DAGs al cluster

Airflow 3 facilita la gestion de DAGs. Hay varias opciones:

**Opcion 1: Copiar DAGs manualmente**
```bash
# Copiar un archivo DAG al pod del scheduler
kubectl cp mi_dag.py airflow/airflow-scheduler-0:/opt/airflow/dags/
```

**Opcion 2: Usar Git-Sync (recomendado)**

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
