from __future__ import annotations

import json
import re
import shutil
import subprocess
import tomllib
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import pytest
from _documents import WorkflowJob, WorkflowStep, load_mapping, load_workflow, string_at
from ci_checks.app import app
from ci_checks.checks.workflow import (
    COLD_WALL_BUDGET_SECONDS,
    WARM_WALL_BUDGET_SECONDS,
    hosted_equivalent_minutes,
    render_report_summary,
    select_wall_budget,
)
from ci_checks.core.change_gate import GateDecision, render_outputs
from ci_checks.core.packages import PackageType, Scope, _scope_filter
from typer.testing import CliRunner

_ROOT = Path(__file__).resolve().parents[3]
_FLAKE = _ROOT / "flake.nix"
_CHECKS = _ROOT / ".github" / "workflows" / "checks.yml"
_LEFTHOOK = _ROOT / "lefthook.yml"
_JUSTFILE = _ROOT / "Justfile"
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
    "pkgs.check-jsonschema",
    "pkgs.hadolint",
    "pkgs.buf",
    "pkgs.skopeo",
)


def _steps(job: WorkflowJob) -> list[WorkflowStep]:
    steps: list[WorkflowStep] = []
    for step in job.get("steps", []):
        steps.extend(step.get("parallel", [step]))
    return steps


def _commands(job: WorkflowJob) -> list[str]:
    return [str(step["run"]) for step in _steps(job) if "run" in step]


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
        "label-sync",
        "worker",
        "playwright-image",
        "title-policy",
        "checks",
    }

    # The summary frame steps, `Open ...` and `Report ...`, name commands in their inventory
    # without running them. Matching on the prefix rather than one exact name keeps this scan
    # measuring real work after a frame step is renamed.
    work = "\n".join(
        step["run"]
        for step in _steps(jobs["worker"])
        if "run" in step and not str(step.get("name", "")).startswith(("Open ", "Report "))
    )
    playwright_image = "\n".join(_commands(jobs["playwright-image"]))
    assert "test_frontend_delivery.py::test_frontend_container_build_and_hardened_runtime_smoke" in work
    assert "test_otel_collector_manifest.py::test_otel_collector_rendered_configs_validate_with_pinned_binary" in work
    assert "typescript/apps/frontend/node_modules/.bin/playwright" in playwright_image

    commands = (
        "biome ci --reporter=github src/",
        "exec tsc --noEmit",
        "exec vitest run",
        "just typecheck-all",
        "just fe-typecheck",
        "just fe-test",
        "just hygiene-deps",
        "just hygiene-arch",
        "just hygiene-build-backend-strict",
        "just api-schema-check",
        "just image-matrix-check",
        "just hygiene-deadcode-strict",
    )
    # Both classes are served by one definition of each command, so one occurrence, not two.
    for command in commands:
        assert work.count(command) == 1
    assert work.count("just lint") == 1
    assert work.count("ruff check --output-format=github") == 1
    assert work.count("just format-check") == 1
    assert work.count("ruff format --check") == 1

    owner_commands = "\n".join(_commands(jobs["worker"]))
    proto_step = next(
        step for step in jobs["worker"].get("steps", []) if step.get("name") == "Check proto compatibility"
    )
    assert proto_step["env"]["BASE_SHA"] == ("${{ github.event.pull_request.base.sha || github.event.before }}")
    assert 'just proto-breaking "$BASE_SHA"' in owner_commands

    all_commands = "\n".join(command for job in jobs.values() for command in _commands(job))
    assert all_commands.count("just hygiene-arch") == 1
    assert "lefthook run pre-push" not in all_commands


def test_python_tests_use_the_named_python_payload_leg() -> None:
    workflow = load_workflow(_CHECKS)
    job = workflow["jobs"]["worker"]
    assert job["timeout-minutes"] == "${{ fromJSON(needs.changes.outputs.worker_timeout_minutes) }}"
    assert job["strategy"]["matrix"]["unit"] == "${{ fromJSON(needs.changes.outputs.worker_units) }}"
    assert json.loads(render_outputs(GateDecision(full=True), (), "push")["worker_units"]) == [
        "python",
        "frontend",
    ]
    assert json.loads(render_outputs(GateDecision(), (), "pull_request")["worker_units"]) == ["frontend"]
    steps = {step["name"]: step for step in _steps(job) if "name" in step}
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


