"""Supply-chain and reconciliation contracts for the gateway foundation."""

from __future__ import annotations

import hashlib
import shlex
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[3]
_K8S = _ROOT / "infra" / "k8s"
_FOUNDATION_CHART = _K8S / "helm-foundation"
_PLATFORM_CHART = _K8S / "helm"
_GATEWAY_API_BUNDLE = _K8S / "gitops" / "gateway-api-crds" / "gateway-api-crds.yaml"
_WORKFLOW = _ROOT / ".github" / "workflows" / "cd_deploy-to-aks_nohiki.yml"
_IMMUTABLE_GATEWAY_INPUTS = {
    "infra/k8s/gitops/gateway-api-crds/kustomization.yaml",
    "infra/k8s/gitops/gateway-api-crds/gateway-api-crds.yaml",
    "infra/k8s/gitops/clusters/prod-aks/gateway-api-crds.yaml",
}
_VENDORED_MARKER = b"# ---8<--- BEGIN VENDORED CONTENT ---8<---\n"

_GATEWAY_API_VERSION = "v1.6.0"
_GATEWAY_API_BUNDLE_EXPECTED_HEX = "a557172e8348f758479e9ee4000bbbb4b4aa48302a6b73461823ea5349bad56d"
_GATEWAY_DEPENDENCIES = {
    "kgateway-crds": ("v2.3.6", "oci://cr.kgateway.dev/kgateway-dev/charts"),
    "kgateway": ("v2.3.6", "oci://cr.kgateway.dev/kgateway-dev/charts"),
    "agentgateway-crds": ("v1.3.1", "oci://cr.agentgateway.dev/charts"),
    "agentgateway": ("v1.3.1", "oci://cr.agentgateway.dev/charts"),
}
_FOUNDATION_DEPENDENCIES = _GATEWAY_DEPENDENCIES | {
    "keda": ("2.20.1", "https://kedacore.github.io/charts"),
}
_KEDA_ARCHIVE_SHA256 = "584c42b33427151abc03d4dd0c8c24be6c9aec96fc988dcf1559711c4dbd0d79"
_GATEWAY_ARCHIVE_SHA256 = {
    "kgateway-crds-v2.3.6.tgz": "d6b1d8bf0e2636bca6b8fb2b4a1525806fd1b4f9e84614c8a6a16eda585a119c",
    "kgateway-v2.3.6.tgz": "23ce30f3180dffad0d68f8aab03d5da422d2c983d513f8e86dd01012845b603a",
    "agentgateway-crds-v1.3.1.tgz": "4d66be934dac6d9ba1e7cf663fce33a0c8417fdc3613c145eb83b581a8fd1bf0",
    "agentgateway-v1.3.1.tgz": "4b27576722ed373c7d677f2252061a03fd2b550b761023d7642677f8bc2b65fc",
}
_STANDARD_CRDS = {
    "backendtlspolicies.gateway.networking.k8s.io",
    "gatewayclasses.gateway.networking.k8s.io",
    "gateways.gateway.networking.k8s.io",
    "grpcroutes.gateway.networking.k8s.io",
    "httproutes.gateway.networking.k8s.io",
    "listenersets.gateway.networking.k8s.io",
    "referencegrants.gateway.networking.k8s.io",
    "tcproutes.gateway.networking.k8s.io",
    "tlsroutes.gateway.networking.k8s.io",
    "udproutes.gateway.networking.k8s.io",
}


def _load(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict), path
    return value


