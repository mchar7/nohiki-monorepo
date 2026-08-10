"""Regression tests for browser security headers at the Helm gateway."""

import subprocess
from pathlib import Path

import pytest
import yaml
from ci_checks.core.image_inventory import load_inventory
from helm_test_utils import runtime_eso_args

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_CHART = _REPOSITORY_ROOT / "infra" / "k8s" / "helm"
_PROD_IDENTITY = Path(__file__).parent / "fixtures" / "values.prod.identity.yaml"
_PROD_NETWORK = Path(__file__).parent / "fixtures" / "values.prod.network.yaml"


def _digest_overlay(tmp_path: Path) -> Path:
    digests = {name: f"sha256:{index + 1:064x}" for index, name in enumerate(load_inventory().names)}
    path = tmp_path / "values.prod.digests.yaml"
    path.write_text(yaml.safe_dump({"global": {"imageDigests": digests}}), encoding="utf-8")
    return path


def _render_helm(values_name: str, tmp_path: Path) -> tuple[dict, ...]:
    environment = values_name.removeprefix("values.").removesuffix(".yaml")
    command = [
        "helm",
        "template",
        "nohiki",
        str(_CHART),
        "--namespace",
        f"nohiki-{environment}",
        "--values",
        str(_CHART / "values.yaml"),
        "--values",
        str(_CHART / values_name),
        "--show-only",
        "templates/gateway.yaml",
        "--show-only",
        "templates/httproutes.yaml",
        "--show-only",
        "templates/traffic-policy.yaml",
        "--show-only",
        "charts/bff-service/templates/service.yaml",
        "--show-only",
        "charts/bff-service/templates/deployment.yaml",
        "--show-only",
        "charts/bff-service/templates/networkpolicy.yaml",
    ]
    if values_name == "values.prod.yaml":
        command.extend(
            [
                "--values",
                str(_PROD_IDENTITY),
                "--values",
                str(_PROD_NETWORK),
                "--values",
                str(_digest_overlay(tmp_path)),
            ]
        )
    command.extend(runtime_eso_args(environment))
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    return tuple(document for document in yaml.safe_load_all(result.stdout) if isinstance(document, dict))


def _response_headers(documents: tuple[dict, ...]) -> list[dict[str, str]]:
    return [
        header
        for document in documents
        if document.get("kind") == "TrafficPolicy"
        for header in document.get("spec", {}).get("transformation", {}).get("response", {}).get("set", [])
    ]


def _rate_limit_policy(documents: tuple[dict, ...]) -> dict:
    policies = [
        document
        for document in documents
        if document.get("kind") == "TrafficPolicy" and document.get("metadata", {}).get("name") == "nohiki-rate-limit"
    ]
    assert len(policies) == 1
    return policies[0]


def _directives(policy: str) -> dict[str, list[str]]:
    return {
        parts[0]: parts[1:] for directive in policy.strip("\"' ").split(";") if (parts := directive.strip().split())
    }


@pytest.mark.parametrize(
    ("values_name", "expected_token_bucket"),
    [
        (
            "values.staging.yaml",
            {"maxTokens": 50, "tokensPerFill": 100, "fillInterval": "60s"},
        ),
        (
            "values.prod.yaml",
            {"maxTokens": 50, "tokensPerFill": 100, "fillInterval": "60s"},
        ),
        (
            "values.local.yaml",
            {"maxTokens": 2_000, "tokensPerFill": 2_000, "fillInterval": "60s"},
        ),
    ],
)
def test_gateway_rate_limit_capacity_matches_environment(
    values_name: str, expected_token_bucket: dict[str, int | str], tmp_path: Path
) -> None:
    default_rate_limit = yaml.safe_load((_CHART / "values.yaml").read_text(encoding="utf-8"))["global"]["ingress"][
        "trafficPolicy"
    ]["rateLimit"]
    assert default_rate_limit == {"average": 100, "burst": 50, "period": "60s"}

    policy = _rate_limit_policy(_render_helm(values_name, tmp_path))
    assert policy["spec"]["targetRefs"] == [
        {
            "group": "gateway.networking.k8s.io",
            "kind": "HTTPRoute",
            "name": "nohiki-auth-route",
        },
        {
            "group": "gateway.networking.k8s.io",
            "kind": "HTTPRoute",
            "name": "nohiki-account-route",
        },
        {
            "group": "gateway.networking.k8s.io",
            "kind": "HTTPRoute",
            "name": "nohiki-api-route",
        },
    ]
    assert policy["spec"]["rateLimit"] == {"local": {"tokenBucket": expected_token_bucket}}


@pytest.mark.parametrize("values_name", ["values.staging.yaml", "values.prod.yaml"])
def test_remote_gateway_sets_one_safe_browser_policy(values_name: str, tmp_path: Path) -> None:
    headers = _response_headers(_render_helm(values_name, tmp_path))
    content_security_policies = [
        header["value"] for header in headers if header["name"].lower() == "content-security-policy"
    ]
    permissions_policies = [header["value"] for header in headers if header["name"].lower() == "permissions-policy"]

    assert len(content_security_policies) == 1
    assert len(permissions_policies) == 1

    directives = _directives(content_security_policies[0])
    assert directives["default-src"] == ["'self'"]
    assert directives["script-src"] == ["'self'"]
    assert "'self'" in directives["connect-src"]
    assert directives["object-src"] == ["'none'"]
    assert directives["frame-ancestors"] == ["'none'"]
    assert "blob:" in directives["frame-src"]
    assert "'unsafe-inline'" not in directives["script-src"]
    assert "'unsafe-eval'" not in directives["script-src"]

    permissions_policy = permissions_policies[0].strip("\"' ")
    for disabled_feature in (
        "camera=()",
        "microphone=()",
        "geolocation=()",
        "payment=()",
    ):
        assert disabled_feature in permissions_policy


def test_local_gateway_omits_browser_policy_headers(tmp_path: Path) -> None:
    header_names = {header["name"].lower() for header in _response_headers(_render_helm("values.local.yaml", tmp_path))}

    assert "content-security-policy" not in header_names
    assert "permissions-policy" not in header_names
