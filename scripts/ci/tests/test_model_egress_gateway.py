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

type Manifest = dict[str, object]

_ROOT = Path(__file__).resolve().parents[3]
_CHART = _ROOT / "infra/k8s/helm"
_AGENTGATEWAY_CRDS = _ROOT / "infra/k8s/helm-foundation/charts/agentgateway-crds-v1.3.1.tgz"
_GATEWAY_API_CRDS = _ROOT / "infra/k8s/gitops/gateway-api-crds/gateway-api-crds.yaml"
_IDENTITY = Path(__file__).parent / "fixtures/values.prod.identity.yaml"
_NETWORK = Path(__file__).parent / "fixtures/values.prod.network.yaml"
_IMAGE_INVENTORY = _ROOT / "scripts" / "ci" / "image_inventory.json"
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
    return tuple(document for document in yaml.safe_load_all(result.stdout) if isinstance(document, dict))


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
        matrix = json.loads(_IMAGE_INVENTORY.read_text(encoding="utf-8"))["images"]
        digests = {
            f"ghcr.io/mchar7/nohiki-monorepo/{entry['name']}": f"sha256:{index + 1:064x}"
            for index, entry in enumerate(matrix)
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
    return tuple(document for document in yaml.safe_load_all(result.stdout) if isinstance(document, dict))


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
        document
        for document in documents
        if document.get("kind") == kind and document.get("metadata", {}).get("name") == name
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
            for document in yaml.safe_load_all(stream.read())
            if isinstance(document, dict) and document.get("kind") == "CustomResourceDefinition"
        ]
    return {document["spec"]["names"]["kind"]: document for document in documents}


@cache
def _gateway_api_crds() -> dict[str, Manifest]:
    documents = (
        document
        for document in yaml.safe_load_all(_GATEWAY_API_CRDS.read_text(encoding="utf-8"))
        if isinstance(document, dict) and document.get("kind") == "CustomResourceDefinition"
    )
    return {document["spec"]["names"]["kind"]: document for document in documents}


def _schema(crd: Manifest, version: str) -> Manifest:
    return next(item for item in crd["spec"]["versions"] if item["name"] == version)["schema"]["openAPIV3Schema"]


def _secret_refs(pod_spec: Manifest) -> set[tuple[str, str]]:
    refs: set[tuple[str, str]] = set()
    for node in _walk(pod_spec):
        if not isinstance(node, dict):
            continue
        key_ref = node.get("secretKeyRef")
        if isinstance(key_ref, dict) and isinstance(key_ref.get("name"), str) and isinstance(key_ref.get("key"), str):
            refs.add((key_ref["name"], key_ref["key"]))
        secret = node.get("secret")
        if isinstance(secret, dict) and isinstance(secret.get("secretName"), str):
            for item in secret.get("items", []):
                refs.add((secret["secretName"], item["key"]))
    return refs


def _matches_selector(labels: dict[str, str], selector: Manifest) -> bool:
    return all(labels.get(key) == value for key, value in selector.get("matchLabels", {}).items())


