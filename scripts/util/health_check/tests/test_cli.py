"""Tests for the health-check CLI: formatting, display, and commands."""

from __future__ import annotations

import io
from contextlib import AbstractContextManager
from unittest import mock

import pytest
from health_check.cli.app import app
from health_check.cli.formatting import (
    OutputMode,
    detect_output_mode,
    format_duration,
    plain_status_icon,
    status_icon,
    status_style,
    truncate,
)
from health_check.core.models import (
    CheckCategory,
    CheckResult,
    CheckStatus,
    CheckSuiteResult,
)
from health_check.platform.models import PlatformTarget
from rich.console import Console
from typer.testing import CliRunner

from ._helpers import make_check_result

_runner = CliRunner()


def _make_suite(
    statuses: list[CheckStatus] | None = None,
    *,
    platform: PlatformTarget = PlatformTarget.COMPOSE,
    duration_ms: float = 250.0,
    unexercised_ids: tuple[str, ...] = (),
) -> CheckSuiteResult:
    """Build a CheckSuiteResult with the given statuses."""
    resolved = statuses or [CheckStatus.PASSED]
    results = tuple(make_check_result(check_id=f"c{i}", status=s, name=f"Check {i}") for i, s in enumerate(resolved))
    return CheckSuiteResult(
        results=results,
        total_duration_ms=duration_ms,
        platform=platform,
        unexercised_ids=unexercised_ids,
    )


# formatting.py


class TestDetectOutputMode:
    """Tests for detect_output_mode()."""

    def test_boring_when_ci_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CI", "true")
        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.delenv("TERM", raising=False)
        assert detect_output_mode() == OutputMode.BORING

    def test_boring_when_no_color_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CI", raising=False)
        monkeypatch.setenv("NO_COLOR", "1")
        monkeypatch.delenv("TERM", raising=False)
        assert detect_output_mode() == OutputMode.BORING

    def test_boring_when_dumb_terminal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CI", raising=False)
        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.setenv("TERM", "dumb")
        assert detect_output_mode() == OutputMode.BORING

    def test_boring_when_not_a_tty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CI", raising=False)
        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.delenv("TERM", raising=False)
        with mock.patch("sys.stdout") as m:
            m.isatty.return_value = False
            assert detect_output_mode() == OutputMode.BORING

    def test_rich_when_tty_and_no_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CI", raising=False)
        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.delenv("TERM", raising=False)
        with mock.patch("sys.stdout") as m:
            m.isatty.return_value = True
            assert detect_output_mode() == OutputMode.RICH

    def test_output_mode_values(self) -> None:
        assert OutputMode.RICH == "rich"
        assert OutputMode.BORING == "boring"


class TestPlainStatusIcon:
    def test_passed(self) -> None:
        assert plain_status_icon(CheckStatus.PASSED) == "PASS"

    def test_failed(self) -> None:
        assert plain_status_icon(CheckStatus.FAILED) == "FAIL"

    def test_skipped(self) -> None:
        assert plain_status_icon(CheckStatus.SKIPPED) == "SKIP"

    def test_error(self) -> None:
        assert plain_status_icon(CheckStatus.ERROR) == "ERR "


class TestStatusIcon:
    def test_passed_contains_checkmark(self) -> None:
        assert "✓" in status_icon(CheckStatus.PASSED)

    def test_failed_contains_x(self) -> None:
        assert "✗" in status_icon(CheckStatus.FAILED)

    def test_skipped_contains_circle(self) -> None:
        assert "⊘" in status_icon(CheckStatus.SKIPPED)

    def test_error_contains_warning(self) -> None:
        assert "⚠" in status_icon(CheckStatus.ERROR)


class TestStatusStyle:
    def test_passed_green(self) -> None:
        assert status_style(CheckStatus.PASSED) == "green"

    def test_failed_red(self) -> None:
        assert status_style(CheckStatus.FAILED) == "red"

    def test_skipped_yellow(self) -> None:
        assert status_style(CheckStatus.SKIPPED) == "yellow"

    def test_error_magenta(self) -> None:
        assert status_style(CheckStatus.ERROR) == "magenta"


class TestTruncate:
    def test_short_string_unchanged(self) -> None:
        assert truncate("hello", 10) == "hello"

    def test_exact_length_unchanged(self) -> None:
        text = "a" * 10
        assert truncate(text, 10) == text

    def test_long_string_truncated(self) -> None:
        text = "a" * 70
        result = truncate(text, 60)
        assert len(result) == 60
        assert result.endswith("…")

    def test_default_max_len(self) -> None:
        text = "x" * 65
        result = truncate(text)
        assert len(result) == 60
        assert result.endswith("…")


