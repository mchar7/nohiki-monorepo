"""Cross-render contracts for continuously reconciled observability resources."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml
from ci_checks.core.image_inventory import load_inventory

ROOT = Path(__file__).resolve().parents[4]
CHART = ROOT / "infra/k8s/helm"
GITOPS = ROOT / "infra/k8s/gitops"
OBSERVABILITY = ROOT / "infra/k8s/observability"
IDENTITY_FIXTURE = ROOT / "scripts/ci/tests/fixtures/values.prod.identity.yaml"
NETWORK_FIXTURE = ROOT / "scripts/ci/tests/fixtures/values.prod.network.yaml"

ENVIRONMENTS = {
    "local": ("local", "nohiki", "values.local.yaml"),
    "dev-aks": ("dev", "nohiki-dev", "values.dev.yaml"),
    "staging-aks": ("staging", "nohiki-staging", "values.staging.yaml"),
    "prod-aks": ("prod", "nohiki-prod", "values.prod.yaml"),
}
GRAFANA_KINDS = {
    "Grafana",
    "GrafanaDashboard",
    "GrafanaDatasource",
    "GrafanaFolder",
}
OVERLAY_READINESS_KINDS = {
    "Certificate",
    "ExternalSecret",
    "Issuer",
    "OpenTelemetryCollector",
} | GRAFANA_KINDS
OBSERVABILITY_WORKLOAD = re.compile(r"(?:grafana-operator|loki|mimir|pyroscope|tempo)")
PROMETHEUS_COMPONENTS = {
    ("apps/v1", "Deployment", "nohiki-kube-prometheus-sta-operator"),
    (
        "monitoring.coreos.com/v1",
        "Prometheus",
        "nohiki-kube-prometheus-sta-prometheus",
    ),
    (
        "monitoring.coreos.com/v1",
        "Alertmanager",
        "nohiki-kube-prometheus-sta-alertmanager",
    ),
    ("apps/v1", "Deployment", "nohiki-kube-state-metrics"),
    ("apps/v1", "DaemonSet", "nohiki-prometheus-node-exporter"),
}
OBSERVABILITY_EXTERNAL_SECRETS = {
    "local": set(),
    "dev": {
        "grafana-admin-credentials",
        "grafana-oauth-credentials",
        "observability-storage-credentials",
    },
    "staging": {
        "grafana-admin-credentials",
        "grafana-oauth-credentials",
        "observability-storage-credentials",
    },
    "prod": {
        "grafana-admin-credentials",
        "grafana-oauth-credentials",
        "observability-storage-credentials",
    },
}
AGE_RECIPIENT = re.compile(r"age1[023456789acdefghjklmnpqrstuvwxyz]{58}")
PLACEHOLDER = re.compile(r"placeholder|promotion.required|replace|change.me|example", re.IGNORECASE)

ResourceId = tuple[str, str, str, str]


def _documents(output: str) -> list[dict[str, Any]]:
    return [document for document in yaml.safe_load_all(output) if isinstance(document, dict)]


def _run(*command: str) -> list[dict[str, Any]]:
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=True)
    return _documents(result.stdout)


def _kustomize(relative: str) -> list[dict[str, Any]]:
    return _run("kubectl", "kustomize", relative)


def _digest_values(tmp_path: Path) -> Path:
    digests = {name: f"sha256:{index + 1:064x}" for index, name in enumerate(load_inventory().names)}
    path = tmp_path / "values.prod.digests.yaml"
    path.write_text(yaml.safe_dump({"global": {"imageDigests": digests}}), encoding="utf-8")
    return path


def _helm(values_file: str, namespace: str, tmp_path: Path) -> list[dict[str, Any]]:
    command = [
        "helm",
        "template",
        "nohiki",
        str(CHART),
        "--namespace",
        namespace,
        "--values",
        str(CHART / "values.yaml"),
        "--values",
        str(CHART / values_file),
    ]
    if values_file in {"values.dev.yaml", "values.staging.yaml"}:
        command.extend(
            (
                "--set-string",
                "global.eso.azure.keyVaultUrl=https://nohiki-test-kv.vault.azure.net",
                "--set-string",
                "global.eso.azure.clientId=00000000-0000-4000-8000-000000000000",
                "--set-string",
                "global.eso.azure.tenantId=11111111-1111-4111-8111-111111111111",
            )
        )
    if values_file == "values.prod.yaml":
        for overlay in (IDENTITY_FIXTURE, NETWORK_FIXTURE, _digest_values(tmp_path)):
            command.extend(("--values", str(overlay)))
    return _run(*command)


def _identity(document: dict[str, Any]) -> ResourceId:
    metadata = document["metadata"]
    return (
        document["apiVersion"],
        document["kind"],
        metadata.get("namespace", ""),
        metadata["name"],
    )


def _observability_stack(cluster: str) -> dict[str, Any]:
    return next(
        document
        for document in _kustomize(f"infra/k8s/gitops/clusters/{cluster}")
        if document.get("kind") == "Kustomization" and document.get("metadata", {}).get("name") == "observability"
    )


def _required_resources(environment: str, namespace: str, values_file: str, tmp_path: Path) -> set[ResourceId]:
    overlay = _kustomize(f"infra/k8s/observability/overlays/{environment}")
    helm = _helm(values_file, namespace, tmp_path)

    required = {_identity(document) for document in overlay if document.get("kind") in OVERLAY_READINESS_KINDS}
    required.update(
        _identity(document)
        for document in helm
        if document.get("kind") in {"DaemonSet", "Deployment", "StatefulSet"}
        and OBSERVABILITY_WORKLOAD.search(document.get("metadata", {}).get("name", ""))
    )

    prometheus_components = {
        (document["apiVersion"], document["kind"], document["metadata"]["name"])
        for document in helm
        if (
            document.get("apiVersion"),
            document.get("kind"),
            document.get("metadata", {}).get("name"),
        )
        in PROMETHEUS_COMPONENTS
    }
    assert prometheus_components == PROMETHEUS_COMPONENTS, (
        f"{environment}: missing Prometheus components {sorted(PROMETHEUS_COMPONENTS - prometheus_components)!r}"
    )
    required.update(
        _identity(document)
        for document in helm
        if (
            document.get("apiVersion"),
            document.get("kind"),
            document.get("metadata", {}).get("name"),
        )
        in PROMETHEUS_COMPONENTS
    )

    collectors = [document for document in overlay if document.get("kind") == "OpenTelemetryCollector"]
    assert len(collectors) == 1, f"{environment}: expected one OpenTelemetryCollector"
    collector = collectors[0]
    required.add(
        (
            "apps/v1",
            "Deployment",
            collector["metadata"].get("namespace", namespace),
            f"{collector['metadata']['name']}-collector",
        )
    )
    return required


@pytest.mark.parametrize("cluster", ENVIRONMENTS)
def test_flux_health_checks_exactly_cover_required_observability_resources(cluster: str, tmp_path: Path) -> None:
    environment, namespace, values_file = ENVIRONMENTS[cluster]
    spec = _observability_stack(cluster)["spec"]
    assert spec["wait"] is False, f"{cluster}: explicit health checks must remain authoritative"

    expected = _required_resources(environment, namespace, values_file, tmp_path)
    actual = {
        (check["apiVersion"], check["kind"], check.get("namespace", ""), check["name"])
        for check in spec["healthChecks"]
    }
    assert actual == expected, (
        f"{cluster}: missing required health targets={sorted(expected - actual)!r}; "
        f"targets absent from emitted resources={sorted(actual - expected)!r}"
    )


@pytest.mark.parametrize("cluster", ENVIRONMENTS)
def test_required_observability_external_secrets_reconcile_continuously(
    cluster: str,
) -> None:
    environment, _, _ = ENVIRONMENTS[cluster]
    external_secrets = [
        document
        for document in _kustomize(f"infra/k8s/observability/overlays/{environment}")
        if document.get("kind") == "ExternalSecret"
    ]
    assert {secret["metadata"]["name"] for secret in external_secrets} == (OBSERVABILITY_EXTERNAL_SECRETS[environment])

    for secret in external_secrets:
        spec = secret["spec"]
        assert spec.get("refreshPolicy", "Periodic") == "Periodic", secret["metadata"]["name"]
        assert str(spec.get("refreshInterval", "1h")) not in {"0", "0s"}, secret["metadata"]["name"]
        assert spec["target"]["creationPolicy"] == "Owner", secret["metadata"]["name"]


def _versioned_sops_policies() -> list[Path]:
    # Use the index so ignored backups cannot masquerade as active policy.
    listing = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "--cached", "-z"],
        capture_output=True,
        check=True,
    )
    names = {".sops.yaml", ".sops.yml"}
    return sorted(ROOT / entry for entry in listing.stdout.decode().split("\0") if entry and Path(entry).name in names)


def test_one_active_sops_policy_covers_every_encrypted_gitops_secret_path() -> None:
    policies = _versioned_sops_policies()
    assert policies == [ROOT / ".sops.yaml"], f"expected one active SOPS policy, got {policies!r}"

    policy = yaml.safe_load(policies[0].read_text(encoding="utf-8"))
    rules = policy.get("creation_rules", [])
    assert len(rules) == 1, f"expected exactly one active SOPS creation rule, got {len(rules)}"
    rule = rules[0]
    recipient = rule.get("age", "")
    assert AGE_RECIPIENT.fullmatch(recipient), "SOPS policy must use one syntactically valid age recipient"
    assert not PLACEHOLDER.search(recipient), "SOPS age recipient must not be a placeholder"
    assert rule.get("encrypted_regex") == "^(data|stringData)$"

    encrypted_paths = sorted((GITOPS / "secrets").rglob("*.sops.yaml"))
    assert encrypted_paths, "no encrypted GitOps secret paths found"
    pattern = re.compile(rule["path_regex"])
    uncovered = [
        path.relative_to(ROOT).as_posix()
        for path in encrypted_paths
        if not pattern.fullmatch(path.relative_to(ROOT).as_posix())
    ]
    assert not uncovered, f"encrypted GitOps secret paths not covered by the active SOPS policy: {uncovered!r}"


def test_postbuild_configmap_ownership_matches_environment_activation() -> None:
    references: dict[str, set[str]] = {}
    for cluster in ENVIRONMENTS:
        references[cluster] = {
            source["name"]
            for document in _kustomize(f"infra/k8s/gitops/clusters/{cluster}")
            if document.get("kind") == "Kustomization"
            for source in document.get("spec", {}).get("postBuild", {}).get("substituteFrom", [])
            if source.get("kind", "ConfigMap") == "ConfigMap" and not source.get("optional", False)
        }

    assert references == {
        "local": set(),
        "dev-aks": {"gitops-runtime"},
        "staging-aks": {"gitops-runtime"},
        "prod-aks": set(),
    }


def test_sops_policy_discovery_ignores_untracked_copies_but_not_staged_ones(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    (repository / "nested").mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
    (repository / ".sops.yaml").write_text("creation_rules: []\n", encoding="utf-8")
    (repository / ".gitignore").write_text("ignored/\n", encoding="utf-8")
    (repository / "ignored").mkdir()
    (repository / "ignored" / ".sops.yaml").write_text("creation_rules: []\n", encoding="utf-8")
    subprocess.run(["git", "add", ".sops.yaml", ".gitignore"], cwd=repository, check=True)

    def discovered() -> list[str]:
        listing = subprocess.run(
            ["git", "-C", str(repository), "ls-files", "--cached", "-z"],
            capture_output=True,
            check=True,
        )
        names = {".sops.yaml", ".sops.yml"}
        return sorted(e for e in listing.stdout.decode().split("\0") if e and Path(e).name in names)

    assert discovered() == [".sops.yaml"]

    (repository / "nested" / ".sops.yaml").write_text("creation_rules: []\n", encoding="utf-8")
    subprocess.run(["git", "add", "nested/.sops.yaml"], cwd=repository, check=True)

    assert discovered() == [".sops.yaml", "nested/.sops.yaml"]
