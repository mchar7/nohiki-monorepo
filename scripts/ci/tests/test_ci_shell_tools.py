from __future__ import annotations

import json
import re
import tomllib
from collections.abc import Mapping
from pathlib import Path

import pytest
from _documents import WorkflowJob, load_mapping, load_workflow
from ci_checks.app import app
from ci_checks.core.packages import PackageType, Scope, _scope_filter
from typer.testing import CliRunner

_ROOT = Path(__file__).resolve().parents[3]
_FLAKE = _ROOT / "flake.nix"
_CHECKS = _ROOT / ".github" / "workflows" / "checks.yml"
_LEFTHOOK = _ROOT / "lefthook.yml"
_CI_PROJECT = _ROOT / "scripts" / "ci" / "pyproject.toml"
_CI_PACKAGE_TOKENS = (
    "pnpmPackage",
    "pkgs.jq",
    "pkgs.yq-go",
    "pkgs.kubernetes-helm",
    "pkgs.ripgrep",
    "pkgs.openssh",
    "pkgs.gitleaks",
    "pkgs.actionlint",
    "pkgs.hadolint",
    "pkgs.buf",
    "pkgs.skopeo",
)


def _commands(job: WorkflowJob) -> list[str]:
    return [step["run"] for step in job.get("steps", []) if "run" in step]


def test_ci_nix_shell_includes_local_secret_bootstrap_tools() -> None:
    flake = _FLAKE.read_text(encoding="utf-8")
    declarations, ci_shell = flake.split("devShells.ci = pkgs.mkShell", 1)
    assert "packages = ciTools" in ci_shell.split("devShells.ci-python", 1)[0]
    for token in _CI_PACKAGE_TOKENS:
        assert token in declarations, f"ciTools must include {token}"


def test_checks_workflow_routes_standard_and_broad_contracts_once() -> None:
    workflow = load_workflow(_CHECKS)
    jobs = workflow["jobs"]
    assert set(jobs) == {
        "changes",
        "worker",
        "container-contracts",
        "playwright-image",
        "checks",
    }

    work = "\n".join(
        step["run"] for step in jobs["worker"]["steps"] if "run" in step and step.get("name") != "Report worker timing"
    )
    container_contracts = "\n".join(_commands(jobs["container-contracts"]))
    playwright_image = "\n".join(_commands(jobs["playwright-image"]))
    assert "test_frontend_delivery.py::test_frontend_container_build_and_hardened_runtime_smoke" in container_contracts
    assert (
        "test_otel_collector_manifest.py::test_otel_collector_rendered_configs_validate_with_pinned_binary"
        in container_contracts
    )
    assert "typescript/apps/frontend/node_modules/.bin/playwright" in playwright_image

    commands = (
        "biome ci --reporter=github src/",
        "exec tsc --noEmit",
        "exec vitest run",
        'ty check "${paths[@]}"',
        "pnpm -C typescript/apps/frontend type-check",
        "pnpm -C typescript/apps/frontend test --run --maxWorkers=100%",
        "ci-checks deptry",
        "semgrep scan",
        "ci-checks build-backend",
        "just api-schema-check",
        "just image-matrix-check",
        "ci-checks deadcode",
    )
    # Both classes are served by one definition of each command, so one occurrence, not two.
    for command in commands:
        assert work.count(command) == 1
    # Ruff is the one step carrying both scopes: whole tree on broad, changed files on standard.
    assert work.count("ruff check --output-format=github") == 2
    assert work.count("ruff format --check") == 2

    owner_commands = "\n".join(_commands(jobs["worker"]))
    proto_step = next(
        step for step in jobs["worker"].get("steps", []) if step.get("name") == "Check proto compatibility"
    )
    assert proto_step["env"]["BASE_SHA"] == ("${{ github.event.pull_request.base.sha || github.event.before }}")
    assert "buf breaking --against '../.git#commit=${BASE_SHA},subdir=proto'" in owner_commands

    all_commands = "\n".join(command for job in jobs.values() for command in _commands(job))
    assert all_commands.count("semgrep scan") == 1
    assert "lefthook run pre-push" not in all_commands


