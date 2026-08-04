"""Tests for nohiki_s3_client module-level functions."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from collections.abc import Generator

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
def clear_cache() -> Generator[None]:
    """Clear the S3 client cache before and after each test."""
    _s3_client_cache.clear()
    yield
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


@pytest.mark.parametrize("provider", ["s3", "azure_blob"])
def test_provider_sdks_load_only_for_the_selected_backend(provider: str) -> None:
    """Load only the configured provider SDK when object storage is first used."""
    script = textwrap.dedent(
        f"""
        import asyncio
        import sys
        from types import SimpleNamespace

        import nohiki_s3_client

        assert "nohiki_s3_client.client" not in sys.modules
        assert "nohiki_s3_client.health" not in sys.modules
        assert "nohiki_s3_client.metrics" not in sys.modules
        assert not any(name.startswith("azure") for name in sys.modules)
        assert not any(name.startswith(("aiobotocore", "botocore")) for name in sys.modules)

        client_type = nohiki_s3_client.S3Client
        settings = SimpleNamespace(
            provider={provider!r},
            endpoint="https://account.blob.core.windows.net",
            public_url="",
            access_key=None,
            secret_key=None,
            bucket="bucket",
        )
        client = client_type(settings)
        assert not any(name.startswith("azure") for name in sys.modules)
        assert not any(name.startswith(("aiobotocore", "botocore")) for name in sys.modules)

        if {provider!r} == "azure_blob":
            try:
                asyncio.run(client.object_exists(""))
            except ValueError:
                pass
            assert any(name.startswith("azure") for name in sys.modules)
            assert not any(name.startswith(("aiobotocore", "botocore")) for name in sys.modules)
        else:
            client._get_backend()
            assert any(name.startswith("aiobotocore") for name in sys.modules)
            assert not any(name.startswith("azure") for name in sys.modules)

        assert "nohiki_s3_client.health" not in sys.modules
        assert "nohiki_s3_client.metrics" not in sys.modules
        """
    )

    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=False)

    assert result.returncode == 0, result.stderr
