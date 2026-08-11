from __future__ import annotations

import re
from functools import cache
from pathlib import Path

import yaml

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_TERRAFORM = _REPOSITORY_ROOT / "infra" / "terraform"
_FOUNDATION_CHART = _REPOSITORY_ROOT / "infra" / "k8s" / "helm-foundation"
_WORKFLOWS = _REPOSITORY_ROOT / ".github" / "workflows"

# Settings that only ever configured the application umbrella chart. With the
# chart owned by the GitOps controller, no environment OpenTofu root and no CD
# workflow may still declare or pass them.
_APPLICATION_CHART_TOKENS = (
    "app_image_tag",
    "app_helm_chart_path",
    "app_helm_overrides_filename",
)

# The environment root may still own KEDA. Cert-manager and its issuers are
# reconciled by Flux with the rest of the declarative foundation.
_CLUSTER_ADDON_RELEASES = {"keda"}

_HELM_RELEASE = re.compile(r'resource\s+"helm_release"\s+"([^"]+)"')
_KUBECTL_MANIFEST = re.compile(r'resource\s+"kubectl_manifest"\s+"([^"]+)"')

_CD_WORKFLOWS = ("cd_deploy-to-aks_nohiki.yml", "cd_destroy-aks_nohiki.yml")


@cache
def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@cache
def _terraform_sources() -> tuple[tuple[Path, str], ...]:
    return tuple((path, _read(path)) for path in sorted(_TERRAFORM.glob("*.tf")))


def test_environment_terraform_owns_no_application_chart_writer() -> None:
    assert not (_TERRAFORM / "app_deployment.tf").exists(), (
        "app_deployment.tf must be gone; the application chart is deployed by the GitOps controller"
    )
    releases: set[str] = set()
    for _, text in _terraform_sources():
        releases.update(_HELM_RELEASE.findall(text))
    assert releases == _CLUSTER_ADDON_RELEASES, releases
    keda = _read(_TERRAFORM / "keda.tf")
    assert re.findall(r"(?m)^\s*count\s*=\s*(.+)$", keda) == [
        'var.deployment_type == "aks" ? 1 : 0',
        'var.deployment_type == "aks" ? 1 : 0',
    ]
    release = re.search(r'(?ms)^resource "helm_release" "keda"\s*\{(?P<body>.*?)^\}', keda)
    assert release
    coordinates = dict(
        re.findall(
            r'(?m)^\s*(repository|chart|version)\s*=\s*"([^"]+)"\s*$',
            release["body"],
        )
    )
    wrapper = yaml.safe_load((_FOUNDATION_CHART / "operators/keda/Chart.yaml").read_text(encoding="utf-8"))
    assert isinstance(wrapper, dict)
    dependencies = wrapper["dependencies"]
    assert isinstance(dependencies, list)
    assert len(dependencies) == 1
    dependency = dependencies[0]
    assert coordinates == {
        "repository": dependency["repository"],
        "chart": dependency["name"],
        "version": dependency["version"],
    }
    assert re.fullmatch(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)", coordinates["version"])
    assert "depends_on = [azurerm_kubernetes_cluster.aks_cluster[0]]" in keda
    assert "depends_on = [helm_release.keda[0]]" in keda


def test_environment_terraform_owns_no_cert_manager_or_clusterissuer() -> None:
    releases: set[str] = set()
    manifests: set[str] = set()
    cluster_issuer_documents: list[str] = []
    for tf, text in _terraform_sources():
        releases.update(_HELM_RELEASE.findall(text))
        manifests.update(_KUBECTL_MANIFEST.findall(text))
        if re.search(r"(?m)^\s*kind:\s*ClusterIssuer\s*$", text):
            cluster_issuer_documents.append(tf.name)

    assert not {name for name in releases if "certmanager" in name.replace("_", "").replace("-", "")}
    assert not {name for name in manifests if "issuer" in name.lower()}
    assert cluster_issuer_documents == []


def test_environment_terraform_drops_application_chart_variables() -> None:
    for tf, text in _terraform_sources():
        for token in _APPLICATION_CHART_TOKENS:
            assert token not in text, f"{tf.name} still references {token}"


def test_aks_launch_envelope_has_zoned_system_and_autoscaled_user_pools() -> None:
    aks = _read(_TERRAFORM / "aks.tf")
    variables = _read(_TERRAFORM / "variables.tf")

    system_count = re.search(r'(?ms)^variable "aks_node_count"\s*\{.*?^\}', variables)
    system_size = re.search(r'(?ms)^variable "aks_node_vm_size"\s*\{.*?^\}', variables)
    zones = re.search(r'(?ms)^variable "aks_node_zones"\s*\{.*?^\}', variables)
    user_size = re.search(r'(?ms)^variable "aks_user_node_vm_size"\s*\{.*?^\}', variables)
    user_minimum = re.search(r'(?ms)^variable "aks_user_node_min_count"\s*\{.*?^\}', variables)
    user_maximum = re.search(r'(?ms)^variable "aks_user_node_max_count"\s*\{.*?^\}', variables)
    user_pool = re.search(
        r'(?ms)^resource "azurerm_kubernetes_cluster_node_pool" "user"\s*\{.*?^\}',
        aks,
    )
    aks_contract = re.sub(r"\s+", " ", aks)

    assert system_count is not None
    assert re.search(r"(?m)^\s*default\s*=\s*3\s*$", system_count.group(0))
    assert system_size is not None
    assert 'default = "Standard_D2s_v5"' in re.sub(r"\s+", " ", system_size.group(0))
    assert zones is not None
    assert 'default = ["1", "2", "3"]' in re.sub(r"\s+", " ", zones.group(0))
    assert "node_count = var.aks_node_count" in aks_contract
    assert "vm_size = var.aks_node_vm_size" in aks_contract
    assert "zones = var.aks_node_zones" in aks_contract

    assert user_size is not None
    assert 'default = "Standard_D4s_v5"' in re.sub(r"\s+", " ", user_size.group(0))
    assert user_minimum is not None
    assert re.search(r"(?m)^\s*default\s*=\s*4\s*$", user_minimum.group(0))
    assert user_maximum is not None
    assert re.search(r"(?m)^\s*default\s*=\s*6\s*$", user_maximum.group(0))
    assert user_pool is not None
    user_contract = re.sub(r"\s+", " ", user_pool.group(0))
    assert "vm_size = var.aks_user_node_vm_size" in user_contract
    assert "zones = var.aks_node_zones" in user_contract
    assert 'mode = "User"' in user_contract
    assert "auto_scaling_enabled = true" in user_contract
    assert "min_count = var.aks_user_node_min_count" in user_contract
    assert "max_count = var.aks_user_node_max_count" in user_contract
    assert "node_count = var.aks_user_node_min_count" in user_contract


def test_cd_workflows_pass_no_application_chart_variables() -> None:
    for name in _CD_WORKFLOWS:
        text = _read(_WORKFLOWS / name)
        for token in _APPLICATION_CHART_TOKENS:
            assert token not in text, f"{name} still passes {token}"
