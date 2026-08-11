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

import pytest
from ci_checks import app as ci_app_module
from ci_checks.checks.test_closure import (
    ENFORCED_PACKAGES,
    ClosureResult,
    _executed_imports,
    _module_distributions,
    _workspace_module_map,
    declared_closure,
    render_results,
    scan_package,
)
from ci_checks.core.packages import Package, PackageType, Scope, load_packages
from typer.testing import CliRunner


def _fake_package(tmp_path: Path, test_source: str, *, dependencies: str = '"typer"') -> Package:
    """Build a throwaway workspace package with one test module."""
    tmp_path.mkdir(parents=True, exist_ok=True)
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


@pytest.mark.parametrize(
    ("binding", "guard"),
    [
        ("from typing import TYPE_CHECKING", "TYPE_CHECKING"),
        ("from typing import TYPE_CHECKING as TC", "TC"),
        ("import typing", "typing.TYPE_CHECKING"),
        ("import typing as t", "t.TYPE_CHECKING"),
    ],
)
def test_imports_that_do_not_execute_at_import_time_are_ignored(
    tmp_path: Path,
    binding: str,
    guard: str,
) -> None:
    """Known forms of typing's sentinel impose no runtime environment cost."""
    pkg = _fake_package(tmp_path, f"{binding}\n\nif {guard}:\n    import jsonschema\n")

    assert scan_package(pkg).violations == []


def test_imports_nested_in_executed_blocks_are_caught(tmp_path: Path) -> None:
    """A try/except or class body still executes on import; hiding there must not work."""
    source = "try:\n    import jsonschema\nexcept ImportError:\n    jsonschema = None\n"
    pkg = _fake_package(tmp_path, source)

    assert [module for _, _, module in scan_package(pkg).violations] == ["jsonschema"]

    class_body = "class Helper:\n    import jsonschema\n"
    assert _executed_imports(ast.parse(class_body).body) == [("jsonschema", 2)]


def test_except_handler_import_is_caught(tmp_path: Path) -> None:
    """An exception handler executes during module import."""
    source = "try:\n    pass\nexcept ImportError:\n    import jsonschema\n"
    pkg = _fake_package(tmp_path, source)

    assert [module for _, _, module in scan_package(pkg).violations] == ["jsonschema"]


def test_match_case_import_is_caught(tmp_path: Path) -> None:
    """A selected match case executes during module import."""
    source = "value = 1\nmatch value:\n    case _:\n        import jsonschema\n"
    pkg = _fake_package(tmp_path, source)

    assert [module for _, _, module in scan_package(pkg).violations] == ["jsonschema"]


def test_type_checking_else_branch_import_is_caught(tmp_path: Path) -> None:
    """Only the guarded body is skipped; the runtime else branch still executes."""
    source = "from typing import TYPE_CHECKING\n\nif TYPE_CHECKING:\n    pass\nelse:\n    import jsonschema\n"
    pkg = _fake_package(tmp_path, source)

    assert [module for _, _, module in scan_package(pkg).violations] == ["jsonschema"]


def test_non_typing_type_checking_attribute_is_executable(tmp_path: Path) -> None:
    """An arbitrary object's TYPE_CHECKING attribute is not typing's sentinel."""
    source = "from sample_pkg import config\n\nif config.TYPE_CHECKING:\n    import jsonschema\n"
    pkg = _fake_package(tmp_path, source)

    assert [module for _, _, module in scan_package(pkg).violations] == ["jsonschema"]


@pytest.mark.parametrize(
    "source",
    [
        "from typing import TYPE_CHECKING as TC\nTC = True\nif TC:\n    import jsonschema\n",
        ("import typing\ntyping.TYPE_CHECKING = True\nif typing.TYPE_CHECKING:\n    import jsonschema\n"),
    ],
)
def test_rebound_type_checking_guards_are_executable(tmp_path: Path, source: str) -> None:
    """A typing sentinel stops suppressing branches after it is overwritten."""
    pkg = _fake_package(tmp_path, source)

    assert [module for _, _, module in scan_package(pkg).violations] == ["jsonschema"]


def test_type_checking_alias_state_does_not_leak_across_branches(tmp_path: Path) -> None:
    """A typing alias from one path cannot suppress an executable sibling path."""
    source = (
        "condition = False\n"
        "TC = True\n"
        "if condition:\n"
        "    from typing import TYPE_CHECKING as TC\n"
        "else:\n"
        "    if TC:\n"
        "        import jsonschema\n"
    )
    pkg = _fake_package(tmp_path, source)

    assert [module for _, _, module in scan_package(pkg).violations] == ["jsonschema"]


