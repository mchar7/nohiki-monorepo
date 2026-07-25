"""Dataset adapter registry.

Provides a central registry for all available dataset adapters
and utilities for retrieving adapters by name or tier.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from job_embedding_finetuning.dataset_adapters.base import DatasetAdapter, DatasetInfo, DatasetTier

if TYPE_CHECKING:
    from collections.abc import Sequence

# Dataset registry: maps dataset name to (DatasetInfo, adapter_class)
# Populated by adapter modules when imported
_REGISTRY: dict[str, tuple[DatasetInfo, type[DatasetAdapter]]] = {}


def register_adapter(info: DatasetInfo, adapter_class: type[DatasetAdapter]) -> None:
    """Register a dataset adapter in the global registry.

    Args:
        info: Dataset metadata.
        adapter_class: The adapter class to register.

    """
    _REGISTRY[info.name] = (info, adapter_class)


def get_adapter(name: str, data_dir: Path) -> DatasetAdapter:
    """Get an adapter instance by dataset name.

    Args:
        name: The dataset name.
        data_dir: Root directory containing downloaded datasets.

    Returns:
        An initialized adapter instance.

    Raises:
        KeyError: If the dataset name is not registered.

    """
    if name not in _REGISTRY:
        available = ", ".join(sorted(_REGISTRY.keys()))
        msg = f"Unknown dataset: {name}. Available: {available}"
        raise KeyError(msg)
    _, adapter_class = _REGISTRY[name]
    return adapter_class(data_dir)


def get_adapters_by_tier(tier: DatasetTier, data_dir: Path) -> list[DatasetAdapter]:
    """Get all adapters for a specific tier.

    Args:
        tier: The dataset tier to filter by.
        data_dir: Root directory containing downloaded datasets.

    Returns:
        List of initialized adapter instances for the tier.

    """
    adapters = []
    for info, adapter_class in _REGISTRY.values():
        if info.tier == tier:
            adapters.append(adapter_class(data_dir))
    return adapters


def get_all_adapters(data_dir: Path) -> list[DatasetAdapter]:
    """Get all registered adapters.

    Args:
        data_dir: Root directory containing downloaded datasets.

    Returns:
        List of all initialized adapter instances.

    """
    return [adapter_class(data_dir) for _, adapter_class in _REGISTRY.values()]


def get_dataset_info(name: str) -> DatasetInfo:
    """Get dataset metadata by name.

    Args:
        name: The dataset name.

    Returns:
        The dataset metadata.

    Raises:
        KeyError: If the dataset name is not registered.

    """
    if name not in _REGISTRY:
        msg = f"Unknown dataset: {name}"
        raise KeyError(msg)
    info, _ = _REGISTRY[name]
    return info


def list_datasets() -> Sequence[DatasetInfo]:
    """List all registered datasets.

    Returns:
        Sequence of all registered dataset metadata.

    """
    return [info for info, _ in _REGISTRY.values()]


def list_datasets_by_tier(tier: DatasetTier) -> Sequence[DatasetInfo]:
    """List datasets for a specific tier.

    Args:
        tier: The dataset tier to filter by.

    Returns:
        Sequence of dataset metadata for the tier.

    """
    return [info for info, _ in _REGISTRY.values() if info.tier == tier]


# Provide module-level access to registry
DATASET_REGISTRY = _REGISTRY