def _container_env(deployment: Manifest) -> dict[str, str]:
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    return {item["name"]: item["value"] for item in container["env"] if "value" in item}


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
                or document.get("metadata", {}).get("name", "").startswith(_GATEWAY_NAME)
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
    assert parameters["spec"]["service"]["spec"] == {"type": "ClusterIP"}
    gateway = _named(rendered, "Gateway", _GATEWAY_NAME)
    assert gateway["spec"]["gatewayClassName"] == "agentgateway"
    assert gateway["spec"]["infrastructure"]["parametersRef"] == {
        "group": "agentgateway.dev",
        "kind": "AgentgatewayParameters",
        "name": _GATEWAY_NAME,
    }
    assert gateway["spec"]["listeners"] == [
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
            document["metadata"]["name"]: document
            for document in documents
            if document.get("kind") == "HTTPRoute"
            and document["metadata"]["name"].startswith(f"{_GATEWAY_NAME}-")
            and document["metadata"]["name"] != f"{_GATEWAY_NAME}-healthz"
        }
        assert set(routes) == set(expected_paths)
        for name, path in expected_paths.items():
            route = routes[name]
            assert route["spec"]["hostnames"] == [_GATEWAY_HOSTS_BY_ENVIRONMENT[environment]]
            assert route["spec"]["parentRefs"] == [
                {
                    "group": "gateway.networking.k8s.io",
                    "kind": "Gateway",
                    "name": _GATEWAY_NAME,
                    "sectionName": "model-https",
                }
            ]
            rule = route["spec"]["rules"][0]
            assert rule["matches"] == [{"path": {"type": "Exact", "value": path}}]
            assert rule["backendRefs"] == [
                {
                    "group": "agentgateway.dev",
                    "kind": "AgentgatewayBackend",
                    "name": name,
                }
            ]

        backends = [document for document in documents if document.get("kind") == "AgentgatewayBackend"]
        assert {backend["metadata"]["name"] for backend in backends} == set(expected_paths)
        assert not any(
            "model" in provider
            for backend in backends
            for group in backend["spec"]["ai"]["groups"]
            for provider in group["providers"]
        )

        providers_by_name = {
            provider["name"]: provider
            for backend in backends
            for group in backend["spec"]["ai"]["groups"]
            for provider in group["providers"]
        }
        assert set(providers_by_name) == _PROVIDER_NAMES_BY_ENVIRONMENT[environment]
        assert providers_by_name["openai-responses"]["host"] == "api.openai.com"
        assert providers_by_name["openai-responses"]["port"] == 443
        assert providers_by_name["openai-responses"]["path"] == "/v1/responses"
        assert providers_by_name["openai-responses"]["openai"] == {}
        assert providers_by_name["openrouter-completions"]["host"] == "openrouter.ai"
        assert providers_by_name["openrouter-completions"]["custom"] == {
            "formats": [{"type": "Completions", "path": "/api/v1/chat/completions"}]
        }
        assert providers_by_name["openai-responses"]["policies"]["tls"] == {
            "sni": "api.openai.com",
            "verifySubjectAltNames": ["api.openai.com"],
        }
        assert providers_by_name["openrouter-completions"]["policies"]["tls"] == {
            "sni": "openrouter.ai",
            "verifySubjectAltNames": ["openrouter.ai"],
        }
        assert "openrouter-responses" not in providers_by_name
        if environment == "managed":
            anthropic = providers_by_name["anthropic-messages"]
            assert anthropic["anthropic"] == {}
            assert anthropic["path"] == "/v1/messages"
            assert anthropic["policies"]["auth"] == {
                "secretRef": {"name": "nohiki-model-egress-anthropic"},
                "location": {"header": {"name": "x-api-key"}},
            }
            assert anthropic["policies"]["tls"] == {
                "sni": "api.anthropic.com",
                "verifySubjectAltNames": ["api.anthropic.com"],
            }


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
    groups = backend["spec"]["ai"]["groups"]
    assert len(groups) == 1
    assert len(groups[0]["providers"]) == 1
    provider = groups[0]["providers"][0]
    assert provider["name"] == "openai-responses"
    assert provider["host"] == "api.openai.com"
    assert provider["port"] == 443
    assert provider["path"] == "/v1/responses"
    assert provider["openai"] == {}
    assert provider["policies"]["auth"]["secretRef"] == {"name": "nohiki-model-egress-openai"}
    assert provider["policies"]["tls"] == {
        "sni": "api.openai.com",
        "verifySubjectAltNames": ["api.openai.com"],
    }
    assert not any(isinstance(node, str) and "openrouter" in node.lower() for node in _walk(backend))


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
    assert not any(
        policy["spec"].get("targetRefs")
        == [
            {
                "group": "gateway.networking.k8s.io",
                "kind": "HTTPRoute",
                "name": route_name,
            }
        ]
        and "apiKeyAuthentication" in policy["spec"].get("traffic", {})
        for policy in rendered
        if policy.get("kind") == "AgentgatewayPolicy"
    )


