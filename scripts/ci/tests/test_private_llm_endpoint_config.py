"""Regression coverage for deployment-private LLM endpoint configuration."""

from __future__ import annotations

import re
import subprocess
from functools import cache
from pathlib import Path
from typing import TypedDict

import yaml
from _documents import (
    ComposeFile,
    ContainerEnv,
    Manifest,
    Scalar,
    containers_of,
    load_compose,
    load_manifests,
    load_mapping,
)

_ROOT = Path(__file__).resolve().parents[3]
_CHART = _ROOT / "infra" / "k8s" / "helm"
_COMPOSE = _ROOT / "infra" / "compose" / "docker-compose.yml"
_ENV_EXAMPLE = _ROOT / "infra" / "compose" / ".env.example"
_EXTERNAL_BASE_URL = "${NOHIKI_LLM_OPENAI_BASE_URL:?set NOHIKI_LLM_OPENAI_BASE_URL}"
_GATEWAY_ORIGIN = "https://nohiki-model-egress.nohiki-local.svc.cluster.local:8443"
_MODEL_CA_FILE = "/etc/nohiki/model-egress/ca.crt"
_MODEL_EGRESS_CLIENTS = {
    "job-ingest-enrichment-service": (
        "nohiki-model-egress-client-job-ingest-enrichment",
        "job-ingest-enrichment",
    ),
    "doc-content-service": ("nohiki-model-egress-client-doc-content", "doc-content"),
}
_PROVIDER_API_KEYS = ("OPENROUTER", "OPENAI", "ANTHROPIC")

type _Model = tuple[str, str]


class _Route(TypedDict):
    prefix: str
    provider: tuple[_Model, ...]
    compose_chains: bool
    chains: dict[str, tuple[_Model, ...]]


_ROUTES: dict[str, _Route] = {
    "nohiki-job-ingest-enrichment-service": {
        "prefix": "JOB_INGEST_ENRICHMENT_",
        "provider": (("openai:gpt-5.6-luna", "medium"),),
        "compose_chains": False,
        "chains": {
            "EXTRACTION": (("openai:gpt-5.6-luna", "medium"),),
            "SKILL_CLARIFICATION": (("openai:gpt-5.6-luna", "medium"),),
        },
    },
    "nohiki-doc-content-service": {
        "prefix": "DOC_CONTENT_",
        "provider": (("openai:gpt-5.6-sol", "high"),),
        "compose_chains": True,
        "chains": {"DOC_TAILORING": (("openai:gpt-5.6-sol", "high"),)},
    },
}
_DISABLED_LLM_SERVICES = {"job-correlation-evaluation-service"}


@cache
def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@cache
def _compose() -> ComposeFile:
    return load_compose(_COMPOSE)


def _source_llm_values(tmp_path: Path) -> Path:
    values = {
        service: {"llm": load_mapping(_CHART / "charts" / service / "values.yaml")["llm"]}
        for deployment in _ROUTES
        for service in (deployment.removeprefix("nohiki-"),)
    }
    path = tmp_path / "source-llm-values.yaml"
    path.write_text(yaml.safe_dump(values), encoding="utf-8")
    return path


