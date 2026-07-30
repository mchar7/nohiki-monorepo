"""Tests for CheckRunner: dependency ordering, parallelism, gating, and error handling."""

from __future__ import annotations

import asyncio

import pytest
from health_check.core.base import HealthCheck
from health_check.core.exceptions import ConfigurationError, DependencyCycleError
from health_check.core.models import (
    CheckCategory,
    CheckMetadata,
    CheckResult,
    CheckStatus,
    FixResult,
    FixStatus,
)
from health_check.core.runner import CheckRunner
from health_check.platform.models import PlatformTarget
from health_check.platform.protocol import Platform

from ._helpers import MockPlatform, make_metadata


def _make_check(
    check_id: str,
    status: CheckStatus = CheckStatus.PASSED,
    depends_on: frozenset[str] = frozenset(),
    category: CheckCategory = CheckCategory.INFRASTRUCTURE,
) -> HealthCheck:
    """Build a simple check stub that returns the given status."""

    class _Stub(HealthCheck):
        @property
        def metadata(self) -> CheckMetadata:
            return make_metadata(
                check_id=check_id,
                category=category,
                depends_on=depends_on,
                platforms=frozenset({PlatformTarget.COMPOSE}),
            )

        async def execute(self, platform: Platform) -> CheckResult:
            return self._make_result(status, f"result of {check_id}")

    return _Stub()


def _make_crashing_check(check_id: str) -> HealthCheck:
    """Build a check stub that raises an unexpected exception."""

    class _CrashingStub(HealthCheck):
        @property
        def metadata(self) -> CheckMetadata:
            return make_metadata(check_id=check_id, platforms=frozenset({PlatformTarget.COMPOSE}))

        async def execute(self, platform: Platform) -> CheckResult:
            msg = "Unexpected internal failure"
            raise RuntimeError(msg)

    return _CrashingStub()


class _RepairableCheck(HealthCheck):
    def __init__(
        self,
        states: list[CheckStatus],
        action: FixResult | BaseException | None,
        fix_delay: float,
    ) -> None:
        self._states = states
        self._action = action
        self._fix_delay = fix_delay
        self.executions = 0
        self.fixes = 0

    @property
    def metadata(self) -> CheckMetadata:
        return make_metadata(check_id="repairable", platforms=frozenset({PlatformTarget.COMPOSE}))

    @property
    def supports_fix(self) -> bool:
        return True

    @property
    def fix_timeout(self) -> float:
        return 0.01

    async def execute(self, platform: Platform) -> CheckResult:
        status = self._states[min(self.executions, len(self._states) - 1)]
        self.executions += 1
        return self._make_result(status, f"execution {self.executions}")

    async def fix(self, _platform: Platform, _check_result: CheckResult) -> FixResult:
        self.fixes += 1
        if self._fix_delay:
            await asyncio.sleep(self._fix_delay)
        if isinstance(self._action, BaseException):
            raise self._action
        return self._action or FixResult("repairable", FixStatus.SUCCESS, "repaired", action_id="typed.repair")


def _make_repairable_check(
    states: list[CheckStatus],
    *,
    action: FixResult | BaseException | None = None,
    fix_delay: float = 0.0,
) -> _RepairableCheck:
    return _RepairableCheck(states, action, fix_delay)


