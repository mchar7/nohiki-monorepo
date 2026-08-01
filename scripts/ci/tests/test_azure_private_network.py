from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_IAC = _ROOT / "infra" / "terraform"


def _iac() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in sorted(_IAC.glob("*.tf")))


def _block(document: str, kind: str, name: str) -> str:
    match = re.search(rf'(?m)^(?:resource|data) "{re.escape(kind)}" "{re.escape(name)}"\s*\{{', document)
    assert match, f"missing {kind}.{name}"
    depth = 0
    for index in range(match.end() - 1, len(document)):
        if document[index] == "{":
            depth += 1
        elif document[index] == "}":
            depth -= 1
            if depth == 0:
                return document[match.start() : index + 1]
    pytest.fail("unterminated HCL block")


def _flat(document: str) -> str:
    return re.sub(r"\s+", " ", document)


def test_production_private_network_topology_and_aks_cni_contract() -> None:
    iac = _iac()
    vnet = _block(iac, "azurerm_virtual_network", "app")
    aks_subnet = _block(iac, "azurerm_subnet", "aks")
    pe_subnet = _block(iac, "azurerm_subnet", "private_endpoints")
    aks = _block(iac, "azurerm_kubernetes_cluster", "aks_cluster")
    iac_contract = _flat(iac)
    vnet_contract = _flat(vnet)
    aks_subnet_contract = _flat(aks_subnet)
    pe_subnet_contract = _flat(pe_subnet)
    aks_contract = _flat(aks)

    assert 'default = "10.42.0.0/16"' in iac_contract
    assert 'default = "10.42.0.0/20"' in iac_contract
    assert 'default = "10.42.16.0/24"' in iac_contract
    assert "address_space = [var.vnet_address_space]" in vnet_contract
    assert "address_prefixes = [var.aks_subnet_address_prefix]" in aks_subnet_contract
    assert "address_prefixes = [var.private_endpoints_subnet_address_prefix]" in pe_subnet_contract
    assert 'private_endpoint_network_policies = "Disabled"' in pe_subnet_contract
    assert 'vnet_subnet_id = var.app_environment == "prod" ? azurerm_subnet.aks[0].id : null' in aks_contract
    assert 'network_plugin = "azure"' in aks_contract
    assert 'network_policy = "azure"' in aks_contract
    assert "service_cidr = var.aks_service_cidr" in aks_contract
    assert "dns_service_ip = var.aks_dns_service_ip" in aks_contract
    assert 'default = "10.43.0.0/16"' in iac_contract
    assert 'default = "10.43.0.10"' in iac_contract
    assert 'resource "azurerm_route_table"' not in iac
    assert 'resource "azurerm_network_security_group"' not in iac


def test_aks_control_plane_tier_and_log_ingestion_are_cost_bounded() -> None:
    iac = _iac()
    aks = _block(iac, "azurerm_kubernetes_cluster", "aks_cluster")
    workspace = _block(iac, "azurerm_log_analytics_workspace", "aks")
    daily_quota = re.search(r'(?ms)^variable "log_analytics_daily_quota_gb"\s*\{.*?^\}', iac)
    aks_contract = _flat(aks)
    workspace_contract = _flat(workspace)

    assert 'sku_tier = var.app_environment == "prod" ? "Standard" : "Free"' in aks_contract
    assert "daily_quota_gb = var.log_analytics_daily_quota_gb" in workspace_contract
    assert daily_quota is not None
    assert re.search(r"(?m)^\s*default\s*=\s*10\s*$", daily_quota.group(0))
    assert "var.log_analytics_daily_quota_gb > 0" in daily_quota.group(0)


def test_managed_services_use_exact_private_link_contracts() -> None:
    iac = _iac()
    expected = {
        "postgres": ("postgresqlServer", "privatelink.postgres.database.azure.com"),
        "redis": ("redisCache", "privatelink.redis.cache.windows.net"),
        "blob": ("blob", "privatelink.blob.core.windows.net"),
        "event_hubs": ("namespace", "privatelink.servicebus.windows.net"),
    }
    for name, (group, zone) in expected.items():
        endpoint = _block(iac, "azurerm_private_endpoint", name)
        assert re.search(r"(?m)^\s*count\s*=\s*local\.production_private_network\s*$", endpoint)
        assert f'subresource_names = ["{group}"]' in _flat(endpoint)
        assert zone in iac

    postgres = _block(iac, "azurerm_postgresql_flexible_server", "nohiki_postgres")
    redis = _block(iac, "azurerm_redis_cache", "main")
    expected_public_access = r'(?m)^\s*public_network_access_enabled\s*=\s*var\.app_environment != "prod"\s*$'
    for service in (postgres, redis):
        assert re.search(expected_public_access, service)
    assert 'version = "~> 4.80.0"' in iac
    assert 'data "azurerm_eventhub_namespace"' in iac
    assert 'variable "event_hubs_namespace_name"' in iac
    assert 'variable "event_hubs_resource_group_name"' in iac


