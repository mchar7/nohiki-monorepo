from __future__ import annotations

import re
import tomllib
from collections.abc import Mapping
from functools import cache
from pathlib import Path
from typing import cast

import pytest
import yaml
from ci_checks.app import app
from ci_checks.core.packages import PackageType, Scope, _scope_filter
from typer.testing import CliRunner

_ROOT = Path(__file__).resolve().parents[3]
_FLAKE = _ROOT / "flake.nix"
_CHECKS = _ROOT / ".github" / "workflows" / "checks.yml"
_LEFTHOOK = _ROOT / "lefthook.yml"
_CI_PROJECT = _ROOT / "scripts" / "ci" / "pyproject.toml"
_CI_PACKAGE_TOKENS = (
    "pkgs.age",
    "pkgs.sops",
    "pkgs.kubernetes-helm",
    "pkgs.kubectl",
    "pkgs.kustomize",
    "pkgs.ripgrep",
    "pkgs.gitleaks",
    "pkgs.actionlint",
    "pkgs.hadolint",
    "pkgs.buf",
    "pkgs.skopeo",
)


@cache
def _load_yaml(path: Path) -> dict[str, object]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return _mapping(document)


def _mapping(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return cast("dict[str, object]", value)


def _mapping_at(mapping: Mapping[str, object], key: str) -> dict[str, object]:
    return _mapping(mapping[key])


def _mapping_list(value: object) -> list[dict[str, object]]:
    assert isinstance(value, list)
    return [_mapping(item) for item in value]


def _strings(value: object) -> list[str]:
    assert isinstance(value, list)
    return [cast("str", item) for item in value]


def test_ci_nix_shell_includes_local_secret_bootstrap_tools() -> None:
    flake = _FLAKE.read_text(encoding="utf-8")
    block = flake.split("devShells.ci = pkgs.mkShell", 1)[1].split("};", 1)[0]
    packages = re.search(r"packages = \[(?P<body>.*?)\];", block, re.DOTALL)
    assert packages is not None, "devShells.ci must define packages"
    for token in _CI_PACKAGE_TOKENS:
        assert token in packages["body"], f"devShells.ci must include {token}"


def _commands(job: object) -> list[str]:
    assert isinstance(job, dict)
    steps = job.get("steps")
    assert isinstance(steps, list)
    commands: list[str] = []
    for step in steps:
        if isinstance(step, dict):
            run = step.get("run")
            if isinstance(run, str):
                commands.append(run)
    return commands


def test_checks_workflow_splits_every_prepush_gate_into_hosted_lanes() -> None:
    workflow = _load_yaml(_CHECKS)
    jobs_value = workflow.get("jobs")
    assert isinstance(jobs_value, dict)
    jobs = _mapping(jobs_value)
    assert "prepush" not in jobs

    lanes = {
        "frontend-smoke",
        "typecheck",
        "python-tests",
        "frontend-tests",
        "hygiene",
        "generated-artifacts",
        "proto-breaking",
    }
    assert lanes < jobs.keys()

    commands = {job_id: "\n".join(_commands(jobs[job_id])) for job_id in lanes}
    hygiene = _mapping_at(jobs, "hygiene")
    hygiene_step_names = [step.get("name") for step in _mapping_list(hygiene["steps"])]
    assert "Install ripgrep" not in hygiene_step_names
    assert "-m requires_docker" in commands["frontend-smoke"]
    assert "ty check backend/" in commands["typecheck"]
    assert "pnpm -C typescript/apps/frontend type-check" in commands["typecheck"]
    assert "pnpm -C typescript/apps/frontend test --run --maxWorkers=25%" in commands["frontend-tests"]
    deadcode = commands["hygiene"]
    assert "ci-checks deadcode --scope all --ci --fail --no-provenance" in deadcode
    assert "--diff" not in deadcode
    assert "--base-ref" not in deadcode
    assert "--baseline" not in deadcode
    assert "--no-grep-verify" not in deadcode
    assert "ci-checks deptry --scope all --ci" in commands["hygiene"]
    assert "semgrep scan --config semgrep.yml --error --no-git-ignore backend/" in commands["hygiene"]
    assert "ci-checks build-backend --scope all --ci --strict" in commands["hygiene"]
    assert "just api-schema-check" in commands["generated-artifacts"]
    assert "just image-matrix-check" in commands["generated-artifacts"]
    proto = _mapping_at(jobs, "proto-breaking")
    proto_step = next(step for step in _mapping_list(proto["steps"]) if step.get("name") == "Check proto compatibility")
    assert _mapping_at(proto_step, "env")["BASE_SHA"] == (
        "${{ github.event.pull_request.base.sha || github.event.before }}"
    )
    assert "buf breaking --against '../.git#commit=${BASE_SHA},subdir=proto'" in commands["proto-breaking"]
    assert all("lefthook run pre-push" not in command for job in jobs.values() for command in _commands(job))


def test_python_tests_use_complete_bounded_category_matrix() -> None:
    workflow = _load_yaml(_CHECKS)
    jobs = _mapping(workflow["jobs"])
    python_tests = _mapping_at(jobs, "python-tests")
    strategy = _mapping_at(python_tests, "strategy")
    assert strategy["matrix"] == "${{ fromJSON(needs.changes.outputs.tests_matrix) }}"
    steps = {cast("str", step.get("name")): step for step in _mapping_list(python_tests["steps"])}
    nix_install = steps["Install Nix"]
    workspace_install = steps["Install workspace (all packages + extras)"]
    scoped_test = steps["Run scoped tests"]

    assert "if" not in nix_install
    assert nix_install["uses"] == ("DeterminateSystems/nix-installer-action@ef8a148080ab6020fd15196c2084a2eea5ff2d25")
    assert "if" not in workspace_install
    assert str(workspace_install["run"]).strip() == (
        "# shellcheck disable=SC2016 # $(command -v python) must expand inside the nix shell, not here\n"
        "nix develop .#ci --command bash -euc '\n"
        '  export UV_PYTHON="$(command -v python)"\n'
        "  uv sync --all-packages --all-extras --no-extra cuda --frozen\n"
        '  if [ "${{ matrix.scope }}" = "scripts" ]; then\n'
        "    pnpm install --frozen-lockfile\n"
        "  fi\n"
        "'"
    )
    assert "if" not in scoped_test
    assert str(scoped_test["run"]).strip() == (
        "# shellcheck disable=SC2016 # $(command -v python) must expand inside the nix shell, not here\n"
        "nix develop .#ci --command bash -euc '\n"
        '  export UV_PYTHON="$(command -v python)"\n'
        "  workers=2\n"
        '  if [ "${{ matrix.scope }}" = "scripts" ]; then\n'
        "    workers=1\n"
        "  fi\n"
        "  uv run --no-sync ci-checks tests all --scope ${{ matrix.scope }}"
        ' --packages "${{ matrix.packages }}" --ci --workers "$workers"\n'
        "'"
    )
    expected_env = {
        "OTEL_SDK_DISABLED": "true",
        "UV_NO_SYNC": "1",
        "COVERAGE_CORE": "sysmon",
    }
    assert scoped_test["env"] == expected_env
    assert "pnpm -C typescript/apps/frontend test --run" not in "\n".join(_commands(python_tests))
    assert "pnpm -C typescript/apps/frontend test --run --maxWorkers=25%" in "\n".join(
        _commands(jobs["frontend-tests"])
    )


def test_ci_self_tests_use_worksteal_xdist_without_dropping_package_coverage() -> None:
    with _CI_PROJECT.open("rb") as project_file:
        pytest_options = tomllib.load(project_file)["tool"]["pytest"]["ini_options"]
    assert pytest_options["addopts"] == "-n auto --dist=worksteal"
    workflow = _load_yaml(_CHECKS)
    hosted_command = "\n".join(_commands(_mapping_at(_mapping(workflow["jobs"]), "python-tests")))
    lefthook = _load_yaml(_LEFTHOOK)
    pre_push = _mapping_at(lefthook, "pre-push")
    local_command = next(
        str(nested["run"])
        for phase in _mapping_list(pre_push["jobs"])
        for nested in _mapping_list(_mapping(phase.get("group", {}))["jobs"])
        if nested.get("name") == "python-tests"
    )
    assert "--no-coverage" not in hosted_command
    assert "--no-coverage" not in local_command


def test_checks_aggregator_requires_every_hosted_lane() -> None:
    workflow = _load_yaml(_CHECKS)
    jobs = _mapping(workflow["jobs"])
    checks = _mapping_at(jobs, "checks")
    assert checks["name"] == "Checks"
    assert checks["if"] == "always()"
    needs = _strings(checks["needs"])
    assert set(needs) == set(jobs) - {"checks"}

    command = "\n".join(_commands(checks))
    for job in needs:
        if job != "commitlint":
            assert f"test '${{{{ needs.{job}.result }}}}' = success" in command
    assert "github.event_name }}' = push" in command
    assert "needs.commitlint.result }}' = skipped" in command
    assert "needs.commitlint.result }}' = success" in command


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