def test_models_lane_is_not_claimed_when_vendored_schema_does_not_support_it(
    rendered: tuple[Manifest, ...],
) -> None:
    if _AGENTGATEWAY_CRDS.is_file():
        backend_schema = _schema(_agentgateway_crds()["AgentgatewayBackend"], "v1alpha1")
        enums = [node["enum"] for node in _walk(backend_schema) if isinstance(node, dict) and "enum" in node]
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
        auth_policies = [policy for policy in policies if "apiKeyAuthentication" in policy["spec"].get("traffic", {})]
        assert len(auth_policies) == len(route_clients)

        expected_clients = set().union(*route_clients.values())
        client_labels = {
            document["metadata"]["name"]: document["spec"]["target"]["template"]["metadata"]["labels"]
            for document in documents
            if document.get("kind") == "ExternalSecret" and document.get("metadata", {}).get("name") in expected_clients
        }
        assert set(client_labels) == expected_clients

        selectors: dict[str, Manifest] = {}
        for policy in auth_policies:
            route_name = policy["metadata"]["name"].removesuffix("-client-auth")
            assert policy["spec"]["targetRefs"] == [
                {
                    "group": "gateway.networking.k8s.io",
                    "kind": "HTTPRoute",
                    "name": route_name,
                }
            ]
            auth = policy["spec"]["traffic"]["apiKeyAuthentication"]
            assert auth["mode"] == "Strict"
            route = route_name.removeprefix(f"{_GATEWAY_NAME}-")
            assert auth["secretSelector"] == {"matchLabels": {f"{_ROUTE_SELECTOR_PREFIX}{route}": "true"}}
            assert "secretRef" not in auth
            expected_header = "x-api-key" if route == "messages" else "Authorization"
            expected_header_config = {"name": expected_header}
            if expected_header == "Authorization":
                expected_header_config["prefix"] = "Bearer"
            assert auth["location"] == {"header": expected_header_config}
            selectors[route_name] = auth["secretSelector"]

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
        sensitive_labels = [
            document["spec"]["target"].get("template", {}).get("metadata", {}).get("labels", {})
            for document in documents
            if document.get("kind") == "ExternalSecret"
            and document.get("metadata", {}).get("name") in sensitive_secret_names
        ]
        assert all(
            not _matches_selector(labels, selector) for labels in sensitive_labels for selector in selectors.values()
        )

        provider_external_secrets = {
            document["metadata"]["name"]
            for document in documents
            if document.get("kind") == "ExternalSecret"
            and document.get("metadata", {}).get("name", "").startswith(f"{_GATEWAY_NAME}-")
            and document["metadata"]["name"] not in expected_clients
            and document["metadata"]["name"] not in {"nohiki-model-egress-tls", "nohiki-model-egress-ca"}
        }
        assert provider_external_secrets == expected_provider_secrets
        assert not any(
            document.get("kind") == "Secret" and document.get("metadata", {}).get("name") in _PROVIDER_SECRETS
            for document in documents
        ), "provider credentials must come from ExternalSecret, never a rendered Secret"

        providers = [
            provider
            for backend in documents
            if backend.get("kind") == "AgentgatewayBackend"
            for group in backend["spec"]["ai"]["groups"]
            for provider in group["providers"]
        ]
        assert {
            provider["policies"]["auth"]["secretRef"]["name"] for provider in providers
        } == expected_provider_secrets
        if environment == "managed":
            anthropic = next(provider for provider in providers if "anthropic" in provider)
            assert anthropic["policies"]["auth"]["location"] == {"header": {"name": "x-api-key"}}


