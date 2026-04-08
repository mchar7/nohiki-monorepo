"""Tests for nohiki_s3_client module-level functions."""

from __future__ import annotations

import pytest
from nohiki_s3_client import S3Client, S3Settings, _s3_client_cache, get_s3_client
from pydantic import SecretStr


@pytest.fixture
def s3_settings() -> S3Settings:
    """Create S3Settings for testing."""
    return S3Settings(
        endpoint="http://localhost:9000",
        access_key=SecretStr("test-access-key"),
        secret_key=SecretStr("test-secret-key"),
        bucket="test-bucket",
        region="us-east-1",
        connect_timeout=10,
        read_timeout=30,
    )


@pytest.fixture(autouse=True)
def clear_cache() -> None:
    """Clear the S3 client cache before each test."""
    _s3_client_cache.clear()


class TestGetS3Client:
    """Tests for get_s3_client factory function."""

    def test_get_s3_client_creates_client(self, s3_settings: S3Settings) -> None:
        """Test that get_s3_client creates an S3Client instance."""
        client = get_s3_client(s3_settings)
        assert isinstance(client, S3Client)

    def test_get_s3_client_caches_by_settings_id(self, s3_settings: S3Settings) -> None:
        """Test that get_s3_client returns cached client for same settings."""
        client1 = get_s3_client(s3_settings)
        client2 = get_s3_client(s3_settings)
        assert client1 is client2

    def test_get_s3_client_different_settings_different_client(self) -> None:
        """Test that different settings create different clients."""
        settings1 = S3Settings(
            endpoint="http://localhost:9000",
            access_key=SecretStr("key1"),
            secret_key=SecretStr("secret1"),
            bucket="bucket1",
            region="us-east-1",
        )
        settings2 = S3Settings(
            endpoint="http://localhost:9001",
            access_key=SecretStr("key2"),
            secret_key=SecretStr("secret2"),
            bucket="bucket2",
            region="us-west-2",
        )
        client1 = get_s3_client(settings1)
        client2 = get_s3_client(settings2)
        assert client1 is not client2
