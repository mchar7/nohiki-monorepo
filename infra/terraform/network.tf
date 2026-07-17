resource "azurerm_virtual_network" "app" {
  count               = var.app_environment == "prod" ? 1 : 0
  name                = "${var.app_name}-${var.app_environment}-vnet"
  location            = azurerm_resource_group.app_rg.location
  resource_group_name = azurerm_resource_group.app_rg.name
  address_space       = [var.vnet_address_space]

  tags = { environment = var.app_environment, application = var.app_name }
}

resource "azurerm_subnet" "aks" {
  count                = var.app_environment == "prod" ? 1 : 0
  name                 = "aks"
  resource_group_name  = azurerm_resource_group.app_rg.name
  virtual_network_name = azurerm_virtual_network.app[0].name
  address_prefixes     = [var.aks_subnet_address_prefix]
}

resource "azurerm_subnet" "private_endpoints" {
  count                             = var.app_environment == "prod" ? 1 : 0
  name                              = "private-endpoints"
  resource_group_name               = azurerm_resource_group.app_rg.name
  virtual_network_name              = azurerm_virtual_network.app[0].name
  address_prefixes                  = [var.private_endpoints_subnet_address_prefix]
  private_endpoint_network_policies = "Disabled"
}

# Public IP for AKS Ingress Controller (only if deploying to AKS)
resource "azurerm_public_ip" "ingress_pip" {
  count = var.deployment_type == "aks" ? 1 : 0
  name  = "${var.app_name}-${var.app_environment}-ingress-pip"
  # Deploys to the MC_* RG associated with the AKS cluster
  resource_group_name = azurerm_kubernetes_cluster.aks_cluster[0].node_resource_group
  location            = azurerm_resource_group.app_rg.location
  allocation_method   = "Static"
  sku                 = "Standard"
  tags                = { environment = var.app_environment, application = var.app_name }
  depends_on          = [azurerm_kubernetes_cluster.aks_cluster[0]]
}

# DNS A Record for AKS Ingress
resource "azurerm_dns_a_record" "aks_app_dns_a_record" {
  count               = var.deployment_type == "aks" ? 1 : 0
  name                = var.app_environment # e.g., "dev" -> dev.nohiki.yourdomain.com
  zone_name           = data.azurerm_dns_zone.app_dns_zone.name
  resource_group_name = data.azurerm_dns_zone.app_dns_zone.resource_group_name
  ttl                 = 300
  records             = [azurerm_public_ip.ingress_pip[0].ip_address]
  depends_on          = [azurerm_public_ip.ingress_pip[0], data.azurerm_dns_zone.app_dns_zone]
}