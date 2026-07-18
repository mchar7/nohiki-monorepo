"""Semantic Helm coverage for the dedicated BFF SSE Gateway route."""

import ast
import hashlib
import re
import tarfile
from functools import cache
from pathlib import Path
from typing import Any

import jsonschema
import pytest
import yaml
from test_gateway_browser_policy import _render_helm

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_BFF_MAIN = _REPOSITORY_ROOT / "backend" / "services" / "bff-service" / "src" / "bff_service" / "main.py"
_BFF_DOCUMENTS = (
    _REPOSITORY_ROOT
    / "backend"
    / "services"
    / "bff-service"
    / "src"
    / "bff_service"
    / "api"
    / "routers"
    / "documents.py"
)
_FOUNDATION_CHART = _REPOSITORY_ROOT / "infra" / "k8s" / "helm-foundation"
_GATEWAY_API_CRDS = _REPOSITORY_ROOT / "infra" / "k8s" / "gitops" / "gateway-api-crds" / "gateway-api-crds.yaml"
_KGATEWAY_CRDS = _FOUNDATION_CHART / "charts" / "kgateway-crds-v2.3.6.tgz"
_GATEWAY_API_MARKER = b"# ---8<--- BEGIN VENDORED CONTENT ---8<---\n"
_GATEWAY_API_EXPECTED_HEX = "a557172e8348f758479e9ee4000bbbb4b4aa48302a6b73461823ea5349bad56d"
_KGATEWAY_CRDS_SHA256 = "d6b1d8bf0e2636bca6b8fb2b4a1525806fd1b4f9e84614c8a6a16eda585a119c"


def _named(documents: tuple[dict, ...], kind: str, name: str) -> dict[str, Any]:
    matches = [
        document
        for document in documents
        if document.get("kind") == kind and document.get("metadata", {}).get("name") == name
    ]
    assert len(matches) == 1, f"expected one {kind} named {name}, got {len(matches)}"
    return matches[0]


@cache
def _crds() -> tuple[dict[str, Any], ...]:
    assert _GATEWAY_API_CRDS.is_file(), f"missing vendored Gateway API CRDs: {_GATEWAY_API_CRDS}"
    gateway_bundle = _GATEWAY_API_CRDS.read_bytes()
    gateway_header, marker, gateway_payload = gateway_bundle.partition(_GATEWAY_API_MARKER)
    assert marker, "vendored Gateway API bundle marker is missing"
    assert b"version: v1.6.0" in gateway_header
    assert hashlib.sha256(gateway_payload).hexdigest() == _GATEWAY_API_EXPECTED_HEX
    gateway_api = tuple(
        document
        for document in yaml.safe_load_all(gateway_payload.decode())
        if isinstance(document, dict) and document.get("kind") == "CustomResourceDefinition"
    )
    assert gateway_api, "vendored Gateway API v1.6.0 bundle contains no CRDs"

    assert _KGATEWAY_CRDS.is_file(), (
        f"missing {_KGATEWAY_CRDS.name}; run `helm dependency build infra/k8s/helm-foundation`"
    )
    assert hashlib.sha256(_KGATEWAY_CRDS.read_bytes()).hexdigest() == _KGATEWAY_CRDS_SHA256
    with tarfile.open(_KGATEWAY_CRDS, mode="r:gz") as archive:
        chart_stream = archive.extractfile("kgateway-crds/Chart.yaml")
        assert chart_stream is not None
        chart = yaml.safe_load(chart_stream.read())
        assert chart == {
            "apiVersion": "v2",
            "appVersion": "v2.3.6",
            "description": "A Helm chart for the kgateway project CRDs",
            "icon": "https://raw.githubusercontent.com/kgateway-dev/kgateway.dev/main/static/favicon.svg",
            "name": "kgateway-crds",
            "type": "application",
            "version": "v2.3.6",
        }
        member = next(
            member
            for member in archive.getmembers()
            if member.name.endswith("/gateway.kgateway.dev_trafficpolicies.yaml")
        )
        stream = archive.extractfile(member)
        assert stream is not None
        kgateway = tuple(
            document
            for document in yaml.safe_load_all(stream.read().decode())
            if isinstance(document, dict) and document.get("kind") == "CustomResourceDefinition"
        )
    assert kgateway, f"{_KGATEWAY_CRDS.name} contains no TrafficPolicy CRD"
    return gateway_api + kgateway


