"""Static contracts for the in-cluster health verification Helm release."""

from __future__ import annotations

import json
import re
import subprocess
from functools import cache
from pathlib import Path
from typing import Any

import yaml
from ci_checks.core.image_inventory import load_inventory

_ROOT = Path(__file__).resolve().parents[3]
_CHART = _ROOT / "infra" / "k8s" / "verification" / "health"
_RELEASE = _ROOT / "infra" / "k8s" / "gitops" / "verification" / "helmrelease.yaml"
_PLATFORM_CHART = _ROOT / "infra" / "k8s" / "helm"
_LOCAL = _ROOT / "infra" / "k8s" / "gitops" / "clusters" / "local"
_DOCKERFILE = _ROOT / "scripts" / "util" / "health_check" / "Dockerfile"
_DIGEST_VALUES = _ROOT / "infra" / "k8s" / "gitops" / "platform" / "local" / "image-digests.values.yaml"
_HEALTH_PROJECT = _ROOT / "scripts" / "util" / "health_check"
_CDC_ADAPTER = _HEALTH_PROJECT / "src" / "health_check" / "acceptance" / "live_cluster_cdc.py"
_NAME = "nohiki-health-verification"
_DIGEST = "sha256:" + "a" * 64
_DEPENDENCY_MODULES = {
    "user-pref-service": {"nohiki_kafka_client", "nohiki_db_utils"},
    "job-ingest-enrichment-service": {"nohiki_kafka_client", "nohiki_llm_client"},
    "job-correlation-evaluation-service": {"nohiki_kafka_client", "nohiki_qdrant_client"},
    "ml-compute-service": {"nohiki_ml_core", "nohiki_kafka_client"},
}
_IMAGE_DIGESTS = {
    "health-runner": _DIGEST,
    **{service: f"sha256:{character * 64}" for service, character in zip(_DEPENDENCY_MODULES, "bcde", strict=True)},
}
_READ_ONLY_VERBS = {"get", "list", "watch"}
_FORBIDDEN_RESOURCES = {"pods/portforward"}
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
            "--set-json",
            f"global.imageDigests={json.dumps(_IMAGE_DIGESTS)}",
        ],
        cwd=_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return tuple(document for document in yaml.safe_load_all(result.stdout) if isinstance(document, dict))


@cache
def _platform_render() -> tuple[dict[str, Any], ...]:
    result = subprocess.run(
        [
            "helm",
            "template",
            "nohiki",
            ".",
            "--values",
            "values.yaml",
            "--values",
            "values.local.yaml",
            "--namespace",
            "nohiki",
        ],
        cwd=_PLATFORM_CHART,
        check=True,
        capture_output=True,
        text=True,
    )
    return tuple(document for document in yaml.safe_load_all(result.stdout) if isinstance(document, dict))


def _platform_service_name(app_name: str, *, component: str | None = None) -> str:
    matches = [
        document["metadata"]["name"]
        for document in _platform_render()
        if document.get("kind") == "Service"
        and document.get("metadata", {}).get("labels", {}).get("app.kubernetes.io/name") == app_name
        and (
            component is None
            or document.get("metadata", {}).get("labels", {}).get("app.kubernetes.io/component") == component
        )
    ]
    assert len(matches) == 1, (app_name, component, matches)
    return matches[0]


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


