"""Tests for metrics builders module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from nohiki_observability.metrics import DomainMetricsBase, MetricDefinition


class TestMetricDefinition:
    """Tests for MetricDefinition dataclass."""

    def test_create_counter_definition(self) -> None:
        """MetricDefinition stores counter definition."""
        defn = MetricDefinition(
            name="test_counter",
            description="Test counter",
            unit="1",
            metric_type="counter",
        )
        assert defn.name == "test_counter"
        assert defn.description == "Test counter"
        assert defn.unit == "1"
        assert defn.metric_type == "counter"

    def test_create_histogram_definition(self) -> None:
        """MetricDefinition stores histogram definition."""
        defn = MetricDefinition(
            name="test_histogram",
            description="Test histogram",
            unit="s",
            metric_type="histogram",
        )
        assert defn.name == "test_histogram"
        assert defn.metric_type == "histogram"

    def test_is_hashable(self) -> None:
        """MetricDefinition is hashable (frozen dataclass)."""
        defn = MetricDefinition("name", "desc", "1", "counter")
        hash_value = hash(defn)
        assert isinstance(hash_value, int)
        defn_set = {defn}
        assert defn in defn_set


class TestDomainMetricsBase:
    """Tests for DomainMetricsBase class."""

    @pytest.fixture
    def counter_definitions(self) -> list[MetricDefinition]:
        """Create counter definitions."""
        return [
            MetricDefinition("test_total", "Test counter", "1", "counter"),
        ]

    @pytest.fixture
    def histogram_definitions(self) -> list[MetricDefinition]:
        """Create histogram definitions."""
        return [
            MetricDefinition("test_duration", "Test histogram", "s", "histogram"),
        ]

    @pytest.fixture
    def up_down_counter_definitions(self) -> list[MetricDefinition]:
        """Create up-down counter definitions."""
        return [
            MetricDefinition("test_gauge", "Test gauge", "1", "up_down_counter"),
        ]

    def test_init_creates_meter(self, counter_definitions: list[MetricDefinition]) -> None:
        """DomainMetricsBase creates meter with given name."""
        with patch("nohiki_observability.metrics.builders.ot_metrics") as mock_metrics:
            mock_meter = MagicMock()
            mock_metrics.get_meter.return_value = mock_meter

            metrics = DomainMetricsBase("test.meter", counter_definitions)

            mock_metrics.get_meter.assert_called_once_with("test.meter")
            assert metrics._meter == mock_meter

    def test_creates_counter_instruments(self, counter_definitions: list[MetricDefinition]) -> None:
        """DomainMetricsBase creates counter instruments."""
        with patch("nohiki_observability.metrics.builders.ot_metrics") as mock_metrics:
            mock_meter = MagicMock()
            mock_counter = MagicMock()
            mock_meter.create_counter.return_value = mock_counter
            mock_metrics.get_meter.return_value = mock_meter

            metrics = DomainMetricsBase("test.meter", counter_definitions)

            mock_meter.create_counter.assert_called_once_with(
                name="test_total",
                description="Test counter",
                unit="1",
            )
            assert metrics._instruments["test_total"] == mock_counter

    def test_creates_histogram_instruments(self, histogram_definitions: list[MetricDefinition]) -> None:
        """DomainMetricsBase creates histogram instruments."""
        with patch("nohiki_observability.metrics.builders.ot_metrics") as mock_metrics:
            mock_meter = MagicMock()
            mock_histogram = MagicMock()
            mock_meter.create_histogram.return_value = mock_histogram
            mock_metrics.get_meter.return_value = mock_meter

            metrics = DomainMetricsBase("test.meter", histogram_definitions)

            mock_meter.create_histogram.assert_called_once_with(
                name="test_duration",
                description="Test histogram",
                unit="s",
            )
            assert metrics._instruments["test_duration"] == mock_histogram

    def test_creates_up_down_counter_instruments(self, up_down_counter_definitions: list[MetricDefinition]) -> None:
        """DomainMetricsBase creates up-down counter instruments."""
        with patch("nohiki_observability.metrics.builders.ot_metrics") as mock_metrics:
            mock_meter = MagicMock()
            mock_up_down = MagicMock()
            mock_meter.create_up_down_counter.return_value = mock_up_down
            mock_metrics.get_meter.return_value = mock_meter

            metrics = DomainMetricsBase("test.meter", up_down_counter_definitions)

            mock_meter.create_up_down_counter.assert_called_once_with(
                name="test_gauge",
                description="Test gauge",
                unit="1",
            )
            assert metrics._instruments["test_gauge"] == mock_up_down

    def test_get_counter_returns_instrument(self, counter_definitions: list[MetricDefinition]) -> None:
        """_get_counter returns the counter instrument."""
        with patch("nohiki_observability.metrics.builders.ot_metrics") as mock_metrics:
            mock_meter = MagicMock()
            mock_counter = MagicMock()
            mock_meter.create_counter.return_value = mock_counter
            mock_metrics.get_meter.return_value = mock_meter

            metrics = DomainMetricsBase("test.meter", counter_definitions)
            result = metrics._get_counter("test_total")

            assert result == mock_counter

    def test_get_histogram_returns_instrument(self, histogram_definitions: list[MetricDefinition]) -> None:
        """_get_histogram returns the histogram instrument."""
        with patch("nohiki_observability.metrics.builders.ot_metrics") as mock_metrics:
            mock_meter = MagicMock()
            mock_histogram = MagicMock()
            mock_meter.create_histogram.return_value = mock_histogram
            mock_metrics.get_meter.return_value = mock_meter

            metrics = DomainMetricsBase("test.meter", histogram_definitions)
            result = metrics._get_histogram("test_duration")

            assert result == mock_histogram

    def test_get_up_down_counter_returns_instrument(self, up_down_counter_definitions: list[MetricDefinition]) -> None:
        """_get_up_down_counter returns the up-down counter instrument."""
        with patch("nohiki_observability.metrics.builders.ot_metrics") as mock_metrics:
            mock_meter = MagicMock()
            mock_up_down = MagicMock()
            mock_meter.create_up_down_counter.return_value = mock_up_down
            mock_metrics.get_meter.return_value = mock_meter

            metrics = DomainMetricsBase("test.meter", up_down_counter_definitions)
            result = metrics._get_up_down_counter("test_gauge")

            assert result == mock_up_down

    def test_creates_multiple_instruments(self) -> None:
        """DomainMetricsBase creates multiple different instruments."""
        definitions = [
            MetricDefinition("counter1", "Counter 1", "1", "counter"),
            MetricDefinition("histogram1", "Histogram 1", "s", "histogram"),
            MetricDefinition("gauge1", "Gauge 1", "1", "up_down_counter"),
        ]

        with patch("nohiki_observability.metrics.builders.ot_metrics") as mock_metrics:
            mock_meter = MagicMock()
            mock_metrics.get_meter.return_value = mock_meter

            metrics = DomainMetricsBase("test.meter", definitions)

            assert mock_meter.create_counter.call_count == 1
            assert mock_meter.create_histogram.call_count == 1
            assert mock_meter.create_up_down_counter.call_count == 1
            assert len(metrics._instruments) == 3
