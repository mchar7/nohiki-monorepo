"""Provider-level job discovery metrics."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from opentelemetry import metrics


@dataclass(frozen=True, slots=True)
class DiscoveryMetricData:
    """Data for recording a discovery operation."""

    provider: str
    source: str
    duration_seconds: float
    success: bool = True
    listings_found: int = 0
    duplicates: int = 0
    invalid: int = 0
    error_type: str | None = None


class DiscoveryProviderMetrics:
    """Per-provider job discovery metrics for monitoring discovery performance."""

    def __init__(self) -> None:
        """Initialize discovery provider metrics with OTEL meter."""
        self._meter = metrics.get_meter("nohiki.discovery")

        self.discoveries = self._meter.create_counter(
            "nohiki_discovery_operations_total",
            description="Discovery operations by provider and source",
            unit="1",
        )
        self.discovery_duration = self._meter.create_histogram(
            "nohiki_discovery_duration_seconds",
            description="Time to complete a discovery operation",
            unit="s",
        )

        self.jobs_discovered = self._meter.create_counter(
            "nohiki_discovery_jobs_discovered_total",
            description="Jobs discovered per operation",
            unit="1",
        )
        self.jobs_duplicates = self._meter.create_counter(
            "nohiki_discovery_jobs_duplicates_total",
            description="Duplicate jobs filtered out",
            unit="1",
        )
        self.jobs_invalid = self._meter.create_counter(
            "nohiki_discovery_jobs_invalid_total",
            description="Jobs rejected due to validation failures",
            unit="1",
        )

        self.errors = self._meter.create_counter(
            "nohiki_discovery_errors_total",
            description="Discovery errors by type",
            unit="1",
        )
        self.rate_limits = self._meter.create_counter(
            "nohiki_discovery_rate_limits_total",
            description="Rate limit hits from job sources",
            unit="1",
        )
        self.timeouts = self._meter.create_counter(
            "nohiki_discovery_timeouts_total",
            description="Discovery operation timeouts",
            unit="1",
        )

        self.source_availability = self._meter.create_up_down_counter(
            "nohiki_discovery_source_available",
            description="Source availability (1=up, 0=down)",
            unit="1",
        )

    def record_discovery(self, data: DiscoveryMetricData) -> None:
        """Record a discovery operation."""
        attrs: dict[str, str] = {
            "provider": data.provider,
            "source": data.source,
            "status": "success" if data.success else "error",
        }
        if data.error_type:
            attrs["error_type"] = data.error_type

        self.discoveries.add(1, attrs)
        self.discovery_duration.record(data.duration_seconds, attrs)

        if data.listings_found > 0:
            self.jobs_discovered.add(data.listings_found, attrs)
        if data.duplicates > 0:
            self.jobs_duplicates.add(data.duplicates, attrs)
        if data.invalid > 0:
            self.jobs_invalid.add(data.invalid, attrs)

        if not data.success:
            self.errors.add(1, attrs)

    def record_rate_limit(self, provider: str, source: str) -> None:
        """Record a rate limit hit."""
        self.rate_limits.add(1, {"provider": provider, "source": source})

    def record_timeout(self, provider: str, source: str) -> None:
        """Record a timeout."""
        self.timeouts.add(1, {"provider": provider, "source": source})

    def update_source_availability(
        self,
        source: str,
        *,
        is_available: bool,
    ) -> None:
        """Update source availability status."""
        self.source_availability.add(
            1 if is_available else -1,
            {"source": source},
        )


@lru_cache(maxsize=1)
def get_discovery_provider_metrics() -> DiscoveryProviderMetrics:
    """Get singleton DiscoveryProviderMetrics instance."""
    return DiscoveryProviderMetrics()
