terraform {
  required_version = ">= 1.12.3, < 2.0.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.80.0"
    }
    azuread = {
      source  = "hashicorp/azuread"
      version = "~> 3.9.0"
    }
  }
}

provider "azurerm" {
  subscription_id = var.az_subscription_id
  features {}
}

provider "azuread" {}

data "azuread_client_config" "current" {}

locals {
  # Stable federated-credential names. "main-branch" is preserved verbatim so the
  # existing credential is imported rather than recreated; its subject tracks the
  # configurable default branch instead of a hardcoded name.
  federated_subjects = merge(
    { "main-branch" = "repo:${var.github_repository}:ref:refs/heads/${var.github_default_branch}" },
    { for env in var.github_environments : "${env}-environment" => "repo:${var.github_repository}:environment:${env}" },
  )
}

# Remote-state storage. Imported from the account created before init, never
# recreated. Attributes mirror the greenfield az CLI block in README.md.
resource "azurerm_resource_group" "state" {
  name     = var.state_resource_group_name
  location = var.az_location
}

resource "azurerm_storage_account" "state" {
  name                            = var.state_storage_account_name
  resource_group_name             = azurerm_resource_group.state.name
  location                        = azurerm_resource_group.state.location
  account_tier                    = "Standard"
  account_replication_type        = "GRS"
  account_kind                    = "StorageV2"
  https_traffic_only_enabled      = true
  min_tls_version                 = "TLS1_2"
  allow_nested_items_to_be_public = false
  shared_access_key_enabled       = false

  blob_properties {
    versioning_enabled = true

    delete_retention_policy {
      days = 14
    }

    container_delete_retention_policy {
      days = 14
    }
  }
}

resource "azurerm_storage_container" "state" {
  name                  = var.state_container_name
  storage_account_id    = azurerm_storage_account.state.id
  container_access_type = "private"
}

# GitHub Actions identity. Application and service principal are tenant objects
# imported by their existing ids.
resource "azuread_application" "github_actions" {
  display_name = var.app_display_name
}

resource "azuread_service_principal" "github_actions" {
  client_id = azuread_application.github_actions.client_id
}

resource "azuread_application_federated_identity_credential" "github" {
  for_each = local.federated_subjects

  application_id = azuread_application.github_actions.id
  display_name   = each.key
  description    = "GitHub Actions OIDC (${each.key})"
  issuer         = "https://token.actions.githubusercontent.com"
  audiences      = ["api://AzureADTokenExchange"]
  subject        = each.value
}

# Management-plane deployment rights at the narrow live scope.
resource "azurerm_role_assignment" "deploy_contributor" {
  scope                = var.deployment_scope
  role_definition_name = "Contributor"
  principal_id         = azuread_service_principal.github_actions.object_id
}

# Data-plane access to the state container so tofu init with use_azuread_auth
# can read and write state blobs. Contributor is management-plane only.
resource "azurerm_role_assignment" "state_blob_contributor" {
  scope                = azurerm_storage_container.state.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azuread_service_principal.github_actions.object_id
}

output "github_actions_secrets" {
  description = "Repository secrets consumed by the CD workflows. Populate with: gh secret set <NAME> --body \"$(tofu output -raw ...)\"."
  sensitive   = true
  value = {
    AZURE_CLIENT_ID       = azuread_application.github_actions.client_id
    AZURE_TENANT_ID       = data.azuread_client_config.current.tenant_id
    AZURE_SUBSCRIPTION_ID = var.az_subscription_id
  }
}

output "github_actions_variables" {
  description = "Repository variables consumed by the CD workflows for backend configuration."
  value = {
    TF_STATE_RESOURCE_GROUP  = azurerm_resource_group.state.name
    TF_STATE_STORAGE_ACCOUNT = azurerm_storage_account.state.name
    TF_STATE_CONTAINER       = azurerm_storage_container.state.name
  }
}