def test_postgres_18_is_required_for_uuidv7_migrations() -> None:
    iac = _iac()
    postgres_version = re.search(r'(?ms)^variable "postgres_version"\s*\{.*?^\}', iac)

    assert postgres_version
    contract = postgres_version.group(0)
    assert re.search(r'(?m)^\s*default\s*=\s*"18"\s*$', contract)
    assert re.search(r'(?m)^\s*condition\s*=\s*var\.postgres_version == "18"\s*$', contract)
    assert (
        'error_message = "postgres_version must be 18 because database migrations require built-in uuidv7()."'
        in contract
    )


def test_obsolete_storage_queue_configuration_is_absent() -> None:
    iac = _iac()
    obsolete_symbols = (
        "use_azure_storage_queue",
        "queue_name_prefix",
        "kv_storage_queue_cs_name",
        "storage-queue-cs",
        "AZURE_STORAGE_CONNECTION_STRING",
    )
    for symbol in obsolete_symbols:
        assert symbol not in iac
    assert re.search(r"objectAlias\s*:\s*AZURE_STORAGE_CONNECTION_STRING", iac) is None


def test_blob_supports_browser_sas_without_anonymous_object_access() -> None:
    iac = _iac()
    storage = _block(iac, "azurerm_storage_account", "nohiki_storage")
    container = _block(iac, "azapi_resource", "nohiki_blob_container")
    storage_contract = _flat(storage)

    assert re.search(r"public_network_access_enabled\s*=\s*true", storage)
    assert re.search(r"shared_access_key_enabled\s*=\s*false", storage)
    assert re.search(r"allow_nested_items_to_be_public\s*=\s*false", storage)
    assert re.search(r"https_traffic_only_enabled\s*=\s*true", storage)
    assert re.search(r"min_tls_version\s*=\s*var\.storage_min_tls_version", storage)
    assert re.search(r'variable "storage_min_tls_version"\s*\{.*?default\s*=\s*"TLS1_2"', iac, re.DOTALL)
    assert 'allowed_origins = ["https://nohiki.com"]' in storage_contract
    assert 'allowed_methods = ["GET", "HEAD", "PUT"]' in storage_contract
    assert 'allowed_headers = ["Content-Type", "x-ms-blob-type"]' in storage_contract
    assert 'exposed_headers = ["Content-Length", "Content-Type", "ETag", "Last-Modified"]' in storage_contract
    assert "max_age_in_seconds = 3600" in storage
    assert 'publicAccess = "None"' in container
    assert "network_rules" not in storage


def test_network_output_storage_container_and_eso_secrets_contract() -> None:
    iac = _iac()
    output = re.search(r'(?ms)^output "production_network"\s*\{.*?^\}', iac)
    assert output
    assert "sensitive = true" not in output.group(0)
    assert set(re.findall(r"(?m)^\s{4}(database|redis|s3|kafka)\s*=", output.group(0))) == {
        "database",
        "redis",
        "s3",
        "kafka",
    }
    assert output.group(0).count("private_ip_address}/32") == 4

    container = _block(iac, "azapi_resource", "nohiki_blob_container")
    container_contract = _flat(container)
    assert 'type = "Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01"' in container_contract
    assert 'name = "nohiki-prod"' in container_contract
    assert 'publicAccess = "None"' in container_contract
    expected_secret_names = {"s3-access-key", "s3-secret-key", "s3-region", "redis-dsn"}
    secret_names = {
        match.group(1)
        for match in re.finditer(r'(?m)^\s*name\s*=\s*"([^"]+)"', iac)
        if match.group(1) in expected_secret_names
    }
    assert secret_names == expected_secret_names
    for generic_pg_name in ("database-host", "database-port", "database-name", "database-user", "database-password"):
        assert f'"{generic_pg_name}"' in iac
