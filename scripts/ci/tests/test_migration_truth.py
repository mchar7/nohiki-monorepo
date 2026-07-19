"""Canonical migration inventory and live equality contract tests."""

from __future__ import annotations

import json
import os
import subprocess
from functools import cache
from pathlib import Path

import pytest
import yaml
from ci_checks.checks.migration_truth import (
    MigrationInventory,
    MigrationInventoryEntry,
    MigrationTruthError,
    derive_inventory,
    render_inventory,
    render_live_verifier,
    validate_migration_truth,
)
from helm_test_utils import runtime_eso_args

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_RUNTIME_VERIFIER = _REPOSITORY_ROOT / "infra/k8s/scripts/verify-migration-heads.py"
_EXPECTED_INVENTORY = MigrationInventory(
    entries=(
        MigrationInventoryEntry("bff-service", "bff_schema", "001"),
        MigrationInventoryEntry("doc-template-service", "doc_template_schema", "001"),
        MigrationInventoryEntry("job-correlation-evaluation-service", "job_correlation_schema", "001"),
        MigrationInventoryEntry("job-ingest-discovery-service", "job_ingest_discovery_schema", "001"),
        MigrationInventoryEntry("job-ingest-enrichment-service", "job_ingest_enrichment_schema", "001"),
        MigrationInventoryEntry("job-ingest-schedule-service", "job_schedule_schema", "001"),
        MigrationInventoryEntry("job-query-composition-service", "job_query_schema", "001"),
        MigrationInventoryEntry("job-storage-service", "job_storage_schema", "001"),
        MigrationInventoryEntry("notification-service", "notification_schema", "001"),
        MigrationInventoryEntry("skill-graph-service", "skill_graph_schema", "001"),
        MigrationInventoryEntry("user-auth-service", "user_auth_schema", "001"),
        MigrationInventoryEntry("user-entitlement-service", "user_entitlement_schema", "001"),
        MigrationInventoryEntry("user-pref-service", "user_pref_schema", "001"),
        MigrationInventoryEntry("user-upload-service", "user_upload_schema", "001"),
    )
)
_MIGRATION_DIGEST = "sha256:" + "a" * 64


