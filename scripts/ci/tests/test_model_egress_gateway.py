"""High-signal render contracts for the agentgateway model-egress boundary."""

import copy
import json
import subprocess
import tarfile
from collections.abc import Iterator
from functools import cache
from pathlib import Path

import jsonschema
import pytest
import yaml
from _documents import Manifest, load_manifests, load_mapping
from ci_checks.core.image_inventory import load_inventory

_ROOT = Path(__file__).resolve().parents[3]
_CHART = _ROOT / "infra/k8s/helm"
_AGENTGATEWAY_CRDS = _ROOT / "infra/k8s/helm-foundation/charts/agentgateway-crds-v1.3.1.tgz"
_GATEWAY_API_CRDS = _ROOT / "infra/k8s/gitops/gateway-api-crds/gateway-api-crds.yaml"
_IDENTITY = Path(__file__).parent / "fixtures/values.prod.identity.yaml"
_NETWORK = Path(__file__).parent / "fixtures/values.prod.network.yaml"
_GATEWAY_NAME = "nohiki-model-egress"
_GATEWAY_HOST = f"{_GATEWAY_NAME}.nohiki.svc.cluster.local"
_GATEWAY_ORIGIN = f"https://{_GATEWAY_HOST}:8443"
_CLIENT_SECRETS = {
    "nohiki-doc-content-service": (
        "nohiki-model-egress-client-doc-content",
        "doc-content",
    ),
    "nohiki-job-ingest-enrichment-service": (
        "nohiki-model-egress-client-job-ingest-enrichment",
        "job-ingest-enrichment",
    ),
}
_PROVIDER_SECRETS_BY_ENVIRONMENT = {
    "local": {
        "nohiki-model-egress-openrouter",
        "nohiki-model-egress-openai",
    },
    "managed": {
        "nohiki-model-egress-openrouter",
        "nohiki-model-egress-openai",
        "nohiki-model-egress-anthropic",
    },
}
_PROVIDER_SECRETS = set().union(*_PROVIDER_SECRETS_BY_ENVIRONMENT.values())
_ROUTE_PATHS_BY_ENVIRONMENT = {
    "local": {
        "nohiki-model-egress-responses": "/v1/responses",
        "nohiki-model-egress-completions": "/v1/chat/completions",
    },
    "managed": {
        "nohiki-model-egress-responses": "/v1/responses",
        "nohiki-model-egress-completions": "/v1/chat/completions",
        "nohiki-model-egress-messages": "/v1/messages",
    },
}
_ROUTE_TYPES = {
    "nohiki-model-egress-responses": "Responses",
    "nohiki-model-egress-completions": "Completions",
    "nohiki-model-egress-messages": "Messages",
}
_ROUTE_CLIENTS_BY_ENVIRONMENT = {
    "local": {
        "nohiki-model-egress-responses": {
            "nohiki-model-egress-client-doc-content",
            "nohiki-model-egress-client-job-ingest-enrichment",
        },
        "nohiki-model-egress-completions": set(),
    },
    "managed": {
        "nohiki-model-egress-responses": {
            "nohiki-model-egress-client-doc-content",
            "nohiki-model-egress-client-job-ingest-enrichment",
        },
        "nohiki-model-egress-completions": set(),
        "nohiki-model-egress-messages": set(),
    },
}
_PROVIDER_NAMES_BY_ENVIRONMENT = {
    "local": {"openai-responses", "openrouter-completions"},
    "managed": {
        "openai-responses",
        "openrouter-completions",
        "anthropic-messages",
    },
}
_GATEWAY_RESOURCE_COUNTS = {"local": 15, "managed": 20}
_GATEWAY_HOSTS_BY_ENVIRONMENT = {
    "local": _GATEWAY_HOST,
    "managed": f"{_GATEWAY_NAME}.nohiki-dev.svc.cluster.local",
}
_MANAGED_RATE_LIMITS = {
    "nohiki-model-egress-responses": [
        {"requests": 2, "unit": "Seconds", "burst": 4},
        {"tokens": 120_000, "unit": "Minutes", "burst": 20_000},
    ],
    "nohiki-model-egress-completions": [
        {"requests": 1, "unit": "Seconds", "burst": 2},
        {"tokens": 60_000, "unit": "Minutes", "burst": 10_000},
    ],
    "nohiki-model-egress-messages": [
        {"requests": 1, "unit": "Seconds", "burst": 2},
        {"tokens": 60_000, "unit": "Minutes", "burst": 10_000},
    ],
}
_ROUTE_SELECTOR_PREFIX = "nohiki.io/model-egress-route-"


def _walk(value: object) -> Iterator[object]:
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _render(
    *set_values: str,
    values: Path | None = None,
    model_egress_enabled: bool = True,
) -> tuple[Manifest, ...]:
    command = [
        "helm",
        "template",
        "nohiki",
        str(_CHART),
        "--namespace",
        "nohiki",
        "--values",
        str(_CHART / "values.local.yaml"),
        "--set",
        f"global.modelEgress.enabled={str(model_egress_enabled).lower()}",
    ]
    if values is not None:
        command.extend(("--values", str(values)))
    for value in set_values:
        command.extend(("--set-string", value))
    result = subprocess.run(command, cwd=_ROOT, check=True, capture_output=True, text=True)
    return tuple(load_manifests(result.stdout))


def _render_environment(values_name: str, tmp_path: Path) -> tuple[Manifest, ...]:
    environment = values_name.removeprefix("values.").removesuffix(".yaml")
    command = [
        "helm",
        "template",
        "nohiki",
        str(_CHART),
        "--namespace",
        "nohiki" if environment == "local" else f"nohiki-{environment}",
        "--values",
        str(_CHART / values_name),
    ]
    if environment == "prod":
        digests = {
            f"ghcr.io/mchar7/nohiki-monorepo/{name}": f"sha256:{index + 1:064x}"
            for index, name in enumerate(load_inventory().names)
        }
        digest_values = tmp_path / "values.prod.digests.yaml"
        digest_values.write_text(yaml.safe_dump({"global": {"imageDigests": digests}}), encoding="utf-8")
        command.extend(
            (
                "--values",
                str(_IDENTITY),
                "--values",
                str(_NETWORK),
                "--values",
                str(digest_values),
            )
        )
    if environment in {"dev", "staging", "prod"}:
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
    result = subprocess.run(command, cwd=_ROOT, check=True, capture_output=True, text=True)
    return tuple(load_manifests(result.stdout))


@pytest.fixture(scope="module")
def rendered() -> tuple[Manifest, ...]:
    return _render()


