# PostgreSQL Flexible Server configuration for Nohiki application

# OpenTofu state contains this generated credential and must use the secured
# remote backend documented in README.md.
resource "random_password" "postgres_admin_password" {
  length  = 32
  special = true
}

resource "azurerm_postgresql_flexible_server" "nohiki_postgres" {
  name                   = "pg-${var.app_name}-${var.app_environment}"
  resource_group_name    = azurerm_resource_group.app_rg.name
  location               = azurerm_resource_group.app_rg.location
  version                = var.postgres_version
  administrator_login    = var.postgres_admin_login
  administrator_password = random_password.postgres_admin_password.result

  sku_name     = var.postgres_flexible_sku_name
  storage_mb   = var.postgres_flexible_storage_mb
  storage_tier = var.postgres_flexible_storage_tier

  backup_retention_days        = var.postgres_backup_retention_days
  geo_redundant_backup_enabled = var.postgres_geo_redundant_backup_enabled

  dynamic "high_availability" {
    for_each = var.app_environment == "prod" ? [1] : []
    content {
      mode = "ZoneRedundant"
    }
  }

  maintenance_window {
    day_of_week  = var.postgres_maintenance_day
    start_hour   = var.postgres_maintenance_hour
    start_minute = 0
  }

  public_network_access_enabled = var.app_environment != "prod"

  tags = {
    environment = var.app_environment
    application = var.app_name
    purpose     = "primary-database"
  }

  # Ignore changes to zone and other attributes that Azure manages
  # Zone cannot be modified after creation without recreating the resource
  lifecycle {
    ignore_changes = [
      zone,
      # Ignore other Azure-managed attributes that cause drift
      create_mode,
      point_in_time_restore_time_in_utc
    ]

    precondition {
      condition     = var.app_environment != "prod" || var.postgres_backup_retention_days >= 14
      error_message = "Production PostgreSQL requires at least 14 days of backup retention."
    }

    precondition {
      condition     = var.app_environment != "prod" || var.postgres_geo_redundant_backup_enabled
      error_message = "Production PostgreSQL requires geo-redundant backups."
    }
  }

  depends_on = [azurerm_resource_group.app_rg]
}


resource "azurerm_postgresql_flexible_server_firewall_rule" "azure_services_nonprod" {
  count            = var.app_environment == "prod" ? 0 : 1
  name             = "allow-azure-services"
  server_id        = azurerm_postgresql_flexible_server.nohiki_postgres.id
  start_ip_address = "0.0.0.0"
  end_ip_address   = "0.0.0.0"
}

resource "azurerm_postgresql_flexible_server_database" "app_db" {
  name      = var.postgres_database_name
  server_id = azurerm_postgresql_flexible_server.nohiki_postgres.id
  charset   = "UTF8"
  collation = "en_US.utf8"

  depends_on = [azurerm_postgresql_flexible_server.nohiki_postgres]
}

# =============================================================================
# PostgreSQL 18 Optimized Server Parameters
# =============================================================================

resource "azurerm_postgresql_flexible_server_configuration" "log_connections" {
  name      = "log_connections"
  server_id = azurerm_postgresql_flexible_server.nohiki_postgres.id
  value     = "on"
}

resource "azurerm_postgresql_flexible_server_configuration" "connection_throttling" {
  name      = "connection_throttling"
  server_id = azurerm_postgresql_flexible_server.nohiki_postgres.id
  value     = "on"
}

resource "azurerm_postgresql_flexible_server_configuration" "log_checkpoints" {
  name      = "log_checkpoints"
  server_id = azurerm_postgresql_flexible_server.nohiki_postgres.id
  value     = "on"
}

resource "azurerm_postgresql_flexible_server_configuration" "ssl_min_protocol_version" {
  name      = "ssl_min_protocol_version"
  server_id = azurerm_postgresql_flexible_server.nohiki_postgres.id
  value     = "TLSv1.2"
}

resource "azurerm_postgresql_flexible_server_configuration" "effective_io_concurrency" {
  name      = "effective_io_concurrency"
  server_id = azurerm_postgresql_flexible_server.nohiki_postgres.id
  value     = "200"
}

resource "azurerm_postgresql_flexible_server_configuration" "max_parallel_workers_per_gather" {
  name      = "max_parallel_workers_per_gather"
  server_id = azurerm_postgresql_flexible_server.nohiki_postgres.id
  value     = "4"
}

