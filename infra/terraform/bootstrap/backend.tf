terraform {
  backend "azurerm" {
    # Partial configuration. Supply the bootstrap state location via:
    #   tofu init -backend-config=bootstrap.backend.tfvars
    # Use key = "nohiki/bootstrap.tfstate" so this root never collides with an
    # environment state in the same account and container.
  }
}
