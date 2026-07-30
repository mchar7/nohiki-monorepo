"""Optional dependency checking for nohiki-ml-core.

Utilities for checking and reporting missing optional
dependencies at encoder construction time, before any ML operations are attempted.

The base package remains lightweight. The [inference] extra provides the
dependencies for direct in-process PyLate, fastembed, and dense inference.
"""

from __future__ import annotations

import importlib
import importlib.util
from enum import StrEnum
from types import ModuleType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sklearn.cluster import MiniBatchKMeans


class LocalDependency(StrEnum):
    """Optional dependencies in the [inference] extra."""

    PYLATE = "pylate"
    FASTEMBED = "fastembed"
    ONNXRUNTIME = "onnxruntime"
    SKLEARN = "sklearn"
    SENTENCE_TRANSFORMERS = "sentence-transformers"
    TORCH = "torch"
    TRITON = "triton"


class MissingLocalDependencyError(ImportError):
    """Raised when a required local inference dependency is not installed."""

    def __init__(self, dependency: LocalDependency, feature: str) -> None:
        """Initialize a missing-dependency import error.

        Args:
            dependency: Missing distribution.
            feature: Feature that requires the distribution.
        """
        match dependency:
            case LocalDependency.TORCH | LocalDependency.TRITON:
                extra = "gpu"
            case _:
                extra = "inference"
        self.dependency = dependency
        self.feature = feature
        super().__init__(
            f"{feature} requires '{dependency}' which is not installed.\n\n"
            f"Install it with the nohiki-ml-core[{extra}] extra. "
            "Alternatively, route inference through ml-gateway-service."
        )


def optional_dependency_available(module_name: str) -> bool:
    """Check module availability without importing a heavy backend."""
    return importlib.util.find_spec(module_name) is not None


def import_optional_module(module_name: str, dependency: LocalDependency, feature: str) -> ModuleType:
    """Import an optional module or raise a typed dependency import error."""
    try:
        return importlib.import_module(module_name)
    except ImportError as exc:
        raise MissingLocalDependencyError(dependency, feature) from exc


def check_pylate_available() -> bool:
    """Check if pylate is installed."""
    return optional_dependency_available("pylate")


def check_fastembed_available() -> bool:
    """Check if fastembed is installed."""
    return optional_dependency_available("fastembed")


def require_pylate(feature: str, *, module_name: str = "pylate") -> None:
    """Require a PyLate module to be installed.

    Args:
        feature: Description of the feature requiring PyLate.
        module_name: Exact PyLate module the feature imports.

    Raises:
        MissingLocalDependencyError: If the module is not installed.
    """
    if not optional_dependency_available(module_name):
        raise MissingLocalDependencyError(LocalDependency.PYLATE, feature)


def require_fastembed(feature: str, *, module_name: str = "fastembed") -> None:
    """Require a fastembed module to be installed.

    Args:
        feature: Description of the feature requiring fastembed.
        module_name: Exact fastembed module the feature imports.

    Raises:
        MissingLocalDependencyError: If the module is not installed.
    """
    if not optional_dependency_available(module_name):
        raise MissingLocalDependencyError(LocalDependency.FASTEMBED, feature)


def check_sklearn_available() -> bool:
    """Check if scikit-learn is installed."""
    return optional_dependency_available("sklearn.cluster")


def require_sklearn(feature: str) -> None:
    """Require scikit-learn to be installed, raising clear error if not.

    Args:
        feature: Description of feature requiring sklearn

    Raises:
        MissingLocalDependencyError: If scikit-learn is not installed

    """
    if not optional_dependency_available("sklearn.cluster"):
        raise MissingLocalDependencyError(LocalDependency.SKLEARN, feature)


def get_minibatch_kmeans(feature: str) -> type[MiniBatchKMeans]:
    """Get sklearn MiniBatchKMeans class, raising clear error if not installed.

    This function centralizes the lazy import of sklearn, allowing callers to
    avoid module-level imports of optional dependencies while keeping the
    import logic in one place.

    Args:
        feature: Description of feature requiring sklearn (for error message)

    Returns:
        The MiniBatchKMeans class from sklearn.cluster

    Raises:
        MissingLocalDependencyError: If scikit-learn is not installed

    """
    try:
        from sklearn.cluster import MiniBatchKMeans
    except ImportError as exc:
        raise MissingLocalDependencyError(LocalDependency.SKLEARN, feature) from exc
    return MiniBatchKMeans
