# infra/terraform/aks.tf

resource "azurerm_log_analytics_workspace" "aks" {
  count               = var.deployment_type == "aks" ? 1 : 0
  name                = "log-${var.app_name}-${var.app_environment}-aks"
  location            = azurerm_resource_group.app_rg.location
  resource_group_name = azurerm_resource_group.app_rg.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
  daily_quota_gb      = var.log_analytics_daily_quota_gb

  tags = { environment = var.app_environment, application = var.app_name }
}

resource "azurerm_kubernetes_cluster" "aks_cluster" {
  count                               = var.deployment_type == "aks" ? 1 : 0
  name                                = "${var.app_name}-${var.app_environment}-${var.aks_cluster_name_suffix}"
  location                            = azurerm_resource_group.app_rg.location
  resource_group_name                 = azurerm_resource_group.app_rg.name
  dns_prefix                          = "${var.app_name}-${var.app_environment}"
  kubernetes_version                  = "1.33" # Or your preferred version
  oidc_issuer_enabled                 = true
  workload_identity_enabled           = true
  private_cluster_enabled             = var.app_environment == "prod"
  private_cluster_public_fqdn_enabled = false
  role_based_access_control_enabled   = true
  azure_policy_enabled                = true
  sku_tier                            = var.app_environment == "prod" ? "Standard" : "Free"

  default_node_pool {
    name            = "default"
    node_count      = var.aks_node_count
    vm_size         = var.aks_node_vm_size
    os_disk_size_gb = var.aks_node_os_disk_size_gb
    zones           = var.aks_node_zones
    type            = "VirtualMachineScaleSets"
    vnet_subnet_id  = var.app_environment == "prod" ? azurerm_subnet.aks[0].id : null

    upgrade_settings {
      max_surge = "10%"
    }
  }

  identity { type = "SystemAssigned" }

  network_profile {
    network_plugin    = "azure"
    network_policy    = "azure"
    service_cidr      = var.aks_service_cidr
    dns_service_ip    = var.aks_dns_service_ip
    load_balancer_sku = var.aks_load_balancer_sku
    outbound_type     = "loadBalancer"
  }

  key_vault_secrets_provider {
    secret_rotation_enabled  = true
    secret_rotation_interval = "24h"
  }

  oms_agent {
    log_analytics_workspace_id = azurerm_log_analytics_workspace.aks[0].id
  }
  tags       = { environment = var.app_environment, application = var.app_name }
  depends_on = [azurerm_resource_group.app_rg]
}

resource "azurerm_kubernetes_cluster_node_pool" "user" {
  count                 = var.deployment_type == "aks" ? 1 : 0
  name                  = var.aks_user_node_pool_name
  kubernetes_cluster_id = azurerm_kubernetes_cluster.aks_cluster[0].id
  vm_size               = var.aks_user_node_vm_size
  os_disk_size_gb       = var.aks_node_os_disk_size_gb
  zones                 = var.aks_node_zones
  mode                  = "User"

  auto_scaling_enabled = true
  min_count            = var.aks_user_node_min_count
  max_count            = var.aks_user_node_max_count
  node_count           = var.aks_user_node_min_count

  node_public_ip_enabled = false
  vnet_subnet_id         = var.app_environment == "prod" ? azurerm_subnet.aks[0].id : null

  tags = { environment = var.app_environment, application = var.app_name }

  lifecycle {
    ignore_changes = [node_count]
  }
}

resource "azurerm_role_assignment" "aks_acr_pull" {
  count                = var.deployment_type == "aks" ? 1 : 0
  scope                = data.azurerm_container_registry.app_acr.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_kubernetes_cluster.aks_cluster[0].kubelet_identity[0].object_id
}

moved {
  from = azurerm_user_assigned_identity.kv_pod_identity
  to   = azurerm_user_assigned_identity.external_secrets
}

resource "azurerm_user_assigned_identity" "external_secrets" {
  count               = var.deployment_type == "aks" ? 1 : 0
  name                = "${var.app_name}-${var.app_environment}-kv-identity"
  resource_group_name = azurerm_resource_group.app_rg.name
  location            = azurerm_resource_group.app_rg.location
  tags                = { environment = var.app_environment, application = var.app_name }
}

resource "azurerm_role_assignment" "kv_pod_identity_secret_user" {
  count                = var.deployment_type == "aks" ? 1 : 0
  scope                = data.azurerm_key_vault.app_kv.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.external_secrets[0].principal_id
}

# External Secrets workload identity federation. The ClusterSecretStore and its
# external-secrets-sa ServiceAccount are chart-managed in every AKS environment,
# so this credential and the outputs below are emitted for all AKS envs. The
# namespace is derived as nohiki-${var.app_environment}.
resource "azurerm_federated_identity_credential" "external_secrets" {
  count               = var.deployment_type == "aks" ? 1 : 0
  name                = "${var.app_name}-${var.app_environment}-external-secrets"
  resource_group_name = azurerm_resource_group.app_rg.name
  audience            = ["api://AzureADTokenExchange"]
  issuer              = azurerm_kubernetes_cluster.aks_cluster[0].oidc_issuer_url
  parent_id           = azurerm_user_assigned_identity.external_secrets[0].id
  subject             = "system:serviceaccount:nohiki-${var.app_environment}:external-secrets-sa"
}

