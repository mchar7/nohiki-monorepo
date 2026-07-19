"""Dependency/build-backend contract for the ml-compute-service CUDA torch runtime.

The production GPU-scheduled ml-compute pod must ship a real CUDA-enabled PyTorch
wheel, while every other install (developers, tests, Compose, non-prod packages)
keeps the CPU-only wheel. These tests parse the workspace/service pyprojects, the
service Dockerfile, and the single workspace lock, and cross-check resolution
behaviourally with offline ``uv export`` so the contract cannot silently regress
to a CPU torch wheel inside a GPU pod.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tomllib
from functools import cache
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[3]
_ROOT_PYPROJECT = _ROOT / "pyproject.toml"
_LOCK = _ROOT / "uv.lock"
_MLC = _ROOT / "backend" / "services" / "ml-compute-service"
_MLC_PYPROJECT = _MLC / "pyproject.toml"
_MLC_DOCKERFILE = _MLC / "Dockerfile"

_UV = shutil.which("uv") or "uv"
_CPU_INDEX_URL = "https://download.pytorch.org/whl/cpu"
_CUDA_INDEX_URL = "https://download.pytorch.org/whl/cu130"
_NVIDIA_REQ = re.compile(r"(?m)^nvidia-[a-z0-9-]+==")
_TRITON_REQ = re.compile(r"(?m)^triton==")


@cache
def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@cache
def _load_toml(path: Path) -> dict[str, Any]:
    return tomllib.loads(_read_text(path))


@cache
def _uv_export(*extras: str) -> subprocess.CompletedProcess[str]:
    """Resolve ml-compute-service against the committed lock, fully offline."""
    args = [
        _UV,
        "export",
        "--frozen",
        "--offline",
        "--no-hashes",
        "--no-dev",
        "--package",
        "ml-compute-service",
    ]
    for extra in extras:
        args += ["--extra", extra]
    return subprocess.run(args, cwd=_ROOT, capture_output=True, text=True, check=False)


def test_ml_compute_declares_mutually_exclusive_cpu_and_cuda_torch_extras() -> None:
    """cpu/cuda are real optional torch extras, declared mutually exclusive."""
    optional = _load_toml(_MLC_PYPROJECT)["project"]["optional-dependencies"]
    assert {"cpu", "cuda"} <= optional.keys(), optional.keys()
    for extra in ("cpu", "cuda"):
        assert any(req.startswith("torch") for req in optional[extra]), (
            extra,
            optional[extra],
        )

    conflicts = _load_toml(_ROOT_PYPROJECT)["tool"]["uv"].get("conflicts", [])
    paired = {frozenset((member["package"], member["extra"]) for member in group) for group in conflicts}
    expected = frozenset({("ml-compute-service", "cpu"), ("ml-compute-service", "cuda")})
    assert expected in paired, conflicts

    # The single workspace lock must record the conflict (proves it was relocked).
    # uv writes `conflicts` at the lock's document root, not under [manifest].
    lock_conflicts = _load_toml(_LOCK).get("conflicts", [])
    lock_paired = {frozenset((member["package"], member["extra"]) for member in group) for group in lock_conflicts}
    assert expected in lock_paired, lock_conflicts


def test_pytorch_cpu_and_cuda_indexes_are_pinned() -> None:
    """Both PyTorch indexes are explicitly pinned; cu130 is reachable only via a source."""
    indexes = {entry["name"]: entry for entry in _load_toml(_ROOT_PYPROJECT)["tool"]["uv"]["index"]}

    assert indexes["pytorch-cpu"]["url"] == _CPU_INDEX_URL, indexes["pytorch-cpu"]
    # CPU index stays the non-explicit default so ordinary syncs resolve +cpu.
    assert not indexes["pytorch-cpu"].get("explicit", False), indexes["pytorch-cpu"]

    assert indexes["pytorch-cu130"]["url"] == _CUDA_INDEX_URL, indexes["pytorch-cu130"]
    # cu130 must be explicit: only the cuda extra's torch source may pull from it.
    assert indexes["pytorch-cu130"].get("explicit", False), indexes["pytorch-cu130"]


def test_blanket_cuda_exclusion_overrides_are_removed() -> None:
    """The old ``sys_platform == 'never'`` nvidia/triton exclusions must be gone.

    They globally deleted CUDA runtime libraries from *every* resolution, so a
    GPU pod requesting the cuda extra would still receive a torch wheel stripped
    of its NVIDIA deps — i.e. effectively a broken/CPU runtime. Removing them is
    what lets the cu130 wheel keep its real accelerator dependencies.
    """
    overrides = _load_toml(_ROOT_PYPROJECT)["tool"]["uv"].get("override-dependencies", [])
    offenders = [line for line in overrides if "sys_platform == 'never'" in line]
    assert not offenders, offenders

    # Same guard at the lock level: no never-markered nvidia/triton overrides survive.
    lock_overrides = _load_toml(_LOCK)["manifest"].get("overrides", [])
    lock_offenders = [
        entry
        for entry in lock_overrides
        if entry.get("marker") == "sys_platform == 'never'"
        and (entry.get("name", "").startswith("nvidia-") or entry.get("name") == "triton")
    ]
    assert not lock_offenders, lock_offenders


def test_gpu_docker_build_installs_cuda_extra_and_cpu_default_unchanged() -> None:
    """The GPU build path requests the cuda extra; the default build stays CPU."""
    dockerfile = _read_text(_MLC_DOCKERFILE)
    sync_lines = [line for line in dockerfile.splitlines() if "uv sync" in line]
    assert sync_lines, "ml-compute Dockerfile has no `uv sync` invocation"

    gpu_syncs = [line for line in sync_lines if re.search(r"--extra[= ]cuda\b", line)]
    assert gpu_syncs, sync_lines

    cpu_syncs = [line for line in sync_lines if "--extra" not in line]
    assert cpu_syncs, "default (CPU) build path must keep a `uv sync` with no --extra"


def test_default_sync_resolves_cpu_only_torch() -> None:
    """No-extra resolution keeps the CPU wheel and pulls in no CUDA runtime.

    Guards the exact trap of a sourceless no-extra fork: if the CPU index source
    fails to cover the bare fork, torch falls back to the PyPI manylinux build
    (a bare ``torch==X.Y.Z`` with bundled CUDA) on Linux. So every linux/win torch
    line must carry the ``+cpu`` local version; a bare version there is the defect.
    (macOS legitimately has no ``+cpu`` suffix and is inherently CPU-only.)
    """
    result = _uv_export()
    assert result.returncode == 0, result.stderr
    out = result.stdout
    torch_reqs = [line for line in out.splitlines() if line.startswith("torch==")]
    assert any("+cpu" in line for line in torch_reqs), out
    for line in torch_reqs:
        if "linux" in line or "win32" in line:
            assert "+cpu" in line, f"CPU-intended path resolved a non-+cpu torch wheel: {line!r}"
    assert "cu130" not in out
    assert not _NVIDIA_REQ.search(out), "CPU sync must not pull NVIDIA CUDA libraries"
    assert not _TRITON_REQ.search(out), "CPU sync must stay slim: no triton"


def test_cuda_extra_resolves_gpu_torch_wheel_with_nvidia_deps() -> None:
    """The cuda extra resolves a real +cu130 wheel with its NVIDIA deps intact."""
    result = _uv_export("cuda")
    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert re.search(r"(?m)^torch==\S+\+cu130\b", out), out
    assert _NVIDIA_REQ.search(out), "cuda extra must retain NVIDIA CUDA runtime deps"
    assert _TRITON_REQ.search(out), "cuda extra is the accelerator superset: triton must be present"


def test_requesting_both_accelerator_extras_is_rejected() -> None:
    """Both extras are strictly mutually exclusive: asking for both must not resolve.

    Declaration alone is not enough - the resolver must actually refuse the pair,
    otherwise a single install could smuggle both the +cpu and +cu130 torch wheels
    (or their conflicting NVIDIA closures) into one environment.
    """
    result = _uv_export("cpu", "cuda")
    assert result.returncode != 0, "resolving both cpu and cuda extras must fail"
    stderr = result.stderr.lower()
    assert "conflict" in stderr, result.stderr
    assert "cpu" in stderr, result.stderr
    assert "cuda" in stderr, result.stderr


def test_ml_compute_dockerfile_has_distinct_cpu_and_gpu_builder_stages() -> None:
    """One build arg selects between two distinct, mutually exclusive builder stages.

    The CPU and CUDA images share a Dockerfile but must resolve to *different*
    builder stages: sync-cpu (default, +cpu torch) vs sync-gpu (+cu130 torch).
    BuildKit only materialises the selected stage, so a CPU image can never pull
    the CUDA closure and vice versa. This guards the image-target split at the
    source: losing either stage, or defaulting the arg to the GPU stage, is a defect.
    """
    dockerfile = _read_text(_MLC_DOCKERFILE)
    # Default arg keeps the plain build CPU-only.
    assert re.search(r"(?m)^ARG ML_COMPUTE_BUILDER=sync-cpu\b", dockerfile), dockerfile
    # Two distinct named stages exist...
    assert re.search(r"(?m)^FROM .+ AS sync-cpu\b", dockerfile), "missing CPU builder stage"
    assert re.search(r"(?m)^FROM .+ AS sync-gpu\b", dockerfile), "missing GPU builder stage"
    # ...and the final builder is chosen solely by the arg (no hardcoded accelerator).
    assert re.search(r"(?m)^FROM \$\{ML_COMPUTE_BUILDER\} AS builder\b", dockerfile), dockerfile
    # The GPU stage is the only one that requests the cuda extra.
    gpu_stage = dockerfile.split("AS sync-gpu", 1)[1].split("FROM ", 1)[0]
    cpu_stage = dockerfile.split("AS sync-cpu", 1)[1].split("FROM ", 1)[0]
    assert re.search(r"--extra[= ]cuda\b", gpu_stage), gpu_stage
    assert "--extra" not in cpu_stage, cpu_stage
