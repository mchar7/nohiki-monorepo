"""Regression coverage for External Secrets Operator ownership and delivery.

The declarative foundation owns exactly one External Secrets Operator (plus its
CRDs); the platform umbrella no longer bundles the operator. The platform chart
renders the chart-managed ServiceAccount, ClusterSecretStore, and ExternalSecrets
for dev/staging/prod, and the shared observability overlays reuse that store instead
of defining their own. Local provider sources are SOPS-owned, the platform derives
only the enabled providers through a namespaced SecretStore, and the observability
overlay defines no credential fallback. Everything is asserted against rendered
manifests or in-tree metadata; no secret values are inspected.
"""

import hashlib
import importlib.util
import re
import shutil
import subprocess
import tarfile
from pathlib import Path
from typing import Any

import pytest
import yaml
from helm_test_utils import runtime_eso_args

_ROOT = Path(__file__).resolve().parents[3]
_CHART = _ROOT / "infra" / "k8s" / "helm"
_FOUNDATION = _ROOT / "infra" / "k8s" / "helm-foundation"
_OBSERVABILITY = _ROOT / "infra" / "k8s" / "observability"
_AKS_TF = _ROOT / "infra" / "terraform" / "aks.tf"
_LOCAL_SECRET_CONTRACT = _ROOT / "scripts" / "infra" / "local_secret_contract.py"

_ESO_CHART_LEDGER = ("2.7.0", "a2ce165cc59b74c88451c9e21eb72c329b392506c53763df19061e62ec29ac60")
_STORE_NAME = "nohiki-secret-store"
_SA_NAME = "external-secrets-sa"
_PINNED_IMAGE = re.compile(r"[A-Za-z0-9./_-]+:[A-Za-z0-9_.-]+@sha256:[0-9a-f]{64}")

# Shared (non per-service-database) secrets every managed environment must project.
_SHARED_SECRETS = frozenset(
    {
        "nohiki-redis-credentials",
        "nohiki-jwt-keys",
        "nohiki-oauth-credentials",
        "nohiki-email-api-keys",
        "nohiki-jsearch-api-keys",
        "nohiki-s3-credentials",
        "qdrant-api-key",
        "auth-listings-secret",
        "kafka-sasl-credentials",
    }
)
_MODEL_EGRESS_TLS_EXTERNAL_SECRETS = frozenset({"nohiki-model-egress-tls", "nohiki-model-egress-ca"})


