import fnmatch
import json
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
    BroadCause,
    BroadReason,
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
from ci_checks.core.display import LANE_DISPLAY_NAMES, LANE_RUNNERS
from ci_checks.core.image_inventory import load_inventory
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
        assert decision.reasons == [
            BroadReason(BroadCause.UNMATCHED_PATH, "unmatched file: mystery.bin", "mystery.bin")
        ]


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


@pytest.mark.parametrize(
    "path",
    [
        ".github/renovate.json5",
        ".github/dependabot.yml",
        ".gitignore",
        ".gitleaks.toml",
        "docs/api/nohiki.openapi.json",
    ],
)
def test_cheap_classified_paths_still_seed_their_contract_test_package(path: str) -> None:
    """A path a ci-checks contract test reads must run that suite, however cheap the path looks."""
    decision = evaluate(
        {path},
        load_packages_with_deps(Scope.ALL),
        EventContext(event="pull_request", base_sha="base", head_sha="head"),
    )

    assert decision.commit_class is CommitClass.STANDARD
    assert not decision.unmatched
    assert "ci-checks" in decision.affected


def test_inert_paths_select_no_lane_and_no_package() -> None:
    decision = evaluate(
        {"commitlint.config.mjs"},
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


def test_setup_ci_composite_change_is_broad_with_an_enumerated_blast_radius() -> None:
    """The composite provisions the toolchain every calling job runs in, so it is broad by rule."""
    decision = evaluate(
        {".github/actions/setup-ci/action.yml"},
        _synthetic_packages(),
        EventContext(event="pull_request", base_sha="base", head_sha="head"),
    )

    assert decision.commit_class is CommitClass.BROAD
    assert not decision.unmatched
    assert not decision.broad_unbounded
    assert render_outputs(decision, (), "pull_request")["broad_unbounded"] == "false"
    # playwright-image is the sole frontend_e2e consumer and never calls the composite.
    assert decision.flags == set(FLAG_NAMES) - {"frontend_e2e"}


def test_composite_action_paths_select_actionlint_and_their_contract_suite() -> None:
    """Local action metadata moves the actionlint verdict, and test_dependency_pins reads it."""
    decision = evaluate({".github/actions/release/action.yml"}, load_packages_with_deps(Scope.ALL))

    assert decision.commit_class is CommitClass.STANDARD
    assert not decision.unmatched
    assert "lint_workflows" in decision.flags
    assert "ci-checks" in decision.affected


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

    assert {"api_schema_freshness", "image_matrix_parity"} <= decision.flags
    # The workflow runs buf breaking inline; the Justfile recipe is local-only.
    assert "proto_breaking" not in decision.flags


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
    assert decision.reasons == [BroadReason(BroadCause.MISSING_SHA, "missing or null base ref")]


def test_missing_tested_sha_fails_closed() -> None:
    decision = evaluate(
        {"docs/guide.md"},
        _synthetic_packages(),
        EventContext(event="pull_request", base_sha="base", head_sha=""),
    )

    assert decision.commit_class is CommitClass.BROAD
    assert decision.reasons == [BroadReason(BroadCause.MISSING_SHA, "missing or null tested SHA")]


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
            {"lint_frontend", "lint_steiger", "typecheck_frontend", "frontend_tests", "frontend_smoke"},
        ),
        (
            "typescript/apps/frontend/e2e/journeys/jobs.spec.ts",
            {"lint_frontend", "typecheck_frontend", "frontend_smoke", "node_workspace_contracts"},
        ),
        (
            "typescript/edge/auth-listings-worker/src/index.ts",
            {"edge_worker"},
        ),
        (
            "typescript/libs/tsconfig/base.json",
            {
                "lint_frontend",
                "lint_steiger",
                "typecheck_frontend",
                "frontend_tests",
                "edge_worker",
                "frontend_smoke",
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
        ".dockerignore",
        "package.json",
        "pnpm-lock.yaml",
        "pnpm-workspace.yaml",
        "typescript/apps/frontend/Dockerfile",
        "typescript/apps/frontend/index.html",
        "typescript/apps/frontend/package.json",
        "typescript/apps/frontend/tsconfig.app.json",
        "typescript/apps/frontend/vite.config.ts",
        "typescript/apps/frontend/vitest.config.ts",
        "typescript/apps/frontend/Caddyfile",
        "typescript/apps/frontend/src/App.tsx",
        "typescript/apps/frontend/public/locales/en/common.json",
        "typescript/apps/frontend/e2e/journeys/jobs.spec.ts",
        "typescript/edge/auth-listings-worker/package.json",
        "typescript/libs/tsconfig/base.json",
        "scripts/ci/tests/test_frontend_delivery.py",
    ],
)
def test_frontend_smoke_selects_every_image_build_context_input(path: str) -> None:
    assert "frontend_smoke" in evaluate({path}, _synthetic_packages()).flags