def _validate_against_vendored_crd(resource: dict[str, Any]) -> None:
    group, version = resource["apiVersion"].split("/", maxsplit=1)
    matching_crds = [
        crd for crd in _crds() if crd["spec"]["group"] == group and crd["spec"]["names"]["kind"] == resource["kind"]
    ]
    assert len(matching_crds) == 1, (
        f"expected one vendored schema for {resource['apiVersion']} {resource['kind']}, got {len(matching_crds)}"
    )
    version_schema = next(item for item in matching_crds[0]["spec"]["versions"] if item["name"] == version)
    openapi_schema = version_schema["schema"]["openAPIV3Schema"]
    assert isinstance(openapi_schema, dict)
    assert openapi_schema, f"vendored schema for {resource['apiVersion']} {resource['kind']} is empty"
    jsonschema.Draft202012Validator(openapi_schema).validate(resource)


_DOCUMENT_EVENTS_PATTERN = (
    r"^/api/documents/([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/events$"
)


def _matches_path(match: dict[str, Any], path: str) -> bool:
    path_match = match["path"]
    if path_match["type"] == "Exact":
        return path == path_match["value"]
    if path_match["type"] == "PathPrefix":
        prefix = path_match["value"].rstrip("/")
        return path == prefix or path.startswith(f"{prefix}/")
    assert path_match["type"] == "RegularExpression"
    return re.fullmatch(path_match["value"], path) is not None


def _literal_call_argument(source: Path, owner: str, method: str) -> str:
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    values = [
        call.args[0].value
        for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == method
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == owner
        and call.args
        and isinstance(call.args[0], ast.Constant)
        and isinstance(call.args[0].value, str)
    ]
    assert len(values) == 1, f"expected one literal {owner}.{method} call in {source}, got {values}"
    return values[0]


@pytest.fixture(scope="module")
def rendered_environments(
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, tuple[dict, ...]]:
    tmp_path = tmp_path_factory.mktemp("gateway-sse")
    return {
        values_name: _render_helm(values_name, tmp_path)
        for values_name in (
            "values.local.yaml",
            "values.staging.yaml",
            "values.prod.yaml",
        )
    }


def test_gateway_path_is_the_direct_fastapi_document_events_mount() -> None:
    main_tree = ast.parse(_BFF_MAIN.read_text(encoding="utf-8"), filename=str(_BFF_MAIN))
    prefixes = [
        keyword.value.value
        for call in ast.walk(main_tree)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "include_router"
        and call.args
        and isinstance(call.args[0], ast.Name)
        and call.args[0].id == "document_events_router"
        for keyword in call.keywords
        if keyword.arg == "prefix" and isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str)
    ]
    assert prefixes == ["/api/documents"]
    endpoint_path = _literal_call_argument(_BFF_DOCUMENTS, "document_events_router", "get")
    assert f"{prefixes[0]}{endpoint_path}" == "/api/documents/{request_id}/events"


