"""Qdrant client configuration and settings mixin."""

from __future__ import annotations

from typing import Self

from nohiki_core_settings.env import DEVELOPMENT_ENVIRONMENTS
from nohiki_core_settings.mixins import SettingsMixin
from pydantic import BaseModel, Field, SecretStr, model_validator


class QdrantSettings(BaseModel):
    """Qdrant connection settings (operational, not ML config).

    Collection names and vector names are derived from
    ``SemanticRepresentationManifest`` at runtime, not configured here.
    """

    host: str = Field(default="qdrant", min_length=1)
    grpc_port: int = Field(default=6334, ge=1, le=65535)
    api_key: SecretStr | None = Field(default=None)
    timeout_seconds: int = Field(default=10, ge=1, le=300)
    use_tls: bool = Field(default=False)


class QdrantMixin(SettingsMixin):
    """Mixin for services connecting to Qdrant.

    Enforces API key authentication in non-development environments
    as defense-in-depth against lateral movement. TLS is a toggle
    configured via infrastructure (Qdrant-native or service mesh mTLS).

    Env vars: ``{PREFIX}QDRANT__HOST``, ``{PREFIX}QDRANT__GRPC_PORT``,
    ``{PREFIX}QDRANT__API_KEY``, ``{PREFIX}QDRANT__USE_TLS``
    """

    qdrant: QdrantSettings = Field(default_factory=QdrantSettings)

    @model_validator(mode="after")
    def _validate_qdrant_security(self) -> Self:
        """Enforce API key in non-dev environments."""
        if self.environment not in DEVELOPMENT_ENVIRONMENTS and self.qdrant.api_key is None:
            msg = "QDRANT__API_KEY is required in non-development environments"
            raise ValueError(msg)
        return self
