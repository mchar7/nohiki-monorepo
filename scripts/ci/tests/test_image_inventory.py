"""Contracts for the canonical release-image inventory, its matching, and its CLI views."""

import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from ci_checks.core.image_inventory import (
    IMAGE_KEYS,
    IMAGE_TIMEOUT_MINUTES,
    INVENTORY_PATH,
    SCHEMA_VERSION,
    SELECTION_AUTHORITY_PATHS,
    TOP_LEVEL_KEYS,
    ImageInventory,
    InventoryError,
    affected_images,
    load_inventory,
    read_affected_record,
    render_matrix,
    write_affected_record,
)

_ROOT = Path(__file__).resolve().parents[3]
_CLI = _ROOT / "scripts" / "ci" / "image_matrix.py"
_IMAGE_COUNT = 27
_SHA = "a" * 40
_OTHER_SHA = "b" * 40

_PYTHON_ROWS = (
    "user-auth-service",
    "user-pref-service",
    "user-upload-service",
    "user-entitlement-service",
    "job-storage-service",
    "job-ingest-discovery-service",
    "job-ingest-schedule-service",
    "job-ingest-enrichment-service",
    "job-query-composition-service",
    "job-correlation-evaluation-service",
    "skill-graph-service",
    "doc-template-service",
    "doc-content-service",
    "doc-process-service",
    "notification-service",
    "bff-service",
    "api-verification-runner",
    "health-runner",
    "ml-gateway-service",
    "ml-compute-service",
    "ml-compute-service-gpu",
    "sys-tick-job",
    "snapshot-refresh-job",
    "qdrant-init",
)


@pytest.fixture(scope="module")
def inventory() -> ImageInventory:
    """Return the repository's canonical inventory."""
    return load_inventory()


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    """Return a synthetic checkout root mirroring the canonical inventory layout."""
    (tmp_path / "scripts" / "ci").mkdir(parents=True)
    (tmp_path / "context").mkdir()
    (tmp_path / "context" / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    (tmp_path / "lock.txt").write_text("locked\n", encoding="utf-8")
    return tmp_path


def _record(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "name": "sample-image",
        "context": "context",
        "dockerfile": "context/Dockerfile",
        "build_args": "",
        "lockfile": "lock.txt",
        "timeout": IMAGE_TIMEOUT_MINUTES,
        "ownership": ["context/"],
    }
    return base | overrides


def _write(checkout: Path, **overrides: object) -> Path:
    payload: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "no_image_ownership": [],
        "images": [_record()],
    }
    path = checkout / "scripts" / "ci" / "image_inventory.json"
    path.write_text(json.dumps(payload | overrides), encoding="utf-8")
    return path


def _synthetic(checkout: Path, **overrides: object) -> ImageInventory:
    return load_inventory(_write(checkout, **overrides))


def _cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_CLI), *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=_ROOT,
    )


def test_canonical_inventory_has_exactly_three_top_level_keys_at_version_two() -> None:
    data = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    assert set(data) == TOP_LEVEL_KEYS
    assert data["schema_version"] == SCHEMA_VERSION
    assert "class" not in {key for image in data["images"] for key in image}


def test_canonical_inventory_declares_twenty_seven_unique_ordered_records(inventory: ImageInventory) -> None:
    data = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    assert len(data["images"]) == _IMAGE_COUNT
    assert all(set(image) == IMAGE_KEYS for image in data["images"])
    assert inventory.names == tuple(image["name"] for image in data["images"])
    assert len(set(inventory.names)) == _IMAGE_COUNT


def test_every_canonical_build_path_exists_and_every_timeout_is_sixteen(inventory: ImageInventory) -> None:
    for record in inventory.images:
        assert (_ROOT / record.context).is_dir(), record.name
        assert (_ROOT / record.dockerfile).is_file(), record.name
        assert (_ROOT / record.lockfile).is_file(), record.name
        assert record.timeout == IMAGE_TIMEOUT_MINUTES, record.name