@pytest.mark.parametrize("path", ["package.json", "pnpm-lock.yaml", "pnpm-workspace.yaml"])
def test_steiger_selects_every_root_node_toolchain_input(path: str) -> None:
    assert "lint_steiger" in evaluate({path}, _synthetic_packages()).flags


@pytest.mark.parametrize(
    "path",
    [
        "typescript/apps/frontend/knip.ts",
        "typescript/apps/frontend/steiger.config.ts",
        "typescript/apps/frontend/components.json",
        "typescript/apps/frontend/biome.jsonc",
        "typescript/apps/frontend/scripts/i18n-check.mjs",
        "typescript/libs/biome-config/biome.json",
    ],
)
def test_frontend_smoke_ignores_context_files_the_image_build_never_reads(path: str) -> None:
    assert "frontend_smoke" not in evaluate({path}, _synthetic_packages()).flags


@pytest.mark.parametrize(
    "path",
    [
        ".dockerignore",
        "package.json",
        "pnpm-lock.yaml",
        "pnpm-workspace.yaml",
        "typescript/apps/frontend/Dockerfile.playwright-runner",
        "typescript/apps/frontend/package.json",
        "typescript/libs/biome-config/package.json",
        "typescript/libs/tsconfig/package.json",
    ],
)
def test_frontend_e2e_selects_every_runner_image_input(path: str) -> None:
    assert "frontend_e2e" in evaluate({path}, _synthetic_packages()).flags


@pytest.mark.parametrize(
    "path",
    [
        "biome.json",
        "typescript/edge/auth-listings-worker/package.json",
        # Copied into the image after its last RUN, so no source content can
        # change what `playwright --version` reports.
        "typescript/apps/frontend/src/App.tsx",
        "typescript/apps/frontend/e2e/journeys/jobs.spec.ts",
        "typescript/apps/frontend/e2e/playwright.config.ts",
        "typescript/apps/frontend/public/locales/en/common.json",
        "typescript/apps/frontend/vite.config.ts",
        "typescript/apps/frontend/Dockerfile",
        "typescript/libs/biome-config/biome.json",
        "typescript/libs/tsconfig/base.json",
    ],
)
def test_frontend_e2e_ignores_inputs_outside_the_runner_image(path: str) -> None:
    assert "frontend_e2e" not in evaluate({path}, _synthetic_packages()).flags


@pytest.mark.parametrize(
    "path",
    [
        "package.json",
        "pnpm-lock.yaml",
        "pnpm-workspace.yaml",
        "typescript/apps/frontend/package.json",
        # Executed, not read: two tests import this config under node and a third lists it.
        "typescript/apps/frontend/e2e/playwright.k8s.config.ts",
        # The k8s config spreads it, so it reaches every assertion the marked tests make.
        "typescript/apps/frontend/e2e/playwright.config.ts",
        # `playwright test --list` collects these and the third test compares the set.
        "typescript/apps/frontend/e2e/journeys/jobs.spec.ts",
        "scripts/ci/tests/test_local_verification_jobs.py",
    ],
)
def test_node_workspace_contracts_selects_every_input_the_marked_tests_execute(path: str) -> None:
    assert "node_workspace_contracts" in evaluate({path}, _synthetic_packages()).flags


@pytest.mark.parametrize(
    "path",
    [
        # Playwright's testDir is the config's own directory, so no app source is collected.
        "typescript/apps/frontend/src/App.tsx",
        "typescript/apps/frontend/public/locales/en/common.json",
        "typescript/apps/frontend/vite.config.ts",
        "typescript/apps/frontend/Dockerfile",
        "typescript/apps/frontend/Dockerfile.playwright-runner",
        "typescript/libs/tsconfig/base.json",
        # A different ci-checks module: it carries no requires_node_modules test.
        "scripts/ci/tests/test_frontend_delivery.py",
    ],
)
def test_node_workspace_contracts_ignores_paths_the_marked_tests_never_execute(path: str) -> None:
    assert "node_workspace_contracts" not in evaluate({path}, _synthetic_packages()).flags


def test_flake_broad_change_selects_every_devshell_sourced_lane() -> None:
    packages = load_packages_with_deps(Scope.ALL)
    decision = evaluate({"flake.nix"}, packages)

    assert decision.commit_class is CommitClass.BROAD
    assert {
        "nix",
        "lint_python",
        "typecheck_backend",
        "python_any",
        "hygiene",
        "build_backend",
        "lint_proto",
        "lint_workflows",
        "lint_docker",
        "proto_breaking",
        "image_matrix_parity",
        "api_schema_freshness",
        # container-contracts has no broad disjunct, so only these two can select it.
        "frontend_smoke",
        "otel_collector",
    } <= decision.flags
    # The frontend unit takes pnpm and Node from actions/setup-node, not the devshell.
    assert not {"lint_frontend", "typecheck_frontend", "frontend_tests", "edge_worker"} & decision.flags
    # playwright-image builds and runs bare docker, never entering the devshell.
    assert "frontend_e2e" not in decision.flags
    expected_test_packages = tuple(sorted(name for name, package in packages.items() if package.has_tests))
    selected_tests = selected_test_packages(decision, packages)
    assert selected_tests == expected_test_packages
    assert render_outputs(decision, selected_tests, "pull_request")["test_packages"] == ",".join(expected_test_packages)


