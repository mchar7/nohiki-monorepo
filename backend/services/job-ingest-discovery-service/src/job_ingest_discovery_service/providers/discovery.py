"""Provider auto-discovery mechanism.

Discovers and loads providers from the providers directory without
requiring explicit imports in the registry. Each provider package
must expose a `get_provider` function that returns a BaseProvider instance.
"""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path
from typing import TYPE_CHECKING

from nohiki_observability import get_logger

if TYPE_CHECKING:
    from job_ingest_discovery_service.providers.base import BaseProvider

logger = get_logger(__name__)


def _iter_provider_packages() -> list[str]:
    package_names: list[str] = []

    providers_dir = Path(__file__).resolve().parent
    for module_info in pkgutil.iter_modules([str(providers_dir)]):
        if not module_info.ispkg:
            continue
        if module_info.name.startswith("_"):
            continue
        package_names.append(module_info.name)
    return package_names


def discover_providers() -> list[BaseProvider]:
    """Discover and instantiate all available providers.

    Scans known provider packages and attempts to load them.
    Each provider package must have a `get_provider()` function
    that returns a BaseProvider instance, or the discovery will skip it.

    Returns:
        List of discovered provider instances.

    """
    providers: list[BaseProvider] = []

    for package_name in _iter_provider_packages():
        provider = _load_provider(package_name)
        if provider is not None:
            providers.append(provider)

    logger.info(
        "Provider discovery complete",
        discovered=[p.name for p in providers],
        total=len(providers),
    )

    return providers


def _load_provider(package_name: str) -> BaseProvider | None:
    """Attempt to load a provider from a package.

    Args:
        package_name: Name of the provider package (e.g., "jobspy")

    Returns:
        Provider instance if successfully loaded, None otherwise.

    """
    module_path = f"job_ingest_discovery_service.providers.{package_name}"

    try:
        module = importlib.import_module(module_path)
    except ImportError:
        logger.debug("Provider package not found", package=package_name)
        return None

    # Look for get_provider function
    get_provider_func = getattr(module, "get_provider", None)
    if get_provider_func is None:
        logger.debug(
            "Provider package missing get_provider function",
            package=package_name,
        )
        return None

    try:
        provider: BaseProvider = get_provider_func()
    except Exception:
        logger.exception("Failed to instantiate provider", package=package_name)
        return None
    else:
        logger.debug("Loaded provider", name=provider.name, package=package_name)
        return provider
