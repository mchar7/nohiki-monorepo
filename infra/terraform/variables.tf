variable "deployment_type" {
  description = "Deployment target. This module currently supports Azure Kubernetes Service only."
  type        = string
  default     = "aks"
  validation {
    condition     = var.deployment_type == "aks"
    error_message = "Allowed value for deployment_type is: aks."
  }
}

variable "app_name" {
  description = "Base name for the application, used in resource naming."
  type        = string
  default     = "nohiki"
}

variable "app_environment" {
  description = "Deployment environment (e.g., dev, staging, prod)."
  type        = string
  default     = "dev"
  validation {
    condition     = contains(["dev", "staging", "prod"], var.app_environment)
    error_message = "Allowed values for app_environment are: dev, staging, prod."
  }
}

# --- Azure Core & Networking ---
variable "az_subscription_id" {
  description = "Azure Subscription ID where resources will be deployed. Null falls back to ARM_SUBSCRIPTION_ID/Azure CLI (used by the destroy workflow, which relies on OIDC login rather than an explicit -var)."
  type        = string
  sensitive   = true
  default     = null
}

variable "az_location" {
  description = "Azure region for deploying resources."
  type        = string
  default     = "eastus"
}

variable "vnet_address_space" {
  description = "Production virtual network address space."
  type        = string
  default     = "10.42.0.0/16"
  validation {
    condition     = can(cidrnetmask(var.vnet_address_space))
    error_message = "vnet_address_space must be a valid IPv4 CIDR."
  }
}

variable "aks_subnet_address_prefix" {
  description = "Production AKS node subnet address prefix."
  type        = string
  default     = "10.42.0.0/20"
  validation {
    condition     = can(cidrnetmask(var.aks_subnet_address_prefix))
    error_message = "aks_subnet_address_prefix must be a valid IPv4 CIDR."
  }
}

variable "private_endpoints_subnet_address_prefix" {
  description = "Production private endpoint subnet address prefix."
  type        = string
  default     = "10.42.16.0/24"
  validation {
    condition     = can(cidrnetmask(var.private_endpoints_subnet_address_prefix))
    error_message = "private_endpoints_subnet_address_prefix must be a valid IPv4 CIDR."
  }
}

variable "aks_service_cidr" {
  description = "Kubernetes service address range, separate from the VNet."
  type        = string
  default     = "10.43.0.0/16"
  validation {
    condition     = can(cidrnetmask(var.aks_service_cidr))
    error_message = "aks_service_cidr must be a valid IPv4 CIDR."
  }
}

variable "aks_dns_service_ip" {
  description = "Kubernetes DNS service address within aks_service_cidr."
  type        = string
  default     = "10.43.0.10"
  validation {
    condition     = can(cidrhost(var.aks_service_cidr, 10)) && var.aks_dns_service_ip == cidrhost(var.aks_service_cidr, 10)
    error_message = "aks_dns_service_ip must be host 10 within aks_service_cidr."
  }
}

# --- AKS Configuration (only used if deployment_type == "aks") ---
variable "aks_cluster_name_suffix" {
  description = "Suffix for the AKS cluster name."
  type        = string
  default     = "aks"
}

variable "aks_node_count" {
  description = "Number of nodes in the AKS default system node pool."
  type        = number
  default     = 3
}

variable "aks_node_vm_size" {
  description = "VM size for AKS system nodes."
  type        = string
  default     = "Standard_D2s_v5"
}

variable "aks_node_zones" {
  description = "Availability zones for the regular AKS node pools."
  type        = list(string)
  default     = ["1", "2", "3"]
}

variable "aks_user_node_pool_name" {
  description = "Name of the autoscaling AKS user node pool."
  type        = string
  default     = "user"
}

variable "aks_user_node_vm_size" {
  description = "VM size for AKS user nodes."
  type        = string
  default     = "Standard_D4s_v5"
}

variable "aks_user_node_min_count" {
  description = "Minimum node count for the autoscaling AKS user node pool."
  type        = number
  default     = 4
  validation {
    condition     = var.aks_user_node_min_count >= 1 && floor(var.aks_user_node_min_count) == var.aks_user_node_min_count
    error_message = "aks_user_node_min_count must be a whole number >= 1."
  }
}

variable "aks_user_node_max_count" {
  description = "Maximum node count for the autoscaling AKS user node pool."
  type        = number
  default     = 6
  validation {
    condition     = var.aks_user_node_max_count >= var.aks_user_node_min_count && floor(var.aks_user_node_max_count) == var.aks_user_node_max_count
    error_message = "aks_user_node_max_count must be a whole number >= aks_user_node_min_count."
  }
}

variable "aks_node_os_disk_size_gb" {
  description = "OS disk size in GB for AKS nodes."
  type        = number
  default     = 30
}

variable "aks_load_balancer_sku" {
  description = "SKU for the AKS load balancer (basic or standard)."
  type        = string
  default     = "standard"
}

variable "log_analytics_daily_quota_gb" {
  description = "Daily Log Analytics ingestion limit in GB."
  type        = number
  default     = 10
  validation {
    condition     = var.log_analytics_daily_quota_gb > 0
    error_message = "log_analytics_daily_quota_gb must be greater than 0."
  }
}

