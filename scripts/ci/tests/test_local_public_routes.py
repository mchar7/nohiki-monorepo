"""Focused contracts for the local k3s public Gateway surface."""

from __future__ import annotations

import importlib.util
import re
import tomllib
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml
from test_frontend_delivery import _named, _render
from test_local_verification_jobs import _container, _pod_spec, _stage_documents

_ROOT = Path(__file__).resolve().parents[3]
_LOCAL_VALUES = _ROOT / "infra" / "k8s" / "helm" / "values.local.yaml"
_PROXY_RUNNER = _ROOT / "tests" / "api" / "run_k8s_verification.py"
_WORKER_CONFIG = _ROOT / "typescript" / "edge" / "auth-listings-worker" / "wrangler.toml"
_PUBLIC_ORIGIN = "http://nohiki.localhost:8080"
_S3_PUBLIC_ORIGIN = "http://s3.nohiki.localhost:8080"
_PROXY_UPSTREAM = "http://nohiki-gateway.nohiki.svc.cluster.local:80"


@pytest.fixture(scope="module")
def rendered_environments(
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, tuple[dict[str, Any], ...]]:
    render_root = tmp_path_factory.mktemp("public-routes")
    return {
        values_name: _render(values_name, render_root)
        for values_name in (
            "values.local.yaml",
            "values.staging.yaml",
            "values.prod.yaml",
        )
    }


def _env(container: dict[str, Any]) -> dict[str, str]:
    return {entry["name"]: entry["value"] for entry in container["env"] if "value" in entry}


def _scalar_strings(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, dict):
        return tuple(item for child in value.values() for item in _scalar_strings(child))
    if isinstance(value, list):
        return tuple(item for child in value for item in _scalar_strings(child))
    return ()


def _proxy_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("nohiki_k8s_verification", _PROXY_RUNNER)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_local_gateway_exposes_exact_workstation_frontend_and_api_origin(
    rendered_environments: dict[str, tuple[dict[str, Any], ...]],
) -> None:
    documents = rendered_environments["values.local.yaml"]
    gateway = _named(documents, "Gateway", "nohiki-gateway")
    listeners = {listener["name"]: listener for listener in gateway["spec"]["listeners"]}

    assert listeners["http"] == {
        "name": "http",
        "protocol": "HTTP",
        "port": 80,
        "hostname": "nohiki.localhost",
        "allowedRoutes": {"namespaces": {"from": "Same"}},
    }
    for route_name, backend, port, path in (
        ("nohiki-api-route", "nohiki-bff-service", 8000, "/api"),
        ("nohiki-frontend-route", "nohiki-frontend", 80, "/"),
    ):
        route = _named(documents, "HTTPRoute", route_name)
        assert route["spec"]["hostnames"] == ["nohiki.localhost"]
        assert route["spec"]["parentRefs"] == [{"name": "nohiki-gateway", "namespace": "nohiki-local"}]
        assert route["spec"]["rules"] == [
            {
                "matches": [{"path": {"type": "PathPrefix", "value": path}}],
                "backendRefs": [{"name": backend, "port": port}],
            }
        ]

    values = yaml.safe_load(_LOCAL_VALUES.read_text(encoding="utf-8"))
    assert values["global"]["ingress"]["host"] == "nohiki.localhost"
    assert _PUBLIC_ORIGIN == "http://nohiki.localhost:8080"


def test_local_s3_hostname_routes_unchanged_paths_to_rustfs_service(
    rendered_environments: dict[str, tuple[dict[str, Any], ...]],
) -> None:
    documents = rendered_environments["values.local.yaml"]
    gateway = _named(documents, "Gateway", "nohiki-gateway")
    route = _named(documents, "HTTPRoute", "nohiki-s3-route")
    service = _named(documents, "Service", "nohiki-rustfs")
    listeners = {listener["name"]: listener for listener in gateway["spec"]["listeners"]}

    assert listeners["s3-http"] == {
        "name": "s3-http",
        "protocol": "HTTP",
        "port": 80,
        "hostname": "s3.nohiki.localhost",
        "allowedRoutes": {"namespaces": {"from": "Same"}},
    }
    assert route["spec"] == {
        "parentRefs": [
            {
                "name": "nohiki-gateway",
                "namespace": "nohiki-local",
                "sectionName": "s3-http",
            }
        ],
        "hostnames": ["s3.nohiki.localhost"],
        "rules": [{"backendRefs": [{"name": "nohiki-rustfs", "port": 9000}]}],
    }
    assert service["spec"]["type"] == "ClusterIP"
    assert service["spec"]["ports"][0] == {
        "port": 9000,
        "targetPort": "api",
        "protocol": "TCP",
        "name": "api",
    }
    values = yaml.safe_load(_LOCAL_VALUES.read_text(encoding="utf-8"))
    assert values["rustfs"]["secret"]["existingSecret"] == "nohiki-rustfs-credentials"
    assert not any(
        document.get("kind") == "Secret" and document.get("metadata", {}).get("name") == "nohiki-rustfs-credentials"
        for document in documents
    )
    assert "filters" not in route["spec"]["rules"][0]
    assert "matches" not in route["spec"]["rules"][0]


def test_local_bff_separates_internal_s3_from_strict_browser_origins(
    rendered_environments: dict[str, tuple[dict[str, Any], ...]],
) -> None:
    documents = rendered_environments["values.local.yaml"]
    deployment = _named(documents, "Deployment", "nohiki-bff-service")
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    env = _env(container)

    assert env["BFF_S3__ENDPOINT"] == "http://nohiki-rustfs:9000"
    assert env["BFF_S3__PUBLIC_URL"] == _S3_PUBLIC_ORIGIN
    assert env["BFF_ORIGINS__CORS_ORIGINS"] == _PUBLIC_ORIGIN
    assert env["BFF_ORIGINS__CSRF_ORIGINS"] == _PUBLIC_ORIGIN


