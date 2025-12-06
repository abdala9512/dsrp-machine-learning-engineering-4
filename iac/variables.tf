variable "resource_group_name" {
  description = "Nombre del grupo de recursos de Azure"
  type        = string
}

variable "location" {
  description = "Región de Azure donde se desplegarán los recursos"
  type        = string
  default     = "West Europe"
}

variable "cluster_name" {
  description = "Nombre del clúster de Kubernetes"
  type        = string
}

variable "dns_prefix" {
  description = "Prefijo DNS para el clúster de Kubernetes"
  type        = string
}

variable "node_count" {
  description = "Número de nodos en el pool por defecto"
  type        = number
  default     = 2
}

variable "vm_size" {
  description = "Tamaño de las máquinas virtuales de los nodos"
  type        = string
  default     = "Standard_B2s"
}

variable "kubernetes_version" {
  description = "Versión de Kubernetes a utilizar"
  type        = string
  default     = "1.28"
}

variable "network_plugin" {
  description = "Plugin de red para AKS (azure o kubenet)"
  type        = string
  default     = "azure"
}

variable "network_policy" {
  description = "Política de red para AKS (azure o calico)"
  type        = string
  default     = "azure"
}

variable "vnet_address_space" {
  description = "Espacio de direcciones de la VNet"
  type        = list(string)
  default     = ["10.0.0.0/16"]
}

variable "aks_subnet_address_prefix" {
  description = "Prefijo de direcciones para la subnet de AKS"
  type        = string
  default     = "10.0.1.0/24"
}

variable "enable_auto_scaling" {
  description = "Habilitar auto-escalado para el pool de nodos"
  type        = bool
  default     = true
}

variable "min_count" {
  description = "Número mínimo de nodos cuando el auto-escalado está habilitado"
  type        = number
  default     = 2
}

variable "max_count" {
  description = "Número máximo de nodos cuando el auto-escalado está habilitado"
  type        = number
  default     = 10
}

variable "enable_rbac" {
  description = "Habilitar RBAC (Role-Based Access Control)"
  type        = bool
  default     = true
}

variable "enable_azure_policy" {
  description = "Habilitar Azure Policy para Kubernetes"
  type        = bool
  default     = true
}

variable "enable_azure_monitor" {
  description = "Habilitar Azure Monitor para contenedores"
  type        = bool
  default     = true
}

variable "tags" {
  description = "Etiquetas para aplicar a los recursos"
  type        = map(string)
  default     = {}
}

variable "ssh_public_key" {
  description = "Clave pública SSH para acceso a los nodos"
  type        = string
  sensitive   = true
}

variable "log_analytics_workspace_name" {
  description = "Nombre del workspace de Log Analytics"
  type        = string
  default     = null
}

variable "enable_private_cluster" {
  description = "Habilitar clúster privado de AKS"
  type        = bool
  default     = false
}

variable "private_dns_zone_id" {
  description = "ID de la zona DNS privada para clúster privado"
  type        = string
  default     = null
}

variable "authorized_ip_ranges" {
  description = "Rangos de IP autorizados para acceso a la API server"
  type        = list(string)
  default     = []
}

variable "admin_access_cidrs" {
  description = "CIDRs permitidos para acceder a las apps desplegadas en AKS (tráfico entrante a los nodos/pods)"
  type        = list(string)
  default     = []
}

