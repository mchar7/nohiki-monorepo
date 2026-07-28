"""Render validation for the GPU-scheduled ml-compute workload.

Mirrors the ``test_helm_image_registry.py`` render harness. Covers the production
GPU contract shared with the Terraform node pool (see ``test_gpu_node_pool.py``):

* the NVIDIA device plugin runs as a DaemonSet, pinned by digest, only on the GPU
  pool, so ``nvidia.com/gpu`` is advertised as an allocatable resource;
* the production ml-compute Deployment requests/limits exactly one
  ``nvidia.com/gpu``, selects and tolerates the GPU pool, runs the CUDA image
  variant, and selects the GPU compute backend; and
* local/staging schedule no GPU at all (no DaemonSet, no GPU request, CPU image).

The GPU device-plugin image is third-party and pinned in chart values; the CUDA
ml-compute image is first-party (build-matrix row ``ml-compute-service-gpu``), so
its digest flows through the aggregated production map (also overlaid explicitly).
"""

from __future__ import annotations

import fcntl
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml
from helm_test_utils import runtime_eso_args
from test_image_digest_gitops import _digest_values

_ROOT = Path(__file__).resolve().parents[3]
_CHART = _ROOT / "infra" / "k8s" / "helm"
_IAC = _ROOT / "infra" / "terraform"
_IDENTITY = Path(__file__).parent / "fixtures" / "values.prod.identity.yaml"
_NETWORK = Path(__file__).parent / "fixtures" / "values.prod.network.yaml"

_FIRST_PARTY_PREFIX = "ghcr.io/mchar7/nohiki-monorepo/"
_ML_COMPUTE = "nohiki-ml-compute-service"
_DEVICE_PLUGIN_REPO = "nvcr.io/nvidia/k8s-device-plugin"
_GPU_RESOURCE = "nvidia.com/gpu"
_DIGEST_RE = re.compile(r"@sha256:[0-9a-f]{64}$")


@dataclass(frozen=True)
class _RenderedEnvironment:
    documents: list[dict[str, Any]]
    manifest: str


def _gpu_image_overlay(tmp_path: Path) -> Path:
    """Explicit digest for the first-party CUDA ml-compute image (build-matrix row)."""
    path = tmp_path / "values.prod.gpu-image.yaml"
    path.write_text(
        yaml.safe_dump(
            {"global": {"imageDigests": {f"{_FIRST_PARTY_PREFIX}ml-compute-service-gpu": "sha256:" + "b" * 64}}}
        ),
        encoding="utf-8",
    )
    return path


def _render(values_file: str, tmp_path: Path) -> _RenderedEnvironment:
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
        "nohiki",
    ]
    if values_file == "values.prod.yaml":
        command += [
            "--values",
            str(_IDENTITY),
            "--values",
            str(_NETWORK),
            "--values",
            str(_digest_values(tmp_path)),
            "--values",
            str(_gpu_image_overlay(tmp_path)),
        ]
    command.extend(runtime_eso_args(values_file.removeprefix("values.").removesuffix(".yaml")))
    result = subprocess.run(command, cwd=_CHART, capture_output=True, text=True, check=True)
    relevant_documents = (
        document
        for chunk in result.stdout.split("\n---")
        if _ML_COMPUTE in chunk or _DEVICE_PLUGIN_REPO in chunk
        if isinstance(document := yaml.load(chunk, Loader=yaml.CSafeLoader), dict)
    )
    return _RenderedEnvironment(list(relevant_documents), result.stdout)


def _cached_render(
    values_file: str,
    tmp_path_factory: pytest.TempPathFactory,
) -> _RenderedEnvironment:
    base = tmp_path_factory.getbasetemp()
    session_directory = base.parent if base.name.startswith("popen-") else base
    environment = values_file.removeprefix("values.").removesuffix(".yaml")
    cache_path = session_directory / f"gpu-helm-config-{environment}.json"
    lock_path = cache_path.with_suffix(".lock")

    with lock_path.open("w", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if cache_path.exists():
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            return _RenderedEnvironment(
                documents=cached["documents"],
                manifest=cached["manifest"],
            )

        tmp_path = session_directory / f"gpu-helm-config-{environment}-inputs"
        tmp_path.mkdir(exist_ok=True)
        rendered = _render(values_file, tmp_path)
        temporary = cache_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {
                    "documents": rendered.documents,
                    "manifest": rendered.manifest,
                }
            ),
            encoding="utf-8",
        )
        temporary.replace(cache_path)
        return rendered