def test_client_route_labels_are_declared_per_client_and_emit_the_responses_only_matrix(
    rendered: tuple[Manifest, ...],
) -> None:
    model_egress = yaml.safe_load((_CHART / "values.yaml").read_text(encoding="utf-8"))["global"]["modelEgress"]
    clients = {client["name"]: client for client in model_egress["clients"]}
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

    client_secrets = {
        document["metadata"]["name"]: document["spec"]["target"]["template"]["metadata"]["labels"]
        for document in rendered
        if document.get("kind") == "ExternalSecret"
        and document.get("metadata", {}).get("name", "").startswith("nohiki-model-egress-client-")
    }
    assert client_secrets == {
        client["secretName"]: {"nohiki.io/model-egress-route-responses": "true"} for client in clients.values()
    }


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
    expected = {
        "job-ingest-enrichment-service": {
            "provider": ("openai:gpt-5.6-luna", "medium"),
            "chains": {
                "extraction": ("openai:gpt-5.6-luna", "medium"),
                "skill_clarification": ("openai:gpt-5.6-luna", "medium"),
            },
        },
        "doc-content-service": {
            "provider": ("openai:gpt-5.6-sol", "high"),
            "chains": {"doc_tailoring": ("openai:gpt-5.6-sol", "high")},
        },
    }
    compose = yaml.safe_load((_ROOT / "infra/compose/docker-compose.yml").read_text(encoding="utf-8"))["services"]
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
        environment = compose[service]["environment"]
        assert {key: environment[key] for key in expectation} == expectation
    for service, policy in expected.items():
        values = yaml.safe_load((_CHART / "charts" / service / "values.yaml").read_text(encoding="utf-8"))["llm"]
        assert values["provider"]["models"] == [
            {"model": policy["provider"][0], "reasoningEffort": policy["provider"][1]}
        ]
        assert "reasoningEffort" not in values["provider"]
        assert set(values["chains"]) == set(policy["chains"])
        for chain, (model, effort) in policy["chains"].items():
            assert values["chains"][chain]["models"] == [{"model": model, "reasoningEffort": effort}]
            assert "reasoningEffort" not in values["chains"][chain]

        env = _container_env(_named(rendered, "Deployment", f"nohiki-{service}"))
        prefix = "JOB_INGEST_ENRICHMENT_" if service.startswith("job-") else "DOC_CONTENT_"
        assert env[f"{prefix}LLM__PROVIDER__MODELS__0__MODEL"] == policy["provider"][0]
        assert env[f"{prefix}LLM__PROVIDER__MODELS__0__REASONING_EFFORT"] == policy["provider"][1]
        assert f"{prefix}LLM__PROVIDER__REASONING_EFFORT" not in env
        model_keys = {key for key in env if key.startswith(f"{prefix}LLM__") and key.endswith("__MODEL")}
        expected_model_keys = {f"{prefix}LLM__PROVIDER__MODELS__0__MODEL"}
        for chain, (model, effort) in policy["chains"].items():
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
    pod_spec = deployment["spec"]["template"]["spec"]
    env_names = {item["name"] for container in pod_spec["containers"] for item in container.get("env", [])}
    assert not any(name.startswith("JOB_CORRELATION_EVAL_LLM__") for name in env_names)
    assert not any(secret.startswith("nohiki-model-egress-client-") for secret, _ in _secret_refs(pod_spec))
    assert not any(
        isinstance(node, str) and ("model-egress" in node or node == "/run/secrets/llm") for node in _walk(pod_spec)
    )

    values = yaml.safe_load(
        (_CHART / "charts/job-correlation-evaluation-service/values.yaml").read_text(encoding="utf-8")
    )
    assert values["llm"]["enabled"] is False
    assert values["secrets"].get("llm", False) is False


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
            assert backend["spec"]["ai"]["groups"]
            for group in backend["spec"]["ai"]["groups"]:
                assert group["providers"]
                for provider in group["providers"]:
                    policies = provider["policies"]
                    assert policies["tls"]["sni"] in policies["tls"]["verifySubjectAltNames"]
                    assert policies["http"] == {"requestTimeout": "180s"}
                    assert policies["tcp"] == {"connectTimeout": "10s"}

        health_policies = {
            policy["spec"]["targetRefs"][0]["name"]: policy["spec"]["backend"]["health"]
            for policy in documents
            if policy.get("kind") == "AgentgatewayPolicy" and "backend" in policy["spec"]
        }
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

    assert not any(
        isinstance(node, dict) and ("retry" in node or "rateLimit" in node)
        for document in rendered
        if document.get("kind") == "AgentgatewayPolicy"
        for node in _walk(document["spec"].get("traffic", {}))
    )