# --- Key Vault Configuration ---
variable "kv_rg_name" {
  description = "Name of the Azure Resource Group containing the Key Vault."
  type        = string
  default     = "nohiki-kv-rg"
}

variable "kv_name" {
  description = "Name of the Azure Key Vault storing application secrets."
  type        = string
  default     = "nohiki-kv"
}

variable "kv_acme_email_secret_name" {
  description = "Name of the Key Vault secret for the ACME registration email."
  type        = string
  default     = "acme-email"
}

variable "postgres_version" {
  description = "PostgreSQL major version supported for this deployment."
  type        = string
  default     = "18"
  validation {
    condition     = var.postgres_version == "18"
    error_message = "postgres_version must be 18 because database migrations require built-in uuidv7()."
  }
}

variable "postgres_admin_login" {
  description = "Administrator login name for the PostgreSQL server."
  type        = string
  default     = "nohikiadmin"
}

variable "postgres_database_name" {
  description = "Name of the default database to be created on the PostgreSQL server."
  type        = string
  default     = "nohiki_db"
}

# --- ACME / Cert-Manager Configuration ---
variable "acme_provider_url" {
  description = "ACME server URL for Cert-Manager or ACA Managed Certs."
  type        = string
  default     = "https://acme-staging-v02.api.letsencrypt.org/directory"
}

# --- Nohiki Specific Secrets (names of secrets in Key Vault) ---

variable "kv_openai_api_key_secret_name" {
  description = "Name of the Key Vault secret for the OpenAI API Key."
  type        = string
  default     = "openai-api-key"
}

# Redis Configuration
variable "redis_provider" {
  description = "Redis provider to use: 'azure' for Azure Cache for Redis or 'upstash' for Upstash Redis"
  type        = string
  default     = "azure"
  validation {
    condition     = contains(["azure", "upstash"], var.redis_provider)
    error_message = "Allowed values for redis_provider are: azure, upstash."
  }
  validation {
    condition     = var.app_environment != "prod" || var.redis_provider == "azure"
    error_message = "Production requires redis_provider azure for private endpoint isolation."
  }
}

# Azure Cache for Redis Configuration
variable "event_hubs_namespace_name" {
  description = "Name of the existing Event Hubs namespace used by production."
  type        = string
  default     = ""
  validation {
    condition     = var.app_environment != "prod" || trimspace(var.event_hubs_namespace_name) != ""
    error_message = "event_hubs_namespace_name must be set for production."
  }
}

variable "event_hubs_resource_group_name" {
  description = "Resource group containing the existing production Event Hubs namespace."
  type        = string
  default     = ""
  validation {
    condition     = var.app_environment != "prod" || trimspace(var.event_hubs_resource_group_name) != ""
    error_message = "event_hubs_resource_group_name must be set for production."
  }
}

variable "azure_redis_sku_name" {
  description = "SKU for Azure Cache for Redis (Basic, Standard, Premium)"
  type        = string
  default     = "Basic"
  validation {
    condition     = contains(["Basic", "Standard", "Premium"], var.azure_redis_sku_name)
    error_message = "azure_redis_sku_name must be Basic, Standard, or Premium."
  }
  validation {
    condition     = var.app_environment != "prod" || var.azure_redis_sku_name == "Standard"
    error_message = "Production requires azure_redis_sku_name Standard."
  }
}

variable "azure_redis_family" {
  description = "Redis family for Azure Cache (C for Basic/Standard, P for Premium)"
  type        = string
  default     = "C"
  validation {
    condition     = var.app_environment != "prod" || var.azure_redis_family == "C"
    error_message = "Production requires azure_redis_family C."
  }
}

variable "azure_redis_capacity" {
  description = "Redis capacity/size for Azure Cache (0-6 for C family, 1-5 for P family)"
  type        = number
  default     = 0
  validation {
    condition     = var.app_environment != "prod" || var.azure_redis_capacity == 0
    error_message = "Production requires azure_redis_capacity 0."
  }
}

# Key Vault secret names (standardized)
variable "kv_pg_conn_string_name" {
  type        = string
  description = "Key Vault secret name for PostgreSQL connection string"
  default     = "database-dsn"
}

variable "kv_internal_jwt_secret_name" {
  type        = string
  description = "Key Vault secret name for internal JWT secret"
  default     = "internal-jwt-secret"
}


# DNS zone configuration for managed certificates
variable "dns_zone_name" {
  type        = string
  description = "DNS zone name for the application (e.g., nohiki.com)"
  default     = "nohiki.com"
}

variable "dns_zone_resource_group" {
  type        = string
  description = "Resource group containing the DNS zone"
  default     = "dns-nohiki-eastus-rg-001"
}

variable "container_registry" {
  type        = string
  description = "Container registry URL"
}

variable "acr_resource_group_name" {
  type        = string
  description = "Resource group containing the Azure Container Registry"
  default     = "acr-nohiki-eastus-rg-001"
}