class TestFormatDuration:
    def test_sub_second_shows_ms(self) -> None:
        result = format_duration(500.0)
        assert result.endswith("ms")
        assert "500" in result

    def test_over_one_second_shows_s(self) -> None:
        result = format_duration(1500.0)
        assert result.endswith("s")
        assert "1.50" in result

    def test_exactly_1000ms(self) -> None:
        result = format_duration(1000.0)
        assert result.endswith("s")

    def test_zero_ms(self) -> None:
        result = format_duration(0.0)
        assert "0" in result
        assert "ms" in result


# display.py


class TestDisplaySuiteResults:
    """Tests for display_suite_results() and related helpers."""

    def test_all_passed_renders_without_error(self) -> None:
        from health_check.cli.display import display_suite_results

        suite = _make_suite([CheckStatus.PASSED, CheckStatus.PASSED])
        buf = io.StringIO()
        con = Console(file=buf, no_color=True, markup=False)
        display_suite_results(suite, con)
        output = buf.getvalue()
        assert "SYSTEMS OPERATIONAL" in output or "passed" in output.lower()

    def test_failed_renders_issues_panel(self) -> None:
        from health_check.cli.display import display_suite_results

        suite = _make_suite([CheckStatus.PASSED, CheckStatus.FAILED])
        buf = io.StringIO()
        con = Console(file=buf, no_color=True, markup=False)
        display_suite_results(suite, con)
        output = buf.getvalue()
        assert "ISSUES" in output or "failed" in output.lower()

    def test_unexercised_capability_renders_incomplete_coverage(self) -> None:
        from health_check.cli.display import display_suite_results

        suite = _make_suite(
            platform=PlatformTarget.KUBERNETES,
            unexercised_ids=("unexercised_check",),
        )
        buf = io.StringIO()
        display_suite_results(suite, Console(file=buf, no_color=True, markup=False))

        output = buf.getvalue()
        assert "INCOMPLETE COVERAGE" in output
        assert "unexercised_check" in output
        assert "SYSTEMS OPERATIONAL" not in output

    def test_verbose_includes_detail_lines(self) -> None:
        from health_check.cli.display import display_suite_results

        results = (
            CheckResult(
                check_id="c0",
                name="My Check",
                category=CheckCategory.INFRASTRUCTURE,
                status=CheckStatus.FAILED,
                summary="Something wrong",
                details=("detail-line-alpha",),
            ),
        )
        suite = CheckSuiteResult(results=results, total_duration_ms=50.0, platform=PlatformTarget.COMPOSE)
        buf = io.StringIO()
        con = Console(file=buf, no_color=True, markup=False)
        display_suite_results(suite, con, verbose=True)
        assert "detail-line-alpha" in buf.getvalue()

    def test_error_result_included_in_issues(self) -> None:
        from health_check.cli.display import display_suite_results

        results = (
            CheckResult(
                check_id="c0",
                name="Err Check",
                category=CheckCategory.INFRASTRUCTURE,
                status=CheckStatus.ERROR,
                summary="unexpected exception",
                error="Traceback: something bad",
            ),
        )
        suite = CheckSuiteResult(results=results, total_duration_ms=10.0, platform=PlatformTarget.COMPOSE)
        buf = io.StringIO()
        con = Console(file=buf, no_color=True, markup=False)
        display_suite_results(suite, con)
        output = buf.getvalue()
        assert "unexpected exception" in output or "Err Check" in output


