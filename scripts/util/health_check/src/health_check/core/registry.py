"""Check registry for auto-discovery and filtered retrieval of HealthCheck instances."""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Iterator
from typing import TYPE_CHECKING

from health_check.core.inventory import InventoryClosure, build_inventory
from health_check.core.models import CheckCategory
from health_check.platform.models import PlatformTarget

if TYPE_CHECKING:
    from health_check.core.base import HealthCheck


def _all_concrete_subclasses(cls: type) -> Iterator[type]:
    """Yield all non-abstract subclasses of ``cls`` recursively.

    Args:
        cls: The parent class to walk.

    Yields:
        Concrete (non-abstract) subclass types.
    """
    for sub in cls.__subclasses__():
        if not getattr(sub, "__abstractmethods__", None):
            yield sub
        yield from _all_concrete_subclasses(sub)


class CheckRegistry:
    """Registry for health check discovery and filtered retrieval.

    Supports two registration patterns:

    1. **Auto-discovery**: ``registry.discover("health_check.checks")`` imports
       all submodules of a package and finds concrete ``HealthCheck`` subclasses
       via Python's class hierarchy.
    2. **Explicit registration**: ``registry.register(MyCheck())`` for cases where
       auto-discovery is insufficient.

    Example::

        registry = CheckRegistry()
        registry.discover()
        checks = registry.get_checks(platform=PlatformTarget.COMPOSE)
    """

    def __init__(self) -> None:
        """Initialise an empty registry."""
        self._checks: dict[str, HealthCheck] = {}

    def register(self, check: HealthCheck) -> None:
        """Register a check, rejecting duplicate identities."""
        check_id = check.metadata.check_id
        if check_id in self._checks:
            message = f"Duplicate health check id: {check_id}"
            raise ValueError(message)
        self._checks[check_id] = check

    def discover(self, package_name: str = "health_check.checks") -> None:
        """Auto-discover all concrete ``HealthCheck`` subclasses.

        Imports every submodule of ``package_name`` so that subclasses are
        registered in Python's class hierarchy, then instantiates and stores
        all non-abstract ones. First-registered wins on ``check_id`` collision.

        Args:
            package_name: Dotted module path of the checks package to walk.
        """
        from health_check.core.base import HealthCheck as _HealthCheck

        pkg = importlib.import_module(package_name)
        pkg_path: list[str] = list(pkg.__path__)
        for _, modname, _ in pkgutil.walk_packages(pkg_path, prefix=package_name + "."):
            importlib.import_module(modname)

        for cls in _all_concrete_subclasses(_HealthCheck):
            if cls.__module__.startswith(f"{package_name}."):
                instance = cls()
                existing = self._checks.get(instance.metadata.check_id)
                if existing is None:
                    self.register(instance)
                elif type(existing) is not cls:
                    message = f"Duplicate health check id: {instance.metadata.check_id}"
                    raise ValueError(message)

        known = frozenset(self._checks)
        missing = {
            check.metadata.check_id: sorted(check.metadata.depends_on - known)
            for check in self._checks.values()
            if check.metadata.depends_on - known
        }
        if missing:
            evidence = "; ".join(f"{check}: {', '.join(deps)}" for check, deps in sorted(missing.items()))
            message = f"Health checks have unknown dependencies: {evidence}"
            raise ValueError(message)

    def get_checks(
        self,
        *,
        platform: PlatformTarget | None = None,
        categories: frozenset[CheckCategory] | None = None,
        check_ids: frozenset[str] | None = None,
        excluded_ids: frozenset[str] = frozenset(),
    ) -> list[HealthCheck]:
        """Return a filtered list of registered checks.

        Filters are applied with AND logic: a check must satisfy all provided
        filters to be included.

        Args:
            platform: Include only checks applicable to this platform.
            categories: Include only checks in these categories.
            check_ids: Include only checks with these IDs (whitelist).
            excluded_ids: Exclude checks with these IDs.

        Returns:
            Ordered list of matching ``HealthCheck`` instances.
        """
        if check_ids is not None:
            self.require_check_ids(check_ids)
        result: list[HealthCheck] = []
        for check in self._checks.values():
            if check.metadata.check_id in excluded_ids:
                continue
            if check_ids is not None and check.metadata.check_id not in check_ids:
                continue
            if platform is not None and platform not in check.metadata.platforms:
                continue
            if categories is not None and check.metadata.category not in categories:
                continue
            result.append(check)
        return result

    def inventory(self) -> InventoryClosure:
        """Generate a fail-closed static inventory for all discovered checks."""
        return build_inventory(self.all_checks)

    def get_k3s_checks(self) -> list[HealthCheck]:
        """Return only checks explicitly applicable or adapted to in-cluster k3s."""
        closure = self.inventory()
        if not closure.closed:
            msg = "; ".join(
                (
                    *closure.errors,
                    f"unknown={sorted(closure.unknown_ids)}",
                    f"silent={sorted(closure.silent_skip_ids)}",
                )
            )
            message = f"Health inventory is not closed: {msg}"
            raise ValueError(message)
        runnable = closure.applicable_ids | closure.adapted_ids
        return [check for check in self.all_checks if check.metadata.check_id in runnable]

    def require_check_ids(self, check_ids: frozenset[str]) -> None:
        """Reject requested IDs that are not registered instead of silently succeeding."""
        unknown = check_ids - self._checks.keys()
        if unknown:
            message = f"Unknown health check IDs: {sorted(unknown)}"
            raise ValueError(message)

    def get_check(self, check_id: str) -> HealthCheck | None:
        """Return the registered check with the given ID, or None if not found.

        Args:
            check_id: Unique check identifier.

        Returns:
            The matching ``HealthCheck`` instance or ``None``.
        """
        return self._checks.get(check_id)

    @property
    def all_checks(self) -> list[HealthCheck]:
        """All registered checks in insertion order."""
        return list(self._checks.values())

    def __len__(self) -> int:
        """Return the number of registered checks."""
        return len(self._checks)