@pytest.fixture(scope="module")
def production_documents(
    tmp_path_factory: pytest.TempPathFactory,
) -> _RenderedEnvironment:
    """Render immutable production documents once across xdist workers."""
    return _cached_render("values.prod.yaml", tmp_path_factory)


@pytest.fixture
def rendered_environment(
    values_file: str,
    tmp_path_factory: pytest.TempPathFactory,
) -> _RenderedEnvironment:
    """Render one parametrized environment once across xdist workers."""
    return _cached_render(values_file, tmp_path_factory)


def _deployment(documents: list[dict[str, Any]], name: str) -> dict[str, Any]:
    return next(d for d in documents if d.get("kind") == "Deployment" and d["metadata"]["name"] == name)


def _pod_spec(workload: dict[str, Any]) -> dict[str, Any]:
    return workload["spec"]["template"]["spec"]


def _device_plugin_daemonsets(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        d
        for d in documents
        if d.get("kind") == "DaemonSet"
        and any(_DEVICE_PLUGIN_REPO in c.get("image", "") for c in _pod_spec(d)["containers"])
    ]


def _tolerates_gpu(tolerations: list[dict[str, Any]] | None, key: str, value: str) -> bool:
    return any(
        t.get("effect") == "NoSchedule"
        and t.get("key") == key
        and (t.get("operator") == "Exists" or t.get("value") == value)
        for t in (tolerations or [])
    )


def _terraform_label_and_taint() -> tuple[dict[str, str], str, str]:
    iac = "\n".join(p.read_text(encoding="utf-8") for p in sorted(_IAC.glob("*.tf")))
    label_key = re.search(r'gpu_node_label_key\s*=\s*"([^"]+)"', iac)
    label_value = re.search(r'gpu_node_label_value\s*=\s*"([^"]+)"', iac)
    taint_key = re.search(r'gpu_node_taint_key\s*=\s*"([^"]+)"', iac)
    taint_value = re.search(r'gpu_node_taint_value\s*=\s*"([^"]+)"', iac)
    assert label_key, "GPU node label key missing from Terraform"
    assert label_value, "GPU node label value missing from Terraform"
    assert taint_key, "GPU node taint key missing from Terraform"
    assert taint_value, "GPU node taint value missing from Terraform"
    return (
        {label_key.group(1): label_value.group(1)},
        taint_key.group(1),
        taint_value.group(1),
    )


def test_base_values_pin_device_plugin_and_default_to_no_gpu() -> None:
    values = yaml.safe_load((_CHART / "charts" / "ml-compute-service" / "values.yaml").read_text(encoding="utf-8"))
    plugin = values["gpuDevicePlugin"]
    # Every knob configurable, but GPU is off unless an environment opts in.
    assert plugin["enabled"] is False
    assert plugin["image"]["repository"] == _DEVICE_PLUGIN_REPO
    assert _DIGEST_RE.search(plugin["image"]["tag"]), "device plugin image must be digest-pinned"
    assert "gpu" not in values.get("resources", {})


def test_production_advertises_gpu_via_pinned_device_plugin(
    production_documents: _RenderedEnvironment,
) -> None:
    documents = production_documents.documents
    label, taint_key, taint_value = _terraform_label_and_taint()
    daemonsets = _device_plugin_daemonsets(documents)
    assert len(daemonsets) == 1, "exactly one NVIDIA device plugin DaemonSet expected in prod"
    spec = _pod_spec(daemonsets[0])
    container = spec["containers"][0]

    assert container["image"].startswith(f"{_DEVICE_PLUGIN_REPO}:")
    assert _DIGEST_RE.search(container["image"]), "device plugin must be pinned by digest"

    # Runs only on the GPU pool.
    assert spec["nodeSelector"] == label
    assert _tolerates_gpu(spec.get("tolerations"), taint_key, taint_value)
    assert spec.get("priorityClassName") == "system-node-critical"

    # hostPath socket dir is how the plugin advertises allocatable GPUs to kubelet.
    assert any(v.get("hostPath", {}).get("path") == "/var/lib/kubelet/device-plugins" for v in spec.get("volumes", []))

    security = container.get("securityContext", {})
    assert security.get("allowPrivilegeEscalation") is False
    assert security.get("capabilities", {}).get("drop") == ["ALL"]


