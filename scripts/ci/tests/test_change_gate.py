import fnmatch
import os
import subprocess
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest
import typer
from ci_checks import app as ci_app_module
from ci_checks.checks import gate as checks_gate
from ci_checks.checks import tests as checks_tests
from ci_checks.checks.gate import gate_cmd
from ci_checks.core import packages as packages_module
from ci_checks.core.change_gate import (
    CommitClass,
    EventContext,
    GateDecision,
    ProtectedMainEvidence,
    evaluate,
    render_outputs,
    render_summary,
    selected_test_packages,
)
from ci_checks.core.change_rules import FLAG_NAMES, SURFACE_RULES
from ci_checks.core.display import LANE_DISPLAY_NAMES
from ci_checks.core.packages import (
    REPO_ROOT,
    Package,
    PackageType,
    Scope,
    build_reverse_dependency_index,
    expand_to_dependents,
    load_packages_with_deps,
)
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


@pytest.mark.parametrize(
    "changed",
    [
        {"mystery.bin"},
        {"uv.lock"},
        {"scripts/ci/src/ci_checks/core/change_gate.py"},
    ],
)
def test_evaluate_fails_closed_for_unmatched_and_broad_policy_files(
    changed: set[str],
) -> None:
    decision = evaluate(changed, _synthetic_packages())

    assert decision.full
    assert decision.reasons
    if changed == {"mystery.bin"}:
        assert decision.unmatched == ["mystery.bin"]
        assert decision.reasons == ["unmatched file: mystery.bin"]


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("docs/guide.md", CommitClass.STANDARD),
        ("backend/libs/lib-a/src/lib_a.py", CommitClass.STANDARD),
        (".github/workflows/checks.yml", CommitClass.BROAD),
        ("scripts/ci/src/ci_checks/core/change_rules.py", CommitClass.BROAD),
        ("scripts/ci/src/ci_checks/checks/gate.py", CommitClass.BROAD),
        ("scripts/ci/src/ci_checks/checks/internal_refs.py", CommitClass.BROAD),
        ("scripts/ci/src/ci_checks/checks/tests.py", CommitClass.BROAD),
        ("scripts/ci/src/ci_checks/core/repository.py", CommitClass.BROAD),
        ("scripts/ci/config/internal-reference-terms.toml", CommitClass.BROAD),
    ],
)
def test_commit_class_boundaries(path: str, expected: CommitClass) -> None:
    decision = evaluate(
        {path},
        _synthetic_packages(),
        EventContext(event="pull_request", base_sha="base", head_sha="head"),
    )

    assert decision.commit_class is expected
    assert not decision.unmatched


def test_unmapped_path_fails_closed_without_unrelated_frontend_smoke() -> None:
    decision = evaluate(
        {"unmapped/tracked.file"},
        _synthetic_packages(),
        EventContext(event="pull_request", base_sha="base", head_sha="head"),
    )

    assert decision.commit_class is CommitClass.BROAD
    assert decision.unmatched == ["unmapped/tracked.file"]
    assert "frontend_smoke" not in decision.flags
    assert decision.affected == set(_synthetic_packages())


def test_renovate_config_has_no_ci_effect() -> None:
    decision = evaluate(
        {".github/renovate.json5"},
        _synthetic_packages(),
        EventContext(event="pull_request", base_sha="base", head_sha="head"),
    )

    assert decision.commit_class is CommitClass.STANDARD
    assert not decision.unmatched
    assert not decision.flags
    assert not decision.affected


def test_checks_workflow_self_change_selects_every_lane() -> None:
    decision = evaluate(
        {".github/workflows/checks.yml"},
        _synthetic_packages(),
        EventContext(event="pull_request", base_sha="base", head_sha="head"),
    )

    assert decision.flags == set(FLAG_NAMES)


def test_uv_lock_selects_api_schema_freshness() -> None:
    decision = evaluate(
        {"uv.lock"},
        _synthetic_packages(),
        EventContext(event="pull_request", base_sha="base", head_sha="head"),
    )

    assert "api_schema_freshness" in decision.flags


