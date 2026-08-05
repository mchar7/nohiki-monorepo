"""Regression tests for CI test-runner summaries."""

from __future__ import annotations

import asyncio
import configparser
import json
import subprocess
import tomllib
from pathlib import Path

import pytest
import typer
from _documents import load_mapping, load_workflow, mapping_sequence_at
from ci_checks.checks import tests as test_checks
from ci_checks.checks.tests import (
    CoverageResult,
    FileCoverage,
    _check_exit_conditions,
    _coverage_meets_policy,
    display_summary,
    render_github_summary,
)
from ci_checks.checks.tests import (
    TestResult as RunnerTestResult,
)
from ci_checks.core.packages import Package, PackageType
from rich.console import Console

pytest_plugins = ("pytester",)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CHECKS_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "checks.yml"
_SETUP_CI_ACTION = _REPO_ROOT / ".github" / "actions" / "setup-ci" / "action.yml"


class _SuccessfulPytestProcess:
    def __init__(self, stdout: bytes = b"1 passed\n", *, returncode: int = 0) -> None:
        self.returncode = returncode
        self.stdout = asyncio.StreamReader()
        self.stdout.feed_data(stdout)
        self.stdout.feed_eof()
        self.stderr = asyncio.StreamReader()
        self.stderr.feed_eof()

    async def wait(self) -> int:
        return self.returncode

    async def communicate(self) -> tuple[bytes, bytes]:
        stdout = await self.stdout.read()
        stderr = await self.stderr.read()
        return stdout, stderr

    def kill(self) -> None:
        self.returncode = -9


def _package(tmp_path: Path, name: str = "example") -> Package:
    path = tmp_path / name
    (path / "tests").mkdir(parents=True)
    return Package(name=name, path=path, pkg_type=PackageType.OTHER)


def _write_junit(command: tuple[str, ...], content: str) -> None:
    junit_arg = next(arg for arg in command if arg.startswith("--junitxml="))
    Path(junit_arg.removeprefix("--junitxml=")).write_text(content, encoding="utf-8")


def _write_coverage_json(command: tuple[str, ...], content: str) -> None:
    report_arg = next(arg for arg in command if arg.startswith("--cov-report=json:"))
    Path(report_arg.removeprefix("--cov-report=json:")).write_text(content, encoding="utf-8")


def test_marker_expressions_keep_slow_tests_out_of_unit_lane(
    pytester: pytest.Pytester,
) -> None:
    assert test_checks._UNIT_TEST_MARKERS == (
        "not integration and not e2e and not requires_docker "
        "and not requires_node_modules and not requires_skylos and not slow"
    )
    assert test_checks._build_markers(integration=False) == test_checks._UNIT_TEST_MARKERS
    assert test_checks._build_markers(integration=True) == "integration"
    assert test_checks._build_markers(integration=False, requires_docker=True) == "requires_docker"
    with pytest.raises(ValueError, match="mutually exclusive"):
        test_checks._build_markers(integration=True, requires_docker=True)

    pytester.makeini(
        """
        [pytest]
        asyncio_default_fixture_loop_scope = function
        markers =
            integration: integration test
            slow: slow test
        """
    )
    pytester.makepyfile(
        """
        import pytest

        def test_unit():
            pass

        @pytest.mark.slow
        def test_slow_only():
            pass

        @pytest.mark.integration
        @pytest.mark.slow
        def test_slow_integration():
            pass
        """
    )

    unit_result = pytester.runpytest("-q", "-m", test_checks._build_markers(integration=False))
    unit_result.assert_outcomes(passed=1, deselected=2)

    integration_result = pytester.runpytest("-q", "-m", test_checks._build_markers(integration=True))
    integration_result.assert_outcomes(passed=1, deselected=2)


def test_docker_marker_selects_only_packages_that_contain_matching_tests() -> None:
    packages = test_checks._load_testable_packages("all", "requires_docker")
    names = {package.name for package in packages}

    assert "nohiki-kafka-client" in names
    assert "nohiki-integration-tests" in names
    assert "nohiki-common-exceptions" not in names
    assert all(package.requires_docker_tests for package in packages)


