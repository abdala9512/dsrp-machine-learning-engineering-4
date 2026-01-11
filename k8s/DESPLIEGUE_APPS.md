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
task dns:set-label SERVICE_NAME=frontend SERVICE_NS=default DNS_LABEL=dsrp-frontend
```
Esto genera un FQDN tipo `<DNS_LABEL>.<region>.cloudapp.azure.com`.

6) Abre la IP/hostname del servicio `frontend` en el navegador.

> Nota: ajusta `replicas`, recursos y namespace en `k8s/frontend.yaml` según tu entorno.

---

## Despliegue de Flyte (ML Pipelines)

Flyte es una plataforma para orquestar workflows de Machine Learning. Aquí usamos el chart `flyte-sandbox` para un despliegue educativo.

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

3) Instalar Flyte Sandbox con los valores personalizados:
```bash
helm install flyte-sandbox flyteorg/flyte-sandbox \
    --namespace flyte \
    --values k8s/flyte-sandbox-values.yaml \
    --timeout 10m
```

4) Verificar que todos los pods estén corriendo:
```bash
kubectl get pods -n flyte
```
Esperar hasta que todos los pods estén en estado `Running`:
- `flyte-sandbox-*` (servidor principal)
- `flyte-sandbox-postgresql-*` (base de datos)
- `flyte-sandbox-minio-*` (almacenamiento)

5) Obtener la IP pública del servicio:
```bash
kubectl get svc -n flyte flyte-sandbox-flyte-binary
```

6) (Opcional) Asignar un DNS label:
```bash
cd iac
task dns:set-label SERVICE_NAME=flyte-sandbox-flyte-binary SERVICE_NS=flyte DNS_LABEL=flyte-dsrp
```

### Acceso a la consola de Flyte

Una vez desplegado, accede a la consola web de Flyte:
- **URL**: `http://<IP_PUBLICA>:8088` o `http://<DNS_LABEL>.<region>.cloudapp.azure.com:8088`

Para acceso local via port-forward:
```bash
kubectl port-forward svc/flyte-sandbox-flyte-binary 8088:8088 -n flyte
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
        insecure=True  # Para sandbox sin SSL
    ),
    default_project="flytesnacks",
    default_domain="development",
)
```

### Desinstalación

Para eliminar Flyte del cluster:
```bash
helm uninstall flyte-sandbox -n flyte
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
