"""Redis metrics - owned by nohiki-redis-utils."""

from __future__ import annotations

from functools import lru_cache

from opentelemetry import metrics


class RedisMetrics:
    """Redis cache metrics using OpenTelemetry."""

    def __init__(self) -> None:
        """Initialize Redis metrics with OpenTelemetry meter."""
        self._meter = metrics.get_meter("nohiki.redis")

        self.operations = self._meter.create_counter(
            "nohiki_redis_operations_total",
            description="Total Redis operations",
            unit="1",
        )
        self.latency = self._meter.create_histogram(
            "nohiki_redis_operation_duration_seconds",
            description="Redis operation latency",
            unit="s",
        )
        self.hits = self._meter.create_counter(
            "nohiki_redis_cache_hits_total",
            description="Cache hits",
            unit="1",
        )
        self.misses = self._meter.create_counter(
            "nohiki_redis_cache_misses_total",
            description="Cache misses",
            unit="1",
        )
        self.errors = self._meter.create_counter(
            "nohiki_redis_errors_total",
            description="Redis operation errors",
            unit="1",
        )
        self.connections = self._meter.create_up_down_counter(
            "nohiki_redis_connections_active",
            description="Active Redis connections",
            unit="1",
        )
        self.circuit_breaker_state = self._meter.create_up_down_counter(
            "nohiki_redis_circuit_breaker_state",
            description="Circuit breaker state (1=open, 0=closed)",
            unit="1",
        )

    def record_operation(
        self,
        operation: str,
        latency_ms: float,
        *,
        success: bool = True,
        hit: bool | None = None,
        key_prefix: str | None = None,
    ) -> None:
        """Record a Redis operation.

        Args:
            operation: Name of the Redis operation (get, set, delete, etc.)
            latency_ms: Operation latency in milliseconds
            success: Whether the operation succeeded
            hit: Whether it was a cache hit (True), miss (False), or N/A (None)
            key_prefix: Optional key prefix for grouping metrics

        """
        attrs: dict[str, str] = {
            "operation": operation,
            "status": "success" if success else "error",
        }
        if key_prefix:
            attrs["key_prefix"] = key_prefix

        self.operations.add(1, attrs)
        self.latency.record(latency_ms / 1000.0, attrs)

        if hit is True:
            self.hits.add(1, attrs)
        elif hit is False:
            self.misses.add(1, attrs)

        if not success:
            self.errors.add(1, attrs)

    def record_hit(self, operation: str, latency_ms: float) -> None:
        """Record a cache hit operation."""
        self.record_operation(operation, latency_ms, hit=True)

    def record_miss(self, operation: str, latency_ms: float) -> None:
        """Record a cache miss operation."""
        self.record_operation(operation, latency_ms, hit=False)

    def record_error(self, operation: str, latency_ms: float, error: str) -> None:
        """Record a failed operation."""
        attrs: dict[str, str] = {
            "operation": operation,
            "error_type": type(error).__name__,
        }
        self.errors.add(1, attrs)
        self.latency.record(latency_ms / 1000.0, {"operation": operation, "status": "error"})

    def record_circuit_breaker_change(
        self,
        *,
        is_open: bool,
        service: str,
    ) -> None:
        """Record circuit breaker state change."""
        self.circuit_breaker_state.add(
            1 if is_open else -1,
            {"service": service},
        )

    def record_connection_change(
        self,
        delta: int,
        pool_name: str = "default",
    ) -> None:
        """Record connection pool change."""
        self.connections.add(delta, {"pool": pool_name})


@lru_cache(maxsize=1)
def get_redis_metrics() -> RedisMetrics:
    """Get singleton RedisMetrics instance."""
    return RedisMetrics()
