"""Async S3-compatible object storage client for Nohiki services."""

from nohiki_s3_client.client import S3Client, S3ObjectMetadata, S3PresignedPutConstraints
from nohiki_s3_client.exceptions import (
    S3ConnectionError,
    S3Error,
    S3ObjectNotFoundError,
    S3ObjectTooLargeError,
    S3PermissionError,
)
from nohiki_s3_client.health import S3Capability, S3HealthProbe, ensure_s3_ready
from nohiki_s3_client.metrics import S3Metrics, get_s3_metrics
from nohiki_s3_client.settings import HasS3Settings, ObjectStorageProvider, S3Mixin, S3Settings

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
        _s3_client_cache[settings_id] = S3Client(settings)
    return _s3_client_cache[settings_id]


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
