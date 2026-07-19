"""Static contracts for the in-cluster health verification Helm release."""

from __future__ import annotations

import json
import re
import subprocess
from functools import cache
from pathlib import Path
from typing import Any

import yaml

_ROOT = Path(__file__).resolve().parents[3]
_CHART = _ROOT / "infra" / "k8s" / "verification" / "health"
_RELEASE = _ROOT / "infra" / "k8s" / "gitops" / "verification" / "helmrelease.yaml"
_LOCAL = _ROOT / "infra" / "k8s" / "gitops" / "clusters" / "local"
_DIGEST_VALUES = _ROOT / "infra" / "k8s" / "gitops" / "platform" / "local" / "image-digests.values.yaml"
_IMAGES = _ROOT / "infra" / "k8s" / "local" / "images.json"
_NAME = "nohiki-health-verification"
_DIGEST = "sha256:" + "a" * 64
_READ_ONLY_VERBS = {"get", "list", "watch"}
_FORBIDDEN_RESOURCES = {"secrets", "pods/exec", "pods/portforward"}
_MIGRATION_SERVICES = (
    "bff-service",
    "doc-template-service",
    "job-correlation-evaluation-service",
    "job-ingest-discovery-service",
    "job-ingest-enrichment-service",
    "job-ingest-schedule-service",
    "job-query-composition-service",
    "job-storage-service",
    "notification-service",
    "skill-graph-service",
    "user-auth-service",
    "user-entitlement-service",
    "user-pref-service",
    "user-upload-service",
)


@cache
def _load(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict), path
    return value