def test_workflow_validators_are_pinned_in_hosted_and_local_paths() -> None:
    workflow = load_workflow(_CHECKS)
    lint = next(step for step in _steps(workflow["jobs"]["worker"]) if step.get("name") == "Lint workflows")
    command = str(lint["run"])
    parallel_diagnostic = 'step must run script with "run" section or run action with "uses" section'
    assert command.endswith("just workflow-lint")

    policy = _JUSTFILE.read_text(encoding="utf-8")
    assert "actionlint -ignore" not in policy
    assert "actionlint -oneline" in policy
    # The narrowness this defends is the exact diagnostic text, not how many times it is written
    # out. The four source locations are read from the workflow rather than pinned, because pinned
    # line numbers drift on any edit above them and then silently stop suppressing, and re-pinning
    # at the new numbers only rearms that. A pinned literal would pass a count and still be aimed
    # at the wrong lines, so the count is replaced by a ban on the pinned form.
    assert parallel_diagnostic in policy
    assert "- parallel:" in policy
    assert not re.search(r"checks\.yml:\d+:", policy), "workflow-lint must not pin suppressions by line number"
    assert "check-jsonschema" in policy
    assert "--builtin-schema vendor.github-workflows .github/workflows/*.yml" in policy

    lefthook = load_mapping(_LEFTHOOK)
    local = string_at(lefthook, "pre-commit", "commands", "actions-lint", "run")
    assert local == "just workflow-lint"


def test_ci_self_tests_use_worksteal_xdist_without_dropping_package_coverage() -> None:
    with _CI_PROJECT.open("rb") as project_file:
        pytest_options = tomllib.load(project_file)["tool"]["pytest"]["ini_options"]
    assert pytest_options["addopts"] == "-n auto --dist=worksteal"
    workflow = load_workflow(_CHECKS)
    worker_steps = {step.get("name"): step for step in _steps(workflow["jobs"]["worker"])}
    selected_tests = worker_steps["Run selected Python tests"].get("run")
    integration_tests = worker_steps["Run job correlation integration tests"].get("run")
    assert isinstance(selected_tests, str)
    assert isinstance(integration_tests, str)
    assert "--no-coverage" not in selected_tests
    assert "--no-coverage" in integration_tests

    lefthook = load_mapping(_LEFTHOOK)
    pre_push = lefthook["pre-push"]
    assert isinstance(pre_push, Mapping)
    phases = pre_push.get("jobs")
    assert isinstance(phases, list)
    local_commands: dict[str, str] = {}
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
            name = nested.get("name")
            if name in {"python-tests", "job-correlation-integration"}:
                run = nested.get("run")
                assert isinstance(run, str)
                local_commands[str(name)] = run
    assert "--no-coverage" not in local_commands["python-tests"]
    assert "--no-coverage" in local_commands["job-correlation-integration"]


def test_checks_aggregator_requires_every_required_hosted_lane() -> None:
    workflow = load_workflow(_CHECKS)
    jobs = workflow["jobs"]
    checks = jobs["checks"]
    assert checks["name"] == "Checks"
    assert checks["if"] == "always()"
    needs = checks["needs"]
    assert isinstance(needs, list)
    advisory = {job_id for job_id, job in jobs.items() if job.get("continue-on-error") is True}
    assert set(needs) == set(jobs) - {"checks"} - advisory

    contract = str(checks)
    for job in needs:
        assert f"needs.{job}.result" in contract


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


def test_checks_workflow_factors_shared_shell_behaviour_into_python() -> None:
    jobs = load_workflow(_CHECKS)["jobs"]
    summaries = [
        step
        for job in jobs.values()
        for step in _steps(job)
        if str(step.get("name", "")).startswith(("Open ", "Report "))
    ]
    assert summaries
    for step in summaries:
        command = str(step["run"])
        if step["name"] == "Report workflow accounting":
            assert "workflow.py accounting" in command
        else:
            assert "workflow.py summary" in command

    commands = "\n".join(command for job in jobs.values() for command in _commands(job))
    assert "workflow.py guard" in commands.replace("\n", " ")
    assert commands.count("workflow.py verdict") == 2
    assert "workflow.py accounting" in commands
    for retired_shell in (
        "read -ra entries",
        'billable_minutes="$(jq',
        "wall_budget_seconds=",
        "cold_wall_budget_seconds=",
        "require() {",
    ):
        assert retired_shell not in commands


