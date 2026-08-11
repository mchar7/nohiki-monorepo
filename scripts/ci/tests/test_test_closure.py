"""Contract tests for the test-tree import closure check.

The check exists because pytest executes a module body before it deselects the
module, so a module-level out-of-closure import in an unselected test imposes
that dependency on every partial environment that collects the directory. The
prescribed repair is a function-local import, so the check must draw exactly
that line: module level fails, function level passes.
"""

from __future__ import annotations

import ast
from pathlib import Path

from ci_checks.checks.test_closure import (
    ENFORCED_PACKAGES,
    ClosureResult,
    _executed_imports,
    declared_closure,
    render_results,
    scan_package,
)
from ci_checks.core.packages import Package, PackageType, Scope, load_packages


def _fake_package(tmp_path: Path, test_source: str, *, dependencies: str = '"typer"') -> Package:
    """Build a throwaway workspace package with one test module."""
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nname = "sample-pkg"\ndependencies = [{dependencies}]\n',
        encoding="utf-8",
    )
    src = tmp_path / "src" / "sample_pkg"
    src.mkdir(parents=True)
    (src / "__init__.py").write_text("", encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_sample.py").write_text(test_source, encoding="utf-8")
    return Package(name="sample-pkg", path=tmp_path, pkg_type=PackageType.OTHER)


def test_module_level_out_of_closure_import_is_a_violation(tmp_path: Path) -> None:
    """The failure mode the check exists for: a top-level undeclared import."""
    pkg = _fake_package(tmp_path, "import jsonschema\n\n\ndef test_x() -> None:\n    assert jsonschema\n")

    result = scan_package(pkg)

    assert result.files_scanned == 1
    assert [(line, module) for _, line, module in result.violations] == [(1, "jsonschema")]


def test_function_local_import_of_the_same_module_passes(tmp_path: Path) -> None:
    """The prescribed repair must clear the check; otherwise the repair is unreachable."""
    pkg = _fake_package(tmp_path, "def test_x() -> None:\n    import jsonschema\n\n    assert jsonschema\n")

    assert scan_package(pkg).violations == []


def test_intra_directory_and_relative_imports_are_not_violations(tmp_path: Path) -> None:
    """Sibling test modules and local helpers are not third-party dependencies."""
    pkg = _fake_package(
        tmp_path,
        "import helm_test_utils\nfrom _documents import Manifest\nfrom . import conftest\nimport sample_pkg\n",
    )
    (tmp_path / "tests" / "helm_test_utils.py").write_text("", encoding="utf-8")
    (tmp_path / "tests" / "_documents.py").write_text("Manifest = dict\n", encoding="utf-8")

    assert scan_package(pkg).violations == []


def test_declared_dependencies_and_stdlib_are_not_violations(tmp_path: Path) -> None:
    """Declared distributions clear, including ones whose import name differs."""
    pkg = _fake_package(
        tmp_path,
        "import tomllib\nimport typer\nimport yaml\n",
        dependencies='"typer>=0.21.0", "pyyaml>=6.0.3"',
    )

    assert scan_package(pkg).violations == []


def test_transitively_available_but_undeclared_import_still_fails(tmp_path: Path) -> None:
    """Availability is not declaration.

    ``jsonschema`` is installed and reachable from ci-checks through
    skylos -> mcp, which is why deptry rates it DEP003 rather than DEP001. The
    closure is the DIRECT declaration set, so reachability must not launder it.
    """
    pkg = _fake_package(tmp_path, "import jsonschema\n", dependencies='"typer"')

    assert "jsonschema" not in declared_closure(pkg)
    assert [module for _, _, module in scan_package(pkg).violations] == ["jsonschema"]


def test_imports_that_do_not_execute_at_import_time_are_ignored(tmp_path: Path) -> None:
    """``if TYPE_CHECKING:`` bodies never run, so they impose no environment cost."""
    source = "from typing import TYPE_CHECKING\n\nif TYPE_CHECKING:\n    import jsonschema\n"
    pkg = _fake_package(tmp_path, source)

    assert scan_package(pkg).violations == []


def test_imports_nested_in_executed_blocks_are_caught(tmp_path: Path) -> None:
    """A try/except or class body still executes on import; hiding there must not work."""
    source = "try:\n    import jsonschema\nexcept ImportError:\n    jsonschema = None\n"
    pkg = _fake_package(tmp_path, source)

    assert [module for _, _, module in scan_package(pkg).violations] == ["jsonschema"]

    class_body = "class Helper:\n    import jsonschema\n"
    assert _executed_imports(ast.parse(class_body).body) == [("jsonschema", 2)]


def test_declared_closure_covers_extras_and_dependency_groups() -> None:
    """Test tooling declared in a PEP 735 group is declared, so it must clear."""
    package = next(pkg for pkg in load_packages(Scope.SCRIPTS) if pkg.name == "ci-checks")

    closure = declared_closure(package)

    assert {"typer", "rich", "pyyaml", "coverage"} <= closure
    assert {"pytest", "pytest-asyncio", "pytest-xdist"} <= closure, "container-tests group must count"
    assert "skylos" in closure, "deadcode group must count"
    assert "jsonschema" not in closure


def test_enforced_scope_is_green_and_names_only_measured_packages() -> None:
    """The enforced allowlist must pass today; a red rule on landing gets suppressed."""
    assert frozenset({"ci-checks"}) == ENFORCED_PACKAGES

    results = [
        scan_package(pkg) for pkg in load_packages(Scope.ALL, require_tests=True) if pkg.name in ENFORCED_PACKAGES
    ]

    assert len(results) == 1
    assert results[0].violations == [], f"scripts/ci test tree regressed: {results[0].violations}"
    assert render_results(results) is True


def test_render_results_reports_failure() -> None:
    """A violating package must make the renderer return False so the CLI exits non-zero."""
    failing = ClosureResult(name="sample-pkg", files_scanned=1)
    failing.violations.append(("scripts/ci/tests/test_x.py", 3, "jsonschema"))

    assert render_results([failing]) is False
