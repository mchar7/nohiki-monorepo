"""Regression tests for CI test-runner summaries."""

from __future__ import annotations

import asyncio
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
import typer
import yaml
from ci_checks.checks import tests as test_checks
from ci_checks.checks.tests import (
    CoverageResult,
    _check_exit_conditions,
    display_summary,
    render_github_summary,
)
from ci_checks.checks.tests import (
    TestResult as RunnerTestResult,
)
from ci_checks.core.packages import Package, PackageType
from rich.console import Console

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CHECKS_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "checks.yml"


class _SuccessfulPytestProcess:
    returncode = 0

    def __init__(self, stdout: bytes = b"1 passed\n") -> None:
        self.stdout = asyncio.StreamReader()
        self.stdout.feed_data(stdout)
        self.stdout.feed_eof()
        self.stderr = asyncio.StreamReader()
        self.stderr.feed_eof()

    async def wait(self) -> int:
        return self.returncode

    def kill(self) -> None:
        self.returncode = -9


def _package(tmp_path: Path, name: str = "example") -> Package:
    path = tmp_path / name
    (path / "tests").mkdir(parents=True)
    return Package(name=name, path=path, pkg_type=PackageType.OTHER)


def test_summary_honors_exempt_package_coverage_policy() -> None:
    """An exempt infrastructure package must not make the headline fail."""
    result = RunnerTestResult(
        name="qdrant-init",
        passed=True,
        coverage=CoverageResult(total_coverage=89.0),
        pkg_type=PackageType.OTHER,
    )
    console = Console(record=True, width=120)

    display_summary([result], console, ci_mode=True)

    output = console.export_text()
    assert "COVERAGE: OK" in output
    assert "BELOW THRESHOLD" not in output
    assert not _check_exit_conditions([result], strict=True, with_coverage=True)


def test_github_summary_renders_batch_results_as_markdown() -> None:
    results = [
        RunnerTestResult(
            name="package-b",
            passed=False,
            duration_ms=2345,
            coverage=CoverageResult(total_coverage=78.0),
        ),
        RunnerTestResult(
            name="package-a",
            passed=True,
            duration_ms=1234,
            coverage=CoverageResult(total_coverage=96.0),
        ),
    ]

    summary = render_github_summary(results, "batch-2")

    assert summary.startswith("## Python tests (batch-2)\n\n**1/2 packages passed.**")
    assert "| `package-a` | 1.2s | 96% | Pass |" in summary
    assert "| `package-b` | 2.3s | 78% | Fail |" in summary


