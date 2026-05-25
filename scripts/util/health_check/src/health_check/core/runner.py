"""Dependency-ordered, parallel health check execution engine."""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import time
import traceback
from collections import defaultdict
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

from health_check.core.exceptions import ConfigurationError, DependencyCycleError
from health_check.core.models import (
    CheckResult,
    CheckStatus,
    CheckSuiteResult,
    FixResult,
    FixStatus,
    RemediationResult,
)
from health_check.platform.models import PlatformTarget

if TYPE_CHECKING:
    from health_check.core.base import HealthCheck
    from health_check.platform.protocol import Platform


class CheckRunner:
    """Orchestrates health check execution with dependency ordering and parallelism.

    Execution algorithm:
    1. Filter checks by platform applicability.
    2. Build a dependency graph from each check's ``metadata.depends_on``.
    3. Topological sort into tiers using Kahn's algorithm.
    4. Execute each tier in parallel via ``asyncio.TaskGroup``.
    5. Gate each check on its dependencies: if any dependency did not pass,
       the check is returned as ``SKIPPED`` without executing.
    6. Apply per-check timeouts via ``asyncio.wait_for``.
    7. Catch unexpected exceptions and return them as ``ERROR`` results.

    Args:
        checks: Ordered collection of check instances to execute.
        platform: Deployment platform to run checks against.
        on_check_complete: Optional callback invoked after each check finishes,
            used by the CLI display layer to update the progress bar in real time.
    """

    def __init__(
        self,
        checks: Sequence[HealthCheck],
        platform: Platform,
        *,
        on_check_complete: Callable[[CheckResult], None] | None = None,
        repair_check_ids: frozenset[str] = frozenset(),
    ) -> None:
        """Initialise the runner with a check list and target platform."""
        self._checks = list(checks)
        self._platform = platform
        self._on_check_complete = on_check_complete
        self._repair_check_ids = repair_check_ids
        self._repair_lock = asyncio.Lock()
        self._remediations: list[RemediationResult] = []

    async def run(self) -> CheckSuiteResult:
        """Execute all checks and return aggregated results.

        Returns:
            ``CheckSuiteResult`` with all individual results and total duration.

        Raises:
            DependencyCycleError: If a circular dependency is detected.
        """
        suite_start = time.monotonic()
        all_results: list[CheckResult] = []
        passed_ids: set[str] = set()
        known_ids: frozenset[str] = frozenset(c.metadata.check_id for c in self._checks)

        tiers = self._build_tiers()
        for tier in tiers:
            tier_results = await self._run_tier(tier, passed_ids, known_ids)
            all_results.extend(tier_results)
            passed_ids.update(r.check_id for r in tier_results if r.passed)

        return CheckSuiteResult(
            results=tuple(all_results),
            total_duration_ms=(time.monotonic() - suite_start) * 1000.0,
            platform=self._platform.target,
            remediations=tuple(self._remediations),
        )

    def _build_tiers(self) -> list[list[HealthCheck]]:
        """Topologically sort checks into parallel execution tiers.

        Uses Kahn's algorithm. Checks in the same tier have no dependencies
        on each other and can run concurrently.

        Returns:
            Ordered list of tiers, each containing checks safe to run in parallel.

        Raises:
            DependencyCycleError: If a circular dependency is detected.
        """
        by_id: dict[str, HealthCheck] = {c.metadata.check_id: c for c in self._checks}
        missing = {
            dependency for check in self._checks for dependency in check.metadata.depends_on if dependency not in by_id
        }
        if missing:
            message = f"Scheduled checks have missing dependencies: {sorted(missing)}"
            raise ConfigurationError(message)
        in_degree: dict[str, int] = dict.fromkeys(by_id, 0)
        dependents: defaultdict[str, list[str]] = defaultdict(list)

        for check in self._checks:
            for dep in check.metadata.depends_on:
                if dep in by_id:
                    in_degree[check.metadata.check_id] += 1
                    dependents[dep].append(check.metadata.check_id)

        queue = [cid for cid, deg in in_degree.items() if deg == 0]
        tiers: list[list[HealthCheck]] = []

        while queue:
            tier = [by_id[cid] for cid in queue]
            tiers.append(tier)
            next_queue: list[str] = []
            for cid in queue:
                for dependent_id in dependents[cid]:
                    in_degree[dependent_id] -= 1
                    if in_degree[dependent_id] == 0:
                        next_queue.append(dependent_id)
            queue = next_queue

        placed = sum(len(t) for t in tiers)
        if placed != len(self._checks):
            cycle_ids = {cid for cid, deg in in_degree.items() if deg > 0}
            msg = f"Circular dependency detected among checks: {sorted(cycle_ids)}"
            raise DependencyCycleError(msg)

        return tiers

    async def _run_tier(
        self,
        tier: list[HealthCheck],
        passed_ids: set[str],
        known_ids: frozenset[str],
    ) -> list[CheckResult]:
        """Run all checks in a tier concurrently.

        Args:
            tier: Checks to execute in parallel.
            passed_ids: Set of check IDs that have already passed.
            known_ids: All check IDs scheduled for this run.

        Returns:
            Results for all checks in this tier.
        """
        if not tier:
            return []

        async with asyncio.TaskGroup() as tg:
            tasks = [tg.create_task(self._run_check(check, passed_ids, known_ids)) for check in tier]

        outcomes = [task.result() for task in tasks]
        self._remediations.extend(remediation for _, remediation in outcomes if remediation is not None)
        return [result for result, _ in outcomes]

    async def _run_check(
        self,
        check: HealthCheck,
        passed_ids: set[str],
        known_ids: frozenset[str],
    ) -> tuple[CheckResult, RemediationResult | None]:
        """Execute a single check with dependency gating, timeout, and error handling.

        Only gates on dependencies that were actually scheduled in this run.
        Dependencies not in ``known_ids`` are treated as outside the current scope
        and do not block execution.

        Uses ``asyncio.wait`` + ``Task.exception()`` to capture arbitrary exceptions
        from check implementations without a broad ``except Exception`` clause.

        Args:
            check: The check to execute.
            passed_ids: Set of check IDs that have already passed.
            known_ids: All check IDs scheduled for this run.

        Returns:
            ``CheckResult`` with status, timing, and platform populated.
        """
        for dep_id in check.metadata.depends_on:
            if dep_id in known_ids and dep_id not in passed_ids:
                return (
                    check._make_result(
                        CheckStatus.SKIPPED,
                        f"Skipped: dependency '{dep_id}' did not pass",
                        platform=self._platform.target,
                    ),
                    None,
                )

        before = await self._execute_timed(check)
        remediation: RemediationResult | None = None
        result = before
        if (
            before.status == CheckStatus.FAILED
            and check.metadata.check_id in self._repair_check_ids
            and check.supports_fix
            and self._platform.target in check.fix_platforms
        ):
            async with self._repair_lock:
                action = await self._execute_fix_timed(check, before)
                result = await self._execute_timed(check)
                remediation = RemediationResult(check.metadata.check_id, before, action, result)

        if self._on_check_complete is not None:
            self._on_check_complete(result)

        return result, remediation

    async def _execute_timed(self, check: HealthCheck) -> CheckResult:
        """Execute one check with timing and exception capture.

        Avoids broad ``except Exception`` by using ``asyncio.wait`` and
        ``Task.exception()``. All exception paths populate ``duration_ms``.

        Args:
            check: The check to execute.

        Returns:
            ``CheckResult`` with ``duration_ms`` and ``platform`` always populated.
        """
        start = time.monotonic()
        task: asyncio.Task[CheckResult] = asyncio.create_task(
            check.execute(self._platform),
            name=check.metadata.check_id,
        )
        _, pending = await asyncio.wait({task}, timeout=check.metadata.timeout_seconds)
        duration_ms = (time.monotonic() - start) * 1000.0

        if pending:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            return check._make_result(
                CheckStatus.ERROR,
                f"Timed out after {check.metadata.timeout_seconds:.0f}s",
                remediation_hint="Increase timeout or investigate slow infrastructure",
                duration_ms=duration_ms,
                platform=self._platform.target,
            )

        exc: BaseException | None
        try:
            exc = task.exception()
        except asyncio.CancelledError as cancelled:
            exc = cancelled

        if exc is not None:
            error_text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            return check._make_result(
                CheckStatus.ERROR,
                "Check crashed unexpectedly -- see error details",
                error=error_text,
                remediation_hint="This check crashed unexpectedly. Please file a bug.",
                duration_ms=duration_ms,
                platform=self._platform.target,
            )

        result = task.result()
        return dataclasses.replace(
            result,
            platform=result.platform or self._platform.target,
            duration_ms=result.duration_ms or duration_ms,
        )

    async def _execute_fix_timed(self, check: HealthCheck, before: CheckResult) -> FixResult:
        """Execute one typed fix with its strict deadline and bounded evidence."""
        start = time.monotonic()
        task = asyncio.create_task(check.fix(self._platform, before), name=f"fix:{check.metadata.check_id}")
        _, pending = await asyncio.wait({task}, timeout=check.fix_timeout)
        duration_ms = (time.monotonic() - start) * 1000.0
        if pending:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            return FixResult(
                check_id=check.metadata.check_id,
                status=FixStatus.FAILED,
                summary=f"Remediation timed out after {check.fix_timeout:.0f}s",
                duration_ms=duration_ms,
            )
        try:
            exc = task.exception()
        except asyncio.CancelledError as cancelled:
            exc = cancelled
        if exc is not None:
            return FixResult(
                check_id=check.metadata.check_id,
                status=FixStatus.FAILED,
                summary="Remediation crashed unexpectedly",
                error="".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
                duration_ms=duration_ms,
            )
        result = task.result()
        return dataclasses.replace(result, duration_ms=result.duration_ms or duration_ms)

    @property
    def platform_target(self) -> PlatformTarget:
        """The deployment target this runner operates against."""
        return self._platform.target
