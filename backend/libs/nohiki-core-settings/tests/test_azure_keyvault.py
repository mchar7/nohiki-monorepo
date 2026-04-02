"""Tests for Azure Key Vault settings source."""

from __future__ import annotations

import importlib.util
from unittest.mock import MagicMock, patch

import pytest
from nohiki_core_settings import AzureKeyVaultNotInstalledError, NohikiBaseSettings
from pydantic import Field
from pydantic.fields import FieldInfo

# Check if azure-identity is available
_AZURE_AVAILABLE = importlib.util.find_spec("azure.identity") is not None

if _AZURE_AVAILABLE:
    from nohiki_core_settings.sources.azure_keyvault import AzureKeyVaultSourceFactory

pytestmark = pytest.mark.skipif(
    not _AZURE_AVAILABLE,
    reason="azure-identity not installed - install with: pip install nohiki-core-settings[azure]",
)


class TestAzureKeyVaultSourceFactory:
    """Tests for AzureKeyVaultSourceFactory."""

    def test_requires_vault_url(self) -> None:
        """Test that factory raises ValueError without AZURE_KEY_VAULT_URL."""

        class TestSettings(NohikiBaseSettings):
            service_name: str = "test-service"
            service_name_friendly: str = "Test Service"
            service_desc_friendly: str = "Test"
            service_version: str = "1.0.0"

        with pytest.raises(ValueError, match="AZURE_KEY_VAULT_URL environment variable is required"):
            AzureKeyVaultSourceFactory(TestSettings)

    def test_creates_source_with_vault_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that factory creates source when AZURE_KEY_VAULT_URL is set."""
        monkeypatch.setenv("AZURE_KEY_VAULT_URL", "https://test-vault.vault.azure.net")

        class TestSettings(NohikiBaseSettings):
            service_name: str = "test-service"
            service_name_friendly: str = "Test Service"
            service_desc_friendly: str = "Test"
            service_version: str = "1.0.0"

        # Mock the credential and inner source to avoid actual Azure calls
        with (
            patch("nohiki_core_settings.sources.azure_keyvault.DefaultAzureCredential"),
            patch("nohiki_core_settings.sources.azure_keyvault.AzureKeyVaultSettingsSource"),
        ):
            factory = AzureKeyVaultSourceFactory(TestSettings)
            assert isinstance(factory, AzureKeyVaultSourceFactory)

    def test_get_field_value_delegates_to_inner_source(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that get_field_value delegates to inner source."""
        monkeypatch.setenv("AZURE_KEY_VAULT_URL", "https://test-vault.vault.azure.net")

        class TestSettings(NohikiBaseSettings):
            service_name: str = "test-service"
            service_name_friendly: str = "Test Service"
            service_desc_friendly: str = "Test"
            service_version: str = "1.0.0"

        mock_inner = MagicMock()
        mock_inner.get_field_value.return_value = ("secret-value", "field_key", False)

        with (
            patch("nohiki_core_settings.sources.azure_keyvault.DefaultAzureCredential"),
            patch(
                "nohiki_core_settings.sources.azure_keyvault.AzureKeyVaultSettingsSource",
                return_value=mock_inner,
            ),
        ):
            factory = AzureKeyVaultSourceFactory(TestSettings)

            # Create a real FieldInfo instance
            test_field = FieldInfo(default="default_value")
            result = factory.get_field_value(test_field, "test_field")

            assert result == ("secret-value", "field_key", False)
            mock_inner.get_field_value.assert_called_once_with(test_field, "test_field")

    def test_call_delegates_to_inner_source(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that __call__ delegates to inner source."""
        monkeypatch.setenv("AZURE_KEY_VAULT_URL", "https://test-vault.vault.azure.net")

        class TestSettings(NohikiBaseSettings):
            service_name: str = "test-service"
            service_name_friendly: str = "Test Service"
            service_desc_friendly: str = "Test"
            service_version: str = "1.0.0"

        mock_inner = MagicMock()
        mock_inner.return_value = {"service_name": "from-keyvault"}

        with (
            patch("nohiki_core_settings.sources.azure_keyvault.DefaultAzureCredential"),
            patch(
                "nohiki_core_settings.sources.azure_keyvault.AzureKeyVaultSettingsSource",
                return_value=mock_inner,
            ),
        ):
            factory = AzureKeyVaultSourceFactory(TestSettings)
            result = factory()

            assert result == {"service_name": "from-keyvault"}
            mock_inner.assert_called_once()


class TestAzureKeyVaultIntegration:
    """Tests for Azure Key Vault integration in base settings."""

    def test_settings_load_with_azure_url_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that settings load correctly when AZURE_KEY_VAULT_URL is set."""
        monkeypatch.setenv("AZURE_KEY_VAULT_URL", "https://test-vault.vault.azure.net")

        # Mock the Azure SDK to avoid actual network calls
        with (
            patch("nohiki_core_settings.sources.azure_keyvault.DefaultAzureCredential"),
            patch("nohiki_core_settings.sources.azure_keyvault.AzureKeyVaultSettingsSource") as mock_source,
        ):
            # Mock the source to return empty dict (no secrets)
            mock_source.return_value.return_value = {}

            class TestSettings(NohikiBaseSettings):
                service_name: str = "test-service"
                service_name_friendly: str = "Test Service"
                service_desc_friendly: str = "Test"
                service_version: str = "1.0.0"
                custom_field: str = Field(default="default")

            settings = TestSettings()
            assert settings.custom_field == "default"

    def test_azure_not_installed_error_when_url_set_but_module_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that clear error is raised when azure is not installed but URL is set."""
        monkeypatch.setenv("AZURE_KEY_VAULT_URL", "https://test-vault.vault.azure.net")

        # Simulate azure-identity not being installed
        with (
            patch("nohiki_core_settings.base._azure_keyvault_source_factory", None),
            patch("nohiki_core_settings.base._AZURE_IDENTITY_AVAILABLE", new=False),
        ):

            class TestSettings(NohikiBaseSettings):
                service_name: str = "test-service"
                service_name_friendly: str = "Test Service"
                service_desc_friendly: str = "Test"
                service_version: str = "1.0.0"

            with pytest.raises(
                AzureKeyVaultNotInstalledError,
                match="AZURE_KEY_VAULT_URL is set but azure-identity is not installed",
            ):
                TestSettings()


class TestSecretsDirectoryHandling:
    """Tests for secrets directory handling."""

    def test_missing_secrets_dir_handled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that missing secrets directory is handled gracefully."""
        monkeypatch.setenv("SECRETS_DIR", "/nonexistent/path/to/secrets")

        class TestSettings(NohikiBaseSettings):
            service_name: str = "test-service"
            service_name_friendly: str = "Test Service"
            service_desc_friendly: str = "Test"
            service_version: str = "1.0.0"
            custom_field: str = Field(default="default")

        # Should not raise, just use defaults
        settings = TestSettings()
        assert settings.custom_field == "default"
