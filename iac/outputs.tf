output "cluster_name" {
  description = "Nombre del clúster de Kubernetes"
  value       = azurerm_kubernetes_cluster.main.name
}

output "cluster_fqdn" {
  description = "FQDN del servidor de API de Kubernetes"
  value       = azurerm_kubernetes_cluster.main.fqdn
}

output "cluster_portal_fqdn" {
  description = "FQDN del portal de Kubernetes"
  value       = azurerm_kubernetes_cluster.main.portal_fqdn
}

output "kube_config" {
  description = "Configuración de kubectl para acceder al clúster"
  value       = azurerm_kubernetes_cluster.main.kube_config_raw
  sensitive   = true
}

output "kube_config_path" {
  description = "Ruta donde se guardará la configuración de kubectl"
  value       = "~/.kube/config-${var.cluster_name}"
}

output "resource_group_name" {
  description = "Nombre del grupo de recursos"
  value       = azurerm_resource_group.main.name
}

output "vnet_id" {
  description = "ID de la Virtual Network"
  value       = azurerm_virtual_network.main.id
}

output "vnet_name" {
  description = "Nombre de la Virtual Network"
  value       = azurerm_virtual_network.main.name
}

output "aks_subnet_id" {
  description = "ID de la subnet de AKS"
  value       = azurerm_subnet.aks.id
}

output "cluster_identity_client_id" {
  description = "Client ID de la identidad administrada del clúster"
  value       = azurerm_user_assigned_identity.aks.client_id
}

output "cluster_identity_principal_id" {
  description = "Principal ID de la identidad administrada del clúster"
  value       = azurerm_user_assigned_identity.aks.principal_id
}

output "log_analytics_workspace_id" {
  description = "ID del workspace de Log Analytics (si está habilitado)"
  value       = var.enable_azure_monitor ? azurerm_log_analytics_workspace.main[0].id : null
}

output "node_resource_group" {
  description = "Nombre del grupo de recursos de los nodos"
  value       = azurerm_kubernetes_cluster.main.node_resource_group
}


