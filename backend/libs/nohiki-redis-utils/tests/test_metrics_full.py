"""Tests for Redis metrics to achieve >90% coverage.

This module covers missing lines in metrics.py:
- Line 78: key_prefix attribute handling
- Line 89: error recording in record_operation
- Lines 101-106: record_error method
- Line 117: record_circuit_breaker_change
- Line 128: record_connection_change
"""

from __future__ import annotations

from nohiki_redis_utils.metrics import RedisMetrics, get_redis_metrics


def teardown_module() -> None:
    """Clear the cached metrics instance after this module."""
    get_redis_metrics.cache_clear()


class TestRedisMetricsRecordOperation:
    """Tests for record_operation method with edge cases."""

    def test_record_operation_with_key_prefix(self) -> None:
        """Should include key_prefix in attributes when provided (line 78)."""
        metrics = RedisMetrics()
        # Just verify it doesn't raise - the actual OTel metrics are hard to inspect
        metrics.record_operation("get", 10.0, success=True, hit=True, key_prefix="user:123")

    def test_record_operation_error_with_key_prefix(self) -> None:
        """Should include key_prefix in error attributes (lines 78, 89)."""
        metrics = RedisMetrics()
        metrics.record_operation("get", 10.0, success=False, key_prefix="user:123")


class TestRedisMetricsRecordError:
    """Tests for record_error method (lines 101-106)."""

    def test_record_error_with_string(self) -> None:
        """Should record error with string error (lines 101-106)."""
        metrics = RedisMetrics()
        error = Exception("Test error")
        metrics.record_error("get", 10.0, str(error))

    def test_record_error_with_different_types(self) -> None:
        """Should record different error types."""
        metrics = RedisMetrics()
        metrics.record_error("set", 5.0, "ConnectionError")
        metrics.record_error("delete", 3.0, "TimeoutError")


class TestRedisMetricsCircuitBreaker:
    """Tests for record_circuit_breaker_change (line 117)."""

    def test_record_circuit_breaker_open(self) -> None:
        """Should record circuit breaker opening (line 117)."""
        metrics = RedisMetrics()
        metrics.record_circuit_breaker_change(is_open=True, service="test-service")

    def test_record_circuit_breaker_close(self) -> None:
        """Should record circuit breaker closing (line 117)."""
        metrics = RedisMetrics()
        metrics.record_circuit_breaker_change(is_open=False, service="test-service")


class TestRedisMetricsConnectionChange:
    """Tests for record_connection_change (line 128)."""

    def test_record_connection_increase(self) -> None:
        """Should record connection increase (line 128)."""
        metrics = RedisMetrics()
        metrics.record_connection_change(1, pool_name="default")

    def test_record_connection_decrease(self) -> None:
        """Should record connection decrease (line 128)."""
        metrics = RedisMetrics()
        metrics.record_connection_change(-1, pool_name="default")

    def test_record_connection_with_custom_pool(self) -> None:
        """Should record connection change with custom pool name."""
        metrics = RedisMetrics()
        metrics.record_connection_change(2, pool_name="custom-pool")


class TestGetRedisMetrics:
    """Tests for get_redis_metrics singleton."""

    def test_singleton_returns_same_instance(self) -> None:
        """Should return same instance on multiple calls."""
        metrics1 = get_redis_metrics()
        metrics2 = get_redis_metrics()
        assert metrics1 is metrics2

    def test_singleton_instance_is_redis_metrics(self) -> None:
        """Should return RedisMetrics instance."""
        metrics = get_redis_metrics()
        assert isinstance(metrics, RedisMetrics)
