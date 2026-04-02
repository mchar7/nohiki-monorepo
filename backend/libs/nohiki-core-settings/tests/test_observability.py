"""Tests for ObservabilitySettings and nested config classes."""

from __future__ import annotations

import pytest
from nohiki_core_settings import (
    LoggingSettings,
    ObservabilitySettings,
    PrometheusSettings,
    TracingSettings,
)
from pydantic import ValidationError


class TestLoggingSettings:
    """Tests for LoggingSettings class."""

    def test_default_values(self) -> None:
        """Test default logging configuration."""
        settings = LoggingSettings()
        assert settings.level == "INFO"
        assert settings.format == "json"
        assert settings.include_trace_id is True

    def test_all_log_levels(self) -> None:
        """Test all valid log levels."""
        for level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            settings = LoggingSettings(level=level)
            assert settings.level == level

    def test_invalid_log_level(self) -> None:
        """Test invalid log level raises ValidationError."""
        with pytest.raises(ValidationError):
            LoggingSettings.model_validate({"level": "INVALID"})

    def test_all_formats(self) -> None:
        """Test all valid log formats."""
        for fmt in ("json", "console"):
            settings = LoggingSettings(format=fmt)
            assert settings.format == fmt

    def test_invalid_format(self) -> None:
        """Test invalid format raises ValidationError."""
        with pytest.raises(ValidationError):
            LoggingSettings.model_validate({"format": "xml"})

    def test_include_trace_id_disabled(self) -> None:
        """Test trace ID can be disabled."""
        settings = LoggingSettings(include_trace_id=False)
        assert settings.include_trace_id is False


class TestTracingSettings:
    """Tests for TracingSettings class."""

    def test_default_values(self) -> None:
        """Test default tracing configuration."""
        settings = TracingSettings()
        assert settings.enabled is True
        assert settings.sample_rate == pytest.approx(1.0)

    def test_disabled(self) -> None:
        """Test tracing can be disabled."""
        settings = TracingSettings(enabled=False)
        assert settings.enabled is False

    def test_sample_rate_zero(self) -> None:
        """Test zero sample rate (no sampling)."""
        settings = TracingSettings(sample_rate=0.0)
        assert settings.sample_rate == pytest.approx(0.0)

    def test_sample_rate_half(self) -> None:
        """Test 50% sample rate."""
        settings = TracingSettings(sample_rate=0.5)
        assert settings.sample_rate == pytest.approx(0.5)

    def test_sample_rate_full(self) -> None:
        """Test 100% sample rate."""
        settings = TracingSettings(sample_rate=1.0)
        assert settings.sample_rate == pytest.approx(1.0)

    def test_sample_rate_below_zero(self) -> None:
        """Test negative sample rate raises ValidationError."""
        with pytest.raises(ValidationError):
            TracingSettings(sample_rate=-0.1)

    def test_sample_rate_above_one(self) -> None:
        """Test sample rate above 1.0 raises ValidationError."""
        with pytest.raises(ValidationError):
            TracingSettings(sample_rate=1.5)


class TestPrometheusSettings:
    """Tests for PrometheusSettings class."""

    def test_default_values(self) -> None:
        """Test default Prometheus configuration."""
        settings = PrometheusSettings()
        assert settings.enabled is True
        assert settings.endpoint_path == "/metrics"

    def test_disabled(self) -> None:
        """Test Prometheus can be disabled."""
        settings = PrometheusSettings(enabled=False)
        assert settings.enabled is False

    def test_custom_endpoint_path(self) -> None:
        """Test custom endpoint path."""
        settings = PrometheusSettings(endpoint_path="/custom/metrics")
        assert settings.endpoint_path == "/custom/metrics"


class TestObservabilitySettingsOtel:
    """Tests for OTEL settings in ObservabilitySettings."""

    def test_default_otel_values(self) -> None:
        """Test default OTEL configuration."""
        settings = ObservabilitySettings()
        assert settings.otel_endpoint == ""
        assert settings.otel_insecure is True
        assert settings.otel_service_name is None

    def test_custom_otel_endpoint(self) -> None:
        """Test custom OTEL endpoint."""
        settings = ObservabilitySettings(otel_endpoint="http://collector:4317")
        assert settings.otel_endpoint == "http://collector:4317"

    def test_otel_secure_connection(self) -> None:
        """Test OTEL secure (TLS) connection."""
        settings = ObservabilitySettings(otel_insecure=False)
        assert settings.otel_insecure is False

    def test_otel_service_name_override(self) -> None:
        """Test OTEL service name override."""
        settings = ObservabilitySettings(otel_service_name="custom-service")
        assert settings.otel_service_name == "custom-service"