def test_justfile_selects_owned_checks() -> None:
    decision = evaluate(
        {"Justfile"},
        _synthetic_packages(),
        EventContext(event="pull_request", base_sha="base", head_sha="head"),
    )

    assert {
        "api_schema_freshness",
        "image_matrix_parity",
        "proto_breaking",
    } <= decision.flags


def _valid_protected_evidence(head_sha: str = "head") -> ProtectedMainEvidence:
    return ProtectedMainEvidence(
        associated_pr_merged=True,
        merge_commit_sha=head_sha,
        checks_run_success=True,
        tested_tree_sha="tree",
        pushed_tree_sha="tree",
    )


def test_protected_main_broad_green_same_tree_selects_standard_smoke() -> None:
    decision = evaluate(
        {"uv.lock"},
        _synthetic_packages(),
        EventContext(
            event="push",
            base_sha="base",
            head_sha="head",
            ref_name="main",
            protected_main=_valid_protected_evidence(),
        ),
    )

    assert decision.commit_class is CommitClass.STANDARD
    assert decision.protected_main_smoke


@pytest.mark.parametrize(
    "evidence",
    [
        None,
        replace(_valid_protected_evidence(), associated_pr_merged=False),
        replace(_valid_protected_evidence(), merge_commit_sha=""),
        replace(_valid_protected_evidence(), merge_commit_sha="other"),
        replace(_valid_protected_evidence(), checks_run_success=False),
        replace(_valid_protected_evidence(), tested_tree_sha=""),
        replace(_valid_protected_evidence(), pushed_tree_sha=""),
        replace(_valid_protected_evidence(), tested_tree_sha="other"),
        replace(_valid_protected_evidence(), pushed_tree_sha="other"),
    ],
)
def test_protected_main_missing_or_mismatched_evidence_fails_closed(
    evidence: ProtectedMainEvidence | None,
) -> None:
    decision = evaluate(
        {"docs/guide.md"},
        _synthetic_packages(),
        EventContext(
            event="push",
            base_sha="base",
            head_sha="head",
            ref_name="main",
            protected_main=evidence,
        ),
    )

    assert decision.commit_class is CommitClass.BROAD
    assert not decision.protected_main_smoke


def test_initial_push_null_before_sha_fails_closed_even_with_valid_evidence() -> None:
    decision = evaluate(
        {"docs/guide.md"},
        _synthetic_packages(),
        EventContext(
            event="push",
            base_sha="0" * 40,
            head_sha="head",
            ref_name="main",
            protected_main=_valid_protected_evidence(),
        ),
    )

    assert decision.commit_class is CommitClass.BROAD
    assert decision.reasons == ["missing or null base ref"]


def test_missing_tested_sha_fails_closed() -> None:
    decision = evaluate(
        {"docs/guide.md"},
        _synthetic_packages(),
        EventContext(event="pull_request", base_sha="base", head_sha=""),
    )

    assert decision.commit_class is CommitClass.BROAD
    assert decision.reasons == ["missing or null tested SHA"]


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


def test_api_export_service_dependent_activates_schema_freshness() -> None:
    decision = evaluate({"backend/libs/lib-a/src/lib_a.py"}, _synthetic_packages())

    assert "bff-service" in decision.affected
    assert "api_schema_freshness" in decision.flags


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
            {"lint_frontend", "typecheck_frontend", "frontend_tests", "frontend_e2e"},
        ),
        (
            "typescript/apps/frontend/src/api/schema.d.ts",
            {
                "lint_frontend",
                "typecheck_frontend",
                "frontend_tests",
                "api_schema_freshness",
                "frontend_e2e",
            },
        ),
        (
            "typescript/apps/frontend/e2e/journeys/jobs.spec.ts",
            {"lint_frontend", "typecheck_frontend", "frontend_tests", "frontend_e2e"},
        ),
        (
            "typescript/edge/auth-listings-worker/src/index.ts",
            {"edge_worker"},
        ),
        (
            "typescript/libs/tsconfig/base.json",
            {
                "lint_frontend",
                "typecheck_frontend",
                "frontend_tests",
                "edge_worker",
                "frontend_e2e",
            },
        ),
    ],
)
def test_evaluate_typescript_surfaces_without_python(path: str, expected: set[str]) -> None:
    decision = evaluate({path}, _synthetic_packages())

    assert decision.flags == expected
    assert "python_any" not in decision.flags
    assert not decision.full