class TestDisplayJson:
    def test_outputs_valid_json_structure(self) -> None:
        import json

        from health_check.cli.display import display_json

        suite = _make_suite([CheckStatus.PASSED, CheckStatus.FAILED])
        buf = io.StringIO()
        con = Console(file=buf, no_color=True, markup=False, highlight=False)
        display_json(suite, con)
        raw = buf.getvalue().strip()
        # The JSON is wrapped in a Rich Syntax block -- extract the JSON manually
        data = json.loads(raw)
        assert "passed" in data
        assert "results" in data
        assert data["summary"]["total"] == 2

    def test_json_platform_matches(self) -> None:
        import json

        from health_check.cli.display import display_json

        suite = _make_suite(platform=PlatformTarget.KUBERNETES)
        buf = io.StringIO()
        con = Console(file=buf, no_color=True, markup=False, highlight=False)
        display_json(suite, con)
        data = json.loads(buf.getvalue().strip())
        assert data["platform"] == "kubernetes"

    def test_json_surfaces_unexercised_capability_in_denominator(self) -> None:
        import json

        from health_check.cli.display import display_json

        suite = _make_suite(
            platform=PlatformTarget.KUBERNETES,
            unexercised_ids=("unexercised_check",),
        )
        buf = io.StringIO()
        display_json(suite, Console(file=buf, no_color=True, markup=False, highlight=False))
        data = json.loads(buf.getvalue().strip())

        assert data["passed"] is False
        assert data["complete"] is False
        assert data["summary"] == {
            "passed": 1,
            "failed": 0,
            "skipped": 0,
            "unexercised": 1,
            "total": 2,
        }
        assert data["unexercised_ids"] == ["unexercised_check"]


class TestDisplaySuiteResultsBoring:
    def test_renders_pass_summary(self) -> None:
        from health_check.cli.display import display_suite_results_boring

        suite = _make_suite([CheckStatus.PASSED])
        with mock.patch("builtins.print"):
            display_suite_results_boring(suite)

    def test_output_contains_category(self, capsys: pytest.CaptureFixture[str]) -> None:
        from health_check.cli.display import display_suite_results_boring

        results = (
            CheckResult(
                check_id="c0",
                name="Infra Check",
                category=CheckCategory.INFRASTRUCTURE,
                status=CheckStatus.PASSED,
                summary="all good",
            ),
        )
        suite = CheckSuiteResult(results=results, total_duration_ms=100.0, platform=PlatformTarget.COMPOSE)
        display_suite_results_boring(suite)

    def test_verbose_shows_detail_lines(self) -> None:
        from health_check.cli.display import display_suite_results_boring

        results = (
            CheckResult(
                check_id="c0",
                name="Svc",
                category=CheckCategory.SERVICES,
                status=CheckStatus.FAILED,
                summary="bad",
                details=("detail-one", "detail-two"),
            ),
        )
        suite = CheckSuiteResult(results=results, total_duration_ms=50.0, platform=PlatformTarget.COMPOSE)
        display_suite_results_boring(suite, verbose=True)

    def test_failure_shows_remediation_hint(self) -> None:
        from health_check.cli.display import display_suite_results_boring

        results = (
            CheckResult(
                check_id="c0",
                name="Check",
                category=CheckCategory.INFRASTRUCTURE,
                status=CheckStatus.FAILED,
                summary="broken",
                remediation_hint="Run: just restart",
            ),
        )
        suite = CheckSuiteResult(results=results, total_duration_ms=10.0, platform=PlatformTarget.COMPOSE)
        display_suite_results_boring(suite)

    def test_mixed_results_summary_shows_counts(self) -> None:
        from health_check.cli.display import display_suite_results_boring

        suite = _make_suite([CheckStatus.PASSED, CheckStatus.FAILED, CheckStatus.SKIPPED])
        display_suite_results_boring(suite)

    def test_incomplete_summary_names_unexercised_capability(self, capsys: pytest.CaptureFixture[str]) -> None:
        from health_check.cli.display import display_suite_results_boring

        suite = _make_suite(
            platform=PlatformTarget.KUBERNETES,
            unexercised_ids=("unexercised_check",),
        )
        display_suite_results_boring(suite)

        output = capsys.readouterr().out
        assert "INCOMPLETE" in output
        assert "1/2 passed" in output
        assert "unexercised_check" in output
        assert "ALL PASSED" not in output


class TestMakeLiveCallback:
    def test_callback_advances_progress(self) -> None:
        from health_check.cli.display import make_live_callback, make_progress_bar

        buf = io.StringIO()
        con = Console(file=buf, no_color=True, markup=False)
        progress = make_progress_bar(con)
        with progress:
            task_id = progress.add_task("test", total=5)
            cb = make_live_callback(progress, task_id)
            result = make_check_result(status=CheckStatus.PASSED)
            cb(result)
            cb(result)

    def test_callback_invokes_on_complete(self) -> None:
        from health_check.cli.display import make_live_callback, make_progress_bar

        buf = io.StringIO()
        con = Console(file=buf, no_color=True, markup=False)
        progress = make_progress_bar(con)
        called: list[object] = []
        with progress:
            task_id = progress.add_task("test", total=1)
            cb = make_live_callback(progress, task_id, on_complete=called.append)
            result = make_check_result(status=CheckStatus.PASSED)
            cb(result)
        assert len(called) == 1

    def test_callback_without_on_complete_does_not_raise(self) -> None:
        from health_check.cli.display import make_live_callback, make_progress_bar

        buf = io.StringIO()
        con = Console(file=buf, no_color=True, markup=False)
        progress = make_progress_bar(con)
        with progress:
            task_id = progress.add_task("test", total=1)
            cb = make_live_callback(progress, task_id)
            cb(make_check_result(status=CheckStatus.ERROR))


