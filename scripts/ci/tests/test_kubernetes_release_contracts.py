from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

import pytest
from _documents import (
    Manifest,
    load_manifests,
    load_workflow,
    mapping_at,
    mapping_sequence_at,
    metadata_of,
    string_at,
)
from ci_checks.core.image_inventory import load_inventory
from test_image_digest_gitops import _digest_values

_ROOT = Path(__file__).resolve().parents[3]
_CHART = _ROOT / "infra" / "k8s" / "helm"
_OBSERVABILITY = _ROOT / "infra" / "k8s" / "observability"
_WORKFLOW = _ROOT / ".github" / "workflows" / "cd_deploy-to-aks_nohiki.yml"
_IDENTITY = Path(__file__).parent / "fixtures" / "values.prod.identity.yaml"
_NETWORK = Path(__file__).parent / "fixtures" / "values.prod.network.yaml"
_FIRST_PARTY_PREFIX = "ghcr.io/mchar7/nohiki-monorepo/"
_CLUSTER_KINDS = {
    "ClusterRole",
    "ClusterRoleBinding",
    "ClusterSecretStore",
    "CustomResourceDefinition",
    "MutatingWebhookConfiguration",
    "Namespace",
    "ValidatingWebhookConfiguration",
}


def _helm(values_name: str, tmp_path: Path, *extra_args: str) -> list[Manifest]:
    environment = values_name.removeprefix("values.").removesuffix(".yaml")
    command = [
        "helm",
        "template",
        "nohiki",
        str(_CHART),
        "--namespace",
        f"nohiki-{environment}",
        "--values",
        str(_CHART / values_name),
    ]
    if values_name == "values.prod.yaml":
        command.extend(
            (
                "--values",
                str(_IDENTITY),
                "--values",
                str(_NETWORK),
                "--values",
                str(_digest_values(tmp_path)),
            )
        )
    elif values_name == "values.staging.yaml":
        command.extend(("--values", str(_IDENTITY)))
    result = subprocess.run([*command, *extra_args], cwd=_ROOT, capture_output=True, text=True, check=True)
    return load_manifests(result.stdout)


