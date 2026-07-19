from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _ROOT / "scripts" / "ci" / "production_identity.py"
_IAC = _ROOT / "infra" / "terraform"
_AKS = _IAC / "aks.tf"
_HELM_CONFIG = _IAC / "helm_config.tf"
_WORKFLOW = _ROOT / ".github" / "workflows" / "cd_deploy-to-aks_nohiki.yml"
_OUTPUT = _ROOT / "infra" / "k8s" / "helm" / "values.prod.identity.yaml"
_SCRIPT_SPEC = importlib.util.spec_from_file_location("production_identity_under_test", _SCRIPT)
assert _SCRIPT_SPEC is not None
assert _SCRIPT_SPEC.loader is not None
_PRODUCTION_IDENTITY = importlib.util.module_from_spec(_SCRIPT_SPEC)
_SCRIPT_SPEC.loader.exec_module(_PRODUCTION_IDENTITY)

_SENSITIVE_IDENTITY_OUTPUTS = {
    "cert_manager_dns_subscription_id",
    "cert_manager_dns_resource_group",
}


def _terraform_output_block(source: str, name: str) -> str:
    marker = f'output "{name}" {{'
    start = source.index(marker)
    end = source.index("\n}", start)
    return source[start:end]


_ALLOWED = {
    "external_secrets_workload_identity_client_id": "11111111-1111-4111-8111-111111111111",
    "external_secrets_workload_identity_tenant_id": "22222222-2222-4222-8222-222222222222",
    "external_secrets_key_vault_url": "https://nohiki-prod.vault.azure.net/",
}


def _opentofu_output(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        name: {"sensitive": False, "type": "string", "value": value} for name, value in _ALLOWED.items()
    }
    values.update(overrides)
    return values


def _run_generator(tmp_path: Path, document: dict[str, object]) -> subprocess.CompletedProcess[str]:
    source = tmp_path / "opentofu-output.json"
    output = tmp_path / "values.prod.identity.yaml"
    tmp_path.mkdir(parents=True, exist_ok=True)
    source.write_text(json.dumps(document), encoding="utf-8")
    return subprocess.run(
        [
            sys.executable,
            str(_SCRIPT),
            "--opentofu-output",
            str(source),
            "--output",
            str(output),
        ],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_generator_accepts_only_public_identity_references_and_is_deterministic(
    tmp_path: Path,
) -> None:
    first = _run_generator(tmp_path / "first", _opentofu_output())
    second_path = tmp_path / "second"
    second_path.mkdir()
    second_source = second_path / "opentofu-output.json"
    second_source.write_text(json.dumps(dict(reversed(list(_opentofu_output().items())))), encoding="utf-8")
    _PRODUCTION_IDENTITY._generate(second_source, second_path / "values.prod.identity.yaml")
    assert first.returncode == 0, first.stderr
    first_text = (tmp_path / "first" / "values.prod.identity.yaml").read_text(encoding="utf-8")
    second_text = (tmp_path / "second" / "values.prod.identity.yaml").read_text(encoding="utf-8")
    assert first_text == second_text
    assert first_text.startswith("# Generated from allowlisted non-sensitive OpenTofu outputs; do not edit.\n")
    document = yaml.safe_load(first_text)
    azure = document["global"]["eso"]["azure"]
    assert azure == {
        "clientId": _ALLOWED["external_secrets_workload_identity_client_id"],
        "tenantId": _ALLOWED["external_secrets_workload_identity_tenant_id"],
        "keyVaultUrl": _ALLOWED["external_secrets_key_vault_url"],
    }


@pytest.mark.parametrize(
    ("document", "match"),
    [
        ({}, "exactly the allowlisted identity outputs"),
        (
            _opentofu_output(extra={"sensitive": False, "type": "string", "value": "public"}),
            "exactly the allowlisted identity outputs",
        ),
        (
            _opentofu_output(
                external_secrets_workload_identity_client_id={
                    "sensitive": True,
                    "type": "string",
                    "value": _ALLOWED["external_secrets_workload_identity_client_id"],
                }
            ),
            "non-sensitive string output",
        ),
        (
            _opentofu_output(
                external_secrets_workload_identity_client_id={
                    "sensitive": False,
                    "type": "number",
                    "value": 1,
                }
            ),
            "non-sensitive string output",
        ),
        (
            _opentofu_output(
                external_secrets_workload_identity_tenant_id={
                    "sensitive": False,
                    "type": "string",
                    "value": "not-a-guid",
                }
            ),
            "must be a GUID",
        ),
        (
            _opentofu_output(
                external_secrets_key_vault_url={
                    "sensitive": False,
                    "type": "string",
                    "value": "http://nohiki-prod.vault.azure.net/",
                }
            ),
            "HTTPS Azure Key Vault URL",
        ),
    ],
    ids=[
        "missing",
        "extra",
        "sensitive",
        "wrong-type",
        "invalid-guid",
        "non-https-vault",
    ],
)
def test_generator_rejects_non_allowlisted_or_malformed_opentofu_output(
    tmp_path: Path, document: dict[str, object], match: str
) -> None:
    output = tmp_path / "values.prod.identity.yaml"
    tmp_path.mkdir(parents=True, exist_ok=True)
    source = tmp_path / "opentofu-output.json"
    source.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match=match):
        _PRODUCTION_IDENTITY._generate(source, output)
    assert not output.exists()


