"""S3/Object storage configuration settings and mixin for Nohiki services."""

from enum import StrEnum
from ipaddress import ip_address
from typing import Protocol, runtime_checkable

from nohiki_core_settings import SettingsMixin
from pydantic import AnyHttpUrl, BaseModel, Field, SecretStr, field_validator


def _is_local_http_hostname(hostname: str) -> bool:
    """Return whether a hostname is reserved for loopback use."""
    ip_hostname = hostname.strip("[]")
    try:
        return ip_address(ip_hostname).is_loopback
    except ValueError:
        return hostname == "localhost" or (hostname.endswith(".localhost") and hostname != ".localhost")


class ObjectStorageProvider(StrEnum):
    """Supported object-storage protocols."""

    S3 = "s3"
    AZURE_BLOB = "azure_blob"


class S3Settings(BaseModel):
    """Object storage configuration retained under its caller-compatible name.

    ``provider`` selects the wire protocol; it defaults to S3 for existing
    services and local development.

    ``bucket`` is required with no default: services must explicitly configure
    which bucket to use. This ensures fast-fail if S3 is not configured.

    ``access_key`` and ``secret_key`` may be empty when using IAM roles or
    instance profiles for authentication.

    ``endpoint`` is empty by default which means AWS S3. For MinIO or other
    S3-compatible services, provide the full endpoint URL.
    """

    provider: ObjectStorageProvider = Field(
        default=ObjectStorageProvider.S3,
        description="Object-storage protocol used by this endpoint",
    )
    endpoint: str = Field(
        default="",
        description="S3 endpoint URL (empty = AWS S3)",
    )
    public_url: str = Field(
        default="",
        description=(
            "Public-facing endpoint used exclusively when generating presigned URLs. "
            "Required when `endpoint` is a Docker-internal host and clients are external. "
            "When empty, presigned URLs use `endpoint` unchanged."
        ),
    )
    access_key: SecretStr | None = Field(
        default=None,
        description="S3 access key (optional when using IAM roles)",
    )
    secret_key: SecretStr | None = Field(
        default=None,
        description="S3 secret key (optional when using IAM roles)",
    )
    region: str = Field(default="us-east-1")
    bucket: str = Field(description="S3 bucket name")

    connect_timeout: int = Field(default=10, ge=1)
    read_timeout: int = Field(default=30, ge=1)
    max_download_bytes: int = Field(default=64 * 1024 * 1024, ge=1)
    use_ssl: bool = Field(default=True)

    @field_validator("public_url")
    @classmethod
    def validate_public_url(cls, value: str) -> str:
        """Require a safe public presign endpoint, except for local HTTP development."""
        if not value:
            return value
        if any(character.isspace() for character in value) or any(delimiter in value for delimiter in "?#\\"):
            message = "public_url must not contain whitespace, backslashes, a query, or a fragment"
            raise ValueError(message)

        try:
            parsed = AnyHttpUrl(value)
            hostname = parsed.host
        except ValueError as error:
            message = "public_url must be an absolute HTTP(S) URL"
            raise ValueError(message) from error

        if hostname is None or parsed.username is not None or parsed.password is not None:
            message = "public_url must be absolute and must not contain credentials"
            raise ValueError(message)
        if parsed.scheme == "https":
            return value
        if parsed.scheme != "http":
            message = "public_url must use HTTPS"
            raise ValueError(message)

        if not _is_local_http_hostname(hostname):
            message = "HTTP public_url is allowed only for loopback development endpoints"
            raise ValueError(message)
        return value


class S3Mixin(SettingsMixin):
    """Mixin that declares s3 as required. Combine with NohikiBaseSettings.

    Usage::

        class Settings(S3Mixin, NohikiBaseSettings):
            model_config = SettingsConfigDict(env_prefix="MY_SERVICE_")
    """

    s3: S3Settings

    @property
    def s3_bucket(self) -> str:
        """Get S3 bucket name."""
        return self.s3.bucket


@runtime_checkable
class HasS3Settings(Protocol):
    """Protocol for settings objects that have S3 configuration."""

    @property
    def s3(self) -> S3Settings:
        """S3 configuration settings."""
        ...

    @property
    def service_name(self) -> str:
        """Service name for identification."""
        ...
