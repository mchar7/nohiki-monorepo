locals {
  production_private_network = var.app_environment == "prod" ? 1 : 0
}

data "azurerm_eventhub_namespace" "app" {
  count               = local.production_private_network
  name                = var.event_hubs_namespace_name
  resource_group_name = var.event_hubs_resource_group_name
}

resource "azurerm_private_dns_zone" "postgres" {
  count               = local.production_private_network
  name                = "privatelink.postgres.database.azure.com"
  resource_group_name = azurerm_resource_group.app_rg.name
}

resource "azurerm_private_dns_zone" "redis" {
  count               = local.production_private_network
  name                = "privatelink.redis.cache.windows.net"
  resource_group_name = azurerm_resource_group.app_rg.name
}

resource "azurerm_private_dns_zone" "blob" {
  count               = local.production_private_network
  name                = "privatelink.blob.core.windows.net"
  resource_group_name = azurerm_resource_group.app_rg.name
}

resource "azurerm_private_dns_zone" "servicebus" {
  count               = local.production_private_network
  name                = "privatelink.servicebus.windows.net"
  resource_group_name = azurerm_resource_group.app_rg.name
}

resource "azurerm_private_dns_zone_virtual_network_link" "postgres" {
  count                 = local.production_private_network
  name                  = "postgres"
  resource_group_name   = azurerm_resource_group.app_rg.name
  private_dns_zone_name = azurerm_private_dns_zone.postgres[0].name
  virtual_network_id    = azurerm_virtual_network.app[0].id
}

resource "azurerm_private_dns_zone_virtual_network_link" "redis" {
  count                 = local.production_private_network
  name                  = "redis"
  resource_group_name   = azurerm_resource_group.app_rg.name
  private_dns_zone_name = azurerm_private_dns_zone.redis[0].name
  virtual_network_id    = azurerm_virtual_network.app[0].id
}

resource "azurerm_private_dns_zone_virtual_network_link" "blob" {
  count                 = local.production_private_network
  name                  = "blob"
  resource_group_name   = azurerm_resource_group.app_rg.name
  private_dns_zone_name = azurerm_private_dns_zone.blob[0].name
  virtual_network_id    = azurerm_virtual_network.app[0].id
}

resource "azurerm_private_dns_zone_virtual_network_link" "servicebus" {
  count                 = local.production_private_network
  name                  = "servicebus"
  resource_group_name   = azurerm_resource_group.app_rg.name
  private_dns_zone_name = azurerm_private_dns_zone.servicebus[0].name
  virtual_network_id    = azurerm_virtual_network.app[0].id
}

resource "azurerm_private_endpoint" "postgres" {
  count               = local.production_private_network
  name                = "pe-postgres-${var.app_name}-${var.app_environment}"
  location            = azurerm_resource_group.app_rg.location
  resource_group_name = azurerm_resource_group.app_rg.name
  subnet_id           = azurerm_subnet.private_endpoints[0].id

  private_service_connection {
    name                           = "postgres"
    private_connection_resource_id = azurerm_postgresql_flexible_server.nohiki_postgres.id
    subresource_names              = ["postgresqlServer"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "postgres"
    private_dns_zone_ids = [azurerm_private_dns_zone.postgres[0].id]
  }
}

resource "azurerm_private_endpoint" "redis" {
  count               = local.production_private_network
  name                = "pe-redis-${var.app_name}-${var.app_environment}"
  location            = azurerm_resource_group.app_rg.location
  resource_group_name = azurerm_resource_group.app_rg.name
  subnet_id           = azurerm_subnet.private_endpoints[0].id

  private_service_connection {
    name                           = "redis"
    private_connection_resource_id = azurerm_redis_cache.main[0].id
    subresource_names              = ["redisCache"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "redis"
    private_dns_zone_ids = [azurerm_private_dns_zone.redis[0].id]
  }
}

resource "azurerm_private_endpoint" "blob" {
  count               = local.production_private_network
  name                = "pe-blob-${var.app_name}-${var.app_environment}"
  location            = azurerm_resource_group.app_rg.location
  resource_group_name = azurerm_resource_group.app_rg.name
  subnet_id           = azurerm_subnet.private_endpoints[0].id

  private_service_connection {
    name                           = "blob"
    private_connection_resource_id = azurerm_storage_account.nohiki_storage.id
    subresource_names              = ["blob"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "blob"
    private_dns_zone_ids = [azurerm_private_dns_zone.blob[0].id]
  }
}

resource "azurerm_private_endpoint" "event_hubs" {
  count               = local.production_private_network
  name                = "pe-eventhubs-${var.app_name}-${var.app_environment}"
  location            = azurerm_resource_group.app_rg.location
  resource_group_name = azurerm_resource_group.app_rg.name
  subnet_id           = azurerm_subnet.private_endpoints[0].id

  private_service_connection {
    name                           = "eventhubs"
    private_connection_resource_id = data.azurerm_eventhub_namespace.app[0].id
    subresource_names              = ["namespace"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "servicebus"
    private_dns_zone_ids = [azurerm_private_dns_zone.servicebus[0].id]
  }
}

output "production_network" {
  description = "Canonical production endpoints and exact private endpoint egress CIDRs."
  value = var.app_environment == "prod" ? {
    database = {
      host  = azurerm_postgresql_flexible_server.nohiki_postgres.fqdn
      port  = 5432
      cidrs = ["${azurerm_private_endpoint.postgres[0].private_service_connection[0].private_ip_address}/32"]
    }
    redis = {
      host  = azurerm_redis_cache.main[0].hostname
      port  = azurerm_redis_cache.main[0].ssl_port
      cidrs = ["${azurerm_private_endpoint.redis[0].private_service_connection[0].private_ip_address}/32"]
    }
    s3 = {
      endpoint = azurerm_storage_account.nohiki_storage.primary_blob_endpoint
      port     = 443
      cidrs    = ["${azurerm_private_endpoint.blob[0].private_service_connection[0].private_ip_address}/32"]
    }
    kafka = {
      bootstrapServers = "${data.azurerm_eventhub_namespace.app[0].name}.servicebus.windows.net:9093"
      dsn              = "${data.azurerm_eventhub_namespace.app[0].name}.servicebus.windows.net"
      port             = 9093
      cidrs            = ["${azurerm_private_endpoint.event_hubs[0].private_service_connection[0].private_ip_address}/32"]
    }
  } : null
  sensitive = false
}
