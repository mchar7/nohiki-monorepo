"""Empirical package discovery from pyproject.toml files."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class PackageType(StrEnum):
    """Type of package in the monorepo."""

    SERVICE = "service"
    SHARED_LIB = "lib"
    JOB = "job"
    SCRIPT = "script"
    TEST = "test"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Package:
    """A package in the monorepo."""

    name: str
    path: Path
    package_type: PackageType
    python_package: str


@dataclass(slots=True)
class PackageRegistry:
    """Registry of discovered packages in the monorepo."""

    packages: dict[str, Package] = field(default_factory=dict)
    shared_libs: frozenset[str] = field(default_factory=frozenset)
    services: frozenset[str] = field(default_factory=frozenset)
    jobs: frozenset[str] = field(default_factory=frozenset)
    _path_to_package: dict[Path, Package] = field(default_factory=dict)

    def get_package_for_path(self, file_path: Path) -> Package | None:
        """Find the package containing a file path."""
        resolved = file_path.resolve()
        for pkg_path, pkg in self._path_to_package.items():
            if resolved.is_relative_to(pkg_path):
                return pkg
        return None

    def is_shared_lib(self, name: str) -> bool:
        """Check if a package name is a shared library."""
        return name in self.shared_libs


def discover_packages(root: Path) -> PackageRegistry:
    """Discover all packages from pyproject.toml workspace members."""
    root = root.resolve()
    root_pyproject = root / "pyproject.toml"

    if not root_pyproject.exists():
        return _fallback_discovery(root)

    members = _parse_workspace_members(root_pyproject)
    return _build_registry(root, members)


def _parse_workspace_members(pyproject_path: Path) -> list[str]:
    """Parse workspace members from pyproject.toml."""
    content = pyproject_path.read_text(encoding="utf-8")
    pattern = re.compile(r"\[tool\.uv\.workspace\]\s*members\s*=\s*\[(.*?)\]", re.DOTALL)
    match = pattern.search(content)

    if not match:
        return []

    members_block = match.group(1)
    member_pattern = re.compile(r'"([^"]+)"')
    return member_pattern.findall(members_block)


def _build_registry(root: Path, members: list[str]) -> PackageRegistry:
    """Build package registry from workspace members."""
    packages: dict[str, Package] = {}
    path_to_package: dict[Path, Package] = {}
    shared_libs: set[str] = set()
    services: set[str] = set()
    jobs: set[str] = set()

    for member in members:
        if not (member_path := root / member).exists():
            continue

        pkg = _create_package(member_path, member)
        packages[pkg.name] = pkg
        path_to_package[pkg.path] = pkg

        match pkg.package_type:
            case PackageType.SHARED_LIB:
                shared_libs.add(pkg.python_package)
            case PackageType.SERVICE:
                services.add(pkg.name)
            case PackageType.JOB:
                jobs.add(pkg.name)

    return PackageRegistry(
        packages=packages,
        shared_libs=frozenset(shared_libs),
        services=frozenset(services),
        jobs=frozenset(jobs),
        _path_to_package=path_to_package,
    )


def _create_package(path: Path, member: str) -> Package:
    """Create a Package from a path and member string."""
    name = path.name
    return Package(
        name=name,
        path=path.resolve(),
        package_type=_infer_package_type(member),
        python_package=name.replace("-", "_"),
    )


def _infer_package_type(member: str) -> PackageType:
    """Infer package type from workspace member path."""
    match member:
        case m if m.startswith("backend/services/"):
            return PackageType.SERVICE
        case m if m.startswith("backend/libs/"):
            return PackageType.SHARED_LIB
        case m if m.startswith("backend/jobs/"):
            return PackageType.JOB
        case m if m.startswith("scripts/"):
            return PackageType.SCRIPT
        case "tests":
            return PackageType.TEST
        case _:
            return PackageType.UNKNOWN


def _fallback_discovery(root: Path) -> PackageRegistry:
    """Fallback: discover packages by scanning directory structure."""
    packages: dict[str, Package] = {}
    path_to_package: dict[Path, Package] = {}
    shared_libs: set[str] = set()
    services: set[str] = set()
    jobs: set[str] = set()

    scan_dirs = [
        (root / "backend" / "services", PackageType.SERVICE),
        (root / "backend" / "libs", PackageType.SHARED_LIB),
        (root / "backend" / "jobs", PackageType.JOB),
    ]

    for scan_dir, pkg_type in scan_dirs:
        if not scan_dir.exists():
            continue

        for child in scan_dir.iterdir():
            if not child.is_dir() or not (child / "pyproject.toml").exists():
                continue

            pkg = Package(
                name=child.name,
                path=child.resolve(),
                package_type=pkg_type,
                python_package=child.name.replace("-", "_"),
            )
            packages[pkg.name] = pkg
            path_to_package[pkg.path] = pkg

            match pkg_type:
                case PackageType.SHARED_LIB:
                    shared_libs.add(pkg.python_package)
                case PackageType.SERVICE:
                    services.add(pkg.name)
                case PackageType.JOB:
                    jobs.add(pkg.name)

    return PackageRegistry(
        packages=packages,
        shared_libs=frozenset(shared_libs),
        services=frozenset(services),
        jobs=frozenset(jobs),
        _path_to_package=path_to_package,
    )