# Storage workloads federation stays production-only: only prod runs the
# nohiki-storage ServiceAccount against Azure Blob workload identity.
resource "azurerm_federated_identity_credential" "storage_workloads" {
  count               = var.deployment_type == "aks" && var.app_environment == "prod" ? 1 : 0
  name                = "${var.app_name}-${var.app_environment}-storage-workloads"
  resource_group_name = azurerm_resource_group.app_rg.name
  audience            = ["api://AzureADTokenExchange"]
  issuer              = azurerm_kubernetes_cluster.aks_cluster[0].oidc_issuer_url
  parent_id           = azurerm_user_assigned_identity.external_secrets[0].id
  subject             = "system:serviceaccount:nohiki-${var.app_environment}:nohiki-storage"
}

output "external_secrets_workload_identity_client_id" {
  description = "Client ID used by the External Secrets workload identity."
  value       = var.deployment_type == "aks" ? azurerm_user_assigned_identity.external_secrets[0].client_id : null
}

output "external_secrets_workload_identity_tenant_id" {
  description = "Azure tenant ID used by the External Secrets workload identity."
  value       = var.deployment_type == "aks" ? data.azurerm_key_vault.app_kv.tenant_id : null
}

output "external_secrets_key_vault_url" {
  description = "Vault URI used by the External Secrets ClusterSecretStore."
  value       = var.deployment_type == "aks" ? data.azurerm_key_vault.app_kv.vault_uri : null
}

# Dedicated GPU node pool for ML compute
# Stable, self-managed AKS GPU path (NOT the managed GPU preview, whose cluster
# autoscaler is unsupported): a standard user node pool on an N-series (T4) SKU.
# AKS installs the NVIDIA driver on the node; the NVIDIA device plugin DaemonSet
# (deployed via Helm) then advertises nvidia.com/gpu as an allocatable resource.
#
# Autoscaling min 0 keeps idle GPU cost at zero: the pool scales up only when a
# pod that tolerates the taint and requests nvidia.com/gpu is scheduled, and
# scales back to zero when idle. Enabled by default in production only; fully
# configurable via var.aks_gpu_node_pool_enabled (null -> prod-only, true/false
# forces it in any environment). Keep this in lockstep with the Helm ml-compute
# accelerator switch: `ml-compute-service.accelerator.mode: cuda` needs this pool
# (its prod default), while `mode: cpu` runs CPU-only and lets it disable cleanly.
locals {
  gpu_node_pool_enabled = var.deployment_type == "aks" && coalesce(var.aks_gpu_node_pool_enabled, var.app_environment == "prod")

  # Fixed scheduling contract shared with the Helm workload (NVIDIA device plugin
  # + the ml-compute-service accelerator=cuda pod) so the pool label/taint and the
  # rendered nodeSelector / tolerations stay in lockstep.
  gpu_node_label_key   = "workload"
  gpu_node_label_value = "nohiki-ml-gpu"
  gpu_node_taint_key   = "sku"
  gpu_node_taint_value = "gpu"
  gpu_node_taint       = "${local.gpu_node_taint_key}=${local.gpu_node_taint_value}:NoSchedule"
}

resource "azurerm_kubernetes_cluster_node_pool" "gpu" {
  count                 = local.gpu_node_pool_enabled ? 1 : 0
  name                  = var.aks_gpu_node_pool_name
  kubernetes_cluster_id = azurerm_kubernetes_cluster.aks_cluster[0].id
  vm_size               = var.aks_gpu_node_vm_size
  os_disk_size_gb       = var.aks_gpu_node_os_disk_size_gb

  auto_scaling_enabled = true
  min_count            = var.aks_gpu_node_min_count
  max_count            = var.aks_gpu_node_max_count
  node_count           = var.aks_gpu_node_min_count

  # No public IP on GPU nodes; they route egress through the cluster load balancer.
  node_public_ip_enabled = false

  # Attach to the same subnet as the default node pool (prod VNet; AKS-managed otherwise).
  vnet_subnet_id = var.app_environment == "prod" ? azurerm_subnet.aks[0].id : null

  # Only GPU-tolerant workloads that select this pool land here.
  node_labels = { (local.gpu_node_label_key) = local.gpu_node_label_value }
  node_taints = [local.gpu_node_taint]

  tags = {
    environment = var.app_environment
    application = var.app_name
    workload    = local.gpu_node_label_value
  }

  # The cluster autoscaler owns the live node_count between min and max.
  lifecycle {
    ignore_changes = [node_count]
  }
}

output "aks_gpu_node_pool_enabled" {
  description = "Whether the dedicated AKS GPU node pool is provisioned in this environment."
  value       = local.gpu_node_pool_enabled
}

output "aks_gpu_node_pool_name" {
  description = "Name of the dedicated AKS GPU node pool (null when disabled)."
  value       = local.gpu_node_pool_enabled ? var.aks_gpu_node_pool_name : null
}

output "aks_gpu_node_pool_vm_size" {
  description = "VM size of the GPU node pool (null when disabled)."
  value       = local.gpu_node_pool_enabled ? var.aks_gpu_node_vm_size : null
}

output "aks_gpu_node_pool_min_count" {
  description = "Autoscaling minimum node count for the GPU node pool."
  value       = local.gpu_node_pool_enabled ? var.aks_gpu_node_min_count : null
}

output "aks_gpu_node_pool_max_count" {
  description = "Autoscaling maximum node count for the GPU node pool."
  value       = local.gpu_node_pool_enabled ? var.aks_gpu_node_max_count : null
}

output "aks_gpu_node_pool_node_label" {
  description = "Node label used as the GPU workload nodeSelector (matches the Helm ml-compute scheduling contract)."
  value       = { (local.gpu_node_label_key) = local.gpu_node_label_value }
}

output "aks_gpu_node_pool_node_taint" {
  description = "Node taint applied to the GPU pool; GPU workloads must tolerate it."
  value       = local.gpu_node_taint
}