def _kustomize(overlay: str) -> list[Manifest]:
    result = subprocess.run(
        ["kustomize", "build", str(_OBSERVABILITY / "overlays" / overlay)],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return load_manifests(result.stdout)


def _container_images(value: object) -> list[str]:
    if isinstance(value, dict):
        images: list[str] = []
        for key, child in value.items():
            if key in {"containers", "initContainers"} and isinstance(child, list):
                images.extend(
                    image for item in child if isinstance(item, dict) and isinstance(image := item.get("image"), str)
                )
            else:
                images.extend(_container_images(child))
        return images
    if isinstance(value, list):
        return [image for child in value for image in _container_images(child)]
    return []


def _named(documents: list[Manifest], kind: str, name: str) -> Manifest:
    return next(
        document for document in documents if document["kind"] == kind and metadata_of(document)["name"] == name
    )


def test_staging_uses_canonical_first_party_images_and_external_jwt_secret(
    tmp_path: Path,
) -> None:
    names = set(load_inventory().names)
    documents = _helm("values.staging.yaml", tmp_path)
    images = {image for document in documents for image in _container_images(document)}
    first_party = {image for image in images if any(f"/{name}:" in image for name in names)}
    assert first_party
    assert all(image.startswith(_FIRST_PARTY_PREFIX) for image in first_party)
    assert {
        f"{_FIRST_PARTY_PREFIX}user-auth-service:sha-933dda3",
        f"{_FIRST_PARTY_PREFIX}sys-tick-job:sha-933dda3",
    } <= first_party

    assert not any(
        document["kind"] == "Secret" and metadata_of(document)["name"] == "nohiki-jwt-keys" for document in documents
    )
    jwt = _named(documents, "ExternalSecret", "nohiki-jwt-keys")
    assert metadata_of(jwt)["namespace"] == "nohiki-staging"
    assert mapping_at(jwt, "spec", "secretStoreRef") == {
        "name": "nohiki-secret-store",
        "kind": "ClusterSecretStore",
    }
    assert mapping_at(jwt, "spec", "target") == {
        "name": "nohiki-jwt-keys",
        "creationPolicy": "Owner",
    }
    assert mapping_sequence_at(jwt, "spec", "data") == [
        {"secretKey": "private_key", "remoteRef": {"key": "jwt-private-key"}}
    ]


def test_production_kafka_scalers_require_authenticated_tls(tmp_path: Path) -> None:
    documents = _helm("values.prod.yaml", tmp_path)
    rendered_protocols: set[str] = set()
    for document in documents:
        if document.get("kind") != "Deployment":
            continue
        containers = mapping_at(document, "spec", "template", "spec").get("containers", [])
        assert isinstance(containers, list)
        for container in containers:
            assert isinstance(container, dict)
            environment = container.get("env", [])
            assert isinstance(environment, list)
            for entry in environment:
                assert isinstance(entry, dict)
                name = entry.get("name", "")
                if isinstance(name, str) and name.endswith("KAFKA__SECURITY__PROTOCOL"):
                    value = entry.get("value")
                    assert isinstance(value, str)
                    rendered_protocols.add(value)
    assert rendered_protocols == {"SASL_SSL"}

    auth = _named(documents, "TriggerAuthentication", "nohiki-kafka-auth")
    auth_name = metadata_of(auth)["name"]
    refs = {
        string_at(item, "parameter"): (string_at(item, "name"), string_at(item, "key"))
        for item in mapping_sequence_at(auth, "spec", "secretTargetRef")
    }
    assert refs == {
        "sasl": ("kafka-sasl-credentials", "mechanism"),
        "username": ("kafka-sasl-credentials", "username"),
        "password": ("kafka-sasl-credentials", "password"),
    }

    scalers = [document for document in documents if document["kind"] == "ScaledObject"]
    assert scalers
    kafka_triggers = [
        (metadata_of(scaler)["name"], trigger)
        for scaler in scalers
        for trigger in mapping_sequence_at(scaler, "spec", "triggers")
        if trigger.get("type") == "kafka"
    ]
    assert kafka_triggers
    for scaler_name, trigger in kafka_triggers:
        assert mapping_at(trigger, "metadata").get("tls") == "enable", scaler_name
        assert mapping_at(trigger, "authenticationRef") == {"name": auth_name}, scaler_name
    assert any(document.get("kind") == "HTTPScaledObject" for document in documents)
    keda_installer = (_ROOT / "infra" / "terraform" / "keda.tf").read_text(encoding="utf-8")
    assert 'resource "helm_release" "keda"' in keda_installer
    assert 'count            = var.deployment_type == "aks" ? 1 : 0' in keda_installer


@pytest.mark.parametrize(
    ("overlay", "namespace"),
    [("staging", "nohiki-staging"), ("prod", "nohiki-prod")],
)
def test_observability_overlays_keep_namespaced_resources_in_environment_namespace(
    overlay: str, namespace: str
) -> None:
    documents = _kustomize(overlay)
    assert documents
    namespaced = [document for document in documents if document["kind"] not in _CLUSTER_KINDS]
    assert namespaced
    assert all(metadata_of(document).get("namespace") == namespace for document in namespaced)
    for kind in ("Grafana", "GrafanaDatasource", "OpenTelemetryCollector"):
        assert any(
            document["kind"] == kind and metadata_of(document).get("namespace") == namespace for document in documents
        )


def test_promotion_validates_merge_revision_renders_all_manifests_and_opens_activation_pr() -> None:
    workflow = load_workflow(_WORKFLOW)
    activation = workflow["jobs"]["activate-production-runtime"]
    condition = activation["if"]
    assert "github.event_name == 'pull_request'" in condition
    assert "github.event.action == 'closed'" in condition
    assert "github.event.pull_request.merged == true" in condition
    assert "github.event.pull_request.head.ref == 'bot/update-production-runtime'" in condition
    assert activation["env"]["RELEASE_SHA"] == "${{ github.event.pull_request.merge_commit_sha }}"

    checkout = next(step for step in activation["steps"] if step.get("name") == "Checkout merged runtime revision")
    assert checkout["with"]["ref"] == "${{ github.event.pull_request.merge_commit_sha }}"

    verify = next(step for step in activation["steps"] if step.get("name") == "Verify immutable release inputs")
    verify_run = verify["run"]
    required_paths = {
        "infra/k8s/helm/values.prod.yaml",
        "infra/k8s/helm/values.prod.identity.yaml",
        "infra/k8s/helm/values.prod.network.yaml",
        "infra/k8s/helm/values.prod.digests.yaml",
        "infra/k8s/observability/overlays/prod/kustomization.yaml",
        "infra/k8s/observability/overlays/prod/otel-receiver-pki.yaml",
        "infra/k8s/gitops/clusters/prod-aks/kustomization.yaml",
        "infra/k8s/gitops/clusters/prod-aks/release-source.yaml",
        "infra/k8s/gitops/clusters/prod-aks/infrastructure.yaml",
        "infra/k8s/gitops/clusters/prod-aks/platform.yaml",
        "infra/k8s/gitops/clusters/prod-aks/observability.yaml",
        "infra/k8s/helm-foundation/Chart.yaml",
        "infra/k8s/helm-foundation/Chart.lock",
        "infra/k8s/helm-foundation/charts/cert-manager-v1.21.0.tgz",
        "infra/k8s/helm-foundation/templates/clusterissuer.yaml",
        "infra/k8s/helm-foundation/values.yaml",
        "infra/k8s/gitops/gateway-api-crds/kustomization.yaml",
        "infra/k8s/gitops/gateway-api-crds/gateway-api-crds.yaml",
        "infra/k8s/gitops/clusters/prod-aks/gateway-api-crds.yaml",
    }
    _before, loop_start, remainder = verify_run.partition("for path in")
    allowlist, loop_end, _after = remainder.partition("; do")
    assert loop_start, "immutable-input loop could not be parsed"
    assert loop_end, "immutable-input loop could not be parsed"
    guarded_paths = [token for token in shlex.split(allowlist) if token.strip()]
    assert len(guarded_paths) == len(set(guarded_paths))
    assert set(guarded_paths) == required_paths
    assert "infra/k8s/helm-foundation/templates/gateway-api-crds.yaml" not in guarded_paths
    assert 'git cat-file -e "$RELEASE_SHA:$path"' in verify_run
    assert "helm template nohiki infra/k8s/helm" in verify_run
    assert "kustomize build infra/k8s/observability/overlays/prod" in verify_run
    assert "kustomize build infra/k8s/gitops/infrastructure/prod" in verify_run
    assert "kustomize build infra/k8s/gitops/platform/prod" in verify_run
    assert "kustomize build infra/k8s/gitops/clusters/prod-aks" in verify_run
    assert "helm dependency update infra/k8s/helm-foundation" in verify_run
    assert "helm template nohiki-foundation" in verify_run

    stamp = next(
        step for step in activation["steps"] if step.get("name") == "Stamp and activate production GitOps source"
    )
    stamp_run = stamp["run"]
    assert 'text.replace("commit: PROMOTION_REQUIRED", f"commit: {sha}")' in stamp_run
    assert "infra/k8s/gitops/clusters/prod-aks" in stamp_run
    assert 'base / "release-source.yaml"' in stamp_run
    for stack in (
        "gateway-api-crds.yaml",
        "infrastructure.yaml",
        "platform.yaml",
        "observability.yaml",
    ):
        assert stack in stamp_run
    assert 'text.replace("suspend: true", "suspend: false")' in stamp_run

    activation_runs = "\n".join(step.get("run", "") for step in activation["steps"])
    for forbidden in (
        "helm install",
        "helm upgrade",
        "kubectl apply",
        "flux bootstrap",
        "git push",
        "argocd",
        "ApplicationSet",
        "sync-wave",
        "targetRevision",
    ):
        assert forbidden not in activation_runs, forbidden

    pr = next(step for step in activation["steps"] if "create-pull-request" in step.get("uses", ""))
    inputs = pr["with"]
    branch = string_at(inputs, "branch")
    assert branch.startswith("bot/activate-production-runtime-")
    assert "${{ github.event.pull_request.merge_commit_sha }}" in branch
    assert string_at(inputs, "base") == "${{ github.event.repository.default_branch }}"
    assert set(string_at(inputs, "add-paths").splitlines()) == {
        "infra/k8s/gitops/clusters/prod-aks/release-source.yaml",
        "infra/k8s/gitops/clusters/prod-aks/gateway-api-crds.yaml",
        "infra/k8s/gitops/clusters/prod-aks/infrastructure.yaml",
        "infra/k8s/gitops/clusters/prod-aks/platform.yaml",
        "infra/k8s/gitops/clusters/prod-aks/observability.yaml",
    }