def test_canonical_lockfiles_follow_the_post_carrier_one_cache_identity(inventory: ImageInventory) -> None:
    lockfiles = {record.name: record.lockfile for record in inventory.images}
    assert lockfiles["frontend"] == "pnpm-lock.yaml"
    assert lockfiles["playwright-verification-runner"] == "pnpm-lock.yaml"
    assert lockfiles["kafka-connect"] == "infra/k8s/kafka-connect/smt/build.gradle.kts"
    assert {name for name, lockfile in lockfiles.items() if lockfile == "uv.lock"} == set(inventory.names) - {
        "frontend",
        "playwright-verification-runner",
        "kafka-connect",
    }


def test_shared_ml_dockerfile_keeps_distinct_cpu_and_gpu_rows(inventory: ImageInventory) -> None:
    rows = {record.name: record for record in inventory.images}
    assert rows["ml-compute-service"].dockerfile == rows["ml-compute-service-gpu"].dockerfile
    assert rows["ml-compute-service"].build_args == ""
    assert rows["ml-compute-service-gpu"].build_args == "ML_COMPUTE_BUILDER=sync-gpu"
    assert {record.name for record in inventory.images if record.build_args} == {"ml-compute-service-gpu"}


def test_kafka_connect_keeps_its_dedicated_context(inventory: ImageInventory) -> None:
    rows = {record.name: record for record in inventory.images}
    assert rows["kafka-connect"].context == "infra/k8s/kafka-connect"
    assert {record.context for record in inventory.images} == {".", "infra/k8s/kafka-connect"}


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        pytest.param({"schema_version": 3}, "schema_version", id="wrong-schema-version"),
        pytest.param({"schema_version": True}, "schema_version", id="boolean-schema-version"),
        pytest.param({"images": []}, "at least one image", id="empty-inventory"),
        pytest.param({"images": [_record(), _record()]}, "duplicate image name", id="duplicate-name"),
        pytest.param({"images": [_record(name="")]}, "kebab-case", id="empty-name"),
        pytest.param({"images": [_record(name="Sample_Image")]}, "kebab-case", id="noncanonical-name"),
        pytest.param({"images": [_record(timeout=20)]}, "timeout must be exactly", id="wrong-timeout"),
        pytest.param({"images": [_record(timeout="16")]}, "timeout must be exactly", id="string-timeout"),
        pytest.param({"images": [_record(build_args=None)]}, "build_args must be a string", id="null-build-args"),
        pytest.param({"images": [_record(context="missing")]}, "not a directory", id="missing-context"),
        pytest.param({"images": [_record(dockerfile="context")]}, "not a file", id="dockerfile-is-directory"),
        pytest.param({"images": [_record(lockfile="absent.txt")]}, "not a file", id="missing-lockfile"),
        pytest.param({"images": [_record(dockerfile="")]}, "empty or non-string", id="empty-dockerfile"),
        pytest.param({"images": [_record(context="/context")]}, "relative posix path", id="absolute-context"),
        pytest.param({"images": [_record(lockfile="../lock.txt")]}, "normalized path", id="traversing-lockfile"),
        pytest.param({"images": [_record(ownership=[])]}, "at least one path rule", id="empty-ownership"),
        pytest.param({"images": [_record(ownership=[""])]}, "empty or non-string", id="empty-ownership-rule"),
        pytest.param({"images": [_record(ownership=["a/", "a/"])]}, "repeats the rule", id="duplicate-ownership-rule"),
        pytest.param({"images": [_record(ownership=["/abs"])]}, "relative posix path", id="absolute-ownership-rule"),
        pytest.param({"images": [_record(ownership=["a/../b"])]}, "normalized path", id="traversing-ownership-rule"),
        pytest.param({"no_image_ownership": ["x", "x"]}, "repeats the rule", id="duplicate-no-image-rule"),
        pytest.param({"no_image_ownership": ["../x"]}, "normalized path", id="traversing-no-image-rule"),
        pytest.param({"no_image_ownership": ["context/"]}, "overlaps image", id="prefix-prefix-overlap"),
        pytest.param({"no_image_ownership": ["context/file"]}, "overlaps image", id="exact-inside-prefix-overlap"),
        pytest.param({"no_image_ownership": ["context"]}, "overlaps image", id="exact-names-owned-directory"),
        pytest.param(
            {"no_image_ownership": [".github/workflows/build-push.yml"]},
            "image-selection authority",
            id="no-image-covers-authority",
        ),
    ],
)
def test_loader_rejects_invalid_inventories(checkout: Path, overrides: dict[str, object], expected: str) -> None:
    with pytest.raises(InventoryError, match=expected):
        _synthetic(checkout, **overrides)


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        pytest.param(lambda data: data.pop("no_image_ownership"), "keys must be exactly", id="missing-top-level-key"),
        pytest.param(lambda data: data.update(extra=1), "keys must be exactly", id="extra-top-level-key"),
        pytest.param(lambda data: data["images"][0].pop("lockfile"), "record keys must be", id="missing-image-key"),
        pytest.param(lambda data: data["images"][0].update(extra=1), "record keys must be", id="extra-image-key"),
        pytest.param(lambda data: data["images"][0].update(clazz="product"), "record keys", id="renamed-image-key"),
    ],
)
def test_loader_rejects_key_drift(checkout: Path, mutate: object, expected: str) -> None:
    payload: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "no_image_ownership": [],
        "images": [_record()],
    }
    assert callable(mutate)
    mutate(payload)
    path = checkout / "scripts" / "ci" / "image_inventory.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(InventoryError, match=expected):
        load_inventory(path)


