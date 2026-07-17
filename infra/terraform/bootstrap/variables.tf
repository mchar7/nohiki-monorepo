variable "az_subscription_id" {
  description = "Target Azure subscription GUID that owns the state storage and role assignments."
  type        = string
  sensitive   = true
}

variable "az_location" {
  description = "Azure region for the remote-state resource group and storage account."
  type        = string
  default     = "eastus"
}

variable "github_repository" {
  description = "GitHub repository in owner/name form. Case must match GitHub's canonical casing or the OIDC subject claim will not match at token exchange."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]{1,100}$", var.github_repository))
    error_message = "github_repository must be <owner>/<name> with a valid GitHub owner and repository name."
  }
}

variable "github_default_branch" {
  description = "Default branch whose ref receives a federated credential for push and dispatch runs."
  type        = string
  default     = "main"

  validation {
    condition     = can(regex("^[A-Za-z0-9._/-]{1,244}$", var.github_default_branch))
    error_message = "github_default_branch must be a valid git branch name."
  }
}

variable "github_environments" {
  description = "GitHub deployment environments that each receive an environment-scoped federated credential."
  type        = list(string)
  default     = ["dev", "staging", "prod"]

  validation {
    condition     = length(var.github_environments) > 0 && length(var.github_environments) == length(distinct(var.github_environments))
    error_message = "github_environments must be a non-empty list of distinct environment names."
  }
}

variable "app_display_name" {
  description = "Display name of the Entra application GitHub Actions authenticates as. Must equal the live application name so the object is imported, not duplicated."
  type        = string
}

variable "deployment_scope" {
  description = "Narrow Azure scope at which the service principal receives Contributor. Set to the live deployment scope so the assignment is imported, not duplicated."
  type        = string
}

variable "state_resource_group_name" {
  description = "Resource group that holds the remote-state storage account. Set to the live resource group so it is imported, not duplicated."
  type        = string
}

variable "state_storage_account_name" {
  description = "Remote-state storage account name. Must equal the live account; storage account names are globally unique."
  type        = string
}

variable "state_container_name" {
  description = "Blob container that holds the OpenTofu state files."
  type        = string
  default     = "tfstate"
}
