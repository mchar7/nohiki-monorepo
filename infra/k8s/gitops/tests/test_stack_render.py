"""Render contract tests for the per-cluster GitOps stacks.

Each cluster directory renders the Gateway API CRD, infrastructure, platform,
and observability Kustomizations; local additionally renders runtime secrets.
The engine itself is bootstrapped natively by
``flux bootstrap github``, which generates and self-manages the ``flux-system``
GitRepository and Kustomization; those are not committed and never appear in the
standalone stack render. These tests build the rendered stream with
``kubectl kustomize`` and lock the reconcile contract that a fork can render and
reason about without a live cluster:

  * composition: every cluster renders its exact environment stack set, no
    hand-written control/root Kustomization, and only prod commits a source;
  * source policy: branch clusters point their stacks at the bootstrap-generated
    ``flux-system`` source; prod commits an immutable, commit-pinned
    ``gitops-release`` source and every prod stack is suspended until activation;
  * the dependency DAG begins at Gateway API CRDs, then infrastructure, platform,
    and observability; local runtime secrets sit between infrastructure and platform;
  * HelmRelease target namespaces and repo-root-relative ordered valuesFiles,
    because a GitRepository HelmChart resolves valuesFiles against the source
    root, not the chart path;
  * dev/staging inject runtime image and ESO coordinates through the platform
    Kustomization's postBuild substitution from the gitops-runtime ConfigMap;
    local and prod carry no runtime placeholders;
  * the Git chart source uses the ``Revision`` reconcile strategy (no OCI chart);
  * environment isolation: a cluster references only its own environment;
  * GA controller API versions throughout.

Run only these:
    uv run pytest infra/k8s/gitops/tests/test_stack_render.py -v
"""

from __future__ import annotations

import functools
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]

PROD_COMMIT_PLACEHOLDER = "PROMOTION_REQUIRED"
# The bootstrap-generated source every branch cluster's stacks reference; prod
# instead commits its own immutable release source.
FLUX_SOURCE = "flux-system"
RELEASE_SOURCE = "gitops-release"
RUNTIME_CONFIGMAP = "gitops-runtime"

BASE_STACKS = ("gateway-api-crds", "infrastructure", "platform", "observability")

# cluster directory -> environment token used across its paths, namespaces, and overlays.
CLUSTER_ENV = {
    "local": "local",
    "dev-aks": "dev",
    "staging-aks": "staging",
    "prod-aks": "prod",
}
BRANCH_CLUSTERS = ("local", "dev-aks", "staging-aks")
# Only dev/staging pull non-secret cloud coordinates in at runtime; local uses chart
# defaults and prod uses committed overlays.
RUNTIME_CLUSTERS = ("dev-aks", "staging-aks")

CLUSTER_STACKS = {
    "local": (
        *BASE_STACKS,
        "registry",
        "runtime-secrets",
        "health-verification",
        "api-verification",
        "playwright-verification",
    ),
    "dev-aks": BASE_STACKS,
    "staging-aks": BASE_STACKS,
    "prod-aks": BASE_STACKS,
}

PLATFORM_NAMESPACE = {
    "local": "nohiki",
    "dev": "nohiki-dev",
    "staging": "nohiki-staging",
    "prod": "nohiki-prod",
}

HELM = "infra/k8s/helm/"
PLATFORM_VALUES = {
    "local": [HELM + "values.yaml", HELM + "values.local.yaml"],
    "dev": [HELM + "values.yaml", HELM + "values.dev.yaml"],
    "staging": [HELM + "values.yaml", HELM + "values.staging.yaml"],
    "prod": [
        HELM + "values.yaml",
        HELM + "values.prod.yaml",
        HELM + "values.prod.identity.yaml",
        HELM + "values.prod.network.yaml",
        HELM + "values.prod.digests.yaml",
    ],
}

# The runtime image and ESO coordinates dev/staging inject into the platform
# HelmRelease values through Kustomization postBuild substitution.
RUNTIME_VALUE_PLACEHOLDERS = {
    ("global", "nohikiImage", "registry"): "${image_registry}",
    ("global", "nohikiImage", "owner"): "${image_owner}",
    ("global", "nohikiImage", "repositoryName"): "${image_repository}",
    ("global", "imageTag"): "${image_tag}",
    ("global", "eso", "azure", "keyVaultUrl"): "${eso_vault_url}",
    ("global", "eso", "azure", "clientId"): "${eso_client_id}",
    ("global", "eso", "azure", "tenantId"): "${eso_tenant_id}",
}