@pytest.mark.parametrize(
    ("source", "excluded"),
    [
        ("pytestmark = pytest.mark.integration\n\ndef test_generated(): pass\n", True),
        ("@pytest.mark.slow\nclass TestSlow:\n    def test_case(self): pass\n", True),
        (
            "@pytest.mark.integration\nasync def test_integration(): pass\n@pytest.mark.slow\ndef test_slow(): pass\n",
            True,
        ),
        (
            "@pytest.mark.integration\nclass TestIntegration:\n    def test_case(self): pass\ndef test_unit(): pass\n",
            False,
        ),
        (
            "class TestInherited(BaseTests):\n    @pytest.mark.integration\n    def test_case(self): pass\n",
            False,
        ),
        (
            "@pytest.mark.integration\nclass TestIntegration:\n    def test_case(self): pass\n"
            "TestDynamic = imported_test_class\n",
            False,
        ),
    ],
)
def test_wholly_excluded_module_detection_is_conservative(tmp_path: Path, source: str, *, excluded: bool) -> None:
    path = tmp_path / "test_example.py"
    path.write_text("import pytest\n" + source, encoding="utf-8")

    assert test_checks._test_module_is_wholly_excluded(path, test_checks._UNIT_EXCLUDED_MARKERS) is excluded


def test_unit_excluded_modules_are_pruned_only_from_the_unit_selection(
    tmp_path: Path,
) -> None:
    package = _package(tmp_path)
    excluded_path = package.path / "tests" / "test_integration.py"
    excluded_path.write_text(
        "import pytest\npytestmark = pytest.mark.integration\ndef test_case(): pass\n",
        encoding="utf-8",
    )
    included_path = package.path / "tests" / "test_unit.py"
    included_path.write_text("def test_case(): pass\n", encoding="utf-8")

    assert test_checks._unit_excluded_test_modules([package], test_checks._UNIT_TEST_MARKERS) == [excluded_path]
    assert test_checks._unit_excluded_test_modules([package], "integration") == []


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


def test_zero_measured_statements_are_coverage_exempt() -> None:
    result = RunnerTestResult(
        name="generated-package",
        passed=True,
        coverage=CoverageResult(),
        pkg_type=PackageType.LIB,
    )
    console = Console(record=True, width=120)

    display_summary([result], console, ci_mode=True)

    output = console.export_text()
    assert "COVERAGE: OK" in output
    assert "BELOW THRESHOLD" not in output
    assert not _check_exit_conditions([result], strict=True, with_coverage=True)


def _measured(cover: float) -> CoverageResult:
    return CoverageResult(
        total_coverage=cover,
        files=[FileCoverage(path="mod.py", stmts=100, miss=round(100 - cover), cover=cover)],
    )


def test_github_summary_renders_named_results_as_markdown() -> None:
    results = [
        RunnerTestResult(
            name="package-b",
            passed=False,
            duration_ms=2345,
            coverage=_measured(78.0),
            pkg_type=PackageType.LIB,
        ),
        RunnerTestResult(
            name="package-a",
            passed=True,
            duration_ms=1234,
            coverage=_measured(96.0),
            pkg_type=PackageType.LIB,
        ),
    ]

    summary = render_github_summary(results, "focused")

    assert summary.startswith("#### Python tests (focused)\n\n**1/2 packages passed.**")
    assert "Coverage is reported, not enforced" in summary
    assert "| `package-a` | 1.2s | Pass | 96% | meets strict policy: module >= 90%, file >= 80% |" in summary
    assert (
        "| `package-b` | 2.3s | Fail | 78% | below strict policy: module >= 90%, file >= 80%, 1 file under 80% |"
    ) in summary


