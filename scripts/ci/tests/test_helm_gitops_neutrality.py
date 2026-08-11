"""Render-level GitOps neutrality contract for the platform Helm chart.

The chart is reconciled by a pull-based GitOps engine that drives Helm
install and upgrade, so ordering must ride native ``helm.sh/hook`` weights
instead of engine-specific sync waves. These render tests pin the migration
Job hooks, forbid every ``argocd.argoproj.io`` annotation in the rendered
manifests, guard the retained qdrant, skill-graph, and Secret hooks, and check
that the local, dev, and staging value sets render.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from _documents import Manifest, containers_of, load_manifests, mapping_at, mapping_sequence_at, string_at
from test_image_digest_gitops import _digest_values

_ROOT = Path(__file__).resolve().parents[3]
_CHART = _ROOT / "infra" / "k8s" / "helm"
_FIXTURES = Path(__file__).parent / "fixtures"
_ARGO_PREFIX = "argocd.argoproj.io"
_CANONICAL_ML_MANIFEST = _ROOT / "data" / "config" / "semantic_representation_manifest.json"
_PACKAGED_ML_MANIFEST = _CHART / "files" / "semantic_representation_manifest.json"

_MIGRATION_HOOK_TOKENS = {
    "helm.sh/hook": frozenset({"post-install", "post-upgrade"}),
    "helm.sh/hook-delete-policy": frozenset({"before-hook-creation"}),
}
_MIGRATION_HOOK_WEIGHT = "1"
_QDRANT_HOOK = {
    "helm.sh/hook": "post-install,post-upgrade",
    "helm.sh/hook-weight": "0",
    "helm.sh/hook-delete-policy": "before-hook-creation",
}
_BOOTSTRAP_HOOK = {
    "helm.sh/hook": "post-install,post-upgrade",
    "helm.sh/hook-weight": "2",
    "helm.sh/hook-delete-policy": "before-hook-creation",
}
_SECRET_HOOK = {
    "helm.sh/hook": "pre-install,pre-upgrade",
    "helm.sh/hook-weight": "-10",
}


def _template(values_file: str, tmp_path: Path | None = None, *extra_args: str) -> str:
    command = [
        "helm",
        "template",
        "nohiki",
        ".",
        "--values",
        "values.yaml",
        "--values",
        values_file,
        "--namespace",
        "nohiki-prod" if values_file == "values.prod.yaml" else "nohiki",
    ]
    if values_file == "values.prod.yaml":
        assert tmp_path is not None
        command += [
            "--values",
            str(_FIXTURES / "values.prod.identity.yaml"),
            "--values",
            str(_FIXTURES / "values.prod.network.yaml"),
            "--values",
            str(_digest_values(tmp_path)),
        ]
    if values_file in {"values.dev.yaml", "values.staging.yaml", "values.prod.yaml"}:
        command += [
            "--set-string",
            "global.eso.azure.keyVaultUrl=https://nohiki-test-kv.vault.azure.net",
            "--set-string",
            "global.eso.azure.clientId=00000000-0000-4000-8000-000000000000",
            "--set-string",
            "global.eso.azure.tenantId=11111111-1111-4111-8111-111111111111",
        ]
    command += extra_args
    result = subprocess.run(command, cwd=_CHART, capture_output=True, text=True, check=True)
    return result.stdout


def _platform_release(overlay: str) -> Manifest:
    executable = "kustomize" if shutil.which("kustomize") else "kubectl"
    command = [executable, "build"] if executable == "kustomize" else [executable, "kustomize"]
    result = subprocess.run(
        [*command, str(_ROOT / "infra" / "k8s" / "gitops" / "platform" / overlay)],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    releases = [
        document
        for document in load_manifests(result.stdout)
        if document["kind"] == "HelmRelease" and document["metadata"]["name"] == "nohiki"
    ]
    assert len(releases) == 1
    return releases[0]


def _jobs_by_suffix(documents: list[Manifest], suffix: str) -> list[Manifest]:
    return [
        document
        for document in documents
        if document["kind"] == "Job" and document["metadata"]["name"].endswith(suffix)
    ]


def _annotation_tokens(value: str) -> frozenset[str]:
    return frozenset(token.strip() for token in value.split(",") if token.strip())


def test_migration_jobs_order_through_helm_hooks_without_argo() -> None:
    documents = load_manifests(_template("values.local.yaml"))
    jobs = _jobs_by_suffix(documents, "-db-migrate")
    assert jobs, "no per-service migration Jobs rendered from the local values"
    for job in jobs:
        annotations = job["metadata"].get("annotations", {})
        for key, expected_tokens in _MIGRATION_HOOK_TOKENS.items():
            actual_tokens = _annotation_tokens(annotations.get(key, ""))
            assert actual_tokens == expected_tokens, (
                job["metadata"]["name"],
                key,
                actual_tokens,
            )
        assert annotations.get("helm.sh/hook-weight") == _MIGRATION_HOOK_WEIGHT
        assert set(annotations) == {*_MIGRATION_HOOK_TOKENS, "helm.sh/hook-weight"}
        assert not any(key.startswith(_ARGO_PREFIX) for key in annotations)


@pytest.mark.parametrize("values_file", ["values.local.yaml", "values.dev.yaml", "values.staging.yaml"])
def test_rendered_manifests_carry_no_argo_annotations(values_file: str) -> None:
    assert _ARGO_PREFIX not in _template(values_file)


def test_production_render_carries_no_argo_annotations(tmp_path: Path) -> None:
    assert _ARGO_PREFIX not in _template("values.prod.yaml", tmp_path)


def test_qdrant_and_skill_bootstrap_jobs_keep_helm_hooks() -> None:
    documents = load_manifests(
        _template(
            "values.local.yaml",
            None,
            "--set",
            "skill-graph-service.enabled=true",
            "--set",
            "skill-graph-service.bootstrap.enabled=true",
        )
    )
    qdrant = _jobs_by_suffix(documents, "-qdrant-init")
    assert len(qdrant) == 1, "expected exactly one qdrant-init hook Job"
    assert qdrant[0]["metadata"].get("annotations", {}) == _QDRANT_HOOK

    bootstrap = _jobs_by_suffix(documents, "-bootstrap")
    assert len(bootstrap) == 1, "expected the skill-graph bootstrap hook Job when enabled"
    assert bootstrap[0]["metadata"].get("annotations", {}) == _BOOTSTRAP_HOOK


def test_job_volume_sources_are_rendered_by_chart() -> None:
    documents = load_manifests(_template("values.local.yaml"))
    config_maps = {document["metadata"]["name"] for document in documents if document["kind"] == "ConfigMap"}
    secrets = {document["metadata"]["name"] for document in documents if document["kind"] == "Secret"}
    secrets.update(
        string_at(document, "spec", "target", "name") for document in documents if document["kind"] == "ExternalSecret"
    )

    missing: list[str] = []
    for job in (document for document in documents if document["kind"] == "Job"):
        pod_spec = mapping_at(job, "spec", "template", "spec")
        if pod_spec.get("volumes") is None:
            continue
        for volume in mapping_sequence_at(pod_spec, "volumes"):
            if "configMap" in volume:
                name = string_at(volume, "configMap", "name")
                if name not in config_maps:
                    missing.append(f"{job['metadata']['name']}: ConfigMap/{name}")
            if "secret" in volume:
                name = string_at(volume, "secret", "secretName")
                if name not in secrets:
                    missing.append(f"{job['metadata']['name']}: Secret/{name}")

    assert not missing, f"Job volume sources are not rendered by the chart: {missing}"


def test_packaged_and_rendered_ml_manifest_match_canonical_source() -> None:
    canonical = _CANONICAL_ML_MANIFEST.read_text(encoding="utf-8")
    assert _PACKAGED_ML_MANIFEST.read_text(encoding="utf-8") == canonical

    config_map = next(
        document
        for document in load_manifests(_template("values.local.yaml"))
        if document["kind"] == "ConfigMap" and document["metadata"]["name"] == "nohiki-ml-manifest"
    )
    assert json.loads(config_map["data"]["semantic_representation_manifest.json"]) == json.loads(canonical)


def test_model_runtime_can_populate_an_empty_cache_in_every_environment() -> None:
    for values_file in ("values.local.yaml", "values.dev.yaml", "values.staging.yaml"):
        documents = load_manifests(_template(values_file))
        deployment = next(
            document
            for document in documents
            if document["kind"] == "Deployment" and document["metadata"]["name"] == "nohiki-ml-compute-service"
        )
        environment = {
            item["name"]
            for item in containers_of(deployment)[0].get("env", [])
            if item["name"] in {"HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"}
        }
        assert not environment


def test_only_local_platform_install_and_upgrade_run_hooks_before_readiness() -> None:
    local_spec = mapping_at(_platform_release("local"), "spec")
    assert mapping_at(local_spec, "install")["disableWait"] is True
    assert mapping_at(local_spec, "upgrade")["disableWait"] is True
    for overlay in ("dev", "staging", "prod"):
        spec = mapping_at(_platform_release(overlay), "spec")
        assert "disableWait" not in mapping_at(spec, "install")
        assert "disableWait" not in mapping_at(spec, "upgrade")


def test_managed_secret_hooks_survive_neutrality() -> None:
    documents = load_manifests(
        _template(
            "values.local.yaml",
            None,
            "--set",
            "global.secrets.inlineSecretsEnabled=true",
        )
    )
    hooked = [
        document
        for document in documents
        if document["kind"] == "Secret" and "helm.sh/hook" in document["metadata"].get("annotations", {})
    ]
    assert hooked, "inline Secret template rendered no pre-hook Secrets"
    for secret in hooked:
        assert secret["metadata"].get("annotations", {}) == _SECRET_HOOK, secret["metadata"]["name"]


@pytest.mark.parametrize("values_file", ["values.local.yaml", "values.dev.yaml", "values.staging.yaml"])
def test_nonproduction_value_sets_render(values_file: str) -> None:
    documents = load_manifests(_template(values_file))
    kinds = {document["kind"] for document in documents}
    assert {"Deployment", "Job"} <= kinds, sorted(kinds)