def _load(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _enabled_provider_credentials(values_name: str) -> tuple[str, ...]:
    spec = importlib.util.spec_from_file_location("test_eso_local_secret_contract", _LOCAL_SECRET_CONTRACT)
    assert spec is not None
    assert spec.loader is not None
    contract = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(contract)
    return contract.enabled_provider_credentials(_CHART / "values.yaml", _CHART / values_name)


def _model_egress_client_secrets() -> frozenset[str]:
    values = _load(_CHART / "values.yaml")
    return frozenset(client["secretName"] for client in values["global"]["modelEgress"]["clients"])


def _model_egress_external_secrets(values_name: str) -> frozenset[str]:
    providers = _enabled_provider_credentials(values_name)
    return (
        _MODEL_EGRESS_TLS_EXTERNAL_SECRETS
        | _model_egress_client_secrets()
        | {f"nohiki-model-egress-{provider}" for provider in providers}
    )


def _render_platform(environment: str, namespace: str, *, eso_identity: bool) -> tuple[dict[str, Any], ...]:
    command = [
        "helm",
        "template",
        "nohiki",
        ".",
        "-f",
        "values.yaml",
        "-f",
        f"values.{environment}.yaml",
        "-n",
        namespace,
    ]
    if eso_identity:
        command.extend(runtime_eso_args(environment))
    result = subprocess.run(command, cwd=_CHART, capture_output=True, text=True, check=True)
    return tuple(
        document for document in yaml.load_all(result.stdout, Loader=yaml.CSafeLoader) if isinstance(document, dict)
    )


def _kustomize(overlay: str) -> tuple[dict[str, Any], ...]:
    command = ["kustomize", "build"] if shutil.which("kustomize") else ["kubectl", "kustomize"]
    if not shutil.which(command[0]):
        pytest.skip("kustomize or kubectl is required to render manifests")
    result = subprocess.run(
        [*command, str(_OBSERVABILITY / "overlays" / overlay)],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return tuple(
        document for document in yaml.load_all(result.stdout, Loader=yaml.CSafeLoader) if isinstance(document, dict)
    )


class _HelmLoader(yaml.CSafeLoader):
    pass


_HelmLoader.add_constructor("tag:yaml.org,2002:value", lambda loader, node: loader.construct_scalar(node))


def _render_foundation(*, include_crds: bool = False) -> tuple[dict[str, Any], ...]:
    command = ["helm", "template", "nohiki-foundation", str(_FOUNDATION)]
    if include_crds:
        command.append("--include-crds")
    result = subprocess.run(command, cwd=_ROOT, capture_output=True, text=True, check=True)
    return tuple(
        document for document in yaml.load_all(result.stdout, Loader=_HelmLoader) if isinstance(document, dict)
    )


@pytest.fixture(scope="module")
def foundation_documents() -> tuple[dict[str, Any], ...]:
    """Render foundation workloads and CRDs once."""
    return _render_foundation(include_crds=True)


@pytest.fixture(scope="module")
def platform_documents() -> dict[str, tuple[dict[str, Any], ...]]:
    """Render each immutable platform values variant once."""
    return {
        "dev": _render_platform("dev", "nohiki-dev", eso_identity=True),
        "staging": _render_platform("staging", "nohiki-staging", eso_identity=True),
        "local": _render_platform("local", "nohiki", eso_identity=False),
    }


@pytest.fixture(scope="module")
def observability_documents() -> dict[str, tuple[dict[str, Any], ...]]:
    """Render each immutable observability overlay once."""
    return {overlay: _kustomize(overlay) for overlay in ("dev", "staging", "prod", "local")}


def _named(documents: tuple[dict[str, Any], ...], kind: str, name: str) -> dict[str, Any]:
    return next(
        document
        for document in documents
        if document.get("kind") == kind and document.get("metadata", {}).get("name") == name
    )


def _hcl_block(text: str, header: str) -> str:
    start = text.index(header)
    depth = 0
    for offset, char in enumerate(text[start:], start=start):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : offset + 1]
    message = f"unbalanced block for {header!r}"
    raise AssertionError(message)


def test_foundation_owns_the_single_external_secrets_operator_and_crds() -> None:
    chart = _load(_FOUNDATION / "Chart.yaml")
    dependencies = [dep for dep in chart["dependencies"] if dep["name"] == "external-secrets"]
    assert len(dependencies) == 1
    dependency = dependencies[0]

    lock = _load(_FOUNDATION / "Chart.lock")
    locked_dependencies = [dep for dep in lock["dependencies"] if dep["name"] == dependency["name"]]
    assert len(locked_dependencies) == 1
    locked_dependency = locked_dependencies[0]
    assert dependency["version"] == locked_dependency["version"]
    ledger_version, ledger_sha256 = _ESO_CHART_LEDGER
    assert locked_dependency["version"] == ledger_version
    assert dependency["repository"] == locked_dependency["repository"]

    values = _load(_FOUNDATION / "values.yaml")
    eso = values["external-secrets"]
    assert eso["enabled"] is True
    assert eso["installCRDs"] is True

    archive = _FOUNDATION / "charts" / f"{locked_dependency['name']}-{locked_dependency['version']}.tgz"
    assert archive.exists()
    with tarfile.open(archive, mode="r:gz") as chart_archive:
        metadata_file = chart_archive.extractfile(f"{locked_dependency['name']}/Chart.yaml")
        assert metadata_file is not None
        metadata: object = yaml.safe_load(metadata_file)
    assert isinstance(metadata, dict)
    assert metadata["name"] == locked_dependency["name"]
    assert metadata["version"] == locked_dependency["version"]
    image_tags = {
        eso["image"]["tag"],
        eso["webhook"]["image"]["tag"],
        eso["certController"]["image"]["tag"],
    }
    assert {tag.partition("@")[0] for tag in image_tags} == {metadata["appVersion"]}
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == ledger_sha256


def test_umbrella_no_longer_owns_external_secrets() -> None:
    chart = _load(_CHART / "Chart.yaml")
    assert "external-secrets" not in {dep["name"] for dep in chart["dependencies"]}

    lock = _load(_CHART / "Chart.lock")
    assert "external-secrets" not in {dep["name"] for dep in lock["dependencies"]}

    values = _load(_CHART / "values.yaml")
    assert "external-secrets" not in values

    assert not list((_CHART / "charts").glob("external-secrets-*.tgz"))


def test_foundation_operator_workloads_are_exact_and_pinned(
    foundation_documents: tuple[dict[str, Any], ...],
) -> None:
    documents = foundation_documents
    workloads = {
        doc["metadata"]["name"]: doc
        for doc in documents
        if doc.get("kind") == "Deployment"
        and doc.get("metadata", {}).get("name", "").startswith("nohiki-foundation-external-secrets")
    }
    values = _load(_FOUNDATION / "values.yaml")["external-secrets"]
    expected_images = {
        "nohiki-foundation-external-secrets": f"{values['image']['repository']}:{values['image']['tag']}",
        "nohiki-foundation-external-secrets-webhook": (
            f"{values['webhook']['image']['repository']}:{values['webhook']['image']['tag']}"
        ),
        "nohiki-foundation-external-secrets-cert-controller": (
            f"{values['certController']['image']['repository']}:{values['certController']['image']['tag']}"
        ),
    }
    assert set(workloads) == expected_images.keys()
    assert all(_PINNED_IMAGE.fullmatch(image) for image in expected_images.values())
    for name, workload in workloads.items():
        containers = workload["spec"]["template"]["spec"]["containers"]
        assert len(containers) == 1
        assert containers[0]["image"] == expected_images[name]


def test_foundation_external_secrets_crds_are_stable_v1_only(
    foundation_documents: tuple[dict[str, Any], ...],
) -> None:
    crds = {
        doc["metadata"]["name"]: doc for doc in foundation_documents if doc.get("kind") == "CustomResourceDefinition"
    }
    required_crds = {
        "externalsecrets.external-secrets.io",
        "secretstores.external-secrets.io",
        "clustersecretstores.external-secrets.io",
    }
    assert required_crds <= set(crds)
    for name in required_crds:
        crd = crds[name]
        assert crd["spec"].get("conversion") is None
        versions = {version["name"]: version for version in crd["spec"]["versions"]}
        assert versions["v1"]["served"] is True
        assert versions["v1"]["storage"] is True
        assert versions["v1beta1"]["served"] is False
        assert versions["v1beta1"]["storage"] is False


@pytest.mark.parametrize(("environment", "namespace"), [("dev", "nohiki-dev"), ("staging", "nohiki-staging")])
def test_dev_staging_platform_emit_chart_managed_service_account_store_and_secrets(
    environment: str,
    namespace: str,
    platform_documents: dict[str, tuple[dict[str, Any], ...]],
) -> None:
    documents = platform_documents[environment]
    expected_model_secrets = _model_egress_external_secrets(f"values.{environment}.yaml")

    service_account = _named(documents, "ServiceAccount", _SA_NAME)
    assert service_account["metadata"]["namespace"] == namespace
    assert service_account["metadata"]["labels"]["azure.workload.identity/use"] == "true"
    annotations = service_account["metadata"]["annotations"]
    assert "azure.workload.identity/client-id" in annotations
    assert "azure.workload.identity/tenant-id" in annotations

    store = _named(documents, "ClusterSecretStore", _STORE_NAME)
    azurekv = store["spec"]["provider"]["azurekv"]
    assert azurekv["authType"] == "WorkloadIdentity"
    assert azurekv["serviceAccountRef"] == {"name": _SA_NAME, "namespace": namespace}

    external_secrets = {
        document["metadata"]["name"]: document for document in documents if document.get("kind") == "ExternalSecret"
    }
    assert set(external_secrets) >= _SHARED_SECRETS | expected_model_secrets
    assert "nohiki-llm-api-keys" not in external_secrets
    assert "observability-storage-credentials" not in external_secrets
    assert any(name.endswith("-db-credentials") for name in external_secrets)

    expected_ref = {"name": _STORE_NAME, "kind": "ClusterSecretStore"}
    for name, secret in external_secrets.items():
        assert secret["metadata"]["namespace"] == namespace
        assert secret["spec"]["target"]["creationPolicy"] == "Owner"
        if name in _model_egress_client_secrets():
            assert secret["spec"]["refreshPolicy"] == "CreatedOnce"
            assert "secretStoreRef" not in secret["spec"]
        else:
            assert secret["spec"]["secretStoreRef"] == expected_ref


@pytest.mark.parametrize("environment", ["dev", "staging"])
def test_dev_staging_disable_the_in_cluster_cnpg_cluster(environment: str) -> None:
    values = _load(_CHART / f"values.{environment}.yaml")
    assert "cnpgCluster" in values
    assert values["cnpgCluster"]["enabled"] is False


def test_local_platform_chart_emits_exact_split_external_secrets(
    platform_documents: dict[str, tuple[dict[str, Any], ...]],
) -> None:
    documents = platform_documents["local"]
    external = {
        document["metadata"]["name"]: document for document in documents if document.get("kind") == "ExternalSecret"
    }
    assert set(external) == _model_egress_external_secrets("values.local.yaml")
    assert not any(document.get("kind") == "ClusterSecretStore" for document in documents)
    assert not any(
        document.get("kind") == "ServiceAccount" and document.get("metadata", {}).get("name") == _SA_NAME
        for document in documents
    )

    for name, secret in external.items():
        assert secret["metadata"]["namespace"] == "nohiki"
        assert secret["spec"]["target"]["creationPolicy"] == "Owner"
        if name in _model_egress_client_secrets():
            assert secret["spec"]["refreshPolicy"] == "CreatedOnce"
            assert "secretStoreRef" not in secret["spec"]
        else:
            assert secret["spec"]["secretStoreRef"] == {
                "name": "nohiki-local-secret-store",
                "kind": "SecretStore",
            }


@pytest.mark.parametrize("overlay", ["dev", "staging", "prod"])
def test_shared_observability_overlays_reuse_platform_store_without_defining_one(
    overlay: str,
    observability_documents: dict[str, tuple[dict[str, Any], ...]],
) -> None:
    documents = observability_documents[overlay]
    assert not any(document.get("kind") == "ClusterSecretStore" for document in documents)

    external_secrets = [document for document in documents if document.get("kind") == "ExternalSecret"]
    assert external_secrets
    for secret in external_secrets:
        assert secret["spec"]["secretStoreRef"] == {
            "kind": "ClusterSecretStore",
            "name": _STORE_NAME,
        }


def test_shared_observability_base_does_not_ship_a_cluster_secret_store() -> None:
    base = _load(_OBSERVABILITY / "base" / "kustomization.yaml")
    assert not any("cluster-secret-store" in resource for resource in base["resources"])


def test_local_observability_overlay_defines_no_secret_delivery_fallback(
    observability_documents: dict[str, tuple[dict[str, Any], ...]],
) -> None:
    documents = observability_documents["local"]
    secret_resources = {
        (document["kind"], document["metadata"]["name"])
        for document in documents
        if document.get("kind") in {"Secret", "ExternalSecret", "SecretStore", "ClusterSecretStore"}
    }
    assert secret_resources == set()


def test_aks_external_secrets_identity_covers_every_environment_and_exact_namespaces() -> None:
    text = _AKS_TF.read_text(encoding="utf-8")

    # Subjects must be environment-parameterized, never pinned to the prod namespace.
    assert "nohiki-prod:external-secrets-sa" not in text
    assert "nohiki-prod:nohiki-storage" not in text
    assert f"system:serviceaccount:nohiki-${{var.app_environment}}:{_SA_NAME}" in text
    assert "system:serviceaccount:nohiki-${var.app_environment}:nohiki-storage" in text

    external_secrets_fic = _hcl_block(text, 'resource "azurerm_federated_identity_credential" "external_secrets"')
    assert 'var.deployment_type == "aks"' in external_secrets_fic
    assert 'var.app_environment == "prod"' not in external_secrets_fic

    storage_fic = _hcl_block(text, 'resource "azurerm_federated_identity_credential" "storage_workloads"')
    assert 'var.app_environment == "prod"' in storage_fic

    for output in (
        "external_secrets_workload_identity_client_id",
        "external_secrets_workload_identity_tenant_id",
        "external_secrets_key_vault_url",
    ):
        block = _hcl_block(text, f'output "{output}"')
        assert 'var.deployment_type == "aks"' in block
        assert 'var.app_environment == "prod"' not in block


def test_required_secret_names_are_documented() -> None:
    readme = (_CHART / "README.md").read_text(encoding="utf-8")
    for name in _SHARED_SECRETS:
        assert name in readme, name
    # Per-service database secrets follow the documented <service>-db-credentials shape.
    assert "-db-credentials" in readme
