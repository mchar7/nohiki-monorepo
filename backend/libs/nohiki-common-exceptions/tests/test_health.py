"""Tests for health probe protocol and types.

Each library that provides access to an external dependency implements
this protocol. Services declare which probes they need, and the health
router aggregates results.
"""

from __future__ import annotations

import pytest
from nohiki_common_exceptions.health import (
    HealthProbeResult,
    HealthProbeTimer,
    HealthStatus,
    create_degraded_result,
    create_healthy_result,
    create_unhealthy_result,
)


class TestHealthStatus:
    """Tests for HealthStatus enum."""

    def test_health_status_values(self) -> None:
        """Verify health status enum values are correct."""
        assert HealthStatus.HEALTHY.value == "healthy"
        assert HealthStatus.DEGRADED.value == "degraded"
        assert HealthStatus.UNHEALTHY.value == "unhealthy"

    def test_health_status_members(self) -> None:
        """Verify all expected enum members exist."""
        assert hasattr(HealthStatus, "HEALTHY")
        assert hasattr(HealthStatus, "DEGRADED")
        assert hasattr(HealthStatus, "UNHEALTHY")


class TestHealthProbeResult:
    """Tests for HealthProbeResult dataclass."""

    def test_create_with_all_fields(self) -> None:
        """Create result with all fields specified."""
        details = {"key": "value", "count": 42}
        result = HealthProbeResult(
            name="test-probe",
            status=HealthStatus.HEALTHY,
            message="All good",
            latency_ms=12.5,
            details=details,
        )

        assert result.name == "test-probe"
        assert result.status == HealthStatus.HEALTHY
        assert result.message == "All good"
        assert result.latency_ms == pytest.approx(12.5)
        assert result.details == details

    def test_create_with_default_details(self) -> None:
        """Create result with default empty details."""
        result = HealthProbeResult(
            name="test-probe",
            status=HealthStatus.HEALTHY,
            message="All good",
            latency_ms=5.0,
        )

        assert result.details == {}

    def test_is_healthy_with_healthy_status(self) -> None:
        """is_healthy returns True for HEALTHY status."""
        result = HealthProbeResult(
            name="test",
            status=HealthStatus.HEALTHY,
            message="OK",
            latency_ms=1.0,
        )

        assert result.is_healthy() is True

    def test_is_healthy_with_degraded_status(self) -> None:
        """is_healthy returns True for DEGRADED status."""
        result = HealthProbeResult(
            name="test",
            status=HealthStatus.DEGRADED,
            message="Slow",
            latency_ms=500.0,
        )

        assert result.is_healthy() is True

    def test_is_healthy_with_unhealthy_status(self) -> None:
        """is_healthy returns False for UNHEALTHY status."""
        result = HealthProbeResult(
            name="test",
            status=HealthStatus.UNHEALTHY,
            message="Failed",
            latency_ms=0.0,
        )

        assert result.is_healthy() is False

    def test_to_dict_with_all_fields(self) -> None:
        """to_dict returns correct dictionary representation."""
        details = {"extra": "data"}
        result = HealthProbeResult(
            name="test-probe",
            status=HealthStatus.DEGRADED,
            message="Degraded performance",
            latency_ms=150.123,
            details=details,
        )

        result_dict = result.to_dict()

        assert result_dict == {
            "name": "test-probe",
            "status": "degraded",
            "message": "Degraded performance",
            "latency_ms": 150.12,
            "healthy": True,
            "details": details,
        }

    def test_to_dict_with_unhealthy_status(self) -> None:
        """to_dict returns healthy=False for UNHEALTHY status."""
        result = HealthProbeResult(
            name="failing-probe",
            status=HealthStatus.UNHEALTHY,
            message="Connection refused",
            latency_ms=0.0,
        )

        result_dict = result.to_dict()

        assert result_dict["status"] == "unhealthy"
        assert result_dict["healthy"] is False

    def test_to_dict_latency_rounding(self) -> None:
        """to_dict rounds latency to 2 decimal places."""
        result = HealthProbeResult(
            name="test",
            status=HealthStatus.HEALTHY,
            message="OK",
            latency_ms=123.456789,
        )

        result_dict = result.to_dict()

        assert result_dict["latency_ms"] == pytest.approx(123.46)


class TestHealthProbeTimer:
    """Tests for HealthProbeTimer context manager."""

    def test_timer_initialization(self) -> None:
        """Timer initializes with zero values."""
        timer = HealthProbeTimer()

        assert timer._start == pytest.approx(0.0)
        assert timer._end == pytest.approx(0.0)
        assert timer.elapsed_ms == pytest.approx(0.0)

    def test_timer_enter_returns_self(self) -> None:
        """__enter__ returns the timer instance."""
        timer = HealthProbeTimer()
        result = timer.__enter__()

        assert result is timer

    def test_timer_enter_sets_start_time(self) -> None:
        """__enter__ sets the start time."""
        timer = HealthProbeTimer()
        timer.__enter__()

        assert timer._start > 0

    def test_timer_exit_sets_end_time(self) -> None:
        """__exit__ sets the end time."""
        timer = HealthProbeTimer()
        timer.__enter__()
        timer.__exit__(None, None, None)

        assert timer._end > 0
        assert timer._end >= timer._start

    def test_timer_elapsed_ms_after_context(self) -> None:
        """elapsed_ms reports the injected clock delta."""
        timestamps = iter((1.0, 1.001))
        timer = HealthProbeTimer(lambda: next(timestamps))

        with timer:
            pass

        assert timer.elapsed_ms == pytest.approx(1.0)

    def test_timer_as_context_manager(self) -> None:
        """Timer works as a context manager."""
        with HealthProbeTimer() as timer:
            assert isinstance(timer, HealthProbeTimer)

        assert timer.elapsed_ms >= 0

    def test_timer_measures_elapsed_time(self) -> None:
        """Timer accurately measures elapsed time."""
        timestamps = iter((10.0, 10.01))

        with HealthProbeTimer(lambda: next(timestamps)) as timer:
            pass

        assert timer.elapsed_ms == pytest.approx(10.0)


