"""Optional dependency checking for nohiki-ml-core.

Utilities for checking and reporting missing optional
dependencies at encoder construction time, before any ML operations are attempted.

The base package remains lightweight. The [inference] extra provides the
dependencies for direct in-process PyLate, fastembed, and dense inference.
"""

from __future__ import annotations

import importlib.util
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sklearn.cluster import MiniBatchKMeans


class LocalDependency(StrEnum):
    """Optional dependencies in the [inference] extra."""

    PYLATE = "pylate"
    FASTEMBED = "fastembed"
    ONNXRUNTIME = "onnxruntime"
    SKLEARN = "sklearn"


class MissingLocalDependencyError(ImportError):
    """Raised when a local inference dependency is not installed.

    This error is raised early (at encoder construction) rather than lazily
    (at encode time) to provide clear guidance on how to resolve the issue.
    """

    def __init__(self, dependency: LocalDependency, feature: str) -> None:
        """Initialize error with helpful installation instructions.

        Args:
            dependency: The missing dependency name
            feature: What feature requires this dependency (e.g., "ColBERT DIRECT backend")

        """
        self.dependency = dependency
        self.feature = feature
        super().__init__(
            f"{feature} requires '{dependency}' which is not installed.\n"
            f"\n"
            f"To use local inference, add the [inference] extra to pyproject.toml:\n"
            f"    nohiki-ml-core[inference]\n"
            f"\n"
            f"Alternatively, route via ml-gateway-service to Kubernetes or Modal workers"
        )


def check_pylate_available() -> bool:
    """Check if pylate is installed."""
    return importlib.util.find_spec("pylate") is not None


def check_fastembed_available() -> bool:
    """Check if fastembed is installed."""
    return importlib.util.find_spec("fastembed") is not None


def require_pylate(feature: str) -> None:
    """Require pylate to be installed, raising clear error if not.

    Args:
        feature: Description of feature requiring pylate

    Raises:
        MissingLocalDependencyError: If pylate is not installed

    """
    if not check_pylate_available():
        raise MissingLocalDependencyError(LocalDependency.PYLATE, feature)


def require_fastembed(feature: str) -> None:
    """Require fastembed to be installed, raising clear error if not.

    Args:
        feature: Description of feature requiring fastembed

    Raises:
        MissingLocalDependencyError: If fastembed is not installed

    """
    if not check_fastembed_available():
        raise MissingLocalDependencyError(LocalDependency.FASTEMBED, feature)


def check_sklearn_available() -> bool:
    """Check if scikit-learn is installed."""
    return importlib.util.find_spec("sklearn") is not None


def require_sklearn(feature: str) -> None:
    """Require scikit-learn to be installed, raising clear error if not.

    Args:
        feature: Description of feature requiring sklearn

    Raises:
        MissingLocalDependencyError: If scikit-learn is not installed

    """
    if not check_sklearn_available():
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
    require_sklearn(feature)
    from sklearn.cluster import MiniBatchKMeans

    return MiniBatchKMeans
