"""Async S3-compatible object storage client for Nohiki services."""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

from nohiki_s3_client.exceptions import (
    S3ConnectionError,
    S3Error,
    S3ObjectNotFoundError,
    S3ObjectTooLargeError,
    S3PermissionError,
)

if TYPE_CHECKING:
    from nohiki_s3_client.client import S3Client as S3Client
    from nohiki_s3_client.client import S3ObjectMetadata as S3ObjectMetadata
    from nohiki_s3_client.client import S3PresignedPutConstraints as S3PresignedPutConstraints
    from nohiki_s3_client.health import S3Capability as S3Capability
    from nohiki_s3_client.health import S3HealthProbe as S3HealthProbe
    from nohiki_s3_client.health import ensure_s3_ready as ensure_s3_ready
    from nohiki_s3_client.metrics import S3Metrics as S3Metrics
    from nohiki_s3_client.metrics import get_s3_metrics as get_s3_metrics
    from nohiki_s3_client.settings import HasS3Settings as HasS3Settings
    from nohiki_s3_client.settings import ObjectStorageProvider as ObjectStorageProvider
    from nohiki_s3_client.settings import S3Mixin as S3Mixin
    from nohiki_s3_client.settings import S3Settings as S3Settings

_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "S3Client": ("nohiki_s3_client.client", "S3Client"),
    "S3ObjectMetadata": ("nohiki_s3_client.client", "S3ObjectMetadata"),
    "S3PresignedPutConstraints": ("nohiki_s3_client.client", "S3PresignedPutConstraints"),
    "S3Capability": ("nohiki_s3_client.health", "S3Capability"),
    "S3HealthProbe": ("nohiki_s3_client.health", "S3HealthProbe"),
    "ensure_s3_ready": ("nohiki_s3_client.health", "ensure_s3_ready"),
    "S3Metrics": ("nohiki_s3_client.metrics", "S3Metrics"),
    "get_s3_metrics": ("nohiki_s3_client.metrics", "get_s3_metrics"),
    "HasS3Settings": ("nohiki_s3_client.settings", "HasS3Settings"),
    "ObjectStorageProvider": ("nohiki_s3_client.settings", "ObjectStorageProvider"),
    "S3Mixin": ("nohiki_s3_client.settings", "S3Mixin"),
    "S3Settings": ("nohiki_s3_client.settings", "S3Settings"),
}

_s3_client_cache: dict[int, S3Client] = {}


def get_s3_client(settings: S3Settings) -> S3Client:
    """Get a cached S3Client instance for the given settings.

    Args:
        settings: S3Settings instance with bucket, endpoint, and credentials.

    Returns:
        Cached S3Client instance for these settings.

    """
    settings_id = id(settings)
    if settings_id not in _s3_client_cache:
        from nohiki_s3_client.client import S3Client  # noqa: PLC0415 -- Construct on first S3 use.

        _s3_client_cache[settings_id] = S3Client(settings)
    return _s3_client_cache[settings_id]


def __getattr__(name: str) -> object:
    """Lazy-import object clients, health probes, and metrics on first use."""
    if name in _LAZY_IMPORTS:
        module_path, attr_name = _LAZY_IMPORTS[name]
        module = importlib.import_module(module_path)
        return getattr(module, attr_name)
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)


__all__ = [
    "HasS3Settings",
    "ObjectStorageProvider",
    "S3Capability",
    "S3Client",
    "S3ConnectionError",
    "S3Error",
    "S3HealthProbe",
    "S3Metrics",
    "S3Mixin",
    "S3ObjectMetadata",
    "S3ObjectNotFoundError",
    "S3ObjectTooLargeError",
    "S3PermissionError",
    "S3PresignedPutConstraints",
    "ensure_s3_ready",
    "get_s3_client",
    "get_s3_metrics",
]
