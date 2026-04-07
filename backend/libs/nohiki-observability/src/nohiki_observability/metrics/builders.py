"""Generic metric builders for domain libraries to extend."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from opentelemetry import metrics as ot_metrics

if TYPE_CHECKING:
    from opentelemetry.metrics import Counter, Histogram, UpDownCounter


@dataclass(frozen=True)
class MetricDefinition:
    """Definition for a metric to be created."""

    name: str
    description: str
    unit: str
    metric_type: str  # "counter", "histogram", "up_down_counter"


class DomainMetricsBase:
    """Base class for domain-specific metrics."""

    def __init__(self, meter_name: str, definitions: list[MetricDefinition]) -> None:
        """Initialize domain metrics."""
        self._meter = ot_metrics.get_meter(meter_name)
        self._instruments: dict[str, object] = {}
        self._create_instruments(definitions)

    def _create_instruments(self, definitions: list[MetricDefinition]) -> None:
        """Create OTel instruments from definitions."""
        for defn in definitions:
            match defn.metric_type:
                case "counter":
                    self._instruments[defn.name] = self._meter.create_counter(
                        name=defn.name, description=defn.description, unit=defn.unit
                    )
                case "histogram":
                    self._instruments[defn.name] = self._meter.create_histogram(
                        name=defn.name, description=defn.description, unit=defn.unit
                    )
                case "up_down_counter":
                    self._instruments[defn.name] = self._meter.create_up_down_counter(
                        name=defn.name, description=defn.description, unit=defn.unit
                    )

    def _get_counter(self, name: str) -> Counter:
        """Get counter instrument with type safety."""
        return cast("Counter", self._instruments[name])

    def _get_histogram(self, name: str) -> Histogram:
        """Get histogram instrument with type safety."""
        return cast("Histogram", self._instruments[name])

    def _get_up_down_counter(self, name: str) -> UpDownCounter:
        """Get up-down counter instrument with type safety."""
        return cast("UpDownCounter", self._instruments[name])
