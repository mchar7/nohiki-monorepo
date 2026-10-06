"""Every Python test module must have a package test root or a recipe lane."""

import ast
import fnmatch
import json
import os
import subprocess
from functools import cache
from pathlib import Path

import pytest
import yaml
from ci_checks.core.packages import REPO_ROOT, Scope, load_packages_with_deps

_ROOTS = ("tests", "scripts", "backend", "infra")

_STANDALONE_TREES: dict[str, str] = {
    "scripts/load/tests": "load-check-tests",
    "scripts/proto_gen/tests": "proto-gen-test",
}


def _declares_tests(path: Path) -> bool:
    """Return whether the module declares a test function, so a helper is not a test suite."""
    module = ast.parse(path.read_text(encoding="utf-8"))
    return any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test")
        for node in ast.walk(module)
    )


def _test_modules() -> tuple[str, ...]:
    return tuple(
        sorted(
            path.relative_to(REPO_ROOT).as_posix()
            for root in _ROOTS
            for path in (REPO_ROOT / root).rglob("test_*.py")
            if _declares_tests(path)
        )
    )


@cache
def _package_test_roots() -> tuple[str, ...]:
    packages = load_packages_with_deps(Scope.ALL)
    return tuple(
        sorted(
            {
                path.relative_to(REPO_ROOT).as_posix()
                for package in packages.values()
                for path in package.test_paths
                if path.is_dir()
            }
        )
    )


def _modules_outside_package_roots() -> tuple[str, ...]:
    roots = _package_test_roots()
    return tuple(module for module in _test_modules() if not any(module.startswith(f"{root}/") for root in roots))


@cache
def _recipe_body(recipe: str) -> str:
    environment = {key: value for key, value in os.environ.items() if key not in {"VIRTUAL_ENV", "PROJECT_ROOT"}}
    dumped = subprocess.run(
        ["just", "--dump", "--dump-format", "json"],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )
    recipes = json.loads(dumped.stdout)["recipes"]
    assert recipe in recipes, f"the justfile declares no recipe {recipe!r}"
    return json.dumps(recipes[recipe])


def test_every_test_module_is_executed_by_a_lane() -> None:
    """A module no package collects needs a named recipe lane in _STANDALONE_TREES."""
    uncovered = [
        module
        for module in _modules_outside_package_roots()
        if not any(module.startswith(f"{tree}/") for tree in _STANDALONE_TREES)
    ]
    assert not uncovered, (
        "test modules no lane executes; give each one a package test root, or a recipe lane in _STANDALONE_TREES:\n"
        + "\n".join(f"  {module}" for module in uncovered)
    )


def test_standalone_trees_are_exactly_the_uncovered_modules() -> None:
    """A stale entry fails here: a tree that gains a package or loses its tests must leave."""
    leftovers = _modules_outside_package_roots()
    recorded = {module for module in leftovers if any(module.startswith(f"{tree}/") for tree in _STANDALONE_TREES)}
    unrecorded = sorted(set(leftovers) - recorded)
    assert not unrecorded, "uncovered modules with no standalone entry:\n" + "\n".join(f"  {m}" for m in unrecorded)

    for tree in sorted(_STANDALONE_TREES):
        assert any(module.startswith(f"{tree}/") for module in recorded), (
            f"{tree} is recorded as standalone but holds no uncovered test module"
        )


@pytest.mark.parametrize(("tree", "recipe"), sorted(_STANDALONE_TREES.items()))
def test_standalone_trees_keep_a_recipe_lane(tree: str, recipe: str) -> None:
    """The recipe owns the tree: it must still run it, and the tree must still exist."""
    assert (REPO_ROOT / tree).is_dir(), f"{tree} is gone; drop the entry and its recipe"
    assert tree in _recipe_body(recipe), f"just {recipe} no longer runs {tree}"


@pytest.mark.parametrize(
    "path",
    [
        "proto/example.proto",
        "proto/nested/example.proto",
        "scripts/proto_gen/main.py",
        "scripts/proto_gen/tests/test_cli.py",
    ],
)
def test_proto_generator_tests_reach_the_push_lane(path: str) -> None:
    hooks = yaml.safe_load((REPO_ROOT / "lefthook.yml").read_text(encoding="utf-8"))
    jobs = hooks["pre-push"]["jobs"]
    generator = next((job for job in jobs if job.get("run") == "just proto-gen-test"), None)
    assert generator is not None, "the push gate does not run the proto generator tests"
    assert any(fnmatch.fnmatch(path, pattern) for pattern in generator["glob"]), f"the push gate skips {path}"


@pytest.mark.parametrize(
    "relative",
    ["backend/libs/nohiki-geo-utils/src/nohiki_geo_utils/test_orphan_probe.py", "infra/unowned/test_orphan_probe.py"],
)
def test_census_rejects_source_tree_orphans(relative: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = tmp_path / relative
    module.parent.mkdir(parents=True)
    module.write_text("def test_orphan_probe():\n    assert False\n", encoding="utf-8")
    monkeypatch.setattr(f"{__name__}.REPO_ROOT", tmp_path)
    monkeypatch.setattr(f"{__name__}._package_test_roots", lambda: ())
    with pytest.raises(AssertionError, match=relative):
        test_every_test_module_is_executed_by_a_lane()