def test_workflow_summary_subcommand_writes_exact_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary = tmp_path / "summary.md"
    environment = {
        "BUILD_OUTCOME": "success",
        "GITHUB_STEP_SUMMARY": str(summary),
        "JOB_STARTED": "100",
        "UNIQUE_STARTED": "130",
        "VERIFY_OUTCOME": "success",
    }
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    result = CliRunner().invoke(
        app,
        ["workflow-summary", "report", "playwright", str(summary)],
    )

    assert result.exit_code == 0, result.output
    rendered = summary.read_text(encoding="utf-8")
    match = re.search(r"\| Unique work \| (\d+) \|", rendered)
    assert match is not None
    assert rendered == render_report_summary(
        "playwright",
        environment,
        now=130 + int(match.group(1)),
    )


def test_workflow_guard_and_verdict_subcommands_preserve_decisions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "output"
    broad = CliRunner().invoke(app, ["workflow-guard", "broad", str(output)])
    assert broad.exit_code == 0, broad.output
    assert output.read_text(encoding="utf-8") == "worker_timeout_minutes=52\n"

    invalid = CliRunner().invoke(app, ["workflow-guard", "invalid", str(output)])
    assert invalid.exit_code != 0
    assert isinstance(invalid.exception, ValueError)
    assert str(invalid.exception) == "cannot derive a guard for commit class: invalid"

    values = {
        "BROAD": "false",
        "CHANGES_RESULT": "success",
        "COMMIT_CLASS": "standard",
        "CONTAINER_EXPECTED": "false",
        "FULL": "false",
        "NODE_GROUP_EXPECTED": "false",
        "PLAYWRIGHT_EXPECTED": "false",
        "PLAYWRIGHT_RESULT": "skipped",
        "STANDARD": "true",
        "TITLE_POLICY_EXPECTED": "false",
        "TITLE_POLICY_RESULT": "skipped",
        "WORKER_COMMITLINT": "",
        "WORKER_COMMITLINT_EXPECTED": "false",
        "WORKER_CONTAINER_CONTRACTS": "",
        "WORKER_NODE_GROUP": "",
        "WORKER_RESULT": "success",
        "WORK_EXPECTED": "true",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    verdict = CliRunner().invoke(app, ["workflow-verdict", "checks"])
    assert verdict.exit_code == 0, verdict.output

    monkeypatch.setenv("COMMIT_CLASS", "invalid")
    invalid_verdict = CliRunner().invoke(app, ["workflow-verdict", "checks"])
    assert invalid_verdict.exit_code != 0
    assert isinstance(invalid_verdict.exception, ValueError)
    assert str(invalid_verdict.exception) == "router emitted an invalid commit class"


def test_workflow_accounting_arithmetic_and_wall_boundary() -> None:
    now = datetime(2026, 7, 23, 0, 2, tzinfo=UTC)
    jobs = [
        {
            "started_at": "2026-07-23T00:00:00Z",
            "completed_at": "2026-07-23T00:01:01Z",
        }
    ]
    assert hosted_equivalent_minutes(jobs, now) == 2
    assert hosted_equivalent_minutes([], now) == 0

    warm = select_wall_budget("", "true", "", "true")
    cold = select_wall_budget("true", "", "", "true")
    assert (warm.classification, warm.seconds) == ("warm", WARM_WALL_BUDGET_SECONDS)
    assert (cold.classification, cold.seconds) == ("cold", COLD_WALL_BUDGET_SECONDS)
    assert warm.seconds > WARM_WALL_BUDGET_SECONDS - 1
    assert warm.seconds <= WARM_WALL_BUDGET_SECONDS


def test_package_manager_comes_from_the_pinned_toolchain_not_a_fetch() -> None:
    """Corepack resolves `packageManager` by downloading, which hermetic shells forbid."""
    root = Path(__file__).resolve().parents[3]
    justfile = (root / "Justfile").read_text(encoding="utf-8")

    assert re.search(r'^pnpm := "pnpm"$', justfile, re.MULTILINE), "pnpm must come from PATH"
    assert "corepack" not in justfile, "Corepack would fetch a package manager the flake already pins"
    assert 'COREPACK_ENABLE_NETWORK = "0"' in (root / "flake.nix").read_text(encoding="utf-8")

    declared = json.loads((root / "package.json").read_text(encoding="utf-8"))["packageManager"]
    name, _, wanted = declared.partition("@")
    assert name == "pnpm", declared

    resolved = shutil.which("pnpm")
    if resolved is None:
        pytest.skip("pnpm is provided by the development shell")
    provided = subprocess.run([resolved, "--version"], capture_output=True, text=True, check=True).stdout.strip()
    assert provided == wanted, f"flake provides pnpm {provided} but package.json declares {wanted}"
