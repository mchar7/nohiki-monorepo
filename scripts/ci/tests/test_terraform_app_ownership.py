from __future__ import annotations

import re
from functools import cache
from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_TERRAFORM = _REPOSITORY_ROOT / "infra" / "terraform"
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
    assert 'repository       = "https://kedacore.github.io/charts"' in keda
    assert 'chart            = "keda"' in keda
    assert 'version          = "2.20.1"' in keda
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


def test_cd_workflows_pass_no_application_chart_variables() -> None:
    for name in _CD_WORKFLOWS:
        text = _read(_WORKFLOWS / name)
        for token in _APPLICATION_CHART_TOKENS:
            assert token not in text, f"{name} still passes {token}"
