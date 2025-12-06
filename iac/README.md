# Despliegue de AKS con Terraform

Guía paso a paso (español) para crear un clúster de AKS desde cero, aplicar la infraestructura con Terraform y ejecutar comandos básicos de Kubernetes.

## Requisitos previos
- Suscripción de Azure con permisos para crear RG, VNet y AKS.
- CLI instaladas: Azure CLI, Terraform (>=1.0) y kubectl.
- Clave pública SSH (genera una con `ssh-keygen` si no tienes).

## Preparación del proyecto
1) Clona este repositorio y entra al directorio.
2) Configura el backend remoto para el estado (recomendado):
   - **Con Task (preferido)**: `task backend:setup`
     - Crea RG + Storage Account + container y genera `backend.hcl` listo para usar.
   - **Manual** (solo si no usas Task): crea Storage Account y container, luego escribe `backend.hcl`:
     ```
     resource_group_name  = "<rg-estado>"
     storage_account_name = "<storage>"
     container_name       = "tfstate"
     key                  = "aks-cluster.terraform.tfstate"
     ```
3) Edita `dsrp-values.tfvars` y ajusta:
   - `resource_group_name`, `location`, `cluster_name`, `dns_prefix`.
   - `ssh_public_key`: pega tu clave pública.
   - `admin_access_cidrs`: tu IP/CIDR pública para acceder a apps (ej. `"203.0.113.5/32"`).
   - `authorized_ip_ranges`: restringe el API server si lo necesitas (usa CIDR, p. ej. `"1.2.3.4/32"`).

## Despliegue con Terraform
```bash
# 1) Autenticarse en Azure
az login

# 2) Inicializar (usa backend.hcl si lo creaste)
terraform init -backend-config=backend.hcl

# 3) Revisar el plan
terraform plan -var-file=dsrp-values.tfvars

# 4) Aplicar (creará RG, VNet, AKS, NSG, Log Analytics opcional)
terraform apply -var-file=dsrp-values.tfvars
```

Terraform imprimirá `kube_config` y sugerirá `kube_config_path` para kubectl.

## Conectar y validar el clúster
Opciones para configurar kubectl:
```bash
# A) Usar kubeconfig del output (si se guarda en archivo):
#    copia el contenido de output.kube_config a ~/.kube/config-<cluster>
#    y exporta: export KUBECONFIG=~/.kube/config-<cluster>

# B) Descargar credenciales con Azure CLI:
az aks get-credentials --resource-group <rg> --name <cluster> --admin --overwrite-existing

# Validar
kubectl get nodes
kubectl get pods -A
```

## Comandos clave de Terraform
- `terraform fmt`: formatea los .tf.
- `terraform validate`: valida la configuración.
- `terraform plan -var-file=dsrp-values.tfvars`: previsualiza cambios.
- `terraform apply -var-file=dsrp-values.tfvars`: aplica cambios.
- `terraform destroy -var-file=dsrp-values.tfvars`: elimina los recursos (cuidado).

## Comandos clave de Kubernetes
- `kubectl get ns` / `kubectl get pods -A`: inventario rápido.
- `kubectl describe pod <pod> -n <ns>`: detalles y eventos.
- `kubectl logs <pod> -n <ns>` y `kubectl logs -f <pod> -c <container>`: logs.
- `kubectl apply -f archivo.yaml`: despliega manifiestos.
- `kubectl delete -f archivo.yaml`: elimina recursos desplegados.
- `kubectl port-forward svc/<service> 8080:80 -n <ns>`: acceder a un servicio localmente.

## Limpieza del entorno
Si es un entorno temporal: `terraform destroy -var-file=dsrp-values.tfvars`. Esto borrará RG, AKS y recursos asociados.

## Notas y buenas prácticas
- Mantén `admin_access_cidrs` con el mínimo de IPs necesarias; abre todos los puertos hacia tus apps/nodos.
- Si activas clúster privado, prepara DNS/peering antes de aplicar.
- Usa workspaces o ramas para aislar cambios en entornos múltiples.

## Desplegar el frontend y backend en AKS
Pasos resumidos para llevar las imágenes a un registro y aplicar los manifiestos incluidos en `app/k8s/manifest.yaml` (Namespace, Secret placeholder, Deployments + Services).

### 1) Construir y publicar imágenes
Elige tu registro (ej. ACR). Ejemplo con Azure Container Registry:
```bash
ACR_NAME="<tu_acr>"
az acr login --name $ACR_NAME

# Backend
docker build -t $ACR_NAME.azurecr.io/dsrpflix-backend:latest app/backend
docker push $ACR_NAME.azurecr.io/dsrpflix-backend:latest

# Frontend (si quieres que use el backend interno, compila con VITE_IMDB_API_BASE_URL=http://backend.dsrpflix.svc.cluster.local:8000)
docker build \
  --build-arg VITE_IMDB_API_BASE_URL=http://backend.dsrpflix.svc.cluster.local:8000 \
  -t $ACR_NAME.azurecr.io/dsrpflix-frontend:latest app/frontend
docker push $ACR_NAME.azurecr.io/dsrpflix-frontend:latest
```

### 2) Actualizar manifest con tus imágenes y API key
Edita `app/k8s/manifest.yaml` y reemplaza:
- `REPLACE_WITH_REGISTRY/backend:latest` -> imagen real (ej. `$ACR_NAME.azurecr.io/dsrpflix-backend:latest`)
- `REPLACE_WITH_REGISTRY/frontend:latest` -> imagen real
- `REPLACE_WITH_IMDB_API_KEY` -> tu API key (o crea/actualiza el Secret manualmente).

### 3) Aplicar manifiestos
```bash
kubectl apply -f app/k8s/manifest.yaml
kubectl get pods -n dsrpflix
kubectl get svc -n dsrpflix
```
El Service `frontend` es tipo LoadBalancer; obtén la IP/hostname público desde `kubectl get svc -n dsrpflix frontend`.

### 4) Validar
- Backend health: `kubectl -n dsrpflix run tmp --rm -it --image=curlimages/curl --command -- sh -c "curl -v backend:8000/health"`
- Frontend: abre la IP del LoadBalancer en el navegador. Si compilaste el frontend apuntando al backend interno, las búsquedas usarán el servicio en AKS; de lo contrario, usará la API pública por defecto.
