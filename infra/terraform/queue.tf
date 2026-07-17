# Public data-plane access supports browser uploads with short-lived SAS tokens.
# Anonymous blob access remains disabled; production server traffic also uses
# the private endpoint and Private DNS.
resource "azurerm_storage_account" "nohiki_storage" {
  name                              = "st${var.app_name}${var.app_environment}${random_string.unique_suffix.result}"
  resource_group_name               = azurerm_resource_group.app_rg.name
  location                          = azurerm_resource_group.app_rg.location
  account_tier                      = var.storage_account_tier
  account_replication_type          = var.storage_account_replication_type
  account_kind                      = var.storage_account_kind
  min_tls_version                   = var.storage_min_tls_version
  https_traffic_only_enabled        = true
  infrastructure_encryption_enabled = true
  allow_nested_items_to_be_public   = false
  public_network_access_enabled     = true
  shared_access_key_enabled         = false

  blob_properties {
    delete_retention_policy {
      days = var.storage_delete_retention_days
    }
    container_delete_retention_policy {
      days = var.storage_delete_retention_days
    }

    cors_rule {
      allowed_headers    = ["Content-Type", "x-ms-blob-type"]
      allowed_methods    = ["GET", "HEAD", "PUT"]
      allowed_origins    = ["https://nohiki.com"]
      exposed_headers    = ["Content-Length", "Content-Type", "ETag", "Last-Modified"]
      max_age_in_seconds = 3600
    }
  }


  tags = {
    environment = var.app_environment
    application = var.app_name
    purpose     = "blob-storage"
  }

  lifecycle {
    precondition {
      condition = var.app_environment != "prod" || contains([
        "GRS", "GZRS", "RAGRS", "RAGZRS"
      ], var.storage_account_replication_type)
      error_message = "Production blob storage requires geo-redundant replication."
    }
  }
}

resource "azapi_resource" "nohiki_blob_container" {
  type      = "Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01"
  name      = "nohiki-prod"
  parent_id = "${azurerm_storage_account.nohiki_storage.id}/blobServices/default"
  body = {
    properties = {
      publicAccess = "None"
    }
  }
}

# The shared storage service account uses the existing production workload
# identity emitted by the identity overlay; no S3 account keys are required.
resource "azurerm_role_assignment" "storage_blob_data_contributor" {
  count                = var.deployment_type == "aks" && var.app_environment == "prod" ? 1 : 0
  scope                = azurerm_storage_account.nohiki_storage.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.external_secrets[0].principal_id
}

resource "azurerm_key_vault_secret" "s3_access_key" {
  name         = "s3-access-key"
  key_vault_id = data.azurerm_key_vault.app_kv.id
  value        = azurerm_storage_account.nohiki_storage.name
  content_type = "text/plain"
}

resource "azurerm_key_vault_secret" "s3_secret_key" {
  name         = "s3-secret-key"
  key_vault_id = data.azurerm_key_vault.app_kv.id
  value        = azurerm_storage_account.nohiki_storage.primary_access_key
  content_type = "text/plain"
}

resource "azurerm_key_vault_secret" "s3_region" {
  name         = "s3-region"
  key_vault_id = data.azurerm_key_vault.app_kv.id
  value        = azurerm_resource_group.app_rg.location
  content_type = "text/plain"
}

output "storage_account_name" {
  value       = azurerm_storage_account.nohiki_storage.name
  description = "Blob storage account name"
}