"""Focused Helm regression coverage for public Gateway TLS listeners."""

import subprocess
from pathlib import Path

import pytest
import yaml
from helm_test_utils import runtime_eso_args
from test_image_digest_gitops import _digest_values

_ROOT = Path(__file__).resolve().parents[3]
_CHART = _ROOT / "infra" / "k8s" / "helm"
_FIXTURES = Path(__file__).parent / "fixtures"


def _render_gateway(values_name: str, tmp_path: Path, *extra_args: str) -> dict:
    command = [
        "helm",
        "template",
        "nohiki",
        str(_CHART),
        "--namespace",
        f"nohiki-{values_name.removeprefix('values.').removesuffix('.yaml')}",
        "--values",
        str(_CHART / values_name),
        "--show-only",
        "templates/gateway.yaml",
        *extra_args,
    ]
    if values_name == "values.prod.yaml":
        command.extend(
            (
                "--values",
                str(_FIXTURES / "values.prod.identity.yaml"),
                "--values",
                str(_FIXTURES / "values.prod.network.yaml"),
                "--values",
                str(_digest_values(tmp_path)),
            )
        )
    command.extend(runtime_eso_args(values_name.removeprefix("values.").removesuffix(".yaml")))
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    return next(
        document
        for document in yaml.safe_load_all(result.stdout)
        if isinstance(document, dict) and document.get("kind") == "Gateway"
    )


def _listener_shape(listener: dict) -> dict[str, str | int]:
    return {key: listener[key] for key in ("name", "hostname", "protocol", "port")}


@pytest.mark.parametrize(
    ("values_name", "expected_listeners"),
    [
        pytest.param(
            "values.local.yaml",
            [
                {
                    "name": "http",
                    "hostname": "nohiki.localhost",
                    "protocol": "HTTP",
                    "port": 80,
                },
                {
                    "name": "s3-http",
                    "hostname": "s3.nohiki.localhost",
                    "protocol": "HTTP",
                    "port": 80,
                },
            ],
            id="local",
        ),
        pytest.param(
            "values.staging.yaml",
            [
                {
                    "name": "http",
                    "hostname": "staging.nohiki.com",
                    "protocol": "HTTP",
                    "port": 80,
                }
            ],
            id="staging",
        ),
        pytest.param(
            "values.prod.yaml",
            [
                {
                    "name": "http",
                    "hostname": "nohiki.com",
                    "protocol": "HTTP",
                    "port": 80,
                }
            ],
            id="production",
        ),
    ],
)
def test_unprovisioned_tls_never_references_a_secret(
    values_name: str,
    expected_listeners: list[dict[str, str | int]],
    tmp_path: Path,
) -> None:
    gateway = _render_gateway(values_name, tmp_path)
    listeners = gateway["spec"]["listeners"]

    assert [_listener_shape(listener) for listener in listeners] == expected_listeners
    assert all("tls" not in listener for listener in listeners)


@pytest.mark.parametrize(
    ("values_name", "hostname", "secret_name"),
    [
        pytest.param(
            "values.staging.yaml",
            "staging.nohiki.com",
            "staging-ready-tls",
            id="staging",
        ),
        pytest.param(
            "values.prod.yaml",
            "nohiki.com",
            "production-ready-tls",
            id="production",
        ),
    ],
)
def test_provisioned_tls_uses_only_the_explicit_secret(
    values_name: str,
    hostname: str,
    secret_name: str,
    tmp_path: Path,
) -> None:
    gateway = _render_gateway(
        values_name,
        tmp_path,
        "--set",
        "global.ingress.tls.secretProvisioned=true",
        "--set",
        f"global.ingress.tls.secretName={secret_name}",
    )
    listeners = gateway["spec"]["listeners"]

    assert [_listener_shape(listener) for listener in listeners] == [
        {
            "name": "https",
            "hostname": hostname,
            "protocol": "HTTPS",
            "port": 443,
        }
    ]
    assert listeners[0]["tls"] == {
        "mode": "Terminate",
        "certificateRefs": [{"name": secret_name, "kind": "Secret"}],
    }
