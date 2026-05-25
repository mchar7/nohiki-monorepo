"""Tests for core data models."""

from __future__ import annotations

import pytest
from health_check.core.base import HealthCheck
from health_check.core.models import (
    CheckCategory,
    CheckMetadata,
    CheckResult,
    CheckStatus,
    CheckSuiteResult,
    FixResult,
    FixStatus,
    RemediationResult,
)
from health_check.platform.models import PlatformTarget

from tests.conftest import make_check_result, make_metadata


class TestCheckStatus:
    def test_values_are_strings(self) -> None:
        assert CheckStatus.PASSED == "passed"
        assert CheckStatus.FAILED == "failed"
        assert CheckStatus.SKIPPED == "skipped"
        assert CheckStatus.ERROR == "error"


class TestCheckResult:
    def test_passed_property_true_when_passed(self) -> None:
        r = make_check_result(status=CheckStatus.PASSED)
        assert r.passed is True

    def test_passed_property_false_when_failed(self) -> None:
        r = make_check_result(status=CheckStatus.FAILED)
        assert r.passed is False

    def test_failed_property_true_when_failed(self) -> None:
        r = make_check_result(status=CheckStatus.FAILED)
        assert r.failed is True

    def test_failed_property_true_when_error(self) -> None:
        r = make_check_result(status=CheckStatus.ERROR)
        assert r.failed is True

    def test_failed_property_false_when_passed(self) -> None:
        r = make_check_result(status=CheckStatus.PASSED)
        assert r.failed is False

    def test_failed_property_false_when_skipped(self) -> None:
        r = make_check_result(status=CheckStatus.SKIPPED)
        assert r.failed is False

    def test_is_frozen(self) -> None:
        assert CheckResult.__dataclass_params__.frozen

    def test_defaults(self) -> None:
        r = CheckResult(
            check_id="x",
            name="X",
            category=CheckCategory.INFRASTRUCTURE,
            status=CheckStatus.PASSED,
            summary="ok",
        )
        assert r.details == ()
        assert r.error is None
        assert r.remediation_hint is None
        assert r.duration_ms == 0.0
        assert r.platform is None


class TestCheckSuiteResult:
    def _make_suite(self, statuses: list[CheckStatus]) -> CheckSuiteResult:
        results = tuple(make_check_result(check_id=f"c{i}", status=s) for i, s in enumerate(statuses))
        return CheckSuiteResult(
            results=results,
            total_duration_ms=100.0,
            platform=PlatformTarget.COMPOSE,
        )

    def test_passed_when_all_pass(self) -> None:
        suite = self._make_suite([CheckStatus.PASSED, CheckStatus.PASSED])
        assert suite.passed is True

    def test_passed_when_skipped(self) -> None:
        suite = self._make_suite([CheckStatus.PASSED, CheckStatus.SKIPPED])
        assert suite.passed is True

    def test_not_passed_when_failed(self) -> None:
        suite = self._make_suite([CheckStatus.PASSED, CheckStatus.FAILED])
        assert suite.passed is False

    def test_not_passed_when_error(self) -> None:
        suite = self._make_suite([CheckStatus.PASSED, CheckStatus.ERROR])
        assert suite.passed is False

    def test_passed_count(self) -> None:
        suite = self._make_suite([CheckStatus.PASSED, CheckStatus.FAILED, CheckStatus.SKIPPED])
        assert suite.passed_count == 1

    def test_failed_count(self) -> None:
        suite = self._make_suite([CheckStatus.PASSED, CheckStatus.FAILED, CheckStatus.ERROR])
        assert suite.failed_count == 2

    def test_skipped_count(self) -> None:
        suite = self._make_suite([CheckStatus.SKIPPED, CheckStatus.SKIPPED, CheckStatus.PASSED])
        assert suite.skipped_count == 2

    def test_error_count(self) -> None:
        suite = self._make_suite([CheckStatus.ERROR, CheckStatus.PASSED])
        assert suite.error_count == 1

    def test_empty_suite_passes(self) -> None:
        suite = CheckSuiteResult(results=(), total_duration_ms=0.0, platform=PlatformTarget.COMPOSE)
        assert suite.passed is True


class TestCheckMetadata:
    def test_frozen(self) -> None:
        assert CheckMetadata.__dataclass_params__.frozen

    def test_default_depends_on_is_frozenset(self) -> None:
        meta = make_metadata()
        assert isinstance(meta.depends_on, frozenset)
        assert len(meta.depends_on) == 0

    def test_custom_depends_on(self) -> None:
        meta = make_metadata(depends_on=frozenset({"dep_a", "dep_b"}))
        assert "dep_a" in meta.depends_on


class TestFixResult:
    def test_defaults(self) -> None:
        r = FixResult(check_id="x", status=FixStatus.NOT_SUPPORTED, summary="no fix")
        assert r.details == ()
        assert r.error is None
        assert r.duration_ms == 0.0

    def test_action_id_and_no_action_status(self) -> None:
        result = FixResult("check", FixStatus.NO_ACTION, "already healthy", action_id="typed.action")
        assert result.action_id == "typed.action"
        assert result.status == FixStatus.NO_ACTION