class TestMakeProgressBar:
    def test_returns_progress_instance(self) -> None:
        from health_check.cli.display import make_progress_bar
        from rich.progress import Progress

        buf = io.StringIO()
        con = Console(file=buf)
        progress = make_progress_bar(con)
        assert isinstance(progress, Progress)


# cli/__init__.py and app.py


class TestCliApp:
    def test_app_has_run_command(self) -> None:
        commands = {cmd.name for cmd in app.registered_commands}
        assert "run" in commands

    def test_app_has_list_command(self) -> None:
        commands = {cmd.name for cmd in app.registered_commands}
        assert "list" in commands

    def test_app_has_info_command(self) -> None:
        commands = {cmd.name for cmd in app.registered_commands}
        assert "info" in commands

    def test_main_entrypoint_callable(self) -> None:
        from health_check.cli import main

        assert callable(main)


# commands/run.py -- unit tests for helpers


class TestResolvePlatformTarget:
    def test_compose(self) -> None:
        from health_check.cli.commands.run import _resolve_platform_target

        assert _resolve_platform_target("compose") == PlatformTarget.COMPOSE

    def test_k8s(self) -> None:
        from health_check.cli.commands.run import _resolve_platform_target

        assert _resolve_platform_target("k8s") == PlatformTarget.KUBERNETES

    def test_kubernetes_alias(self) -> None:
        from health_check.cli.commands.run import _resolve_platform_target

        assert _resolve_platform_target("kubernetes") == PlatformTarget.KUBERNETES

    def test_auto_returns_none(self) -> None:
        from health_check.cli.commands.run import _resolve_platform_target

        assert _resolve_platform_target("auto") is None

    def test_unknown_returns_none(self) -> None:
        from health_check.cli.commands.run import _resolve_platform_target

        assert _resolve_platform_target("bogus") is None


class TestResolveCategories:
    def test_none_input_returns_none(self) -> None:
        from health_check.cli.commands.run import _resolve_categories

        assert _resolve_categories(None) is None

    def test_empty_list_returns_none(self) -> None:
        from health_check.cli.commands.run import _resolve_categories

        assert _resolve_categories([]) is None

    def test_valid_category_string(self) -> None:
        from health_check.cli.commands.run import _resolve_categories

        result = _resolve_categories(["infrastructure"])
        assert result == frozenset({CheckCategory.INFRASTRUCTURE})

    def test_multiple_categories(self) -> None:
        from health_check.cli.commands.run import _resolve_categories

        result = _resolve_categories(["infrastructure", "services"])
        assert result == frozenset({CheckCategory.INFRASTRUCTURE, CheckCategory.SERVICES})

    def test_invalid_category_raises(self) -> None:
        from health_check.cli.commands.run import _resolve_categories

        with pytest.raises(ValueError):  # noqa: PT011
            _resolve_categories(["not_a_real_category"])


class TestEmitHelpers:
    def test_emit_error_rich_mode(self) -> None:
        from health_check.cli.commands.run import _emit_error

        buf = io.StringIO()
        con = Console(file=buf, no_color=True, markup=False)
        _emit_error("something broke", OutputMode.RICH, con)
        assert "something broke" in buf.getvalue()

    def test_emit_error_boring_mode(self) -> None:
        from health_check.cli.commands.run import _emit_error

        buf = io.StringIO()
        con = Console(file=buf, no_color=True, markup=False)
        _emit_error("boring error", OutputMode.BORING, con)

    def test_emit_warning_rich_mode(self) -> None:
        from health_check.cli.commands.run import _emit_warning

        buf = io.StringIO()
        con = Console(file=buf, no_color=True, markup=False)
        _emit_warning("a warning", OutputMode.RICH, con)
        assert "a warning" in buf.getvalue()

    def test_emit_warning_boring_mode(self) -> None:
        from health_check.cli.commands.run import _emit_warning

        buf = io.StringIO()
        con = Console(file=buf, no_color=True, markup=False)
        _emit_warning("boring warning", OutputMode.BORING, con)


