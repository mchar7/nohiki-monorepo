import json
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
import typer
from ci_checks.checks import gate as checks_gate
from ci_checks.checks import tests as checks_tests
from ci_checks.checks.gate import gate_cmd
from ci_checks.core import change_gate as change_gate_module
from ci_checks.core import packages as packages_module
from ci_checks.core.change_gate import (
    GateDecision,
    evaluate,
    render_outputs,
    render_summary,
)
from ci_checks.core.change_gate import (
    tests_matrix as build_tests_matrix,
)
from ci_checks.core.change_rules import FLAG_NAMES
from ci_checks.core.display import GATE_LABELS, LANE_DISPLAY_NAMES
from ci_checks.core.packages import (
    REPO_ROOT,
    Package,
    PackageType,
    Scope,
    build_reverse_dependency_index,
    expand_to_dependents,
    load_packages_with_deps,
)
from ci_checks.core.test_batches import TestBatch as BatchSpec
from rich.console import Console
from typer.testing import CliRunner


def _synthetic_packages() -> dict[str, Package]:
    return {
        "lib-a": Package("lib-a", REPO_ROOT / "backend/libs/lib-a", PackageType.LIB),
        "nohiki-domain-models": Package(
            "nohiki-domain-models",
            REPO_ROOT / "backend" / "libs" / "nohiki-domain-models",
            PackageType.LIB,
        ),
        "tool-a": Package(
            "tool-a",
            REPO_ROOT / "scripts" / "tool-a",
            PackageType.SCRIPTS,
        ),
        "svc-b": Package(
            "svc-b",
            REPO_ROOT / "backend/services/svc-b",
            PackageType.SERVICE,
            frozenset({"lib-a"}),
        ),
        "svc-c": Package(
            "svc-c",
            REPO_ROOT / "backend/services/svc-c",
            PackageType.SERVICE,
            frozenset({"lib-a"}),
        ),
        "bff-service": Package(
            "bff-service",
            REPO_ROOT / "backend/services/bff-service",
            PackageType.SERVICE,
            frozenset({"lib-a"}),
        ),
    }


@pytest.mark.parametrize("changed", [{"mystery.bin"}, {"uv.lock"}, {"scripts/ci/src/ci_checks/app.py"}])
def test_evaluate_fails_closed_for_unmatched_and_global_files(
    changed: set[str],
) -> None:
    decision = evaluate(changed, _synthetic_packages())

    assert decision.full
    assert decision.reasons
    if changed == {"mystery.bin"}:
        assert decision.unmatched == ["mystery.bin"]
        assert decision.reasons == ["unmatched file: mystery.bin"]


@pytest.mark.parametrize(
    ("path", "expected_flags"),
    [
        (".markdownlintignore", {"lint_markdown"}),
        ("scripts/tool-a/pyproject.toml", {"hygiene", "typecheck_backend"}),
        (
            "proto/foo.proto",
            {"lint_proto", "proto_breaking", "hygiene", "typecheck_backend"},
        ),
        ("backend/services/svc-b/Dockerfile.dev", {"lint_docker"}),
    ],
)
def test_evaluate_path_lane_contract(path: str, expected_flags: set[str]) -> None:
    decision = evaluate({path}, _synthetic_packages())

    assert not decision.full
    assert expected_flags <= decision.flags


def test_evaluate_package_change_expands_runtime_and_test_extra_dependents() -> None:
    packages = _synthetic_packages()
    non_python = evaluate({"backend/libs/lib-a/README.txt"}, packages)
    python = evaluate({"backend/libs/lib-a/src/lib_a.py"}, packages)

    assert non_python.affected == {"lib-a", "svc-b", "svc-c", "bff-service"}
    assert "lint_python" not in non_python.flags
    assert python.affected == non_python.affected
    assert {"lint_python", "python_any", "hygiene", "typecheck_backend"} <= python.flags


def test_api_export_service_dependent_activates_generated_artifacts() -> None:
    decision = evaluate({"backend/libs/lib-a/src/lib_a.py"}, _synthetic_packages())

    assert "bff-service" in decision.affected
    assert "generated_artifacts" in decision.flags