def test_github_summary_states_the_policy_behind_every_coverage_number() -> None:
    """A passing row must say which policy it passed, or that no policy applied."""
    results = [
        # scripts packages map to the no-requirements gate, so 21% is a deliberate pass.
        RunnerTestResult(
            name="tooling",
            passed=True,
            duration_ms=1000,
            coverage=_measured(21.0),
            pkg_type=PackageType.SCRIPTS,
        ),
        # No measurable code at all: neutral, and a percentage would assert a measurement.
        RunnerTestResult(
            name="namespace-only",
            passed=True,
            duration_ms=500,
            coverage=CoverageResult(),
            pkg_type=PackageType.LIB,
        ),
        # Source carries statements that coverage never saw. This is a policy failure, and it must
        # not render as a neutral gap beside the code-free package above.
        RunnerTestResult(
            name="blanked",
            passed=True,
            duration_ms=750,
            coverage=CoverageResult(),
            pkg_type=PackageType.LIB,
            source_has_statements=True,
        ),
    ]

    summary = render_github_summary(results, "broad", strict=True)

    assert "Coverage is enforced" in summary
    assert (
        "| `tooling` | 1.0s | Pass | 21% | no policy: scripts packages carry the "
        "no-requirements gate (module >= 0%, file >= 0%) |"
    ) in summary
    assert (
        "| `namespace-only` | 0.5s | Pass | n/a | no policy: the package carries no measurable statements |"
    ) in summary
    assert (
        "| `blanked` | 0.8s | Pass | none | unmeasured: source carries statements but coverage measured none |"
    ) in summary
    # The two zero-statement rows share a predicate but not a verdict; conflating them is the defect.
    assert not _coverage_meets_policy(results[2])
    assert _coverage_meets_policy(results[1])


