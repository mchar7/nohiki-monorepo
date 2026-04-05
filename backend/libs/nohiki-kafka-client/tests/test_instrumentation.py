"""Unit tests for Kafka OpenTelemetry instrumentation."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from nohiki_kafka_client.observability.instrumentation import (
    _is_otel_kafka_available,
    maybe_enable_otel,
)


class TestIsOtelKafkaAvailable:
    """Tests for _is_otel_kafka_available function."""

    @patch("nohiki_kafka_client.observability.instrumentation.importlib.util.find_spec")
    def test_returns_true_when_available(self, mock_find_spec: MagicMock) -> None:
        """Returns True when OTel Kafka instrumentation is available."""
        mock_find_spec.return_value = MagicMock()
        assert _is_otel_kafka_available() is True
        mock_find_spec.assert_called_once_with("opentelemetry.instrumentation.aiokafka")

    @patch("nohiki_kafka_client.observability.instrumentation.importlib.util.find_spec")
    def test_returns_false_when_not_available(self, mock_find_spec: MagicMock) -> None:
        """Returns False when OTel Kafka instrumentation is not available."""
        mock_find_spec.return_value = None
        assert _is_otel_kafka_available() is False


class TestMaybeEnableOtel:
    """Tests for maybe_enable_otel function."""

    def test_does_nothing_when_disabled(self) -> None:
        """Does nothing when enabled=False."""
        maybe_enable_otel(enabled=False)

    @patch("nohiki_kafka_client.observability.instrumentation._is_otel_kafka_available")
    def test_logs_debug_when_not_available(self, mock_available: MagicMock) -> None:
        """Logs debug message when instrumentation not available."""
        mock_available.return_value = False
        maybe_enable_otel(enabled=True)
        mock_available.assert_called_once()

    @patch("nohiki_kafka_client.observability.instrumentation.importlib.import_module")
    @patch("nohiki_kafka_client.observability.instrumentation._is_otel_kafka_available")
    def test_enables_instrumentation_when_available(self, mock_available: MagicMock, mock_import: MagicMock) -> None:
        """Enables instrumentation when available."""
        mock_available.return_value = True
        mock_instrumentor = MagicMock()
        mock_module = MagicMock()
        mock_module.AIOKafkaInstrumentor.return_value = mock_instrumentor
        mock_import.return_value = mock_module

        maybe_enable_otel(enabled=True)

        mock_import.assert_called_once_with("opentelemetry.instrumentation.aiokafka")
        mock_instrumentor.instrument.assert_called_once()

    @patch("nohiki_kafka_client.observability.instrumentation.importlib.import_module")
    @patch("nohiki_kafka_client.observability.instrumentation._is_otel_kafka_available")
    def test_handles_instrumentation_error(self, mock_available: MagicMock, mock_import: MagicMock) -> None:
        """Handles instrumentation errors gracefully."""
        mock_available.return_value = True
        mock_import.side_effect = ImportError("Module not found")

        maybe_enable_otel(enabled=True)