@pytest.mark.parametrize(
    "path",
    [
        "typescript/apps/frontend/index.html",
        "typescript/apps/frontend/package.json",
        "typescript/apps/frontend/vite.config.ts",
        "typescript/apps/frontend/Caddyfile",
    ],
)
def test_frontend_smoke_selects_only_build_contract_inputs(path: str) -> None:
    decision = evaluate({path}, _synthetic_packages())

    assert "frontend_smoke" in decision.flags


@pytest.mark.parametrize(
    "path",
    [
        "pnpm-lock.yaml",
        "package.json",
        "pnpm-workspace.yaml",
        "typescript/apps/frontend/e2e/playwright.config.ts",
        "typescript/apps/frontend/e2e/playwright.k8s.config.ts",
        "typescript/apps/frontend/Dockerfile.playwright-runner",
        "typescript/apps/frontend/e2e/journeys/jobs.spec.ts",
        "typescript/apps/frontend/package.json",
        "typescript/libs/biome-config/biome.json",
        "typescript/libs/tsconfig/base.json",
    ],
)
def test_frontend_e2e_selects_every_runner_image_input(path: str) -> None:
    assert "frontend_e2e" in evaluate({path}, _synthetic_packages()).flags


@pytest.mark.parametrize(
    "path",
    [
        "biome.json",
        "typescript/edge/auth-listings-worker/package.json",
    ],
)
def test_frontend_e2e_ignores_inputs_outside_the_runner_image(path: str) -> None:
    assert "frontend_e2e" not in evaluate({path}, _synthetic_packages()).flags


def test_flake_broad_change_selects_every_nix_runtime_owner() -> None:
    packages = load_packages_with_deps(Scope.ALL)
    decision = evaluate({"flake.nix"}, packages)

    assert decision.commit_class is CommitClass.BROAD
    assert {
        "nix",
        "lint_python",
        "typecheck_backend",
        "python_any",
        "hygiene",
        "lint_frontend",
        "typecheck_frontend",
        "frontend_tests",
        "edge_worker",
    } <= decision.flags
    assert not {"frontend_smoke", "frontend_e2e", "otel_collector"} & decision.flags
    expected_test_packages = tuple(sorted(name for name, package in packages.items() if package.has_tests))
    selected_tests = selected_test_packages(decision, packages)
    assert selected_tests == expected_test_packages
    assert render_outputs(decision, selected_tests, "pull_request")["test_packages"] == ",".join(expected_test_packages)


def test_broad_change_can_co_select_frontend_smoke_and_otel_collector() -> None:
    decision = evaluate(
        {
            "scripts/ci/src/ci_checks/core/change_rules.py",
            "typescript/apps/frontend/Dockerfile",
            "infra/k8s/observability/base/otel/collector.yaml",
        },
        load_packages_with_deps(Scope.ALL),
    )

    assert decision.commit_class is CommitClass.BROAD
    assert {"frontend_smoke", "frontend_e2e", "otel_collector"} <= decision.flags


