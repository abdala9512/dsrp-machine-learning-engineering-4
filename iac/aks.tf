# Identidad administrada para el clúster AKS
resource "azurerm_user_assigned_identity" "aks" {
  name                = "${var.cluster_name}-aks-identity"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  tags                = var.tags

  depends_on = [azurerm_resource_group.main]
}

# Asignar permisos a la identidad para que AKS pueda gestionar recursos
resource "azurerm_role_assignment" "aks_network_contributor" {
  scope                = azurerm_subnet.aks.id
  role_definition_name = "Network Contributor"
  principal_id         = azurerm_user_assigned_identity.aks.principal_id

  depends_on = [azurerm_user_assigned_identity.aks, azurerm_subnet.aks]
}

resource "azurerm_role_assignment" "aks_msi_operator" {
  scope                = azurerm_user_assigned_identity.aks.id
  role_definition_name = "Managed Identity Operator"
  principal_id         = azurerm_user_assigned_identity.aks.principal_id

  depends_on = [azurerm_user_assigned_identity.aks]
}

# Clúster de Azure Kubernetes Service
resource "azurerm_kubernetes_cluster" "main" {
  name                = var.cluster_name
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  dns_prefix          = var.dns_prefix
  kubernetes_version  = var.kubernetes_version
  node_resource_group = "${var.cluster_name}-nodes-rg"
  tags                = var.tags

  # Configuración de red
  network_profile {
    network_plugin = var.network_plugin
    network_policy = var.network_policy
    service_cidr   = "10.1.0.0/16"
    dns_service_ip = "10.1.0.10"
  }

  # Identidad administrada
  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.aks.id]
  }

  # Pool de nodos por defecto (mínimo para sistema)
  default_node_pool {
    name            = "systempool"
    vm_size         = var.vm_size
    vnet_subnet_id  = azurerm_subnet.aks.id
    os_disk_size_gb = 30
    type            = "VirtualMachineScaleSets"
    node_count      = 1
    max_pods        = 30

    # Etiquetas y etiquetas de nodo
    node_labels = {
      "pool" = "system"
    }

    tags = var.tags
  }

  # Configuración de RBAC
  role_based_access_control_enabled = var.enable_rbac

  # Azure Policy
  azure_policy_enabled = var.enable_azure_policy

  # Azure Monitor para contenedores
  dynamic "oms_agent" {
    for_each = var.enable_azure_monitor ? [1] : []
    content {
      log_analytics_workspace_id = azurerm_log_analytics_workspace.main[0].id
    }
  }

  # Configuración de API server
  private_cluster_enabled = var.enable_private_cluster
  private_dns_zone_id     = var.enable_private_cluster ? var.private_dns_zone_id : null

  # Configuración de seguridad adicional
  auto_scaler_profile {
    balance_similar_node_groups      = true
    max_graceful_termination_sec     = 600
    scale_down_delay_after_add       = "10m"
    scale_down_unneeded              = "10m"
    scale_down_utilization_threshold = "0.5"
    skip_nodes_with_local_storage    = false
    skip_nodes_with_system_pods      = false
  }

  depends_on = [
    azurerm_subnet.aks,
    azurerm_user_assigned_identity.aks,
    azurerm_role_assignment.aks_network_contributor,
    azurerm_role_assignment.aks_msi_operator
  ]
}

# Pool de nodos adicional para cargas de trabajo
resource "azurerm_kubernetes_cluster_node_pool" "workload" {
  name                  = "workloadpool"
  kubernetes_cluster_id = azurerm_kubernetes_cluster.main.id
  vm_size               = var.vm_size
  vnet_subnet_id        = azurerm_subnet.aks.id
  os_disk_size_gb       = 30
  max_pods              = 30
  priority              = "Regular"
  node_count            = var.node_count
  mode                  = "User"

  node_labels = {
    "pool" = "workload"
  }

  tags = var.tags

  depends_on = [azurerm_kubernetes_cluster.main]
}

# Nota: Para habilitar auto-escalado en los pools de nodos, 
# configura manualmente desde Azure Portal o usa el recurso:
# azurerm_kubernetes_cluster_node_pool con los parámetros:
# - node_count = null (cuando enable_auto_scaling = true)
# - min_count y max_count para definir los límites

# Configuración de rangos de IP autorizados (si se especifica)
# Esto se configura mediante el recurso azurerm_kubernetes_cluster_authorized_ip_ranges
# si está disponible, o manualmente después del despliegue