def test_production_ml_compute_requests_exactly_one_gpu(
    production_documents: _RenderedEnvironment,
) -> None:
    documents = production_documents.documents
    label, taint_key, taint_value = _terraform_label_and_taint()

    pod = _pod_spec(_deployment(documents, _ML_COMPUTE))
    container = pod["containers"][0]

    assert int(container["resources"]["requests"][_GPU_RESOURCE]) == 1
    assert int(container["resources"]["limits"][_GPU_RESOURCE]) == 1

    # CUDA image variant + GPU compute backend.
    assert re.search(r"/ml-compute-service-gpu@sha256:[0-9a-f]{64}$", container["image"]), container["image"]
    env = {entry["name"]: entry.get("value") for entry in container["env"]}
    assert env["ML_COMPUTE_PROCESSING__COMPUTE_BACKEND"] == "gpu"

    # Lands on the GPU pool.
    assert pod["nodeSelector"] == label
    assert _tolerates_gpu(pod.get("tolerations"), taint_key, taint_value)


def test_scheduling_matches_terraform_gpu_pool_label_and_taint(
    production_documents: _RenderedEnvironment,
) -> None:
    """The workload's selector/toleration must match the Terraform pool label/taint."""
    documents = production_documents.documents
    label, taint_key, taint_value = _terraform_label_and_taint()

    ml_compute = _pod_spec(_deployment(documents, _ML_COMPUTE))
    device_plugin = _pod_spec(_device_plugin_daemonsets(documents)[0])

    for spec in (ml_compute, device_plugin):
        assert spec["nodeSelector"] == label
        assert _tolerates_gpu(spec.get("tolerations"), taint_key, taint_value)


@pytest.mark.parametrize("values_file", ["values.local.yaml", "values.staging.yaml"])
def test_local_and_staging_schedule_no_gpu(
    values_file: str,
    rendered_environment: _RenderedEnvironment,
) -> None:
    assert values_file in {"values.local.yaml", "values.staging.yaml"}
    documents = rendered_environment.documents

    assert _device_plugin_daemonsets(documents) == [], "no device plugin outside prod"
    assert _GPU_RESOURCE not in rendered_environment.manifest, "no GPU requested outside prod"

    pod = _pod_spec(_deployment(documents, _ML_COMPUTE))
    container = pod["containers"][0]
    # CPU image variant, no GPU scheduling, no GPU backend.
    assert "ml-compute-service-gpu" not in container["image"]
    assert "ml-compute-service" in container["image"]
    assert pod.get("nodeSelector") in (None, {})
    env = {entry["name"] for entry in container.get("env", [])}
    assert "ML_COMPUTE_PROCESSING__COMPUTE_BACKEND" not in env


def _ml_compute_overlay(tmp_path: Path, name: str, config: dict[str, Any]) -> Path:
    """Write an umbrella overlay scoped to the ml-compute-service subchart."""
    path = tmp_path / name
    path.write_text(yaml.safe_dump({"ml-compute-service": config}), encoding="utf-8")
    return path