def test_local_values_have_no_workstation_or_direct_backend_runtime_targets() -> None:
    values = yaml.safe_load(_LOCAL_VALUES.read_text(encoding="utf-8"))
    scalars = _scalar_strings(values)
    assert all(re.search(r"(?<![A-Za-z0-9.-])nohiki\.local(?!host\b)", value) is None for value in scalars)
    forbidden = (
        "http://localhost:9000",
        "host.docker.internal",
        "http://localhost:5173",
        "http://localhost:3000",
        "docker-compose",
        "http://nohiki-bff-service",
        "http://nohiki-frontend",
    )
    for target in forbidden:
        assert all(target not in value for value in scalars), target


def test_auth_listings_worker_k3s_uses_only_public_gateway_origin() -> None:
    config = tomllib.loads(_WORKER_CONFIG.read_text(encoding="utf-8"))
    k3s = config["env"]["k3s"]["vars"]

    assert k3s == {
        "BFF_ORIGIN": _PUBLIC_ORIGIN,
        "ALLOWED_ORIGINS": _PUBLIC_ORIGIN,
        "OTEL_EXPORTER_OTLP_ENDPOINT": f"{_PUBLIC_ORIGIN}/v1/traces",
    }
    assert "localhost:5173" not in "\n".join(k3s.values())
    assert all(re.search(r"(?<![A-Za-z0-9.-])nohiki\.local(?!host\b)", value) is None for value in k3s.values())
    assert config["vars"] == {
        "BFF_ORIGIN": "http://localhost:8000",
        "ALLOWED_ORIGINS": "http://localhost:5173",
        "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4318/v1/traces",
    }
    assert config["env"]["staging"]["vars"] == {
        "BFF_ORIGIN": "https://staging.nohiki.com",
        "ALLOWED_ORIGINS": "https://staging.nohiki.com",
        "OTEL_EXPORTER_OTLP_ENDPOINT": "",
    }
    assert config["env"]["production"]["vars"] == {
        "BFF_ORIGIN": "https://nohiki.com",
        "ALLOWED_ORIGINS": "https://nohiki.com",
        "OTEL_EXPORTER_OTLP_ENDPOINT": "",
    }


def test_verification_proxy_accepts_only_both_public_gateway_hosts_without_network() -> None:
    proxy = _proxy_module()

    assert frozenset({"nohiki.localhost", "s3.nohiki.localhost"}) == proxy.PROXY_ALLOWED_HOSTS
    for raw, expected in (
        ("nohiki.localhost", "nohiki.localhost"),
        ("nohiki.localhost:80", "nohiki.localhost"),
        ("s3.nohiki.localhost", "s3.nohiki.localhost"),
        ("s3.nohiki.localhost:8080", "s3.nohiki.localhost"),
    ):
        assert proxy._validated_proxy_host(raw) == expected

    for rejected in (
        "nohiki.local",
        "frontend.nohiki.svc.cluster.local",
        "nohiki-bff-service:8000",
        "nohiki-rustfs:9000",
        "user@nohiki.localhost",
        "nohiki.localhost:not-a-port",
        "[::1]",
    ):
        with pytest.raises(ValueError, match="request Host"):
            proxy._validated_proxy_host(rejected)


@pytest.mark.parametrize("lane", ["api", "playwright"])
def test_verification_jobs_map_both_hosts_to_loopback_gateway_proxy(lane: str) -> None:
    pod = _pod_spec(lane)
    proxy = _container(lane, "gateway-proxy")
    env = _env(proxy)

    assert pod["hostAliases"] == [{"ip": "127.0.0.1", "hostnames": ["nohiki.localhost", "s3.nohiki.localhost"]}]
    assert env == {
        "NOHIKI_GATEWAY_UPSTREAM": _PROXY_UPSTREAM,
        "NOHIKI_PROXY_LISTEN_HOST": "127.0.0.1",
        "NOHIKI_PROXY_LISTEN_PORT": "80",
        "NOHIKI_PROXY_ALLOWED_HOSTS": "nohiki.localhost,s3.nohiki.localhost",
    }
    assert all(
        direct not in "\n".join(yaml.safe_dump(document) for document in _stage_documents(lane))
        for direct in ("nohiki-frontend", "nohiki-bff-service", "nohiki-rustfs:9000")
    )


@pytest.mark.parametrize(
    ("values_name", "hostname"),
    [("values.staging.yaml", "staging.nohiki.com"), ("values.prod.yaml", "nohiki.com")],
)
def test_managed_frontend_and_api_routes_remain_unchanged(
    values_name: str,
    hostname: str,
    rendered_environments: dict[str, tuple[dict[str, Any], ...]],
) -> None:
    documents = rendered_environments[values_name]
    route_names = {document["metadata"]["name"] for document in documents if document.get("kind") == "HTTPRoute"}
    assert "nohiki-s3-route" not in route_names

    for route_name, backend, port, path in (
        ("nohiki-api-route", "nohiki-bff-service", 8000, "/api"),
        ("nohiki-frontend-route", "nohiki-frontend", 80, "/"),
    ):
        route = _named(documents, "HTTPRoute", route_name)
        assert route["spec"]["hostnames"] == [hostname]
        assert route["spec"]["rules"] == [
            {
                "matches": [{"path": {"type": "PathPrefix", "value": path}}],
                "backendRefs": [{"name": backend, "port": port}],
            }
        ]