RUNTIME_SUBSTITUTE_FROM = [{"kind": "ConfigMap", "name": RUNTIME_CONFIGMAP}]


@functools.cache
def _render(relative: str) -> str:
    result = subprocess.run(
        ["kubectl", "kustomize", str(REPO_ROOT / relative)],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def documents(relative: str) -> list[dict]:
    return [doc for doc in yaml.safe_load_all(_render(relative)) if isinstance(doc, dict)]


def cluster_docs(cluster: str) -> list[dict]:
    return documents(f"infra/k8s/gitops/clusters/{cluster}")


def stack(cluster: str, name: str) -> dict:
    for doc in cluster_docs(cluster):
        if doc.get("kind") == "Kustomization" and doc["metadata"]["name"] == name:
            return doc
    pytest.fail(f"cluster {cluster!r} rendered no {name!r} Kustomization")


def gitrepositories(cluster: str) -> dict[str, dict]:
    return {doc["metadata"]["name"]: doc for doc in cluster_docs(cluster) if doc.get("kind") == "GitRepository"}


def source(cluster: str, name: str) -> dict:
    repos = gitrepositories(cluster)
    assert name in repos, f"cluster {cluster!r} rendered no GitRepository {name!r}; got {sorted(repos)}"
    return repos[name]


def helmrelease(relative: str, name: str) -> dict:
    for doc in documents(relative):
        if doc.get("kind") == "HelmRelease" and doc["metadata"]["name"] == name:
            return doc
    pytest.fail(f"{relative} rendered no HelmRelease {name!r}")


def _dig(value: object, path: tuple[str, ...]) -> object:
    for key in path:
        assert isinstance(value, dict), f"expected a mapping at {key!r}, got {type(value).__name__}"
        assert key in value, f"missing key {key!r}; have {sorted(value)}"
        value = value[key]
    return value


# ------------------------------------------------------------------ composition


@pytest.mark.parametrize("cluster", CLUSTER_ENV)
def test_cluster_renders_exact_environment_stacks(cluster: str) -> None:
    kustomizations = sorted(d["metadata"]["name"] for d in cluster_docs(cluster) if d.get("kind") == "Kustomization")
    assert kustomizations == sorted(CLUSTER_STACKS[cluster]), f"{cluster}: kustomizations were {kustomizations}"


def test_only_prod_commits_a_source() -> None:
    # Branch clusters reference the bootstrap-generated flux-system source, which is
    # uncommitted and never in the render. Only prod commits its release source.
    for cluster in BRANCH_CLUSTERS:
        assert gitrepositories(cluster) == {}, f"{cluster} must not commit a GitRepository"
    assert set(gitrepositories("prod-aks")) == {RELEASE_SOURCE}, sorted(gitrepositories("prod-aks"))


@pytest.mark.parametrize("cluster", CLUSTER_ENV)
def test_stacks_use_ga_apiversions(cluster: str) -> None:
    for name in CLUSTER_STACKS[cluster]:
        assert stack(cluster, name)["apiVersion"] == "kustomize.toolkit.fluxcd.io/v1", name
    for repo in gitrepositories(cluster).values():
        assert repo["apiVersion"] == "source.toolkit.fluxcd.io/v1", repo["metadata"]["name"]


# ------------------------------------------------------------------ dependency DAG


@pytest.mark.parametrize("cluster", CLUSTER_ENV)
def test_stack_dependency_dag(cluster: str) -> None:
    expected = {
        "gateway-api-crds": [],
        "infrastructure": ["gateway-api-crds"],
        "platform": ["runtime-secrets", "registry"] if cluster == "local" else ["infrastructure"],
        "observability": ["platform"],
    }
    if cluster == "local":
        expected |= {
            "registry": [],
            "runtime-secrets": ["infrastructure"],
            "health-verification": ["observability"],
            "api-verification": ["health-verification"],
            "playwright-verification": ["api-verification"],
        }
    actual = {
        name: [dependency["name"] for dependency in stack(cluster, name)["spec"].get("dependsOn", [])]
        for name in CLUSTER_STACKS[cluster]
    }
    assert actual == expected


@pytest.mark.parametrize("cluster", CLUSTER_ENV)
def test_stack_paths_target_exact_environment_manifests(cluster: str) -> None:
    env = CLUSTER_ENV[cluster]
    expected = {
        "gateway-api-crds": "./infra/k8s/gitops/gateway-api-crds",
        "infrastructure": f"./infra/k8s/gitops/infrastructure/{env}",
        "platform": f"./infra/k8s/gitops/platform/{env}",
        "observability": f"./infra/k8s/observability/overlays/{env}",
    }
    if cluster == "local":
        expected |= {
            "registry": "./infra/k8s/gitops/registry",
            "runtime-secrets": "./infra/k8s/gitops/secrets/local",
            "health-verification": "./infra/k8s/gitops/verification",
            "api-verification": "./infra/k8s/gitops/verification/api",
            "playwright-verification": "./infra/k8s/gitops/verification/playwright",
        }
    actual = {name: stack(cluster, name)["spec"]["path"] for name in CLUSTER_STACKS[cluster]}
    assert actual == expected


def _object_identity(document: dict) -> tuple[str, str, str, str]:
    metadata = document["metadata"]
    return (
        document["apiVersion"],
        document["kind"],
        metadata.get("namespace", ""),
        metadata["name"],
    )


@pytest.mark.parametrize("cluster", CLUSTER_ENV)
def test_every_rendered_source_object_has_one_flux_owner(cluster: str) -> None:
    owners: dict[tuple[str, str, str, str], list[str]] = {}
    for name in CLUSTER_STACKS[cluster]:
        relative = stack(cluster, name)["spec"]["path"].removeprefix("./")
        rendered = documents(relative)
        assert rendered, f"{cluster}/{name} source path rendered no objects"
        for document in rendered:
            owners.setdefault(_object_identity(document), []).append(name)

    duplicates = {identity: names for identity, names in owners.items() if len(names) != 1}
    assert duplicates == {}, f"{cluster} has duplicate Flux ownership: {duplicates}"


@pytest.mark.parametrize("cluster", CLUSTER_ENV)
def test_rendered_sources_have_no_argo_ownership(cluster: str) -> None:
    rendered = [*cluster_docs(cluster)]
    for name in CLUSTER_STACKS[cluster]:
        relative = stack(cluster, name)["spec"]["path"].removeprefix("./")
        rendered.extend(documents(relative))

    for document in rendered:
        assert not document["apiVersion"].startswith("argoproj.io/")
        metadata = document.get("metadata", {})
        ownership_keys = {
            key
            for field in ("annotations", "labels")
            for key in metadata.get(field, {})
            if key.startswith("argocd.argoproj.io/")
        }
        assert ownership_keys == set(), _object_identity(document)


@pytest.mark.parametrize("cluster", CLUSTER_ENV)
def test_foundation_stack_waits_on_its_release_before_platform(cluster: str) -> None:
    infrastructure = stack(cluster, "infrastructure")["spec"]
    assert infrastructure["dependsOn"] == [{"name": "gateway-api-crds"}]
    assert infrastructure["retryInterval"] == "2m"
    assert infrastructure["timeout"] == "10m"
    assert infrastructure["prune"] is True
    assert infrastructure["wait"] is False
    assert infrastructure["healthChecks"] == [
        {
            "apiVersion": "helm.toolkit.fluxcd.io/v2",
            "kind": "HelmRelease",
            "name": "nohiki-foundation",
            "namespace": "flux-system",
        }
    ]

    gateway = stack(cluster, "gateway-api-crds")["spec"]
    assert gateway.get("dependsOn", []) == []
    assert gateway["timeout"] == "5m"
    assert gateway["prune"] is True
    assert gateway["wait"] is True

    platform_dependencies = (
        [{"name": "runtime-secrets"}, {"name": "registry"}] if cluster == "local" else [{"name": "infrastructure"}]
    )
    assert stack(cluster, "platform")["spec"]["dependsOn"] == platform_dependencies
    assert stack(cluster, "observability")["spec"]["dependsOn"] == [{"name": "platform"}]


# --------------------------------------------------------- source revision policy


@pytest.mark.parametrize("cluster", BRANCH_CLUSTERS)
def test_branch_cluster_stacks_track_the_bootstrap_source_and_reconcile(
    cluster: str,
) -> None:
    for name in CLUSTER_STACKS[cluster]:
        spec = stack(cluster, name)["spec"]
        assert spec["sourceRef"] == {"kind": "GitRepository", "name": FLUX_SOURCE}, f"{cluster}/{name} sourceRef"
        assert spec.get("suspend") is not True, f"{cluster}/{name} must reconcile actively"


def test_prod_release_source_is_commit_pinned_to_placeholder() -> None:
    ref = source("prod-aks", RELEASE_SOURCE)["spec"]["ref"]
    assert ref["commit"] == PROD_COMMIT_PLACEHOLDER, "prod must stay on the placeholder until the activation PR"
    assert "branch" not in ref, "the prod release source is commit-pinned, never branch-tracking"


def test_prod_stacks_use_the_release_source_and_stay_suspended() -> None:
    # The prod control (native flux-system, branch-tracking) reconciles this directory,
    # so a merged activation PR that stamps the release commit and flips suspend reaches
    # the cluster. Until then every prod stack stays suspended on the release source.
    for name in CLUSTER_STACKS["prod-aks"]:
        spec = stack("prod-aks", name)["spec"]
        assert spec["sourceRef"] == {"kind": "GitRepository", "name": RELEASE_SOURCE}, name
        assert spec.get("suspend") is True, f"prod {name} must stay suspended until activation"


# ------------------------------------------------------------------- HelmReleases


@pytest.mark.parametrize("cluster", CLUSTER_ENV)
def test_platform_helmrelease_namespaces_and_repo_root_valuefiles(cluster: str) -> None:
    env = CLUSTER_ENV[cluster]
    release = helmrelease(f"infra/k8s/gitops/platform/{env}", "nohiki")
    assert release["apiVersion"] == "helm.toolkit.fluxcd.io/v2"
    assert release["spec"]["targetNamespace"] == PLATFORM_NAMESPACE[env]
    assert release["spec"]["storageNamespace"] == PLATFORM_NAMESPACE[env]
    values_files = release["spec"]["chart"]["spec"]["valuesFiles"]
    assert values_files == PLATFORM_VALUES[env], f"{cluster} valuesFiles order"
    # A GitRepository HelmChart resolves valuesFiles against the source root, so every
    # entry must be repo-root-relative, never chart-relative (bare values.yaml).
    for entry in values_files:
        assert entry.startswith("infra/k8s/helm/"), f"{cluster}: chart-relative valuesFiles entry {entry!r}"


def test_foundation_helmrelease_targets_the_foundation_namespace() -> None:
    for env in CLUSTER_ENV.values():
        release = helmrelease(f"infra/k8s/gitops/infrastructure/{env}", "nohiki-foundation")
        assert release["spec"]["targetNamespace"] == "nohiki-foundation", env
        assert release["spec"]["chart"]["spec"]["chart"] == "./infra/k8s/helm-foundation", env
        values_files = release["spec"]["chart"]["spec"].get("valuesFiles", [])
        assert values_files == (["infra/k8s/helm/values.prod.identity.yaml"] if env == "prod" else [])


@pytest.mark.parametrize("cluster", CLUSTER_ENV)
def test_foundation_owns_environment_cert_manager_configuration(cluster: str) -> None:
    env = CLUSTER_ENV[cluster]
    spec = helmrelease(f"infra/k8s/gitops/infrastructure/{env}", "nohiki-foundation")["spec"]
    if env == "local":
        assert "values" not in spec
        return

    if env == "prod":
        identity_path = REPO_ROOT / "infra/k8s/helm/values.prod.identity.yaml"
        values = yaml.safe_load(identity_path.read_text(encoding="utf-8"))
        assert isinstance(values, dict)
    else:
        values = spec["values"]
    assert values["managedClusterIssuer"]["enabled"] is True
    assert values["managedClusterIssuer"]["name"] == f"letsencrypt-{env}"
    assert values["cert-manager"]["serviceAccount"]["annotations"]


@pytest.mark.parametrize("cluster", CLUSTER_ENV)
def test_foundation_helmrelease_has_exact_readiness_and_remediation(
    cluster: str,
) -> None:
    env = CLUSTER_ENV[cluster]
    spec = helmrelease(f"infra/k8s/gitops/infrastructure/{env}", "nohiki-foundation")["spec"]
    assert spec["timeout"] == "10m"
    assert spec["install"] == {
        "createNamespace": True,
        "crds": "Create",
        "remediation": {"retries": 3, "remediateLastFailure": True},
    }
    assert spec["upgrade"] == {
        "crds": "CreateReplace",
        "cleanupOnFail": True,
        "remediation": {"retries": 3, "remediateLastFailure": True},
    }
    assert spec["driftDetection"] == {"mode": "enabled"}


@pytest.mark.parametrize("cluster", CLUSTER_ENV)
def test_platform_helmrelease_has_explicit_readiness_and_remediation(
    cluster: str,
) -> None:
    env = CLUSTER_ENV[cluster]
    spec = helmrelease(f"infra/k8s/gitops/platform/{env}", "nohiki")["spec"]
    assert spec["timeout"] == "20m"
    assert spec["install"] == {
        "createNamespace": True,
        "crds": "Create",
        "remediation": {"retries": 3, "remediateLastFailure": True},
    }
    assert spec["upgrade"] == {
        "crds": "CreateReplace",
        "cleanupOnFail": True,
        "remediation": {"retries": 3, "remediateLastFailure": True},
    }
    assert spec["driftDetection"] == {"mode": "enabled"}


@pytest.mark.parametrize("cluster", CLUSTER_ENV)
def test_platform_gate_requires_public_and_model_gateway_readiness(
    cluster: str,
) -> None:
    env = CLUSTER_ENV[cluster]
    spec = stack(cluster, "platform")["spec"]
    assert spec["wait"] is False
    namespace = PLATFORM_NAMESPACE[env]
    route_names = {
        "nohiki-jwks-route",
        "nohiki-auth-route",
        "nohiki-account-route",
        "nohiki-ping-route",
        "nohiki-sse-route",
        "nohiki-api-route",
        "nohiki-frontend-route",
        "nohiki-model-egress-healthz",
        "nohiki-model-egress-responses",
        "nohiki-model-egress-completions",
    }
    if env == "local":
        route_names |= {"nohiki-s3-route", "nohiki-otel-traces-route"}
    else:
        route_names.add("nohiki-model-egress-messages")

    expected = {
        ("gateway.networking.k8s.io/v1", "Gateway", "nohiki-gateway", namespace),
        (
            "gateway.networking.k8s.io/v1",
            "Gateway",
            "nohiki-model-egress",
            namespace,
        ),
        *{("gateway.networking.k8s.io/v1", "HTTPRoute", name, namespace) for name in route_names},
    }
    actual = {
        (check["apiVersion"], check["kind"], check["name"], check["namespace"])
        for check in spec["healthChecks"]
        if check["kind"] in {"Gateway", "HTTPRoute"}
    }
    assert actual == expected, (
        f"{cluster} readiness mismatch: missing={expected - actual}, not rendered={actual - expected}"
    )
    expressions = {expression["kind"]: expression for expression in spec["healthCheckExprs"]}
    assert expressions.keys() == {"Gateway", "HTTPRoute"}
    for field in ("current", "failed"):
        assert "observedGeneration == metadata.generation" in expressions["Gateway"][field]
        assert "Accepted" in expressions["Gateway"][field]
        assert "Programmed" in expressions["Gateway"][field]
        assert "observedGeneration == metadata.generation" in expressions["HTTPRoute"][field]
        assert "Accepted" in expressions["HTTPRoute"][field]
        assert "ResolvedRefs" in expressions["HTTPRoute"][field]


@pytest.mark.parametrize("cluster", CLUSTER_ENV)
def test_git_chart_uses_revision_reconcile_strategy(cluster: str) -> None:
    env = CLUSTER_ENV[cluster]
    expected_source = RELEASE_SOURCE if cluster == "prod-aks" else FLUX_SOURCE
    for relative, name, chart in (
        (f"infra/k8s/gitops/platform/{env}", "nohiki", "./infra/k8s/helm"),
        (
            f"infra/k8s/gitops/infrastructure/{env}",
            "nohiki-foundation",
            "./infra/k8s/helm-foundation",
        ),
    ):
        chart_spec = helmrelease(relative, name)["spec"]["chart"]["spec"]
        # A Git chart path with the Revision strategy, since there is no OCI chart pipeline.
        assert chart_spec["chart"] == chart, f"{cluster}/{name} chart path"
        assert chart_spec["sourceRef"]["kind"] == "GitRepository", f"{cluster}/{name} chart source kind"
        assert chart_spec["sourceRef"]["name"] == expected_source, f"{cluster}/{name} chart source name"
        assert chart_spec["reconcileStrategy"] == "Revision", f"{cluster}/{name} reconcile strategy"


# ------------------------------------------------------ runtime substitution wiring


@pytest.mark.parametrize("cluster", RUNTIME_CLUSTERS)
def test_dev_staging_platform_substitutes_the_runtime_configmap(cluster: str) -> None:
    spec = stack(cluster, "platform")["spec"]
    assert spec.get("postBuild", {}).get("substituteFrom") == RUNTIME_SUBSTITUTE_FROM, spec.get("postBuild")


@pytest.mark.parametrize("cluster", ["local", "prod-aks"])
def test_local_prod_platform_has_no_runtime_substitution(cluster: str) -> None:
    # local uses chart defaults + values.local; prod uses committed overlays. Neither
    # injects runtime coordinates, so the platform stack carries no postBuild block.
    assert "postBuild" not in stack(cluster, "platform")["spec"]


@pytest.mark.parametrize("cluster", RUNTIME_CLUSTERS)
def test_dev_staging_platform_values_carry_runtime_placeholders(cluster: str) -> None:
    env = CLUSTER_ENV[cluster]
    values = helmrelease(f"infra/k8s/gitops/platform/{env}", "nohiki")["spec"]["values"]
    for path, placeholder in RUNTIME_VALUE_PLACEHOLDERS.items():
        assert _dig(values, path) == placeholder, f"{cluster}: {'.'.join(path)}"


@pytest.mark.parametrize("cluster", ["local", "prod-aks"])
def test_local_prod_platform_values_have_no_runtime_placeholders(cluster: str) -> None:
    env = CLUSTER_ENV[cluster]
    dumped = yaml.safe_dump(helmrelease(f"infra/k8s/gitops/platform/{env}", "nohiki")["spec"].get("values", {}))
    for token in (
        "${image_registry}",
        "${image_tag}",
        "${eso_vault_url}",
        "${eso_client_id}",
        "${eso_tenant_id}",
    ):
        assert token not in dumped, f"{cluster} unexpectedly carries the runtime placeholder {token!r}"


# ------------------------------------------------------------ environment isolation


@pytest.mark.parametrize("cluster", CLUSTER_ENV)
def test_cluster_never_references_a_foreign_environment(cluster: str) -> None:
    env = CLUSTER_ENV[cluster]
    rendered = _render(f"infra/k8s/gitops/clusters/{cluster}")
    for other_env in {v for v in CLUSTER_ENV.values() if v != env}:
        assert f"/gitops/infrastructure/{other_env}" not in rendered, f"{cluster} leaks infrastructure/{other_env}"
        assert f"/gitops/platform/{other_env}" not in rendered, f"{cluster} leaks platform/{other_env}"
        assert f"/observability/overlays/{other_env}" not in rendered, f"{cluster} leaks overlays/{other_env}"


@pytest.mark.parametrize("cluster", CLUSTER_ENV)
def test_observability_healthcheck_targets_own_namespace(cluster: str) -> None:
    env = CLUSTER_ENV[cluster]
    checks = stack(cluster, "observability")["spec"]["healthChecks"]
    namespaces = {check["namespace"] for check in checks}
    assert namespaces == {PLATFORM_NAMESPACE[env]}, f"{cluster} observability health check namespaces {namespaces}"


@pytest.mark.parametrize("cluster", CLUSTER_ENV)
def test_observability_waits_for_every_enabled_prometheus_target(cluster: str) -> None:
    env = CLUSTER_ENV[cluster]
    namespace = PLATFORM_NAMESPACE[env]
    checks = {
        (check["apiVersion"], check["kind"], check["name"], check["namespace"])
        for check in stack(cluster, "observability")["spec"]["healthChecks"]
    }
    assert {
        ("apps/v1", "Deployment", "nohiki-kube-prometheus-sta-operator", namespace),
        (
            "monitoring.coreos.com/v1",
            "Prometheus",
            "nohiki-kube-prometheus-sta-prometheus",
            namespace,
        ),
        (
            "monitoring.coreos.com/v1",
            "Alertmanager",
            "nohiki-kube-prometheus-sta-alertmanager",
            namespace,
        ),
        ("apps/v1", "Deployment", "nohiki-kube-state-metrics", namespace),
        ("apps/v1", "DaemonSet", "nohiki-prometheus-node-exporter", namespace),
    } <= checks
