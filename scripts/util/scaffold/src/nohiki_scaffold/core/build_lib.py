"""Build plan for library packages (minimal / with-testing / namespace variants)."""

from __future__ import annotations

from pathlib import Path

from nohiki_scaffold.core.build import (
    BuildPlan,
    FileWrite,
    TomlEdit,
    _add_ty_root,
    _add_uv_source,
    _add_workspace_member,
)
from nohiki_scaffold.core.models import LibSpec
from nohiki_scaffold.core.naming import module_name as _module_name
from nohiki_scaffold.templates.loader import get_environment

_LIB_SECTION_COMMENT = "# Shared libraries"


def build_lib_plan(spec: LibSpec, *, repo_root: Path) -> BuildPlan:
    """Return a BuildPlan that creates a shared library at `backend/libs/<name>/`.

    Handles all three variants (minimal / with-testing / namespace) via template
    conditionals driven by `LibSpec` flags.
    """
    target_dir = repo_root / "backend" / "libs" / spec.name
    module = spec.module_name or _module_name(spec.name)
    env = get_environment()
    context = {
        "spec": spec,
        "module_name": module,
        "canonical_requires_line": 'requires = ["uv_build>=0.11.7,<0.12"]',
        "canonical_build_backend_line": 'build-backend = "uv_build"',
    }

    # Decide where py.typed lives: namespace packages put it at src/nohiki/,
    # regular packages at src/<module>/.
    py_typed_path = (
        target_dir / "src" / "nohiki" / "py.typed"
        if spec.namespace_package
        else target_dir / "src" / module / "py.typed"
    )

    files: list[FileWrite] = []

    # pyproject.toml
    files.append(
        FileWrite(
            path=target_dir / "pyproject.toml",
            content=env.get_template("lib/pyproject.toml.j2").render(context),
            trigger="lib.core",
        ),
    )
    # README.md
    files.append(
        FileWrite(
            path=target_dir / "README.md",
            content=env.get_template("lib/README.md.j2").render(context),
            trigger="lib.core",
        ),
    )
    # src/<module>/__init__.py (skipped for namespace packages)
    if not spec.namespace_package:
        files.append(
            FileWrite(
                path=target_dir / "src" / module / "__init__.py",
                content=env.get_template("lib/src/__init__.py.j2").render(context),
                trigger="lib.core",
            ),
        )
    # py.typed marker (empty file)
    files.append(
        FileWrite(path=py_typed_path, content="", trigger="lib.core"),
    )
    if spec.ships_exceptions_module:
        files.append(
            FileWrite(
                path=target_dir / "src" / module / "exceptions.py",
                content=env.get_template("lib/src/exceptions.py.j2").render(context),
                trigger="lib.ships_exceptions",
            ),
        )
    if spec.ships_testing_module:
        files.append(
            FileWrite(
                path=target_dir / "src" / module / "testing.py",
                content=env.get_template("lib/src/testing.py.j2").render(context),
                trigger="lib.ships_testing",
            ),
        )
    # tests
    files.append(
        FileWrite(
            path=target_dir / "tests" / "__init__.py",
            content='"""Test suite."""\n',
            trigger="lib.core",
        ),
    )
    files.append(
        FileWrite(
            path=target_dir / "tests" / "test_smoke.py",
            content=env.get_template("lib/tests/test_smoke.py.j2").render(context),
            trigger="lib.core",
        ),
    )

    # Root pyproject edits.
    member_path = f"backend/libs/{spec.name}"
    src_path = f"backend/libs/{spec.name}/src"
    root_edits: tuple[TomlEdit, ...] = (
        _add_workspace_member(member_path, section_comment=_LIB_SECTION_COMMENT),
        _add_uv_source(spec.name),
        _add_ty_root(src_path),
    )

    hints: tuple[str, ...] = (
        f"[dim]Library [bold]{spec.name}[/bold] is now a workspace member.[/dim]",
        (
            "[dim]To depend on it, add [bold]"
            + spec.name
            + "==0.1.0[/bold] to a service's [cyan][project].dependencies[/cyan].[/dim]"
        ),
    )

    return BuildPlan(
        spec=spec,
        files=tuple(files),
        root_edits=root_edits,
        hints=hints,
    )