def test_proto_change_seeds_domain_models_and_real_test_extra_dependents() -> None:
    packages = load_packages_with_deps(Scope.ALL)
    decision = evaluate({"proto/foo.proto"}, packages)

    assert {"lint_proto", "proto_breaking"} <= decision.flags
    assert "nohiki-domain-models" in decision.affected
    reverse = build_reverse_dependency_index(packages)
    assert "job-ingest-enrichment-service" in expand_to_dependents({"nohiki-test-utils"}, reverse)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (
            "typescript/apps/frontend/src/App.tsx",
            {"lint_frontend", "typecheck_frontend", "frontend_tests", "frontend_smoke"},
        ),
        (
            "typescript/apps/frontend/src/api/schema.d.ts",
            {
                "lint_frontend",
                "typecheck_frontend",
                "frontend_tests",
                "frontend_smoke",
                "generated_artifacts",
            },
        ),
    ],
)
def test_evaluate_frontend_flags_without_python(path: str, expected: set[str]) -> None:
    decision = evaluate({path}, _synthetic_packages())

    assert decision.flags == expected
    assert "python_any" not in decision.flags
    assert not decision.full


def test_evaluate_deleted_package_path_still_maps_to_owner() -> None:
    decision = evaluate({"backend/libs/lib-a/src/deleted_forever.py"}, _synthetic_packages())

    assert "lib-a" in decision.affected
    assert "lint_python" in decision.flags


def test_evaluate_infra_change_seeds_ci_checks() -> None:
    packages = load_packages_with_deps(Scope.ALL)

    assert "ci-checks" in evaluate({"infra/k8s/helm/values.yaml"}, packages).affected


def test_evaluate_alembic_change_seeds_ci_checks() -> None:
    packages = load_packages_with_deps(Scope.ALL)
    changed = {"backend/services/user-pref-service/alembic/versions/001_initial_migration.py"}

    assert "ci-checks" in evaluate(changed, packages).affected


@pytest.mark.parametrize(
    ("path", "full", "affected", "present", "absent"),
    [
        (
            "scripts/ci/src/ci_checks/checks/freshness.py",
            "false",
            {"ci-checks"},
            {"python_any"},
            set(),
        ),
        (
            "scripts/ci/src/ci_checks/core/change_gate.py",
            "true",
            set(),
            set(),
            set(),
        ),
        (
            "infra/k8s/helm/values.prod.digests.yaml",
            "false",
            {"ci-checks"},
            {"python_any", "hygiene"},
            {"typecheck_backend"},
        ),
        (
            "backend/libs/nohiki-test-utils/src/nohiki_test_utils/utils/docker.py",
            "false",
            {"nohiki-test-utils"},
            {"hygiene", "typecheck_backend"},
            set(),
        ),
    ],
)
def test_evaluate_precision_for_ci_engine_contract_seeds_and_python_sources(
    path: str,
    full: str,
    affected: set[str],
    present: set[str],
    absent: set[str],
) -> None:
    packages = load_packages_with_deps(Scope.ALL)

    decision = evaluate({path}, packages)

    assert str(decision.full).lower() == full
    assert affected <= decision.affected
    assert present <= decision.flags
    assert decision.flags.isdisjoint(absent)
    if affected:
        matrix_packages = {
            name for entry in build_tests_matrix(decision, packages)["include"] for name in entry["packages"].split(",")
        }
        assert affected <= matrix_packages


def test_dependency_loader_reads_runtime_extras_and_pep735_groups(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "pyproject.toml").write_text('[tool.uv.workspace]\nmembers = ["pkg"]\n')
    package_dir = tmp_path / "pkg"
    package_dir.mkdir()
    (package_dir / "pyproject.toml").write_text(
        """[project]
name = "fixture-package"
dependencies = ["runtime-dep>=1"]

[project.optional-dependencies]
test = ["test-extra[feature]>=2"]

[dependency-groups]
dev = ["group-dep==3", {include-group = "lint"}]
lint = ["lint-dep"]
"""
    )
    monkeypatch.setattr(packages_module, "REPO_ROOT", tmp_path)

    package = packages_module.load_packages_with_deps(Scope.ALL)["fixture-package"]

    assert package.deps == frozenset({"runtime-dep", "test-extra", "group-dep", "lint-dep"})
    graph = {
        "runtime-dep": Package("runtime-dep", tmp_path / "runtime", PackageType.LIB),
        "fixture-package": package,
        "downstream": Package(
            "downstream",
            tmp_path / "downstream",
            PackageType.SERVICE,
            frozenset({"fixture-package"}),
        ),
    }
    reverse = build_reverse_dependency_index(graph)
    assert reverse["runtime-dep"] == {"fixture-package"}
    assert expand_to_dependents({"runtime-dep"}, reverse) == {
        "runtime-dep",
        "fixture-package",
        "downstream",
    }


