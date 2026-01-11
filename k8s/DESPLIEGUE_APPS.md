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

## Despliegue de Flyte (ML Pipelines)

Flyte es una plataforma para orquestar workflows de Machine Learning. Usamos el chart `flyte-binary` con PostgreSQL y MinIO desplegados manualmente.

### Prerrequisitos
- Cluster AKS configurado y accesible via `kubectl`
- Helm 3.x instalado
- Al menos 4GB de RAM disponible en el cluster

### Instalación paso a paso

1) Agregar el repositorio de Helm de Flyte:
```bash
helm repo add flyteorg https://flyteorg.github.io/flyte
helm repo update
```

2) Crear el namespace de Flyte:
```bash
kubectl apply -f k8s/flyte-namespace.yaml
```

3) Desplegar las dependencias (PostgreSQL + MinIO):
```bash
kubectl apply -f k8s/flyte-deps.yaml
```

4) Esperar a que las dependencias estén listas:
```bash
kubectl get pods -n flyte -w
# Esperar hasta que flyte-postgresql y flyte-minio estén Running
# El job flyte-minio-init debe estar Completed
```

5) Instalar Flyte Binary con Helm:
```bash
helm install flyte flyteorg/flyte-binary \
    --namespace flyte \
    --values k8s/flyte-binary-values.yaml \
    --timeout 10m
```

6) Verificar que todos los pods estén corriendo:
```bash
kubectl get pods -n flyte
```
Esperar hasta que todos los pods estén en estado `Running`:
- `flyte-flyte-binary-*` (servidor principal)
- `flyte-postgresql-*` (base de datos)
- `flyte-minio-*` (almacenamiento)

7) Obtener la IP pública del servicio:
```bash
kubectl get svc -n flyte flyte-flyte-binary
```

8) (Opcional) Asignar un DNS label:
```bash
cd iac
task dns:set-label SERVICE=flyte-flyte-binary NS=flyte LABEL=flyte-dsrp
```

### Acceso a la consola de Flyte

Una vez desplegado, accede a la consola web de Flyte:
- **URL**: `http://<IP_PUBLICA>:8088/console` o `http://<DNS_LABEL>.<region>.cloudapp.azure.com:8088/console`

Para acceso local via port-forward:
```bash
kubectl port-forward svc/flyte-flyte-binary 8088:8088 -n flyte
# Acceder en: http://localhost:8088/console
```

### Configuración del cliente (flytekit)

Para ejecutar workflows desde notebooks/scripts:

1) Instalar flytekit:
```bash
pip install flytekit
# o con uv:
uv add flytekit
```

2) Configurar el endpoint de Flyte:
```python
from flytekit.remote import FlyteRemote
from flytekit.configuration import Config

remote = FlyteRemote(
    config=Config.for_endpoint(
        endpoint="<IP_PUBLICA>:8089",  # Puerto gRPC
        insecure=True
    ),
    default_project="flytesnacks",
    default_domain="development",
)
```

### Desinstalación

Para eliminar Flyte del cluster:
```bash
helm uninstall flyte -n flyte
kubectl delete -f k8s/flyte-deps.yaml
kubectl delete namespace flyte
```

### Troubleshooting

- **Pods en CrashLoopBackOff**: Verificar recursos disponibles en los nodos
  ```bash
  kubectl describe pod <pod-name> -n flyte
  kubectl logs <pod-name> -n flyte
  ```

- **Conexión rechazada**: Verificar que el servicio esté expuesto
  ```bash
  kubectl get svc -n flyte
  ```

- **MinIO no inicia**: Puede requerir más memoria. Editar `flyte-sandbox-values.yaml` y aumentar límites

> Nota: Este es un despliegue educativo. Para producción, usar el chart `flyte-core` con PostgreSQL y almacenamiento externo (Azure Blob Storage).