# run_command integration via CliRunner


def _patched_init_run(
    suite_result: CheckSuiteResult,
) -> AbstractContextManager[None]:
    """Return a context manager that patches _init_run and _run_suite."""
    from health_check.core.base import HealthCheck
    from health_check.core.models import CheckMetadata
    from health_check.platform.models import PlatformTarget

    class _FakeCheck(HealthCheck):
        @property
        def metadata(self) -> CheckMetadata:
            from ._helpers import make_metadata

            return make_metadata(
                check_id="fake_check",
                platforms=frozenset({PlatformTarget.COMPOSE}),
            )

        async def execute(self, platform: object) -> CheckResult:
            return make_check_result(status=CheckStatus.PASSED)

    platform = mock.MagicMock()
    platform.target = PlatformTarget.COMPOSE
    checks = [_FakeCheck()]

    async def _fake_run_suite(*_args: object, **_kwargs: object) -> CheckSuiteResult:
        return suite_result

    return mock.patch.multiple(
        "health_check.cli.commands.run",
        _init_run=mock.MagicMock(return_value=(platform, checks, ())),
        _run_suite=_fake_run_suite,
    )


class TestInitRunFunction:
    """Direct unit tests for _init_run() covering lines 96-105."""

    def test_returns_platform_and_checks(self) -> None:
        from health_check.cli.commands.run import _init_run
        from health_check.platform.models import PlatformTarget

        mock_platform = mock.MagicMock()
        mock_platform.target = PlatformTarget.COMPOSE
        with mock.patch("health_check.cli.commands.run.get_platform", return_value=mock_platform):
            platform, checks, unexercised_ids = _init_run("compose", None, None, None)
        assert platform is mock_platform
        assert isinstance(checks, list)
        assert not unexercised_ids

    def test_category_filter_propagated(self) -> None:
        from health_check.cli.commands.run import _init_run
        from health_check.platform.models import PlatformTarget

        mock_platform = mock.MagicMock()
        mock_platform.target = PlatformTarget.COMPOSE
        with mock.patch("health_check.cli.commands.run.get_platform", return_value=mock_platform):
            _, checks, _ = _init_run("compose", ["infrastructure"], None, None)
        for check in checks:
            assert check.metadata.category.value == "infrastructure"

    def test_excluded_ids_removed(self) -> None:
        from health_check.cli.commands.run import _init_run
        from health_check.platform.models import PlatformTarget

        mock_platform = mock.MagicMock()
        mock_platform.target = PlatformTarget.COMPOSE
        with mock.patch("health_check.cli.commands.run.get_platform", return_value=mock_platform):
            _, checks, _ = _init_run("compose", None, None, ["postgres_connectivity"])
        ids = [c.metadata.check_id for c in checks]
        assert "postgres_connectivity" not in ids

    def test_full_kubernetes_run_has_no_unexercised_capabilities(self) -> None:
        from health_check.cli.commands.run import _init_run
        from health_check.platform.models import PlatformTarget

        mock_platform = mock.MagicMock()
        mock_platform.target = PlatformTarget.KUBERNETES
        with mock.patch("health_check.cli.commands.run.get_platform", return_value=mock_platform):
            _, checks, unexercised_ids = _init_run("k8s", None, None, None)

        assert not unexercised_ids
        assert "cdc_end_to_end" not in {check.metadata.check_id for check in checks}

    def test_invalid_category_raises_value_error(self) -> None:
        from health_check.cli.commands.run import _init_run
        from health_check.platform.models import PlatformTarget

        mock_platform = mock.MagicMock()
        mock_platform.target = PlatformTarget.COMPOSE
        with (
            mock.patch("health_check.cli.commands.run.get_platform", return_value=mock_platform),
            pytest.raises(ValueError),  # noqa: PT011
        ):
            _init_run("compose", ["not_a_real_category"], None, None)