@pytest.mark.asyncio
async def test_parallel_runner_syncs_locked_workspace_once_before_tests(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """One consolidated pytest process starts after the workspace-wide sync."""
    events: list[str] = []
    sync_commands: list[list[str]] = []
    consolidated_calls: list[tuple[list[str], tuple[str, ...], int]] = []

    def fake_sync_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        del kwargs
        sync_commands.append(command)
        events.append("sync")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    async def fake_consolidated_run(
        packages: list[Package],
        markers: str,
        extra_args: tuple[str, ...],
        *,
        pytest_workers: int,
        with_coverage: bool,
    ) -> list[RunnerTestResult]:
        del markers, with_coverage
        consolidated_calls.append(([pkg.name for pkg in packages], extra_args, pytest_workers))
        events.append("pytest")
        return [RunnerTestResult(name=pkg.name, passed=True, pkg_type=pkg.pkg_type) for pkg in packages]

    monkeypatch.setattr(test_checks.subprocess, "run", fake_sync_run)
    monkeypatch.setattr(test_checks, "run_consolidated_tests", fake_consolidated_run)
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

    assert sync_commands == [
        [
            "scripts/dev/env-lock.sh",
            "exclusive",
            "venv",
            "--",
            "uv",
            "sync",
            "--all-packages",
            "--all-extras",
            "--no-extra",
            "cuda",
            "--group",
            "deadcode",
            "--locked",
        ]
    ]
    assert events == ["sync", "pytest"]
    assert consolidated_calls == [(["first", "second"], (), 2)]


@pytest.mark.asyncio
async def test_parallel_runner_skips_workspace_sync_in_ci_and_dispatches_tests(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A pre-synced CI workspace dispatches one consolidated pytest process."""
    consolidated_calls: list[list[str]] = []
    console = Console(record=True)

    def unexpected_sync(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        del args, kwargs
        pytest.fail("workspace sync must not run when CI owns the environment")

    async def fake_consolidated_run(
        packages: list[Package],
        markers: str,
        extra_args: tuple[str, ...],
        *,
        pytest_workers: int,
        with_coverage: bool,
    ) -> list[RunnerTestResult]:
        del markers, extra_args, pytest_workers, with_coverage
        consolidated_calls.append([pkg.name for pkg in packages])
        return [RunnerTestResult(name=pkg.name, passed=True, pkg_type=pkg.pkg_type) for pkg in packages]

    monkeypatch.setenv("CI_CHECKS_SKIP_WORKSPACE_SYNC", "1")
    monkeypatch.setattr(test_checks.subprocess, "run", unexpected_sync)
    monkeypatch.setattr(test_checks, "run_consolidated_tests", fake_consolidated_run)

    await test_checks.run_tests_parallel(
        [_package(tmp_path, "first"), _package(tmp_path, "second")],
        "not integration",
        (),
        2,
        console,
        ci_mode=True,
        with_coverage=False,
    )

    assert consolidated_calls == [["first", "second"]]
    assert "INFO: Skipping workspace sync; CI already installed the locked workspace." in console.export_text()


def test_consolidated_pythonpath_exposes_only_collision_free_helpers() -> None:
    packages = test_checks._load_testable_packages("all")
    package_by_name = {pkg.name: pkg for pkg in packages}
    helper_owners = test_checks._test_helper_module_owners(packages)

    assert test_checks._pythonpath_test_dirs(packages) == [package_by_name["ci-checks"].path / "tests"]
    assert helper_owners["_helpers.py"] == {
        "bff-service",
        "health-check",
        "nohiki-scaffold",
    }
    assert helper_owners["_documents.py"] == {"ci-checks"}
    assert helper_owners["helm_test_utils.py"] == {"ci-checks"}


def test_consolidated_coverage_config_uses_selected_sources_and_root_policy(
    tmp_path: Path,
) -> None:
    packages = [_package(tmp_path, "first"), _package(tmp_path, "second")]
    config_path = tmp_path / "coverage.ini"

    test_checks._write_consolidated_coverage_config(config_path, packages)

    config = configparser.ConfigParser(interpolation=None)
    config.read(config_path)
    root_config = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    root_coverage = root_config["tool"]["coverage"]

    def values(section: str, option: str) -> list[str]:
        return [line.strip() for line in config.get(section, option).splitlines() if line.strip()]

    assert not config.has_option("run", "include")
    assert values("run", "source") == [str((package.path / "src").resolve()) for package in packages]
    assert values("run", "omit") == root_coverage["run"]["omit"]
    assert not config.has_option("report", "exclude_lines")
    assert values("report", "exclude_also") == root_coverage["report"]["exclude_lines"]


def test_selected_coverage_source_is_not_excluded_by_root_omit(tmp_path: Path) -> None:
    package = next(
        package for package in test_checks._load_testable_packages("all") if package.name == "nohiki-domain-models"
    )
    config_path = tmp_path / "coverage.ini"

    test_checks._write_consolidated_coverage_config(config_path, [package])

    config = configparser.ConfigParser(interpolation=None)
    config.read(config_path)
    source_target = Path(test_checks._coverage_target(package))
    omit = [line.strip() for line in config.get("run", "omit").splitlines() if line.strip()]
    assert not any(source_target.full_match(pattern) for pattern in omit)


@pytest.mark.asyncio
async def test_consolidated_pytest_uses_one_bounded_workstealing_process(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    packages = [_package(tmp_path, "first"), _package(tmp_path, "second")]
    commands: list[tuple[str, ...]] = []
    first_file = test_checks._repo_relative(packages[0].path / "tests" / "test_one.py")
    second_file = test_checks._repo_relative(packages[1].path / "tests" / "test_two.py")

    async def fake_create_subprocess_exec(*command: str, **kwargs: object) -> _SuccessfulPytestProcess:
        del kwargs
        commands.append(command)
        _write_junit(
            command,
            "<testsuites><testsuite>"
            f'<testcase classname="tests.test_one" file="{first_file}" name="test_one" time="0.1"/>'
            f'<testcase classname="tests.test_two" file="{second_file}" name="test_two" time="0.2"/>'
            "</testsuite></testsuites>",
        )
        return _SuccessfulPytestProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    results = await test_checks.run_consolidated_tests(
        packages,
        test_checks._UNIT_TEST_MARKERS,
        (),
        pytest_workers=2,
        with_coverage=False,
    )

    assert [result.name for result in results] == ["first", "second"]
    assert len(commands) == 1
    command = commands[0]
    assert command[:4] == ("uv", "run", "--no-sync", "pytest")
    assert command.count("pytest") == 1
    assert command[command.index("-n") + 1] == "2"
    assert "--dist=worksteal" in command
    assert "--no-coverage" not in command
    assert not any(arg.startswith("--cov=") for arg in command)
    assert "--cov" not in command


@pytest.mark.asyncio
async def test_container_selection_collects_only_marker_derived_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    package = _package(tmp_path)
    marked = package.path / "tests" / "test_container.py"
    unit = package.path / "tests" / "test_unit.py"
    marked.write_text(
        "import pytest\n\n@pytest.mark.requires_docker\ndef test_container():\n    pass\n",
        encoding="utf-8",
    )
    unit.write_text("def test_unit():\n    pass\n", encoding="utf-8")
    package = Package(
        package.name,
        package.path,
        package.pkg_type,
        requires_docker_tests=frozenset({"tests/test_container.py"}),
    )
    commands: list[tuple[str, ...]] = []
    marked_arg = test_checks._repo_relative(marked)

    async def fake_create_subprocess_exec(*command: str, **kwargs: object) -> _SuccessfulPytestProcess:
        del kwargs
        commands.append(command)
        _write_junit(
            command,
            "<testsuites><testsuite>"
            f'<testcase classname="tests.test_container" file="{marked_arg}" '
            'name="test_container" time="0.1"/>'
            "</testsuite></testsuites>",
        )
        return _SuccessfulPytestProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    results = await test_checks.run_consolidated_tests(
        [package],
        "requires_docker",
        (),
        pytest_workers=1,
        with_coverage=False,
    )

    assert [result.passed for result in results] == [True]
    assert marked_arg in commands[0]
    assert test_checks._repo_relative(unit) not in commands[0]


@pytest.mark.asyncio
async def test_test_subprocesses_pin_project_root_to_their_own_checkout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A poisoned ambient PROJECT_ROOT must not redirect tests into another checkout.

    get_repo_root() prefers PROJECT_ROOT, so an inherited value from a sibling worktree
    silently resolves every repository-relative path against the wrong tree. The gate
    then passes or fails on code the runner is not testing.
    """
    monkeypatch.setenv("PROJECT_ROOT", "/somewhere/else/entirely")
    packages = [_package(tmp_path, "first")]
    captured: list[dict[str, str]] = []
    first_file = test_checks._repo_relative(packages[0].path / "tests" / "test_one.py")

    async def fake_create_subprocess_exec(*command: str, **kwargs: object) -> _SuccessfulPytestProcess:
        env = kwargs.get("env")
        assert isinstance(env, dict)
        captured.append({str(k): str(v) for k, v in env.items()})
        _write_junit(
            command,
            "<testsuites><testsuite>"
            f'<testcase classname="tests.test_one" file="{first_file}" name="test_one" time="0.1"/>'
            "</testsuite></testsuites>",
        )
        return _SuccessfulPytestProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    await test_checks.run_consolidated_tests(
        packages,
        test_checks._UNIT_TEST_MARKERS,
        (),
        pytest_workers=1,
        with_coverage=False,
    )

    assert captured, "the consolidated runner never spawned a subprocess"
    assert captured[0]["PROJECT_ROOT"] == str(test_checks.REPO_ROOT)
    assert captured[0]["PROJECT_ROOT"] != "/somewhere/else/entirely"


@pytest.mark.asyncio
async def test_consolidated_results_attribute_junit_timings_and_package_coverage(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    packages = [_package(tmp_path, "first"), _package(tmp_path, "second")]
    first_target = test_checks._coverage_target(packages[0])
    second_target = test_checks._coverage_target(packages[1])
    first_file = test_checks._repo_relative(packages[0].path / "tests" / "test_one.py")
    second_file = test_checks._repo_relative(packages[1].path / "tests" / "test_two.py")
    coverage_json = json.dumps(
        {
            "files": {
                f"{first_target}/first.py": {
                    "summary": {
                        "num_statements": 10,
                        "missing_lines": 1,
                        "percent_covered_display": "90",
                    }
                },
                f"{second_target}/second.py": {
                    "summary": {
                        "num_statements": 20,
                        "missing_lines": 5,
                        "percent_covered_display": "75",
                    }
                },
            }
        }
    )
    commands: list[tuple[str, ...]] = []

    async def fake_create_subprocess_exec(*command: str, **kwargs: object) -> _SuccessfulPytestProcess:
        del kwargs
        commands.append(command)
        _write_junit(
            command,
            "<testsuites><testsuite>"
            f'<testcase classname="tests.test_one" file="{first_file}" name="test_one" time="1.25"/>'
            f'<testcase classname="tests.test_two" file="{second_file}" name="test_two" time="2.5"/>'
            "</testsuite></testsuites>",
        )
        _write_coverage_json(command, coverage_json)
        return _SuccessfulPytestProcess()

    monkeypatch.setenv("CI_CHECKS_SKIP_WORKSPACE_SYNC", "1")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(test_checks.os, "process_cpu_count", lambda: 2)
    console = Console(record=True, width=120)

    results = await test_checks.run_tests_parallel(
        packages,
        "",
        (),
        2,
        console,
        ci_mode=True,
        with_coverage=True,
    )

    assert [(result.tests_run, result.duration_ms) for result in results] == [
        (1, 1250),
        (1, 2500),
    ]
    assert [result.coverage.total_coverage for result in results] == [90.0, 75.0]
    assert len(commands) == 1
    command = commands[0]
    assert not any(arg.startswith("--cov=") for arg in command)
    assert command.count("--cov") == 1
    assert "-v" not in command
    assert any(arg.startswith("--cov-report=json:") for arg in command)
    assert any(arg.startswith("--cov-config=") for arg in command)
    assert "--no-coverage" not in command
    summary = console.export_text()
    assert "first" in summary
    assert "1.2s" in summary
    assert "90%" in summary
    assert "second" in summary
    assert "2.5s" in summary
    assert "75%" in summary


@pytest.mark.asyncio
async def test_selected_package_with_zero_junit_cases_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    packages = [_package(tmp_path, "first"), _package(tmp_path, "second")]
    first_file = test_checks._repo_relative(packages[0].path / "tests" / "test_one.py")

    async def fake_create_subprocess_exec(*command: str, **kwargs: object) -> _SuccessfulPytestProcess:
        del kwargs
        _write_junit(
            command,
            "<testsuites><testsuite>"
            f'<testcase classname="tests.test_one" file="{first_file}" name="test_one" time="0.1"/>'
            "</testsuite></testsuites>",
        )
        return _SuccessfulPytestProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    results = await test_checks.run_consolidated_tests(
        packages,
        "",
        (),
        pytest_workers=2,
        with_coverage=False,
    )

    assert [result.passed for result in results] == [True, False]
    assert results[1].tests_run == 0
    assert results[1].output == "No selected tests were collected for package second."


@pytest.mark.asyncio
async def test_nonzero_pytest_exit_has_explicit_controller_result(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    packages = [_package(tmp_path, "first"), _package(tmp_path, "second")]
    first_file = test_checks._repo_relative(packages[0].path / "tests" / "test_one.py")
    second_file = test_checks._repo_relative(packages[1].path / "tests" / "test_two.py")

    async def fake_create_subprocess_exec(*command: str, **kwargs: object) -> _SuccessfulPytestProcess:
        del kwargs
        _write_junit(
            command,
            "<testsuites><testsuite>"
            f'<testcase classname="tests.test_one" file="{first_file}" name="test_one" time="0.1">'
            "<failure>assert 1 == 2</failure></testcase>"
            f'<testcase classname="tests.test_two" file="{second_file}" name="test_two" time="0.2"/>'
            "</testsuite></testsuites>",
        )
        return _SuccessfulPytestProcess(b"FAILED tests/test_one.py::test_one - assert 1 == 2\n", returncode=1)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    results = await test_checks.run_consolidated_tests(
        packages,
        "",
        (),
        pytest_workers=2,
        with_coverage=False,
    )

    assert [(result.name, result.passed) for result in results] == [
        ("first", False),
        ("second", True),
        ("pytest controller", False),
    ]
    assert "assert 1 == 2" in results[0].output
    assert results[-1].output == "pytest controller exited with status 1."


@pytest.mark.asyncio
async def test_package_pytest_uv_command_does_not_sync(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The package primitive must preserve caller-supplied pytest arguments."""
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
async def test_package_subprocess_pins_project_root_to_its_own_checkout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The per-package runner needs the same root pin as the consolidated one.

    It spawns with ``cwd=pkg.path``, so an inherited PROJECT_ROOT from a sibling
    worktree redirects repository-relative resolution just as silently there.
    """
    monkeypatch.setenv("PROJECT_ROOT", "/somewhere/else/entirely")
    captured: list[dict[str, str]] = []

    async def fake_create_subprocess_exec(*command: str, **kwargs: object) -> _SuccessfulPytestProcess:
        del command
        env = kwargs.get("env")
        assert isinstance(env, dict)
        captured.append({str(k): str(v) for k, v in env.items()})
        return _SuccessfulPytestProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    await test_checks.run_package_tests(_package(tmp_path), "", (), with_coverage=False)

    assert captured, "the package runner never spawned a subprocess"
    assert captured[0]["PROJECT_ROOT"] == str(test_checks.REPO_ROOT)
    assert captured[0]["PROJECT_ROOT"] != "/somewhere/else/entirely"


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


def test_scoped_worker_uses_one_cached_environment_with_bounded_tests() -> None:
    """The one work job obtains one environment and runs one bounded Python command."""
    workflow = load_workflow(_CHECKS_WORKFLOW)
    setup_action = load_mapping(_SETUP_CI_ACTION)
    worker = workflow["jobs"]["worker"]

    # One job definition serves both classes; the matrix, not a second job, picks the units.
    assert [
        job_id
        for job_id, job in workflow["jobs"].items()
        if "needs.changes.outputs.standard == 'true'" in str(job.get("if", ""))
    ] == ["worker"]
    assert "needs.changes.outputs.broad == 'true'" in worker["if"]

    unit_steps = worker["steps"]
    setup_steps = [step for step in unit_steps if step.get("uses") == "./.github/actions/setup-ci"]
    assert len(setup_steps) == 1
    setup_inputs = setup_steps[0].get("with", {})
    assert isinstance(setup_inputs, dict)
    assert setup_inputs.get("ready-cache") == "${{ env.NIX_SETUP_SELECTED }}"
    assert setup_inputs.get("runner-class") == "${{ needs.changes.outputs.runner_class }}"
    assert setup_inputs.get("lookup-only") != "true"
    direct_environment_commands = "\n".join(str(step.get("run", "")) for step in unit_steps)
    assert "sync-ci-environment.sh" not in direct_environment_commands
    assert "uv sync" not in direct_environment_commands
    worker_nix_selector = str(worker["env"]["NIX_SETUP_SELECTED"])
    assert "needs.changes.outputs.python_any == 'true'" in worker_nix_selector

    action_steps = mapping_sequence_at(setup_action, "runs", "steps")
    environment_restores = [
        step
        for step in action_steps
        if str(step.get("uses", "")).startswith(("nix-community/cache-nix-action/restore@", "actions/cache/restore@"))
        and "inputs.lookup-only != 'true'" in str(step.get("if", ""))
        and "ready-cache" in str(step.get("id", ""))
    ]
    environment_syncs = [
        step for step in action_steps if "scripts/dev/sync-ci-environment.sh" in str(step.get("run", ""))
    ]
    assert {step["id"] for step in environment_restores} == {
        "hosted-ready-cache",
        "persistent-ready-cache",
    }
    assert len(environment_syncs) == 1
    assert "steps.ready-cache-result.outputs.restore-exact != 'true'" in str(environment_syncs[0]["if"])

    test = next(step for step in unit_steps if step.get("name") == "Run selected Python tests")
    test_command = str(test["run"])
    assert worker["timeout-minutes"] == "${{ fromJSON(needs.changes.outputs.worker_timeout_minutes) }}"
    assert '--packages "$TEST_PACKAGES"' in test_command
    assert test_command.count("--ci --workers 2") == 1
    assert "--lf" not in test_command
    assert "--ff" not in test_command
    assert '--summary "$GITHUB_STEP_SUMMARY"' in test_command
    assert '--summary-title "$SUMMARY_TITLE"' in test_command
    assert test["env"]["SUMMARY_TITLE"] == "${{ needs.changes.outputs.commit_class }}"
    assert test["env"]["CI_CHECKS_SKIP_WORKSPACE_SYNC"] == "1"

    # The bounded Python command is alone in its named payload leg in both classes.
    condition = str(test["if"])
    assert "matrix.unit == 'python'" in condition
    assert "matrix.unit == 'frontend'" not in condition
    assert condition.endswith("needs.changes.outputs.python_any == 'true')")

    docker_smoke = next(
        step
        for step in workflow["jobs"]["worker"]["steps"]
        if step.get("name") == "Smoke production frontend container"
    )
    assert (
        "scripts/ci/tests/test_frontend_delivery.py::test_frontend_container_build_and_hardened_runtime_smoke"
        in docker_smoke["run"]
    )
    assert "-m requires_docker" not in docker_smoke["run"]


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