def test_environment_rate_limits_are_exact_schema_valid_and_bounded(
    rendered: tuple[Manifest, ...],
    managed_rendered: tuple[Manifest, ...],
) -> None:
    policy_schema = _schema(_agentgateway_crds()["AgentgatewayPolicy"], "v1alpha1")
    local_traffic_policies = {
        policy["spec"]["targetRefs"][0]["name"]: policy
        for policy in rendered
        if policy.get("kind") == "AgentgatewayPolicy"
        and policy.get("metadata", {}).get("name", "").endswith("-traffic")
    }
    assert set(local_traffic_policies) == set(_ROUTE_PATHS_BY_ENVIRONMENT["local"])
    assert all("rateLimit" not in policy["spec"]["traffic"] for policy in local_traffic_policies.values())

    managed_traffic_policies = {
        policy["spec"]["targetRefs"][0]["name"]: policy
        for policy in managed_rendered
        if policy.get("kind") == "AgentgatewayPolicy"
        and policy.get("metadata", {}).get("name", "").endswith("-traffic")
    }
    assert set(managed_traffic_policies) == set(_MANAGED_RATE_LIMITS)
    for route, expected in _MANAGED_RATE_LIMITS.items():
        policy = managed_traffic_policies[route]
        jsonschema.Draft202012Validator(policy_schema).validate(policy)
        assert policy["spec"]["traffic"]["rateLimit"] == {"local": expected}
        assert all(0 < item.get("requests", item.get("tokens", 0)) <= 120_000 for item in expected)
        assert all(0 < item["burst"] <= 20_000 for item in expected)
        assert "retry" not in policy["spec"]["traffic"]


def test_apps_receive_gateway_url_client_key_and_ca_but_no_provider_or_tls_key(
    rendered: tuple[Manifest, ...],
) -> None:
    deployments = {
        document["metadata"]["name"]: document for document in rendered if document.get("kind") == "Deployment"
    }
    client_readers: dict[str, set[str]] = {secret: set() for secret, _ in _CLIENT_SECRETS.values()}
    for name, (client_secret, client_key) in _CLIENT_SECRETS.items():
        pod_spec = deployments[name]["spec"]["template"]["spec"]
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

        env = pod_spec["containers"][0]["env"]
        base_urls = [item["value"] for item in env if item["name"].endswith("__BASE_URL")]
        assert base_urls, name
        assert set(base_urls) <= {
            _GATEWAY_ORIGIN,
            f"{_GATEWAY_ORIGIN}/v1",
        }, name
        models = [item["value"] for item in env if item["name"].endswith("__MODEL")]
        assert models, name
        model_env_names = {item["name"] for item in env if item["name"].endswith("__MODEL")}
        health_env = {item["name"]: item["value"] for item in env if item["name"].endswith("__HEALTH_URL")}
        assert model_env_names, name
        assert set(health_env) == {
            f"{model_name.removesuffix('__MODEL')}__HEALTH_URL" for model_name in model_env_names
        }, name
        assert set(health_env.values()) == {f"{_GATEWAY_ORIGIN}/healthz"}, name
        tls_env = {item["name"]: item["value"] for item in env if item["name"].endswith("__TLS_CA_FILE")}
        assert set(tls_env) == {
            f"{model_name.removesuffix('__MODEL')}__TLS_CA_FILE" for model_name in model_env_names
        }, name
        assert set(tls_env.values()) == {"/etc/nohiki/model-egress/ca.crt"}, name
        assert not {"SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"} & {item["name"] for item in env}, name
    assert client_readers == {secret: {deployment} for deployment, (secret, _) in _CLIENT_SECRETS.items()}
    assert not any(node == "nohiki-model-egress-client" for document in rendered for node in _walk(document)), (
        "the shared model-egress client Secret must not remain"
    )


def test_non_llm_skill_graph_never_joins_the_gateway_lane(
    rendered: tuple[Manifest, ...],
) -> None:
    deployment = _named(rendered, "Deployment", "nohiki-skill-graph-service")
    pod_spec = deployment["spec"]["template"]["spec"]
    refs = _secret_refs(pod_spec)
    assert not any(secret == "nohiki-llm-runtime" or secret.startswith("nohiki-model-egress") for secret, _ in refs)
    env_names = {item["name"] for item in pod_spec["containers"][0]["env"]}
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
        (document["kind"], document["metadata"]["name"])
        for document in rendered
        if document.get("kind") in gateway_kinds
        and document.get("metadata", {}).get("name", "").startswith(_GATEWAY_NAME)
    }
    actual_gateway_resources = {
        (document["kind"], document["metadata"]["name"])
        for document in false_override
        if document.get("kind") in gateway_kinds
        and document.get("metadata", {}).get("name", "").startswith(_GATEWAY_NAME)
    }
    assert actual_gateway_resources == expected_gateway_resources

    for name, (client_secret, client_key) in _CLIENT_SECRETS.items():
        pod_spec = _named(false_override, "Deployment", name)["spec"]["template"]["spec"]
        refs = _secret_refs(pod_spec)
        assert (client_secret, client_key) in refs, name
        assert ("nohiki-model-egress-ca", "ca.crt") in refs, name
        assert not any(secret == "nohiki-llm-runtime" for secret, _ in refs), name