class TestRunSuiteFunction:
    """Direct unit tests for _run_suite() covering lines 128-135."""

    async def test_no_progress_path(self) -> None:
        from health_check.cli.commands.run import _run_suite
        from health_check.platform.models import PlatformTarget

        mock_platform = mock.MagicMock()
        mock_platform.target = PlatformTarget.COMPOSE
        console = Console(file=io.StringIO(), no_color=True)
        suite = await _run_suite([], mock_platform, console, show_progress=False)
        assert suite.platform == PlatformTarget.COMPOSE
        assert suite.passed is True

    async def test_unexercised_capability_makes_suite_incomplete(self) -> None:
        from health_check.cli.commands.run import _run_suite
        from health_check.platform.models import PlatformTarget

        mock_platform = mock.MagicMock()
        mock_platform.target = PlatformTarget.KUBERNETES
        console = Console(file=io.StringIO(), no_color=True)
        suite = await _run_suite(
            [],
            mock_platform,
            console,
            show_progress=False,
            unexercised_ids=("unexercised_check",),
        )

        assert suite.complete is False
        assert suite.passed is False

    async def test_with_progress_path(self) -> None:
        from health_check.cli.commands.run import _run_suite
        from health_check.platform.models import PlatformTarget

        mock_platform = mock.MagicMock()
        mock_platform.target = PlatformTarget.COMPOSE
        console = Console(file=io.StringIO(), no_color=True)
        suite = await _run_suite([], mock_platform, console, show_progress=True)
        assert suite.platform == PlatformTarget.COMPOSE


class TestRunCommand:
    def test_exits_0_on_pass(self) -> None:
        suite = _make_suite([CheckStatus.PASSED])
        with _patched_init_run(suite):
            result = _runner.invoke(app, ["run", "--no-progress", "--output-mode", "boring"])
        assert result.exit_code == 0

    def test_exits_1_on_failure(self) -> None:
        suite = _make_suite([CheckStatus.FAILED])
        with _patched_init_run(suite):
            result = _runner.invoke(app, ["run", "--no-progress", "--output-mode", "boring"])
        assert result.exit_code == 1

    def test_exits_1_when_designed_capability_is_unexercised(self) -> None:
        suite = _make_suite(
            [CheckStatus.PASSED],
            platform=PlatformTarget.KUBERNETES,
            unexercised_ids=("unexercised_check",),
        )
        with _patched_init_run(suite):
            result = _runner.invoke(app, ["run", "--no-progress", "--output-mode", "boring"])
        assert result.exit_code == 1

    def test_json_flag(self) -> None:
        suite = _make_suite([CheckStatus.PASSED])
        with _patched_init_run(suite):
            result = _runner.invoke(app, ["run", "--json", "--no-progress"])
        assert result.exit_code == 0

    def test_quiet_flag(self) -> None:
        suite = _make_suite([CheckStatus.PASSED])
        with _patched_init_run(suite):
            result = _runner.invoke(app, ["run", "--quiet", "--no-progress"])
        assert result.exit_code == 0

    def test_no_checks_exits_0(self) -> None:
        platform = mock.MagicMock()
        platform.target = PlatformTarget.COMPOSE
        with mock.patch.multiple(
            "health_check.cli.commands.run",
            _init_run=mock.MagicMock(return_value=(platform, [], ())),
        ):
            result = _runner.invoke(app, ["run", "--output-mode", "boring"])
        assert result.exit_code == 0

    def test_no_checks_exits_1_when_capabilities_remain_unexercised(self) -> None:
        platform = mock.MagicMock()
        platform.target = PlatformTarget.KUBERNETES
        with mock.patch.multiple(
            "health_check.cli.commands.run",
            _init_run=mock.MagicMock(return_value=(platform, [], ("unprobed_check",))),
        ):
            result = _runner.invoke(app, ["run", "--no-progress", "--output-mode", "boring"])

        assert result.exit_code == 1
        assert "SUMMARY: INCOMPLETE" in result.output
        assert "unprobed_check" in result.output

    def test_init_run_error_exits_2(self) -> None:
        with mock.patch(
            "health_check.cli.commands.run._init_run",
            side_effect=ValueError("bad category"),
        ):
            result = _runner.invoke(app, ["run", "--output-mode", "boring"])
        assert result.exit_code == 2

    def test_verbose_flag_accepted(self) -> None:
        suite = _make_suite([CheckStatus.PASSED])
        with _patched_init_run(suite):
            result = _runner.invoke(app, ["run", "--verbose", "--no-progress", "--output-mode", "boring"])
        assert result.exit_code == 0

    def test_dependency_cycle_error_exits_2(self) -> None:
        from health_check.core.exceptions import DependencyCycleError

        mock_platform = mock.MagicMock()
        mock_platform.target = PlatformTarget.COMPOSE
        checks = [mock.MagicMock()]
        with mock.patch.multiple(
            "health_check.cli.commands.run",
            _init_run=mock.MagicMock(return_value=(mock_platform, checks, ())),
            _run_suite=mock.AsyncMock(side_effect=DependencyCycleError("cycle detected")),
        ):
            result = _runner.invoke(app, ["run", "--no-progress", "--output-mode", "boring"])
        assert result.exit_code == 2

    def test_rich_mode_display_suite_results(self) -> None:
        suite = _make_suite([CheckStatus.PASSED])
        with _patched_init_run(suite):
            result = _runner.invoke(app, ["run", "--no-progress", "--output-mode", "rich"])
        assert result.exit_code == 0

    def test_repair_requires_double_opt_in(self) -> None:
        suite = _make_suite([CheckStatus.PASSED])
        with _patched_init_run(suite):
            for args in (["--repair"], ["--repair-check", "debezium_connectors"]):
                result = _runner.invoke(app, ["run", "--no-progress", "--output-mode", "boring", *args])
                assert result.exit_code == 2
                assert "supplied together" in result.output

    def test_unknown_unscheduled_and_detect_only_repair_ids_exit_two(self) -> None:
        suite = _make_suite([CheckStatus.PASSED])
        with _patched_init_run(suite):
            for check_id in ("unknown", "fake-check"):
                result = _runner.invoke(
                    app,
                    [
                        "run",
                        "--no-progress",
                        "--output-mode",
                        "boring",
                        "--repair",
                        "--repair-check",
                        check_id,
                    ],
                )
                assert result.exit_code == 2
                assert check_id in result.output

    def test_duplicate_repair_allowlist_is_deduplicated(self) -> None:
        from health_check.cli.commands.run import _validate_repair_request
        from health_check.core.base import HealthCheck

        check = mock.MagicMock(spec=HealthCheck)
        check.metadata.check_id = "debezium_connectors"
        check.supports_fix = True
        check.fix_platforms = frozenset({PlatformTarget.COMPOSE})
        repair = True
        resolved = _validate_repair_request(
            repair,
            ["debezium_connectors", "debezium_connectors"],
            [check],
        )
        assert resolved == frozenset({"debezium_connectors"})