def test_loader_rejects_a_symlinked_dockerfile_escaping_the_checkout(checkout: Path, tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-dockerfile"
    outside.write_text("FROM scratch\n", encoding="utf-8")
    (checkout / "context" / "escape").symlink_to(outside)
    with pytest.raises(InventoryError, match="outside the checkout"):
        _synthetic(checkout, images=[_record(dockerfile="context/escape")])


def test_loader_rejects_unreadable_and_malformed_inventory_files(checkout: Path) -> None:
    path = checkout / "scripts" / "ci" / "image_inventory.json"
    with pytest.raises(InventoryError, match="cannot read image inventory"):
        load_inventory(path)
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(InventoryError, match="keys must be exactly"):
        load_inventory(path)


def test_exact_rules_match_only_the_named_path(checkout: Path) -> None:
    """A path extending an exact rule must miss it, which is observable only with two images."""
    (checkout / "second").mkdir()
    (checkout / "second" / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    built = _synthetic(
        checkout,
        images=[
            _record(ownership=["context/Dockerfile"]),
            _record(name="second-image", context="second", dockerfile="second/Dockerfile", ownership=["second/"]),
        ],
        no_image_ownership=["context/other"],
    )
    assert built.names == ("sample-image", "second-image")
    assert affected_images({"context/Dockerfile"}, built) == ("sample-image",)
    assert affected_images({"context/other"}, built) == ()
    # Treating the exact rule as a prefix would select only its owner; failing closed selects both.
    assert affected_images({"context/Dockerfile/nested"}, built) == built.names


def test_prefix_rules_match_every_path_beneath_them(checkout: Path) -> None:
    built = _synthetic(checkout, images=[_record(ownership=["context/"])])
    assert affected_images({"context/deep/nested/file"}, built) == ("sample-image",)
    assert affected_images({"contextual/file"}, built) == built.names


def test_multi_owner_union_follows_declaration_order(inventory: ImageInventory) -> None:
    selected = affected_images({"package.json"}, inventory)
    assert selected == ("frontend", "playwright-verification-runner")
    assert selected == tuple(name for name in inventory.names if name in set(selected))


def test_a_diff_of_only_no_image_paths_selects_nothing(inventory: ImageInventory) -> None:
    assert affected_images({"README.md", "CONTRIBUTING.md", "scripts/dev/env-lock.sh"}, inventory) == ()


def test_a_mixed_diff_returns_the_owner_union_without_the_no_image_paths(inventory: ImageInventory) -> None:
    selected = affected_images({"README.md", "infra/k8s/kafka-connect/Dockerfile"}, inventory)
    assert selected == ("kafka-connect",)


def test_an_unknown_path_fails_closed_to_every_image(inventory: ImageInventory) -> None:
    assert affected_images({"unmodelled/new-surface.txt"}, inventory) == inventory.names
    assert affected_images({"README.md", "unmodelled/new-surface.txt"}, inventory) == inventory.names


def test_an_empty_diff_selects_nothing(inventory: ImageInventory) -> None:
    assert affected_images(set(), inventory) == ()
    assert affected_images({""}, inventory) == ()


@pytest.mark.parametrize("authority", sorted(SELECTION_AUTHORITY_PATHS))
def test_every_image_selection_authority_selects_all_twenty_seven(inventory: ImageInventory, authority: str) -> None:
    assert affected_images({authority}, inventory) == inventory.names
    assert len(inventory.names) == _IMAGE_COUNT


def test_selection_authorities_name_the_producer_and_build_surface() -> None:
    assert {
        ".github/workflows/build-push.yml",
        ".github/workflows/checks.yml",
        "scripts/ci/image_digests.py",
        "scripts/ci/image_inventory.json",
        "scripts/ci/image_matrix.py",
        "scripts/ci/src/ci_checks/checks/gate.py",
        "scripts/ci/src/ci_checks/core/image_inventory.py",
    } == SELECTION_AUTHORITY_PATHS
    for authority in SELECTION_AUTHORITY_PATHS:
        assert (_ROOT / authority).is_file(), authority


def test_no_ownership_rule_names_the_absent_typescript_packages_tree(inventory: ImageInventory) -> None:
    rules = {rule for record in inventory.images for rule in record.ownership} | set(inventory.no_image_ownership)
    assert not any(rule.startswith("typescript/packages") for rule in rules)
    assert not (_ROOT / "typescript" / "packages").exists()


@pytest.mark.parametrize("manifest", ["package.json", "pnpm-lock.yaml", "pnpm-workspace.yaml"])
def test_root_node_manifests_select_frontend_and_playwright(inventory: ImageInventory, manifest: str) -> None:
    assert affected_images({manifest}, inventory) == ("frontend", "playwright-verification-runner")


def test_typescript_libs_select_frontend_and_the_two_shared_configs_also_select_playwright(
    inventory: ImageInventory,
) -> None:
    assert affected_images({"typescript/libs/api-client/src/index.ts"}, inventory) == ("frontend",)
    for shared in ("biome-config", "tsconfig"):
        assert affected_images({f"typescript/libs/{shared}/package.json"}, inventory) == (
            "frontend",
            "playwright-verification-runner",
        )


def test_frontend_tree_paths_select_both_dockerfiles_that_copy_it(inventory: ImageInventory) -> None:
    for path in (
        "typescript/apps/frontend/e2e/global-setup.ts",
        "typescript/apps/frontend/e2e/journeys/apply.spec.ts",
        "typescript/apps/frontend/e2e/pages/login.ts",
        "typescript/apps/frontend/playwright.config.ts",
        "typescript/apps/frontend/src/locales/en.json",
        "typescript/apps/frontend/scripts/i18n/scan.mjs",
    ):
        assert affected_images({path}, inventory) == ("frontend", "playwright-verification-runner"), path


def test_a_frontend_only_source_path_selects_frontend_alone(inventory: ImageInventory) -> None:
    assert affected_images({"typescript/apps/frontend/Caddyfile"}, inventory) == (
        "frontend",
        "playwright-verification-runner",
    )
    assert affected_images({"typescript/libs/tsconfig-unrelated/x.json"}, inventory) == ("frontend",)


@pytest.mark.parametrize(
    "path",
    [
        "scripts/ci/src/ci_checks/app.py",
        "scripts/ci/src/ci_checks/checks/internal_refs.py",
        "scripts/ci/src/ci_checks/checks/tests.py",
        "scripts/ci/src/ci_checks/core/repository.py",
        "scripts/ci/README.md",
        "scripts/ci/tests/test_change_gate.py",
        "scripts/ci/pyproject.toml",
    ],
)
def test_scripts_ci_paths_select_the_health_runner(inventory: ImageInventory, path: str) -> None:
    assert affected_images({path}, inventory) == ("health-runner",)


def test_common_python_manifests_fan_out_to_every_python_image(inventory: ImageInventory) -> None:
    for manifest in ("pyproject.toml", "uv.lock", "backend/libs/nohiki-kafka-client/pyproject.toml"):
        assert affected_images({manifest}, inventory) == _PYTHON_ROWS, manifest


def test_a_backend_service_change_selects_that_service_and_the_health_runner(inventory: ImageInventory) -> None:
    assert affected_images({"backend/services/bff-service/src/bff_service/main.py"}, inventory) == (
        "bff-service",
        "health-runner",
    )


def test_a_health_check_source_change_selects_health_and_the_api_runner(inventory: ImageInventory) -> None:
    assert affected_images({"scripts/util/health_check/src/health_check/probe.py"}, inventory) == (
        "api-verification-runner",
        "health-runner",
    )


def test_the_api_runner_owns_exactly_its_narrowed_context(inventory: ImageInventory) -> None:
    api = next(record for record in inventory.images if record.name == "api-verification-runner")
    assert api.ownership == (
        "backend/libs/",
        "docs/api/nohiki.openapi.json",
        "pyproject.toml",
        "scripts/util/health_check/",
        "tests/",
        "uv.lock",
    )
    for path in ("tests/api/run_k8s_verification.py", "tests/Dockerfile.api-runner.dockerignore"):
        assert affected_images({path}, inventory) == ("api-verification-runner",), path
    assert affected_images({"docs/api/nohiki.openapi.json"}, inventory) == ("api-verification-runner",)


def test_the_api_ignore_file_admits_exactly_the_inventoried_api_inputs() -> None:
    ignore = (_ROOT / "tests" / "Dockerfile.api-runner.dockerignore").read_text(encoding="utf-8")
    admitted = {line.removeprefix("!").rstrip("*").rstrip("/") for line in ignore.splitlines() if line.startswith("!")}
    assert {"pyproject.toml", "uv.lock", "backend/libs", "docs/api/nohiki.openapi.json", "tests"} <= admitted
    assert "**" in ignore.splitlines()
    assert "tests/uv.lock" in ignore.splitlines()


def test_the_root_ignore_owns_every_root_context_image_except_the_api_and_kafka(inventory: ImageInventory) -> None:
    selected = affected_images({".dockerignore"}, inventory)
    assert set(selected) == set(inventory.names) - {"api-verification-runner", "kafka-connect"}
    assert selected == tuple(name for name in inventory.names if name in set(selected))


def test_each_dockerfile_specific_ignore_selects_exactly_its_own_image(inventory: ImageInventory) -> None:
    assert affected_images({"tests/Dockerfile.api-runner.dockerignore"}, inventory) == ("api-verification-runner",)


def test_kafka_and_qdrant_contexts_select_exactly_their_own_image(inventory: ImageInventory) -> None:
    assert affected_images({"infra/k8s/kafka-connect/smt/build.gradle.kts"}, inventory) == ("kafka-connect",)
    assert affected_images({"infra/shared/qdrant-init/Dockerfile"}, inventory) == ("qdrant-init",)


def test_a_job_change_selects_only_its_own_job_row(inventory: ImageInventory) -> None:
    assert affected_images({"backend/jobs/sys-tick-job/src/sys_tick_job/main.py"}, inventory) == ("sys-tick-job",)


@pytest.mark.parametrize(
    "path",
    [
        "scripts/dev/env-lock.sh",
        "skills-lock.json",
        "Justfile",
        "CONTRIBUTING.md",
        "README.md",
        "flake.nix",
        "infra/k8s/gitops/platform/prod/kustomization.yaml",
        "infra/k8s/helm/values.prod.yaml",
        "infra/terraform/main.tf",
        "infra/k8s/local/images.json",
        "scripts/util/analyze_codebase.py",
        "scripts/infra/verify-k8s-jobs.py",
        ".github/workflows/release-helm-charts.yml",
    ],
)
def test_adjudicated_no_image_paths_select_nothing(inventory: ImageInventory, path: str) -> None:
    assert affected_images({path}, inventory) == ()


def test_no_scripts_ci_or_typescript_path_is_marked_no_image(inventory: ImageInventory) -> None:
    assert not any(rule.startswith(("scripts/ci", "typescript")) for rule in inventory.no_image_ownership)


def test_render_matrix_emits_declaration_ordered_build_rows(inventory: ImageInventory) -> None:
    data = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    full = render_matrix(inventory)
    assert set(full) == {"include"}
    # Every field is pinned to its own declared value: a swapped mapping feeds Buildx the wrong input.
    assert full["include"] == [
        {
            "name": image["name"],
            "context": image["context"],
            "dockerfile": image["dockerfile"],
            "build_args": image["build_args"],
            "lockfile": image["lockfile"],
            "timeout_minutes": image["timeout"],
        }
        for image in data["images"]
    ]
    assert [row["name"] for row in full["include"]] == list(inventory.names)
    assert all(row["timeout_minutes"] == IMAGE_TIMEOUT_MINUTES for row in full["include"])


def test_render_matrix_rows_carry_the_documented_values_for_the_special_cases(inventory: ImageInventory) -> None:
    """Literal expected rows for the non-root context and the only build-arg image."""
    selected = render_matrix(inventory, ["kafka-connect", "ml-compute-service-gpu"])["include"]
    rows = {row["name"]: row for row in selected}
    assert rows["kafka-connect"] == {
        "name": "kafka-connect",
        "context": "infra/k8s/kafka-connect",
        "dockerfile": "infra/k8s/kafka-connect/Dockerfile",
        "build_args": "",
        "lockfile": "infra/k8s/kafka-connect/smt/build.gradle.kts",
        "timeout_minutes": IMAGE_TIMEOUT_MINUTES,
    }
    assert rows["ml-compute-service-gpu"] == {
        "name": "ml-compute-service-gpu",
        "context": ".",
        "dockerfile": "backend/services/ml-compute-service/Dockerfile",
        "build_args": "ML_COMPUTE_BUILDER=sync-gpu",
        "lockfile": "uv.lock",
        "timeout_minutes": IMAGE_TIMEOUT_MINUTES,
    }


def test_render_matrix_preserves_order_for_a_subset_and_rejects_unknown_names(inventory: ImageInventory) -> None:
    subset = render_matrix(inventory, ["kafka-connect", "bff-service"])
    assert [row["name"] for row in subset["include"]] == ["bff-service", "kafka-connect"]
    assert render_matrix(inventory, []) == {"include": []}
    with pytest.raises(InventoryError, match="unknown image names"):
        render_matrix(inventory, ["not-an-image"])


def test_the_affected_record_round_trips_a_selection(tmp_path: Path, inventory: ImageInventory) -> None:
    path = tmp_path / "affected-images.json"
    write_affected_record(path, _SHA.upper(), ["bff-service", "health-runner"])
    assert path.read_text(encoding="utf-8") == f'{{"head_sha":"{_SHA}","images":["bff-service","health-runner"]}}\n'
    assert read_affected_record(path, _SHA, inventory) == ("bff-service", "health-runner")


def test_an_empty_affected_record_is_valid(tmp_path: Path, inventory: ImageInventory) -> None:
    path = tmp_path / "affected-images.json"
    write_affected_record(path, _SHA, [])
    assert path.read_text(encoding="utf-8") == f'{{"head_sha":"{_SHA}","images":[]}}\n'
    assert read_affected_record(path, _SHA, inventory) == ()


def test_writing_a_record_requires_a_commit_id(tmp_path: Path) -> None:
    with pytest.raises(InventoryError, match="40-character commit id"):
        write_affected_record(tmp_path / "record.json", "HEAD", [])


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        pytest.param({"head_sha": "nope", "images": []}, "not 40 lowercase hex", id="bad-sha"),
        pytest.param({"head_sha": _SHA.upper(), "images": []}, "not 40 lowercase hex", id="uppercase-sha"),
        pytest.param({"head_sha": _OTHER_SHA, "images": []}, "not the tested", id="stale-sha"),
        pytest.param({"head_sha": _SHA}, "keys must be exactly", id="missing-images-key"),
        pytest.param({"head_sha": _SHA, "images": [], "extra": 1}, "keys must be exactly", id="extra-key"),
        pytest.param({"head_sha": _SHA, "images": "bff-service"}, "list of image names", id="images-not-a-list"),
        pytest.param({"head_sha": _SHA, "images": [1]}, "list of image names", id="images-not-strings"),
        pytest.param(
            {"head_sha": _SHA, "images": ["bff-service", "bff-service"]},
            "repeats an image name",
            id="duplicate-name",
        ),
        pytest.param({"head_sha": _SHA, "images": ["ghost-service"]}, "unknown images", id="unknown-name"),
        pytest.param(
            {"head_sha": _SHA, "images": ["health-runner", "bff-service"]},
            "declaration order",
            id="noncanonical-order",
        ),
    ],
)
def test_reading_rejects_invalid_records(
    tmp_path: Path,
    inventory: ImageInventory,
    payload: dict[str, object],
    expected: str,
) -> None:
    path = tmp_path / "affected-images.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(InventoryError, match=expected):
        read_affected_record(path, _SHA, inventory)


