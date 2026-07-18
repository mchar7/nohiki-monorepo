"""Regression tests for user-auth and BFF Helm environment contracts."""

import subprocess
from pathlib import Path

import pytest
import yaml
from helm_test_utils import runtime_eso_args
from test_image_digest_gitops import _digest_values

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_CHART = _REPOSITORY_ROOT / "infra" / "k8s" / "helm"
_IDENTITY = Path(__file__).parent / "fixtures" / "values.prod.identity.yaml"
_NETWORK = Path(__file__).parent / "fixtures" / "values.prod.network.yaml"
_REQUIRED_USER_AUTH_ENV = {
    "USER_AUTH_JWT__ISSUER",
    "USER_AUTH_JWT__AUDIENCE",
    "USER_AUTH_JWT__KEY_ID",
    "USER_AUTH_JWT__PRIVATE_KEY_PATH",
    "USER_AUTH_COOKIE__SECURE",
    "USER_AUTH_OAUTH__GITHUB__ENABLED",
    "USER_AUTH_OAUTH__GOOGLE__ENABLED",
}


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
        str(_CHART / values_name),
    ]
    if values_name == "values.prod.yaml":
        command.extend(
            (
                "--values",
                str(_IDENTITY),
                "--values",
                str(_NETWORK),
                "--values",
                str(_digest_values(tmp_path)),
            )
        )
    command.extend(runtime_eso_args(environment))
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    return tuple(document for document in yaml.safe_load_all(result.stdout) if isinstance(document, dict))


def _deployment_env(documents: tuple[dict, ...], deployment_name: str) -> dict[str, str]:
    deployment = next(
        document
        for document in documents
        if document.get("kind") == "Deployment" and document["metadata"]["name"] == deployment_name
    )
    container = next(
        item
        for item in deployment["spec"]["template"]["spec"]["containers"]
        if item["name"] == deployment_name.removeprefix("nohiki-")
    )
    return {item["name"]: item["value"] for item in container["env"] if "value" in item}


@pytest.mark.parametrize(
    ("values_name", "secure_cookie"),
    [
        pytest.param("values.local.yaml", "false", id="local"),
        pytest.param("values.staging.yaml", "true", id="staging"),
        pytest.param("values.prod.yaml", "true", id="production"),
    ],
)
def test_rendered_auth_environment_retains_security_contract(
    values_name: str, secure_cookie: str, tmp_path: Path
) -> None:
    documents = _render_helm(values_name, tmp_path)
    user_auth = _deployment_env(documents, "nohiki-user-auth-service")
    bff = _deployment_env(documents, "nohiki-bff-service")

    assert user_auth.keys() >= _REQUIRED_USER_AUTH_ENV
    assert user_auth["USER_AUTH_COOKIE__SECURE"] == secure_cookie

    if values_name != "values.local.yaml":
        assert user_auth["USER_AUTH_JWT__ISSUER"] == bff["BFF_JWT__ISSUER"]
        assert user_auth["USER_AUTH_JWT__AUDIENCE"] == bff["BFF_JWT__AUDIENCE"]
        assert bff["BFF_JWT__JWKS_URL"] == f"{user_auth['USER_AUTH_JWT__ISSUER']}/.well-known/jwks.json"