@cache
def _render() -> tuple[dict[str, Any], ...]:
    result = subprocess.run(
        [
            "helm",
            "template",
            _NAME,
            str(_CHART),
            "--namespace",
            "nohiki",
            "--set-string",
            f"global.imageDigests.health-runner={_DIGEST}",
        ],
        cwd=_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return tuple(document for document in yaml.safe_load_all(result.stdout) if isinstance(document, dict))


@cache
def _document(kind: str, name: str) -> dict[str, Any]:
    matches = [
        document
        for document in _render()
        if document.get("kind") == kind and document.get("metadata", {}).get("name") == name
    ]
    assert len(matches) == 1, (kind, name)
    return matches[0]


def _job() -> dict[str, Any]:
    return _document("Job", _NAME)


def _container() -> dict[str, Any]:
    containers = _job()["spec"]["template"]["spec"]["containers"]
    assert len(containers) == 1
    return containers[0]


def test_health_chart_has_one_dedicated_job_identity_and_bindings() -> None:
    chart = _load(_CHART / "Chart.yaml")
    assert chart["name"] == "nohiki-health-verification"
    assert chart["type"] == "application"

    account = _document("ServiceAccount", _NAME)
    binding = _document("RoleBinding", _NAME)
    cluster_role = _document("ClusterRole", f"{_NAME}-flux-reader")
    cluster_binding = _document("ClusterRoleBinding", f"{_NAME}-flux-reader")
    assert account["automountServiceAccountToken"] is False
    assert binding["subjects"] == [{"kind": "ServiceAccount", "name": _NAME}]
    assert binding["roleRef"] == {
        "apiGroup": "rbac.authorization.k8s.io",
        "kind": "Role",
        "name": _NAME,
    }
    assert cluster_role["metadata"]["name"] == f"{_NAME}-flux-reader"
    assert cluster_binding["subjects"] == [{"kind": "ServiceAccount", "name": _NAME, "namespace": "nohiki"}]


def test_health_job_is_non_retrying_hardened_and_uses_token_only_in_pod() -> None:
    job = _job()
    assert job["metadata"]["labels"]["nohiki.io/verification-stage"] == "health"
    assert job["spec"]["backoffLimit"] == 0
    assert "ttlSecondsAfterFinished" not in job["spec"]

    pod = job["spec"]["template"]["spec"]
    assert pod["serviceAccountName"] == _NAME
    assert pod["automountServiceAccountToken"] is True
    assert pod["restartPolicy"] == "Never"
    assert pod["securityContext"] == {
        "runAsNonRoot": True,
        "runAsUser": 65532,
        "runAsGroup": 65532,
        "fsGroup": 65532,
        "seccompProfile": {"type": "RuntimeDefault"},
    }
    security = _container()["securityContext"]
    assert security["allowPrivilegeEscalation"] is False
    assert security["readOnlyRootFilesystem"] is True
    assert security["capabilities"] == {"drop": ["ALL"]}


def test_health_rbac_is_read_only_without_secret_or_subresource_access() -> None:
    rules = [
        *_document("Role", _NAME)["rules"],
        *_document("ClusterRole", f"{_NAME}-flux-reader")["rules"],
    ]
    observed_resources: set[str] = set()
    observed_verbs: set[str] = set()
    for rule in rules:
        resources = set(rule["resources"])
        verbs = set(rule["verbs"])
        assert resources
        assert verbs
        assert "*" not in resources
        assert "*" not in verbs
        assert verbs <= _READ_ONLY_VERBS
        assert not (resources & _FORBIDDEN_RESOURCES)
        observed_resources.update(resources)
        observed_verbs.update(verbs)

    assert observed_verbs == _READ_ONLY_VERBS
    assert {
        "pods",
        "services",
        "endpoints",
        "endpointslices",
        "deployments",
        "statefulsets",
        "daemonsets",
        "jobs",
        "configmaps",
        "events",
        "networkpolicies",
        "gateways",
        "httproutes",
        "kustomizations",
        "helmreleases",
        "kafkas",
        "kafkaconnects",
        "kafkaconnectors",
        "kafkatopics",
        "servicemonitors",
        "podmonitors",
        "opentelemetrycollectors",
        "grafanadatasources",
        "grafanadashboards",
    } <= observed_resources


def test_health_image_is_inventory_owned_and_digest_rendered() -> None:
    image_inventory = json.loads(_IMAGES.read_text(encoding="utf-8"))
    health_images = [image for image in image_inventory["images"] if image["name"] == "health-runner"]
    assert health_images == [
        {
            "name": "health-runner",
            "context": ".",
            "dockerfile": "scripts/util/health_check/Dockerfile",
            "local": True,
        }
    ]

    container = _container()
    assert container["image"] == f"localhost:5000/health-runner:immutable@{_DIGEST}"
    assert container["imagePullPolicy"] == "IfNotPresent"
    assert re.fullmatch(
        r"localhost:5000/health-runner:immutable@sha256:[0-9a-f]{64}",
        container["image"],
    )

    release = _load(_RELEASE)
    assert release["spec"]["valuesFrom"] == [
        {
            "kind": "ConfigMap",
            "name": "nohiki-image-digests",
            "valuesKey": "values.yaml",
            "optional": False,
        }
    ]
    assert _load(_DIGEST_VALUES)["global"]["imageDigests"] == {}


def test_health_chart_rejects_missing_or_invalid_image_digest() -> None:
    missing = subprocess.run(
        ["helm", "template", _NAME, str(_CHART), "--namespace", "nohiki"],
        cwd=_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    invalid = subprocess.run(
        [
            "helm",
            "template",
            _NAME,
            str(_CHART),
            "--namespace",
            "nohiki",
            "--set-string",
            "global.imageDigests.health-runner=latest",
        ],
        cwd=_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert missing.returncode != 0
    assert "global.imageDigests.health-runner is required" in missing.stderr
    assert invalid.returncode != 0
    assert "health-runner digest must be sha256" in invalid.stderr


def test_health_commands_fail_closed_and_keep_migration_proof_separate() -> None:
    container = _container()
    assert container["command"] == ["/bin/sh", "-ceu"]
    assert len(container["args"]) == 1
    script = container["args"][0]
    inventory = "health-check inventory --target k8s --json"
    migration = "python -m health_check.verify_migrations"
    runtime = "health-check run --target k8s --no-progress --output-mode boring"
    assert script.count(inventory) == 1
    assert script.count(migration) == 1
    assert script.count(runtime) == 1
    assert script.index(inventory) < script.index(migration) < script.index(runtime)
    assert "--inventory /opt/health/migration-heads.json" in script
    assert "--evidence /evidence/migration-heads.json" in script
    assert "alembic" not in inventory
    assert "migration" not in runtime


def test_health_job_uses_cluster_dns_and_explicit_observability_inputs() -> None:
    env_items = _container()["env"]
    literal_env = {item["name"]: item["value"] for item in env_items if "value" in item}
    assert literal_env == {
        "K8S_NAMESPACE": "nohiki",
        "K8S_LOCAL_MODE": "false",
        "E2E_BASE_URL": "http://bff-service:8000",
        "KAFKA_BOOTSTRAP_SERVERS": "nohiki-kafka-bootstrap:9092",
        "VALKEY_URL": "redis://valkey:6379",
        "PROMETHEUS_URL": "http://prometheus-operated:9090",
        "GRAFANA_URL": "http://grafana-service:3000",
        "LOKI_URL": "http://loki-gateway:80",
        "TEMPO_URL": "http://tempo:3200",
        "MIMIR_URL": "http://mimir-nginx:8080",
        "PYROSCOPE_URL": "http://pyroscope:4040",
        "OTEL_COLLECTOR_URL": "http://nohiki-collector-collector:8888",
    }
    database_env = {
        item["name"]: item["valueFrom"]["secretKeyRef"]
        for item in env_items
        if item["name"].startswith("MIGRATION_DATABASE_URL_")
    }
    assert database_env == {
        "MIGRATION_DATABASE_URL_" + service.upper().replace("-", "_"): {
            "name": f"{service}-db-credentials",
            "key": "uri",
        }
        for service in _MIGRATION_SERVICES
    }
    assert "DATABASE_URL" not in {item["name"] for item in env_items}
    assert all("localhost" not in value for value in literal_env.values())
    assert all("127.0.0.1" not in value for value in literal_env.values())
    assert not any("PHOENIX" in item["name"] for item in env_items)


def test_flux_runs_health_helmrelease_and_job_after_observability_ready() -> None:
    flux = _load(_LOCAL / "health.yaml")
    assert flux["metadata"] == {
        "name": "health-verification",
        "namespace": "flux-system",
    }
    assert flux["spec"]["dependsOn"] == [{"name": "observability"}]
    assert flux["spec"]["path"] == "./infra/k8s/gitops/verification"
    assert flux["spec"]["wait"] is True
    assert flux["spec"]["healthChecks"] == [
        {
            "apiVersion": "helm.toolkit.fluxcd.io/v2",
            "kind": "HelmRelease",
            "name": _NAME,
            "namespace": "flux-system",
        },
        {
            "apiVersion": "batch/v1",
            "kind": "Job",
            "name": _NAME,
            "namespace": "nohiki",
        },
    ]