@pytest.fixture(scope="module")
def managed_rendered(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[Manifest, ...]:
    return _render_environment("values.dev.yaml", tmp_path_factory.mktemp("managed-model-egress"))


@pytest.fixture(scope="module")
def environment_rendered(
    rendered: tuple[Manifest, ...],
    managed_rendered: tuple[Manifest, ...],
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, tuple[Manifest, ...]]:
    tmp_path = tmp_path_factory.mktemp("model-egress-environments")
    return {
        "values.local.yaml": rendered,
        "values.dev.yaml": managed_rendered,
        "values.staging.yaml": _render_environment("values.staging.yaml", tmp_path),
        "values.prod.yaml": _render_environment("values.prod.yaml", tmp_path),
    }


def _named(documents: tuple[Manifest, ...], kind: str, name: str) -> Manifest:
    return next(
        document for document in documents if document.get("kind") == kind and document["metadata"]["name"] == name
    )


@cache
def _agentgateway_crds() -> dict[str, Manifest]:
    with tarfile.open(_AGENTGATEWAY_CRDS) as archive:
        members = [member for member in archive.getmembers() if member.name.endswith(".yaml")]
        documents = [
            document
            for member in members
            for stream in (archive.extractfile(member),)
            if stream is not None
            for document in load_manifests(stream.read().decode())
            if document.get("kind") == "CustomResourceDefinition"
        ]
    crds: dict[str, Manifest] = {}
    for document in documents:
        spec = document["spec"]
        assert isinstance(spec, dict)
        names: object = spec.get("names")
        assert isinstance(names, dict)
        kind = names.get("kind")
        assert isinstance(kind, str)
        crds[kind] = document
    return crds


@cache
def _gateway_api_crds() -> dict[str, Manifest]:
    documents = (
        document
        for document in load_manifests(_GATEWAY_API_CRDS.read_text(encoding="utf-8"))
        if document.get("kind") == "CustomResourceDefinition"
    )
    crds: dict[str, Manifest] = {}
    for document in documents:
        spec = document["spec"]
        assert isinstance(spec, dict)
        names: object = spec.get("names")
        assert isinstance(names, dict)
        kind = names.get("kind")
        assert isinstance(kind, str)
        crds[kind] = document
    return crds


def _schema(crd: Manifest, version: str) -> dict[object, object]:
    spec = crd["spec"]
    assert isinstance(spec, dict)
    versions: object = spec.get("versions")
    assert isinstance(versions, list)
    version_spec = next(item for item in versions if isinstance(item, dict) and item.get("name") == version)
    schema: object = version_spec.get("schema")
    assert isinstance(schema, dict)
    openapi_schema: object = schema.get("openAPIV3Schema")
    assert isinstance(openapi_schema, dict)
    return {key: openapi_schema.get(key) for key in openapi_schema}


def _secret_refs(pod_spec: object) -> set[tuple[str, str]]:
    refs: set[tuple[str, str]] = set()
    for node in _walk(pod_spec):
        if not isinstance(node, dict):
            continue
        key_ref = node.get("secretKeyRef")
        if isinstance(key_ref, dict):
            name = key_ref.get("name")
            key = key_ref.get("key")
            if isinstance(name, str) and isinstance(key, str):
                refs.add((name, key))
        secret = node.get("secret")
        if not isinstance(secret, dict):
            continue
        secret_name = secret.get("secretName")
        items = secret.get("items", [])
        if not isinstance(secret_name, str) or not isinstance(items, list):
            continue
        for item in items:
            assert isinstance(item, dict)
            key = item.get("key")
            assert isinstance(key, str)
            refs.add((secret_name, key))
    return refs


def _matches_selector(labels: object, selector: object) -> bool:
    assert isinstance(labels, dict)
    assert all(isinstance(key, str) and isinstance(value, str) for key, value in labels.items())
    assert isinstance(selector, dict)
    match_labels = selector.get("matchLabels", {})
    assert isinstance(match_labels, dict)
    assert all(isinstance(key, str) and isinstance(value, str) for key, value in match_labels.items())
    return all(labels.get(key) == value for key, value in match_labels.items())


def _container_env(deployment: Manifest) -> dict[str, str]:
    spec = deployment["spec"]
    assert isinstance(spec, dict)
    template: object = spec.get("template")
    assert isinstance(template, dict)
    pod_spec: object = template.get("spec")
    assert isinstance(pod_spec, dict)
    containers: object = pod_spec.get("containers")
    assert isinstance(containers, list)
    container = containers[0]
    assert isinstance(container, dict)
    env: object = container.get("env")
    assert isinstance(env, list)
    entries: dict[str, str] = {}
    for item in env:
        assert isinstance(item, dict)
        if "value" not in item:
            continue
        name = item.get("name")
        value = item.get("value")
        assert isinstance(name, str)
        assert isinstance(value, str)
        entries[name] = value
    return entries


def test_rendered_gateway_resources_validate_against_vendored_1_3_1_schemas(
    rendered: tuple[Manifest, ...],
    managed_rendered: tuple[Manifest, ...],
) -> None:
    assert _AGENTGATEWAY_CRDS.is_file(), (
        "run `helm dependency build infra/k8s/helm-foundation`; pinned agentgateway 1.3.1 schemas are required"
    )
    crds = _gateway_api_crds() | _agentgateway_crds()
    assert {
        "AgentgatewayParameters",
        "AgentgatewayBackend",
        "AgentgatewayPolicy",
    } <= set(crds)
    for environment, documents in {
        "local": rendered,
        "managed": managed_rendered,
    }.items():
        resources = [
            document
            for document in documents
            if document.get("kind")
            in {
                "AgentgatewayParameters",
                "AgentgatewayBackend",
                "AgentgatewayPolicy",
                "Gateway",
                "HTTPRoute",
            }
            and (
                document.get("kind") not in {"Gateway", "HTTPRoute"}
                or (document.get("metadata", {})).get("name", "").startswith(_GATEWAY_NAME)
            )
        ]
        assert len(resources) == _GATEWAY_RESOURCE_COUNTS[environment]
        for resource in resources:
            kind = resource["kind"]
            assert kind in crds, f"rendered {kind} has no pinned validation schema"
            version = resource["apiVersion"].rsplit("/", 1)[-1]
            if kind.startswith("Agentgateway"):
                assert resource["apiVersion"] == "agentgateway.dev/v1alpha1"
            jsonschema.Draft202012Validator(_schema(crds[kind], version)).validate(resource)


def test_gateway_is_one_private_https_clusterip_with_certificate_sni_and_ca(
    rendered: tuple[Manifest, ...],
) -> None:
    parameters = _named(rendered, "AgentgatewayParameters", _GATEWAY_NAME)
    parameter_spec = parameters["spec"]
    assert isinstance(parameter_spec, dict)
    service: object = parameter_spec.get("service")
    assert isinstance(service, dict)
    assert service.get("spec") == {"type": "ClusterIP"}
    gateway = _named(rendered, "Gateway", _GATEWAY_NAME)
    gateway_spec = gateway["spec"]
    assert isinstance(gateway_spec, dict)
    assert gateway_spec.get("gatewayClassName") == "agentgateway"
    infrastructure: object = gateway_spec.get("infrastructure")
    assert isinstance(infrastructure, dict)
    assert infrastructure.get("parametersRef") == {
        "group": "agentgateway.dev",
        "kind": "AgentgatewayParameters",
        "name": _GATEWAY_NAME,
    }
    assert gateway_spec.get("listeners") == [
        {
            "name": "model-https",
            "hostname": _GATEWAY_HOST,
            "protocol": "HTTPS",
            "port": 8443,
            "tls": {
                "mode": "Terminate",
                "certificateRefs": [{"group": "", "kind": "Secret", "name": "nohiki-model-egress-tls"}],
            },
            "allowedRoutes": {"namespaces": {"from": "Same"}},
        }
    ]


def test_exact_supported_lanes_use_agentgateway_backends_and_preserve_models(
    rendered: tuple[Manifest, ...],
    managed_rendered: tuple[Manifest, ...],
) -> None:
    for environment, documents in {
        "local": rendered,
        "managed": managed_rendered,
    }.items():
        expected_paths = _ROUTE_PATHS_BY_ENVIRONMENT[environment]
        routes = {
            (document)["metadata"]["name"]: document
            for document in documents
            if document.get("kind") == "HTTPRoute"
            and (document)["metadata"]["name"].startswith(f"{_GATEWAY_NAME}-")
            and (document)["metadata"]["name"] != f"{_GATEWAY_NAME}-healthz"
        }
        assert set(routes) == set(expected_paths)
        for name, path in expected_paths.items():
            route = routes[name]
            route_spec = route["spec"]
            assert isinstance(route_spec, dict)
            assert route_spec.get("hostnames") == [_GATEWAY_HOSTS_BY_ENVIRONMENT[environment]]
            assert route_spec.get("parentRefs") == [
                {
                    "group": "gateway.networking.k8s.io",
                    "kind": "Gateway",
                    "name": _GATEWAY_NAME,
                    "sectionName": "model-https",
                }
            ]
            rules: object = route_spec.get("rules")
            assert isinstance(rules, list)
            rule = rules[0]
            assert isinstance(rule, dict)
            assert rule.get("matches") == [{"path": {"type": "Exact", "value": path}}]
            assert rule.get("backendRefs") == [
                {
                    "group": "agentgateway.dev",
                    "kind": "AgentgatewayBackend",
                    "name": name,
                }
            ]

        backends = [document for document in documents if document.get("kind") == "AgentgatewayBackend"]
        assert {(backend)["metadata"]["name"] for backend in backends} == set(expected_paths)
        backend_groups: dict[str, list[object]] = {}
        for backend in backends:
            spec = backend["spec"]
            assert isinstance(spec, dict)
            ai: object = spec.get("ai")
            assert isinstance(ai, dict)
            groups = ai.get("groups")
            assert isinstance(groups, list)
            backend_groups[backend["metadata"]["name"]] = list(groups)
        providers_by_name: dict[str, dict[object, object]] = {}
        for groups in backend_groups.values():
            for group in groups:
                assert isinstance(group, dict)
                providers = group.get("providers")
                assert isinstance(providers, list)
                for provider in providers:
                    assert isinstance(provider, dict)
                    assert "model" not in provider
                    provider_name = provider.get("name")
                    assert isinstance(provider_name, str)
                    providers_by_name[provider_name] = {key: provider.get(key) for key in provider}
        assert set(providers_by_name) == _PROVIDER_NAMES_BY_ENVIRONMENT[environment]
        assert providers_by_name["openai-responses"].get("host") == "api.openai.com"
        assert providers_by_name["openai-responses"].get("port") == 443
        assert providers_by_name["openai-responses"].get("path") == "/v1/responses"
        assert providers_by_name["openai-responses"].get("openai") == {}
        assert providers_by_name["openrouter-completions"].get("host") == "openrouter.ai"
        assert providers_by_name["openrouter-completions"].get("custom") == {
            "formats": [{"type": "Completions", "path": "/api/v1/chat/completions"}]
        }
        openai_policies = providers_by_name["openai-responses"].get("policies")
        assert isinstance(openai_policies, dict)
        assert openai_policies.get("tls") == {
            "sni": "api.openai.com",
            "verifySubjectAltNames": ["api.openai.com"],
        }
        openrouter_policies = providers_by_name["openrouter-completions"].get("policies")
        assert isinstance(openrouter_policies, dict)
        assert openrouter_policies.get("tls") == {
            "sni": "openrouter.ai",
            "verifySubjectAltNames": ["openrouter.ai"],
        }
        assert "openrouter-responses" not in providers_by_name
        if environment == "managed":
            anthropic = providers_by_name["anthropic-messages"]
            assert anthropic.get("anthropic") == {}
            assert anthropic.get("path") == "/v1/messages"
            anthropic_policies = anthropic.get("policies")
            assert isinstance(anthropic_policies, dict)
            assert anthropic_policies.get("auth") == {
                "secretRef": {"name": "nohiki-model-egress-anthropic"},
                "location": {"header": {"name": "x-api-key"}},
            }
            assert anthropic_policies.get("tls") == {
                "sni": "api.anthropic.com",
                "verifySubjectAltNames": ["api.anthropic.com"],
            }

        route_type_policies = {
            document["metadata"]["name"].removesuffix("-health"): document
            for document in documents
            if document.get("kind") == "AgentgatewayPolicy" and document["metadata"]["name"].endswith("-health")
        }
        assert set(route_type_policies) == set(expected_paths)
        for name, path in expected_paths.items():
            policy_spec = route_type_policies[name]["spec"]
            assert isinstance(policy_spec, dict)
            backend_policy = policy_spec.get("backend")
            assert isinstance(backend_policy, dict)
            backend_ai = backend_policy.get("ai")
            assert isinstance(backend_ai, dict)
            assert backend_ai.get("routes") == {path: _ROUTE_TYPES[name]}


@pytest.mark.parametrize(
    "values_name",
    ["values.local.yaml", "values.dev.yaml", "values.staging.yaml", "values.prod.yaml"],
)
def test_every_environment_routes_openai_luna_sol_models_only_through_native_openai_responses(
    values_name: str,
    environment_rendered: dict[str, tuple[Manifest, ...]],
) -> None:
    documents = environment_rendered[values_name]
    backend = _named(documents, "AgentgatewayBackend", "nohiki-model-egress-responses")
    spec = backend["spec"]
    assert isinstance(spec, dict)
    ai: object = spec.get("ai")
    assert isinstance(ai, dict)
    groups = ai.get("groups")
    assert isinstance(groups, list)
    assert len(groups) == 1
    group = groups[0]
    assert isinstance(group, dict)
    providers = group.get("providers")
    assert isinstance(providers, list)
    assert len(providers) == 1
    provider = providers[0]
    assert isinstance(provider, dict)
    assert provider.get("name") == "openai-responses"
    assert provider.get("host") == "api.openai.com"
    assert provider.get("port") == 443
    assert provider.get("path") == "/v1/responses"
    assert provider.get("openai") == {}
    policies = provider.get("policies")
    assert isinstance(policies, dict)
    auth: object = policies.get("auth")
    assert isinstance(auth, dict)
    assert auth.get("secretRef") == {"name": "nohiki-model-egress-openai"}
    assert policies.get("tls") == {
        "sni": "api.openai.com",
        "verifySubjectAltNames": ["api.openai.com"],
    }
    assert not any(isinstance(node, str) and "openrouter" in node.lower() for node in _walk(backend))


def test_provider_endpoint_override_routes_through_plaintext_local_proxy(tmp_path: Path) -> None:
    values = tmp_path / "values.proxy.yaml"
    values.write_text(
        yaml.safe_dump(
            {
                "global": {
                    "modelEgress": {
                        "providerEndpoints": {
                            "openai-responses": {
                                "host": "127.0.0.1",
                                "port": 8317,
                                "path": "/v1/responses",
                                "tls": None,
                            }
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    backend = _named(_render(values=values), "AgentgatewayBackend", "nohiki-model-egress-responses")
    spec = backend["spec"]
    assert isinstance(spec, dict)
    ai = spec.get("ai")
    assert isinstance(ai, dict)
    groups = ai.get("groups")
    assert isinstance(groups, list)
    group = groups[0]
    assert isinstance(group, dict)
    providers = group.get("providers")
    assert isinstance(providers, list)
    provider = providers[0]
    assert isinstance(provider, dict)
    assert provider["host"] == "127.0.0.1"
    assert provider["port"] == 8317
    assert provider["path"] == "/v1/responses"
    policies = provider.get("policies")
    assert isinstance(policies, dict)
    assert "tls" not in policies


def test_healthz_is_an_exact_unauthenticated_direct_response_route(
    rendered: tuple[Manifest, ...],
) -> None:
    route_name = f"{_GATEWAY_NAME}-healthz"
    route = _named(rendered, "HTTPRoute", route_name)
    assert route["spec"] == {
        "parentRefs": [
            {
                "group": "gateway.networking.k8s.io",
                "kind": "Gateway",
                "name": _GATEWAY_NAME,
                "sectionName": "model-https",
            }
        ],
        "hostnames": [_GATEWAY_HOST],
        "rules": [
            {
                "name": "healthz",
                "matches": [{"path": {"type": "Exact", "value": "/healthz"}}],
            }
        ],
    }

    policy = _named(
        rendered,
        "AgentgatewayPolicy",
        f"{route_name}-direct-response",
    )
    assert policy["spec"] == {
        "targetRefs": [
            {
                "group": "gateway.networking.k8s.io",
                "kind": "HTTPRoute",
                "name": route_name,
            }
        ],
        "traffic": {"directResponse": {"status": 200, "body": "ok"}},
    }
    authenticated_target = [
        {
            "group": "gateway.networking.k8s.io",
            "kind": "HTTPRoute",
            "name": route_name,
        }
    ]
    for candidate in rendered:
        if candidate.get("kind") != "AgentgatewayPolicy":
            continue
        candidate_spec = candidate["spec"]
        assert isinstance(candidate_spec, dict)
        if candidate_spec.get("targetRefs") != authenticated_target:
            continue
        traffic = candidate_spec.get("traffic", {})
        assert isinstance(traffic, dict)
        assert "apiKeyAuthentication" not in traffic


def test_models_lane_is_not_claimed_when_vendored_schema_does_not_support_it(
    rendered: tuple[Manifest, ...],
) -> None:
    if _AGENTGATEWAY_CRDS.is_file():
        backend_schema = _schema(_agentgateway_crds()["AgentgatewayBackend"], "v1alpha1")
        enums: list[list[str]] = []
        for node in _walk(backend_schema):
            if not isinstance(node, dict) or "enum" not in node:
                continue
            enum = node.get("enum")
            assert isinstance(enum, list)
            assert all(isinstance(item, str) for item in enum)
            enums.append([item for item in enum if isinstance(item, str)])
        custom_formats = next(
            enum for enum in enums if {"Responses", "Completions", "Messages"} <= set(enum) and "Detect" not in enum
        )
        assert "Models" not in custom_formats
    assert not any(node == "/v1/models" for document in rendered for node in _walk(document)), (
        "agentgateway 1.3.1 custom providers have no Models format and must not advertise that lane"
    )


def test_route_auth_selectors_authorize_only_the_declared_client_matrix(
    rendered: tuple[Manifest, ...],
    managed_rendered: tuple[Manifest, ...],
) -> None:
    for environment, documents in {
        "local": rendered,
        "managed": managed_rendered,
    }.items():
        route_clients = _ROUTE_CLIENTS_BY_ENVIRONMENT[environment]
        policies = [document for document in documents if document.get("kind") == "AgentgatewayPolicy"]
        auth_policies: list[Manifest] = []
        for policy in policies:
            spec = policy["spec"]
            assert isinstance(spec, dict)
            traffic: object = spec.get("traffic", {})
            assert isinstance(traffic, dict)
            if "apiKeyAuthentication" in traffic:
                auth_policies.append(policy)
        assert len(auth_policies) == len(route_clients)

        expected_clients = set().union(*route_clients.values())
        client_labels: dict[str, object] = {}
        for document in documents:
            if document.get("kind") != "ExternalSecret" or document["metadata"]["name"] not in expected_clients:
                continue
            spec = document["spec"]
            assert isinstance(spec, dict)
            target: object = spec.get("target")
            assert isinstance(target, dict)
            template: object = target.get("template")
            assert isinstance(template, dict)
            metadata: object = template.get("metadata")
            assert isinstance(metadata, dict)
            labels = metadata.get("labels")
            assert isinstance(labels, dict)
            assert all(isinstance(key, str) and isinstance(value, str) for key, value in labels.items())
            client_labels[document["metadata"]["name"]] = labels
        assert set(client_labels) == expected_clients

        selectors: dict[str, object] = {}
        for policy in auth_policies:
            route_name = policy["metadata"]["name"].removesuffix("-client-auth")
            policy_spec = policy["spec"]
            assert isinstance(policy_spec, dict)
            assert policy_spec.get("targetRefs") == [
                {
                    "group": "gateway.networking.k8s.io",
                    "kind": "HTTPRoute",
                    "name": route_name,
                }
            ]
            traffic: object = policy_spec.get("traffic")
            assert isinstance(traffic, dict)
            auth: object = traffic.get("apiKeyAuthentication")
            assert isinstance(auth, dict)
            assert auth.get("mode") == "Strict"
            route = route_name.removeprefix(f"{_GATEWAY_NAME}-")
            assert auth.get("secretSelector") == {"matchLabels": {f"{_ROUTE_SELECTOR_PREFIX}{route}": "true"}}
            assert "secretRef" not in auth
            expected_header = "x-api-key" if route == "messages" else "Authorization"
            expected_header_config = {"name": expected_header}
            if expected_header == "Authorization":
                expected_header_config["prefix"] = "Bearer "
            assert auth.get("location") == {"header": expected_header_config}
            selectors[route_name] = auth.get("secretSelector")

        assert set(selectors) == set(route_clients)
        actual_matrix = {
            route: {secret for secret, labels in client_labels.items() if _matches_selector(labels, selectors[route])}
            for route in selectors
        }
        assert actual_matrix == route_clients
        assert all(
            not _matches_selector(labels, selectors[route])
            for route, clients in route_clients.items()
            if not clients
            for labels in client_labels.values()
        ), "a client key must not authorize a route that its purpose did not declare"

        expected_provider_secrets = _PROVIDER_SECRETS_BY_ENVIRONMENT[environment]
        sensitive_secret_names = expected_provider_secrets | {
            "nohiki-model-egress-tls",
            "nohiki-model-egress-ca",
        }
        sensitive_labels: list[object] = []
        for document in documents:
            if document.get("kind") != "ExternalSecret" or document["metadata"]["name"] not in sensitive_secret_names:
                continue
            spec = document["spec"]
            assert isinstance(spec, dict)
            target: object = spec.get("target")
            assert isinstance(target, dict)
            template: object = target.get("template", {})
            assert isinstance(template, dict)
            metadata: object = template.get("metadata", {})
            assert isinstance(metadata, dict)
            labels = metadata.get("labels", {})
            assert isinstance(labels, dict)
            assert all(isinstance(key, str) and isinstance(value, str) for key, value in labels.items())
            sensitive_labels.append(labels)
        assert all(
            not _matches_selector(labels, selector) for labels in sensitive_labels for selector in selectors.values()
        )

        provider_external_secrets = {
            (document)["metadata"]["name"]
            for document in documents
            if document.get("kind") == "ExternalSecret"
            and (document.get("metadata", {})).get("name", "").startswith(f"{_GATEWAY_NAME}-")
            and (document)["metadata"]["name"] not in expected_clients
            and (document)["metadata"]["name"] not in {"nohiki-model-egress-tls", "nohiki-model-egress-ca"}
        }
        assert provider_external_secrets == expected_provider_secrets
        assert not any(
            document.get("kind") == "Secret" and (document.get("metadata", {})).get("name") in _PROVIDER_SECRETS
            for document in documents
        ), "provider credentials must come from ExternalSecret, never a rendered Secret"

        providers: list[dict[object, object]] = []
        for backend in documents:
            if backend.get("kind") != "AgentgatewayBackend":
                continue
            spec = backend["spec"]
            assert isinstance(spec, dict)
            ai: object = spec.get("ai")
            assert isinstance(ai, dict)
            groups = ai.get("groups")
            assert isinstance(groups, list)
            for group in groups:
                assert isinstance(group, dict)
                group_providers = group.get("providers")
                assert isinstance(group_providers, list)
                for provider in group_providers:
                    assert isinstance(provider, dict)
                    providers.append({key: provider.get(key) for key in provider})
        provider_secret_names: set[str] = set()
        for provider in providers:
            policies = provider.get("policies")
            assert isinstance(policies, dict)
            auth: object = policies.get("auth")
            assert isinstance(auth, dict)
            secret_ref: object = auth.get("secretRef")
            assert isinstance(secret_ref, dict)
            secret_name = secret_ref.get("name")
            assert isinstance(secret_name, str)
            provider_secret_names.add(secret_name)
        assert provider_secret_names == expected_provider_secrets
        if environment == "managed":
            anthropic = next(provider for provider in providers if "anthropic" in provider)
            policies = anthropic.get("policies")
            assert isinstance(policies, dict)
            auth: object = policies.get("auth")
            assert isinstance(auth, dict)
            assert auth.get("location") == {"header": {"name": "x-api-key"}}


def test_api_key_auth_prefixes_include_the_header_separator(
    rendered: tuple[Manifest, ...],
    managed_rendered: tuple[Manifest, ...],
) -> None:
    for documents in (rendered, managed_rendered):
        prefixes = [
            prefix
            for document in documents
            if document.get("kind") == "AgentgatewayPolicy"
            for spec in [document.get("spec")]
            if isinstance(spec, dict)
            for traffic in [spec.get("traffic")]
            if isinstance(traffic, dict)
            for auth in [traffic.get("apiKeyAuthentication")]
            if isinstance(auth, dict)
            for location in [auth.get("location")]
            if isinstance(location, dict)
            for header in [location.get("header")]
            if isinstance(header, dict)
            for prefix in [header.get("prefix")]
            if isinstance(prefix, str)
        ]
        assert prefixes
        assert all(prefix.strip() and prefix.endswith(" ") for prefix in prefixes)


def test_client_route_labels_are_declared_per_client_and_emit_the_responses_only_matrix(
    rendered: tuple[Manifest, ...],
) -> None:
    values = load_mapping(_CHART / "values.yaml")
    global_values = values["global"]
    assert isinstance(global_values, dict)
    model_egress = global_values.get("modelEgress")
    assert isinstance(model_egress, dict)
    client_values = model_egress.get("clients")
    assert isinstance(client_values, list)
    clients: dict[str, dict[object, object]] = {}
    for client in client_values:
        assert isinstance(client, dict)
        name = client.get("name")
        assert isinstance(name, str)
        clients[name] = {key: client.get(key) for key in client}
    assert clients == {
        "doc-content-service": {
            "name": "doc-content-service",
            "secretName": "nohiki-model-egress-client-doc-content",
            "secretKey": "doc-content",
            "allowedRoutes": ["responses"],
        },
        "job-ingest-enrichment-service": {
            "name": "job-ingest-enrichment-service",
            "secretName": "nohiki-model-egress-client-job-ingest-enrichment",
            "secretKey": "job-ingest-enrichment",
            "allowedRoutes": ["responses"],
        },
    }

    client_secrets: dict[str, object] = {}
    for document in rendered:
        if document.get("kind") != "ExternalSecret" or not document["metadata"]["name"].startswith(
            "nohiki-model-egress-client-"
        ):
            continue
        spec = document["spec"]
        assert isinstance(spec, dict)
        target: object = spec.get("target")
        assert isinstance(target, dict)
        template: object = target.get("template")
        assert isinstance(template, dict)
        metadata: object = template.get("metadata")
        assert isinstance(metadata, dict)
        client_secrets[document["metadata"]["name"]] = metadata.get("labels")
    expected_client_secrets: dict[str, object] = {}
    for client in clients.values():
        secret_name = client.get("secretName")
        assert isinstance(secret_name, str)
        expected_client_secrets[secret_name] = {"nohiki.io/model-egress-route-responses": "true"}
    assert client_secrets == expected_client_secrets


@pytest.mark.parametrize("allowed_routes", [[], ["unknown"]])
def test_client_allowed_routes_must_be_nonempty_and_reference_a_declared_backend(
    tmp_path: Path,
    allowed_routes: list[str],
) -> None:
    clients = [
        {
            "name": "doc-content-service",
            "secretName": "nohiki-model-egress-client-doc-content",
            "secretKey": "doc-content",
            "allowedRoutes": allowed_routes,
        },
        {
            "name": "job-ingest-enrichment-service",
            "secretName": "nohiki-model-egress-client-job-ingest-enrichment",
            "secretKey": "job-ingest-enrichment",
            "allowedRoutes": ["responses"],
        },
        {
            "name": "job-correlation-evaluation-service",
            "secretName": "nohiki-model-egress-client-job-correlation-evaluation",
            "secretKey": "job-correlation-evaluation",
            "allowedRoutes": ["responses"],
        },
    ]
    override = tmp_path / "invalid-client-routes.yaml"
    override.write_text(
        yaml.safe_dump({"global": {"modelEgress": {"clients": clients}}}),
        encoding="utf-8",
    )
    with pytest.raises(subprocess.CalledProcessError) as error:
        _render(values=override)
    assert "doc-content-service" in error.value.stderr


def test_chart_model_mapping_and_rendered_deployments_match_luna_sol_policy(
    rendered: tuple[Manifest, ...],
) -> None:
    expected: dict[str, tuple[tuple[str, str], dict[str, tuple[str, str]]]] = {
        "job-ingest-enrichment-service": (
            ("openai:gpt-5.6-luna", "medium"),
            {
                "extraction": ("openai:gpt-5.6-luna", "medium"),
                "skill_clarification": ("openai:gpt-5.6-luna", "medium"),
            },
        ),
        "doc-content-service": (
            ("openai:gpt-5.6-sol", "high"),
            {"doc_tailoring": ("openai:gpt-5.6-sol", "high")},
        ),
    }
    compose_document = load_mapping(_ROOT / "infra/compose/docker-compose.yml")
    compose = compose_document["services"]
    assert isinstance(compose, dict)
    compose_expectations = {
        "nohiki-svc-job-ingest-enrichment": {
            "JOB_INGEST_ENRICHMENT_LLM__PROVIDER__MODELS__0__MODEL": "openai:gpt-5.6-luna",
            "JOB_INGEST_ENRICHMENT_LLM__PROVIDER__MODELS__0__REASONING_EFFORT": "medium",
        },
        "nohiki-svc-doc-content": {
            "DOC_CONTENT_LLM__PROVIDER__MODELS__0__MODEL": "openai:gpt-5.6-sol",
            "DOC_CONTENT_LLM__PROVIDER__MODELS__0__REASONING_EFFORT": "high",
            "DOC_CONTENT_LLM__CHAINS__DOC_TAILORING__MODELS__0__MODEL": "openai:gpt-5.6-sol",
            "DOC_CONTENT_LLM__CHAINS__DOC_TAILORING__MODELS__0__REASONING_EFFORT": "high",
        },
    }
    for service, expectation in compose_expectations.items():
        service_values = compose.get(service)
        assert isinstance(service_values, dict)
        environment = service_values.get("environment")
        assert isinstance(environment, dict)
        assert {key: environment.get(key) for key in expectation} == expectation
    for service, ((provider_model, provider_effort), chains) in expected.items():
        values_document = load_mapping(_CHART / "charts" / service / "values.yaml")
        values = values_document["llm"]
        assert isinstance(values, dict)
        provider = values.get("provider")
        assert isinstance(provider, dict)
        assert provider.get("models") == [{"model": provider_model, "reasoningEffort": provider_effort}]
        assert "reasoningEffort" not in provider
        values_chains = values.get("chains")
        assert isinstance(values_chains, dict)
        assert set(values_chains) == set(chains)
        for chain, (model, effort) in chains.items():
            chain_values = values_chains.get(chain)
            assert isinstance(chain_values, dict)
            assert chain_values.get("models") == [{"model": model, "reasoningEffort": effort}]
            assert "reasoningEffort" not in chain_values

        env = _container_env(_named(rendered, "Deployment", f"nohiki-{service}"))
        prefix = "JOB_INGEST_ENRICHMENT_" if service.startswith("job-") else "DOC_CONTENT_"
        assert env[f"{prefix}LLM__PROVIDER__MODELS__0__MODEL"] == provider_model
        assert env[f"{prefix}LLM__PROVIDER__MODELS__0__REASONING_EFFORT"] == provider_effort
        assert f"{prefix}LLM__PROVIDER__REASONING_EFFORT" not in env
        model_keys = {key for key in env if key.startswith(f"{prefix}LLM__") and key.endswith("__MODEL")}
        expected_model_keys = {f"{prefix}LLM__PROVIDER__MODELS__0__MODEL"}
        for chain, (model, effort) in chains.items():
            chain_key = chain.upper()
            expected_model_keys.add(f"{prefix}LLM__CHAINS__{chain_key}__MODELS__0__MODEL")
            assert env[f"{prefix}LLM__CHAINS__{chain_key}__MODELS__0__MODEL"] == model
            assert env[f"{prefix}LLM__CHAINS__{chain_key}__MODELS__0__REASONING_EFFORT"] == effort
            assert f"{prefix}LLM__CHAINS__{chain_key}__REASONING_EFFORT" not in env
        assert model_keys == expected_model_keys


def test_correlation_deployment_has_no_dead_llm_configuration_or_secret_mounts(
    rendered: tuple[Manifest, ...],
) -> None:
    deployment = _named(rendered, "Deployment", "nohiki-job-correlation-evaluation-service")
    spec = deployment["spec"]
    assert isinstance(spec, dict)
    template: object = spec.get("template")
    assert isinstance(template, dict)
    pod_spec: object = template.get("spec")
    assert isinstance(pod_spec, dict)
    containers: object = pod_spec.get("containers")
    assert isinstance(containers, list)
    env_names: set[str] = set()
    for container in containers:
        assert isinstance(container, dict)
        env: object = container.get("env", [])
        assert isinstance(env, list)
        for item in env:
            assert isinstance(item, dict)
            name = item.get("name")
            assert isinstance(name, str)
            env_names.add(name)
    assert not any(name.startswith("JOB_CORRELATION_EVAL_LLM__") for name in env_names)
    assert not any(secret.startswith("nohiki-model-egress-client-") for secret, _ in _secret_refs(pod_spec))
    assert not any(
        isinstance(node, str) and ("model-egress" in node or node == "/run/secrets/llm") for node in _walk(pod_spec)
    )

    values = load_mapping(_CHART / "charts/job-correlation-evaluation-service/values.yaml")
    llm = values["llm"]
    assert isinstance(llm, dict)
    assert llm.get("enabled") is False
    secrets = values["secrets"]
    assert isinstance(secrets, dict)
    assert secrets.get("llm", False) is False


def test_provider_tls_health_priority_and_timeouts_have_only_supported_fields(
    rendered: tuple[Manifest, ...],
    managed_rendered: tuple[Manifest, ...],
) -> None:
    expected_health = {
        "unhealthyCondition": "response.code >= 500 || response.code == 429",
        "eviction": {
            "consecutiveFailures": 3,
            "duration": "30s",
            "restoreHealth": 50,
        },
    }
    for environment, documents in {
        "local": rendered,
        "managed": managed_rendered,
    }.items():
        backends = [document for document in documents if document.get("kind") == "AgentgatewayBackend"]
        for backend in backends:
            spec = backend["spec"]
            assert isinstance(spec, dict)
            ai: object = spec.get("ai")
            assert isinstance(ai, dict)
            groups = ai.get("groups")
            assert isinstance(groups, list)
            assert groups
            for group in groups:
                assert isinstance(group, dict)
                providers = group.get("providers")
                assert isinstance(providers, list)
                assert providers
                for provider in providers:
                    assert isinstance(provider, dict)
                    policies = provider.get("policies")
                    assert isinstance(policies, dict)
                    tls: object = policies.get("tls")
                    assert isinstance(tls, dict)
                    sni = tls.get("sni")
                    subject_alt_names = tls.get("verifySubjectAltNames")
                    assert isinstance(sni, str)
                    assert isinstance(subject_alt_names, list)
                    assert sni in subject_alt_names
                    assert policies.get("http") == {"requestTimeout": "180s"}
                    assert policies.get("tcp") == {"connectTimeout": "10s"}

        health_policies: dict[str, object] = {}
        for policy in documents:
            if policy.get("kind") != "AgentgatewayPolicy":
                continue
            spec = policy["spec"]
            assert isinstance(spec, dict)
            backend: object = spec.get("backend")
            if backend is None:
                continue
            assert isinstance(backend, dict)
            target_refs: object = spec.get("targetRefs")
            assert isinstance(target_refs, list)
            target_ref = target_refs[0]
            assert isinstance(target_ref, dict)
            target_name = target_ref.get("name")
            assert isinstance(target_name, str)
            health_policies[target_name] = backend.get("health")
        assert set(health_policies) == set(_ROUTE_PATHS_BY_ENVIRONMENT[environment])
        assert all(health == expected_health for health in health_policies.values())

        unsupported = {
            "insecureSkipVerify",
            "perTryTimeout",
            "budget",
            "dollarBudget",
            "tokenBudget",
        }
        gateway_resources = [
            document
            for document in documents
            if document.get("kind") in {"AgentgatewayBackend", "AgentgatewayPolicy", "AgentgatewayParameters"}
        ]
        assert not any(
            isinstance(node, dict) and unsupported & node.keys()
            for document in gateway_resources
            for node in _walk(document)
        )

    for document in rendered:
        if document.get("kind") != "AgentgatewayPolicy":
            continue
        spec = document["spec"]
        assert isinstance(spec, dict)
        traffic: object = spec.get("traffic", {})
        assert not any(isinstance(node, dict) and ("retry" in node or "rateLimit" in node) for node in _walk(traffic))


def test_environment_rate_limits_are_exact_schema_valid_and_bounded(
    rendered: tuple[Manifest, ...],
    managed_rendered: tuple[Manifest, ...],
) -> None:
    policy_schema = _schema(_agentgateway_crds()["AgentgatewayPolicy"], "v1alpha1")
    local_traffic_policies: dict[str, Manifest] = {}
    for policy in rendered:
        if policy.get("kind") != "AgentgatewayPolicy" or not policy["metadata"]["name"].endswith("-traffic"):
            continue
        spec = policy["spec"]
        assert isinstance(spec, dict)
        target_refs: object = spec.get("targetRefs")
        assert isinstance(target_refs, list)
        target_ref = target_refs[0]
        assert isinstance(target_ref, dict)
        target_name = target_ref.get("name")
        assert isinstance(target_name, str)
        local_traffic_policies[target_name] = policy
        traffic: object = spec.get("traffic")
        assert isinstance(traffic, dict)
        assert "rateLimit" not in traffic
    assert set(local_traffic_policies) == set(_ROUTE_PATHS_BY_ENVIRONMENT["local"])

    managed_traffic_policies: dict[str, Manifest] = {}
    for policy in managed_rendered:
        if policy.get("kind") != "AgentgatewayPolicy" or not policy["metadata"]["name"].endswith("-traffic"):
            continue
        spec = policy["spec"]
        assert isinstance(spec, dict)
        target_refs: object = spec.get("targetRefs")
        assert isinstance(target_refs, list)
        target_ref = target_refs[0]
        assert isinstance(target_ref, dict)
        target_name = target_ref.get("name")
        assert isinstance(target_name, str)
        managed_traffic_policies[target_name] = policy
    assert set(managed_traffic_policies) == set(_MANAGED_RATE_LIMITS)
    for route, expected in _MANAGED_RATE_LIMITS.items():
        policy = managed_traffic_policies[route]
        jsonschema.Draft202012Validator(policy_schema).validate(policy)
        spec = policy["spec"]
        assert isinstance(spec, dict)
        traffic: object = spec.get("traffic")
        assert isinstance(traffic, dict)
        assert traffic.get("rateLimit") == {"local": expected}
        for item in expected:
            limit = item.get("requests", item.get("tokens", 0))
            burst = item.get("burst")
            assert isinstance(limit, int)
            assert isinstance(burst, int)
            assert 0 < limit <= 120_000
            assert 0 < burst <= 20_000
        assert "retry" not in traffic


def test_apps_receive_gateway_url_client_key_and_ca_but_no_provider_or_tls_key(
    rendered: tuple[Manifest, ...],
) -> None:
    deployments = {
        (document)["metadata"]["name"]: document for document in rendered if document.get("kind") == "Deployment"
    }
    client_readers: dict[str, set[str]] = {secret: set() for secret, _ in _CLIENT_SECRETS.values()}
    for name, (client_secret, client_key) in _CLIENT_SECRETS.items():
        deployment = deployments[name]
        spec = deployment["spec"]
        assert isinstance(spec, dict)
        template: object = spec.get("template")
        assert isinstance(template, dict)
        pod_spec: object = template.get("spec")
        assert isinstance(pod_spec, dict)
        refs = _secret_refs(pod_spec)
        gateway_refs = {ref for ref in refs if ref[0].startswith("nohiki-model-egress")}
        assert gateway_refs == {
            (client_secret, client_key),
            ("nohiki-model-egress-ca", "ca.crt"),
        }, name
        for secret, _ in refs:
            if secret in client_readers:
                client_readers[secret].add(name)
        assert not ({secret for secret, _ in refs} & _PROVIDER_SECRETS), name
        assert ("nohiki-model-egress-tls", "tls.key") not in refs, name

        env = _container_env(deployment)
        base_urls = [value for env_name, value in env.items() if env_name.endswith("__BASE_URL")]
        assert base_urls, name
        assert set(base_urls) <= {
            _GATEWAY_ORIGIN,
            f"{_GATEWAY_ORIGIN}/v1",
        }, name
        models = [value for env_name, value in env.items() if env_name.endswith("__MODEL")]
        assert models, name
        model_env_names = {env_name for env_name in env if env_name.endswith("__MODEL")}
        health_env = {env_name: value for env_name, value in env.items() if env_name.endswith("__HEALTH_URL")}
        assert model_env_names, name
        assert set(health_env) == {
            f"{model_name.removesuffix('__MODEL')}__HEALTH_URL" for model_name in model_env_names
        }, name
        assert set(health_env.values()) == {f"{_GATEWAY_ORIGIN}/healthz"}, name
        tls_env = {env_name: value for env_name, value in env.items() if env_name.endswith("__TLS_CA_FILE")}
        assert set(tls_env) == {
            f"{model_name.removesuffix('__MODEL')}__TLS_CA_FILE" for model_name in model_env_names
        }, name
        assert set(tls_env.values()) == {"/etc/nohiki/model-egress/ca.crt"}, name
        assert not {"SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"} & set(env), name
    assert client_readers == {secret: {deployment} for deployment, (secret, _) in _CLIENT_SECRETS.items()}
    assert not any(node == "nohiki-model-egress-client" for document in rendered for node in _walk(document)), (
        "the shared model-egress client Secret must not remain"
    )


def test_non_llm_skill_graph_never_joins_the_gateway_lane(
    rendered: tuple[Manifest, ...],
) -> None:
    deployment = _named(rendered, "Deployment", "nohiki-skill-graph-service")
    spec = deployment["spec"]
    assert isinstance(spec, dict)
    template: object = spec.get("template")
    assert isinstance(template, dict)
    pod_spec: object = template.get("spec")
    assert isinstance(pod_spec, dict)
    refs = _secret_refs(pod_spec)
    assert not any(secret == "nohiki-llm-runtime" or secret.startswith("nohiki-model-egress") for secret, _ in refs)
    env_names = set(_container_env(deployment))
    assert not any("LLM__" in name for name in env_names)
    policy = _named(rendered, "NetworkPolicy", "nohiki-skill-graph-service")
    assert not any(node == _GATEWAY_NAME for node in _walk(policy))


def test_legacy_disable_value_cannot_bypass_gateway_cutover(
    rendered: tuple[Manifest, ...],
) -> None:
    false_override = _render(model_egress_enabled=False)
    gateway_kinds = {
        "AgentgatewayBackend",
        "AgentgatewayParameters",
        "AgentgatewayPolicy",
        "Gateway",
        "HTTPRoute",
    }
    expected_gateway_resources = {
        (document["kind"], (document)["metadata"]["name"])
        for document in rendered
        if document.get("kind") in gateway_kinds
        and (document.get("metadata", {})).get("name", "").startswith(_GATEWAY_NAME)
    }
    actual_gateway_resources = {
        (document["kind"], (document)["metadata"]["name"])
        for document in false_override
        if document.get("kind") in gateway_kinds
        and (document.get("metadata", {})).get("name", "").startswith(_GATEWAY_NAME)
    }
    assert actual_gateway_resources == expected_gateway_resources

    for name, (client_secret, client_key) in _CLIENT_SECRETS.items():
        deployment = _named(false_override, "Deployment", name)
        spec = deployment["spec"]
        assert isinstance(spec, dict)
        template: object = spec.get("template")
        assert isinstance(template, dict)
        pod_spec: object = template.get("spec")
        assert isinstance(pod_spec, dict)
        refs = _secret_refs(pod_spec)
        assert (client_secret, client_key) in refs, name
        assert ("nohiki-model-egress-ca", "ca.crt") in refs, name
        assert not any(secret == "nohiki-llm-runtime" for secret, _ in refs), name


def test_network_policy_allows_clients_only_to_gateway_and_gateway_only_to_control_plane_and_providers(
    rendered: tuple[Manifest, ...],
) -> None:
    policies = [document for document in rendered if document.get("kind") == "NetworkPolicy"]
    gateway = _named(rendered, "NetworkPolicy", _GATEWAY_NAME)
    gateway_spec = gateway["spec"]
    assert isinstance(gateway_spec, dict)
    pod_selector: object = gateway_spec.get("podSelector")
    assert isinstance(pod_selector, dict)
    assert pod_selector.get("matchLabels") == {"gateway.networking.k8s.io/gateway-name": _GATEWAY_NAME}
    ingress_value: object = gateway_spec.get("ingress")
    assert isinstance(ingress_value, list)
    ingress: list[dict[object, object]] = []
    for rule in ingress_value:
        assert isinstance(rule, dict)
        ingress.append({key: rule.get(key) for key in rule})
    assert len(ingress) == 2
    client_ingress = [rule for rule in ingress if rule.get("ports") == [{"port": 8443, "protocol": "TCP"}]]
    assert len(client_ingress) == 1
    client_peers = client_ingress[0].get("from")
    assert isinstance(client_peers, list)
    actual_client_selectors: set[tuple[tuple[str, str], ...]] = set()
    for peer in client_peers:
        assert isinstance(peer, dict)
        selector = peer.get("podSelector")
        assert isinstance(selector, dict)
        match_labels = selector.get("matchLabels")
        assert isinstance(match_labels, dict)
        assert all(isinstance(key, str) and isinstance(value, str) for key, value in match_labels.items())
        actual_client_selectors.add(
            tuple(
                sorted(
                    (key, value)
                    for key, value in match_labels.items()
                    if isinstance(key, str) and isinstance(value, str)
                )
            )
        )
    assert actual_client_selectors == {
        (
            ("app.kubernetes.io/instance", "nohiki"),
            ("app.kubernetes.io/name", name.removeprefix("nohiki-")),
        )
        for name in _CLIENT_SECRETS
    }
    metrics_ingress = [rule for rule in ingress if rule.get("ports") == [{"port": 15020, "protocol": "TCP"}]]
    assert metrics_ingress == [
        {
            "from": [
                {
                    "podSelector": {
                        "matchLabels": {
                            "app.kubernetes.io/name": "prometheus",
                            "operator.prometheus.io/name": "nohiki-kube-prometheus-stack-prometheus",
                        }
                    }
                }
            ],
            "ports": [{"port": 15020, "protocol": "TCP"}],
        }
    ]
    egress_value: object = gateway_spec.get("egress")
    assert isinstance(egress_value, list)
    egress: list[dict[object, object]] = []
    for rule in egress_value:
        assert isinstance(rule, dict)
        egress.append({key: rule.get(key) for key in rule})
    gateway_otlp_rules = [rule for rule in egress if rule.get("ports") == [{"port": 4317, "protocol": "TCP"}]]
    assert gateway_otlp_rules == [
        {
            "to": [{"podSelector": {"matchLabels": {"app.kubernetes.io/instance": "nohiki.nohiki-collector"}}}],
            "ports": [{"port": 4317, "protocol": "TCP"}],
        }
    ], "non-production OTLP egress must select the local collector pods exactly"

    gateway_ip_rules: list[dict[object, object]] = []
    for rule in egress:
        destinations = rule.get("to", [])
        assert isinstance(destinations, list)
        if any(isinstance(peer, dict) and "ipBlock" in peer for peer in destinations):
            gateway_ip_rules.append(rule)
    assert gateway_ip_rules == [
        {
            "to": [
                {
                    "ipBlock": {
                        "cidr": "0.0.0.0/0",
                        "except": [
                            "10.0.0.0/8",
                            "100.64.0.0/10",
                            "127.0.0.0/8",
                            "169.254.0.0/16",
                            "172.16.0.0/12",
                            "192.168.0.0/16",
                        ],
                    }
                }
            ],
            "ports": [{"port": 443, "protocol": "TCP"}],
        }
    ], "only the gateway may reach public provider HTTPS, with private/LAN ranges excluded"
    client_selector = {"gateway.networking.k8s.io/gateway-name": _GATEWAY_NAME}
    for name in _CLIENT_SECRETS:
        deployment = _named(rendered, "Deployment", name)
        spec = deployment["spec"]
        assert isinstance(spec, dict)
        template: object = spec.get("template")
        assert isinstance(template, dict)
        metadata: object = template.get("metadata")
        assert isinstance(metadata, dict)
        labels = metadata.get("labels")
        assert isinstance(labels, dict)
        selected: list[Manifest] = []
        for policy in policies:
            policy_spec = policy["spec"]
            assert isinstance(policy_spec, dict)
            selector: object = policy_spec.get("podSelector")
            if _matches_selector(labels, selector):
                selected.append(policy)
        rules: list[dict[object, object]] = []
        for policy in selected:
            policy_spec = policy["spec"]
            assert isinstance(policy_spec, dict)
            policy_rules: object = policy_spec.get("egress", [])
            assert isinstance(policy_rules, list)
            for rule in policy_rules:
                assert isinstance(rule, dict)
                rules.append({key: rule.get(key) for key in rule})
        gateway_rules: list[dict[object, object]] = []
        for rule in rules:
            destinations = rule.get("to", [])
            assert isinstance(destinations, list)
            for peer in destinations:
                assert isinstance(peer, dict)
                selector = peer.get("podSelector", {})
                assert isinstance(selector, dict)
                if selector.get("matchLabels") == client_selector:
                    gateway_rules.append(rule)
                    break
        assert gateway_rules == [
            {
                "to": [{"podSelector": {"matchLabels": client_selector}}],
                "ports": [{"port": 8443, "protocol": "TCP"}],
            }
        ], name
        public_or_lan_model_rules: list[dict[object, object]] = []
        for rule in rules:
            destinations = rule.get("to", [])
            ports = rule.get("ports", [])
            assert isinstance(destinations, list)
            assert isinstance(ports, list)
            has_model_port = any(isinstance(port, dict) and port.get("port") in {443, 8317} for port in ports)
            for peer in destinations:
                assert isinstance(peer, dict)
                ip_block = peer.get("ipBlock", {})
                assert isinstance(ip_block, dict)
                if ip_block.get("cidr") in {"0.0.0.0/0", "192.168.1.200/32"} and has_model_port:
                    public_or_lan_model_rules.append(rule)
                    break
        if name == "nohiki-job-ingest-enrichment-service":
            assert public_or_lan_model_rules == [
                {
                    "to": [
                        {
                            "ipBlock": {
                                "cidr": "0.0.0.0/0",
                                "except": [
                                    "10.0.0.0/8",
                                    "100.64.0.0/10",
                                    "127.0.0.0/8",
                                    "169.254.0.0/16",
                                    "172.16.0.0/12",
                                    "192.168.0.0/16",
                                ],
                            }
                        }
                    ],
                    "ports": [{"port": 443, "protocol": "TCP"}],
                }
            ], name
        else:
            assert public_or_lan_model_rules == [], name


def test_configuration_only_override_switches_provider_priority_ca_and_model(
    tmp_path: Path,
) -> None:
    values = load_mapping(_CHART / "values.yaml")
    global_values = values["global"]
    assert isinstance(global_values, dict)
    model_egress_value = copy.deepcopy(global_values.get("modelEgress"))
    assert isinstance(model_egress_value, dict)
    model_egress: dict[object, object] = {key: model_egress_value.get(key) for key in model_egress_value}
    backend_values = model_egress.get("backends")
    assert isinstance(backend_values, list)
    backends: list[object] = list(backend_values)
    model_egress["backends"] = backends
    primary_backend_value = backends[0]
    assert isinstance(primary_backend_value, dict)
    primary_backend: dict[object, object] = {key: primary_backend_value.get(key) for key in primary_backend_value}
    backends[0] = primary_backend
    group_values = primary_backend.get("groups")
    assert isinstance(group_values, list)
    override_groups: list[object] = list(group_values)
    primary_backend["groups"] = override_groups
    override_groups.append(
        {
            "providers": [
                {
                    "name": "openai-failover",
                    "type": "openai",
                    "credentialName": "openai",
                    "path": "/v1/responses",
                    "tls": {
                        "sni": "api.openai.com",
                        "verifySubjectAltNames": ["api.openai.com"],
                        "caConfigMapName": "model-provider-ca",
                    },
                }
            ]
        }
    )
    override = tmp_path / "provider-switch.yaml"
    override.write_text(
        yaml.safe_dump(
            {
                "global": {"modelEgress": model_egress},
                "doc-content-service": {"llm": {"provider": {"models": [{"model": "openrouter:openai/gpt-4.1"}]}}},
            }
        ),
        encoding="utf-8",
    )
    switched = _render(values=override)
    backend = _named(switched, "AgentgatewayBackend", "nohiki-model-egress-responses")
    spec = backend["spec"]
    assert isinstance(spec, dict)
    ai: object = spec.get("ai")
    assert isinstance(ai, dict)
    groups = ai.get("groups")
    assert isinstance(groups, list)
    assert len(groups) == 2
    failover_group = groups[1]
    assert isinstance(failover_group, dict)
    failover = failover_group.get("providers")
    assert isinstance(failover, list)
    failover_provider = failover[0]
    assert isinstance(failover_provider, dict)
    assert failover_provider.get("name") == "openai-failover"
    failover_policies = failover_provider.get("policies")
    assert isinstance(failover_policies, dict)
    auth: object = failover_policies.get("auth")
    assert isinstance(auth, dict)
    assert auth.get("secretRef") == {"name": "nohiki-model-egress-openai"}
    tls: object = failover_policies.get("tls")
    assert isinstance(tls, dict)
    assert tls.get("caCertificateRefs") == [{"name": "model-provider-ca"}]
    deployment = _named(switched, "Deployment", "nohiki-doc-content-service")
    env = _container_env(deployment)
    assert env["DOC_CONTENT_LLM__PROVIDER__MODELS__0__MODEL"] == "openrouter:openai/gpt-4.1"
    assert all(value != "openai-failover" for value in env.values())


def test_gateway_metrics_service_monitor_targets_only_agentgateway_data_plane(
    rendered: tuple[Manifest, ...],
) -> None:
    monitor = _named(rendered, "ServiceMonitor", "agentgateway-proxy")
    assert (monitor)["metadata"]["labels"] == {
        "app.kubernetes.io/name": "agentgateway-proxy",
        "app.kubernetes.io/instance": "nohiki",
        "app.kubernetes.io/component": "model-egress",
        "app.kubernetes.io/part-of": "nohiki",
        "release": "nohiki",
    }
    assert (monitor)["spec"] == {
        "selector": {"matchLabels": {"gateway.networking.k8s.io/gateway-class-name": "agentgateway"}},
        "namespaceSelector": {"matchNames": ["nohiki"]},
        "endpoints": [
            {
                "port": "metrics",
                "path": "/metrics",
                "interval": "15s",
                "scrapeTimeout": "10s",
            }
        ],
    }

    prometheus_resources = [document for document in rendered if document.get("kind") == "Prometheus"]
    assert len(prometheus_resources) == 1
    prometheus_spec = prometheus_resources[0]["spec"]
    assert isinstance(prometheus_spec, dict)
    selector: object = prometheus_spec.get("serviceMonitorSelector")
    monitors = [document for document in rendered if document.get("kind") == "ServiceMonitor"]
    assert monitor in monitors
    assert monitors
    unmatched = {
        (item)["metadata"]["name"]
        for item in monitors
        if not _matches_selector(
            (item)["metadata"].get("labels", {}),
            selector,
        )
    }
    assert unmatched == set(), (
        f"Prometheus selector {selector!r} does not select emitted ServiceMonitors: {sorted(unmatched)}"
    )


def test_llm_dashboard_queries_gateway_requests_tokens_latency_and_errors() -> None:
    dashboard_manifest = load_mapping(_ROOT / "infra/k8s/observability/base/grafana/dashboards/nohiki-llm.yaml")
    assert dashboard_manifest["kind"] == "GrafanaDashboard"
    dashboard_spec = dashboard_manifest["spec"]
    assert isinstance(dashboard_spec, dict)
    dashboard_json = dashboard_spec.get("json")
    assert isinstance(dashboard_json, str)
    dashboard = json.loads(dashboard_json)
    assert isinstance(dashboard, dict)
    canonical = load_mapping(_ROOT / "infra/shared/dashboards/nohiki-llm.json")
    assert dashboard == canonical
    assert dashboard.get("uid") == "nohiki-llm"
    panel_values = dashboard.get("panels")
    assert isinstance(panel_values, list)
    panels: dict[str, dict[object, object]] = {}
    for panel in panel_values:
        assert isinstance(panel, dict)
        title = panel.get("title")
        assert isinstance(title, str)
        panels[title] = dict(panel)
    expected_queries = {
        "Model Gateway Requests": "agentgateway_requests_total",
        "Gateway Tokens by Provider and Model": "agentgateway_gen_ai_client_token_usage_sum",
        "Gateway LLM Request Latency": "agentgateway_gen_ai_server_request_duration_bucket",
        "Gateway Time to First Token": "agentgateway_gen_ai_server_time_to_first_token_bucket",
        "Model Gateway Errors": 'agentgateway_requests_total{status=~"4..|5.."}',
    }
    assert set(expected_queries) <= set(panels)
    for title, metric in expected_queries.items():
        targets = panels[title].get("targets")
        assert isinstance(targets, list)
        assert len(targets) == 1
        target = targets[0]
        assert isinstance(target, dict)
        expression = target.get("expr")
        assert isinstance(expression, str)
        assert metric in expression
        assert target.get("datasource") == {"type": "prometheus", "uid": "mimir"}


def test_local_and_managed_environments_use_distinct_secret_delivery_without_private_defaults() -> None:
    base = load_mapping(_CHART / "values.yaml")
    local = load_mapping(_CHART / "values.local.yaml")
    base_global = base["global"]
    local_global = local["global"]
    assert isinstance(base_global, dict)
    assert isinstance(local_global, dict)
    model_egress = base_global.get("modelEgress")
    assert isinstance(model_egress, dict)
    assert "enabled" not in model_egress
    secrets = local_global.get("secrets")
    assert isinstance(secrets, dict)
    assert secrets.get("inlineSecretsEnabled") is False
    eso = local_global.get("eso", {})
    assert isinstance(eso, dict)
    assert not eso.get("externalSecretsEnabled", False)
    assert model_egress.get("certificateSecretName") == ""
    assert model_egress.get("caSecretName") == ""
    assert "clientSecretName" not in model_egress
    credential_names: set[object] = set()
    backends = model_egress.get("backends")
    assert isinstance(backends, list)
    for backend in backends:
        assert isinstance(backend, dict)
        groups = backend.get("groups")
        assert isinstance(groups, list)
        for group in groups:
            assert isinstance(group, dict)
            providers = group.get("providers")
            assert isinstance(providers, list)
            for provider in providers:
                assert isinstance(provider, dict)
                credential_names.add(provider.get("credentialName"))
    assert credential_names == {"anthropic", "openai", "openrouter"}
    for values_name in ("values.staging.yaml", "values.prod.yaml"):
        managed_document = load_mapping(_CHART / values_name)
        managed = managed_document["global"]
        assert isinstance(managed, dict)
        eso = managed.get("eso")
        assert isinstance(eso, dict)
        assert eso.get("externalSecretsEnabled") is True
        assert managed.get("modelEgress") == {"rateLimitsEnabled": True}, (
            "managed overlays may enable bounded gateway limits but must not inject disable switches, "
            "provider keys, or private endpoints"
        )

    destinations = model_egress.get("destinations")
    assert destinations == [
        {
            "cidr": "0.0.0.0/0",
            "except": [
                "10.0.0.0/8",
                "100.64.0.0/10",
                "127.0.0.0/8",
                "169.254.0.0/16",
                "172.16.0.0/12",
                "192.168.0.0/16",
            ],
            "port": 443,
        }
    ]
