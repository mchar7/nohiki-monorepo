"""Unit tests for LLM instrumentation module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from nohiki_llm_client.config.settings import LLMInstrumentationSettings
from nohiki_llm_client.observability.instrumentation import (
    _create_tracer_provider,
    create_instrumented_model,
)
from pydantic_ai.models.test import TestModel


class TestCreateTracerProvider:
    """Tests for _create_tracer_provider function."""

    def test_creates_tracer_provider(self) -> None:
        """TracerProvider is created with correct attributes."""
        settings = LLMInstrumentationSettings(
            enabled=True,
            collector_endpoint="http://phoenix:4317",
            project_name="test-project",
            service_name="test-service",
        )

        with patch("nohiki_llm_client.observability.instrumentation.TracerProvider") as mock_tp_cls:
            provider = _create_tracer_provider(settings)
            assert provider is not None
            mock_tp_cls.assert_called_once()

            # Verify span processors were added
            mock_tp_cls.return_value.add_span_processor.assert_called()

    def test_removes_trailing_slash_from_endpoint(self) -> None:
        """Endpoint is forwarded to create_grpc_exporter unchanged (stripping is its responsibility)."""
        settings = LLMInstrumentationSettings(
            collector_endpoint="http://phoenix:4317/",
        )
        with patch("nohiki_llm_client.observability.instrumentation.create_grpc_exporter") as mock_exporter:
            _create_tracer_provider(settings)
            mock_exporter.assert_called_once()
            endpoint_arg = mock_exporter.call_args[0][0]
            assert endpoint_arg == "http://phoenix:4317/"


class TestCreateTracerProviderBatchMode:
    """Tests for _create_tracer_provider span processor selection."""

    def test_uses_simple_processor_when_batch_disabled(self) -> None:
        """SimpleSpanProcessor is used instead of BatchSpanProcessor when batch_export=False."""
        settings = LLMInstrumentationSettings(
            enabled=True,
            collector_endpoint="http://phoenix:4317",
            batch_export=False,
        )

        with (
            patch("nohiki_llm_client.observability.instrumentation.TracerProvider"),
            patch("nohiki_llm_client.observability.instrumentation.create_grpc_exporter"),
            patch("nohiki_llm_client.observability.instrumentation.SimpleSpanProcessor") as mock_simple,
            patch("nohiki_llm_client.observability.instrumentation.BatchSpanProcessor") as mock_batch,
        ):
            _create_tracer_provider(settings)

        mock_simple.assert_called_once()
        mock_batch.assert_not_called()


class TestCreateInstrumentedModel:
    """Tests for create_instrumented_model function."""

    def test_returns_original_model_when_disabled(self) -> None:
        """Returns model unchanged if disabled."""
        model = TestModel()
        settings = LLMInstrumentationSettings(enabled=False)

        result = create_instrumented_model(model, settings)
        assert result is model

    def test_returns_original_model_when_no_endpoint(self) -> None:
        """Returns model unchanged if no endpoint."""
        model = TestModel()
        settings = LLMInstrumentationSettings(enabled=True, collector_endpoint="")

        result = create_instrumented_model(model, settings)
        assert result is model

    def test_wraps_model_when_enabled(self) -> None:
        """Returns instrumented model when enabled."""
        model = TestModel()
        settings = LLMInstrumentationSettings(enabled=True, collector_endpoint="http://phoenix:4317")

        with (
            patch("nohiki_llm_client.observability.instrumentation._create_tracer_provider"),
            patch("nohiki_llm_client.observability.instrumentation.instrument_model") as mock_instrument,
        ):
            mock_instrument.return_value = MagicMock()
            create_instrumented_model(model, settings)
            mock_instrument.assert_called_once()

    def test_handles_exception_gracefully(self) -> None:
        """Returns original model if instrumentation fails."""
        model = TestModel()
        settings = LLMInstrumentationSettings(enabled=True, collector_endpoint="http://phoenix:4317")

        patch_target = "nohiki_llm_client.observability.instrumentation._create_tracer_provider"
        with patch(patch_target, side_effect=RuntimeError("OTEL fail")):
            result = create_instrumented_model(model, settings)
            assert result is model