def test_tests_matrix_full_and_scoped_excludes_packages_without_tests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package_specs = (
        ("z-service", PackageType.SERVICE, True),
        ("a-service", PackageType.SERVICE, True),
        ("untested-lib", PackageType.LIB, False),
        ("tested-lib", PackageType.LIB, True),
    )
    packages: dict[str, Package] = {}
    for name, package_type, has_tests in package_specs:
        path = tmp_path / name
        path.mkdir()
        if has_tests:
            (path / "tests").mkdir()
        packages[name] = Package(name, path, package_type)
    monkeypatch.setattr(
        change_gate_module,
        "load_test_batches",
        lambda: (
            BatchSpec(name="batch-1", packages=("z-service", "a-service"), needs_pnpm=True),
            BatchSpec(name="batch-2", packages=("untested-lib",), needs_pnpm=False),
            BatchSpec(name="batch-3", packages=("tested-lib",), needs_pnpm=False),
        ),
    )

    full = build_tests_matrix(GateDecision(full=True), packages)
    assert full == {
        "include": [
            {"batch": "batch-1", "packages": "a-service,z-service", "needs_pnpm": True},
            {"batch": "batch-3", "packages": "tested-lib", "needs_pnpm": False},
        ]
    }

    scoped = build_tests_matrix(GateDecision(affected=set(packages)), packages)
    assert scoped == full


def test_lane_display_names_cover_gate_flags_exactly() -> None:
    assert set(LANE_DISPLAY_NAMES) == set(FLAG_NAMES)


def test_gate_labels_have_distinct_stable_colors() -> None:
    assert GATE_LABELS == {
        "python_any": ("area:backend", "1D76DB"),
        "frontend_tests": ("area:frontend", "D4C5F9"),
        "lint_proto": ("area:proto", "FBCA04"),
        "lint_docker": ("area:docker", "0E8A16"),
        "lint_workflows": ("area:workflows", "5319E7"),
        "lint_markdown": ("area:docs", "0075CA"),
        "full": ("ci:full-run", "B60205"),
    }
    assert len({color for _, color in GATE_LABELS.values()}) == len(GATE_LABELS)


def test_render_outputs_serializes_flags_matrix_and_event_contract() -> None:
    matrix = {"include": [{"batch": "batch-2", "packages": "lib-a", "needs_pnpm": False}]}
    scoped = render_outputs(GateDecision(flags={"lint_python"}), matrix, "push")

    assert scoped["lint_python"] == "true"
    assert scoped["nix"] == "false"
    assert set(scoped.values()) - {"true", "false", scoped["tests_matrix"]} == set()
    assert json.loads(scoped["tests_matrix"]) == matrix
    assert scoped["tests_matrix"] == ('{"include":[{"batch":"batch-2","packages":"lib-a","needs_pnpm":false}]}')
    assert scoped["commitlint_expected"] == "false"
    assert render_outputs(GateDecision(), {"include": []}, "pull_request")["commitlint_expected"] == "true"

    full = render_outputs(GateDecision(full=True), {"include": []}, "push")
    assert all(full[name] == "true" for name in FLAG_NAMES)


def test_render_summary_uses_friendly_lanes_and_checkmarks() -> None:
    decision = GateDecision(flags={"lint_markdown"})
    outputs = render_outputs(decision, {"include": []}, "pull_request")

    summary = render_summary(decision, outputs, "pull_request", "base123", "head456")

    assert "`base123...head456`" in summary
    assert "Verdict: scoped run" in summary
    assert "| Markdown lint | ✓ |" in summary
    assert "| Python lint | — |" in summary
    assert all(f"| {name} |" in summary for name in LANE_DISPLAY_NAMES.values())
    assert "| lint_markdown |" not in summary
    assert "true" not in summary
    assert "false" not in summary


def test_render_summary_links_full_run_file_reasons() -> None:
    decision = GateDecision(
        full=True,
        reasons=["global trigger: uv.lock", "unmatched file: odd files/data.bin"],
        unmatched=["odd files/data.bin"],
    )
    outputs = render_outputs(decision, {"include": []}, "pull_request")

    summary = render_summary(
        decision,
        outputs,
        "pull_request",
        "base123",
        "head456",
        repository="mchar7/nohiki-monorepo",
        head_sha="head456",
    )

    assert "**Full-run reasons:**" in summary
    assert ("- global trigger: [`uv.lock`](https://github.com/mchar7/nohiki-monorepo/blob/head456/uv.lock)") in summary
    assert (
        "- unmatched file: [`odd files/data.bin`]"
        "(https://github.com/mchar7/nohiki-monorepo/blob/head456/odd%20files/data.bin)"
    ) in summary
    assert all(
        line.startswith("- ") for line in summary.splitlines() if "trigger:" in line or "unmatched file:" in line
    )


