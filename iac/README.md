# Despliegue de AKS con Terraform

Guía paso a paso para crear un clúster de AKS desde cero, aplicar la infraestructura con Terraform y ejecutar comandos básicos de Kubernetes.

## Requisitos previos
- Suscripción de Azure con permisos para crear RG, VNet y AKS.
- CLI instaladas: Azure CLI, Terraform (>=1.0) y kubectl.
- Clave pública SSH (genera una con `ssh-keygen` si no tienes).

## Ejemplo de `dsrp-values.tfvars`
Guarda tus variables en `iac/dsrp-values.tfvars` (excluido de git) y ajusta los valores según tu entorno:
```hcl
# Grupo de recursos
resource_group_name = "rg-aks-demo"
location            = "East US"

# Configuración del clúster
cluster_name        = "aks-cluster-demo"
dns_prefix          = "dsrp-mlops-demo"
node_count          = 2
vm_size             = "Standard_E2s_v3"
kubernetes_version  = "1.32"

# Configuración de red
network_plugin            = "azure"
network_policy            = "azure"
vnet_address_space        = ["10.0.0.0/16"]
aks_subnet_address_prefix = "10.0.1.0/24"

# Auto-escalado
enable_auto_scaling = true
min_count           = 2
max_count           = 5

# Seguridad
enable_rbac            = true
enable_azure_policy    = true
enable_azure_monitor   = true
enable_private_cluster = false
authorized_ip_ranges = [
  "203.0.113.5/32", # API server (ajusta tus IPs)
]

# Acceso administrativo a apps/nodos
admin_access_cidrs = [
  "203.0.113.5/32", # IP pública para acceder a apps/nodos
]

# SSH Public Key
ssh_public_key = "ssh-rsa AAAA... tu_llave_publica"

# Log Analytics (opcional)
log_analytics_workspace_name = null

# Etiquetas
tags = {
  Environment = "Dev"
  Project     = "Kubernetes"
  ManagedBy   = "Terraform"
  Course      = "MLE4"
}
```
Cómo usarlo:
1) Copia el bloque anterior en `iac/dsrp-values.tfvars`.
2) Ajusta nombres (`resource_group_name`, `cluster_name`, `dns_prefix`), ubicación, tamaño/cantidad de nodos y CIDRs reales.
3) Reemplaza `ssh_public_key` con tu clave pública (ej. `cat ~/.ssh/id_ed25519.pub`).
4) Si usas Log Analytics, define `log_analytics_workspace_name`; adapta etiquetas a tu entorno.

## Instalación de CLIs (macOS y Windows)
### macOS (Homebrew)
- Azure CLI: `brew update && brew install azure-cli`
- Terraform: `brew tap hashicorp/tap && brew install hashicorp/tap/terraform`
- kubectl: `brew install kubectl`
- Task (Taskfile): `brew install go-task/tap/go-task`

### Windows (winget)
- Azure CLI: `winget install -e --id Microsoft.AzureCLI`
- Terraform: `winget install -e --id HashiCorp.Terraform`
- kubectl: `winget install -e --id Kubernetes.kubectl`
- Task (Taskfile): `winget install -e --id GoTask.GoTask`

Verifica con `az version`, `terraform version` y `kubectl version --client`.

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

# C) Usar la salida de Terraform:
#  - Si es YAML directo:
terraform output -raw kube_config > ~/.kube/config-aks
chmod 600 ~/.kube/config-aks
export KUBECONFIG=~/.kube/config-aks

#  - Si es base64 (kube_config_raw):
terraform output -raw kube_config_raw | base64 --decode > ~/.kube/config-aks
chmod 600 ~/.kube/config-aks
export KUBECONFIG=~/.kube/config-aks

#  - Si tienes kube_config_path:
export KUBECONFIG=$(terraform output -raw kube_config_path)

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
