"""Cross-render contracts for Flux, ESO ownership, and production activation."""

from __future__ import annotations

import functools
import importlib.util
import os
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
WORKFLOW = ROOT / ".github/workflows/cd_deploy-to-aks_nohiki.yml"
BUILD_PUSH_WORKFLOW = ROOT / ".github/workflows/build-push.yml"
BOOTSTRAP = GITOPS / "install/bootstrap.sh"
IDENTITY_FIXTURE = ROOT / "scripts/ci/tests/fixtures/values.prod.identity.yaml"
NETWORK_FIXTURE = ROOT / "scripts/ci/tests/fixtures/values.prod.network.yaml"
LOCAL_SECRET_CONTRACT = ROOT / "scripts/infra/local_secret_contract.py"

CLUSTERS = {
    "local": ("local", "nohiki"),
    "dev-aks": ("dev", "nohiki-dev"),
    "staging-aks": ("staging", "nohiki-staging"),
    "prod-aks": ("prod", "nohiki-prod"),
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
GATEWAY_NAMES = {"nohiki-gateway", "nohiki-model-egress"}
LOCAL_HTTP_ROUTE_NAMES = {
    "nohiki-account-route",
    "nohiki-api-route",
    "nohiki-auth-route",
    "nohiki-frontend-route",
    "nohiki-jwks-route",
    "nohiki-model-egress-healthz",
    "nohiki-otel-traces-route",
    "nohiki-ping-route",
    "nohiki-s3-route",
    "nohiki-sse-route",
}
CLOUD_HTTP_ROUTE_NAMES = LOCAL_HTTP_ROUTE_NAMES - {
    "nohiki-otel-traces-route",
    "nohiki-s3-route",
}
GATEWAY_HEALTH_CHECK_EXPRESSIONS = [
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


def _docs(text: str) -> tuple[dict[str, Any], ...]:
    return tuple(document for document in yaml.safe_load_all(text) if isinstance(document, dict))


@functools.cache
def _kustomize(relative: str) -> tuple[dict[str, Any], ...]:
    result = subprocess.run(
        ["kubectl", "kustomize", str(ROOT / relative)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return _docs(result.stdout)


def _digest_values(tmp_path: Path) -> Path:
    digests = {name: f"sha256:{index + 1:064x}" for index, name in enumerate(load_inventory().names)}
    path = tmp_path / "values.prod.digests.yaml"
    path.write_text(yaml.safe_dump({"global": {"imageDigests": digests}}), encoding="utf-8")
    return path


def _helm(environment: str, namespace: str, tmp_path: Path) -> tuple[dict[str, Any], ...]:
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
        str(CHART / f"values.{environment}.yaml"),
    ]
    if environment in {"dev", "staging"}:
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
    if environment == "prod":
        for overlay in (IDENTITY_FIXTURE, NETWORK_FIXTURE, _digest_values(tmp_path)):
            command.extend(("--values", str(overlay)))
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=True)
    return _docs(result.stdout)


def _external_secrets(
    documents: tuple[dict[str, Any], ...],
) -> dict[str, dict[str, Any]]:
    return {
        document["metadata"]["name"]: document for document in documents if document.get("kind") == "ExternalSecret"
    }


def _enabled_provider_consumers(
    documents: tuple[dict[str, Any], ...],
) -> tuple[set[str], set[str]]:
    routes: set[str] = set()
    provider_secrets: set[str] = set()
    for document in documents:
        if document.get("kind") != "AgentgatewayBackend":
            continue
        routes.add(document["metadata"]["name"])
        for group in document["spec"]["ai"]["groups"]:
            for provider in group["providers"]:
                provider_secrets.add(provider["policies"]["auth"]["secretRef"]["name"])
    return routes, provider_secrets


def _declared_provider_secret_names(environment: str) -> tuple[set[str], set[str]]:
    spec = importlib.util.spec_from_file_location("test_flux_local_secret_contract", LOCAL_SECRET_CONTRACT)
    assert spec is not None
    assert spec.loader is not None
    contract = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(contract)
    enabled_provider_credentials = contract.enabled_provider_credentials
    base_path = CHART / "values.yaml"
    all_credentials = enabled_provider_credentials(base_path, base_path)
    configured = enabled_provider_credentials(base_path, CHART / f"values.{environment}.yaml")
    prefix = "nohiki-model-egress-"
    return (
        {f"{prefix}{credential}" for credential in all_credentials},
        {f"{prefix}{credential}" for credential in configured},
    )


@pytest.mark.parametrize("cluster", CLUSTERS)
def test_provider_consumers_exactly_drive_routes_secrets_and_health(cluster: str, tmp_path: Path) -> None:
    environment, namespace = CLUSTERS[cluster]
    documents = _helm(environment, namespace, tmp_path)
    expected_routes, expected_secrets = _enabled_provider_consumers(documents)
    known_provider_secrets, declared_provider_secrets = _declared_provider_secret_names(environment)
    rendered_routes = {
        document["metadata"]["name"]
        for document in documents
        if document.get("kind") == "HTTPRoute"
        and document["metadata"]["name"].startswith("nohiki-model-egress-")
        and document["metadata"]["name"] != "nohiki-model-egress-healthz"
    }
    rendered_provider_secrets = set(_external_secrets(documents)) & known_provider_secrets
    checked_provider_secrets = {
        check["name"]
        for check in _stack(cluster, "platform")["spec"]["healthChecks"]
        if check["kind"] == "ExternalSecret" and check["name"] in known_provider_secrets
    }

    assert expected_secrets == declared_provider_secrets
    assert rendered_routes == expected_routes
    assert rendered_provider_secrets == expected_secrets
    assert checked_provider_secrets == expected_secrets
    for secret_name in expected_secrets:
        credential = secret_name.removeprefix("nohiki-model-egress-")
        external_secret = _external_secrets(documents)[secret_name]
        assert external_secret["spec"]["target"] == {
            "name": secret_name,
            "creationPolicy": "Owner",
        }
        if environment == "local" and credential == "openai":
            remote_ref = {
                "key": "nohiki-llm-proxy-source",
                "property": "LLM_PROXY_SERVER_API_KEY",
            }
        elif environment == "local":
            remote_ref = {
                "key": "nohiki-llm-runtime",
                "property": f"{credential}_api_key",
            }
        else:
            remote_ref = {"key": f"model-egress-{credential}-authorization"}
        assert external_secret["spec"]["data"] == [
            {
                "secretKey": "Authorization",
                "remoteRef": remote_ref,
            }
        ]
    if environment == "local":
        assert "nohiki-model-egress-messages" not in expected_routes
        assert "nohiki-model-egress-anthropic" not in expected_secrets
    else:
        assert "nohiki-model-egress-messages" in expected_routes
        assert "nohiki-model-egress-anthropic" in expected_secrets


def _stack(cluster: str, name: str) -> dict[str, Any]:
    return next(
        document
        for document in _kustomize(f"infra/k8s/gitops/clusters/{cluster}")
        if document.get("kind") == "Kustomization" and document["metadata"]["name"] == name
    )


def _resource_identity(document: dict[str, Any]) -> tuple[str, str, str, str]:
    api_version = document["apiVersion"]
    group = api_version.split("/", 1)[0] if "/" in api_version else "core"
    metadata = document["metadata"]
    return group, document["kind"], metadata.get("namespace", ""), metadata["name"]


@pytest.mark.parametrize("cluster", CLUSTERS)
def test_platform_and_observability_have_one_owner_per_gvk_name_namespace(cluster: str, tmp_path: Path) -> None:
    environment, namespace = CLUSTERS[cluster]
    streams = {
        "platform Helm release": _helm(environment, namespace, tmp_path),
        "observability Kustomization": _kustomize(f"infra/k8s/observability/overlays/{environment}"),
    }
    owners: dict[tuple[str, str, str, str], list[str]] = {}
    for owner, documents in streams.items():
        for document in documents:
            owners.setdefault(_resource_identity(document), []).append(owner)
    duplicates = {identity: sources for identity, sources in owners.items() if len(sources) != 1}
    assert duplicates == {}, f"resources must have one declarative owner: {duplicates}"


@pytest.mark.parametrize("cluster", CLUSTERS)
def test_platform_readiness_exactly_covers_rendered_secrets_and_gateway_routes(cluster: str, tmp_path: Path) -> None:
    environment, namespace = CLUSTERS[cluster]
    documents = _helm(environment, namespace, tmp_path)
    emitted_secrets = set(_external_secrets(documents))
    assert emitted_secrets, f"{environment} Helm render emitted no ExternalSecrets"

    readiness_role = next(
        document
        for document in documents
        if document.get("kind") == "Role" and document["metadata"]["name"] == "nohiki-external-secret-readiness"
    )
    rules = readiness_role["rules"]
    assert len(rules) == 1
    assert set(rules[0]["resourceNames"]) == emitted_secrets

    static_route_names = LOCAL_HTTP_ROUTE_NAMES if environment == "local" else CLOUD_HTTP_ROUTE_NAMES
    provider_route_names, _ = _enabled_provider_consumers(documents)
    route_names = static_route_names | provider_route_names
    expected_gateway_resources = {
        *{("gateway.networking.k8s.io/v1", "Gateway", namespace, name) for name in GATEWAY_NAMES},
        *{("gateway.networking.k8s.io/v1", "HTTPRoute", namespace, name) for name in route_names},
    }
    emitted_gateway_resources = {
        (
            document["apiVersion"],
            document["kind"],
            document["metadata"].get("namespace", ""),
            document["metadata"]["name"],
        )
        for document in documents
        if document.get("kind") in {"Gateway", "HTTPRoute"}
    }
    assert emitted_gateway_resources == expected_gateway_resources

    spec = _stack(cluster, "platform")["spec"]
    expected = {
        ("helm.toolkit.fluxcd.io/v2", "HelmRelease", "flux-system", "nohiki"),
        *{("external-secrets.io/v1", "ExternalSecret", namespace, name) for name in emitted_secrets},
        *emitted_gateway_resources,
    }
    actual = {(check["apiVersion"], check["kind"], check["namespace"], check["name"]) for check in spec["healthChecks"]}
    assert actual == expected
    assert spec["healthCheckExprs"] == GATEWAY_HEALTH_CHECK_EXPRESSIONS


@pytest.mark.parametrize("cluster", ["local", "dev-aks", "staging-aks"])
def test_observability_flux_health_covers_all_its_external_secrets(
    cluster: str,
) -> None:
    environment, _ = CLUSTERS[cluster]
    emitted = set(_external_secrets(_kustomize(f"infra/k8s/observability/overlays/{environment}")))
    assert emitted == OBSERVABILITY_EXTERNAL_SECRETS[environment]
    checked = {
        check["name"]
        for check in _stack(cluster, "observability")["spec"]["healthChecks"]
        if check["kind"] == "ExternalSecret"
    }
    assert checked == emitted


def test_kubernetes_has_no_direct_or_disabled_llm_secret_mode() -> None:
    template = (CHART / "templates/eso-external-secrets.yaml").read_text(encoding="utf-8")
    assert "modeName" not in template
    assert 'ternary "modelEgress" "direct"' not in template
    assert 'index $refs "direct"' not in template
    assert 'list "nohiki-llm-runtime"' not in template
    gateway_template = (CHART / "templates/model-egress.yaml").read_text(encoding="utf-8")
    assert "$modelEgress.enabled" not in gateway_template

    for environment, _namespace in CLUSTERS.values():
        values = yaml.safe_load((CHART / f"values.{environment}.yaml").read_text(encoding="utf-8"))
        assert "enabled" not in values["global"].get("modelEgress", {})
        remote_refs = values["global"].get("eso", {}).get("remoteRefs", {})
        assert "direct" not in remote_refs
        assert "nohiki-llm-runtime" not in yaml.safe_dump(remote_refs)


@pytest.mark.parametrize("environment", CLUSTERS.values(), ids=CLUSTERS)
def test_observability_external_secret_remote_keys_and_targets_are_exact(
    environment: tuple[str, str],
) -> None:
    name, _namespace = environment
    external = _external_secrets(_kustomize(f"infra/k8s/observability/overlays/{name}"))
    if name == "local":
        assert external == {}
        return

    expected_remote = {
        "grafana-admin-credentials": {
            "admin-user": "grafana-admin-user",
            "admin-password": "grafana-admin-password",
        },
        "grafana-oauth-credentials": {
            "OAUTH_CLIENT_ID": "grafana-oauth-client-id",
            "OAUTH_CLIENT_SECRET": "grafana-oauth-client-secret",
            "TENANT_ID": "azure-tenant-id",
        },
        "observability-storage-credentials": {
            "accessKey": "s3-access-key",
            "secretKey": "s3-secret-key",
            "region": "s3-region",
        },
    }
    assert set(external) == set(expected_remote)
    for secret_name, remote_keys in expected_remote.items():
        secret = external[secret_name]
        assert secret["spec"]["target"]["name"] == secret_name
        assert secret["spec"]["target"]["creationPolicy"] == "Owner"
        assert secret["spec"]["secretStoreRef"] == {
            "kind": "ClusterSecretStore",
            "name": "nohiki-secret-store",
        }
        assert {item["secretKey"]: item["remoteRef"]["key"] for item in secret["spec"]["data"]} == remote_keys

    storage_template = external["observability-storage-credentials"]["spec"]["target"]["template"]
    assert storage_template == {
        "engineVersion": "v2",
        "data": {
            "AWS_ACCESS_KEY_ID": "{{ .accessKey }}",
            "AWS_SECRET_ACCESS_KEY": "{{ .secretKey }}",
            "AWS_REGION": "{{ .region }}",
        },
    }


def test_production_fixture_renders_without_plaintext_secrets(tmp_path: Path) -> None:
    documents = _helm("prod", "nohiki-prod", tmp_path)
    assert _external_secrets(documents)
    assert not any("stringData" in document for document in documents)
    secret_names = {document["metadata"]["name"] for document in documents if document.get("kind") == "Secret"}
    assert not secret_names & {
        "nohiki-llm-runtime",
        "nohiki-llm-api-keys",
        "nohiki-model-egress-openai",
        "nohiki-model-egress-anthropic",
        "nohiki-model-egress-openrouter",
    }
    assert "PROMOTION_REQUIRED" not in yaml.safe_dump_all(documents)


def test_prod_values_files_are_present_before_activation_or_generated_by_promotion() -> None:
    platform = next(
        document
        for document in _kustomize("infra/k8s/gitops/platform/prod")
        if document.get("kind") == "HelmRelease" and document["metadata"]["name"] == "nohiki"
    )
    values_files = platform["spec"]["chart"]["spec"]["valuesFiles"]
    assert values_files
    missing = {path for path in values_files if not (ROOT / path).is_file()}

    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    activation = workflow["jobs"]["activate-production-runtime"]
    verify = next(step for step in activation["steps"] if step.get("name") == "Verify immutable release inputs")
    verify_run = verify["run"]
    for path in missing:
        assert path in verify_run
    assert 'git cat-file -e "$RELEASE_SHA:$path"' in verify_run
    assert 'test -s "$path"' in verify_run

    producer_workflows = (
        workflow,
        yaml.safe_load(BUILD_PUSH_WORKFLOW.read_text(encoding="utf-8")),
    )
    promotion_steps = {
        step["name"]: step
        for producer in producer_workflows
        for job in producer["jobs"].values()
        for step in job.get("steps", [])
        if isinstance(step, dict) and "name" in step
    }
    generated = {
        "infra/k8s/helm/values.prod.identity.yaml": "Generate production identity overlay",
        "infra/k8s/helm/values.prod.network.yaml": "Generate production network overlay",
        "infra/k8s/helm/values.prod.digests.yaml": "Assemble and validate production digests",
    }
    assert missing <= set(generated)
    for path in missing:
        step_name = generated[path]
        assert step_name in promotion_steps, f"{path} has no tested promotion producer"
        assert path in promotion_steps[step_name]["run"]

    stamp = next(
        step for step in activation["steps"] if step.get("name") == "Stamp and activate production GitOps source"
    )
    assert activation["steps"].index(verify) < activation["steps"].index(stamp)
    for stack_name in (
        "gateway-api-crds.yaml",
        "infrastructure.yaml",
        "platform.yaml",
        "observability.yaml",
    ):
        assert stack_name in stamp["run"]
    assert 'text.replace("suspend: true", "suspend: false")' in stamp["run"]


def test_flux_release_source_and_bootstrap_source_identities_are_unambiguous() -> None:
    bootstrap = BOOTSTRAP.read_text(encoding="utf-8")
    assert 'GITOPS_NAMESPACE="flux-system"' in bootstrap
    assert 'cluster_path="infra/k8s/gitops/clusters/local"' in bootstrap
    assert '--path="${cluster_path}"' in bootstrap

    for cluster in ("local", "dev-aks", "staging-aks"):
        documents = _kustomize(f"infra/k8s/gitops/clusters/{cluster}")
        assert not any(document.get("kind") == "GitRepository" for document in documents)
        for stack_name in ("infrastructure", "platform", "observability"):
            assert _stack(cluster, stack_name)["spec"]["sourceRef"] == {
                "kind": "GitRepository",
                "name": "flux-system",
            }

    prod_documents = _kustomize("infra/k8s/gitops/clusters/prod-aks")
    repositories = [document for document in prod_documents if document.get("kind") == "GitRepository"]
    assert len(repositories) == 1
    repository = repositories[0]
    assert _resource_identity(repository) == (
        "source.toolkit.fluxcd.io",
        "GitRepository",
        "flux-system",
        "gitops-release",
    )
    assert repository["spec"]["ref"] == {"commit": "PROMOTION_REQUIRED"}
    for stack_name in ("infrastructure", "platform", "observability"):
        assert _stack("prod-aks", stack_name)["spec"]["sourceRef"] == {
            "kind": "GitRepository",
            "name": "gitops-release",
        }


def test_local_runtime_secrets_have_one_flux_owner_and_ordered_dependencies() -> None:
    cluster = yaml.safe_load((GITOPS / "clusters/local/kustomization.yaml").read_text(encoding="utf-8"))
    assert cluster["resources"].count("runtime-secrets.yaml") == 1
    runtime = _stack("local", "runtime-secrets")
    assert runtime["spec"]["path"] == "./infra/k8s/gitops/secrets/local"
    assert runtime["spec"]["decryption"] == {
        "provider": "sops",
        "secretRef": {"name": "flux-sops"},
    }
    assert runtime["spec"]["dependsOn"] == [{"name": "infrastructure"}]
    assert runtime["spec"]["healthChecks"] == [
        {
            "apiVersion": "v1",
            "kind": "Secret",
            "name": "nohiki-llm-proxy-source",
            "namespace": "nohiki",
        },
        {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "name": "nohiki-owner-model-egress-values",
            "namespace": "flux-system",
        },
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
    assert _stack("local", "platform")["spec"]["dependsOn"] == [
        {"name": "infrastructure"},
        {"name": "runtime-secrets"},
        {"name": "registry"},
    ]


def test_local_runtime_kustomization_has_one_encrypted_secret_owner() -> None:
    local = yaml.safe_load((GITOPS / "secrets/local/kustomization.yaml").read_text(encoding="utf-8"))
    encrypted = {resource for resource in local["resources"] if resource.endswith(".sops.yaml")}
    assert encrypted == {
        "nohiki-llm-runtime.sops.yaml",
        "nohiki-app-secrets.sops.yaml",
        "nohiki-model-egress-tls-source.sops.yaml",
    }
    assert not any("generated-values" in resource for resource in local["resources"])


def test_bootstrap_applies_only_the_snapshotted_age_trust_root_secret() -> None:
    bootstrap = BOOTSTRAP.read_text(encoding="utf-8")
    created = re.findall(r"\bcreate secret generic\s+([^\s\\]+)", bootstrap)
    assert created == ["flux-sops"]
    assert "bound_kubectl_with_age create secret generic flux-sops" in bootstrap
    assert "--from-file=age.agekey=@AGEKEY@" in bootstrap
    assert '--from-file=age.agekey="${BOOTSTRAP_AGE_KEY}"' not in bootstrap


def test_invalid_age_preflight_emits_no_kubernetes_or_flux_bytes(
    tmp_path: Path,
) -> None:
    mutations = tmp_path / "mutations"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    kubectl = bin_dir / "kubectl"
    kubectl.write_text(
        "#!/bin/sh\n"
        "if [ \"$*\" = 'config current-context' ]; then\n"
        "  printf '%s\\n' synthetic-context\n"
        "else\n"
        f"  printf '%s\\n' \"$*\" >> {mutations}\n"
        "fi\n",
        encoding="utf-8",
    )
    kubectl.chmod(0o755)
    flux = bin_dir / "flux"
    flux.write_text(
        f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> {mutations}\n",
        encoding="utf-8",
    )
    flux.chmod(0o755)
    age_key = tmp_path / "age.agekey"
    age_key.write_text("AGE-SECRET-KEY-1INVALID-FIXTURE\n", encoding="utf-8")
    age_key.chmod(0o600)
    result = subprocess.run(
        [str(ROOT / "infra/k8s/local/lifecycle.sh"), "bootstrap"],
        cwd=ROOT,
        env={
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "K8S_LOCAL_CONTEXT": "synthetic-context",
            "SOPS_AGE_KEY_FILE": str(age_key),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert not mutations.exists()
    assert "AGE-SECRET-KEY-1INVALID-FIXTURE" not in result.stdout + result.stderr