@pytest.mark.parametrize("values_name", ["values.local.yaml", "values.staging.yaml", "values.prod.yaml"])
def test_sse_route_matches_only_request_scoped_public_get(
    values_name: str,
    rendered_environments: dict[str, tuple[dict, ...]],
) -> None:
    documents = rendered_environments[values_name]
    route = _named(documents, "HTTPRoute", "nohiki-sse-route")
    rules = route["spec"]["rules"]

    assert len(rules) == 1
    rule = rules[0]
    assert rule["name"] == "document-events"
    assert rule["matches"] == [
        {
            "method": "GET",
            "path": {"type": "RegularExpression", "value": _DOCUMENT_EVENTS_PATTERN},
        }
    ]
    match = rule["matches"][0]
    assert _matches_path(match, "/api/documents/018f47a6-7b2c-4d1e-8f90-123456789abc/events")
    for rejected_path in (
        "/api/v1/documents/events",
        "/api/documents/events",
        "/api/documents/not-a-uuid/events",
        "/api/documents/018f47a6-7b2c-4d1e-8f90-123456789abc/events/extra",
    ):
        assert not _matches_path(match, rejected_path)
    assert rule["backendRefs"] == [{"name": "nohiki-bff-service", "port": 8000}]
    assert "filters" not in rule, "the HTTPRoute must not rewrite or mutate the stream"
    assert "queryParams" not in match, "credentials and cursors must not be accepted from the query string"
    _validate_against_vendored_crd(route)


@pytest.mark.parametrize("values_name", ["values.local.yaml", "values.staging.yaml", "values.prod.yaml"])
def test_sse_route_alone_disables_timeouts_buffering_and_compression(
    values_name: str,
    rendered_environments: dict[str, tuple[dict, ...]],
) -> None:
    documents = rendered_environments[values_name]
    route = _named(documents, "HTTPRoute", "nohiki-sse-route")
    policy = _named(documents, "TrafficPolicy", "nohiki-sse-response")
    sse_rule = route["spec"]["rules"][0]

    assert sse_rule["timeouts"] == {"backendRequest": "0s", "request": "0s"}
    assert policy["spec"] == {
        "buffer": {"disable": {}},
        "compression": {"responseCompression": {"disable": {}}},
        "targetRefs": [
            {
                "group": "gateway.networking.k8s.io",
                "kind": "HTTPRoute",
                "name": "nohiki-sse-route",
                "sectionName": "document-events",
            }
        ],
    }
    assert "urlRewrite" not in policy["spec"]
    _validate_against_vendored_crd(policy)

    other_bff_routes = [
        document
        for document in documents
        if document.get("kind") == "HTTPRoute"
        and document.get("metadata", {}).get("name") in {"nohiki-api-route", "nohiki-ping-route"}
    ]
    assert {route["metadata"]["name"] for route in other_bff_routes} == {
        "nohiki-api-route",
        "nohiki-ping-route",
    }
    assert all("timeouts" not in rule for route in other_bff_routes for rule in route["spec"]["rules"])


@pytest.mark.parametrize("values_name", ["values.local.yaml", "values.staging.yaml", "values.prod.yaml"])
def test_sse_route_precedes_catch_all_without_granting_legacy_sse_policy(
    values_name: str,
    rendered_environments: dict[str, tuple[dict, ...]],
) -> None:
    documents = rendered_environments[values_name]
    sse_route = _named(documents, "HTTPRoute", "nohiki-sse-route")
    api_route = _named(documents, "HTTPRoute", "nohiki-api-route")
    sse_match = sse_route["spec"]["rules"][0]["matches"][0]
    api_match = api_route["spec"]["rules"][0]["matches"][0]
    public_path = "/api/documents/018f47a6-7b2c-4d1e-8f90-123456789abc/events"

    assert _matches_path(sse_match, public_path)
    assert _matches_path(api_match, public_path)
    assert sse_match["path"]["type"] == "RegularExpression"
    assert api_match == {"path": {"type": "PathPrefix", "value": "/api"}}
    assert not _matches_path(sse_match, "/api/v1/documents/events")
    assert "timeouts" not in api_route["spec"]["rules"][0]
    assert not any(
        ref.get("name") == "nohiki-api-route"
        for policy in documents
        if policy.get("kind") == "TrafficPolicy" and policy.get("metadata", {}).get("name") == "nohiki-sse-response"
        for ref in policy["spec"]["targetRefs"]
    )


