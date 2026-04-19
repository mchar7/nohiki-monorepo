"""Unit tests for ml_compute_service.core.config module."""

from __future__ import annotations

from pathlib import Path

import pytest
from ml_compute_service.core.config import (
    ComputeBackendConfig,
    MLComputeCachingSettings,
    ProcessingSettings,
    Settings,
    get_settings,
)


class TestComputeBackendConfig:
    """Tests for ComputeBackendConfig enum."""

    def test_enum_values(self) -> None:
        """Verifies enum has expected values."""
        assert ComputeBackendConfig.CPU.value == "cpu"
        assert ComputeBackendConfig.GPU.value == "gpu"
        assert ComputeBackendConfig.AUTO.value == "auto"

    def test_enum_members(self) -> None:
        """Verifies enum has exactly 3 members."""
        members = list(ComputeBackendConfig)
        assert len(members) == 3

    def test_string_conversion(self) -> None:
        """Verifies StrEnum string conversion works."""
        assert str(ComputeBackendConfig.CPU) == "cpu"
        assert str(ComputeBackendConfig.GPU) == "gpu"
        assert str(ComputeBackendConfig.AUTO) == "auto"


class TestMLComputeCachingSettings:
    """Tests for MLComputeCachingSettings extended model."""

    def test_default_colbert_token_ttl(self) -> None:
        """Verifies ColBERT token TTL defaults to 7 days."""
        caching = MLComputeCachingSettings()

        assert caching.colbert_token_ttl == 604800

    def test_custom_colbert_token_ttl(self) -> None:
        """Verifies ColBERT token TTL can be overridden."""
        caching = MLComputeCachingSettings(colbert_token_ttl=86400)

        assert caching.colbert_token_ttl == 86400

    def test_colbert_token_ttl_must_be_positive(self) -> None:
        """Verifies ColBERT token TTL must be at least 1 second."""
        with pytest.raises(ValueError, match=r"greater than or equal to 1"):
            MLComputeCachingSettings(colbert_token_ttl=0)

    def test_inherits_base_ttl_config(self) -> None:
        """Verifies base CachingSettings TTL config is available."""
        caching = MLComputeCachingSettings()

        assert caching.ttls.short == 300
        assert caching.ttls.medium == 3600
        assert caching.ttls.long == 86400


class TestProcessingSettings:
    """Tests for ProcessingSettings nested model."""

    def test_default_values(self) -> None:
        """Request admission and inference micro-batching have distinct defaults."""
        proc = ProcessingSettings()

        assert proc.max_request_items == 100
        assert proc.inference_batch_size == 8
        assert proc.timeout_seconds == 300
        assert proc.cache_dir == Path("/home/app/.cache")

    def test_default_compute_backend(self) -> None:
        """Verifies default compute backend is CPU."""
        proc = ProcessingSettings()

        assert proc.compute_backend == ComputeBackendConfig.CPU

    def test_custom_values(self) -> None:
        """Verifies micro-batch settings remain configurable with fixed admission."""
        proc = ProcessingSettings(
            max_request_items=100,
            inference_batch_size=16,
            timeout_seconds=600,
            compute_backend=ComputeBackendConfig.GPU,
        )

        assert proc.max_request_items == 100
        assert proc.inference_batch_size == 16
        assert proc.timeout_seconds == 600
        assert proc.compute_backend == ComputeBackendConfig.GPU

    def test_auto_compute_backend(self) -> None:
        """Verifies auto compute backend setting."""
        proc = ProcessingSettings(compute_backend=ComputeBackendConfig.AUTO)

        assert proc.compute_backend == ComputeBackendConfig.AUTO

    @pytest.mark.parametrize(
        ("max_request_items", "error_match"),
        [
            (99, r"greater than or equal to 100"),
            (101, r"less than or equal to 100"),
        ],
    )
    def test_request_admission_limit_is_fixed(
        self,
        max_request_items: int,
        error_match: str,
    ) -> None:
        """Rejects overrides below or above the Kubernetes worker limit."""
        with pytest.raises(ValueError, match=error_match):
            ProcessingSettings(max_request_items=max_request_items)

    @pytest.mark.parametrize("inference_batch_size", [1, 64])
    def test_inference_micro_batch_boundaries_are_configurable(
        self,
        inference_batch_size: int,
    ) -> None:
        """Accepts the independent inference micro-batch boundaries."""
        proc = ProcessingSettings(
            max_request_items=100,
            inference_batch_size=inference_batch_size,
        )

        assert proc.max_request_items == 100
        assert proc.inference_batch_size == inference_batch_size

    @pytest.mark.parametrize(
        ("inference_batch_size", "error_match"),
        [
            (0, r"greater than or equal to 1"),
            (65, r"less than or equal to 64"),
        ],
    )
    def test_inference_micro_batch_size_constraints(
        self,
        inference_batch_size: int,
        error_match: str,
    ) -> None:
        """Rejects inference micro-batches outside the supported range."""
        with pytest.raises(ValueError, match=error_match):
            ProcessingSettings(inference_batch_size=inference_batch_size)