@pytest.mark.asyncio
async def test_parallel_runner_syncs_frozen_workspace_once_before_tests(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Package processes start only after one frozen workspace-wide sync."""
    events: list[str] = []
    sync_commands: list[list[str]] = []
    package_args: list[tuple[str, ...]] = []

    def fake_sync_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        del kwargs
        sync_commands.append(command)
        events.append("sync")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    async def fake_package_run(
        pkg: Package,
        markers: str,
        extra_args: tuple[str, ...],
        *,
        with_coverage: bool,
        progress_callback: Callable[[int], None] | None = None,
    ) -> RunnerTestResult:
        del markers, with_coverage, progress_callback
        package_args.append(extra_args)
        events.append(f"pytest:{pkg.name}")
        return RunnerTestResult(name=pkg.name, passed=True, pkg_type=pkg.pkg_type)

    monkeypatch.setattr(test_checks.subprocess, "run", fake_sync_run)
    monkeypatch.setattr(test_checks, "run_package_tests", fake_package_run)
    monkeypatch.setattr(test_checks.os, "process_cpu_count", lambda: 8)

    await test_checks.run_tests_parallel(
        [_package(tmp_path, "first"), _package(tmp_path, "second")],
        "not integration",
        (),
        2,
        Console(record=True),
        ci_mode=True,
        with_coverage=False,
    )

    assert sync_commands == [["uv", "sync", "--all-packages", "--frozen"]]
    assert events[0] == "sync"
    assert set(events[1:]) == {"pytest:first", "pytest:second"}
    assert package_args == [("-n", "4"), ("-n", "4")]


def test_dispatch_order_moves_ci_checks_first_and_preserves_other_order(
    tmp_path: Path,
) -> None:
    packages = [
        _package(tmp_path, "first"),
        _package(tmp_path, "ci-checks"),
        _package(tmp_path, "second"),
    ]

    ordered = test_checks._order_packages_for_dispatch(packages)

    assert [package.name for package in ordered] == ["ci-checks", "first", "second"]


@pytest.mark.asyncio
async def test_interactive_priority_preserves_input_result_order(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    packages = [
        _package(tmp_path, "first"),
        _package(tmp_path, "ci-checks"),
        _package(tmp_path, "second"),
    ]
    starts: list[str] = []

    async def fake_package_run(
        pkg: Package,
        markers: str,
        extra_args: tuple[str, ...],
        *,
        with_coverage: bool,
        progress_callback: Callable[[int], None] | None = None,
    ) -> RunnerTestResult:
        del markers, extra_args, with_coverage, progress_callback
        starts.append(pkg.name)
        return RunnerTestResult(name=pkg.name, passed=True, pkg_type=pkg.pkg_type)

    monkeypatch.setattr(test_checks, "run_package_tests", fake_package_run)
    results = await test_checks._run_tests_interactive(packages, "", (), 1, Console(record=True), with_coverage=False)

    assert starts == ["ci-checks", "first", "second"]
    assert [result.name for result in results] == ["first", "ci-checks", "second"]


@pytest.mark.asyncio
async def test_package_pytest_uv_command_does_not_sync(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The package primitive must preserve orchestrator-supplied pytest arguments."""
    commands: list[tuple[str, ...]] = []

    async def fake_create_subprocess_exec(*command: str, **kwargs: object) -> _SuccessfulPytestProcess:
        del kwargs
        commands.append(command)
        return _SuccessfulPytestProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    result = await test_checks.run_package_tests(_package(tmp_path), "", (), with_coverage=False)

    assert result.passed
    assert len(commands) == 1
    assert commands[0][:5] == ("uv", "run", "--no-sync", "--package", "example")
    assert "-n" not in commands[0]
    assert "--collect-only" not in commands[0]
    assert commands[0].count("pytest") == 1


@pytest.mark.asyncio
async def test_primary_pytest_retains_coverage_without_filtered_fixture_scan(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Filtered package runs leave fixture hygiene to the dedicated gate."""
    package = _package(tmp_path)
    output = (
        b"src/example.py 10 1 90%\n"
        b"TOTAL 10 1 90%\n"
        b"================ UNUSED FIXTURES ================\n"
        b"unused_value -- tests/test_sample.py:3\n"
        b"1 passed\n"
    )
    commands: list[tuple[str, ...]] = []

    async def fake_create_subprocess_exec(*command: str, **kwargs: object) -> _SuccessfulPytestProcess:
        del kwargs
        commands.append(command)
        return _SuccessfulPytestProcess(output)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    result = await test_checks.run_package_tests(package, test_checks._UNIT_TEST_MARKERS, (), with_coverage=True)

    assert result.passed
    assert result.coverage.total_coverage == 90.0
    assert len(commands) == 1
    command = commands[0]
    assert "--cov=src" in command
    assert "--unused-fixtures" not in command
    assert "--unused-fixtures-context" not in command
    assert "--collect-only" not in command


@pytest.mark.asyncio
async def test_integration_run_ignores_unit_fixture_report(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    package = _package(tmp_path)
    output = b"================ UNUSED FIXTURES ================\nunused_value -- tests/test_sample.py:3\n1 passed\n"
    commands: list[tuple[str, ...]] = []

    async def fake_create_subprocess_exec(*command: str, **kwargs: object) -> _SuccessfulPytestProcess:
        del kwargs
        commands.append(command)
        return _SuccessfulPytestProcess(output)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    result = await test_checks.run_package_tests(package, "integration", (), with_coverage=False)

    assert result.passed
    assert len(commands) == 1
    assert "--unused-fixtures" not in commands[0]
    assert commands[0][commands[0].index("-m") + 1] == "integration"


def test_python_batches_use_one_nix_interpreter_and_bounded_workers() -> None:
    """Every matrix batch builds and runs one nix environment with bounded workers."""
    workflow = yaml.safe_load(_CHECKS_WORKFLOW.read_text(encoding="utf-8"))
    python_steps = {step["name"]: step for step in workflow["jobs"]["python-tests"]["steps"] if "name" in step}

    sync = python_steps["Install workspace (all packages + extras)"]
    test = python_steps["Run batch tests"]
    assert "if" not in sync
    assert "if" not in test

    interpreter_pin = 'export UV_PYTHON="$(command -v python)"'
    assert interpreter_pin in sync["run"]
    assert "uv sync --all-packages --all-extras --no-extra cuda --frozen" in sync["run"]
    assert interpreter_pin in test["run"]
    assert '--scope all --packages "${{ matrix.packages }}"' in test["run"]
    assert "--ci --workers 2" in test["run"]
    assert "--lf" not in test["run"]
    assert "--ff" not in test["run"]
    assert '--summary "$GITHUB_STEP_SUMMARY"' in test["run"]

    docker_smoke = next(
        step
        for step in workflow["jobs"]["frontend-smoke"]["steps"]
        if step.get("name") == "Smoke production frontend container"
    )
    assert "pytest scripts/ci/tests" in docker_smoke["run"]
    assert "-m requires_docker" in docker_smoke["run"]
    assert "::" not in docker_smoke["run"]


@pytest.mark.asyncio
async def test_sync_failure_prevents_pytest_spawn_and_reports_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A failed environment sync aborts before any package process is spawned."""
    spawned = False

    def failed_sync(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        del kwargs
        return subprocess.CompletedProcess(
            command,
            17,
            stdout="resolver stdout",
            stderr="frozen lock is stale",
        )

    async def unexpected_spawn(*command: str, **kwargs: object) -> _SuccessfulPytestProcess:
        del command, kwargs
        nonlocal spawned
        spawned = True
        return _SuccessfulPytestProcess()

    monkeypatch.setattr(test_checks.subprocess, "run", failed_sync)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", unexpected_spawn)
    console = Console(record=True)

    with pytest.raises(typer.Exit) as exc_info:
        await test_checks.run_tests_parallel(
            [_package(tmp_path)],
            "not integration",
            (),
            1,
            console,
            ci_mode=True,
            with_coverage=False,
        )

    assert exc_info.value.exit_code == 17
    assert not spawned
    output = console.export_text()
    assert "Failed to synchronize workspace packages" in output
    assert "resolver stdout" in output
    assert "frozen lock is stale" in output
