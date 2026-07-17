# Azure Cache for Redis
resource "azurerm_redis_cache" "main" {
  count                         = var.redis_provider == "azure" ? 1 : 0
  name                          = "rc-${var.app_name}-${var.app_environment}"
  location                      = azurerm_resource_group.app_rg.location
  resource_group_name           = azurerm_resource_group.app_rg.name
  capacity                      = var.azure_redis_capacity
  family                        = var.azure_redis_family
  sku_name                      = var.azure_redis_sku_name
  minimum_tls_version           = "1.2"
  public_network_access_enabled = var.app_environment != "prod"

  tags = {
    Environment = var.app_environment
    Application = var.app_name
  }

  lifecycle {
    precondition {
      condition     = var.app_environment != "prod" || var.azure_redis_sku_name != "Basic"
      error_message = "Production Azure Cache for Redis requires Standard or Premium SKU."
    }
  }
}

# Redis URL secret for Azure Cache
resource "azurerm_key_vault_secret" "redis_url_azure" {
  count        = var.redis_provider == "azure" ? 1 : 0
  name         = "redis-dsn"
  value        = "rediss://:${azurerm_redis_cache.main[0].primary_access_key}@${azurerm_redis_cache.main[0].hostname}:${azurerm_redis_cache.main[0].ssl_port}/0"
  key_vault_id = data.azurerm_key_vault.app_kv.id
  content_type = "application/x-redis-connection-string"

  depends_on = [azurerm_redis_cache.main]
}

resource "azurerm_key_vault_secret" "redis_password_azure" {
  count        = var.redis_provider == "azure" ? 1 : 0
  name         = "redis-password"
  value        = azurerm_redis_cache.main[0].primary_access_key
  key_vault_id = data.azurerm_key_vault.app_kv.id
  content_type = "text/plain"

  depends_on = [azurerm_redis_cache.main]
}