class TestSettings:
    """Tests for Settings class with nested models."""

    def test_default_service_identity(self) -> None:
        """Verifies default service identity values."""
        settings = Settings()

        assert settings.service_name == "ml-compute-service"
        assert settings.service_name_friendly == "ML Compute Worker"
        assert settings.service_version == "0.1.0"
        assert settings.debug is False

    def test_nested_redis_settings(self) -> None:
        """Verifies nested redis settings via RedisMixin."""
        settings = Settings()

        assert "localhost" in str(settings.redis.dsn)
        assert settings.redis_url is not None
        assert "localhost" in settings.redis_url

    def test_nested_kafka_settings(self) -> None:
        """Verifies nested kafka settings via KafkaMixin."""
        settings = Settings()

        assert settings.kafka.bootstrap_servers == "localhost:29092"
        assert settings.kafka.consumer_group == "ml-compute-service"
        assert settings.kafka_consumer_group == "ml-compute-service"

    def test_nested_s3_settings(self) -> None:
        """Verifies nested S3 settings via S3Mixin."""
        settings = Settings()

        assert settings.s3.bucket == "test-bucket"  # From conftest env var
        assert settings.s3_bucket == "test-bucket"

    def test_nested_caching_settings(self) -> None:
        """Verifies nested caching settings with ColBERT TTL."""
        settings = Settings()

        assert settings.caching.colbert_token_ttl == 604800
        assert isinstance(settings.caching, MLComputeCachingSettings)

    def test_nested_processing_settings(self) -> None:
        """Verifies nested processing settings."""
        settings = Settings()

        assert settings.processing.max_request_items == 100
        assert settings.processing.inference_batch_size == 8
        assert settings.processing.timeout_seconds == 300

    def test_observability_defaults(self) -> None:
        """Verifies observability settings defaults."""
        settings = Settings()

        assert settings.observability.logging.level == "INFO"
        assert settings.observability.otel_endpoint == ""


class TestGetSettings:
    """Tests for get_settings function."""

    def test_returns_settings_instance(self) -> None:
        """Returns a Settings instance."""
        get_settings.cache_clear()

        # ML compute worker has no database requirement
        settings = Settings()

        assert isinstance(settings, Settings)

    def test_caching_behavior(self) -> None:
        """Verifies get_settings returns cached instance."""
        get_settings.cache_clear()

        settings1 = get_settings()
        settings2 = get_settings()
        assert settings1 is settings2


class TestGetManifest:
    """Tests for get_manifest function."""

    def test_delegates_to_manifest_cache_with_configured_path(self) -> None:
        """get_manifest loads via the shared cache using this service's manifest_path."""
        from unittest.mock import patch

        from ml_compute_service.core.config import ManifestCache, get_manifest

        get_settings.cache_clear()
        expected_manifest = object()
        expected_path = get_settings().manifest_path
        with patch.object(ManifestCache, "get", return_value=expected_manifest) as mock_get:
            result = get_manifest()

        mock_get.assert_called_once_with(expected_path)
        assert result is expected_manifest
