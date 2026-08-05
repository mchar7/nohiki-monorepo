"""Workspace package discovery, classification, and dependency graph.

Single source of truth for uv workspace membership: enumeration from the
root pyproject.toml, path-based categorization, and the internal
dependency graph used for affected-package expansion.
"""

from __future__ import annotations

import ast
import tomllib
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


def _find_workspace_root(start: Path) -> Path:
    """Walk up from start until we find the uv workspace root.

    The workspace root is identified by a pyproject.toml containing a
    [tool.uv.workspace] table. Anchoring on this marker keeps path
    discovery correct regardless of how deeply this module is nested
    inside its own package.
    """
    for candidate in (start, *start.parents):
        toml = candidate / "pyproject.toml"
        if toml.is_file():
            data = tomllib.loads(toml.read_text())
            if "workspace" in data.get("tool", {}).get("uv", {}):
                return candidate
    msg = f"could not locate uv workspace root above {start}"
    raise RuntimeError(msg)


REPO_ROOT = _find_workspace_root(Path(__file__).resolve().parent)
BACKEND_DIR = REPO_ROOT / "backend"
SERVICES_DIR = BACKEND_DIR / "services"
LIBS_DIR = BACKEND_DIR / "libs"
JOBS_DIR = BACKEND_DIR / "jobs"
SCRIPTS_DIR = REPO_ROOT / "scripts"


class PackageType(StrEnum):
    """Package category based on repository path."""

    SERVICE = "service"
    LIB = "lib"
    JOB = "job"
    SCRIPTS = "scripts"
    OTHER = "other"


class Scope(StrEnum):
    """Scan scope filter."""

    ALL = "all"
    SERVICES = "services"
    LIBS = "libs"
    JOBS = "jobs"
    SCRIPTS = "scripts"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class Package:
    """Workspace package metadata with common path-derived properties."""

    name: str
    path: Path
    pkg_type: PackageType
    # Only populated when loading packages with dependency tracking (test runner).
    deps: frozenset[str] = field(default_factory=frozenset)
    # Package-relative pytest collection roots (``testpaths``, else ``tests``) that exist.
    test_roots: frozenset[str] = field(default_factory=frozenset)
    # Package-relative test modules carrying the canonical container marker.
    requires_docker_tests: frozenset[str] = field(default_factory=frozenset)

    @property
    def src_dir(self) -> Path:
        """Conventional src/ layout directory (used by backend packages)."""
        return self.path / "src"

    @property
    def has_src(self) -> bool:
        """Whether the package has a src/ directory (used by deadcode/deptry checks)."""
        return self.src_dir.is_dir()

    @property
    def tests_dir(self) -> Path:
        """Conventional tests/ directory."""
        return self.path / "tests"

    @property
    def has_tests(self) -> bool:
        """Whether the package has conventional or marker-discovered tests."""
        return self.tests_dir.is_dir() or bool(self.requires_docker_tests)

    @property
    def test_paths(self) -> tuple[Path, ...]:
        """Directories pytest collects for this package.

        A workspace member may configure ``testpaths`` away from ``tests/``; handing pytest
        the conventional directory then names a path that does not exist and aborts the run.
        Directly constructed packages carry no loader-derived roots and keep the convention.
        """
        return tuple(self.path / root for root in sorted(self.test_roots)) or (self.tests_dir,)


def _pytest_test_roots(path: Path, config: dict[str, object]) -> tuple[Path, ...]:
    pytest_options = config.get("tool", {})
    if isinstance(pytest_options, dict):
        pytest_options = pytest_options.get("pytest", {})
    if isinstance(pytest_options, dict):
        pytest_options = pytest_options.get("ini_options", {})
    if isinstance(pytest_options, dict):
        configured = pytest_options.get("testpaths")
        if isinstance(configured, list) and all(isinstance(value, str) for value in configured):
            return tuple(path / value for value in configured if isinstance(value, str))
    return (path / "tests",)