def test_reading_rejects_a_missing_or_unparseable_record(tmp_path: Path, inventory: ImageInventory) -> None:
    path = tmp_path / "affected-images.json"
    with pytest.raises(InventoryError, match="cannot read affected-image record"):
        read_affected_record(path, _SHA, inventory)
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(InventoryError, match="cannot read affected-image record"):
        read_affected_record(path, _SHA, inventory)
    path.write_bytes(b"\xff\xfe\x00")
    with pytest.raises(InventoryError, match="cannot read affected-image record"):
        read_affected_record(path, _SHA, inventory)


def test_reading_requires_a_commit_id_as_the_expected_source(tmp_path: Path, inventory: ImageInventory) -> None:
    path = tmp_path / "affected-images.json"
    write_affected_record(path, _SHA, [])
    with pytest.raises(InventoryError, match="expected source sha"):
        read_affected_record(path, "HEAD", inventory)


def test_cli_matrix_without_an_artifact_emits_the_full_canonical_matrix(inventory: ImageInventory) -> None:
    result = _cli("matrix")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == render_matrix(inventory)
    assert result.stdout.count("\n") == 1


def test_cli_matrix_emits_the_affected_subset_for_a_valid_artifact(tmp_path: Path, inventory: ImageInventory) -> None:
    path = tmp_path / "affected-images.json"
    write_affected_record(path, _SHA, ["frontend", "kafka-connect"])
    result = _cli("matrix", "--artifact", str(path), "--source-sha", _SHA)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == render_matrix(inventory, ["frontend", "kafka-connect"])
    assert result.stderr == ""