@cache
def _render_environment(values_file: str) -> tuple[dict[str, object], ...]:
    chart = _REPOSITORY_ROOT / "infra/k8s/helm"
    command = [
        "helm",
        "template",
        "nohiki",
        ".",
        "--values",
        "values.yaml",
        "--values",
        values_file,
        "--namespace",
        "nohiki",
        "--set",
        "skill-graph-service.bootstrap.enabled=true",
    ]
    if values_file == "values.prod.yaml":
        command.extend(
            [
                "--values",
                str(_REPOSITORY_ROOT / "scripts/ci/tests/fixtures/values.prod.identity.yaml"),
                "--values",
                str(_REPOSITORY_ROOT / "scripts/ci/tests/fixtures/values.prod.network.yaml"),
                *runtime_eso_args("prod"),
            ]
        )
    workflow = yaml.safe_load((_REPOSITORY_ROOT / ".github/workflows/build-push.yml").read_text(encoding="utf-8"))
    image_digests = {
        f"ghcr.io/mchar7/nohiki-monorepo/{entry['name']}": _MIGRATION_DIGEST
        for entry in workflow["jobs"]["build-push"]["strategy"]["matrix"]["include"]
    }
    command.extend(["--set-json", f"global.imageDigests={json.dumps(image_digests)}"])
    result = subprocess.run(
        command,
        cwd=chart,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    rendered = result.stdout
    return tuple(document for document in yaml.safe_load_all(rendered) if isinstance(document, dict))


def _write_history(
    root: Path,
    revisions: list[tuple[str, str | None]],
    *,
    service: str = "example-service",
    schema: str = "example_schema",
) -> None:
    values = root / "infra/k8s/helm/values.yaml"
    values.parent.mkdir(parents=True)
    values.write_text(
        f"{service}:\n  enabled: true\n  database:\n    enabled: true\n    schema: {schema}\n",
        encoding="utf-8",
    )
    versions = root / "backend/services" / service / "alembic/versions"
    versions.mkdir(parents=True)
    for revision, parent in revisions:
        (versions / f"{revision}_migration.py").write_text(
            f"revision = {revision!r}\ndown_revision = {parent!r}\nSCHEMA_NAME = {schema!r}\n",
            encoding="utf-8",
        )


def _write_fake_kubectl(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env bash
set -u
{
  printf '%s' "$1"
  printf '\\t%s' "${@:2}"
  printf '\\n'
} >>"$KUBECTL_LOG"
if [[ "${1:-} ${2:-}" == "get pods" ]]; then
  printf '%s\n' "${KUBECTL_PRIMARY:-nohiki-pg-1}"
elif [[ " $* " == *" exec "* ]]; then
  query=""
  for ((index = 1; index <= $#; index++)); do
    if [[ "${!index}" == "--command" ]]; then
      ((index++))
      query="${!index}"
      break
    fi
  done
  if [[ "$query" =~ FROM\\ \\\"([a-z_][a-z0-9_]*)\\\"\\.alembic_version ]]; then
    variable="KUBECTL_VERSION_${BASH_REMATCH[1]}"
    printf '%s' "${!variable}"
    printf '%s' "${KUBECTL_STDERR:-}" >&2
    exit "${KUBECTL_EXIT:-0}"
  fi
  exit 64
else
  exit 64
fi
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def test_real_enabled_schema_inventory_and_all_committed_heads_are_exact() -> None:
    assert derive_inventory(_REPOSITORY_ROOT) == _EXPECTED_INVENTORY

    bff_versions = _REPOSITORY_ROOT / "backend/services/bff-service/alembic/versions"
    assert sorted(path.name[:3] for path in bff_versions.glob("*.py")) == ["001"]
    assert {entry.head for entry in _EXPECTED_INVENTORY.entries} == {"001"}


def test_real_migration_jobs_match_inventory_order_and_evidence_contract() -> None:
    assert validate_migration_truth(_REPOSITORY_ROOT) == _EXPECTED_INVENTORY


@pytest.mark.parametrize("values_file", ["values.local.yaml", "values.prod.yaml"])
def test_rendered_environments_have_exact_raw_unique_migration_jobs(
    values_file: str,
) -> None:
    documents = _render_environment(values_file)
    migrations = [
        document
        for document in documents
        if document.get("kind") == "Job" and document["metadata"]["name"].endswith("-db-migrate")
    ]
    names = [document["metadata"]["name"].removesuffix("-db-migrate") for document in migrations]
    expected_names = [entry.service for entry in _EXPECTED_INVENTORY.entries]

    # Count the raw YAML documents before building any keyed lookup: duplicate
    # names must remain visible to both cardinality and uniqueness assertions.
    assert len(migrations) == len(_EXPECTED_INVENTORY.entries) == 14
    assert len(names) == len(set(names))
    assert set(names) == set(expected_names)
    for job in migrations:
        assert job["metadata"]["annotations"] == {
            "helm.sh/hook": "post-install,post-upgrade",
            "helm.sh/hook-delete-policy": "before-hook-creation",
            "helm.sh/hook-weight": "1",
        }
        assert "ttlSecondsAfterFinished" not in job["spec"]


def test_production_migration_images_exactly_match_service_digest_images() -> None:
    documents = _render_environment("values.prod.yaml")
    migrations = [
        document
        for document in documents
        if document.get("kind") == "Job" and document["metadata"]["name"].endswith("-db-migrate")
    ]
    deployments = {
        document["metadata"]["labels"]["app.kubernetes.io/name"]: document
        for document in documents
        if document.get("kind") == "Deployment"
        and document.get("metadata", {}).get("labels", {}).get("app.kubernetes.io/name")
        in {entry.service for entry in _EXPECTED_INVENTORY.entries}
    }
    assert len(deployments) == len(_EXPECTED_INVENTORY.entries) == 14
    for job in migrations:
        service = job["metadata"]["name"].removesuffix("-db-migrate")
        migration_image = job["spec"]["template"]["spec"]["containers"][0]["image"]
        service_image = deployments[service]["spec"]["template"]["spec"]["containers"][0]["image"]
        assert migration_image == service_image
        assert migration_image.endswith(f"@{_MIGRATION_DIGEST}")


def test_local_hook_order_remains_qdrant_then_migrations_then_bootstrap() -> None:
    documents = _render_environment("values.local.yaml")
    jobs = [document for document in documents if document.get("kind") == "Job"]
    migration = next(document for document in jobs if document["metadata"]["name"].endswith("-db-migrate"))
    qdrant = next(document for document in jobs if document["metadata"]["name"].endswith("-qdrant-init"))
    bootstrap = next(document for document in jobs if document["metadata"]["name"].endswith("-bootstrap"))
    assert (
        qdrant["metadata"]["annotations"]["helm.sh/hook-weight"],
        migration["metadata"]["annotations"]["helm.sh/hook-weight"],
        bootstrap["metadata"]["annotations"]["helm.sh/hook-weight"],
    ) == ("0", "1", "2")


@pytest.mark.parametrize(
    ("revisions", "expected"),
    [
        (
            [("001", None), ("003", "001")],
            "example-service: numeric revision gap: [1, 3]",
        ),
        (
            [("001", None), ("002", "001"), ("003", "001")],
            "example-service: forked revisions [('001', ['002', '003'])]; "
            "heads are ['002', '003'], expected exactly one",
        ),
    ],
    ids=("gap", "fork"),
)
def test_derive_inventory_rejects_non_linear_histories_deterministically(
    tmp_path: Path,
    revisions: list[tuple[str, str | None]],
    expected: str,
) -> None:
    _write_history(tmp_path, revisions)

    with pytest.raises(MigrationTruthError) as error:
        derive_inventory(tmp_path)

    assert str(error.value) == expected


def test_derive_inventory_rejects_disconnected_revision_cycle(tmp_path: Path) -> None:
    _write_history(tmp_path, [("001", None), ("002", "003"), ("003", "002")])

    with pytest.raises(MigrationTruthError) as error:
        derive_inventory(tmp_path)

    assert str(error.value) == ("example-service: revisions unreachable from 001 ['002', '003']")


def test_derive_inventory_rejects_adversarial_revision_quote_injection(
    tmp_path: Path,
) -> None:
    revision = "x';echo-pwned;#"
    _write_history(tmp_path, [(revision, None)])

    with pytest.raises(MigrationTruthError) as error:
        derive_inventory(tmp_path)

    assert str(error.value).endswith(f": unsafe revision {revision!r}")


def test_derive_inventory_rejects_enabled_service_without_committed_schema(
    tmp_path: Path,
) -> None:
    _write_history(tmp_path, [])

    with pytest.raises(MigrationTruthError) as error:
        derive_inventory(tmp_path)

    assert str(error.value) == "example-service: no committed Alembic revisions"


def test_inventory_rendering_and_head_derivation_are_deterministic(
    tmp_path: Path,
) -> None:
    _write_history(tmp_path, [("001", None), ("002", "001")])
    first = derive_inventory(tmp_path)
    second = derive_inventory(tmp_path)

    assert first == second == MigrationInventory((MigrationInventoryEntry("example-service", "example_schema", "002"),))
    assert render_inventory(first) == (
        '{"entries":[{"head":"002","schema":"example_schema","service":"example-service"}]}'
    )


def test_live_verifier_command_is_exact_read_only_and_shell_safe() -> None:
    inventory = MigrationInventory((MigrationInventoryEntry("bff-service", "bff_schema", "007"),))

    assert render_live_verifier(inventory, namespace="nohiki-test") == (
        "inventory_file=$(mktemp) && "
        "trap 'rm -f \"$inventory_file\"' EXIT HUP INT TERM && "
        'printf \'%s\' \'{"entries":[{"head":"007",'
        '"schema":"bff_schema","service":'
        '"bff-service"}]}\' >"$inventory_file" && '
        "python3 infra/k8s/scripts/verify-migration-heads.py "
        '--inventory "$inventory_file" --namespace nohiki-test '
        "--evidence migration-head-evidence.json"
    )


def test_live_verifier_rejects_namespace_injection() -> None:
    with pytest.raises(MigrationTruthError) as error:
        render_live_verifier(_EXPECTED_INVENTORY, namespace="nohiki; kubectl delete ns nohiki")

    assert str(error.value) == ("invalid Kubernetes namespace 'nohiki; kubectl delete ns nohiki'")


@pytest.mark.parametrize("length", [63, 64])
@pytest.mark.parametrize("argument", ["namespace", "cluster"])
def test_kubernetes_name_length_boundary(
    tmp_path: Path,
    length: int,
    argument: str,
) -> None:
    name = "a" * length
    if argument == "namespace":
        if length == 63:
            assert "--namespace " + name in render_live_verifier(_EXPECTED_INVENTORY, namespace=name)
        else:
            with pytest.raises(MigrationTruthError, match="invalid Kubernetes namespace"):
                render_live_verifier(_EXPECTED_INVENTORY, namespace=name)

    inventory = tmp_path / "inventory.json"
    inventory.write_text(render_inventory(_EXPECTED_INVENTORY), encoding="utf-8")
    kubectl = tmp_path / "kubectl"
    _write_fake_kubectl(kubectl)
    evidence = tmp_path / "evidence.json"
    completed = subprocess.run(
        [
            str(_RUNTIME_VERIFIER),
            "--inventory",
            str(inventory),
            "--namespace",
            name if argument == "namespace" else "nohiki",
            "--cluster",
            name if argument == "cluster" else "nohiki-pg",
            "--evidence",
            str(evidence),
            "--kubectl",
            str(kubectl),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=os.environ
        | {"KUBECTL_LOG": str(tmp_path / "kubectl.tsv")}
        | {f"KUBECTL_VERSION_{entry.schema}": entry.head for entry in _EXPECTED_INVENTORY.entries},
    )
    assert completed.returncode == (0 if length == 63 else 1)
    if length == 64:
        assert completed.stderr == "[FAIL] migration verification: invalid namespace or cluster name\n"
        assert json.loads(evidence.read_text(encoding="utf-8")) == {
            "entries": [],
            "error": "verification-failed",
            "passed": False,
        }


def test_runtime_verifier_accepts_exact_heads_and_writes_retained_evidence(
    tmp_path: Path,
) -> None:
    inventory_path = tmp_path / "inventory.json"
    inventory_path.write_text(render_inventory(_EXPECTED_INVENTORY), encoding="utf-8")
    kubectl = tmp_path / "kubectl"
    _write_fake_kubectl(kubectl)
    evidence = tmp_path / "evidence.json"
    log = tmp_path / "kubectl.jsonl"

    completed = subprocess.run(
        [
            str(_RUNTIME_VERIFIER),
            "--inventory",
            str(inventory_path),
            "--namespace",
            "nohiki-test",
            "--evidence",
            str(evidence),
            "--kubectl",
            str(kubectl),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=os.environ
        | {"KUBECTL_LOG": str(log)}
        | {f"KUBECTL_VERSION_{entry.schema}": entry.head for entry in _EXPECTED_INVENTORY.entries},
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    assert payload["passed"] is True
    assert [(item["service"], item["actual"]) for item in payload["entries"]] == [
        (entry.service, entry.head) for entry in _EXPECTED_INVENTORY.entries
    ]
    invocations = [line.split("\t") for line in log.read_text(encoding="utf-8").splitlines()]
    assert all(not ({"apply", "create", "delete", "patch", "replace"} & set(args)) for args in invocations)


def test_runtime_verifier_fails_closed_on_stale_head_with_redacted_evidence(
    tmp_path: Path,
) -> None:
    inventory = MigrationInventory((MigrationInventoryEntry("bff-service", "bff_schema", "007"),))
    inventory_path = tmp_path / "inventory.json"
    inventory_path.write_text(render_inventory(inventory), encoding="utf-8")
    kubectl = tmp_path / "kubectl"
    _write_fake_kubectl(kubectl)
    evidence = tmp_path / "evidence.json"
    log = tmp_path / "kubectl.jsonl"
    secret = "postgres://admin:never-print-me@database/nohiki"

    completed = subprocess.run(
        [
            str(_RUNTIME_VERIFIER),
            "--inventory",
            str(inventory_path),
            "--evidence",
            str(evidence),
            "--kubectl",
            str(kubectl),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=os.environ
        | {
            "KUBECTL_LOG": str(log),
            "KUBECTL_VERSION_bff_schema": "006",
            "KUBECTL_STDERR": secret,
        },
    )

    assert completed.returncode == 1
    diagnostic = completed.stdout + completed.stderr + evidence.read_text(encoding="utf-8")
    assert secret not in diagnostic
    assert "006" in diagnostic
    assert "007" in diagnostic
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    assert payload == {
        "entries": [
            {
                "actual": "006",
                "expected": "007",
                "matches": False,
                "schema": "bff_schema",
                "service": "bff-service",
            }
        ],
        "passed": False,
    }