def test_broad_change_can_co_select_frontend_smoke_and_otel_collector() -> None:
    decision = evaluate(
        {
            "scripts/ci/src/ci_checks/core/change_rules.py",
            "typescript/apps/frontend/Dockerfile",
            "typescript/apps/frontend/Dockerfile.playwright-runner",
            "infra/k8s/observability/base/otel/collector.yaml",
        },
        load_packages_with_deps(Scope.ALL),
    )

    assert decision.commit_class is CommitClass.BROAD
    assert {"frontend_smoke", "frontend_e2e", "otel_collector"} <= decision.flags


def _tracked_paths() -> set[str]:
    return set(
        subprocess.run(
            ["git", "ls-files"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
    )


@pytest.mark.parametrize("flag", ["frontend_e2e", "frontend_smoke"])
def test_container_image_rule_patterns_each_match_a_tracked_path(flag: str) -> None:
    tracked = _tracked_paths()

    for rule in SURFACE_RULES:
        if rule.flags != (flag,):
            continue
        for pattern in rule.patterns:
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
            {"frontend_smoke", "lint_docker", "python_any", "hygiene", "typecheck_backend"},
        ),
        (
            "typescript/apps/frontend/Dockerfile.playwright-runner",
            "false",
            {"frontend_e2e", "lint_docker", "python_any", "hygiene", "typecheck_backend"},
        ),
        (
            "infra/k8s/observability/base/otel/collector.yaml",
            "false",
            {"otel_collector", "python_any", "hygiene", "typecheck_backend"},
        ),
        (
            "scripts/util/export-openapi.py",
            "false",
            {"api_schema_freshness", "lint_python"},
        ),
        (
            "infra/k8s/local/images.json",
            "false",
            {"image_matrix_parity", "python_any", "hygiene", "typecheck_backend"},
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
            {"python_any", "typecheck_backend"},
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
            {"python_any", "hygiene", "typecheck_backend"},
            set(),
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


def test_lane_display_names_and_runners_cover_gate_flags_exactly() -> None:
    assert set(LANE_DISPLAY_NAMES) == set(LANE_RUNNERS) == set(FLAG_NAMES)


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
    assert json.loads(scoped["worker_units"]) == ["python", "frontend"]
    assert (
        set(scoped.values())
        - {
            "true",
            "false",
            "standard",
            "lib-a,svc-b",
            "lib-a",
            '["python","frontend"]',
        }
        == set()
    )
    assert scoped["affected_packages"] == "lib-a,svc-b"
    assert scoped["test_packages"] == "lib-a"
    assert scoped["commitlint_expected"] == "false"
    assert render_outputs(GateDecision(), (), "pull_request")["commitlint_expected"] == "true"
    assert json.loads(render_outputs(GateDecision(), (), "pull_request")["worker_units"]) == ["frontend"]

    broad = render_outputs(GateDecision(full=True), (), "push")
    assert broad["commit_class"] == "broad"
    assert broad["standard"] == "false"
    assert broad["broad"] == broad["full"] == "true"
    assert all(broad[name] == "false" for name in FLAG_NAMES)
    assert json.loads(broad["worker_units"]) == ["python", "frontend"]


def test_pnpm_manifest_breach_emits_both_payload_legs() -> None:
    packages = load_packages_with_deps(Scope.ALL)
    decision = evaluate(
        {
            "package.json",
            "pnpm-lock.yaml",
            "pnpm-workspace.yaml",
            "typescript/edge/auth-listings-worker/package.json",
        },
        packages,
    )
    outputs = render_outputs(decision, selected_test_packages(decision, packages), "pull_request")

    assert decision.commit_class is CommitClass.STANDARD
    assert json.loads(outputs["worker_units"]) == ["python", "frontend"]


def test_protected_main_smoke_emits_only_the_python_payload_leg() -> None:
    decision = GateDecision(protected_main_smoke=True)

    assert json.loads(render_outputs(decision, (), "push")["worker_units"]) == ["python"]


def _policy_reason(path: str) -> BroadReason:
    return BroadReason(BroadCause.POLICY_SOURCE, f"broad policy source: {path}", path)


def _unmatched_reason(path: str) -> BroadReason:
    return BroadReason(BroadCause.UNMATCHED_PATH, f"unmatched file: {path}", path)


def test_render_summary_uses_friendly_lanes_and_names_the_owning_bin() -> None:
    decision = GateDecision(flags={"lint_markdown"})
    outputs = render_outputs(decision, (), "pull_request")

    summary = render_summary(decision, outputs, "pull_request", "base123", "head456")

    assert "`base123..head456`" in summary
    assert "| Commit class | **standard** |" in summary
    assert "| Markdown lint | ✓ | frontend |" in summary
    assert "| Python lint | — | frontend |" in summary
    assert all(f"| {name} |" in summary for name in LANE_DISPLAY_NAMES.values())
    assert "| lint_markdown |" not in summary
    assert "true" not in summary
    assert "false" not in summary


def test_render_summary_marks_every_lane_selected_on_a_broad_verdict() -> None:
    """Broad runs every lane while carrying no lane flags, so flags alone would render 20 dashes."""
    decision = GateDecision(full=True, reasons=[_policy_reason("uv.lock")])
    outputs = render_outputs(decision, (), "push")

    summary = render_summary(decision, outputs, "push", "base123", "head456")

    assert all(outputs[flag] == "false" for flag in FLAG_NAMES)
    assert "Broad class selects every lane." in summary
    assert "—" not in summary
    assert summary.count("| ✓ |") == len(FLAG_NAMES)


def test_render_summary_groups_reasons_and_leads_with_unclassified_paths() -> None:
    decision = GateDecision(
        full=True,
        # Policy first in source order, to prove the grouping reorders rather than echoing input.
        reasons=[
            _policy_reason("uv.lock"),
            _unmatched_reason("odd files/data.bin"),
            BroadReason(BroadCause.MISSING_SHA, "base sha is unusable"),
        ],
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

    unclassified = summary.index("**Unclassified paths (1).**")
    policy = summary.index("**Broad policy sources (1).**")
    # An unclassified path means the gate never decided, which outranks policy doing its job.
    assert unclassified < policy
    assert "fails closed to broad instead of deciding" in summary
    assert (
        "- [`odd files/data.bin`](https://github.com/mchar7/nohiki-monorepo/blob/head456/odd%20files/data.bin)"
    ) in summary
    assert "- [`uv.lock`](https://github.com/mchar7/nohiki-monorepo/blob/head456/uv.lock)" in summary
    # The group heading carries the category, so repeating it on every bullet is noise.
    assert "- unmatched file:" not in summary
    assert "- broad policy source:" not in summary
    # A cause carrying no path must still be reported, not silently dropped between the groups.
    assert "**Other broad-class reasons (1):**" in summary
    assert "- base sha is unusable" in summary


def test_render_summary_keeps_paths_plain_without_github_context() -> None:
    decision = GateDecision(full=True, reasons=[_unmatched_reason("mystery.bin")], unmatched=["mystery.bin"])
    outputs = render_outputs(decision, (), "push")

    summary = render_summary(decision, outputs, "push", "base", "HEAD")

    assert "**Unclassified paths (1).**" in summary
    assert "- `mystery.bin`" in summary
    assert "https://github.com/" not in summary


def test_render_summary_collapses_the_affected_package_list() -> None:
    """48 comma-joined names is a wall; the count is the signal and the list is on demand."""
    decision = GateDecision(flags={"lint_python"}, affected={f"pkg-{index:02d}" for index in range(48)})
    outputs = render_outputs(decision, (), "push")

    summary = render_summary(decision, outputs, "push", "base", "HEAD")

    assert "<details><summary>Affected packages (48)</summary>" in summary
    assert "`pkg-00`, `pkg-01`" in summary
    assert "</details>" in summary


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
        if fixture.get("fail_api") == "runs":
            print("recorded API failure", file=sys.stderr)
            raise SystemExit(9)
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


def _checked_out_tree() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD^{tree}"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=True,
    )
    return result.stdout.strip()


def _reuse_fixture(tmp_path: Path, tree_sha: str) -> Path:
    """Write fake-gh scenarios whose attested tree is the tree the command will resolve."""

    def runs(*ids: int) -> dict[str, object]:
        return {
            "workflow_runs": [
                {
                    "id": run_id,
                    "name": "Checks",
                    "event": "pull_request",
                    "status": "completed",
                    "conclusion": "success",
                    "head_sha": "pr-head",
                }
                for run_id in ids
            ]
        }

    def attested(run_id: int, **overrides: object) -> dict[str, object]:
        record: dict[str, object] = {
            "tested_tree_sha": tree_sha,
            "event_action": "synchronize",
            "commit_class": "standard",
            "run_id": run_id,
            "base_sha": "base-sha",
        }
        return record | overrides

    legacy = {key: value for key, value in attested(204).items() if key != "base_sha"}
    scenarios: dict[str, object] = {
        "proven": {"runs": runs(201), "attestations": {"201": attested(201)}},
        "tree_mismatch": {
            "runs": runs(202),
            "attestations": {"202": attested(202, tested_tree_sha="a-different-tree")},
        },
        # The retarget hole: an ancestor base leaves the tree identical, so only base binding
        # separates this from a genuine title edit.
        "base_retargeted": {
            "runs": runs(203),
            "attestations": {"203": attested(203, base_sha="a-different-base")},
        },
        "legacy_without_base": {"runs": runs(204), "attestations": {"204": legacy}},
        "only_edited": {
            "runs": runs(205),
            "attestations": {"205": attested(205, event_action="edited")},
        },
        "artifact_expired": {"runs": runs(206), "attestations": {}},
        "no_successful_run": {"runs": {"workflow_runs": []}, "attestations": {}},
        "api_failure": {"fail_api": "runs", "runs": {}, "attestations": {}},
    }
    path = tmp_path / "reuse_scenarios.json"
    path.write_text(json.dumps(scenarios), encoding="utf-8")
    return path


def _run_gate_reuse(
    tmp_path: Path,
    harness: tuple[dict[str, str], Path],
    scenario: str,
    fixtures: Path,
    action: str = "edited",
) -> dict[str, str]:
    environment, _log = harness
    github_output = tmp_path / f"{scenario}.out"
    result = CliRunner().invoke(
        ci_app_module.app,
        [
            "gate-reuse",
            "--event",
            "pull_request",
            "--action",
            action,
            "--repository",
            "mchar7/nohiki-monorepo",
            "--pr-head-sha",
            "pr-head",
            "--base-sha",
            "base-sha",
            "--github-output",
            str(github_output),
        ],
        env=environment | {"FAKE_GH_SCENARIO": scenario, "FAKE_GH_FIXTURES": str(fixtures)},
    )
    assert result.exit_code == 0, result.output
    return dict(line.split("=", maxsplit=1) for line in github_output.read_text(encoding="utf-8").splitlines())


def test_gate_reuse_proves_a_title_edit_and_names_the_run_it_relied_on(
    tmp_path: Path,
    gate_evidence_harness: tuple[dict[str, str], Path],
) -> None:
    fixtures = _reuse_fixture(tmp_path, _checked_out_tree())
    values = _run_gate_reuse(tmp_path, gate_evidence_harness, "proven", fixtures)

    assert values == {"title_only": "true", "reused_run_id": "201"}


@pytest.mark.parametrize(
    "scenario",
    [
        "tree_mismatch",
        "base_retargeted",
        "legacy_without_base",
        "only_edited",
        "artifact_expired",
        "no_successful_run",
        "api_failure",
    ],
)
def test_gate_reuse_fails_closed_on_every_unproven_path(
    tmp_path: Path,
    gate_evidence_harness: tuple[dict[str, str], Path],
    scenario: str,
) -> None:
    fixtures = _reuse_fixture(tmp_path, _checked_out_tree())
    values = _run_gate_reuse(tmp_path, gate_evidence_harness, scenario, fixtures)

    assert values == {"title_only": "false", "reused_run_id": ""}


def test_gate_reuse_defines_both_outputs_without_calling_github_off_an_edit(
    tmp_path: Path,
    gate_evidence_harness: tuple[dict[str, str], Path],
) -> None:
    _environment, log = gate_evidence_harness
    fixtures = _reuse_fixture(tmp_path, _checked_out_tree())
    values = _run_gate_reuse(tmp_path, gate_evidence_harness, "proven", fixtures, action="synchronize")

    # The renderer reads these on every event, so a skipped lookup must still define them.
    assert values == {"title_only": "false", "reused_run_id": ""}
    assert not log.exists()


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


def test_schema_types_and_committed_spec_seed_their_contract_test() -> None:
    """The api-schema-check recipe diffs only the generated types; test_upload_api_schema reads both."""
    packages = load_packages_with_deps(Scope.ALL)

    types = evaluate({"typescript/apps/frontend/src/api/schema.d.ts"}, packages)
    spec = evaluate({"docs/api/nohiki.openapi.json"}, packages)

    assert "api_schema_freshness" in types.flags
    assert "ci-checks" in types.affected
    assert "api_schema_freshness" not in spec.flags
    assert "ci-checks" in spec.affected


@pytest.mark.parametrize("path", [".markdownlint-cli2.jsonc", ".markdownlint.json", ".markdownlintignore"])
def test_markdownlint_configs_select_the_markdown_lane(path: str) -> None:
    decision = evaluate({path}, _synthetic_packages())

    assert decision.flags == {"lint_markdown"}
    assert not decision.full


@pytest.mark.parametrize(
    "path",
    [
        "typescript/edge/auth-listings-worker/wrangler.toml",
        "semgrep-overrides.txt",
        "backend/services/ml-compute-service/pyproject.toml",
        "package.json",
        "pnpm-lock.yaml",
    ],
)
def test_single_file_contract_inputs_seed_ci_checks(path: str) -> None:
    assert "ci-checks" in evaluate({path}, load_packages_with_deps(Scope.ALL)).affected


def test_container_only_assertion_files_select_the_job_that_runs_them() -> None:
    """Both assertions are requires_docker, which the Python lane deselects."""
    packages = load_packages_with_deps(Scope.ALL)

    assert "otel_collector" in evaluate({"scripts/ci/tests/test_otel_collector_manifest.py"}, packages).flags
    assert "frontend_smoke" in evaluate({"scripts/ci/tests/test_frontend_delivery.py"}, packages).flags


@pytest.mark.parametrize(
    "path",
    [
        "typescript/apps/frontend/e2e/journeys/jobs.spec.ts",
        "typescript/apps/frontend/e2e/playwright.config.ts",
        "typescript/apps/frontend/e2e/pages/login.page.ts",
    ],
)
def test_e2e_specs_lint_and_typecheck_without_running_vitest(path: str) -> None:
    """vitest.config.ts excludes **/e2e/**, so a Playwright spec cannot move that verdict."""
    flags = evaluate({path}, _synthetic_packages()).flags

    assert {"lint_frontend", "typecheck_frontend"} <= flags
    assert "frontend_tests" not in flags


@pytest.mark.parametrize(
    "path",
    [
        "typescript/apps/frontend/.ast-grep/sgconfig.yml",
        "typescript/apps/frontend/.ast-grep/rules/no-memo-ts.yaml",
        "typescript/apps/frontend/components.json",
        "typescript/apps/frontend/knip.ts",
    ],
)
def test_frontend_tooling_configs_select_no_lane_without_falling_broad(path: str) -> None:
    """No checks.yml step runs ast-grep or knip, and biome, tsc and vitest all exclude them."""
    decision = evaluate({path}, _synthetic_packages())

    assert not decision.full
    assert decision.flags == set()


def test_steiger_config_selects_architecture_lane_without_falling_broad() -> None:
    decision = evaluate({"typescript/apps/frontend/steiger.config.ts"}, _synthetic_packages())

    assert not decision.full
    assert decision.flags == {"lint_steiger"}


def test_lefthook_config_selects_its_contract_test_not_the_nix_lane() -> None:
    """`nix flake check` builds the binary from flake.nix and the version step compares a literal."""
    decision = evaluate({"lefthook.yml"}, load_packages_with_deps(Scope.ALL))

    assert "nix" not in decision.flags
    assert "ci-checks" in decision.affected


# Representative native-ty packages outside the backend service and library families.
_TYPECHECKED_SOURCES: tuple[tuple[str, str, PackageType], ...] = (
    (
        "skill-semantic-analysis",
        "scripts/ml/skill_semantic_analysis/src/skill_semantic_analysis/cli.py",
        PackageType.SCRIPTS,
    ),
    ("ci-checks", "scripts/ci/src/ci_checks/checks/freshness.py", PackageType.SCRIPTS),
    ("tailor", "scripts/util/tailor/src/tailor/main.py", PackageType.SCRIPTS),
    ("llm-benchmark", "scripts/benchmark/src/llm_benchmark/main.py", PackageType.SCRIPTS),
    ("qdrant-init", "infra/shared/qdrant-init/src/qdrant_init/main.py", PackageType.OTHER),
)


@pytest.mark.parametrize(("package", "source", "pkg_type"), _TYPECHECKED_SOURCES)
def test_source_change_selects_typecheck_for_every_package_the_step_reads(
    package: str,
    source: str,
    pkg_type: PackageType,
) -> None:
    """A source change selects native ty on the standard class regardless of package type."""
    packages = load_packages_with_deps(Scope.ALL)
    assert packages[package].pkg_type is pkg_type

    decision = evaluate(
        {source},
        packages,
        EventContext(event="pull_request", base_sha="base", head_sha="head"),
    )

    assert decision.commit_class is CommitClass.STANDARD
    assert package in decision.affected
    assert decision.flag_value("typecheck_backend")


@pytest.mark.parametrize(
    ("source", "package"),
    [
        ("tests/integration/test_smoke.py", "nohiki-integration-tests"),
        ("infra/k8s/gitops/tests/test_bootstrap.py", "gitops-contract-tests"),
    ],
)
def test_virtual_workspace_members_select_native_typecheck(source: str, package: str) -> None:
    packages = load_packages_with_deps(Scope.ALL)
    decision = evaluate({source}, packages)
    assert package in decision.affected
    assert decision.flag_value("typecheck_backend")


_UNBOUNDED_CASES: tuple[tuple[str, set[str], EventContext], ...] = (
    ("unmatched path", {"mystery.bin"}, EventContext(event="pull_request", base_sha="base", head_sha="head")),
    ("null base sha", {"docs/guide.md"}, EventContext(event="pull_request", base_sha="0" * 40, head_sha="head")),
    ("missing head sha", {"docs/guide.md"}, EventContext(event="pull_request", base_sha="base", head_sha="")),
    ("unsupported event", {"docs/guide.md"}, EventContext(event="schedule", base_sha="base", head_sha="head")),
    (
        "protected-main mismatch",
        {"docs/guide.md"},
        EventContext(event="push", base_sha="base", head_sha="head", ref_name="main"),
    ),
)


@pytest.mark.parametrize(("label", "changed", "context"), _UNBOUNDED_CASES, ids=[case[0] for case in _UNBOUNDED_CASES])
def test_broad_unbounded_reports_causes_that_enumerate_no_blast_radius(
    label: str,
    changed: set[str],
    context: EventContext,
) -> None:
    """Each fail-closed cause leaves the affected surface unknown, so every lane must run."""
    decision = evaluate(changed, _synthetic_packages(), context)

    assert decision.commit_class is CommitClass.BROAD, label
    assert decision.broad_unbounded, label
    assert render_outputs(decision, (), context.event)["broad_unbounded"] == "true", label


@pytest.mark.parametrize("path", ["uv.lock", "flake.nix", "flake.lock", ".python-version"])
def test_broad_unbounded_is_false_for_triggers_whose_rule_names_what_they_select(path: str) -> None:
    """A policy source is broad by rule, and that rule already enumerates its own lanes."""
    decision = evaluate(
        {path},
        _synthetic_packages(),
        EventContext(event="pull_request", base_sha="base", head_sha="head"),
    )

    assert decision.commit_class is CommitClass.BROAD
    assert not decision.broad_unbounded
    assert render_outputs(decision, (), "pull_request")["broad_unbounded"] == "false"


def test_broad_unbounded_takes_the_unbounded_cause_when_both_kinds_are_present() -> None:
    decision = evaluate(
        {"uv.lock", "mystery.bin"},
        _synthetic_packages(),
        EventContext(event="pull_request", base_sha="base", head_sha="head"),
    )

    assert [reason.cause for reason in decision.reasons] == [
        BroadCause.UNMATCHED_PATH,
        BroadCause.POLICY_SOURCE,
    ]
    assert decision.broad_unbounded


@pytest.mark.parametrize(
    ("changed", "context"),
    [
        ({"docs/guide.md"}, EventContext(event="pull_request", base_sha="base", head_sha="head")),
        (
            {"mystery.bin"},
            EventContext(
                event="push",
                base_sha="base",
                head_sha="head",
                ref_name="main",
                protected_main=_valid_protected_evidence(),
            ),
        ),
    ],
)
def test_broad_unbounded_is_false_whenever_the_verdict_is_not_broad(
    changed: set[str],
    context: EventContext,
) -> None:
    """A proven protected-main smoke withdraws the broad verdict, and the split follows it."""
    decision = evaluate(changed, _synthetic_packages(), context)

    assert decision.commit_class is CommitClass.STANDARD
    assert not decision.broad_unbounded


def test_broad_unbounded_is_the_only_output_the_cause_can_move() -> None:
    """Two broad decisions differing only in cause must differ only in the new output."""
    bounded = GateDecision(
        full=True,
        reasons=[BroadReason(BroadCause.POLICY_SOURCE, "broad policy source: uv.lock", "uv.lock")],
    )
    unbounded = GateDecision(
        full=True,
        reasons=[BroadReason(BroadCause.UNMATCHED_PATH, "unmatched file: mystery.bin", "mystery.bin")],
    )

    bounded_outputs = render_outputs(bounded, (), "push")
    unbounded_outputs = render_outputs(unbounded, (), "push")

    assert bounded_outputs["broad_unbounded"] == "false"
    assert unbounded_outputs["broad_unbounded"] == "true"
    assert {key: value for key, value in bounded_outputs.items() if key != "broad_unbounded"} == {
        key: value for key, value in unbounded_outputs.items() if key != "broad_unbounded"
    }
    # Not a lane: keeping it out of FLAG_NAMES keeps it out of the lane table, the summary
    # and the workflow's flag-driven outputs contract until a consumer is wired deliberately.
    assert "broad_unbounded" not in FLAG_NAMES
    assert set(bounded_outputs) == set(FLAG_NAMES) | {
        "commit_class",
        "standard",
        "broad",
        "broad_unbounded",
        "protected_main_smoke",
        "full",
        "affected_packages",
        "test_packages",
        "worker_units",
        "commitlint_expected",
    }


_RECORD_HEAD_SHA = "9c1d4b7a2e5f80c3d6a9b2e5f8014b7ad3c6e9f2"


def _run_gate_producer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    diff: Callable[[str, str], set[str]],
    *,
    event: str = "push",
    base_ref: str = "base123",
    with_record: bool = True,
    label: str = "gate",
) -> tuple[int, str, dict[str, str], Path]:
    """Drive the gate CLI and return its exit code, output, emitted outputs and record path."""
    monkeypatch.setattr(checks_gate, "_diff_files", diff)
    monkeypatch.setattr(checks_gate, "load_packages_with_deps", lambda _scope: _synthetic_packages())
    app = typer.Typer()
    app.command("gate")(gate_cmd)
    github_output = tmp_path / f"{label}-github-output"
    record = tmp_path / f"{label}-affected-images.json"
    arguments = [
        "--event",
        event,
        "--base-ref",
        base_ref,
        "--head-ref",
        _RECORD_HEAD_SHA,
        "--github-output",
        str(github_output),
    ]
    if with_record:
        arguments += ["--affected-images-record", str(record)]

    result = CliRunner().invoke(app, arguments)

    emitted = (
        dict(line.split("=", maxsplit=1) for line in github_output.read_text(encoding="utf-8").splitlines())
        if github_output.exists()
        else {}
    )
    return result.exit_code, result.output, emitted, record


def test_record_holds_the_declaration_ordered_owner_union_for_a_service_diff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The record is a byte-exact contract: the consumer parses it with no schema tolerance."""
    exit_code, output, _emitted, record = _run_gate_producer(
        tmp_path,
        monkeypatch,
        lambda _base, _head: {"backend/services/notification-service/src/app.py"},
    )

    assert exit_code == 0, output
    assert record.read_text(encoding="utf-8") == (
        f'{{"head_sha":"{_RECORD_HEAD_SHA}","images":["notification-service","health-runner"]}}\n'
    )


def test_record_is_empty_and_successful_when_the_diff_owns_no_image(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A no-image push must publish an empty selection, not fail and not fall back to everything."""
    exit_code, output, _emitted, record = _run_gate_producer(
        tmp_path,
        monkeypatch,
        lambda _base, _head: {"README.md", "scripts/dev/env-lock.sh"},
    )

    assert exit_code == 0, output
    assert json.loads(record.read_text(encoding="utf-8")) == {"head_sha": _RECORD_HEAD_SHA, "images": []}


@pytest.mark.parametrize("base_ref", ["", "0" * 40])
def test_record_names_every_image_when_the_base_ref_gives_no_diff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    base_ref: str,
) -> None:
    def unreachable_diff(_base: str, _head: str) -> set[str]:
        raise AssertionError

    exit_code, output, _emitted, record = _run_gate_producer(
        tmp_path,
        monkeypatch,
        unreachable_diff,
        base_ref=base_ref,
    )

    assert exit_code == 0, output
    assert json.loads(record.read_text(encoding="utf-8"))["images"] == list(load_inventory().names)