class TestCreateHealthyResult:
    """Tests for create_healthy_result helper function."""

    def test_create_healthy_result_basic(self) -> None:
        """Create healthy result with minimal parameters."""
        result = create_healthy_result(
            name="test-probe",
            message="All systems operational",
            latency_ms=5.5,
        )

        assert result.name == "test-probe"
        assert result.status == HealthStatus.HEALTHY
        assert result.message == "All systems operational"
        assert result.latency_ms == pytest.approx(5.5)
        assert result.details == {}

    def test_create_healthy_result_with_details(self) -> None:
        """Create healthy result with custom details."""
        details = {"connections": 10, "uptime_seconds": 3600}
        result = create_healthy_result(
            name="database",
            message="Connected",
            latency_ms=2.0,
            details=details,
        )

        assert result.details == details
        assert result.is_healthy() is True

    def test_create_healthy_result_with_none_details(self) -> None:
        """Create healthy result with None details defaults to empty dict."""
        result = create_healthy_result(
            name="test",
            message="OK",
            latency_ms=1.0,
            details=None,
        )

        assert result.details == {}


class TestCreateDegradedResult:
    """Tests for create_degraded_result helper function."""

    def test_create_degraded_result_basic(self) -> None:
        """Create degraded result with minimal parameters."""
        result = create_degraded_result(
            name="test-probe",
            message="High latency detected",
            latency_ms=150.0,
        )

        assert result.name == "test-probe"
        assert result.status == HealthStatus.DEGRADED
        assert result.message == "High latency detected"
        assert result.latency_ms == pytest.approx(150.0)
        assert result.details == {}

    def test_create_degraded_result_with_details(self) -> None:
        """Create degraded result with custom details."""
        details = {"threshold_ms": 100, "current_ms": 150}
        result = create_degraded_result(
            name="api",
            message="Slow response",
            latency_ms=150.0,
            details=details,
        )

        assert result.details == details
        assert result.is_healthy() is True

    def test_create_degraded_result_with_none_details(self) -> None:
        """Create degraded result with None details defaults to empty dict."""
        result = create_degraded_result(
            name="test",
            message="Slow",
            latency_ms=100.0,
            details=None,
        )

        assert result.details == {}


class TestCreateUnhealthyResult:
    """Tests for create_unhealthy_result helper function."""

    def test_create_unhealthy_result_basic(self) -> None:
        """Create unhealthy result with minimal parameters."""
        result = create_unhealthy_result(
            name="test-probe",
            message="Connection failed",
            latency_ms=0.0,
        )

        assert result.name == "test-probe"
        assert result.status == HealthStatus.UNHEALTHY
        assert result.message == "Connection failed"
        assert result.latency_ms == pytest.approx(0.0)
        assert result.details == {}

    def test_create_unhealthy_result_with_details(self) -> None:
        """Create unhealthy result with custom details."""
        details = {"error": "ECONNREFUSED", "port": 5432}
        result = create_unhealthy_result(
            name="database",
            message="Cannot connect",
            latency_ms=0.0,
            details=details,
        )

        assert result.details == details
        assert result.is_healthy() is False

    def test_create_unhealthy_result_with_none_details(self) -> None:
        """Create unhealthy result with None details defaults to empty dict."""
        result = create_unhealthy_result(
            name="test",
            message="Failed",
            latency_ms=0.0,
            details=None,
        )

        assert result.details == {}


class TestHealthProbeResultEdgeCases:
    """Edge case tests for HealthProbeResult."""

    def test_zero_latency(self) -> None:
        """Handle zero latency correctly."""
        result = HealthProbeResult(
            name="test",
            status=HealthStatus.HEALTHY,
            message="Instant",
            latency_ms=0.0,
        )

        assert result.latency_ms == pytest.approx(0.0)
        assert result.to_dict()["latency_ms"] == pytest.approx(0.0)

    def test_very_high_latency(self) -> None:
        """Handle very high latency values."""
        result = HealthProbeResult(
            name="test",
            status=HealthStatus.DEGRADED,
            message="Timeout",
            latency_ms=999999.999,
        )

        assert result.to_dict()["latency_ms"] == pytest.approx(1000000.0)

    def test_empty_details_dict(self) -> None:
        """Handle explicitly empty details dict."""
        result = HealthProbeResult(
            name="test",
            status=HealthStatus.HEALTHY,
            message="OK",
            latency_ms=1.0,
            details={},
        )

        assert result.details == {}

    def test_nested_details(self) -> None:
        """Handle nested dictionary details."""
        details = {"nested": {"key": "value"}, "list": [1, 2, 3]}
        result = HealthProbeResult(
            name="test",
            status=HealthStatus.HEALTHY,
            message="OK",
            latency_ms=1.0,
            details=details,
        )

        assert result.details == details
        assert result.to_dict()["details"] == details