def test_python_tests_use_one_runner_per_commit_class() -> None:
    workflow = load_workflow(_CHECKS)
    job = workflow["jobs"]["worker"]
    assert job["timeout-minutes"] == "${{ fromJSON(needs.changes.outputs.worker_timeout_minutes) }}"
    # Standard takes one unit, broad three, and the Python tests are alone in their unit.
    broad_units, standard_units = (
        json.loads(group) for group in re.findall(r"'(\[[^']*\])'", str(job["strategy"]["matrix"]["unit"]))
    )
    assert broad_units == ["python", "frontend", "hygiene"]
    assert standard_units == ["all"]
    steps = {step["name"]: step for step in job["steps"] if "name" in step}
    run_tests = steps["Run selected Python tests"]
    command = str(run_tests["run"])
    assert command.count("ci-checks tests all --scope all") == 1
    assert '--packages "$TEST_PACKAGES"' in command
    assert "--ci --workers 2" in command
    assert '--summary "$GITHUB_STEP_SUMMARY"' in command
    assert '--summary-title "$SUMMARY_TITLE"' in command
    assert run_tests["env"] == {
        "TEST_PACKAGES": "${{ needs.changes.outputs.test_packages }}",
        "CI_CHECKS_SKIP_WORKSPACE_SYNC": "1",
        "SUMMARY_TITLE": "${{ needs.changes.outputs.commit_class }}",
        "OTEL_SDK_DISABLED": "true",
        "UV_NO_SYNC": "1",
        "COVERAGE_CORE": "sysmon",
    }


def test_ci_self_tests_use_worksteal_xdist_without_dropping_package_coverage() -> None:
    with _CI_PROJECT.open("rb") as project_file:
        pytest_options = tomllib.load(project_file)["tool"]["pytest"]["ini_options"]
    assert pytest_options["addopts"] == "-n auto --dist=worksteal"
    workflow = load_workflow(_CHECKS)
    hosted_command = "\n".join(_commands(workflow["jobs"]["worker"]))
    lefthook = load_mapping(_LEFTHOOK)
    pre_push = lefthook["pre-push"]
    assert isinstance(pre_push, Mapping)
    phases = pre_push.get("jobs")
    assert isinstance(phases, list)
    local_commands: list[str] = []
    for phase in phases:
        assert isinstance(phase, Mapping)
        if "group" in phase:
            group = phase.get("group")
            assert isinstance(group, Mapping)
            nested_jobs = group.get("jobs")
            assert isinstance(nested_jobs, list)
        else:
            nested_jobs = [phase]
        for nested in nested_jobs:
            assert isinstance(nested, Mapping)
            if nested.get("name") == "python-tests":
                run = nested.get("run")
                assert isinstance(run, str)
                local_commands.append(run)
    local_command = next(iter(local_commands))
    assert "--no-coverage" not in hosted_command
    assert "--no-coverage" not in local_command


def test_checks_aggregator_requires_every_hosted_lane() -> None:
    workflow = load_workflow(_CHECKS)
    jobs = workflow["jobs"]
    checks = jobs["checks"]
    assert checks["name"] == "Checks"
    assert checks["if"] == "always()"
    needs = checks["needs"]
    assert isinstance(needs, list)
    assert set(needs) == set(jobs) - {"checks"}

    command = "\n".join(_commands(checks))
    for job in needs:
        assert f"needs.{job}.result" in command


def test_package_scopes_partition_all_package_types() -> None:
    categories = {
        Scope.SERVICES: PackageType.SERVICE,
        Scope.LIBS: PackageType.LIB,
        Scope.JOBS: PackageType.JOB,
        Scope.SCRIPTS: PackageType.SCRIPTS,
        Scope.OTHER: PackageType.OTHER,
    }
    assert set(categories) == set(Scope) - {Scope.ALL}
    assert set(categories.values()) == set(PackageType)
    assert all(_scope_filter(package_type, Scope.ALL) for package_type in PackageType)
    for scope, selected_type in categories.items():
        assert {package_type for package_type in PackageType if _scope_filter(package_type, scope)} == {selected_type}


def test_empty_package_scope_succeeds_without_falling_back_to_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected_scopes: list[Scope] = []

    def load_empty_scope(scope: Scope) -> dict[str, object]:
        selected_scopes.append(scope)
        return {}

    monkeypatch.setattr("ci_checks.core.packages.load_packages_with_deps", load_empty_scope)
    result = CliRunner().invoke(
        app,
        ["tests", "all", "--scope", "other", "--ci", "--workers", "2"],
    )

    assert result.exit_code == 0
    assert selected_scopes == [Scope.OTHER]
    assert "No testable packages found" in result.output
