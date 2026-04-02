"""Azure Key Vault settings source.

This module requires the `azure` optional dependency:
    pip install nohiki-core-settings[azure]
"""

from __future__ import annotations

import os
from typing import Any

from azure.identity import DefaultAzureCredential
from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource
from pydantic_settings.sources import AzureKeyVaultSettingsSource


class AzureKeyVaultSourceFactory(PydanticBaseSettingsSource):
    """Factory for Azure Key Vault settings source.

    Requires environment variables:
    - AZURE_KEY_VAULT_URL: Key Vault URL (e.g., https://my-vault.vault.azure.net/)

    Uses DefaultAzureCredential which supports:
    - Managed Identity (in Azure)
    - Azure CLI credentials (local dev)
    - Environment variables (AZURE_CLIENT_ID, AZURE_TENANT_ID, AZURE_CLIENT_SECRET)
    """

    def __init__(self, settings_cls: type[BaseSettings]) -> None:
        """Initialize the Azure Key Vault source factory.

        Args:
            settings_cls: The settings class to create a source for.

        """
        super().__init__(settings_cls)
        vault_url = os.environ.get("AZURE_KEY_VAULT_URL", "")
        if not vault_url:
            msg = "AZURE_KEY_VAULT_URL environment variable is required"
            raise ValueError(msg)

        credential = DefaultAzureCredential()
        self._inner_source = AzureKeyVaultSettingsSource(
            settings_cls,
            vault_url,
            credential,
        )

    def get_field_value(
        self,
        field: FieldInfo,
        field_name: str,
    ) -> tuple[Any, str, bool]:
        """Get a field value from Azure Key Vault.

        Args:
            field: The field info.
            field_name: The field name.

        Returns:
            Tuple of (value, field_key, is_complex).

        """
        return self._inner_source.get_field_value(field, field_name)

    def __call__(self) -> dict[str, Any]:
        """Get all settings from Azure Key Vault.

        Returns:
            Dictionary of settings values.

        """
        return self._inner_source()
