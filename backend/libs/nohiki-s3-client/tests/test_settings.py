"""Tests for S3Settings."""

from __future__ import annotations

import pytest
from nohiki_s3_client import S3Settings
from pydantic import SecretStr, ValidationError


class TestS3SettingsRequired:
    """Tests for required field validation."""

    def test_requires_bucket(self) -> None:
        """Test that bucket is required."""
        with pytest.raises(ValidationError) as exc_info:
            S3Settings.model_validate({})
        assert "bucket" in str(exc_info.value)

    def test_bucket_provided(self) -> None:
        """Test that providing bucket is valid."""
        settings = S3Settings(bucket="my-bucket")
        assert settings.bucket == "my-bucket"


class TestS3SettingsDefaults:
    """Tests for default settings when bucket is provided."""

    def test_default_values(self) -> None:
        """Test default S3 settings values."""
        settings = S3Settings(bucket="my-bucket")
        assert settings.endpoint == ""
        assert settings.access_key is None
        assert settings.secret_key is None
        assert settings.region == "us-east-1"
        assert settings.bucket == "my-bucket"
        assert settings.connect_timeout == 10
        assert settings.read_timeout == 30
        assert settings.use_ssl is True

    def test_credentials_optional_for_iam_roles(self) -> None:
        """Test that access_key and secret_key are optional (for IAM roles)."""
        settings = S3Settings(bucket="my-bucket")
        assert settings.access_key is None
        assert settings.secret_key is None


class TestS3SettingsCustom:
    """Tests for custom configuration."""

    def test_aws_s3_config(self) -> None:
        """Test AWS S3 configuration (empty endpoint)."""
        settings = S3Settings(
            access_key=SecretStr("AKIAIOSFODNN7EXAMPLE"),
            secret_key=SecretStr("wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"),
            region="eu-west-1",
            bucket="my-bucket",
        )
        assert settings.endpoint == ""
        assert settings.access_key is not None
        assert settings.access_key.get_secret_value() == "AKIAIOSFODNN7EXAMPLE"
        assert settings.region == "eu-west-1"
        assert settings.bucket == "my-bucket"

    def test_minio_config(self) -> None:
        """Test MinIO configuration (custom endpoint)."""
        settings = S3Settings(
            endpoint="http://minio:9000",
            access_key=SecretStr("minioadmin"),
            secret_key=SecretStr("minioadmin"),
            region="us-east-1",
            bucket="test-bucket",
            use_ssl=False,
        )
        assert settings.endpoint == "http://minio:9000"
        assert settings.use_ssl is False

    def test_custom_timeouts(self) -> None:
        """Test custom timeout settings."""
        settings = S3Settings(
            bucket="my-bucket",
            connect_timeout=30,
            read_timeout=60,
        )
        assert settings.connect_timeout == 30
        assert settings.read_timeout == 60


class TestS3SettingsValidation:
    """Tests for validation logic."""

    def test_connect_timeout_positive(self) -> None:
        """Test connect_timeout must be positive."""
        settings = S3Settings(bucket="my-bucket", connect_timeout=1)
        assert settings.connect_timeout == 1

        with pytest.raises(ValidationError):
            S3Settings(bucket="my-bucket", connect_timeout=0)

        with pytest.raises(ValidationError):
            S3Settings(bucket="my-bucket", connect_timeout=-1)

    def test_read_timeout_positive(self) -> None:
        """Test read_timeout must be positive."""
        settings = S3Settings(bucket="my-bucket", read_timeout=1)
        assert settings.read_timeout == 1

        with pytest.raises(ValidationError):
            S3Settings(bucket="my-bucket", read_timeout=0)

        with pytest.raises(ValidationError):
            S3Settings(bucket="my-bucket", read_timeout=-1)


class TestS3SettingsPublicUrl:
    """Tests for public presigned-URL endpoint validation."""

    @pytest.mark.parametrize(
        "public_url",
        [
            "http://storage.example.com",
            "https://user:password@storage.example.com",
            "https://storage.example.com/presigned?tenant=other",
            "https://storage.example.com/presigned#fragment",
            "/presigned",
        ],
    )
    def test_rejects_unsafe_public_url(self, public_url: str) -> None:
        """Remote HTTP and URLs with ambiguous authority or suffixes are unsafe."""
        with pytest.raises(ValidationError):
            S3Settings(bucket="my-bucket", public_url=public_url)

    def test_accepts_https_remote_public_url(self) -> None:
        """Remote public endpoints are valid when protected by TLS."""
        settings = S3Settings(bucket="my-bucket", public_url="https://storage.example.com:9443/presigned")

        assert settings.public_url == "https://storage.example.com:9443/presigned"

    def test_accepts_localhost_http_public_url_for_local_development(self) -> None:
        """Loopback HTTP remains supported for documented local development."""
        settings = S3Settings(bucket="my-bucket", public_url="http://localhost:9002")

        assert settings.public_url == "http://localhost:9002"


class TestS3SettingsSecrets:
    """Tests for secret handling."""

    def test_access_key_is_secret(self) -> None:
        """Test access_key is SecretStr when provided."""
        settings = S3Settings(bucket="my-bucket", access_key=SecretStr("my-access-key"))
        assert settings.access_key is not None
        assert isinstance(settings.access_key, SecretStr)
        assert settings.access_key.get_secret_value() == "my-access-key"
        assert "my-access-key" not in str(settings.access_key)

    def test_secret_key_is_secret(self) -> None:
        """Test secret_key is SecretStr when provided."""
        settings = S3Settings(bucket="my-bucket", secret_key=SecretStr("my-secret-key"))
        assert settings.secret_key is not None
        assert isinstance(settings.secret_key, SecretStr)
        assert settings.secret_key.get_secret_value() == "my-secret-key"
        assert "my-secret-key" not in str(settings.secret_key)

    def test_secrets_not_exposed_in_repr(self) -> None:
        """Test secrets are not exposed in repr."""
        settings = S3Settings(
            bucket="my-bucket",
            access_key=SecretStr("sensitive-access"),
            secret_key=SecretStr("sensitive-secret"),
        )
        repr_str = repr(settings)
        assert "sensitive-access" not in repr_str
        assert "sensitive-secret" not in repr_str


class TestS3SettingsProductionScenarios:
    """Tests for production-like scenarios."""

    def test_azure_blob_via_s3_api(self) -> None:
        """Test Azure Blob Storage via S3 API."""
        settings = S3Settings(
            endpoint="https://myaccount.blob.core.windows.net",
            access_key=SecretStr("account-name"),
            secret_key=SecretStr("account-key"),
            bucket="mycontainer",
            use_ssl=True,
        )
        assert "blob.core.windows.net" in settings.endpoint
        assert settings.use_ssl is True

    def test_cloudflare_r2(self) -> None:
        """Test Cloudflare R2 configuration."""
        settings = S3Settings(
            endpoint="https://account-id.r2.cloudflarestorage.com",
            access_key=SecretStr("r2-access-key"),
            secret_key=SecretStr("r2-secret-key"),
            bucket="my-r2-bucket",
        )
        assert "r2.cloudflarestorage.com" in settings.endpoint