def _render_local(tmp_path: Path) -> tuple[Manifest, ...]:
    result = subprocess.run(
        [
            "helm",
            "template",
            "nohiki",
            str(_CHART),
            "--namespace",
            "nohiki-local",
            "--values",
            str(_source_llm_values(tmp_path)),
            "--values",
            str(_CHART / "values.local.yaml"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return tuple(load_manifests(result.stdout))


def _deployment_env(documents: tuple[Manifest, ...], name: str) -> dict[str, ContainerEnv]:
    deployment = next(
        document
        for document in documents
        if document.get("kind") == "Deployment" and document["metadata"]["name"] == name
    )
    container = containers_of(deployment)[0]
    return {entry["name"]: entry for entry in container["env"]}


def _expected_route_env(route: _Route, *, include_chains: bool = True) -> tuple[dict[str, str], set[str]]:
    prefix = route["prefix"]
    values: dict[str, str] = {}
    base_urls: set[str] = set()

    scopes = [("PROVIDER", route["provider"])]
    if include_chains:
        scopes.extend(route["chains"].items())
    for scope, models in scopes:
        scope_prefix = f"{prefix}LLM__PROVIDER" if scope == "PROVIDER" else f"{prefix}LLM__CHAINS__{scope}"
        for index, (model, reasoning) in enumerate(models):
            stem = f"{scope_prefix}__MODELS__{index}"
            values[f"{stem}__MODEL"] = model
            values[f"{stem}__REASONING_EFFORT"] = reasoning
            base_urls.add(f"{stem}__BASE_URL")

    return values, base_urls


def test_local_helm_llm_routes_use_gateway_and_secret_contract(tmp_path: Path) -> None:
    documents = _render_local(tmp_path)
    expected_base_urls: set[str] = set()

    for deployment, route in _ROUTES.items():
        env = _deployment_env(documents, deployment)
        expected_values, route_base_urls = _expected_route_env(route)
        expected_base_urls.update(route_base_urls)
        client_secret = _MODEL_EGRESS_CLIENTS[deployment.removeprefix("nohiki-")]

        for name, value in expected_values.items():
            assert env[name] == {"name": name, "value": value}
        for name in route_base_urls:
            model_name = env[name.removesuffix("__BASE_URL") + "__MODEL"]["value"]
            assert isinstance(model_name, str)
            suffix = "" if model_name.startswith("anthropic:") else "/v1"
            assert env[name] == {"name": name, "value": f"{_GATEWAY_ORIGIN}{suffix}"}
            health_name = name.removesuffix("__BASE_URL") + "__HEALTH_URL"
            assert env[health_name] == {
                "name": health_name,
                "value": f"{_GATEWAY_ORIGIN}/healthz",
            }
            ca_name = name.removesuffix("__BASE_URL") + "__TLS_CA_FILE"
            assert env[ca_name] == {"name": ca_name, "value": _MODEL_CA_FILE}
        for provider in _PROVIDER_API_KEYS:
            name = f"{route['prefix']}LLM__PROVIDER__API_KEYS__{provider}"
            assert env[name] == {
                "name": name,
                "valueFrom": {"secretKeyRef": {"name": client_secret[0], "key": client_secret[1]}},
            }

    disabled_env = _deployment_env(documents, "nohiki-job-correlation-evaluation-service")
    assert not any("LLM__" in name for name in disabled_env)
    rendered_llm_base_urls = {
        entry["name"]
        for document in documents
        if document.get("kind") == "Deployment"
        for container in containers_of(document)
        for entry in container.get("env", [])
        if "LLM__" in entry["name"] and entry["name"].endswith("__BASE_URL")
    }
    assert rendered_llm_base_urls == expected_base_urls


def test_tracked_helm_llm_values_have_no_endpoint_defaults() -> None:
    values_paths = (
        _CHART / "values.local.yaml",
        _CHART / "charts" / "job-ingest-enrichment-service" / "values.yaml",
        _CHART / "charts" / "job-correlation-evaluation-service" / "values.yaml",
        _CHART / "charts" / "doc-content-service" / "values.yaml",
    )
    for path in values_paths:
        text = _text(path)
        assert re.search(r"(?im)^\s*baseUrl:", text) is None
        assert re.search(r"(?im)^\s*LLM__.*BASE_URL:", text) is None


def test_compose_llm_base_url_is_external_with_no_tracked_default() -> None:
    compose = _compose()
    actual: dict[str, str] = {}
    services = compose["services"]
    for service in services.values():
        environment = service.get("environment", {})
        if not isinstance(environment, dict):
            continue
        for name, value in environment.items():
            if "LLM__" in name and name.endswith("__BASE_URL"):
                assert isinstance(value, str)
                actual[name] = value

    expected = {
        name: _EXTERNAL_BASE_URL
        for route in _ROUTES.values()
        for name in _expected_route_env(route, include_chains=route["compose_chains"])[1]
    }
    assert actual == expected
    compose_text = _text(_COMPOSE)
    provider_endpoints = compose["x-llm-provider-endpoints"]
    assert provider_endpoints["NOHIKI_LLM_OPENAI_BASE_URL"] == _EXTERNAL_BASE_URL
    assert "${NOHIKI_LLM_OPENAI_BASE_URL:-" not in compose_text
    assert re.search(r"(?m)^NOHIKI_LLM_BASE_URL=", _text(_ENV_EXAMPLE)) is None
    assert not re.search(r"(?im)^\s*[^#].*LLM__.*BASE_URL:\s*https?://", compose_text)


def test_compose_llm_model_order_and_reasoning_match_helm_contract() -> None:
    compose = _compose()
    environments: dict[str, dict[str, Scalar]] = {}
    services = compose["services"]
    for service in services.values():
        environment = service.get("environment")
        if isinstance(environment, dict) and "SERVICE_NAME" in environment:
            service_name = environment["SERVICE_NAME"]
            assert isinstance(service_name, str)
            environments[service_name] = environment

    for deployment, route in _ROUTES.items():
        service_name = deployment.removeprefix("nohiki-")
        env = environments[service_name]
        expected_values, _ = _expected_route_env(route, include_chains=route["compose_chains"])
        for name, value in expected_values.items():
            assert env[name] == value
        if not route["compose_chains"]:
            assert not any(f"{route['prefix']}LLM__CHAINS__" in name for name in env)
            assert all(chain == route["provider"] for chain in route["chains"].values())

    assert not any("LLM__" in name for name in environments["job-correlation-evaluation-service"])
    assert {"job-correlation-evaluation-service"} == _DISABLED_LLM_SERVICES
