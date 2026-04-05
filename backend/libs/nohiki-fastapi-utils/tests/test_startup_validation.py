"""Tests for startup validation utilities."""

from __future__ import annotations

import asyncio

import pytest
from nohiki_common_exceptions import HealthProbeResult, HealthStatus
from nohiki_fastapi_utils.startup_validation import (
    StartupValidationResult,
    _collect_results,
    _convert_exception_to_result,
    _process_probe_result,
    _run_probes,
    run_health_probes,
    validate_startup_dependencies,
)


class MockHealthProbe:
    """Mock health probe for testing."""

    def __init__(self, name: str, *, healthy: bool = True, raises: Exception | None = None) -> None:
        self.name = name
        self._healthy = healthy
        self._raises = raises

    async def check(self) -> HealthProbeResult:
        event = asyncio.Event()
        event.set()
        await event.wait()
        if self._raises:
            raise self._raises
        return HealthProbeResult(
            name=self.name,
            status=HealthStatus.HEALTHY if self._healthy else HealthStatus.UNHEALTHY,
            message="OK" if self._healthy else "Failed",
            latency_ms=1.0,
        )


class TestStartupValidationResult:
    """Tests for StartupValidationResult."""

    def test_success_does_not_raise(self) -> None:
        """raise_if_failed does nothing when success=True."""
        result = StartupValidationResult(success=True)
        result.raise_if_failed()

    def test_failure_raises_runtime_error(self) -> None:
        """raise_if_failed raises RuntimeError when success=False."""
        result = StartupValidationResult(
            success=False,
            failed_probes=["database", "redis"],
        )
        with pytest.raises(RuntimeError, match="database, redis"):
            result.raise_if_failed()


class TestProcessProbeResult:
    """Tests for _process_probe_result."""

    def test_exception_adds_to_failed(self) -> None:
        """Exceptions are added to failed_probes list."""
        probe_results: list[HealthProbeResult] = []
        failed_probes: list[str] = []

        _process_probe_result(
            "test_probe",
            RuntimeError("Connection failed"),
            probe_results,
            failed_probes,
        )

        assert "test_probe" in failed_probes
        assert len(probe_results) == 0

    def test_healthy_result_not_in_failed(self) -> None:
        """Healthy results are not added to failed_probes."""
        probe_results: list[HealthProbeResult] = []
        failed_probes: list[str] = []

        result = HealthProbeResult(
            name="test",
            status=HealthStatus.HEALTHY,
            message="OK",
            latency_ms=1.0,
        )
        _process_probe_result("test", result, probe_results, failed_probes)

        assert len(failed_probes) == 0
        assert len(probe_results) == 1

    def test_unhealthy_result_in_failed(self) -> None:
        """Unhealthy results are added to failed_probes."""
        probe_results: list[HealthProbeResult] = []
        failed_probes: list[str] = []

        result = HealthProbeResult(
            name="test",
            status=HealthStatus.UNHEALTHY,
            message="Failed",
            latency_ms=1.0,
        )
        _process_probe_result("test", result, probe_results, failed_probes)

        assert "test" in failed_probes
        assert len(probe_results) == 1


class TestRunProbes:
    """Tests for _run_probes."""

    @pytest.mark.asyncio
    async def test_runs_all_probes_concurrently(self) -> None:
        """Runs all probes and returns results."""
        probes = [
            MockHealthProbe("probe1"),
            MockHealthProbe("probe2"),
        ]
        results = await _run_probes(probes)
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_captures_exceptions(self) -> None:
        """Captures exceptions from failing probes."""
        probes = [
            MockHealthProbe("good"),
            MockHealthProbe("bad", raises=RuntimeError("Failed")),
        ]
        results = await _run_probes(probes)
        assert len(results) == 2
        assert isinstance(results[0], HealthProbeResult)
        assert isinstance(results[1], RuntimeError)


class TestCollectResults:
    """Tests for _collect_results."""

    def test_collects_healthy_and_failed(self) -> None:
        """Separates healthy and failed probe results."""
        probes = [MockHealthProbe("good"), MockHealthProbe("bad")]
        raw_results = [
            HealthProbeResult(
                name="good",
                status=HealthStatus.HEALTHY,
                message="OK",
                latency_ms=1.0,
            ),
            HealthProbeResult(
                name="bad",
                status=HealthStatus.UNHEALTHY,
                message="Failed",
                latency_ms=1.0,
            ),
        ]

        probe_results, failed_probes = _collect_results(probes, raw_results)
        assert len(probe_results) == 2
        assert "bad" in failed_probes
        assert "good" not in failed_probes


class TestValidateStartupDependencies:
    """Tests for validate_startup_dependencies."""

    @pytest.mark.asyncio
    async def test_empty_probes_returns_success(self) -> None:
        """Empty probe list returns success."""
        result = await validate_startup_dependencies([])
        assert result.success is True

    @pytest.mark.asyncio
    async def test_all_healthy_returns_success(self) -> None:
        """All healthy probes returns success."""
        probes = [
            MockHealthProbe("db"),
            MockHealthProbe("redis"),
        ]
        result = await validate_startup_dependencies(probes, timeout_seconds=1.0)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_unhealthy_probe_returns_failure(self) -> None:
        """Unhealthy probe returns failure after timeout."""
        probes = [MockHealthProbe("db", healthy=False)]
        result = await validate_startup_dependencies(
            probes,
            timeout_seconds=0.1,
            retry_interval_seconds=0.05,
            fail_fast=False,
        )
        assert result.success is False
        assert "db" in result.failed_probes

    @pytest.mark.asyncio
    async def test_fail_fast_raises(self) -> None:
        """fail_fast=True raises RuntimeError on failure."""
        probes = [MockHealthProbe("db", healthy=False)]
        with pytest.raises(RuntimeError, match="db"):
            await validate_startup_dependencies(
                probes,
                timeout_seconds=0.1,
                retry_interval_seconds=0.05,
                fail_fast=True,
            )


class TestConvertExceptionToResult:
    """Tests for _convert_exception_to_result."""

    def test_converts_exception_to_unhealthy(self) -> None:
        """Converts exception to unhealthy result."""
        exc = RuntimeError("Connection failed")
        result = _convert_exception_to_result("test_probe", exc)

        assert result.name == "test_probe"
        assert result.status == HealthStatus.UNHEALTHY
        assert "Connection failed" in result.message
        assert result.details["error_type"] == "RuntimeError"


class TestRunHealthProbes:
    """Tests for run_health_probes."""

    @pytest.mark.asyncio
    async def test_empty_probes_returns_empty_list(self) -> None:
        """Empty probe list returns empty list."""
        result = await run_health_probes([])
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_all_results(self) -> None:
        """Returns results from all probes."""
        probes = [
            MockHealthProbe("probe1"),
            MockHealthProbe("probe2"),
        ]
        results = await run_health_probes(probes)
        assert len(results) == 2
        assert all(isinstance(r, HealthProbeResult) for r in results)

    @pytest.mark.asyncio
    async def test_converts_exceptions_to_results(self) -> None:
        """Converts exceptions to unhealthy results."""
        probes = [
            MockHealthProbe("good"),
            MockHealthProbe("bad", raises=RuntimeError("Failed")),
        ]
        results = await run_health_probes(probes)
        assert len(results) == 2
        assert results[0].status == HealthStatus.HEALTHY
        assert results[1].status == HealthStatus.UNHEALTHY
