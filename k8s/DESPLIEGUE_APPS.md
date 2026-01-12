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

## Despliegue de Dagster (ML Pipelines)

Dagster es una plataforma moderna para orquestar pipelines de datos y ML. Incluye UI web, scheduler, y soporte nativo para Kubernetes.

### Componentes incluidos
- **Webserver**: UI para monitorear y ejecutar pipelines
- **Daemon**: Scheduler, sensors y monitoreo de runs
- **PostgreSQL**: Base de datos para metadatos
- **User Deployments**: Pods con tu código de pipelines

### Prerrequisitos
- Cluster AKS configurado y accesible via `kubectl`
- Helm 3.x instalado
- Al menos 2GB de RAM disponible en el cluster

### Instalación paso a paso

1) Agregar el repositorio de Helm de Dagster:
```bash
helm repo add dagster https://dagster-io.github.io/helm
helm repo update
```

2) Crear el namespace de Dagster:
```bash
kubectl apply -f k8s/dagster-namespace.yaml
```

3) Instalar Dagster con Helm:
```bash
helm install dagster dagster/dagster \
    --namespace dagster \
    --values k8s/dagster-values.yaml \
    --timeout 10m
```

4) Verificar que todos los pods estén corriendo:
```bash
kubectl get pods -n dagster -w
```
Esperar hasta que todos los pods estén en estado `Running`:
- `dagster-dagster-webserver-*` (UI web)
- `dagster-dagster-daemon-*` (scheduler)
- `dagster-postgresql-*` (base de datos)
- `dagster-dagster-user-deployments-*` (código de usuario)

5) Obtener la IP pública del servicio:
```bash
kubectl get svc -n dagster dagster-dagster-webserver
```

6) (Opcional) Asignar un DNS label:
```bash
cd iac
task dns:set-label SERVICE=dagster-dagster-webserver NS=dagster LABEL=dagster-dsrp
```

### Acceso a la UI de Dagster

Una vez desplegado, accede a la UI web:
- **URL**: `http://<IP_PUBLICA>` o `http://dagster-dsrp.<region>.cloudapp.azure.com`

Para acceso local via port-forward:
```bash
kubectl port-forward svc/dagster-dagster-webserver 8080:80 -n dagster
# Acceder en: http://localhost:8080
```

### Configuración del cliente (dagster)

Para ejecutar pipelines desde notebooks/scripts:

1) Instalar dagster:
```bash
pip install dagster dagster-webserver
# o con uv:
uv add dagster dagster-webserver
```

2) Ejemplo básico de definición:
```python
from dagster import asset, Definitions

@asset
def my_first_asset():
    """Un asset simple que retorna datos."""
    return [1, 2, 3]

@asset
def my_second_asset(my_first_asset):
    """Asset que depende del primero."""
    return [x * 2 for x in my_first_asset]

defs = Definitions(
    assets=[my_first_asset, my_second_asset],
)
```

3) Ejecutar localmente:
```bash
dagster dev -f my_pipeline.py
# Abre http://localhost:3000
```

### Desinstalación

Para eliminar Dagster del cluster:
```bash
helm uninstall dagster -n dagster
kubectl delete namespace dagster
```

### Troubleshooting

- **Pods en CrashLoopBackOff**: Verificar recursos disponibles
  ```bash
  kubectl describe pod -l app.kubernetes.io/name=dagster -n dagster
  kubectl logs -l app.kubernetes.io/name=dagster -n dagster
  ```

- **Webserver no accesible**: Verificar que el LoadBalancer tenga IP
  ```bash
  kubectl get svc -n dagster
  ```

- **PostgreSQL no inicia**: Verificar PVC y recursos
  ```bash
  kubectl describe pvc -n dagster
  kubectl logs -l app.kubernetes.io/name=postgresql -n dagster
  ```

> Nota: Este es un despliegue educativo. Para producción, considera usar PostgreSQL externo (Azure Database for PostgreSQL) y configurar autenticación.