def test_frontend_e2e_rule_patterns_each_match_a_tracked_path() -> None:
    tracked = set(
        subprocess.run(
            ["git", "ls-files"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
    )
    runner_rule = next(rule for rule in SURFACE_RULES if rule.flags == ("frontend_e2e",))

    for pattern in runner_rule.patterns:
        assert any(fnmatch.fnmatch(path, pattern) for path in tracked), pattern


def test_build_backend_selects_manifests_not_backend_leaf_sources() -> None:
    packages = _synthetic_packages()

    assert "build_backend" in evaluate({"scripts/tool-a/pyproject.toml"}, packages).flags
    assert "build_backend" in evaluate({"uv.lock"}, packages).flags
    assert "build_backend" not in evaluate({"backend/libs/lib-a/src/lib_a.py"}, packages).flags


@pytest.mark.parametrize(
    ("path", "expected_full", "flags"),
    [
        (
            "typescript/apps/frontend/Dockerfile",
            "false",
            {"frontend_smoke", "frontend_e2e", "lint_docker", "python_any", "hygiene"},
        ),
        (
            "typescript/apps/frontend/Dockerfile.playwright-runner",
            "false",
            {"frontend_e2e", "lint_docker", "python_any", "hygiene"},
        ),
        (
            "infra/k8s/observability/base/otel/collector.yaml",
            "false",
            {"otel_collector", "python_any", "hygiene"},
        ),
        (
            "scripts/util/export-openapi.py",
            "false",
            {"api_schema_freshness", "lint_python"},
        ),
        (
            "infra/k8s/local/images.json",
            "false",
            {"image_matrix_parity", "python_any", "hygiene"},
        ),
        (
            "unknown.bin",
            "true",
            {"lint_python", "python_any", "hygiene", "typecheck_backend"},
        ),
    ],
)
def test_evaluate_container_and_generated_surfaces(path: str, expected_full: str, flags: set[str]) -> None:
    decision = evaluate({path}, load_packages_with_deps(Scope.ALL))

    assert str(decision.full).lower() == expected_full
    assert decision.flags == flags


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
    selected = packages.keys() if decision.full else decision.affected
    expected_tests = tuple(sorted(name for name in selected if name in packages and packages[name].has_tests))
    assert selected_test_packages(decision, packages) == expected_tests


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


def test_selected_test_packages_full_and_scoped_exclude_packages_without_tests(
    tmp_path: Path,
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

    expected = ("a-service", "tested-lib", "z-service")
    assert selected_test_packages(GateDecision(full=True), packages) == expected
    assert selected_test_packages(GateDecision(affected=set(packages)), packages) == expected
    assert selected_test_packages(GateDecision(affected={"untested-lib"}), packages) == ()


def test_lane_display_names_cover_gate_flags_exactly() -> None:
    assert set(LANE_DISPLAY_NAMES) == set(FLAG_NAMES)


def test_render_outputs_serializes_flags_packages_and_event_contract() -> None:
    scoped = render_outputs(
        GateDecision(flags={"lint_python"}, affected={"svc-b", "lib-a"}),
        ("lib-a",),
        "push",
    )

    assert scoped["commit_class"] == "standard"
    assert scoped["standard"] == "true"
    assert scoped["broad"] == "false"
    assert scoped["protected_main_smoke"] == "false"
    assert scoped["lint_python"] == "true"
    assert scoped["nix"] == "false"
    assert (
        set(scoped.values())
        - {
            "true",
            "false",
            "standard",
            "lib-a,svc-b",
            "lib-a",
        }
        == set()
    )
    assert scoped["affected_packages"] == "lib-a,svc-b"
    assert scoped["test_packages"] == "lib-a"
    assert scoped["commitlint_expected"] == "false"
    assert render_outputs(GateDecision(), (), "pull_request")["commitlint_expected"] == "true"

    broad = render_outputs(GateDecision(full=True), (), "push")
    assert broad["commit_class"] == "broad"
    assert broad["standard"] == "false"
    assert broad["broad"] == broad["full"] == "true"
    assert all(broad[name] == "false" for name in FLAG_NAMES)


def test_render_summary_uses_friendly_lanes_and_checkmarks() -> None:
    decision = GateDecision(flags={"lint_markdown"})
    outputs = render_outputs(decision, (), "pull_request")

    summary = render_summary(decision, outputs, "pull_request", "base123", "head456")

    assert "`base123..head456`" in summary
    assert "Verdict: **standard**" in summary
    assert "| Markdown lint | ✓ |" in summary
    assert "| Python lint | — |" in summary
    assert all(f"| {name} |" in summary for name in LANE_DISPLAY_NAMES.values())
    assert "| lint_markdown |" not in summary
    assert "true" not in summary
    assert "false" not in summary


def test_render_summary_links_broad_class_file_reasons() -> None:
    decision = GateDecision(
        full=True,
        reasons=["broad policy source: uv.lock", "unmatched file: odd files/data.bin"],
        unmatched=["odd files/data.bin"],
    )
    outputs = render_outputs(decision, (), "pull_request")

    summary = render_summary(
        decision,
        outputs,
        "pull_request",
        "base123",
        "head456",
        repository="mchar7/nohiki-monorepo",
        head_sha="head456",
    )

    assert "**Broad-class reasons:**" in summary
    assert (
        "- broad policy source: [`uv.lock`](https://github.com/mchar7/nohiki-monorepo/blob/head456/uv.lock)"
    ) in summary
    assert (
        "- unmatched file: [`odd files/data.bin`]"
        "(https://github.com/mchar7/nohiki-monorepo/blob/head456/odd%20files/data.bin)"
    ) in summary
    assert all(
        line.startswith("- ") for line in summary.splitlines() if "trigger:" in line or "unmatched file:" in line
    )


def test_render_summary_keeps_paths_plain_without_github_context() -> None:
    decision = GateDecision(full=True, reasons=["unmatched file: mystery.bin"], unmatched=["mystery.bin"])
    outputs = render_outputs(decision, (), "push")

    summary = render_summary(decision, outputs, "push", "base", "HEAD")

    assert "- unmatched file: `mystery.bin`" in summary
    assert "https://github.com/" not in summary


def test_gate_diff_uses_exact_base_and_tested_shas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "one.py\ntwo.py\n", "")

    monkeypatch.setattr(checks_gate.subprocess, "run", run)

    assert checks_gate._diff_files("base", "tested") == {"one.py", "two.py"}
    assert calls == [["git", "diff", "--name-only", "--no-renames", "base..tested"]]


@pytest.mark.parametrize(
    ("event", "base_ref", "expected_full", "expected_diff_calls"),
    [
        ("push", "base123", "true", 1),
        ("pull_request", "base123", "false", 1),
        ("push", "0" * 40, "true", 0),
        ("workflow_dispatch", "base123", "true", 1),
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

    result = CliRunner().invoke(
        app,
        ["--event", event, "--base-ref", base_ref, "--github-output", str(output)],
    )

    assert result.exit_code == 0, result.output
    parsed = dict(line.split("=", maxsplit=1) for line in output.read_text().splitlines())
    assert parsed["full"] == expected_full
    assert len(calls) == expected_diff_calls
    if expected_full == "true":
        assert parsed["commit_class"] == "broad"
        assert parsed["broad"] == "true"
        assert parsed["standard"] == "false"
        assert parsed["test_packages"] == ",".join(
            selected_test_packages(GateDecision(full=True), _synthetic_packages())
        )
        assert parsed["frontend_smoke"] == "false"
    else:
        assert parsed["lint_markdown"] == "true"
        assert parsed["hygiene"] == "false"
        assert parsed["test_packages"] == ""


def test_gate_cli_selects_every_lane_when_the_diff_cannot_be_resolved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unresolvable diff must fail closed across flag-only consumers, not just the class."""

    def failing_diff(_base: str, _head: str) -> set[str]:
        message = "fatal: bad object base123"
        raise RuntimeError(message)

    monkeypatch.setattr(checks_gate, "_diff_files", failing_diff)
    monkeypatch.setattr(checks_gate, "load_packages_with_deps", lambda _scope: _synthetic_packages())
    app = typer.Typer()
    app.command("gate")(gate_cmd)
    output = tmp_path / "github-output"

    result = CliRunner().invoke(
        app,
        [
            "--event",
            "pull_request",
            "--base-ref",
            "base123",
            "--github-output",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.output
    parsed = dict(line.split("=", maxsplit=1) for line in output.read_text().splitlines())
    assert parsed["full"] == "true"
    # Container contracts and the Playwright image dispatch on their flag alone, so a broad
    # class does not reach them; every lane must be selected when the router knows nothing.
    assert [flag for flag in FLAG_NAMES if parsed[flag] != "true"] == []


def test_gate_cli_consumes_protected_main_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(checks_gate, "_diff_files", lambda _base, _head: {"uv.lock"})
    monkeypatch.setattr(checks_gate, "load_packages_with_deps", lambda _scope: _synthetic_packages())
    output = tmp_path / "github-output"
    app = typer.Typer()
    app.command("gate")(gate_cmd)

    result = CliRunner().invoke(
        app,
        [
            "--event",
            "push",
            "--base-ref",
            "base",
            "--head-ref",
            "head",
            "--ref-name",
            "main",
            "--github-output",
            str(output),
        ],
        env={
            "CI_ASSOCIATED_PR_MERGED": "true",
            "CI_MERGE_COMMIT_SHA": "head",
            "CI_CHECKS_RUN_SUCCESS": "true",
            "CI_TESTED_TREE_SHA": "tree",
            "CI_PUSHED_TREE_SHA": "tree",
        },
    )

    assert result.exit_code == 0, result.output
    parsed = dict(line.split("=", maxsplit=1) for line in output.read_text().splitlines())
    assert parsed["commit_class"] == "standard"
    assert parsed["standard"] == "true"
    assert parsed["broad"] == parsed["full"] == "false"
    assert parsed["protected_main_smoke"] == "true"


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


_FAKE_GH = r"""#!/usr/bin/env python3
import json
import os
import pathlib
import shutil
import sys

args = sys.argv[1:]
fixture_data = json.loads(pathlib.Path(os.environ["FAKE_GH_FIXTURES"]).read_text(encoding="utf-8"))
fixture = fixture_data[os.environ["FAKE_GH_SCENARIO"]]
log = pathlib.Path(os.environ["FAKE_GH_LOG"])
with log.open("a", encoding="utf-8") as stream:
    stream.write("\t".join(args) + "\n")

if args and args[0] == "api":
    endpoint = args[1]
    if endpoint.endswith("/pulls"):
        if fixture.get("fail_api") == "pulls":
            print("recorded API failure", file=sys.stderr)
            raise SystemExit(9)
        payload = fixture["pulls"]
    elif "/actions/workflows/checks.yml/runs" in endpoint:
        payload = fixture["runs"]
    elif "/commits/" in endpoint:
        payload = fixture["commit"]
    else:
        print("unexpected API endpoint: " + endpoint, file=sys.stderr)
        raise SystemExit(97)
    print(json.dumps(payload))
    raise SystemExit(0)

if args[:2] == ["run", "download"]:
    run_id = args[2]
    attestation = fixture["attestations"].get(run_id)
    if attestation is None:
        print("recorded artifact absence", file=sys.stderr)
        raise SystemExit(8)
    destination = pathlib.Path(args[args.index("--dir") + 1])
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "checks-attestation.json").write_text(json.dumps(attestation), encoding="utf-8")
    raise SystemExit(0)

print("unexpected gh argv: " + json.dumps(args), file=sys.stderr)
raise SystemExit(97)
"""

_EVIDENCE_FIXTURES = REPO_ROOT / "scripts/ci/tests/fixtures/gate_evidence_scenarios.json"


@pytest.fixture
def gate_evidence_harness(tmp_path: Path) -> tuple[dict[str, str], Path]:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    gh = bindir / "gh"
    gh.write_text(_FAKE_GH, encoding="utf-8")
    gh.chmod(0o755)
    log = tmp_path / "gh.log"
    environment = {
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "FAKE_GH_FIXTURES": str(_EVIDENCE_FIXTURES),
        "FAKE_GH_LOG": str(log),
    }
    return environment, log


def _run_gate_evidence(
    tmp_path: Path,
    harness: tuple[dict[str, str], Path],
    scenario: str,
) -> tuple[dict[str, str], list[list[str]], str]:
    environment, log = harness
    github_env = tmp_path / f"{scenario}.env"
    result = CliRunner().invoke(
        ci_app_module.app,
        [
            "gate-evidence",
            "--event",
            "push",
            "--repository",
            "mchar7/nohiki-monorepo",
            "--head-sha",
            "merge-sha",
            "--github-env",
            str(github_env),
        ],
        env=environment | {"FAKE_GH_SCENARIO": scenario},
    )
    assert result.exit_code == 0, result.output
    values = dict(line.split("=", maxsplit=1) for line in github_env.read_text(encoding="utf-8").splitlines())
    calls = [line.split("\t") for line in log.read_text(encoding="utf-8").splitlines()]
    return values, calls, result.output


def test_gate_evidence_extracts_success_through_fake_gh_subprocess(
    tmp_path: Path,
    gate_evidence_harness: tuple[dict[str, str], Path],
) -> None:
    values, calls, _output = _run_gate_evidence(tmp_path, gate_evidence_harness, "success")

    assert values == {
        "CI_ASSOCIATED_PR_MERGED": "true",
        "CI_MERGE_COMMIT_SHA": "merge-sha",
        "CI_CHECKS_RUN_SUCCESS": "true",
        "CI_TESTED_TREE_SHA": "tree-merge",
        "CI_PUSHED_TREE_SHA": "tree-merge",
    }
    assert any(call[:3] == ["run", "download", "101"] for call in calls)


def test_gate_evidence_exposes_merge_ref_tree_mismatch_for_fail_closed_gate(
    tmp_path: Path,
    gate_evidence_harness: tuple[dict[str, str], Path],
) -> None:
    values, _calls, _output = _run_gate_evidence(tmp_path, gate_evidence_harness, "tree_mismatch")
    evidence = ProtectedMainEvidence(
        associated_pr_merged=values["CI_ASSOCIATED_PR_MERGED"] == "true",
        merge_commit_sha=values["CI_MERGE_COMMIT_SHA"],
        checks_run_success=values["CI_CHECKS_RUN_SUCCESS"] == "true",
        tested_tree_sha=values["CI_TESTED_TREE_SHA"],
        pushed_tree_sha=values["CI_PUSHED_TREE_SHA"],
    )

    assert values["CI_TESTED_TREE_SHA"] == "tree-merge-ref"
    assert values["CI_PUSHED_TREE_SHA"] == "tree-pushed"
    assert not evidence.proves_broad_tree("merge-sha")


def test_gate_evidence_missing_latest_artifact_falls_back_to_older_attested_run(
    tmp_path: Path,
    gate_evidence_harness: tuple[dict[str, str], Path],
) -> None:
    values, calls, _output = _run_gate_evidence(tmp_path, gate_evidence_harness, "title_only_latest")
    downloads = [call[2] for call in calls if call[:2] == ["run", "download"]]

    assert values["CI_CHECKS_RUN_SUCCESS"] == "true"
    assert values["CI_TESTED_TREE_SHA"] == "tree-merge"
    assert downloads == ["102", "101"]


def test_gate_evidence_ignores_failed_latest_run(
    tmp_path: Path,
    gate_evidence_harness: tuple[dict[str, str], Path],
) -> None:
    values, calls, _output = _run_gate_evidence(tmp_path, gate_evidence_harness, "failed_latest")
    downloads = [call[2] for call in calls if call[:2] == ["run", "download"]]

    assert values["CI_CHECKS_RUN_SUCCESS"] == "true"
    assert downloads == ["101"]


def test_gate_evidence_selects_latest_of_multiple_successful_runs(
    tmp_path: Path,
    gate_evidence_harness: tuple[dict[str, str], Path],
) -> None:
    values, calls, _output = _run_gate_evidence(tmp_path, gate_evidence_harness, "multiple_runs")
    downloads = [call[2] for call in calls if call[:2] == ["run", "download"]]

    assert values["CI_TESTED_TREE_SHA"] == "tree-latest"
    assert downloads == ["104"]


@pytest.mark.parametrize("scenario", ["stale_base", "api_failure", "ambiguous_pr"])
def test_gate_evidence_failures_emit_empty_evidence(
    tmp_path: Path,
    gate_evidence_harness: tuple[dict[str, str], Path],
    scenario: str,
) -> None:
    values, _calls, output = _run_gate_evidence(tmp_path, gate_evidence_harness, scenario)

    assert values == {
        "CI_ASSOCIATED_PR_MERGED": "false",
        "CI_MERGE_COMMIT_SHA": "",
        "CI_CHECKS_RUN_SUCCESS": "false",
        "CI_TESTED_TREE_SHA": "",
        "CI_PUSHED_TREE_SHA": "",
    }
    assert "Protected-main evidence unavailable:" in output


def _consumer_packages(tmp_path: Path) -> list[Package]:
    return [Package(name, tmp_path / name, PackageType.LIB) for name in ("first", "second")]


def test_deptry_packages_filters_within_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    available = _consumer_packages(tmp_path)
    captured: list[str] = []

    async def scan(
        selected: list[Package],
        _scanner: object,
        _workers: int,
        _console: Console,
        *,
        ci_mode: bool,
        ci_suffix: object,
    ) -> list[object]:
        del ci_mode, ci_suffix
        captured.extend(package.name for package in selected)
        return []

    monkeypatch.setattr(ci_app_module, "load_packages", lambda _scope, **_kwargs: available)
    monkeypatch.setattr(ci_app_module, "scan_parallel", scan)
    monkeypatch.setattr(ci_app_module._deptry, "render_results", lambda _results: True)

    result = CliRunner().invoke(ci_app_module.app, ["deptry", "--packages", "second"])

    assert result.exit_code == 0, result.output
    assert captured == ["second"]


def test_deadcode_packages_filters_within_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    available = _consumer_packages(tmp_path)
    captured: list[str] = []

    async def scan(selected: list[Package], _options: object) -> list[object]:
        captured.extend(package.name for package in selected)
        return []

    monkeypatch.setattr(ci_app_module, "load_packages", lambda _scope, **_kwargs: available)
    monkeypatch.setattr(ci_app_module._deadcode, "scan_scope", scan)
    monkeypatch.setattr(
        ci_app_module._deadcode,
        "render_results",
        lambda _results, *, fail_on_findings: not fail_on_findings or True,
    )

    result = CliRunner().invoke(ci_app_module.app, ["deadcode", "--packages", "second", "--ci"])

    assert result.exit_code == 0, result.output
    assert captured == ["second"]


def test_build_backend_packages_filters_within_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    available = _consumer_packages(tmp_path)
    captured: list[str] = []

    def scan(package: Package) -> object:
        captured.append(package.name)
        return object()

    monkeypatch.setattr(ci_app_module, "load_packages", lambda _scope, **_kwargs: available)
    monkeypatch.setattr(ci_app_module._build_backend, "scan_package", scan)
    monkeypatch.setattr(
        ci_app_module._build_backend,
        "render_results",
        lambda _results, *, strict: not strict or True,
    )

    result = CliRunner().invoke(ci_app_module.app, ["build-backend", "--packages", "first"])

    assert result.exit_code == 0, result.output
    assert captured == ["first"]


def test_consumer_packages_intersects_command_eligibility(tmp_path: Path) -> None:
    first, second = _consumer_packages(tmp_path)

    assert ci_app_module._filter_packages([first], "second", {first.name, second.name}) == []


@pytest.mark.parametrize("command", ["deptry", "build-backend"])
def test_consumer_packages_empty_csv_is_noop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
) -> None:
    monkeypatch.setattr(
        ci_app_module,
        "load_packages",
        lambda _scope, **_kwargs: _consumer_packages(tmp_path),
    )

    result = CliRunner().invoke(ci_app_module.app, [command, "--packages", ""])

    assert result.exit_code == 0, result.output
    assert "selected" in result.output


@pytest.mark.parametrize("command", ["deptry", "build-backend"])
def test_consumer_packages_unknown_name_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
) -> None:
    monkeypatch.setattr(
        ci_app_module,
        "load_packages",
        lambda _scope, **_kwargs: _consumer_packages(tmp_path),
    )

    result = CliRunner().invoke(ci_app_module.app, [command, "--packages", "missing"])

    assert result.exit_code == 2
    assert "Unknown packages" in result.output
