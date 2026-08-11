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
from pathlib import Path

from ci_checks.core.display import render_error_panel, render_summary_table
from ci_checks.core.packages import (
    REPO_ROOT,
    Package,
    Scope,
    _iter_dependency_specifiers,
    _parse_dependency_name,
    load_packages,
)

# Only named packages are checked by default; ``--packages`` can select others.
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


def _src_module_names(src_dir: Path) -> set[str]:
    """Top-level import packages a source root provides, read off the filesystem."""
    return {
        entry.name if entry.is_dir() else entry.stem
        for entry in src_dir.iterdir()
        if (entry.is_dir() and not entry.name.startswith(".")) or entry.suffix == ".py"
    }


@cache
def _workspace_module_map() -> dict[str, str]:
    """Map import name to the workspace distribution that ships it.

    Derived from the tree, not from the environment and not from a table. A
    member's top-level import packages are exactly the directories under its
    source root, so ``nohiki`` and its siblings resolve to
    ``nohiki-domain-models`` whether or not that member is installed in the
    interpreter running the scan. This is what makes a first-party name
    resolvable when scanning a package other than the one whose environment we
    are in, and it cannot go stale: it regenerates from the tree every run.
    """
    mapping: dict[str, str] = {}
    for pkg in load_packages(Scope.ALL, require_src=True):
        for module in _src_module_names(pkg.src_dir):
            mapping[module] = pkg.name
    return mapping


def _local_module_names(pkg: Package) -> frozenset[str]:
    """Top-level module names importable from within the package itself.

    Covers sibling test modules and local helpers (pytest inserts each test
    directory on ``sys.path`` under rootdir-relative collection) plus the
    package's own shipped modules under ``src/``.
    """
    names: set[str] = set()
    if pkg.has_tests:
        for path in pkg.tests_dir.rglob("*"):
            if path.is_dir():
                if (path / "__init__.py").is_file():
                    names.add(path.name)
            elif path.suffix == ".py":
                names.add(path.parent.name if path.name == "__init__.py" else path.stem)
    if pkg.has_src:
        names.update(_src_module_names(pkg.src_dir))
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


def _is_type_checking_guard(
    node: ast.If,
    type_checking_names: set[str],
    typing_module_names: set[str],
) -> bool:
    """Whether the node is a guard bound to ``typing.TYPE_CHECKING``."""
    test = node.test
    if isinstance(test, ast.Name):
        return test.id in type_checking_names
    return (
        isinstance(test, ast.Attribute)
        and test.attr == "TYPE_CHECKING"
        and isinstance(test.value, ast.Name)
        and test.value.id in typing_module_names
    )


def _binding_names(node: ast.AST) -> set[str]:
    """Aliases invalidated by an assignment target or match pattern."""
    names = {
        child.id
        for child in ast.walk(node)
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store | ast.Del)
    }
    names.update(
        child.name for child in ast.walk(node) if isinstance(child, ast.MatchAs | ast.MatchStar) and child.name
    )
    names.update(
        child.value.id
        for child in ast.walk(node)
        if isinstance(child, ast.Attribute) and child.attr == "TYPE_CHECKING" and isinstance(child.value, ast.Name)
    )
    return names


def _header_bindings(node: ast.stmt) -> set[str]:
    """Names bound by named expressions outside nested statement bodies."""
    names: set[str] = set()

    def visit(value: ast.AST) -> None:
        if isinstance(value, ast.stmt):
            return
        if isinstance(value, ast.NamedExpr):
            names.update(_binding_names(value.target))
        for child in ast.iter_child_nodes(value):
            visit(child)

    for _field, value in ast.iter_fields(node):
        if isinstance(value, ast.AST):
            visit(value)
        elif isinstance(value, list):
            for child in value:
                if isinstance(child, ast.AST):
                    visit(child)
    return names


def _statement_lists(node: ast.AST) -> list[list[ast.stmt]]:
    """Executable statement-list fields below a statement wrapper."""
    bodies: list[list[ast.stmt]] = []
    for _field, value in ast.iter_fields(node):
        if isinstance(value, list):
            statements = [child for child in value if isinstance(child, ast.stmt)]
            if statements:
                bodies.append(statements)
            for child in value:
                if isinstance(child, ast.AST) and not isinstance(child, ast.stmt):
                    bodies.extend(_statement_lists(child))
        elif isinstance(value, ast.AST) and not isinstance(value, ast.stmt):
            bodies.extend(_statement_lists(value))
    return bodies


def _potential_bindings(statements: list[ast.stmt]) -> set[str]:
    """Names that any path through statements may overwrite."""
    names: set[str] = set()

    def visit(node: ast.AST) -> None:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            names.add(node.name)
            return
        if isinstance(node, ast.ClassDef):
            names.add(node.name)
            names.update(_class_outer_mutations(node.body))
            return
        if isinstance(node, ast.alias):
            names.add("*" if node.name == "*" else node.asname or node.name.split(".", maxsplit=1)[0])
            return
        if isinstance(node, ast.ExceptHandler) and node.name:
            names.add(node.name)
        if isinstance(node, ast.MatchAs | ast.MatchStar) and node.name:
            names.add(node.name)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store | ast.Del):
            names.add(node.id)
        if (
            isinstance(node, ast.Attribute)
            and node.attr == "TYPE_CHECKING"
            and isinstance(node.ctx, ast.Store | ast.Del)
            and isinstance(node.value, ast.Name)
        ):
            names.add(node.value.id)
        for child in ast.iter_child_nodes(node):
            visit(child)

    for statement in statements:
        visit(statement)
    return names


