deployment_type = "aks"

# Azure core and networking
# az_subscription_id = "YOUR_AZURE_SUBSCRIPTION_ID"
az_location             = "eastus"
dns_zone_resource_group = "nohiki-dns-rg"
dns_zone_name           = "nohiki.yourdomain.com"
acr_resource_group_name = "acr-nohiki-eastus-rg-001"
container_registry      = "acrnohikiprod.azurecr.io"

# Environment
app_environment = "dev"

# AKS
aks_node_count               = 3
aks_node_vm_size             = "Standard_D2s_v5"
aks_node_zones               = ["1", "2", "3"]
aks_user_node_pool_name      = "user"
aks_user_node_vm_size        = "Standard_D4s_v5"
aks_user_node_min_count      = 4
aks_user_node_max_count      = 6
aks_node_os_disk_size_gb     = 30
aks_load_balancer_sku        = "Standard"
log_analytics_daily_quota_gb = 10

# Existing Key Vault
kv_rg_name = "kv-nohiki-eastus-rg-001"
kv_name    = "nohiki-kv"

# PostgreSQL
postgres_admin_login   = "nohikiadmin"
postgres_database_name = "nohiki_db"
postgres_version       = "16"

# Use the Let's Encrypt production URL only after validating staging issuance.
acme_provider_url = "https://acme-staging-v02.api.letsencrypt.org/directory"

# Cache and blob storage
redis_provider                = "azure"
azure_redis_sku_name          = "Basic"
azure_redis_family            = "C"
azure_redis_capacity          = 0
storage_delete_retention_days = 14

# AKS GPU node pool (self-managed stable GPU path)
# The GPU pool is disabled here (dev). It is enabled automatically in production
# (app_environment = "prod") since aks_gpu_node_pool_enabled defaults to null.
# Set it explicitly to true/false to force it in any environment. Autoscaling
# min 0 keeps idle GPU cost at zero.
# aks_gpu_node_pool_enabled    = false
# aks_gpu_node_pool_name       = "gpu"
# aks_gpu_node_vm_size         = "Standard_NC4as_T4_v3"
# aks_gpu_node_min_count       = 0
# aks_gpu_node_max_count       = 1
# aks_gpu_node_os_disk_size_gb = 128