def test_cli_matrix_emits_an_empty_include_for_a_valid_empty_artifact(tmp_path: Path) -> None:
    path = tmp_path / "affected-images.json"
    write_affected_record(path, _SHA, [])
    result = _cli("matrix", "--artifact", str(path), "--source-sha", _SHA)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"include": []}
    assert result.stderr == ""


@pytest.mark.parametrize(
    ("content", "source_sha"),
    [
        pytest.param(None, _SHA, id="missing-artifact"),
        pytest.param("{not json", _SHA, id="malformed-artifact"),
        pytest.param(json.dumps({"head_sha": _SHA, "images": []}), _OTHER_SHA, id="stale-artifact"),
        pytest.param(json.dumps({"head_sha": _SHA, "images": ["ghost"]}), _SHA, id="unknown-name"),
        pytest.param(
            json.dumps({"head_sha": _SHA, "images": ["health-runner", "bff-service"]}),
            _SHA,
            id="noncanonical-order",
        ),
    ],
)
def test_cli_matrix_falls_back_to_full_on_an_unusable_artifact(
    tmp_path: Path,
    inventory: ImageInventory,
    content: str | None,
    source_sha: str,
) -> None:
    path = tmp_path / "affected-images.json"
    if content is not None:
        path.write_text(content, encoding="utf-8")
    result = _cli("matrix", "--artifact", str(path), "--source-sha", source_sha)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == render_matrix(inventory)
    assert "warning:" in result.stderr