# PostgreSQL Flexible Server configuration
variable "postgres_flexible_sku_name" {
  type        = string
  description = "SKU for PostgreSQL Flexible Server"
  default     = "B_Standard_B1ms"
}

variable "postgres_flexible_storage_mb" {
  type        = number
  description = "Storage size in MB for PostgreSQL Flexible Server"
  default     = 32768 # 32 GiB
}

variable "postgres_flexible_storage_tier" {
  type        = string
  description = "Storage tier for PostgreSQL Flexible Server"
  default     = "P4"
}

variable "postgres_backup_retention_days" {
  type        = number
  description = "Backup retention days for PostgreSQL"
  default     = 7
}

variable "postgres_geo_redundant_backup_enabled" {
  type        = bool
  description = "Enable geo-redundant backup for PostgreSQL"
  default     = false
}

variable "postgres_maintenance_day" {
  type        = number
  description = "Day of week for PostgreSQL maintenance (0=Sunday)"
  default     = 0
}

variable "postgres_maintenance_hour" {
  type        = number
  description = "Hour for PostgreSQL maintenance (UTC)"
  default     = 1
}

# Storage Account configuration
variable "storage_account_tier" {
  type        = string
  description = "Storage account tier"
  default     = "Standard"
}

variable "storage_account_replication_type" {
  type        = string
  description = "Storage account replication type"
  default     = "LRS"
}

variable "storage_account_kind" {
  type        = string
  description = "Storage account kind"
  default     = "StorageV2"
}

variable "storage_min_tls_version" {
  type        = string
  description = "Minimum TLS version for storage account"
  default     = "TLS1_2"
}

variable "storage_delete_retention_days" {
  type        = number
  description = "Retention period for deleted blobs and containers"
  default     = 14
  validation {
    condition     = var.storage_delete_retention_days >= 7 && var.storage_delete_retention_days <= 365
    error_message = "storage_delete_retention_days must be between 7 and 365."
  }
}

# --- AKS GPU Node Pool (self-managed stable GPU path) ---
# A dedicated, autoscaling GPU node pool for ML compute (e.g. profile/listing
# embedding). It uses the stable AKS GPU path: AKS installs the NVIDIA driver on
# the node and the NVIDIA device plugin (deployed via Helm) advertises
# nvidia.com/gpu. The AKS managed GPU preview is intentionally NOT used because
# cluster autoscaler is unsupported there.
variable "aks_gpu_node_pool_enabled" {
  description = "Enable the dedicated AKS GPU node pool. Null (default) enables it only in production; set true/false to force it in any environment."
  type        = bool
  nullable    = true
  default     = null
}

variable "aks_gpu_node_pool_name" {
  description = "Name of the AKS GPU node pool. Must be a valid Linux node pool name (lowercase alphanumeric, start with a letter, 1-12 chars)."
  type        = string
  default     = "gpu"
  validation {
    condition     = can(regex("^[a-z][a-z0-9]{0,11}$", var.aks_gpu_node_pool_name))
    error_message = "aks_gpu_node_pool_name must be lowercase alphanumeric, start with a letter, and be 1-12 characters."
  }
}

variable "aks_gpu_node_vm_size" {
  description = "VM size for the AKS GPU node pool. Must be an Azure N-series (NVIDIA GPU) size. Default Standard_NC4as_T4_v3 is the minimum supported single-T4 AKS GPU SKU."
  type        = string
  default     = "Standard_NC4as_T4_v3"
  validation {
    condition     = can(regex("^Standard_N", var.aks_gpu_node_vm_size))
    error_message = "aks_gpu_node_vm_size must be an Azure N-series (NVIDIA GPU) VM size, e.g. Standard_NC4as_T4_v3."
  }
}

variable "aks_gpu_node_min_count" {
  description = "Minimum node count for the autoscaling GPU node pool. Keep at 0 so idle GPU cost is bounded to zero."
  type        = number
  default     = 0
  validation {
    condition     = var.aks_gpu_node_min_count >= 0 && floor(var.aks_gpu_node_min_count) == var.aks_gpu_node_min_count
    error_message = "aks_gpu_node_min_count must be a whole number >= 0."
  }
}

variable "aks_gpu_node_max_count" {
  description = "Maximum node count for the autoscaling GPU node pool."
  type        = number
  default     = 1
  validation {
    condition     = var.aks_gpu_node_max_count >= 1 && floor(var.aks_gpu_node_max_count) == var.aks_gpu_node_max_count
    error_message = "aks_gpu_node_max_count must be a whole number >= 1."
  }
  validation {
    condition     = var.aks_gpu_node_max_count >= var.aks_gpu_node_min_count
    error_message = "aks_gpu_node_max_count must be >= aks_gpu_node_min_count."
  }
}

variable "aks_gpu_node_os_disk_size_gb" {
  description = "OS disk size in GB for GPU nodes. GPU/CUDA container images are large, so this defaults higher than the standard node pool."
  type        = number
  default     = 128
  validation {
    condition     = var.aks_gpu_node_os_disk_size_gb >= 30
    error_message = "aks_gpu_node_os_disk_size_gb must be at least 30 GB."
  }
}