resource "azurerm_postgresql_flexible_server_configuration" "max_parallel_workers" {
  name      = "max_parallel_workers"
  server_id = azurerm_postgresql_flexible_server.nohiki_postgres.id
  value     = "8"
}

resource "azurerm_postgresql_flexible_server_configuration" "max_parallel_maintenance_workers" {
  name      = "max_parallel_maintenance_workers"
  server_id = azurerm_postgresql_flexible_server.nohiki_postgres.id
  value     = "4"
}

resource "azurerm_postgresql_flexible_server_configuration" "shared_buffers" {
  name      = "shared_buffers"
  server_id = azurerm_postgresql_flexible_server.nohiki_postgres.id
  # 256MB in 8KB pages = 32768
  value = "32768"
}

resource "azurerm_postgresql_flexible_server_configuration" "work_mem" {
  name      = "work_mem"
  server_id = azurerm_postgresql_flexible_server.nohiki_postgres.id
  # 16MB in KB = 16384
  value = "16384"
}

resource "azurerm_key_vault_secret" "postgres_admin_password" {
  name         = "database-password"
  key_vault_id = data.azurerm_key_vault.app_kv.id
  value        = random_password.postgres_admin_password.result
  content_type = "text/plain"

  tags = {
    environment = var.app_environment
    application = var.app_name
    sensitive   = "true"
  }
}

resource "azurerm_key_vault_secret" "pg_connection_string" {
  name         = "database-dsn"
  key_vault_id = data.azurerm_key_vault.app_kv.id
  value        = "postgresql://${azurerm_postgresql_flexible_server.nohiki_postgres.administrator_login}:${random_password.postgres_admin_password.result}@${azurerm_postgresql_flexible_server.nohiki_postgres.fqdn}:5432/${azurerm_postgresql_flexible_server_database.app_db.name}?sslmode=require"
  content_type = "application/x-postgresql-connection-string"

  tags = {
    environment = var.app_environment
    application = var.app_name
    sensitive   = "true"
  }

  depends_on = [
    azurerm_postgresql_flexible_server.nohiki_postgres,
    azurerm_postgresql_flexible_server_database.app_db
  ]
}

resource "azurerm_key_vault_secret" "pg_host_secret" {
  name         = "database-host"
  key_vault_id = data.azurerm_key_vault.app_kv.id
  value        = azurerm_postgresql_flexible_server.nohiki_postgres.fqdn
  content_type = "text/plain"

  tags = {
    environment = var.app_environment
    application = var.app_name
    sensitive   = "false"
  }

  depends_on = [azurerm_postgresql_flexible_server.nohiki_postgres]
}

resource "azurerm_key_vault_secret" "pg_port_secret" {
  name         = "database-port"
  key_vault_id = data.azurerm_key_vault.app_kv.id
  value        = "5432"
  content_type = "text/plain"

  tags = {
    environment = var.app_environment
    application = var.app_name
    sensitive   = "false"
  }
}

resource "azurerm_key_vault_secret" "pg_db_name_secret" {
  name         = "database-name"
  key_vault_id = data.azurerm_key_vault.app_kv.id
  value        = azurerm_postgresql_flexible_server_database.app_db.name
  content_type = "text/plain"

  tags = {
    environment = var.app_environment
    application = var.app_name
    sensitive   = "false"
  }

  depends_on = [azurerm_postgresql_flexible_server_database.app_db]
}

resource "azurerm_key_vault_secret" "pg_user_secret" {
  name         = "database-user"
  key_vault_id = data.azurerm_key_vault.app_kv.id
  value        = azurerm_postgresql_flexible_server.nohiki_postgres.administrator_login
  content_type = "text/plain"

  tags = {
    environment = var.app_environment
    application = var.app_name
    sensitive   = "false"
  }

  depends_on = [azurerm_postgresql_flexible_server.nohiki_postgres]
}

output "postgres_fqdn" {
  value       = azurerm_postgresql_flexible_server.nohiki_postgres.fqdn
  description = "PostgreSQL server FQDN"
}

output "postgres_database_name" {
  value       = azurerm_postgresql_flexible_server_database.app_db.name
  description = "PostgreSQL database name"
}