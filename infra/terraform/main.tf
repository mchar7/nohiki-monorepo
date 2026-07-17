resource "azurerm_resource_group" "app_rg" {
  name     = "${var.app_name}-${var.app_environment}-rg"
  location = var.az_location

  tags = {
    environment   = var.app_environment
    application   = var.app_name
    deployment_by = "opentofu"
  }
}

data "azurerm_key_vault" "app_kv" {
  name                = var.kv_name
  resource_group_name = var.kv_rg_name
}

data "azurerm_dns_zone" "app_dns_zone" {
  name                = var.dns_zone_name
  resource_group_name = var.dns_zone_resource_group
}

data "azurerm_container_registry" "app_acr" {
  name                = replace(var.container_registry, ".azurecr.io", "")
  resource_group_name = var.acr_resource_group_name
}

# Random string for globally unique names (e.g., storage account)
resource "random_string" "unique_suffix" {
  length  = 6
  special = false
  upper   = false
}