def pytest_file_has_marker(path: Path, marker: str) -> bool:
    """Return whether a Python test module contains ``pytest.mark.<marker>``."""
    try:
        module = ast.parse(path.read_bytes(), filename=str(path))
    except OSError, SyntaxError:
        return False
    return any(
        isinstance(node, ast.Attribute)
        and node.attr == marker
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "mark"
        and isinstance(node.value.value, ast.Name)
        and node.value.value.id == "pytest"
        for node in ast.walk(module)
    )


def requires_docker_test_paths(path: Path, config: dict[str, object]) -> frozenset[str]:
    """Derive package-relative container test paths from the canonical marker."""
    return frozenset(
        test_file.relative_to(path).as_posix()
        for root in _pytest_test_roots(path, config)
        if root.is_dir()
        for test_file in root.rglob("test_*.py")
        if pytest_file_has_marker(test_file, "requires_docker")
    )


def pytest_test_roots(path: Path, config: dict[str, object]) -> frozenset[str]:
    """Derive the package-relative pytest collection roots that exist on disk."""
    return frozenset(root.relative_to(path).as_posix() for root in _pytest_test_roots(path, config) if root.is_dir())


def _classify_package(path: Path) -> PackageType:
    """Classify a package's type from its filesystem path."""
    if path.is_relative_to(SERVICES_DIR):
        return PackageType.SERVICE
    if path.is_relative_to(LIBS_DIR):
        return PackageType.LIB
    if path.is_relative_to(JOBS_DIR):
        return PackageType.JOB
    if path.is_relative_to(SCRIPTS_DIR):
        return PackageType.SCRIPTS
    return PackageType.OTHER


def _parse_dependency_name(dep_str: str) -> str:
    """Extract the bare package name from a dependency specifier like 'pkg[extra]>=1.0'."""
    for sep in ("[", "<", ">", "=", "!", ";"):
        dep_str = dep_str.split(sep, maxsplit=1)[0]
    return dep_str.strip()


def _iter_dependency_specifiers(pkg_config: dict[str, object]) -> list[str]:
    """Collect every dependency specifier a package declares.

    Covers runtime dependencies, optional extras, and PEP 735 dependency
    groups. Test-only workspace deps (e.g. nohiki-test-utils in a service's
    test extra) must count as graph edges: a change there can break the
    dependent's suite even though runtime code never imports it.
    """
    specs: list[str] = []
    project = pkg_config.get("project")
    if isinstance(project, dict):
        deps = project.get("dependencies")
        if isinstance(deps, list):
            specs.extend(entry for entry in deps if isinstance(entry, str))
        extras = project.get("optional-dependencies")
        if isinstance(extras, dict):
            for extra_deps in extras.values():
                if isinstance(extra_deps, list):
                    specs.extend(entry for entry in extra_deps if isinstance(entry, str))
    groups = pkg_config.get("dependency-groups")
    if isinstance(groups, dict):
        for group_deps in groups.values():
            if isinstance(group_deps, list):
                # {include-group = "..."} entries reference sibling groups
                # that this loop already walks; only strings are specifiers.
                specs.extend(entry for entry in group_deps if isinstance(entry, str))
    return specs


def build_reverse_dependency_index(packages: dict[str, Package]) -> dict[str, set[str]]:
    """Build a map from each package to the set of packages that depend on it.

    Args:
        packages: All known workspace packages with deps populated.

    Returns:
        Dict mapping package name to the set of dependent package names.
    """
    index: dict[str, set[str]] = {name: set() for name in packages}
    for name, pkg in packages.items():
        for dep in pkg.deps:
            if dep in index:
                index[dep].add(name)
    return index


def expand_to_dependents(changed: set[str], reverse_deps: dict[str, set[str]]) -> set[str]:
    """Expand a set of changed packages to include all transitive dependents.

    Args:
        changed: Directly changed package names.
        reverse_deps: Index from build_reverse_dependency_index.

    Returns:
        Expanded set including all transitive dependents.
    """
    result = set(changed)
    queue = list(changed)
    while queue:
        pkg = queue.pop()
        for dependent in reverse_deps.get(pkg, set()):
            if dependent not in result:
                result.add(dependent)
                queue.append(dependent)
    return result