def test_cli_exits_nonzero_when_the_inventory_authority_itself_is_corrupt(tmp_path: Path) -> None:
    corrupt = tmp_path / "scripts" / "ci" / "image_inventory.json"
    corrupt.parent.mkdir(parents=True)
    corrupt.write_text("{}", encoding="utf-8")
    result = _cli("matrix", "--inventory", str(corrupt))
    assert result.returncode == 2
    assert "error:" in result.stderr
    assert result.stdout == ""


def test_undecodable_bytes_fall_back_for_a_record_but_exit_nonzero_for_the_authority(
    tmp_path: Path,
    inventory: ImageInventory,
) -> None:
    """Record corruption falls back to the full set; authority corruption is never disguised as it."""
    undecodable = b"\xff\xfe\x00"
    record = tmp_path / "affected-images.json"
    record.write_bytes(undecodable)
    fallback = _cli("matrix", "--artifact", str(record), "--source-sha", _SHA)
    assert fallback.returncode == 0, fallback.stderr
    assert json.loads(fallback.stdout) == render_matrix(inventory)
    assert len(json.loads(fallback.stdout)["include"]) == _IMAGE_COUNT
    assert "warning: cannot read affected-image record" in fallback.stderr

    authority = tmp_path / "scripts" / "ci" / "image_inventory.json"
    authority.parent.mkdir(parents=True)
    authority.write_bytes(undecodable)
    corrupt = _cli("matrix", "--inventory", str(authority))
    assert corrupt.returncode == 2
    assert "error: cannot read image inventory" in corrupt.stderr
    assert corrupt.stdout == ""


def test_cli_matrix_requires_a_source_sha_beside_an_artifact(tmp_path: Path) -> None:
    result = _cli("matrix", "--artifact", str(tmp_path / "affected-images.json"))
    assert result.returncode == 2
    assert "--artifact requires --source-sha" in result.stderr


def test_cli_names_and_specs_are_canonical_views(inventory: ImageInventory) -> None:
    names = _cli("names")
    specs = _cli("specs")
    assert names.returncode == 0, names.stderr
    assert specs.returncode == 0, specs.stderr
    assert names.stdout.splitlines() == list(inventory.names)
    assert [line.split("\t") for line in specs.stdout.splitlines()] == [
        [record.name, record.context, record.dockerfile, record.build_args] for record in inventory.images
    ]


def test_the_canonical_inventory_survives_a_deep_copy_round_trip(inventory: ImageInventory) -> None:
    data = deepcopy(json.loads(INVENTORY_PATH.read_text(encoding="utf-8")))
    assert [image["name"] for image in data["images"]] == list(inventory.names)
    assert all(image["timeout"] == IMAGE_TIMEOUT_MINUTES for image in data["images"])
