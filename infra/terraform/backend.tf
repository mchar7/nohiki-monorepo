terraform {
  backend "azurerm" {
    # Environment-specific backend settings, including the state key, are
    # required via: tofu init -backend-config=backend.tfvars
  }
}