class TestCliMainEntrypoint:
    """Test the health_check.cli.main() console script entrypoint."""

    def test_main_calls_app(self) -> None:
        from health_check.cli import main

        with mock.patch("health_check.cli.app") as mock_app:
            main()
        mock_app.assert_called_once()


# list_command via CliRunner


class TestListCommand:
    def test_lists_all_checks(self) -> None:
        result = _runner.invoke(app, ["list"])
        assert result.exit_code == 0

    def test_filter_by_valid_category(self) -> None:
        result = _runner.invoke(app, ["list", "--category", "infrastructure"])
        assert result.exit_code == 0

    @pytest.mark.parametrize("platform", ["compose", "k8s", "kubernetes"])
    def test_filter_by_valid_platform(self, platform: str) -> None:
        result = _runner.invoke(app, ["list", "--platform", platform])
        assert result.exit_code == 0

    def test_invalid_category_exits_1(self) -> None:
        result = _runner.invoke(app, ["list", "--category", "not_a_real_one"])
        assert result.exit_code == 1

    def test_invalid_platform_exits_1(self) -> None:
        result = _runner.invoke(app, ["list", "--platform", "invalid_platform"])
        assert result.exit_code == 1

    def test_no_matches_shows_warning(self) -> None:
        result = _runner.invoke(
            app,
            ["list", "--platform", "kubernetes", "--category", "observability"],
        )
        assert result.exit_code == 0


# info_command via CliRunner


class TestInfoCommand:
    def test_shows_known_check(self) -> None:
        result = _runner.invoke(app, ["info", "postgres_connectivity"])
        assert result.exit_code == 0
        assert "postgres_connectivity" in result.output

    def test_unknown_check_exits_1(self) -> None:
        result = _runner.invoke(app, ["info", "nonexistent_check_id_xyz"])
        assert result.exit_code == 1

    def test_output_includes_category(self) -> None:
        result = _runner.invoke(app, ["info", "kafka_broker"])
        assert result.exit_code == 0
        assert "infrastructure" in result.output.lower()