def _coordinates(dependencies: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    return [(dependency["name"], dependency["version"], dependency["repository"]) for dependency in dependencies]


def _render_foundation() -> tuple[dict[str, Any], ...]:
    result = subprocess.run(
        [
            "helm",
            "template",
            "foundation",
            str(_FOUNDATION_CHART),
            "--namespace",
            "nohiki-foundation",
        ],
        cwd=_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return tuple(
        document for document in yaml.load_all(result.stdout, Loader=yaml.CSafeLoader) if isinstance(document, dict)
    )


@pytest.fixture(scope="module")
def foundation_documents() -> tuple[dict[str, Any], ...]:
    """Render the immutable foundation chart once for this module."""
    return _render_foundation()


def test_foundation_dependency_coordinates_lock_and_archives_are_exact() -> None:
    chart = _load(_FOUNDATION_CHART / "Chart.yaml")
    dependencies = {dependency["name"]: dependency for dependency in chart["dependencies"]}
    for name, (version, repository) in _FOUNDATION_DEPENDENCIES.items():
        assert (dependencies[name]["version"], dependencies[name]["repository"]) == (
            version,
            repository,
        )

    lock = _load(_FOUNDATION_CHART / "Chart.lock")
    assert _coordinates(lock["dependencies"]) == _coordinates(chart["dependencies"])

    chart_dir = _FOUNDATION_CHART / "charts"
    gateway_archives = {path.name for path in chart_dir.glob("*gateway*.tgz")}
    assert gateway_archives == set(_GATEWAY_ARCHIVE_SHA256)
    for archive_name, expected_sha256 in _GATEWAY_ARCHIVE_SHA256.items():
        assert hashlib.sha256((chart_dir / archive_name).read_bytes()).hexdigest() == expected_sha256
    assert hashlib.sha256((chart_dir / "keda-2.20.1.tgz").read_bytes()).hexdigest() == _KEDA_ARCHIVE_SHA256


def test_gateway_api_bundle_matches_upstream_standard_schema_and_digest() -> None:
    chart = _load(_FOUNDATION_CHART / "Chart.yaml")
    values = _load(_FOUNDATION_CHART / "values.yaml")
    assert chart["annotations"]["nohiki.io/gateway-api-version"] == _GATEWAY_API_VERSION
    assert chart["annotations"]["nohiki.io/gateway-bundle-integrity"] == _GATEWAY_API_BUNDLE_EXPECTED_HEX
    assert values["gatewayApi"] == {
        "version": _GATEWAY_API_VERSION,
        "sha256": _GATEWAY_API_BUNDLE_EXPECTED_HEX,
    }

    header, marker, content = _GATEWAY_API_BUNDLE.read_bytes().partition(_VENDORED_MARKER)
    assert marker, "vendored Gateway API boundary marker is missing"
    assert hashlib.sha256(content).hexdigest() == _GATEWAY_API_BUNDLE_EXPECTED_HEX
    assert _GATEWAY_API_VERSION.encode() in header

    documents = tuple(
        document for document in yaml.load_all(content, Loader=yaml.CSafeLoader) if isinstance(document, dict)
    )
    assert {document.get("kind") for document in documents} == {
        "CustomResourceDefinition",
        "ValidatingAdmissionPolicy",
        "ValidatingAdmissionPolicyBinding",
    }
    crds = [document for document in documents if document["kind"] == "CustomResourceDefinition"]
    assert {document["metadata"]["name"] for document in crds} == _STANDARD_CRDS
    for document in crds:
        annotations = document["metadata"]["annotations"]
        assert annotations["gateway.networking.k8s.io/bundle-version"] == _GATEWAY_API_VERSION
        assert annotations["gateway.networking.k8s.io/channel"] == "standard"


def test_foundation_is_the_only_gateway_controller_and_crd_owner(
    foundation_documents: tuple[dict[str, Any], ...],
) -> None:
    owners: dict[Path, set[str]] = {}
    for chart_path in _K8S.rglob("Chart.yaml"):
        gateway_dependencies = {
            dependency["name"]
            for dependency in _load(chart_path).get("dependencies", [])
            if dependency["name"] in _GATEWAY_DEPENDENCIES
        }
        if gateway_dependencies:
            owners[chart_path.relative_to(_ROOT)] = gateway_dependencies
    assert owners == {Path("infra/k8s/helm-foundation/Chart.yaml"): set(_GATEWAY_DEPENDENCIES)}

    documents = foundation_documents
    controller_counts = Counter(
        document.get("metadata", {}).get("labels", {}).get("app.kubernetes.io/name")
        for document in documents
        if document.get("kind") == "Deployment"
        and document.get("metadata", {}).get("labels", {}).get("app.kubernetes.io/name") in {"kgateway", "agentgateway"}
    )
    assert controller_counts == {"kgateway": 1, "agentgateway": 1}
    images = {
        document["metadata"]["labels"]["app.kubernetes.io/name"]: document["spec"]["template"]["spec"]["containers"][0][
            "image"
        ]
        for document in documents
        if document.get("kind") == "Deployment"
        and document.get("metadata", {}).get("labels", {}).get("app.kubernetes.io/name") in controller_counts
    }
    assert images == {
        "kgateway": "cr.kgateway.dev/kgateway-dev/kgateway:v2.3.6",
        "agentgateway": "cr.agentgateway.dev/controller:v1.3.1",
    }

    rendered_crd_names = [
        document["metadata"]["name"] for document in documents if document.get("kind") == "CustomResourceDefinition"
    ]
    assert rendered_crd_names
    assert len(rendered_crd_names) == len(set(rendered_crd_names))
    assert _STANDARD_CRDS.isdisjoint(rendered_crd_names)
    assert not (_FOUNDATION_CHART / "templates" / "gateway-api-crds.yaml").exists()

    imperative_gateway_scripts = [
        path.relative_to(_ROOT)
        for path in _K8S.rglob("*.sh")
        if any("gateway" in part.lower() for part in path.relative_to(_K8S).parts)
    ]
    assert not imperative_gateway_scripts


def test_foundation_is_the_single_cert_manager_chart_owner() -> None:
    owners: dict[Path, int] = {}
    for chart_path in _K8S.rglob("Chart.yaml"):
        count = sum(dependency["name"] == "cert-manager" for dependency in _load(chart_path).get("dependencies", []))
        if count:
            owners[chart_path.relative_to(_ROOT)] = count

    assert owners == {Path("infra/k8s/helm-foundation/Chart.yaml"): 1}
    lock = _load(_FOUNDATION_CHART / "Chart.lock")
    assert sum(dependency["name"] == "cert-manager" for dependency in lock["dependencies"]) == 1
    values = _load(_FOUNDATION_CHART / "values.yaml")
    assert values["cert-manager"]["enabled"] is True
    assert values["cert-manager"]["crds"]["enabled"] is True


def test_flux_orders_crds_foundation_and_platform_with_health_gates() -> None:
    environment_namespaces = {
        "local": "nohiki",
        "dev-aks": "nohiki-dev",
        "staging-aks": "nohiki-staging",
        "prod-aks": "nohiki-prod",
    }
    local_external_secret_names = (
        "nohiki-model-egress-openai",
        "nohiki-model-egress-openrouter",
        "nohiki-model-egress-tls",
        "nohiki-model-egress-ca",
        "nohiki-model-egress-client-doc-content",
        "nohiki-model-egress-client-job-ingest-enrichment",
    )
    managed_external_secret_names = (
        "nohiki-model-egress-anthropic",
        "nohiki-model-egress-ca",
        "nohiki-model-egress-openai",
        "nohiki-model-egress-openrouter",
        "nohiki-model-egress-tls",
        "auth-listings-secret",
        "kafka-sasl-credentials",
        "nohiki-email-api-keys",
        "nohiki-jsearch-api-keys",
        "nohiki-jwt-keys",
        "nohiki-oauth-credentials",
        "nohiki-redis-credentials",
        "nohiki-s3-credentials",
        "qdrant-api-key",
        "bff-service-db-credentials",
        "doc-template-service-db-credentials",
        "job-correlation-evaluation-service-db-credentials",
        "job-ingest-discovery-service-db-credentials",
        "job-ingest-enrichment-service-db-credentials",
        "job-ingest-schedule-service-db-credentials",
        "job-query-composition-service-db-credentials",
        "job-storage-service-db-credentials",
        "notification-service-db-credentials",
        "skill-graph-service-db-credentials",
        "user-auth-service-db-credentials",
        "user-entitlement-service-db-credentials",
        "user-pref-service-db-credentials",
        "user-upload-service-db-credentials",
        "nohiki-model-egress-client-doc-content",
        "nohiki-model-egress-client-job-ingest-enrichment",
    )
    gateway_names = ("nohiki-gateway", "nohiki-model-egress")
    local_http_route_names = (
        "nohiki-jwks-route",
        "nohiki-auth-route",
        "nohiki-account-route",
        "nohiki-ping-route",
        "nohiki-sse-route",
        "nohiki-api-route",
        "nohiki-s3-route",
        "nohiki-otel-traces-route",
        "nohiki-frontend-route",
        "nohiki-model-egress-healthz",
        "nohiki-model-egress-responses",
        "nohiki-model-egress-completions",
    )
    cloud_http_route_names = (
        *(name for name in local_http_route_names if name not in {"nohiki-s3-route", "nohiki-otel-traces-route"}),
        "nohiki-model-egress-messages",
    )
    gateway_health_check_expressions = [
        {
            "apiVersion": "gateway.networking.k8s.io/v1",
            "kind": "Gateway",
            "failed": (
                "status.conditions.exists(c, "
                "(c.type == 'Accepted' || c.type == 'Programmed')"
                " && c.status == 'False'"
                " && c.observedGeneration == metadata.generation)"
            ),
            "current": (
                "status.conditions.exists(c, c.type == 'Accepted'"
                " && c.status == 'True'"
                " && c.observedGeneration == metadata.generation)"
                " && status.conditions.exists(c, c.type == 'Programmed'"
                " && c.status == 'True'"
                " && c.observedGeneration == metadata.generation)"
            ),
        },
        {
            "apiVersion": "gateway.networking.k8s.io/v1",
            "kind": "HTTPRoute",
            "failed": (
                "status.parents.exists(p, p.conditions.exists(c, "
                "(c.type == 'Accepted' || c.type == 'ResolvedRefs')"
                " && c.status == 'False'"
                " && c.observedGeneration == metadata.generation))"
            ),
            "current": (
                "status.parents.size() > 0"
                " && status.parents.all(p, p.conditions.exists(c, c.type == 'Accepted'"
                " && c.status == 'True'"
                " && c.observedGeneration == metadata.generation)"
                " && p.conditions.exists(c, c.type == 'ResolvedRefs'"
                " && c.status == 'True'"
                " && c.observedGeneration == metadata.generation))"
            ),
        },
    ]
    cluster_root = _K8S / "gitops" / "clusters"
    environments = {path.name for path in cluster_root.iterdir() if path.is_dir()}
    assert environments == environment_namespaces.keys()

    for environment, namespace in environment_namespaces.items():
        cluster = cluster_root / environment
        resources = _load(cluster / "kustomization.yaml")["resources"]
        if environment == "local":
            assert resources.count("bootstrap/") == 1
            bootstrap_resources = _load(cluster / "bootstrap/kustomization.yaml")["resources"]
            assert bootstrap_resources.count("gateway-api-crds.yaml") == 1
            crds_path = cluster / "bootstrap/gateway-api-crds.yaml"
        else:
            assert resources.count("gateway-api-crds.yaml") == 1
            crds_path = cluster / "gateway-api-crds.yaml"
        assert resources.count("infrastructure.yaml") == 1
        assert resources.count("platform.yaml") == 1
        assert resources.count("runtime-secrets.yaml") == (1 if environment == "local" else 0)

        crds = _load(crds_path)
        assert crds["metadata"]["name"] == "gateway-api-crds"
        assert crds["spec"]["path"] == "./infra/k8s/gitops/gateway-api-crds"
        assert crds["spec"]["wait"] is True
        assert crds["spec"]["timeout"] == "5m"

        infrastructure = _load(cluster / "infrastructure.yaml")
        assert infrastructure["spec"]["dependsOn"] == [{"name": "gateway-api-crds"}]
        assert infrastructure["spec"]["retryInterval"] == "2m"
        assert infrastructure["spec"]["timeout"] == "10m"
        assert infrastructure["spec"]["wait"] is False
        assert infrastructure["spec"]["healthChecks"] == [
            {
                "apiVersion": "helm.toolkit.fluxcd.io/v2",
                "kind": "HelmRelease",
                "name": "nohiki-foundation",
                "namespace": "flux-system",
            }
        ]

        expected_platform_dependencies = [{"name": "infrastructure"}]
        if environment == "local":
            runtime_secrets = _load(cluster / "runtime-secrets.yaml")
            assert runtime_secrets["spec"]["dependsOn"] == [{"name": "infrastructure"}]
            assert runtime_secrets["spec"]["healthChecks"] == [
                {
                    "apiVersion": "v1",
                    "kind": "Secret",
                    "name": "nohiki-llm-runtime",
                    "namespace": "nohiki",
                },
                {
                    "apiVersion": "v1",
                    "kind": "Secret",
                    "name": "nohiki-model-egress-tls-source",
                    "namespace": "nohiki",
                },
                {
                    "apiVersion": "external-secrets.io/v1",
                    "kind": "SecretStore",
                    "name": "nohiki-local-secret-store",
                    "namespace": "nohiki",
                },
            ]
            expected_platform_dependencies = [
                {"name": "infrastructure"},
                {"name": "runtime-secrets"},
                {"name": "registry"},
            ]

        platform = _load(cluster / "platform.yaml")
        assert platform["spec"]["dependsOn"] == expected_platform_dependencies
        assert platform["spec"]["wait"] is False
        external_secret_names = local_external_secret_names if environment == "local" else managed_external_secret_names
        http_route_names = local_http_route_names if environment == "local" else cloud_http_route_names
        assert platform["spec"]["healthChecks"] == [
            {
                "apiVersion": "helm.toolkit.fluxcd.io/v2",
                "kind": "HelmRelease",
                "name": "nohiki",
                "namespace": "flux-system",
            },
            *[
                {
                    "apiVersion": "external-secrets.io/v1",
                    "kind": "ExternalSecret",
                    "name": name,
                    "namespace": namespace,
                }
                for name in external_secret_names
            ],
            *[
                {
                    "apiVersion": "gateway.networking.k8s.io/v1",
                    "kind": "Gateway",
                    "name": name,
                    "namespace": namespace,
                }
                for name in gateway_names
            ],
            *[
                {
                    "apiVersion": "gateway.networking.k8s.io/v1",
                    "kind": "HTTPRoute",
                    "name": name,
                    "namespace": namespace,
                }
                for name in http_route_names
            ],
        ]
        assert platform["spec"]["healthCheckExprs"] == (gateway_health_check_expressions)


def test_production_workflow_guards_each_declarative_gateway_crd_input_once() -> None:
    workflow = _load(_WORKFLOW)
    activation = workflow["jobs"]["activate-production-runtime"]
    verify_step = next(step for step in activation["steps"] if step.get("name") == "Verify immutable release inputs")
    run = verify_step["run"]

    _before, loop_start, remainder = run.partition("for path in")
    allowlist, loop_end, _after = remainder.partition("; do")
    assert loop_start, "immutable-input loop could not be parsed"
    assert loop_end, "immutable-input loop could not be parsed"
    paths = [token for token in shlex.split(allowlist) if token.strip()]

    assert len(paths) == len(set(paths)), "immutable-input allowlist contains duplicate ownership paths"
    gateway_paths = {path for path in paths if "gateway-api-crds" in path}
    assert gateway_paths == _IMMUTABLE_GATEWAY_INPUTS
    assert all((_ROOT / path).is_file() for path in _IMMUTABLE_GATEWAY_INPUTS)
    assert "infra/k8s/helm-foundation/templates/gateway-api-crds.yaml" not in paths


def test_platform_chart_no_longer_owns_cnpg_operator() -> None:
    chart = _load(_PLATFORM_CHART / "Chart.yaml")
    assert "cloudnative-pg" not in {dependency["name"] for dependency in chart["dependencies"]}

    lock_path = _PLATFORM_CHART / "Chart.lock"
    if lock_path.exists():
        lock = _load(lock_path)
        assert "cloudnative-pg" not in {dependency["name"] for dependency in lock["dependencies"]}

    for name in (
        "values.yaml",
        "values.local.yaml",
        "values.dev.yaml",
        "values.staging.yaml",
    ):
        values = _load(_PLATFORM_CHART / name)
        assert "cloudnativepg" not in values, f"{name} still toggles the CNPG operator"
        assert "cnpgCluster" in values, f"{name} dropped the Postgres cluster it must keep"