class TestCheckRunner:
    async def test_single_passing_check(self) -> None:
        platform = MockPlatform()
        runner = CheckRunner([_make_check("a")], platform)
        suite = await runner.run()
        assert suite.passed is True
        assert suite.passed_count == 1

    async def test_single_failing_check(self) -> None:
        platform = MockPlatform()
        runner = CheckRunner([_make_check("a", CheckStatus.FAILED)], platform)
        suite = await runner.run()
        assert suite.passed is False
        assert suite.failed_count == 1

    async def test_dependency_gating_skips_when_dep_fails(self) -> None:
        checks = [
            _make_check("a", CheckStatus.FAILED),
            _make_check("b", depends_on=frozenset({"a"})),
        ]
        platform = MockPlatform()
        suite = await CheckRunner(checks, platform).run()
        results = {r.check_id: r for r in suite.results}
        assert results["b"].status == CheckStatus.SKIPPED

    async def test_dependency_gating_runs_when_dep_passes(self) -> None:
        checks = [
            _make_check("a"),
            _make_check("b", depends_on=frozenset({"a"})),
        ]
        platform = MockPlatform()
        suite = await CheckRunner(checks, platform).run()
        results = {r.check_id: r for r in suite.results}
        assert results["b"].status == CheckStatus.PASSED

    async def test_missing_dependency_fails_closed_before_execution(self) -> None:
        check = _make_check("b", depends_on=frozenset({"nonexistent"}))
        platform = MockPlatform()

        with pytest.raises(ConfigurationError, match="nonexistent"):
            await CheckRunner([check], platform).run()

    async def test_crashing_check_produces_error_status(self) -> None:
        platform = MockPlatform()
        suite = await CheckRunner([_make_crashing_check("x")], platform).run()
        assert suite.results[0].status == CheckStatus.ERROR
        assert "Unexpected internal failure" in (suite.results[0].error or "")

    async def test_timeout_produces_error_status(self) -> None:

        class _SlowCheck(HealthCheck):
            @property
            def metadata(self) -> CheckMetadata:
                return CheckMetadata(
                    check_id="slow",
                    name="Slow",
                    category=CheckCategory.INFRASTRUCTURE,
                    platforms=frozenset({PlatformTarget.COMPOSE}),
                    timeout_seconds=0.01,
                )

            async def execute(self, platform: Platform) -> CheckResult:
                await asyncio.sleep(10)
                return self._make_result(CheckStatus.PASSED, "done")

        platform = MockPlatform()
        suite = await CheckRunner([_SlowCheck()], platform).run()
        assert suite.results[0].status == CheckStatus.ERROR
        assert "Timed out" in suite.results[0].summary

    async def test_on_check_complete_callback_invoked(self) -> None:
        collected: list[CheckResult] = []
        platform = MockPlatform()
        runner = CheckRunner(
            [_make_check("a"), _make_check("b")],
            platform,
            on_check_complete=collected.append,
        )
        await runner.run()
        assert len(collected) == 2
        assert {r.check_id for r in collected} == {"a", "b"}

    async def test_platform_target_property(self) -> None:
        platform = MockPlatform(target=PlatformTarget.KUBERNETES)
        runner = CheckRunner([], platform)
        assert runner.platform_target == PlatformTarget.KUBERNETES

    async def test_cycle_detection_raises(self) -> None:
        checks = [
            _make_check("a", depends_on=frozenset({"b"})),
            _make_check("b", depends_on=frozenset({"a"})),
        ]
        platform = MockPlatform()
        with pytest.raises(DependencyCycleError):
            await CheckRunner(checks, platform).run()

    async def test_multi_tier_ordering(self) -> None:
        """Checks in tier 1 wait for tier 0 to complete."""
        execution_order: list[str] = []

        class _OrderedCheck(HealthCheck):
            def __init__(self, check_id: str, depends_on: frozenset[str]) -> None:
                self._check_id = check_id
                self._depends_on = depends_on

            @property
            def metadata(self) -> CheckMetadata:
                return make_metadata(
                    check_id=self._check_id,
                    depends_on=self._depends_on,
                    platforms=frozenset({PlatformTarget.COMPOSE}),
                )

            async def execute(self, platform: Platform) -> CheckResult:
                execution_order.append(self._check_id)
                return self._make_result(CheckStatus.PASSED, "ok")

        checks = [
            _OrderedCheck("tier0_a", frozenset()),
            _OrderedCheck("tier0_b", frozenset()),
            _OrderedCheck("tier1_c", frozenset({"tier0_a"})),
        ]
        platform = MockPlatform()
        await CheckRunner(checks, platform).run()
        tier1_pos = execution_order.index("tier1_c")
        tier0_a_pos = execution_order.index("tier0_a")
        assert tier1_pos > tier0_a_pos

    async def test_suite_result_duration_is_positive(self) -> None:
        platform = MockPlatform()
        suite = await CheckRunner([_make_check("a")], platform).run()
        assert suite.total_duration_ms >= 0.0

    async def test_empty_check_list(self) -> None:
        platform = MockPlatform()
        suite = await CheckRunner([], platform).run()
        assert suite.passed is True
        assert len(suite.results) == 0

    async def test_default_runner_never_calls_fix(self) -> None:
        check = _make_repairable_check([CheckStatus.FAILED])
        suite = await CheckRunner([check], MockPlatform()).run()
        assert check.fixes == 0
        assert suite.remediations == ()

    async def test_selected_repair_rechecks_and_uses_after_as_final_result(
        self,
    ) -> None:
        check = _make_repairable_check([CheckStatus.FAILED, CheckStatus.PASSED])
        suite = await CheckRunner([check], MockPlatform(), repair_check_ids=frozenset({"repairable"})).run()
        assert check.executions == 2
        assert check.fixes == 1
        assert suite.passed is True
        assert suite.results[0].status == CheckStatus.PASSED
        audit = suite.remediations[0]
        assert audit.before.status == CheckStatus.FAILED
        assert audit.action.action_id == "typed.repair"
        assert audit.after is suite.results[0]

    async def test_action_failure_still_rechecks(self) -> None:
        action = FixResult("repairable", FixStatus.FAILED, "failed")
        check = _make_repairable_check([CheckStatus.FAILED, CheckStatus.PASSED], action=action)
        suite = await CheckRunner([check], MockPlatform(), repair_check_ids=frozenset({"repairable"})).run()
        assert check.executions == 2
        assert suite.passed is True
        assert suite.remediations[0].action.status == FixStatus.FAILED

    async def test_fix_timeout_is_failed_action_and_after_check_still_runs(
        self,
    ) -> None:
        check = _make_repairable_check([CheckStatus.FAILED, CheckStatus.FAILED], fix_delay=1.0)
        suite = await CheckRunner([check], MockPlatform(), repair_check_ids=frozenset({"repairable"})).run()
        assert check.executions == 2
        assert suite.remediations[0].action.status == FixStatus.FAILED
        assert "timed out" in suite.remediations[0].action.summary

    async def test_fix_exception_is_failed_action_and_does_not_cancel_sibling(
        self,
    ) -> None:
        check = _make_repairable_check([CheckStatus.FAILED, CheckStatus.FAILED], action=RuntimeError("boom"))
        sibling = _make_check("sibling")
        suite = await CheckRunner([check, sibling], MockPlatform(), repair_check_ids=frozenset({"repairable"})).run()
        assert {r.check_id: r.status for r in suite.results}["sibling"] == CheckStatus.PASSED
        assert suite.remediations[0].action.status == FixStatus.FAILED
        assert "boom" in (suite.remediations[0].action.error or "")

    async def test_after_result_controls_dependency_gating(self) -> None:
        recovered = _make_repairable_check([CheckStatus.FAILED, CheckStatus.PASSED])
        dependent = _make_check("dependent", depends_on=frozenset({"repairable"}))
        suite = await CheckRunner(
            [recovered, dependent],
            MockPlatform(),
            repair_check_ids=frozenset({"repairable"}),
        ).run()
        assert {r.check_id: r.status for r in suite.results}["dependent"] == CheckStatus.PASSED

        failed = _make_repairable_check([CheckStatus.FAILED, CheckStatus.FAILED])
        suite = await CheckRunner(
            [failed, dependent],
            MockPlatform(),
            repair_check_ids=frozenset({"repairable"}),
        ).run()
        assert {r.check_id: r.status for r in suite.results}["dependent"] == CheckStatus.SKIPPED

    async def test_callback_receives_final_result_once(self) -> None:
        seen: list[CheckResult] = []
        check = _make_repairable_check([CheckStatus.FAILED, CheckStatus.PASSED])
        await CheckRunner(
            [check],
            MockPlatform(),
            repair_check_ids=frozenset({"repairable"}),
            on_check_complete=seen.append,
        ).run()
        assert [result.status for result in seen] == [CheckStatus.PASSED]