def test_network_policy_allows_clients_only_to_gateway_and_gateway_only_to_control_plane_and_providers(
    rendered: tuple[Manifest, ...],
) -> None:
    policies = [document for document in rendered if document.get("kind") == "NetworkPolicy"]
    gateway = _named(rendered, "NetworkPolicy", _GATEWAY_NAME)
    assert gateway["spec"]["podSelector"]["matchLabels"] == {"gateway.networking.k8s.io/gateway-name": _GATEWAY_NAME}
    assert len(gateway["spec"]["ingress"]) == 2
    client_ingress = [
        rule for rule in gateway["spec"]["ingress"] if rule.get("ports") == [{"port": 8443, "protocol": "TCP"}]
    ]
    assert len(client_ingress) == 1
    assert {tuple(sorted(peer["podSelector"]["matchLabels"].items())) for peer in client_ingress[0]["from"]} == {
        (
            ("app.kubernetes.io/instance", "nohiki"),
            ("app.kubernetes.io/name", name.removeprefix("nohiki-")),
        )
        for name in _CLIENT_SECRETS
    }
    metrics_ingress = [
        rule for rule in gateway["spec"]["ingress"] if rule.get("ports") == [{"port": 15020, "protocol": "TCP"}]
    ]
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
    gateway_otlp_rules = [
        rule for rule in gateway["spec"]["egress"] if rule.get("ports") == [{"port": 4317, "protocol": "TCP"}]
    ]
    assert gateway_otlp_rules == [
        {
            "to": [{"podSelector": {"matchLabels": {"app.kubernetes.io/instance": "nohiki.nohiki-collector"}}}],
            "ports": [{"port": 4317, "protocol": "TCP"}],
        }
    ], "non-production OTLP egress must select the local collector pods exactly"

    gateway_ip_rules = [
        rule for rule in gateway["spec"]["egress"] if any("ipBlock" in peer for peer in rule.get("to", []))
    ]
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
        labels = _named(rendered, "Deployment", name)["spec"]["template"]["metadata"]["labels"]
        selected = [
            policy
            for policy in policies
            if all(
                labels.get(key) == value for key, value in policy["spec"]["podSelector"].get("matchLabels", {}).items()
            )
        ]
        rules = [rule for policy in selected for rule in policy["spec"].get("egress", [])]
        gateway_rules = [
            rule
            for rule in rules
            if any(peer.get("podSelector", {}).get("matchLabels") == client_selector for peer in rule.get("to", []))
        ]
        assert gateway_rules == [
            {
                "to": [{"podSelector": {"matchLabels": client_selector}}],
                "ports": [{"port": 8443, "protocol": "TCP"}],
            }
        ], name
        public_or_lan_model_rules = [
            rule
            for rule in rules
            if any(
                peer.get("ipBlock", {}).get("cidr") in {"0.0.0.0/0", "192.168.1.200/32"}
                and any(port.get("port") in {443, 8317} for port in rule.get("ports", []))
                for peer in rule.get("to", [])
            )
        ]
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
    model_egress = copy.deepcopy(
        yaml.safe_load((_CHART / "values.yaml").read_text(encoding="utf-8"))["global"]["modelEgress"]
    )
    model_egress["enabled"] = True
    model_egress["backends"][0]["groups"].append(
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
    assert len(backend["spec"]["ai"]["groups"]) == 2
    failover = backend["spec"]["ai"]["groups"][1]["providers"]
    assert failover[0]["name"] == "openai-failover"
    assert failover[0]["policies"]["auth"]["secretRef"] == {"name": "nohiki-model-egress-openai"}
    assert failover[0]["policies"]["tls"]["caCertificateRefs"] == [{"name": "model-provider-ca"}]
    deployment = _named(switched, "Deployment", "nohiki-doc-content-service")
    env = _container_env(deployment)
    assert env["DOC_CONTENT_LLM__PROVIDER__MODELS__0__MODEL"] == "openrouter:openai/gpt-4.1"
    assert all(value != "openai-failover" for value in env.values())


def test_gateway_metrics_service_monitor_targets_only_agentgateway_data_plane(
    rendered: tuple[Manifest, ...],
) -> None:
    monitor = _named(rendered, "ServiceMonitor", "agentgateway-proxy")
    assert monitor["metadata"]["labels"] == {
        "app.kubernetes.io/name": "agentgateway-proxy",
        "app.kubernetes.io/instance": "nohiki",
        "app.kubernetes.io/component": "model-egress",
        "app.kubernetes.io/part-of": "nohiki",
        "release": "nohiki",
    }
    assert monitor["spec"] == {
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
    selector = prometheus_resources[0]["spec"]["serviceMonitorSelector"]
    monitors = [document for document in rendered if document.get("kind") == "ServiceMonitor"]
    assert monitor in monitors
    assert monitors
    unmatched = {
        item["metadata"]["name"]
        for item in monitors
        if not _matches_selector(item["metadata"].get("labels", {}), selector)
    }
    assert unmatched == set(), (
        f"Prometheus selector {selector!r} does not select emitted ServiceMonitors: {sorted(unmatched)}"
    )


def test_llm_dashboard_queries_gateway_requests_tokens_latency_and_errors() -> None:
    dashboard_manifest = yaml.safe_load(
        (_ROOT / "infra/k8s/observability/base/grafana/dashboards/nohiki-llm.yaml").read_text(encoding="utf-8")
    )
    assert dashboard_manifest["kind"] == "GrafanaDashboard"
    dashboard = json.loads(dashboard_manifest["spec"]["json"])
    canonical = json.loads((_ROOT / "infra/shared/dashboards/nohiki-llm.json").read_text(encoding="utf-8"))
    assert dashboard == canonical
    assert dashboard["uid"] == "nohiki-llm"
    panels = {panel["title"]: panel for panel in dashboard["panels"]}
    expected_queries = {
        "Model Gateway Requests": "agentgateway_requests_total",
        "Gateway Tokens by Provider and Model": "agentgateway_gen_ai_client_token_usage_sum",
        "Gateway LLM Request Latency": "agentgateway_gen_ai_server_request_duration_bucket",
        "Gateway Time to First Token": "agentgateway_gen_ai_server_time_to_first_token_bucket",
        "Model Gateway Errors": 'agentgateway_requests_total{status=~"4..|5.."}',
    }
    assert set(expected_queries) <= set(panels)
    for title, metric in expected_queries.items():
        targets = panels[title]["targets"]
        assert len(targets) == 1
        assert metric in targets[0]["expr"]
        assert targets[0]["datasource"] == {"type": "prometheus", "uid": "mimir"}


def test_local_and_managed_environments_use_distinct_secret_delivery_without_private_defaults() -> None:
    base = yaml.safe_load((_CHART / "values.yaml").read_text(encoding="utf-8"))
    local = yaml.safe_load((_CHART / "values.local.yaml").read_text(encoding="utf-8"))
    assert "enabled" not in base["global"]["modelEgress"]
    assert local["global"]["secrets"]["inlineSecretsEnabled"] is False
    assert not local["global"].get("eso", {}).get("externalSecretsEnabled", False)

    model_egress = base["global"]["modelEgress"]
    assert model_egress["certificateSecretName"] == ""
    assert model_egress["caSecretName"] == ""
    assert "clientSecretName" not in model_egress
    credential_names = {
        provider["credentialName"]
        for backend in model_egress["backends"]
        for group in backend["groups"]
        for provider in group["providers"]
    }
    assert credential_names == {"anthropic", "openai", "openrouter"}
    for values_name in ("values.staging.yaml", "values.prod.yaml"):
        managed = yaml.safe_load((_CHART / values_name).read_text(encoding="utf-8"))["global"]
        assert managed["eso"]["externalSecretsEnabled"] is True
        assert managed["modelEgress"] == {"rateLimitsEnabled": True}, (
            "managed overlays may enable bounded gateway limits but must not inject disable switches, "
            "provider keys, or private endpoints"
        )

    destinations = base["global"]["modelEgress"]["destinations"]
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