@pytest.mark.parametrize("values_name", ["values.local.yaml", "values.staging.yaml", "values.prod.yaml"])
def test_gateway_listener_service_selector_and_network_policy_form_one_reachable_path(
    values_name: str,
    rendered_environments: dict[str, tuple[dict, ...]],
) -> None:
    documents = rendered_environments[values_name]
    gateway = _named(documents, "Gateway", "nohiki-gateway")
    route = _named(documents, "HTTPRoute", "nohiki-sse-route")
    service = _named(documents, "Service", "nohiki-bff-service")
    deployment = _named(documents, "Deployment", "nohiki-bff-service")
    policy = _named(documents, "NetworkPolicy", "nohiki-bff-service")
    application_host = route["spec"]["hostnames"][0]
    assert application_host
    expected_listeners = [
        {
            "name": "http",
            "hostname": application_host,
            "protocol": "HTTP",
            "port": 80,
        }
    ]
    if values_name == "values.local.yaml":
        expected_listeners.append(
            {
                "name": "s3-http",
                "hostname": "s3.nohiki.localhost",
                "protocol": "HTTP",
                "port": 80,
            }
        )
    assert [
        {key: listener[key] for key in ("name", "hostname", "protocol", "port")}
        for listener in gateway["spec"]["listeners"]
    ] == expected_listeners
    assert route["spec"]["parentRefs"] == [{"name": "nohiki-gateway", "namespace": service["metadata"]["namespace"]}]
    assert service["spec"]["type"] == "ClusterIP"
    assert service["spec"]["ports"] == [{"name": "http", "port": 8000, "protocol": "TCP", "targetPort": "http"}]
    endpoint_labels = service["spec"]["selector"]
    assert endpoint_labels == {
        "app.kubernetes.io/name": "bff-service",
        "app.kubernetes.io/instance": "nohiki",
    }
    assert deployment["spec"]["selector"]["matchLabels"] == endpoint_labels
    assert deployment["spec"]["template"]["metadata"]["labels"].items() >= endpoint_labels.items()
    assert policy["spec"]["podSelector"]["matchLabels"] == endpoint_labels
    assert {
        "from": [{"podSelector": {"matchLabels": {"gateway.networking.k8s.io/gateway-name": "nohiki-gateway"}}}],
        "ports": [{"port": 8000, "protocol": "TCP"}],
    } in policy["spec"]["ingress"]


def test_sse_static_response_policy_is_unmodified_and_isolated_from_ordinary_bff(
    rendered_environments: dict[str, tuple[dict, ...]],
) -> None:
    documents = rendered_environments["values.staging.yaml"]
    sse_policy = _named(documents, "TrafficPolicy", "nohiki-sse-response")
    api_route = _named(documents, "HTTPRoute", "nohiki-api-route")

    assert "transformation" not in sse_policy["spec"], "the static policy must not mutate responses"
    assert api_route["spec"]["rules"] == [
        {
            "matches": [{"path": {"type": "PathPrefix", "value": "/api"}}],
            "backendRefs": [{"name": "nohiki-bff-service", "port": 8000}],
        }
    ]
    policies_targeting_sse = [
        policy
        for policy in documents
        if policy.get("kind") == "TrafficPolicy"
        and any(ref.get("name") == "nohiki-sse-route" for ref in policy.get("spec", {}).get("targetRefs", []))
    ]
    assert [policy["metadata"]["name"] for policy in policies_targeting_sse] == ["nohiki-sse-response"]
    policies_targeting_api = [
        policy
        for policy in documents
        if policy.get("kind") == "TrafficPolicy"
        and any(ref.get("name") == "nohiki-api-route" for ref in policy.get("spec", {}).get("targetRefs", []))
    ]
    assert policies_targeting_api
    assert all(policy["metadata"]["name"] != "nohiki-sse-response" for policy in policies_targeting_api)