def test_render_summary_keeps_paths_plain_without_github_context() -> None:
    decision = GateDecision(full=True, reasons=["unmatched file: mystery.bin"], unmatched=["mystery.bin"])
    outputs = render_outputs(decision, {"include": []}, "push")

    summary = render_summary(decision, outputs, "push", "base", "HEAD")

    assert "- unmatched file: `mystery.bin`" in summary
    assert "https://github.com/" not in summary


@pytest.mark.parametrize(
    ("event", "base_ref", "expected_full", "expected_diff_calls"),
    [
        ("push", "base123", "true", 0),
        ("pull_request", "base123", "false", 1),
        ("push", "0" * 40, "true", 0),
        ("workflow_dispatch", "base123", "true", 0),
    ],
)
def test_gate_cli_scopes_only_supported_events_with_usable_base(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    event: str,
    base_ref: str,
    expected_full: str,
    expected_diff_calls: int,
) -> None:
    app = typer.Typer()
    app.command("gate")(gate_cmd)
    output = tmp_path / "github-output"
    calls: list[tuple[str, str]] = []

    def diff_files(base: str, head: str) -> set[str]:
        calls.append((base, head))
        return {"docs/guide.md"}

    monkeypatch.setattr(checks_gate, "_diff_files", diff_files)
    monkeypatch.setattr(checks_gate, "load_packages_with_deps", lambda _scope: _synthetic_packages())
    monkeypatch.setattr(
        change_gate_module,
        "load_test_batches",
        lambda: (BatchSpec(name="batch-1", packages=tuple(_synthetic_packages()), needs_pnpm=False),),
    )

    result = CliRunner().invoke(
        app,
        ["--event", event, "--base-ref", base_ref, "--github-output", str(output)],
    )

    assert result.exit_code == 0, result.output
    parsed = dict(line.split("=", maxsplit=1) for line in output.read_text().splitlines())
    assert parsed["full"] == expected_full
    assert len(calls) == expected_diff_calls
    if expected_full == "true":
        assert all(parsed[flag] == "true" for flag in FLAG_NAMES)
        assert json.loads(parsed["tests_matrix"])["include"] == [
            {
                "batch": "batch-1",
                "packages": "bff-service,nohiki-domain-models",
                "needs_pnpm": False,
            }
        ]
        assert json.loads(parsed["labels"]) == [
            {"name": name, "color": color, "active": "true"} for name, color in GATE_LABELS.values()
        ]
    else:
        assert parsed["lint_markdown"] == "true"
        assert parsed["hygiene"] == "false"
        assert json.loads(parsed["tests_matrix"]) == {"include": []}


