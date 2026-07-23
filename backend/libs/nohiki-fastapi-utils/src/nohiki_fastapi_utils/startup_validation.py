"""Startup validation utilities for ensuring dependencies are ready before service starts.

Services call validate_startup_dependencies() in their lifespan to fail fast
if critical dependencies are unavailable.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from nohiki_common_exceptions import (
    HealthProbeResult,
    create_unhealthy_result,
)
from nohiki_observability import get_logger

if TYPE_CHECKING:
    from nohiki_common_exceptions import HealthProbe

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ProbeTiming:
    """Timing dependencies for a startup probe retry loop."""

    clock: Callable[[], float] = time.perf_counter
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep


@dataclass(slots=True)
class StartupValidationResult:
    """Result of startup validation."""

    success: bool
    results: list[HealthProbeResult] = field(default_factory=list)
    failed_probes: list[str] = field(default_factory=list)

    def raise_if_failed(self) -> None:
        """Raise RuntimeError if validation failed."""
        if not self.success:
            failed_names = ", ".join(self.failed_probes)
            msg = f"Startup validation failed for: {failed_names}"
            raise RuntimeError(msg)


def _process_probe_result(
    probe_name: str,
    result: HealthProbeResult | BaseException,
    probe_results: list[HealthProbeResult],
    failed_probes: list[str],
) -> None:
    """Process a single probe result and update the result lists."""
    if isinstance(result, BaseException):
        failed_probes.append(probe_name)
        return

    probe_results.append(result)
    if not result.is_healthy():
        failed_probes.append(probe_name)


async def _run_probes(probes: Sequence[HealthProbe]) -> list[HealthProbeResult | BaseException]:
    """Execute all probes concurrently and return results."""
    return await asyncio.gather(
        *[p.check() for p in probes],
        return_exceptions=True,
    )


def _collect_results(
    probes: Sequence[HealthProbe],
    raw_results: Sequence[HealthProbeResult | BaseException],
) -> tuple[list[HealthProbeResult], list[str]]:
    """Collect probe results into success and failure lists."""
    probe_results: list[HealthProbeResult] = []
    failed_probes: list[str] = []

    for probe, result in zip(probes, raw_results, strict=True):
        _process_probe_result(probe.name, result, probe_results, failed_probes)

    return probe_results, failed_probes


async def validate_startup_dependencies(
    probes: Sequence[HealthProbe],
    *,
    timeout_seconds: float = 60.0,
    retry_interval_seconds: float = 2.0,
    fail_fast: bool = True,
    timing: ProbeTiming | None = None,
) -> StartupValidationResult:
    """Validate all startup dependencies are available.

    Runs health probes with retry logic until all pass or timeout is reached.

    Args:
        probes: List of HealthProbe instances to validate.
        timeout_seconds: Maximum time to wait for all probes.
        retry_interval_seconds: Interval between retry attempts.
        fail_fast: If True, raises RuntimeError on failure.
        timing: Optional timing dependencies for deterministic retry control.

    Returns:
        StartupValidationResult with probe results.

    Raises:
        RuntimeError: If fail_fast=True and any probe fails after timeout.

    """
    if not probes:
        return StartupValidationResult(success=True)
    timing = ProbeTiming() if timing is None else timing

    probe_names = [p.name for p in probes]
    logger.info("Validating startup dependencies", probes=probe_names, timeout_seconds=timeout_seconds)

    start_time = timing.clock()

    while (timing.clock() - start_time) < timeout_seconds:
        raw_results = await _run_probes(probes)
        probe_results, failed_probes = _collect_results(probes, raw_results)

        if not failed_probes:
            elapsed = timing.clock() - start_time
            logger.info("All startup dependencies validated", probes=probe_names, elapsed_seconds=round(elapsed, 2))
            return StartupValidationResult(success=True, results=probe_results)

        remaining = timeout_seconds - (timing.clock() - start_time)
        if remaining > 0:
            await timing.sleep(min(retry_interval_seconds, remaining))

    raw_results = await _run_probes(probes)
    probe_results, failed_probes = _collect_results(probes, raw_results)

    elapsed = timing.clock() - start_time
    logger.error("Startup validation failed", failed=failed_probes, elapsed_seconds=round(elapsed, 2))

    validation_result = StartupValidationResult(success=False, results=probe_results, failed_probes=failed_probes)

    if fail_fast:
        validation_result.raise_if_failed()

    return validation_result


def _convert_exception_to_result(probe_name: str, exc: BaseException) -> HealthProbeResult:
    """Convert an exception to an unhealthy probe result."""
    return create_unhealthy_result(
        name=probe_name,
        message=f"Probe raised exception: {exc}",
        latency_ms=0.0,
        details={"error": str(exc), "error_type": type(exc).__name__},
    )


async def run_health_probes(probes: Sequence[HealthProbe]) -> list[HealthProbeResult]:
    """Run all health probes and return results.

    This is the aggregation function used by the health router.

    Args:
        probes: List of HealthProbe instances.

    Returns:
        List of HealthProbeResult from all probes.

    """
    if not probes:
        return []

    raw_results = await _run_probes(probes)

    probe_results: list[HealthProbeResult] = []
    for probe, result in zip(probes, raw_results, strict=True):
        if isinstance(result, HealthProbeResult):
            probe_results.append(result)
        else:
            probe_results.append(_convert_exception_to_result(probe.name, result))

    return probe_results