def _scope_filter(pkg_type: PackageType, scope: Scope) -> bool:
    """Return True if the package should be included for the given scope."""
    match scope:
        case Scope.ALL:
            return True
        case Scope.SERVICES:
            return pkg_type == PackageType.SERVICE
        case Scope.LIBS:
            return pkg_type == PackageType.LIB
        case Scope.JOBS:
            return pkg_type == PackageType.JOB
        case Scope.SCRIPTS:
            return pkg_type == PackageType.SCRIPTS
        case Scope.OTHER:
            return pkg_type == PackageType.OTHER


def load_packages(scope: Scope, *, require_src: bool = False, require_tests: bool = False) -> list[Package]:
    """Load workspace packages from the root pyproject.toml.

    Args:
        scope: Filter to all packages or one package category.
        require_src: Only include packages with a src/ directory.
        require_tests: Only include packages with a tests/ directory.

    Returns:
        Filtered list of Package metadata objects.
    """
    root_toml = REPO_ROOT / "pyproject.toml"
    if not root_toml.exists():
        return []

    config = tomllib.loads(root_toml.read_text())
    globs: list[str] = config.get("tool", {}).get("uv", {}).get("workspace", {}).get("members", [])

    packages: list[Package] = []
    for glob in globs:
        pkg_path = (REPO_ROOT / glob).resolve()
        pkg_toml = pkg_path / "pyproject.toml"
        if not pkg_toml.exists():
            continue

        pkg_type = _classify_package(pkg_path)
        if not _scope_filter(pkg_type, scope):
            continue

        pkg_config = tomllib.loads(pkg_toml.read_text())
        # The project name is the canonical identity; directory basenames diverge for script packages.
        name = pkg_config.get("project", {}).get("name") or pkg_path.name
        pkg = Package(
            name=name,
            path=pkg_path,
            pkg_type=pkg_type,
            test_roots=pytest_test_roots(pkg_path, pkg_config),
            requires_docker_tests=requires_docker_test_paths(pkg_path, pkg_config),
        )
        if require_src and not pkg.has_src:
            continue
        # Deliberately the conventional directory, not `has_tests`: the fixture and coverage
        # consumers both assume a `tests/` sibling of a measurable `src/`, which a package
        # whose only tests are marker-discovered under another root does not have.
        if require_tests and not pkg.tests_dir.is_dir():
            continue
        packages.append(pkg)

    return packages


def load_packages_with_deps(scope: Scope) -> dict[str, Package]:
    """Load workspace packages including per-package dependency metadata.

    Reads each package's pyproject.toml to extract declared dependencies.
    Used by the test runner for transitive affected-package detection.

    Args:
        scope: Filter to services, libs, or all packages.

    Returns:
        Dict mapping package name to Package (with deps populated).
    """
    root_toml = REPO_ROOT / "pyproject.toml"
    if not root_toml.exists():
        return {}

    config = tomllib.loads(root_toml.read_text())
    globs: list[str] = config.get("tool", {}).get("uv", {}).get("workspace", {}).get("members", [])

    packages: dict[str, Package] = {}
    for glob in globs:
        pkg_path = (REPO_ROOT / glob).resolve()
        pkg_toml = pkg_path / "pyproject.toml"
        if not pkg_toml.exists():
            continue

        pkg_config = tomllib.loads(pkg_toml.read_text())
        name = pkg_config.get("project", {}).get("name")
        if not name:
            continue

        pkg_type = _classify_package(pkg_path)
        if not _scope_filter(pkg_type, scope):
            continue

        deps = frozenset(_parse_dependency_name(d) for d in _iter_dependency_specifiers(pkg_config))

        packages[name] = Package(
            name=name,
            path=pkg_path,
            pkg_type=pkg_type,
            deps=deps,
            test_roots=pytest_test_roots(pkg_path, pkg_config),
            requires_docker_tests=requires_docker_test_paths(pkg_path, pkg_config),
        )

    return packages
