"""Tests for doc_process_service.core.config module."""

import pytest
from doc_process_service.core.config import (
    CacheSettings,
    CircuitBreakerSettings,
    DoclingSettings,
    Settings,
    VLMSettings,
    get_settings,
)
from pydantic import ValidationError


class TestDoclingSettings:
    """Tests for DoclingSettings."""

    def test_default_values(self) -> None:
        """Test default values are set correctly."""
        settings = DoclingSettings()

        assert settings.base_url == "http://docling-serve:5001"
        assert settings.api_key is None
        assert settings.enabled is True
        assert settings.timeout_seconds == 300
        assert settings.max_retries == 3
        assert settings.pipeline == "standard"
        assert settings.pdf_backend == "docling_parse"
        assert settings.ocr_engine == "rapidocr"
        assert settings.table_mode == "accurate"
        assert settings.do_ocr is True
        assert settings.force_ocr is False
        assert settings.do_table_structure is True
        assert settings.include_images is True
        assert settings.do_picture_description is False
        assert settings.poll_interval_seconds == pytest.approx(1.0)
        assert settings.max_poll_attempts == 300

    def test_custom_base_url(self) -> None:
        """Test custom base URL can be set."""
        settings = DoclingSettings(base_url="http://docling:5001")

        assert settings.base_url == "http://docling:5001"


class TestVLMSettings:
    """Tests for VLMSettings."""

    def test_default_values(self) -> None:
        """Test default values are set correctly."""
        settings = VLMSettings()

        assert settings.enabled is False
        assert settings.engine_type == "api_ollama"
        assert settings.api_url == "http://ollama:11434/v1/chat/completions"
        assert settings.api_key is None
        assert settings.model == "qwen3-vl:30b"
        assert settings.timeout_seconds == 180
        assert settings.max_tokens == 4096
        assert settings.temperature == pytest.approx(0.1)
        assert settings.thinking_budget == 1024
        assert settings.headers == {}
        assert settings.extra_params == {}
        assert settings.prompt == "Describe this image in detail."
        assert settings.response_format == "plaintext"
        assert settings.picture_area_threshold == pytest.approx(0.01)

    def test_enabled_vlm(self) -> None:
        """Test enabling VLM settings."""
        settings = VLMSettings(enabled=True, model="llava:13b")

        assert settings.enabled is True
        assert settings.model == "llava:13b"

    def test_thinking_budget_zero(self) -> None:
        """Test thinking_budget=0 disables thinking params."""
        settings = VLMSettings(thinking_budget=0)

        assert settings.thinking_budget == 0

    def test_thinking_budget_rejects_negative(self) -> None:
        """Test thinking_budget rejects negative values."""
        with pytest.raises(ValidationError):
            VLMSettings(thinking_budget=-1)

    def test_api_key_and_headers(self) -> None:
        """Test VLM api_key and custom headers."""
        settings = VLMSettings(
            api_key="sk-test123",
            headers={"X-Custom": "value"},
        )

        assert settings.api_key == "sk-test123"
        assert settings.headers == {"X-Custom": "value"}

    def test_extra_params(self) -> None:
        """Test extra_params for provider-specific API parameters."""
        settings = VLMSettings(
            extra_params={"chat_template_kwargs": {"enable_thinking": False}},
        )

        assert settings.extra_params == {"chat_template_kwargs": {"enable_thinking": False}}


class TestCacheSettings:
    """Tests for CacheSettings."""

    def test_default_values(self) -> None:
        """Test default TTL values (7 days for content)."""
        settings = CacheSettings()

        assert settings.raw_ttl_seconds == 604800
        assert settings.processed_ttl_seconds == 604800
        assert settings.key_prefix == "doc-process"

    def test_custom_prefix(self) -> None:
        """Test custom key prefix."""
        settings = CacheSettings(key_prefix="myapp:doc")

        assert settings.key_prefix == "myapp:doc"


class TestCircuitBreakerSettings:
    """Tests for CircuitBreakerSettings."""

    def test_default_values(self) -> None:
        """Test default values are set correctly."""
        settings = CircuitBreakerSettings()

        assert settings.enabled is True
        assert settings.failure_threshold == 5
        assert settings.success_threshold == 2
        assert settings.timeout_seconds == 30

    def test_disabled_circuit_breaker(self) -> None:
        """Test disabling circuit breaker."""
        settings = CircuitBreakerSettings(enabled=False)

        assert settings.enabled is False


class TestSettings:
    """Tests for Settings root configuration."""

    def test_default_values(self) -> None:
        """Test default values are set correctly."""
        settings = Settings()

        assert settings.service_name == "doc-process-service"
        assert settings.service_version == "0.1.0"
        assert settings.service_name_friendly == "Document Processing Service"

    def test_nested_settings_created(self) -> None:
        """Test nested settings are created with defaults."""
        settings = Settings()

        assert isinstance(settings.docling, DoclingSettings)
        assert isinstance(settings.vlm, VLMSettings)
        assert isinstance(settings.cache, CacheSettings)
        assert isinstance(settings.circuit_breaker, CircuitBreakerSettings)

    def test_kafka_consumer_group(self) -> None:
        """Test kafka_consumer_group property."""
        settings = Settings()

        assert settings.kafka_consumer_group == "doc-process-service-primary"


class TestGetSettings:
    """Tests for get_settings function."""

    def test_returns_settings(self) -> None:
        """Test get_settings returns Settings instance."""
        settings = get_settings()

        assert isinstance(settings, Settings)

    def test_cached(self) -> None:
        """Test get_settings returns cached instance."""
        settings1 = get_settings()
        settings2 = get_settings()

        assert settings1 is settings2