def test_opentofu_owns_external_secrets_identity_federation_rbac_and_public_outputs() -> None:
    opentofu = _AKS.read_text(encoding="utf-8")
    helm_config = _HELM_CONFIG.read_text(encoding="utf-8")
    assert "from = azurerm_user_assigned_identity.kv_pod_identity" in opentofu
    assert "to   = azurerm_user_assigned_identity.external_secrets" in opentofu
    assert 'resource "azurerm_federated_identity_credential" "external_secrets"' in opentofu
    assert 'subject             = "system:serviceaccount:nohiki-${var.app_environment}:external-secrets-sa"' in opentofu
    assert 'audience            = ["api://AzureADTokenExchange"]' in opentofu
    assert "issuer              = azurerm_kubernetes_cluster.aks_cluster[0].oidc_issuer_url" in opentofu
    assert 'role_definition_name = "Key Vault Secrets User"' in opentofu
    assert "principal_id         = azurerm_user_assigned_identity.external_secrets[0].principal_id" in opentofu
    for output in _ALLOWED:
        assert f'output "{output}"' in opentofu
    identity_blocks = {name: _terraform_output_block(opentofu, name) for name in _ALLOWED} | {
        name: _terraform_output_block(helm_config, name)
        for name in (
            "cert_manager_workload_identity_client_id",
            "cert_manager_workload_identity_tenant_id",
            "cert_manager_dns_subscription_id",
            "cert_manager_dns_resource_group",
            "cert_manager_dns_zone_name",
        )
    }
    assert {
        name
        for name, block in identity_blocks.items()
        if any(line.split() == ["sensitive", "=", "true"] for line in block.splitlines())
    } == _SENSITIVE_IDENTITY_OUTPUTS
    assert 'resource "helm_release" "external_secrets"' not in opentofu
    assert "client_secret" not in opentofu.lower()
    assert "oidc_issuer_enabled                 = true" in opentofu
    assert "workload_identity_enabled           = true" in opentofu


def test_workflow_exports_exact_subsets_and_promotes_both_overlays_atomically() -> None:
    workflow = _WORKFLOW.read_text(encoding="utf-8")
    identity = (
        "{external_secrets_workload_identity_client_id, external_secrets_workload_identity_tenant_id, "
        "external_secrets_key_vault_url}"
    )
    assert f"tofu output -json | jq '{identity}' > production-identity-outputs.json" in workflow
    assert "tofu output -json | jq '{production_network}' > production-network-output.json" in workflow
    assert '-var "dns_zone_name=${{ env.ROOT_DOMAIN }}"' in workflow
    assert '-var "az_dns_zone_name=' not in workflow
    assert "tofu output -json >" not in workflow
    assert workflow.count("uses: peter-evans/create-pull-request@") == 2
    assert "name: production-runtime-overlays" in workflow
    assert "add-paths: |" in workflow
    assert "infra/k8s/helm/values.prod.identity.yaml" in workflow
    assert "infra/k8s/helm/values.prod.network.yaml" in workflow
    assert "git add -A" not in workflow
    assert (
        "if: github.event_name == 'pull_request' && github.event.action == 'closed' && "
        "github.event.pull_request.merged == true && "
        "(github.event.pull_request.head.ref == 'bot/update-production-runtime' || "
        "github.event.pull_request.head.ref == 'bot/update-production-image-digests')"
    ) in workflow
    assert "ref: ${{ github.event.pull_request.merge_commit_sha }}" in workflow
    assert "branch: bot/activate-production-runtime" in workflow
    for path in (
        "infra/k8s/gitops/clusters/prod-aks/release-source.yaml",
        "infra/k8s/gitops/clusters/prod-aks/infrastructure.yaml",
        "infra/k8s/gitops/clusters/prod-aks/platform.yaml",
        "infra/k8s/gitops/clusters/prod-aks/observability.yaml",
    ):
        assert path in workflow