class TestObservabilitySettingsNested:
    """Tests for nested settings in ObservabilitySettings."""

    def test_default_nested_settings(self) -> None:
        """Test default nested settings are created."""
        settings = ObservabilitySettings()

        assert isinstance(settings.logging, LoggingSettings)
        assert isinstance(settings.tracing, TracingSettings)
        assert isinstance(settings.prometheus, PrometheusSettings)

    def test_nested_logging_override(self) -> None:
        """Test overriding nested logging settings."""
        settings = ObservabilitySettings(
            logging=LoggingSettings(level="DEBUG", format="console"),
        )
        assert settings.logging.level == "DEBUG"
        assert settings.logging.format == "console"

    def test_nested_tracing_override(self) -> None:
        """Test overriding nested tracing settings."""
        settings = ObservabilitySettings(
            tracing=TracingSettings(enabled=False, sample_rate=0.5),
        )
        assert settings.tracing.enabled is False
        assert settings.tracing.sample_rate == pytest.approx(0.5)

    def test_nested_prometheus_override(self) -> None:
        """Test overriding nested Prometheus settings."""
        settings = ObservabilitySettings(
            prometheus=PrometheusSettings(enabled=False, endpoint_path="/prom"),
        )
        assert settings.prometheus.enabled is False
        assert settings.prometheus.endpoint_path == "/prom"


class TestObservabilitySettingsProduction:
    """Tests for production-like configurations."""

    def test_production_config(self) -> None:
        """Test production-like configuration."""
        settings = ObservabilitySettings(
            otel_endpoint="http://otel-collector:4317",
            otel_insecure=False,
            otel_service_name="my-service",
            logging=LoggingSettings(level="WARNING", format="json"),
            tracing=TracingSettings(enabled=True, sample_rate=0.1),
            prometheus=PrometheusSettings(enabled=True),
        )

        assert settings.otel_endpoint == "http://otel-collector:4317"
        assert settings.otel_insecure is False
        assert settings.otel_service_name == "my-service"
        assert settings.logging.level == "WARNING"
        assert settings.tracing.sample_rate == pytest.approx(0.1)
        assert settings.prometheus.enabled is True

    def test_development_config(self) -> None:
        """Test development-like configuration."""
        settings = ObservabilitySettings(
            otel_endpoint="",
            logging=LoggingSettings(level="DEBUG", format="console"),
            tracing=TracingSettings(enabled=False),
            prometheus=PrometheusSettings(enabled=False),
        )

        assert settings.otel_endpoint == ""
        assert settings.logging.level == "DEBUG"
        assert settings.logging.format == "console"
        assert settings.tracing.enabled is False
        assert settings.prometheus.enabled is False


class TestObservabilitySettingsModelValidate:
    """Tests for model_validate with dict input."""

    def test_from_dict_flat(self) -> None:
        """Test creating settings from flat dict."""
        data = {
            "otel_endpoint": "http://collector:4317",
            "otel_insecure": False,
        }
        settings = ObservabilitySettings.model_validate(data)
        assert settings.otel_endpoint == "http://collector:4317"
        assert settings.otel_insecure is False

    def test_from_dict_nested(self) -> None:
        """Test creating settings from nested dict."""
        data = {
            "logging": {"level": "DEBUG", "format": "console"},
            "tracing": {"enabled": False, "sample_rate": 0.5},
            "prometheus": {"enabled": True, "endpoint_path": "/metrics"},
        }
        settings = ObservabilitySettings.model_validate(data)

        assert settings.logging.level == "DEBUG"
        assert settings.logging.format == "console"
        assert settings.tracing.enabled is False
        assert settings.tracing.sample_rate == pytest.approx(0.5)
        assert settings.prometheus.enabled is True

    def test_invalid_nested_logging(self) -> None:
        """Test invalid nested logging raises ValidationError."""
        data = {"logging": {"level": "INVALID"}}
        with pytest.raises(ValidationError):
            ObservabilitySettings.model_validate(data)

    def test_invalid_nested_tracing(self) -> None:
        """Test invalid nested tracing raises ValidationError."""
        data = {"tracing": {"sample_rate": 2.0}}
        with pytest.raises(ValidationError):
            ObservabilitySettings.model_validate(data)