def _render_prod_result(
    tmp_path: Path,
    *overlays: Path,
    digests: Path | None = None,
    gpu_image_digest: bool = True,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Render the prod umbrella with the standard prod overlays plus extra ones.

    ``digests`` defaults to the full first-party digest map; pass a custom map (for
    example one omitting the GPU repo) to exercise fail-closed paths. Later overlays
    win, so trailing ``overlays`` flip only the fields they set.
    """
    if digests is None:
        digests = _digest_values(tmp_path)
    command = [
        "helm",
        "template",
        "nohiki",
        ".",
        "--values",
        "values.yaml",
        "--values",
        "values.prod.yaml",
        "--namespace",
        "nohiki",
        "--values",
        str(_IDENTITY),
        "--values",
        str(_NETWORK),
        "--values",
        str(digests),
    ]
    if gpu_image_digest:
        command += ["--values", str(_gpu_image_overlay(tmp_path))]
    for overlay in overlays:
        command += ["--values", str(overlay)]
    return subprocess.run(command, cwd=_CHART, capture_output=True, text=True, check=check)


def _docs(result: subprocess.CompletedProcess[str]) -> list[dict[str, Any]]:
    return [
        document for document in yaml.load_all(result.stdout, Loader=yaml.CSafeLoader) if isinstance(document, dict)
    ]


def test_base_values_default_accelerator_mode_is_cpu() -> None:
    """The single switch defaults to the production-safe CPU mode."""
    values = yaml.safe_load((_CHART / "charts" / "ml-compute-service" / "values.yaml").read_text(encoding="utf-8"))
    accelerator = values["accelerator"]
    assert accelerator["mode"] == "cpu"
    assert accelerator["cpuImageName"] == "ml-compute-service"
    assert accelerator["gpuImageName"] == "ml-compute-service-gpu"


def test_single_accelerator_switch_flips_all_or_nothing(
    tmp_path: Path,
    production_documents: _RenderedEnvironment,
) -> None:
    """Flipping only accelerator.mode toggles every GPU contract, all or nothing.

    The same production environment is rendered twice, changing exactly one field.
    mode=cuda (the prod default) yields the complete GPU contract; a lone
    accelerator.mode=cpu overlay must remove the GPU image, the nvidia.com/gpu
    resource, the device plugin, the GPU placement, and the compute-backend env
    together - operators never wire those six fields by hand.
    """
    label, taint_key, taint_value = _terraform_label_and_taint()

    # mode=cuda: the full GPU contract renders coherently.
    cuda_docs = production_documents.documents
    cuda_pod = _pod_spec(_deployment(cuda_docs, _ML_COMPUTE))
    cuda_container = cuda_pod["containers"][0]
    assert re.search(r"/ml-compute-service-gpu@sha256:[0-9a-f]{64}$", cuda_container["image"]), cuda_container["image"]
    assert int(cuda_container["resources"]["requests"][_GPU_RESOURCE]) == 1
    assert int(cuda_container["resources"]["limits"][_GPU_RESOURCE]) == 1
    assert len(_device_plugin_daemonsets(cuda_docs)) == 1
    assert cuda_pod["nodeSelector"] == label
    assert _tolerates_gpu(cuda_pod.get("tolerations"), taint_key, taint_value)
    cuda_env = {entry["name"]: entry.get("value") for entry in cuda_container["env"]}
    assert cuda_env["ML_COMPUTE_PROCESSING__COMPUTE_BACKEND"] == "gpu"

    # Flip ONLY the switch to cpu: every GPU artifact disappears in lockstep.
    cpu_overlay = _ml_compute_overlay(tmp_path, "mode-cpu.yaml", {"accelerator": {"mode": "cpu"}})
    cpu_docs = _docs(_render_prod_result(tmp_path, cpu_overlay, check=True))
    cpu_pod = _pod_spec(_deployment(cpu_docs, _ML_COMPUTE))
    cpu_container = cpu_pod["containers"][0]
    assert "ml-compute-service-gpu" not in cpu_container["image"]
    assert re.search(r"/ml-compute-service@sha256:[0-9a-f]{64}$", cpu_container["image"]), cpu_container["image"]
    assert not any(_GPU_RESOURCE in yaml.safe_dump(document) for document in cpu_docs)
    assert _device_plugin_daemonsets(cpu_docs) == []
    assert cpu_pod.get("nodeSelector") in (None, {})
    assert not _tolerates_gpu(cpu_pod.get("tolerations"), taint_key, taint_value)
    cpu_env = {entry["name"] for entry in cpu_container.get("env", [])}
    assert "ML_COMPUTE_PROCESSING__COMPUTE_BACKEND" not in cpu_env


def test_invalid_accelerator_mode_fails_render(tmp_path: Path) -> None:
    """An unknown accelerator.mode is rejected at render time."""
    overlay = _ml_compute_overlay(tmp_path, "bad-mode.yaml", {"accelerator": {"mode": "tpu"}})
    result = _render_prod_result(tmp_path, overlay, check=False)
    assert result.returncode != 0
    assert "accelerator.mode" in result.stderr, result.stderr


def test_cuda_mode_without_pinned_gpu_digest_fails_render(tmp_path: Path) -> None:
    """mode=cuda demands a pinned GPU image digest; its absence fails render."""
    digests = _digest_values(tmp_path, omit="ml-compute-service-gpu")
    result = _render_prod_result(tmp_path, digests=digests, gpu_image_digest=False, check=False)
    assert result.returncode != 0
    assert "digest" in result.stderr.lower(), result.stderr


@pytest.mark.parametrize(
    "gpu_field",
    [{"gpuDevicePlugin": {"enabled": True}}, {"resources": {"gpu": 1}}],
    ids=["device-plugin-enabled", "gpu-resource-requested"],
)
def test_cpu_mode_with_gpu_artifact_fails_render(tmp_path: Path, gpu_field: dict[str, Any]) -> None:
    """mode=cpu alongside an explicitly requested GPU artifact is an incoherent mix."""
    overlay = _ml_compute_overlay(tmp_path, "mixed.yaml", {"accelerator": {"mode": "cpu"}, **gpu_field})
    result = _render_prod_result(tmp_path, overlay, check=False)
    assert result.returncode != 0
    assert "conflict" in result.stderr.lower(), result.stderr