def test_health_rbac_limits_cdc_mutations_and_secret_reads() -> None:
    role_rules = _document("Role", _NAME)["rules"]
    cluster_rules = _document("ClusterRole", f"{_NAME}-flux-reader")["rules"]
    rules = [*role_rules, *cluster_rules]
    observed_resources: set[str] = set()
    observed_verbs: set[str] = set()
    mutation_rules: list[dict[str, Any]] = []
    for rule in rules:
        resources = set(rule["resources"])
        verbs = set(rule["verbs"])
        assert resources
        assert verbs
        assert "*" not in resources
        assert "*" not in verbs
        assert not (resources & _FORBIDDEN_RESOURCES)
        if not verbs <= _READ_ONLY_VERBS:
            mutation_rules.append(rule)
        observed_resources.update(resources)
        observed_verbs.update(verbs)

    assert mutation_rules == [
        {"apiGroups": [""], "resources": ["pods/exec"], "verbs": ["create"]},
        {
            "apiGroups": ["apps"],
            "resources": ["deployments"],
            "resourceNames": ["nohiki-connect-connect"],
            "verbs": ["patch"],
        },
    ]
    assert [rule for rule in role_rules if "secrets" in rule["resources"]] == [
        {
            "apiGroups": [""],
            "resources": ["secrets"],
            "resourceNames": [
                "user-auth-service-db-credentials",
                "user-auth-service-debezium-credentials",
            ],
            "verbs": ["get"],
        }
    ]
    assert observed_verbs == _READ_ONLY_VERBS | {"create", "patch"}
    assert {
        "pods",
        "pods/exec",
        "services",
        "secrets",
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
    health_records = [record for record in load_inventory().images if record.name == "health-runner"]
    assert len(health_records) == 1
    health = health_records[0]
    assert health.context == "."
    assert health.dockerfile == "scripts/util/health_check/Dockerfile"
    assert health.lockfile == "uv.lock"
    assert health.build_args == ""
    assert health.timeout == 16
    assert "backend/libs/" in health.ownership
    assert "backend/services/" not in health.ownership
    assert "scripts/ci/" not in health.ownership
    assert "scripts/util/health_check/" in health.ownership
    assert _CDC_ADAPTER.is_file()
    dockerfile = _DOCKERFILE.read_text(encoding="utf-8")
    project = (_HEALTH_PROJECT / "pyproject.toml").read_text(encoding="utf-8")
    assert "COPY scripts/util/health_check ./scripts/util/health_check/" in dockerfile
    assert "uv sync --frozen --package health-check --no-dev --no-editable" in dockerfile
    assert "/usr/local/bin/kubectl" in dockerfile
    assert '"httpx>=0.28.0"' in project

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
    committed_digests = _load(_DIGEST_VALUES)["global"]["imageDigests"]
    assert isinstance(committed_digests, dict)
    if committed_digests:
        assert re.fullmatch(r"sha256:[0-9a-f]{64}", committed_digests["health-runner"])


def test_service_dependency_init_containers_use_workload_digests_and_fail_closed_evidence() -> None:
    pod = _job()["spec"]["template"]["spec"]
    init_containers = pod["initContainers"]
    assert len(init_containers) == len(_DEPENDENCY_MODULES)
    for container in init_containers:
        service = container["name"].removeprefix("dependency-") + "-service"
        assert service in _DEPENDENCY_MODULES
        repository = f"localhost:5000/{service}"
        assert container["image"] == f"{repository}:immutable@{_IMAGE_DIGESTS[service]}"
        assert container["command"] == ["python", "-c"]
        assert len(container["args"]) == 1
        script = container["args"][0]
        assert set(re.findall(r'"(nohiki_[a-z0-9_]+)"', script)) == _DEPENDENCY_MODULES[service]
        assert f'{service}.json"' in script
        assert "find_spec(module) is not None" in script
        assert container["volumeMounts"] == [{"name": "evidence", "mountPath": "/evidence"}]
        assert container["securityContext"] == {
            "allowPrivilegeEscalation": False,
            "readOnlyRootFilesystem": True,
            "capabilities": {"drop": ["ALL"]},
        }

    assert {"name": "evidence", "emptyDir": {}} in pod["volumes"]


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
    adapter = "python -m health_check.acceptance.live_cluster_cdc"
    inventory = "health-check inventory --target k8s --json"
    migration = "python -m health_check.verify_migrations"
    runtime = "health-check run --target k8s --no-progress --output-mode boring"
    assert script.count(adapter) == 1
    assert script.count(inventory) == 1
    assert script.count(migration) == 1
    assert script.count(runtime) == 1
    assert script.index(adapter) < script.index(inventory) < script.index(migration) < script.index(runtime)
    assert '--namespace "$K8S_NAMESPACE"' in script
    assert '--base-url "$E2E_BASE_URL"' in script
    assert '--evidence "$CDC_ACCEPTANCE_EVIDENCE"' in script
    assert "--inventory /opt/health/migration-heads.json" in script
    assert "--evidence /evidence/migration-heads.json" in script
    assert "alembic" not in inventory
    assert "migration" not in runtime


def test_health_job_uses_cluster_dns_and_explicit_observability_inputs() -> None:
    bff_service = _platform_service_name("bff-service")
    valkey_service = _platform_service_name("valkey", component="primary")
    kafka_resources = [
        document["metadata"]["name"] for document in _platform_render() if document.get("kind") == "Kafka"
    ]
    assert len(kafka_resources) == 1
    kafka_bootstrap = f"{kafka_resources[0]}-kafka-bootstrap:9092"
    env_items = _container()["env"]
    literal_env = {item["name"]: item["value"] for item in env_items if "value" in item}
    assert literal_env == {
        "K8S_NAMESPACE": "nohiki",
        "K8S_LOCAL_MODE": "false",
        "K8S_SERVICE_DEPENDENCY_EVIDENCE_DIR": "/evidence/service-dependencies",
        "CDC_ACCEPTANCE_EVIDENCE": "/evidence/live-cdc.json",
        "E2E_BASE_URL": f"http://{bff_service}:8000",
        "KAFKA_BOOTSTRAP_SERVERS": kafka_bootstrap,
        "VALKEY_URL": f"redis://{valkey_service}:6379",
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
