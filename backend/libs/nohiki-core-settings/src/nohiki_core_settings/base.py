"""Base settings for all Nohiki services."""

import importlib.util
import os
from typing import Literal

from pydantic import Field
from pydantic_settings import (
    BaseSettings,
    NestedSecretsSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from nohiki_core_settings.env import is_development
from nohiki_core_settings.observability import ObservabilitySettings

type SecretsDirMissing = Literal["ok", "warn", "error"]

DEFAULT_SECRETS_DIR = "/run/secrets"


def _check_azure_identity_available() -> bool:
    """Check if azure-identity package is available."""
    try:
        return importlib.util.find_spec("azure.identity") is not None
    except ModuleNotFoundError:
        return False


_AZURE_IDENTITY_AVAILABLE = _check_azure_identity_available()

_azure_keyvault_source_factory: type[PydanticBaseSettingsSource] | None = None

if _AZURE_IDENTITY_AVAILABLE:
    from nohiki_core_settings.sources.azure_keyvault import AzureKeyVaultSourceFactory

    _azure_keyvault_source_factory = AzureKeyVaultSourceFactory


class NohikiBaseSettings(BaseSettings):
    """Base settings class for all Nohiki services.

    Domain-specific settings are added via mixins from their respective packages:
    - ``KafkaMixin`` from ``nohiki_kafka_client``
    - ``DatabaseMixin`` from ``nohiki_db_utils``
    - ``RedisMixin`` from ``nohiki_redis_utils``
    - ``S3Mixin`` from ``nohiki_s3_client``
    - ``LLMMixin`` from ``nohiki_llm_client``
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )

    service_name: str = Field()
    service_name_friendly: str = Field()
    service_desc_friendly: str = Field()
    service_version: str = Field()

    environment: str = Field(
        default_factory=lambda: os.environ.get("ENVIRONMENT", "development"),
    )

    debug: bool = Field(default=False)
    host: str = Field(default="127.0.0.1")
    port: int = Field(default=8000, ge=1, le=65535)
    api_prefix: str = Field(default="/api/v1")

    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)

    @property
    def instrument_redis(self) -> bool:
        """Whether to enable Redis OTEL instrumentation.

        Default is ``False``. ``RedisMixin`` overrides this to ``True`` via MRO,
        so services with Redis automatically get Redis instrumentation.
        """
        return False

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Customize settings sources priority."""
        secrets_dir_missing: SecretsDirMissing = "ok" if is_development() else "error"
        # SECRETS_DIR is read here rather than frozen into ``model_config`` at import time,
        # which would tie the secrets source to whichever module imported this one first and
        # silently discard any later change. A directory pinned in a class config, or passed
        # as ``_secrets_dir``, still takes precedence inside the source.
        secrets_dir = os.environ.get("SECRETS_DIR", DEFAULT_SECRETS_DIR)

        sources: list[PydanticBaseSettingsSource] = [
            init_settings,
            env_settings,
            dotenv_settings,
            NestedSecretsSettingsSource(
                file_secret_settings,
                secrets_dir=secrets_dir,
                secrets_nested_subdir=True,
                secrets_prefix="",
                secrets_dir_missing=secrets_dir_missing,
            ),
        ]

        _maybe_add_azure_keyvault_source(sources, settings_cls)

        return tuple(sources)


class AzureKeyVaultNotInstalledError(ImportError):
    """Raised when Azure Key Vault is requested but azure-identity is not installed."""


def _maybe_add_azure_keyvault_source(
    sources: list[PydanticBaseSettingsSource],
    settings_cls: type[BaseSettings],
) -> None:
    """Add Azure Key Vault source if configured and available.

    Args:
        sources: List of settings sources to append to.
        settings_cls: The settings class being instantiated.

    Raises:
        AzureKeyVaultNotInstalledError: If AZURE_KEY_VAULT_URL is set but
            azure-identity is not installed.

    """
    vault_url = os.environ.get("AZURE_KEY_VAULT_URL")
    if not vault_url:
        return

    if _azure_keyvault_source_factory is None:
        msg = (
            "AZURE_KEY_VAULT_URL is set but azure-identity is not installed. "
            "Install with: pip install nohiki-core-settings[azure]"
        )
        raise AzureKeyVaultNotInstalledError(msg)

    sources.append(_azure_keyvault_source_factory(settings_cls))