class TestRemediationResult:
    def test_is_frozen_and_preserves_before_action_after(self) -> None:
        import dataclasses

        before = make_check_result(status=CheckStatus.FAILED, summary="before")
        after = make_check_result(status=CheckStatus.PASSED, summary="after")
        action = FixResult("check_0", FixStatus.SUCCESS, "action", action_id="typed.action")
        record = RemediationResult("check_0", before, action, after)
        assert (record.before, record.action, record.after) == (before, action, after)
        with pytest.raises(dataclasses.FrozenInstanceError):
            record.before = after  # type: ignore[misc]

    def test_suite_remediations_default_empty(self) -> None:
        suite = CheckSuiteResult((), 0.0, PlatformTarget.COMPOSE)
        assert suite.remediations == ()


class TestExceptions:
    """Tests for the typed exception hierarchy in core/exceptions.py."""

    def test_health_check_error_stores_message(self) -> None:
        from health_check.core.exceptions import HealthCheckError

        exc = HealthCheckError("base error")
        assert exc.message == "base error"
        assert str(exc) == "base error"

    def test_check_execution_error_stores_check_id(self) -> None:
        from health_check.core.exceptions import CheckExecutionError

        exc = CheckExecutionError("execution failed", check_id="my_check")
        assert exc.check_id == "my_check"
        assert exc.message == "execution failed"

    def test_check_execution_error_is_health_check_error(self) -> None:
        from health_check.core.exceptions import CheckExecutionError, HealthCheckError

        exc = CheckExecutionError("fail", check_id="x")
        assert isinstance(exc, HealthCheckError)

    def test_dependency_cycle_error(self) -> None:
        from health_check.core.exceptions import DependencyCycleError

        exc = DependencyCycleError("cycle: a → b → a")
        assert "cycle" in str(exc)

    def test_platform_error(self) -> None:
        from health_check.core.exceptions import PlatformError

        exc = PlatformError("kubectl not found")
        assert isinstance(exc, Exception)

    def test_runtime_detection_error(self) -> None:
        from health_check.core.exceptions import RuntimeDetectionError

        exc = RuntimeDetectionError("no docker or podman found")
        assert "podman" in str(exc)

    def test_configuration_error(self) -> None:
        from health_check.core.exceptions import ConfigurationError

        exc = ConfigurationError("missing manifest file")
        assert isinstance(exc, Exception)


class TestHealthCheckBase:
    """Tests for HealthCheck ABC concrete method scaffolding."""

    def _make_concrete(self) -> HealthCheck:
        from health_check.platform.models import PlatformTarget
        from health_check.platform.protocol import Platform

        class _Concrete(HealthCheck):
            @property
            def metadata(self) -> CheckMetadata:
                return make_metadata(
                    check_id="concrete",
                    platforms=frozenset({PlatformTarget.COMPOSE}),
                )

            async def execute(self, platform: Platform) -> CheckResult:
                return self._make_result(CheckStatus.PASSED, "ok")

        return _Concrete()

    def test_supports_fix_defaults_false(self) -> None:
        assert self._make_concrete().supports_fix is False

    def test_fix_timeout_default(self) -> None:
        assert self._make_concrete().fix_timeout == 60.0

    def test_fix_platforms_defaults_to_check_platforms(self) -> None:
        check = self._make_concrete()
        assert check.fix_platforms == check.metadata.platforms

    async def test_fix_returns_not_supported(self) -> None:
        from tests.conftest import MockPlatform

        check = self._make_concrete()
        result = await check.fix(MockPlatform(), make_check_result())
        assert result.status == FixStatus.NOT_SUPPORTED

    def test_start_timer_returns_float(self) -> None:
        check = self._make_concrete()
        t = check._start_timer()
        assert isinstance(t, float)

    def test_elapsed_ms_is_non_negative(self) -> None:
        check = self._make_concrete()
        t = check._start_timer()
        elapsed = check._elapsed_ms(t)
        assert elapsed >= 0.0

    def test_make_result_uses_check_category_by_default(self) -> None:
        check = self._make_concrete()
        result = check._make_result(CheckStatus.PASSED, "ok")
        assert result.category == check.metadata.category

    def test_make_result_category_override(self) -> None:
        check = self._make_concrete()
        result = check._make_result(CheckStatus.PASSED, "ok", category=CheckCategory.DATABASE)
        assert result.category == CheckCategory.DATABASE

    def test_make_result_all_fields(self) -> None:
        from health_check.platform.models import PlatformTarget

        check = self._make_concrete()
        result = check._make_result(
            CheckStatus.FAILED,
            "bad thing",
            details=("detail1",),
            error="exc text",
            remediation_hint="do X",
            duration_ms=42.5,
            platform=PlatformTarget.KUBERNETES,
        )
        assert result.check_id == "concrete"
        assert result.summary == "bad thing"
        assert result.details == ("detail1",)
        assert result.error == "exc text"
        assert result.remediation_hint == "do X"
        assert result.duration_ms == 42.5
        assert result.platform == PlatformTarget.KUBERNETES