def test_unresolvable_diff_builds_every_image_and_keeps_the_fail_closed_classification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Images and lanes fail closed off the same unknown changed set, and neither may drift."""

    def failing_diff(_base: str, _head: str) -> set[str]:
        message = "fatal: bad object base123"
        raise RuntimeError(message)

    exit_code, output, emitted, record = _run_gate_producer(tmp_path, monkeypatch, failing_diff)

    assert exit_code == 0, output
    assert json.loads(record.read_text(encoding="utf-8"))["images"] == list(load_inventory().names)
    assert emitted["full"] == "true"
    assert [flag for flag in FLAG_NAMES if emitted[flag] != "true"] == []


def test_record_and_lane_classification_share_one_diff_invocation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two consumers of the changed set must not cost two `git diff` calls."""
    calls: list[tuple[str, str]] = []

    def counting_diff(base: str, head: str) -> set[str]:
        calls.append((base, head))
        return {"backend/services/notification-service/src/app.py"}

    exit_code, output, _emitted, record = _run_gate_producer(tmp_path, monkeypatch, counting_diff)

    assert exit_code == 0, output
    assert calls == [("base123", _RECORD_HEAD_SHA)]
    assert record.exists()


@pytest.mark.parametrize("event", ["pull_request", "workflow_dispatch"])
def test_record_option_is_rejected_off_a_push_without_writing_a_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    event: str,
) -> None:
    """Only a push has a mainline SHA the selection can bind to."""
    exit_code, output, _emitted, record = _run_gate_producer(
        tmp_path,
        monkeypatch,
        lambda _base, _head: {"backend/services/notification-service/src/app.py"},
        event=event,
    )

    # Exit 2 is the usage-error code, so this pins the rejection to argument validation rather
    # than a runtime failure. The rendered message is deliberately not asserted: Typer routes
    # usage errors through Rich, whose wrapping and truncation differ between a local shell and
    # a hosted xdist worker, and a test of the contract must not depend on presentation.
    assert exit_code == 2, output
    assert not record.exists()


def test_producing_the_record_leaves_every_router_output_identical(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The record is a side output: the lane verdict a push publishes must not move with it."""
    changed = {"backend/libs/lib-a/src/lib_a.py", "uv.lock"}
    _code, _output, with_record, _record = _run_gate_producer(
        tmp_path,
        monkeypatch,
        lambda _base, _head: changed,
        label="with-record",
    )
    _bare_code, _bare_output, without_record, _bare = _run_gate_producer(
        tmp_path,
        monkeypatch,
        lambda _base, _head: changed,
        with_record=False,
        label="without-record",
    )

    assert with_record == without_record
    assert with_record["commit_class"]
    assert "protected_main_smoke" in with_record
    assert "test_packages" in with_record
