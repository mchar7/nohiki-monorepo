# User Assigned Identity for Cert-Manager to interact with Azure DNS
resource "azurerm_user_assigned_identity" "cert_manager_identity" {
  count               = var.deployment_type == "aks" ? 1 : 0
  name                = "${var.app_name}-${var.app_environment}-certmgr-identity"
  resource_group_name = azurerm_resource_group.app_rg.name
  location            = azurerm_resource_group.app_rg.location
}

resource "azurerm_role_assignment" "cert_manager_dns_contributor" {
  count                = var.deployment_type == "aks" ? 1 : 0
  scope                = data.azurerm_dns_zone.app_dns_zone.id
  role_definition_name = "DNS Zone Contributor"
  principal_id         = azurerm_user_assigned_identity.cert_manager_identity[0].principal_id
}

resource "azurerm_federated_identity_credential" "cert_manager_fic" {
  count               = var.deployment_type == "aks" ? 1 : 0
  name                = "${var.app_name}-${var.app_environment}-certmgr-fic"
  resource_group_name = azurerm_resource_group.app_rg.name
  audience            = ["api://AzureADTokenExchange"]
  issuer              = azurerm_kubernetes_cluster.aks_cluster[0].oidc_issuer_url
  parent_id           = azurerm_user_assigned_identity.cert_manager_identity[0].id
  subject             = "system:serviceaccount:nohiki-foundation:nohiki-foundation-cert-manager"
}


output "cert_manager_workload_identity_client_id" {
  description = "Client ID used by cert-manager for Azure DNS workload identity."
  value       = var.deployment_type == "aks" ? azurerm_user_assigned_identity.cert_manager_identity[0].client_id : null
}

output "cert_manager_workload_identity_tenant_id" {
  description = "Azure tenant ID used by the cert-manager workload identity."
  value       = var.deployment_type == "aks" ? data.azurerm_key_vault.app_kv.tenant_id : null
}

output "cert_manager_dns_subscription_id" {
  description = "Azure subscription containing the cert-manager DNS zone."
  value       = var.deployment_type == "aks" ? var.az_subscription_id : null
  sensitive   = true
}

output "cert_manager_dns_resource_group" {
  description = "Resource group containing the cert-manager DNS zone."
  value       = var.deployment_type == "aks" ? data.azurerm_dns_zone.app_dns_zone.resource_group_name : null
  sensitive   = true
}

output "cert_manager_dns_zone_name" {
  description = "Azure DNS zone reconciled by cert-manager."
  value       = var.deployment_type == "aks" ? data.azurerm_dns_zone.app_dns_zone.name : null
}