@pytest.mark.parametrize(
    "source",
    [
        (
            "from typing import TYPE_CHECKING as TC\n"
            "try:\n"
            "    TC = True\n"
            "except RuntimeError:\n"
            "    pass\n"
            "else:\n"
            "    if TC:\n"
            "        import jsonschema\n"
        ),
        (
            "from typing import TYPE_CHECKING as TC\n"
            "for _ in range(2):\n"
            "    if TC:\n"
            "        import jsonschema\n"
            "    TC = True\n"
        ),
        ("import typing\nclass C:\n    typing.TYPE_CHECKING = True\nif typing.TYPE_CHECKING:\n    import jsonschema\n"),
        (
            "from typing import TYPE_CHECKING as TC\n"
            "try:\n"
            "    TC = True\n"
            "    raise RuntimeError\n"
            "    from typing import TYPE_CHECKING as TC\n"
            "finally:\n"
            "    if TC:\n"
            "        import jsonschema\n"
        ),
        (
            "import typing\n"
            "class Outer:\n"
            "    class Inner:\n"
            "        typing.TYPE_CHECKING = True\n"
            "if typing.TYPE_CHECKING:\n"
            "    import jsonschema\n"
        ),
        (
            "from typing import TYPE_CHECKING as TC\n"
            "try:\n"
            '    raise ExceptionGroup("both", [ValueError(), TypeError()])\n'
            "except* ValueError:\n"
            "    TC = True\n"
            "except* TypeError:\n"
            "    if TC:\n"
            "        import jsonschema\n"
        ),
        (
            "from typing import TYPE_CHECKING as TC\n"
            "for _ in [1]:\n"
            "    TC = True\n"
            "    break\n"
            "    from typing import TYPE_CHECKING as TC\n"
            "if TC:\n"
            "    import jsonschema\n"
        ),
        (
            "from typing import TYPE_CHECKING as TC\n"
            "match True:\n"
            "    case TC if False:\n"
            "        pass\n"
            "    case _:\n"
            "        if TC:\n"
            "            import jsonschema\n"
        ),
    ],
)
def test_type_checking_state_follows_executable_control_flow(tmp_path: Path, source: str) -> None:
    """Later executable paths see sentinel mutations from earlier paths."""
    pkg = _fake_package(tmp_path, source)

    assert [module for _, _, module in scan_package(pkg).violations] == ["jsonschema"]


def test_declared_closure_covers_extras_and_dependency_groups() -> None:
    """Test tooling declared in a PEP 735 group is declared, so it must clear."""
    package = next(pkg for pkg in load_packages(Scope.SCRIPTS) if pkg.name == "ci-checks")

    closure = declared_closure(package)

    assert {"typer", "rich", "pyyaml", "coverage"} <= closure
    assert {"pytest", "pytest-asyncio", "pytest-xdist"} <= closure, "container-tests group must count"
    assert "skylos" in closure, "deadcode group must count"
    assert "jsonschema" not in closure


def test_first_party_import_names_are_derived_from_the_tree() -> None:
    """The workspace map must come off the filesystem, not a hand-maintained table.

    ``nohiki-domain-models`` ships four top-level packages whose names match
    neither the distribution nor each other, and deptry hardcodes exactly those
    four at deptry.py:225 because it hit this wall. Reading them from the
    member's source root cannot go stale: it regenerates every run.
    """
    mapping = _workspace_module_map()

    assert {"nohiki", "nohiki_proto_google", "nohiki_domain_utils", "message_pool"} <= set(mapping)
    assert {mapping[name] for name in ("nohiki", "message_pool")} == {"nohiki-domain-models"}
    assert mapping["ci_checks"] == "ci-checks"
    assert "py" not in mapping, "src/py.typed is a marker file, not an import package"
    for pkg in load_packages(Scope.ALL, require_src=True):
        assert pkg.name in set(mapping.values()), f"{pkg.name} contributes no import name"


def test_first_party_resolution_does_not_need_the_module_installed(tmp_path: Path) -> None:
    """The accuracy fix: a workspace name resolves whichever interpreter we scan from.

    ``nohiki`` is absent from the ci-checks environment, so the ambient
    metadata cannot map it. Resolving it from the tree is what lets the check
    judge a package other than the one whose environment it is running in.
    """
    assert _module_distributions().get("nohiki") is None, "precondition: not installed here"

    declared = _fake_package(tmp_path, "import nohiki\n", dependencies='"nohiki-domain-models"')
    assert scan_package(declared).violations == []

    undeclared = _fake_package(tmp_path / "other", "import nohiki\n", dependencies='"typer"')
    assert [module for _, _, module in scan_package(undeclared).violations] == ["nohiki"]


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


@pytest.mark.parametrize(
    ("enforced", "packages", "expected"),
    [
        (frozenset(), [], "No enforced packages configured"),
        (frozenset({"missing"}), [], "Unknown enforced packages"),
        (
            frozenset({"sample-pkg"}),
            [Package("sample-pkg", Path("/nonexistent"), PackageType.OTHER)],
            "Enforced packages without tests",
        ),
    ],
)
def test_enforced_selection_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    enforced: frozenset[str],
    packages: list[Package],
    expected: str,
) -> None:
    """Invalid enforced package names are configuration errors, not empty success."""
    monkeypatch.setattr(ci_app_module._test_closure, "ENFORCED_PACKAGES", enforced)
    monkeypatch.setattr(
        ci_app_module,
        "load_packages",
        lambda _scope, **kwargs: [] if kwargs.get("require_tests") else packages,
    )

    result = CliRunner().invoke(ci_app_module.app, ["test-closure"])

    assert result.exit_code == 2
    assert expected in result.output


def test_explicit_empty_selection_remains_a_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    """An explicit empty CSV is a user-selected no-op, not an enforced configuration."""
    monkeypatch.setattr(ci_app_module, "load_packages", lambda _scope, **_kwargs: [])

    result = CliRunner().invoke(ci_app_module.app, ["test-closure", "--packages", ""])

    assert result.exit_code == 0, result.output
    assert "No workspace packages selected" in result.output