def test_gate_cli_uses_repository_env_for_sticky_comment_links(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(checks_gate, "_diff_files", lambda _base, _head: {"uv.lock"})
    app = typer.Typer()
    app.command("gate")(gate_cmd)
    comment = tmp_path / "gate-comment.md"

    result = CliRunner().invoke(
        app,
        [
            "--event",
            "pull_request",
            "--base-ref",
            "base123",
            "--head-ref",
            "head456",
            "--comment-file",
            str(comment),
        ],
        env={"GITHUB_REPOSITORY": "mchar7/nohiki-monorepo"},
    )

    assert result.exit_code == 0, result.output
    body = comment.read_text()
    assert body.startswith("<!-- nohiki-change-gate -->\n")
    assert "[`uv.lock`](https://github.com/mchar7/nohiki-monorepo/blob/head456/uv.lock)" in body


def test_get_changed_files_raises_on_staged_git_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(_args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(_args, 1, "", "staged failure")

    monkeypatch.setattr(checks_tests.subprocess, "run", fail)

    with pytest.raises(RuntimeError, match="staged failure"):
        checks_tests.get_changed_files(checks_tests.GitMode.STAGED)


def test_get_changed_files_push_raises_and_uses_three_dot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[:3] == ["git", "rev-parse", "--abbrev-ref"]:
            return subprocess.CompletedProcess(args, 0, "feature\n", "")
        if args[:2] == ["git", "rev-parse"]:
            return subprocess.CompletedProcess(args, 0, "abc123\n", "")
        return subprocess.CompletedProcess(args, 1, "", "push failure")

    monkeypatch.setattr(checks_tests.subprocess, "run", run)

    with pytest.raises(RuntimeError, match="push failure"):
        checks_tests.get_changed_files(checks_tests.GitMode.PUSH)
    assert calls[-1] == ["git", "diff", "--name-only", "--no-renames", "abc123...HEAD"]


def _successful_runner(captured: list[str]) -> Callable[..., object]:
    async def run(
        packages: list[Package],
        _markers: str,
        _extra_args: tuple[str, ...],
        _workers: int,
        _console: Console,
        *,
        ci_mode: bool,
        with_coverage: bool,
    ) -> list[checks_tests.TestResult]:
        del ci_mode, with_coverage
        captured.extend(package.name for package in packages)
        return [checks_tests.TestResult(package.name, passed=True, pkg_type=package.pkg_type) for package in packages]

    return run


def _real_testable_packages() -> dict[str, Package]:
    return {name: package for name, package in load_packages_with_deps(Scope.ALL).items() if package.has_tests}


@pytest.mark.parametrize("failure", [RuntimeError("git failed"), {REPO_ROOT / "mystery.bin"}])
def test_affected_cli_fails_closed_to_full_testable_set(
    monkeypatch: pytest.MonkeyPatch, failure: RuntimeError | set[Path]
) -> None:
    all_packages = load_packages_with_deps(Scope.ALL)
    expected = {name for name, package in all_packages.items() if package.has_tests}
    captured: list[str] = []
    monkeypatch.setattr(packages_module, "load_packages_with_deps", lambda _scope: all_packages)
    if isinstance(failure, RuntimeError):

        def changed(_mode: checks_tests.GitMode) -> set[Path]:
            raise failure

        monkeypatch.setattr(checks_tests, "get_changed_files", changed)
    else:
        monkeypatch.setattr(checks_tests, "get_changed_files", lambda _mode: failure)
    monkeypatch.setattr(checks_tests, "run_tests_parallel", _successful_runner(captured))

    result = CliRunner().invoke(checks_tests.tests_app, ["affected", "--no-coverage", "--ci"])

    assert result.exit_code == 0, result.output
    assert set(captured) == expected


def test_affected_cli_schedules_only_changed_lib_and_dependents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    all_packages = load_packages_with_deps(Scope.ALL)
    testable = _real_testable_packages()
    assert "nohiki-test-utils" in testable
    changed = REPO_ROOT / "backend/libs/nohiki-test-utils/src/deleted.py"
    expected_decision = evaluate({changed.relative_to(REPO_ROOT).as_posix()}, all_packages)
    expected = {name for name in expected_decision.affected if name in testable}
    captured: list[str] = []
    monkeypatch.setattr(packages_module, "load_packages_with_deps", lambda _scope: all_packages)
    monkeypatch.setattr(checks_tests, "get_changed_files", lambda _mode: {changed})
    monkeypatch.setattr(checks_tests, "run_tests_parallel", _successful_runner(captured))

    result = CliRunner().invoke(checks_tests.tests_app, ["affected", "--no-coverage", "--ci"])

    assert result.exit_code == 0, result.output
    assert set(captured) == expected
    assert "job-ingest-enrichment-service" in captured


def test_all_cli_rejects_unknown_package(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    package = tmp_path / "known"
    (package / "tests").mkdir(parents=True)
    monkeypatch.setattr(
        checks_tests,
        "_load_testable_packages",
        lambda _scope: [Package("known", package, PackageType.LIB)],
    )

    result = CliRunner().invoke(checks_tests.tests_app, ["all", "--packages", "missing", "--no-coverage"])

    assert result.exit_code == 2


@pytest.mark.parametrize(
    ("selection", "expected"),
    [("second,first", ["first", "second"]), ("ALL", ["first", "second"])],
)
def test_all_cli_filters_valid_csv_and_all_sentinel(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, selection: str, expected: list[str]
) -> None:
    packages = []
    for name in ("first", "second"):
        path = tmp_path / name
        (path / "tests").mkdir(parents=True)
        packages.append(Package(name, path, PackageType.LIB))
    captured: list[str] = []
    monkeypatch.setattr(checks_tests, "_load_testable_packages", lambda _scope: packages)
    monkeypatch.setattr(checks_tests, "run_tests_parallel", _successful_runner(captured))

    result = CliRunner().invoke(
        checks_tests.tests_app,
        ["all", "--packages", selection, "--no-coverage", "--ci"],
    )

    assert result.exit_code == 0, result.output
    assert captured == expected


def test_standalone_python_file_still_lints() -> None:
    """A rule-matched .py outside every workspace package must lint."""
    packages = load_packages_with_deps(Scope.ALL)
    decision = evaluate({"scripts/util/export-openapi.py"}, packages)
    assert not decision.full
    assert "lint_python" in decision.flags
