"""Test-tree import closure check.

A package's test tree may import at module level only from that package's
declared closure. Pytest collects before it deselects, so a marker-excluded
test still has its module body executed: a module-level third-party import in
an unselected test imposes that dependency on every partial environment that
collects the directory. That is how ``boto3`` reached hosted CI and failed.

Neither existing tool reaches this. import-linter cannot: grimp builds its
graph from importable packages and every test tree here lives outside ``src/``.
Ruff cannot express it: ``banned-module-level-imports`` is a single global
table and ``per-file-ignores`` only subtracts, so a directory-scoped allowlist
has no representation.

Imports inside function bodies are fine -- that is the prescribed repair, and
it is what the production helpers already do. Relative imports and imports of
modules that live in the test tree itself are intra-directory, not violations.
"""

from __future__ import annotations

import ast
import re
import sys
import tomllib
from dataclasses import dataclass, field
from functools import cache
from importlib.metadata import packages_distributions

from ci_checks.core.display import render_error_panel, render_summary_table
from ci_checks.core.packages import (
    REPO_ROOT,
    Package,
    _iter_dependency_specifiers,
    _parse_dependency_name,
)

# Enforcement scope. Widening is a configuration change: add a package name.
#
# Workspace-wide enforcement is not green today, so it is not the default --
# a rule that fails on the day it lands gets suppressed and never comes back.
# ``scripts/ci`` is enforced because its test tree was measured clean after
# three function-local repairs. ``--packages`` overrides this for measurement
# and for staged rollout.
ENFORCED_PACKAGES: frozenset[str] = frozenset({"ci-checks"})


def _normalize(name: str) -> str:
    """Normalize a distribution or module name to its PEP 503 comparison form."""
    return re.sub(r"[-_.]+", "-", name).lower()


@cache
def _module_distributions() -> dict[str, tuple[str, ...]]:
    """Map importable top-level module name to the distributions providing it.

    Resolved from the running interpreter's installed metadata, which is how
    ``yaml`` is known to come from ``pyyaml``. Modules absent from the
    environment fall back to name equality at the callsite, which fails closed.
    """
    return {module: tuple(dists) for module, dists in packages_distributions().items()}


def _local_module_names(pkg: Package) -> frozenset[str]:
    """Top-level module names importable from within the package itself.

    Covers sibling test modules and local helpers (pytest inserts each test
    directory on ``sys.path`` under rootdir-relative collection) plus the
    package's own shipped modules under ``src/``.
    """
    names: set[str] = set()
    if pkg.has_tests:
        for path in pkg.tests_dir.rglob("*.py"):
            names.add(path.parent.name if path.name == "__init__.py" else path.stem)
        for path in pkg.tests_dir.rglob("*"):
            if path.is_dir() and (path / "__init__.py").is_file():
                names.add(path.name)
    if pkg.has_src:
        names.update(entry.stem if entry.is_file() else entry.name for entry in pkg.src_dir.iterdir())
    return frozenset(names)


def declared_closure(pkg: Package) -> frozenset[str]:
    """Normalized distribution names the package declares.

    Reuses the workspace resolver the deptry wrapper depends on, so runtime
    dependencies, extras and PEP 735 dependency groups all count. Test tooling
    declared in a group is part of the closure by construction: it is declared.
    """
    pkg_toml = pkg.path / "pyproject.toml"
    if not pkg_toml.is_file():
        return frozenset()
    config = tomllib.loads(pkg_toml.read_text(encoding="utf-8"))
    declared = {_normalize(_parse_dependency_name(spec)) for spec in _iter_dependency_specifiers(config)}
    declared.add(_normalize(pkg.name))
    return frozenset(declared)


def _is_type_checking_guard(node: ast.stmt) -> bool:
    """Whether the statement is an ``if TYPE_CHECKING:`` block (never executed)."""
    if not isinstance(node, ast.If):
        return False
    test = node.test
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    return isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"


def _executed_imports(body: list[ast.stmt]) -> list[tuple[str, int]]:
    """Collect (top-level module, line) for imports that run on module import.

    Descends through ``if``/``try``/``with``/``for`` and class bodies, all of
    which execute during import, and stops at function boundaries, which do
    not. ``if TYPE_CHECKING:`` blocks are skipped: they never execute.
    """
    found: list[tuple[str, int]] = []
    for node in body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) or _is_type_checking_guard(node):
            continue
        if isinstance(node, ast.Import):
            found.extend((alias.name.split(".", maxsplit=1)[0], node.lineno) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            # level > 0 is a relative import: intra-directory by definition.
            if node.level == 0 and node.module:
                found.append((node.module.split(".", maxsplit=1)[0], node.lineno))
        else:
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.stmt):
                    found.extend(_executed_imports([child]))
    return found


@dataclass(slots=True)
class ClosureResult:
    """Scan result for one package's test tree."""

    name: str
    files_scanned: int = 0
    # (repo-relative path, line, module) for each out-of-closure module-level import.
    violations: list[tuple[str, int, str]] = field(default_factory=list)
    parse_errors: list[str] = field(default_factory=list)

    @property
    def issues_found(self) -> int:
        """Total findings, counting unparseable files as findings."""
        return len(self.violations) + len(self.parse_errors)


def scan_package(pkg: Package) -> ClosureResult:
    """Check every module-level import in a package's test tree against its closure."""
    result = ClosureResult(name=pkg.name)
    if not pkg.has_tests:
        return result

    closure = declared_closure(pkg)
    local = {_normalize(name) for name in _local_module_names(pkg)}
    module_dists = _module_distributions()

    for path in sorted(pkg.tests_dir.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            result.parse_errors.append(f"{path}: {exc}")
            continue
        result.files_scanned += 1
        for module, lineno in _executed_imports(tree.body):
            if module in sys.stdlib_module_names:
                continue
            normalized = _normalize(module)
            if normalized in local:
                continue
            providers = {_normalize(dist) for dist in module_dists.get(module, ())} or {normalized}
            if providers & closure:
                continue
            relative = path.relative_to(REPO_ROOT) if path.is_relative_to(REPO_ROOT) else path
            result.violations.append((str(relative), lineno, module))

    return result


def ci_suffix(result: ClosureResult) -> str:
    """CI-mode suffix showing finding count when non-zero."""
    return f" ({result.issues_found} issues)" if result.issues_found else ""


def render_results(results: list[ClosureResult]) -> bool:
    """Render the summary and per-package detail panels. True when all pass."""
    failed = [result for result in results if result.issues_found]

    render_summary_table(
        "Test Import Closure",
        clean_count=len(results) - len(failed),
        failed_count=len(failed),
        total_issues=sum(result.issues_found for result in results),
        extra_rows=[("Files scanned", str(sum(result.files_scanned for result in results)))],
    )

    for result in failed:
        lines = [
            f"{path}:{lineno} imports [bold]{module}[/bold] at module level, outside the declared closure"
            for path, lineno, module in result.violations
        ]
        lines.extend(result.parse_errors)
        lines.append("")
        lines.append("Move the import into the tests that use it, or declare the dependency.")
        render_error_panel(result.name, "\n".join(lines))

    return not failed