def _class_outer_mutations(statements: list[ast.stmt]) -> set[str]:
    """Outer aliases a class body can mutate rather than shadow."""
    names: set[str] = set()

    def visit(node: ast.AST) -> None:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            return
        if isinstance(node, ast.Global):
            names.update(node.names)
        if (
            isinstance(node, ast.Attribute)
            and node.attr == "TYPE_CHECKING"
            and isinstance(node.ctx, ast.Store | ast.Del)
            and isinstance(node.value, ast.Name)
        ):
            names.add(node.value.id)
        for child in ast.iter_child_nodes(node):
            visit(child)

    for statement in statements:
        visit(statement)
    return names


def _executed_imports(body: list[ast.stmt]) -> list[tuple[str, int]]:
    """Collect (top-level module, line) for imports that run on module import.

    Descends through every executable statement-list field, including
    exception handlers and match cases. Function bodies do not execute during
    import. A typing ``TYPE_CHECKING`` body is skipped, but its runtime
    ``else`` branch is scanned.
    """
    found: set[tuple[str, int]] = set()

    def intersect_states(
        states: list[tuple[set[str], set[str]]],
    ) -> tuple[set[str], set[str]]:
        merged_type_names = set(states[0][0])
        merged_module_names = set(states[0][1])
        for state_type_names, state_module_names in states[1:]:
            merged_type_names.intersection_update(state_type_names)
            merged_module_names.intersection_update(state_module_names)
        return merged_type_names, merged_module_names

    def scan_body(
        statements: list[ast.stmt],
        type_checking_names: set[str],
        typing_module_names: set[str],
    ) -> tuple[set[str], set[str]]:
        type_checking_names = set(type_checking_names)
        typing_module_names = set(typing_module_names)

        def set_state(state: tuple[set[str], set[str]]) -> None:
            type_checking_names.clear()
            type_checking_names.update(state[0])
            typing_module_names.clear()
            typing_module_names.update(state[1])

        def forget(names: set[str]) -> None:
            type_checking_names.difference_update(names)
            typing_module_names.difference_update(names)

        def invalidate(
            state: tuple[set[str], set[str]],
            names: set[str],
        ) -> tuple[set[str], set[str]]:
            invalidated_type_names = set(state[0])
            invalidated_module_names = set(state[1])
            if "*" in names:
                invalidated_type_names.clear()
                invalidated_module_names.clear()
            else:
                invalidated_type_names.difference_update(names)
                invalidated_module_names.difference_update(names)
            return invalidated_type_names, invalidated_module_names

        def merge_paths(
            paths: list[tuple[set[str], set[str]]],
            *,
            include_entry: bool,
        ) -> None:
            if include_entry:
                paths.insert(0, (set(type_checking_names), set(typing_module_names)))
            set_state(intersect_states(paths))

        for node in statements:
            forget(_header_bindings(node))

            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                forget({node.name})
                continue

            if isinstance(node, ast.ClassDef):
                scan_body(node.body, type_checking_names, typing_module_names)
                forget(_class_outer_mutations(node.body) | {node.name})
                continue

            if isinstance(node, ast.Import):
                found.update((alias.name.split(".", maxsplit=1)[0], node.lineno) for alias in node.names)
                for alias in node.names:
                    bound = alias.asname or alias.name.split(".", maxsplit=1)[0]
                    forget({bound})
                    if alias.name == "typing":
                        typing_module_names.add(bound)
                continue

            if isinstance(node, ast.ImportFrom):
                # level > 0 is a relative import: intra-directory by definition.
                if node.level == 0 and node.module:
                    found.add((node.module.split(".", maxsplit=1)[0], node.lineno))
                for alias in node.names:
                    if alias.name == "*":
                        type_checking_names.clear()
                        typing_module_names.clear()
                        continue
                    bound = alias.asname or alias.name
                    forget({bound})
                    if node.level == 0 and node.module == "typing" and alias.name == "TYPE_CHECKING":
                        type_checking_names.add(bound)
                continue

            if isinstance(node, ast.If):
                if _is_type_checking_guard(node, type_checking_names, typing_module_names):
                    set_state(scan_body(node.orelse, type_checking_names, typing_module_names))
                else:
                    merge_paths(
                        [
                            scan_body(node.body, type_checking_names, typing_module_names),
                            scan_body(node.orelse, type_checking_names, typing_module_names),
                        ],
                        include_entry=False,
                    )
                continue

            if isinstance(node, ast.Try | ast.TryStar):
                entry = (set(type_checking_names), set(typing_module_names))
                body_state = scan_body(node.body, *entry)
                else_state = scan_body(node.orelse, *body_state)

                body_exception_state = invalidate(entry, _potential_bindings(node.body))
                continuing_paths = [else_state]
                exceptional_paths = [
                    body_exception_state,
                    invalidate(body_state, _potential_bindings(node.orelse)),
                ]
                if isinstance(node, ast.TryStar):
                    handler_state = body_exception_state
                    for handler in node.handlers:
                        path_type_names, path_module_names = handler_state
                        path_type_names = set(path_type_names)
                        path_module_names = set(path_module_names)
                        if handler.name:
                            path_type_names.discard(handler.name)
                            path_module_names.discard(handler.name)
                        handler_entry = (path_type_names, path_module_names)
                        handler_result = scan_body(handler.body, *handler_entry)
                        handler_exception_state = invalidate(handler_entry, _potential_bindings(handler.body))
                        exceptional_paths.append(handler_exception_state)
                        handler_state = intersect_states([handler_state, handler_result, handler_exception_state])
                    continuing_paths.append(handler_state)
                else:
                    for handler in node.handlers:
                        path_type_names, path_module_names = body_exception_state
                        path_type_names = set(path_type_names)
                        path_module_names = set(path_module_names)
                        if handler.name:
                            path_type_names.discard(handler.name)
                            path_module_names.discard(handler.name)
                        handler_entry = (path_type_names, path_module_names)
                        continuing_paths.append(scan_body(handler.body, *handler_entry))
                        exceptional_paths.append(invalidate(handler_entry, _potential_bindings(handler.body)))

                before_finally = intersect_states(continuing_paths)
                final_state = scan_body(node.finalbody, *before_finally)
                for exceptional_state in exceptional_paths:
                    scan_body(node.finalbody, *exceptional_state)
                set_state(final_state)
                continue

            if isinstance(node, ast.Match):
                case_state = (set(type_checking_names), set(typing_module_names))
                paths = []
                for case in node.cases:
                    bound = _binding_names(case.pattern)
                    if case.guard is not None:
                        bound.update(_binding_names(case.guard))
                    case_entry = invalidate(case_state, bound)
                    paths.append(scan_body(case.body, *case_entry))
                    case_state = invalidate(case_state, bound)
                paths.append(case_state)
                set_state(intersect_states(paths))
                continue

            if isinstance(node, ast.For | ast.AsyncFor | ast.While):
                entry = (set(type_checking_names), set(typing_module_names))
                loop_type_names, loop_module_names = entry
                if isinstance(node, ast.For | ast.AsyncFor):
                    bound = _binding_names(node.target)
                    loop_type_names.difference_update(bound)
                    loop_module_names.difference_update(bound)

                potential = _potential_bindings(node.body)
                while True:
                    body_state = scan_body(node.body, loop_type_names, loop_module_names)
                    abrupt_state = invalidate((loop_type_names, loop_module_names), potential)
                    next_state = intersect_states(
                        [
                            (loop_type_names, loop_module_names),
                            body_state,
                            abrupt_state,
                        ]
                    )
                    if next_state == (loop_type_names, loop_module_names):
                        break
                    loop_type_names, loop_module_names = next_state

                else_state = scan_body(node.orelse, loop_type_names, loop_module_names)
                merge_paths([body_state, abrupt_state, else_state], include_entry=True)
                continue

            if isinstance(node, ast.With | ast.AsyncWith):
                entry = (set(type_checking_names), set(typing_module_names))
                with_type_names, with_module_names = entry
                bound = set().union(
                    *(_binding_names(item.optional_vars) for item in node.items if item.optional_vars is not None)
                )
                with_type_names.difference_update(bound)
                with_module_names.difference_update(bound)
                body_state = scan_body(node.body, with_type_names, with_module_names)
                potential = _potential_bindings(node.body)
                if "*" in potential:
                    set_state((set(), set()))
                else:
                    safe_type_names, safe_module_names = entry
                    safe_type_names.difference_update(potential)
                    safe_module_names.difference_update(potential)
                    set_state(intersect_states([(safe_type_names, safe_module_names), body_state]))
                continue

            if isinstance(node, ast.Assign):
                forget(set().union(*(_binding_names(target) for target in node.targets)))
                continue
            if isinstance(node, ast.AnnAssign | ast.AugAssign):
                forget(_binding_names(node.target))
                continue
            if isinstance(node, ast.Delete):
                forget(set().union(*(_binding_names(target) for target in node.targets)))
                continue

            nested = _statement_lists(node)
            if nested:
                merge_paths(
                    [scan_body(statements, type_checking_names, typing_module_names) for statements in nested],
                    include_entry=True,
                )

        return type_checking_names, typing_module_names

    scan_body(body, set(), set())
    return sorted(found, key=lambda item: (item[1], item[0]))


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
    workspace = _workspace_module_map()

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
            # First-party wins: the tree answers this without an install, so a
            # workspace module resolves the same whichever interpreter we run in.
            if module in workspace:
                providers = {_normalize(workspace[module])}
            else:
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
