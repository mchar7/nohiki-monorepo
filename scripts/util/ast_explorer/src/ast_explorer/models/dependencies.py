"""Models for cross-package dependency analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ast_explorer.discovery.packages import Package, PackageType
from ast_explorer.models.nodes import SymbolNode

__all__ = [
    "DependencyGraph",
    "ImpactAnalysis",
    "ImportReference",
    "Package",
    "PackageDependency",
    "PackageType",
    "SymbolUsage",
]


@dataclass(frozen=True, slots=True)
class ImportReference:
    """A single import statement reference."""

    module: str
    names: tuple[str, ...]
    file_path: Path
    line: int
    is_from_import: bool
    alias: str | None = None

    @property
    def package_name(self) -> str:
        """Extract the top-level package name from the module."""
        return self.module.split(".")[0]


@dataclass(slots=True)
class PackageDependency:
    """Dependency relationship between packages."""

    source_package: Package
    target_package: str
    imports: list[ImportReference] = field(default_factory=list)

    @property
    def import_count(self) -> int:
        """Number of imports from target package."""
        return len(self.imports)

    @property
    def imported_symbols(self) -> set[str]:
        """Set of all symbols imported from target package."""
        return {name for imp in self.imports for name in imp.names}


@dataclass(slots=True)
class SymbolUsage:
    """Where a symbol is used in the codebase."""

    symbol_name: str
    symbol_qualified_name: str
    defined_in: Path
    used_in: list[ImportReference] = field(default_factory=list)

    @property
    def usage_count(self) -> int:
        """Number of places this symbol is imported."""
        return len(self.used_in)

    @property
    def packages_using(self) -> set[str]:
        """Set of packages that use this symbol."""
        return {imp.file_path.parts[0] for imp in self.used_in if imp.file_path.parts}


@dataclass(slots=True)
class DependencyGraph:
    """Complete dependency graph for the codebase."""

    packages: dict[str, Package] = field(default_factory=dict)
    dependencies: dict[str, list[PackageDependency]] = field(default_factory=dict)
    symbol_usages: dict[str, SymbolUsage] = field(default_factory=dict)
    shared_lib_packages: frozenset[str] = field(default_factory=frozenset)

    def get_package_dependencies(self, package_name: str) -> list[PackageDependency]:
        """Get all dependencies for a package."""
        return self.dependencies.get(package_name, [])

    def get_dependents(self, package_name: str) -> list[str]:
        """Get packages that depend on this package."""
        return [pkg for pkg, deps in self.dependencies.items() if any(d.target_package == package_name for d in deps)]

    def get_shared_lib_usage(self, lib_name: str) -> list[PackageDependency]:
        """Get all usages of a shared library across packages."""
        return [dep for deps in self.dependencies.values() for dep in deps if dep.target_package == lib_name]

    def get_symbol_impact(self, qualified_name: str) -> SymbolUsage | None:
        """Get impact analysis for a symbol."""
        return self.symbol_usages.get(qualified_name)

    def get_cross_service_dependencies(self) -> dict[str, list[str]]:
        """Get services that share dependencies on the same libs."""
        lib_to_services: dict[str, list[str]] = {}
        for pkg_name, deps in self.dependencies.items():
            if not (pkg := self.packages.get(pkg_name)) or pkg.package_type != PackageType.SERVICE:
                continue
            for dep in deps:
                if dep.target_package in self.shared_lib_packages:
                    lib_to_services.setdefault(dep.target_package, []).append(pkg_name)
        return lib_to_services


@dataclass(slots=True)
class ImpactAnalysis:
    """Analysis of what would be affected by changing a symbol."""

    symbol: SymbolNode | None
    symbol_qualified_name: str
    defined_in_package: str
    defined_in_file: Path

    direct_imports: list[ImportReference] = field(default_factory=list)
    affected_packages: set[str] = field(default_factory=set)
    affected_services: set[str] = field(default_factory=set)
    affected_event_handlers: list[str] = field(default_factory=list)
    affected_event_publishers: list[str] = field(default_factory=list)

    @property
    def is_cross_package(self) -> bool:
        """True if symbol is used outside its defining package."""
        return len(self.affected_packages) > 1

    @property
    def is_cross_service(self) -> bool:
        """True if symbol is used across multiple services."""
        return len(self.affected_services) > 1
