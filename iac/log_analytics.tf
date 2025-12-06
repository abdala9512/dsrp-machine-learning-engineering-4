# Log Analytics Workspace para Azure Monitor
resource "azurerm_log_analytics_workspace" "main" {
  count               = var.enable_azure_monitor ? 1 : 0
  name                = var.log_analytics_workspace_name != null ? var.log_analytics_workspace_name : "${var.cluster_name}-loganalytics"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags                = var.tags

  depends_on = [azurerm_resource_group.main]
}

