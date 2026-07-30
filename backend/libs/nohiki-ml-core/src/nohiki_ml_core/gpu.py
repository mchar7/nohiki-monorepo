"""GPU capability detection and validation for nohiki-ml-core.

Fail-fast checks for GPU availability and graceful handling
when GPU dependencies are missing. It should be called early during service startup
to prevent late runtime failures.

GPU support is OPTIONAL and requires installing the [gpu] extras:
    pip install nohiki-ml-core[gpu]

Without GPU extras, all GPU operations will raise GpuNotAvailableError with
clear instructions on how to enable GPU support.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from functools import cache
from types import ModuleType

from nohiki_observability import get_logger

from nohiki_ml_core import _deps

logger = get_logger(__name__)


class ComputeBackend(Enum):
    """Available compute backends for ML operations."""

    CPU = "cpu"
    CUDA = "cuda"


class GpuNotAvailableError(RuntimeError):
    """Raised when GPU operations are requested but GPU is not available.

    This error is raised early during startup if GPU compute is configured
    but GPU dependencies are not installed or no GPU hardware is detected.
    """

    def __init__(self, reason: str, *, suggestion: str | None = None) -> None:
        """Initialize with reason and optional suggestion.

        Args:
            reason: Why GPU is not available
            suggestion: How to fix the issue (optional)

        """
        self.reason = reason
        self.suggestion = suggestion or "Install GPU extras: pip install nohiki-ml-core[gpu]"
        message = f"GPU not available: {reason}. {self.suggestion}"
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class GpuCapabilities:
    """GPU hardware and software capabilities."""

    cuda_available: bool
    cuda_version: str | None
    device_count: int
    device_names: tuple[str, ...]
    triton_available: bool


def _get_torch() -> ModuleType | None:
    """Lazy import torch, returning None if it is not installed."""
    try:
        return _deps.import_optional_module("torch", _deps.LocalDependency.TORCH, "CUDA detection")
    except _deps.MissingLocalDependencyError:
        return None


def _check_cuda_deps_installed() -> bool:
    """Check if CUDA dependencies (torch with CUDA) are installed."""
    try:
        torch = _get_torch()
        if torch is None:
            return False
        return bool(torch.cuda.is_available())
    except Exception:
        logger.exception("Unexpected error checking CUDA dependencies")
        return False


def _check_triton_installed() -> bool:
    """Check if triton is installed."""
    return _deps.optional_dependency_available("triton")


def _get_cuda_version() -> str | None:
    """Get CUDA version if available."""
    try:
        torch = _get_torch()
        if torch is None:
            return None
        if torch.cuda.is_available():
            cuda_version = getattr(torch, "version", None)
            if cuda_version is not None:
                return str(getattr(cuda_version, "cuda", None))
    except ImportError, AttributeError:
        pass
    return None


def _get_device_info() -> tuple[int, tuple[str, ...]]:
    """Get GPU device count and names."""
    try:
        torch = _get_torch()
        if torch is None:
            return 0, ()
        if torch.cuda.is_available():
            count = int(torch.cuda.device_count())
            names = tuple(str(torch.cuda.get_device_name(i)) for i in range(count))
            return count, names
    except ImportError, RuntimeError:
        pass
    return 0, ()


@cache
def detect_gpu_capabilities() -> GpuCapabilities:
    """Detect GPU hardware and software capabilities.

    This function is cached - subsequent calls return the same result.
    Call once during startup to detect capabilities.

    Returns:
        GpuCapabilities with detection results

    """
    cuda_available = _check_cuda_deps_installed()
    cuda_version = _get_cuda_version() if cuda_available else None
    device_count, device_names = _get_device_info() if cuda_available else (0, ())
    triton_available = _check_triton_installed()

    return GpuCapabilities(
        cuda_available=cuda_available,
        cuda_version=cuda_version,
        device_count=device_count,
        device_names=device_names,
        triton_available=triton_available,
    )


def get_available_backend() -> ComputeBackend:
    """Get the best available compute backend.

    Returns:
        ComputeBackend.CUDA if GPU is available, else ComputeBackend.CPU

    """
    caps = detect_gpu_capabilities()
    return ComputeBackend.CUDA if caps.cuda_available and caps.device_count > 0 else ComputeBackend.CPU


def require_gpu() -> GpuCapabilities:
    """Require GPU availability, raising error if not available.

    This is the fail-fast check that should be called early during
    service startup if GPU operations are expected.

    Returns:
        GpuCapabilities if GPU is available

    Raises:
        GpuNotAvailableError: If GPU is not available

    """
    caps = detect_gpu_capabilities()

    if not caps.cuda_available:
        raise GpuNotAvailableError(
            reason="CUDA dependencies not installed or not functional",
            suggestion="Install GPU extras: pip install nohiki-ml-core[gpu]",
        )

    if caps.device_count == 0:
        raise GpuNotAvailableError(
            reason="No CUDA-capable GPU devices found",
            suggestion="Ensure NVIDIA drivers are installed and GPU is accessible",
        )

    return caps


def validate_compute_backend(requested: ComputeBackend) -> None:
    """Validate that the requested compute backend is available.

    Call this during service startup to fail fast if the configured
    backend is not available.

    Args:
        requested: The compute backend to validate

    Raises:
        GpuNotAvailableError: If CUDA requested but not available

    """
    if requested == ComputeBackend.CUDA:
        require_gpu()


def reset_gpu_detection_cache() -> None:
    """Reset the GPU detection cache (for testing)."""
    detect_gpu_capabilities.cache_clear()
