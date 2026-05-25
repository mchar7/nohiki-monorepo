"""Implementation of ``nohiki-scaffold new lib``."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Annotated

import typer

from nohiki_scaffold.config.paths import get_repo_root
from nohiki_scaffold.core.build import apply_plan, build_plan
from nohiki_scaffold.core.exceptions import ScaffoldError, ValidationError, WorkspaceEditError
from nohiki_scaffold.core.features import VerifyMode
from nohiki_scaffold.core.validators import validate_lib_spec

_EXIT_SUCCESS = 0
_EXIT_VALIDATION = 2
_EXIT_GIT_DIRTY = 3
_EXIT_USER_ABORT = 4
_EXIT_APPLY_ERROR = 5
_EXIT_VERIFY_FAIL = 6


def _check_git_dirty(repo_root: Path) -> None:
    """Raise Exit if repo has uncommitted changes and not --yes."""
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.stdout.strip():
        msg = "[yellow]Warning[/yellow]: Repository has uncommitted changes. Use [bold]--yes[/bold] to proceed anyway."
        try:
            from nohiki_scaffold.cli.display import console

            console.print(msg)
        except ImportError, AttributeError:
            typer.echo(f"WARNING: {msg}")
        raise typer.Exit(code=_EXIT_GIT_DIRTY)


def new_lib_command(
    name: Annotated[
        str | None,
        typer.Option("--name", help="Library distribution name (must start with 'nohiki-')."),
    ] = None,
    description: Annotated[
        str | None,
        typer.Option("--description", help="Short description of the library."),
    ] = None,
    owner: Annotated[
        str | None,
        typer.Option("--owner", help="Team/owner string."),
    ] = None,
    module_name: Annotated[
        str | None,
        typer.Option("--module-name", help="Override derived module name."),
    ] = None,
    namespace_package: Annotated[
        bool,
        typer.Option("--namespace-package", help="Namespace package (PEP 420) under nohiki/."),
    ] = False,
    ships_testing_module: Annotated[
        bool,
        typer.Option("--ships-testing-module", help="Ship testing.py with pytest fixtures."),
    ] = False,
    ships_exceptions_module: Annotated[
        bool,
        typer.Option("--ships-exceptions-module", help="Ship exceptions.py with NohikiError subclass."),
    ] = False,
    config_file: Annotated[
        str | None,
        typer.Option("--config-file", "-c", help="Path to TOML spec file."),
    ] = None,
    non_interactive: Annotated[
        bool,
        typer.Option("--non-interactive", help="Skip prompts; require all required flags."),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip confirmation and git-dirty-guard."),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Preview only, do not apply."),
    ] = False,
    verify_mode: Annotated[
        str,
        typer.Option("--verify-mode", help="Verification depth: default, full, or none."),
    ] = "default",
) -> None:
    """Scaffold a new shared library."""
    try:
        repo_root = get_repo_root()

        if not yes:
            _check_git_dirty(repo_root)

        if config_file:
            try:
                from nohiki_scaffold.core.spec_loader import load_lib_spec

                spec = load_lib_spec(Path(config_file))
            except ImportError:
                msg = "spec_loader module not available (Phase E parallel workstream pending)"
                typer.echo(f"Error: {msg}", err=True)
                raise typer.Exit(code=_EXIT_APPLY_ERROR) from None
        else:
            try:
                from nohiki_scaffold.cli.prompts import prompt_lib_spec

                spec = prompt_lib_spec(
                    name=name,
                    description=description,
                    owner=owner,
                    module_name=module_name,
                    namespace_package=namespace_package,
                    ships_testing_module=ships_testing_module,
                    ships_exceptions_module=ships_exceptions_module,
                    non_interactive=non_interactive,
                )
            except ImportError:
                msg = "prompts module not available (Phase E parallel workstream pending)"
                typer.echo(f"Error: {msg}", err=True)
                raise typer.Exit(code=_EXIT_APPLY_ERROR) from None

        problems = validate_lib_spec(spec, repo_root)
        if problems:
            try:
                from nohiki_scaffold.cli.display import render_validation_errors

                render_validation_errors(problems)
            except ImportError, AttributeError:
                for problem in problems:
                    typer.echo(f"Error: {problem}", err=True)
            raise typer.Exit(code=_EXIT_VALIDATION) from None  # noqa: TRY301

        plan = build_plan(spec, repo_root=repo_root)

        try:
            from nohiki_scaffold.cli.display import (
                render_hints,
                render_plan_files,
                render_root_edits,
                render_spec_panel,
            )

            render_spec_panel(spec)
            render_plan_files(plan, explain=False)
            render_root_edits(plan)
            render_hints(plan)
        except ImportError, AttributeError:
            typer.echo("(display module not available — skipping preview)")

        if dry_run:
            raise typer.Exit(code=_EXIT_SUCCESS) from None  # noqa: TRY301

        if not yes and not non_interactive and not typer.confirm("Proceed?"):
            raise typer.Exit(code=_EXIT_USER_ABORT) from None  # noqa: TRY301

        try:
            apply_plan(plan, repo_root=repo_root, dry_run=False)
        except WorkspaceEditError as exc:
            typer.echo(f"Error applying plan: {exc}", err=True)
            raise typer.Exit(code=_EXIT_APPLY_ERROR) from None

        verify = VerifyMode(verify_mode) if verify_mode else VerifyMode.DEFAULT
        if verify != VerifyMode.NONE:
            try:
                from nohiki_scaffold.verify.runner import run_verify

                run_verify(plan, mode=verify)
            except ModuleNotFoundError:
                try:
                    from nohiki_scaffold.cli.display import console

                    console.print("[yellow]Info[/yellow]: Phase F verification not yet available (skipping)")
                except ImportError, AttributeError:
                    typer.echo("Info: Phase F verification not yet available (skipping)")
            except Exception as exc:  # noqa: BLE001
                typer.echo(f"Verification failed: {exc}", err=True)
                raise typer.Exit(code=_EXIT_VERIFY_FAIL) from None

        try:
            from nohiki_scaffold.cli.display import console

            console.print(f"[green]✓[/green] Scaffold complete: [bold]backend/libs/{spec.name}[/bold]")
        except ImportError, AttributeError:
            typer.echo(f"Scaffold complete: backend/libs/{spec.name}")

    except typer.Exit:
        raise
    except ValidationError as exc:
        typer.echo(f"Validation error: {exc}", err=True)
        raise typer.Exit(code=_EXIT_VALIDATION) from None
    except ScaffoldError as exc:
        typer.echo(f"Scaffold error: {exc}", err=True)
        raise typer.Exit(code=_EXIT_APPLY_ERROR) from None
    except Exception as exc:  # noqa: BLE001  # noqa: BLE001
        typer.echo(f"Unexpected error: {exc}", err=True)
        raise typer.Exit(code=_EXIT_APPLY_ERROR) from None
