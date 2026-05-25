"""Implementation of ``nohiki-scaffold new service``."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Annotated

import typer

from nohiki_scaffold.config.paths import get_repo_root
from nohiki_scaffold.core.build import apply_plan, build_plan
from nohiki_scaffold.core.exceptions import ScaffoldError, ValidationError, WorkspaceEditError
from nohiki_scaffold.core.features import VerifyMode
from nohiki_scaffold.core.validators import validate_service_spec

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


def new_service_command(
    name: Annotated[
        str | None,
        typer.Option("--name", help="Service distribution name (kebab-case, e.g. 'skill-tagger-service')."),
    ] = None,
    friendly_name: Annotated[
        str | None,
        typer.Option("--friendly-name", help="Display name for the service."),
    ] = None,
    description: Annotated[
        str | None,
        typer.Option("--description", help="Short description of the service."),
    ] = None,
    owner: Annotated[
        str | None,
        typer.Option("--owner", help="Team/owner string."),
    ] = None,
    shape: Annotated[
        str | None,
        typer.Option("--shape", help="Transport shape: kafka-only, http-only, or http-and-kafka."),
    ] = None,
    env_prefix: Annotated[
        str | None,
        typer.Option("--env-prefix", help="Override derived env prefix."),
    ] = None,
    module_name: Annotated[
        str | None,
        typer.Option("--module-name", help="Override derived module name."),
    ] = None,
    db: Annotated[
        bool,
        typer.Option("--db/--no-db", help="Enable database."),
    ] = False,
    schema_name: Annotated[
        str | None,
        typer.Option("--schema-name", help="Override derived database schema name."),
    ] = None,
    outbox: Annotated[
        bool,
        typer.Option("--outbox", help="Enable transactional outbox."),
    ] = False,
    alembic: Annotated[
        bool,
        typer.Option("--alembic", help="Emit Alembic migrations scaffolding."),
    ] = False,
    redis: Annotated[
        bool,
        typer.Option("--redis/--no-redis", help="Enable Redis cache."),
    ] = False,
    kafka_role: Annotated[
        str | None,
        typer.Option("--kafka-role", help="Kafka role: none, producer-only, consumer-only, or both."),
    ] = None,
    handler: Annotated[
        list[str] | None,
        typer.Option("--handler", help="Repeatable: commands, callbacks, upstream-cdc, feedback, backfill."),
    ] = None,
    embedding_callback: Annotated[
        bool,
        typer.Option("--embedding-callback", help="Register the embedding callback handler."),
    ] = False,
    max_concurrent_handlers: Annotated[
        int | None,
        typer.Option("--max-concurrent-handlers", help="Max concurrent Kafka handlers (1-200)."),
    ] = None,
    s3: Annotated[
        bool,
        typer.Option("--s3/--no-s3", help="Enable S3 integration."),
    ] = False,
    s3_bucket: Annotated[
        str | None,
        typer.Option("--s3-bucket", help="S3 bucket name (required if --s3)."),
    ] = None,
    s3_key_prefix: Annotated[
        str | None,
        typer.Option("--s3-key-prefix", help="S3 key prefix (optional)."),
    ] = None,
    llm: Annotated[
        bool,
        typer.Option("--llm/--no-llm", help="Enable LLM integration."),
    ] = False,
    llm_provider: Annotated[
        str | None,
        typer.Option("--llm-provider", help="LLM provider (e.g. openai, anthropic)."),
    ] = None,
    llm_model: Annotated[
        str | None,
        typer.Option("--llm-model", help="LLM model (e.g. gpt-4o, claude-sonnet)."),
    ] = None,
    llm_api_key_env: Annotated[
        str | None,
        typer.Option("--llm-api-key-env", help="Environment variable for LLM API key."),
    ] = None,
    qdrant: Annotated[
        bool,
        typer.Option("--qdrant/--no-qdrant", help="Enable Qdrant integration."),
    ] = False,
    qdrant_collection_entity: Annotated[
        str | None,
        typer.Option(
            "--qdrant-collection-entity", help="Qdrant collection entity: jobs, profiles, skills, or occupations."
        ),
    ] = None,
    manifest: Annotated[
        bool,
        typer.Option("--manifest/--no-manifest", help="Enable ML manifest integration."),
    ] = False,
    service_holder_pattern: Annotated[
        bool,
        typer.Option("--service-holder-pattern", help="Use _ServiceHolder class for ML-heavy services."),
    ] = False,
    fail_fast_validation: Annotated[
        bool,
        typer.Option("--fail-fast-validation", help="Emit core/validation.py with fail-fast checks."),
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
    """Scaffold a new backend service."""
    try:
        repo_root = get_repo_root()

        if not yes:
            _check_git_dirty(repo_root)

        if config_file:
            try:
                from nohiki_scaffold.core.spec_loader import load_service_spec

                spec = load_service_spec(Path(config_file))
            except ImportError:
                msg = "spec_loader module not available (Phase E parallel workstream pending)"
                typer.echo(f"Error: {msg}", err=True)
                raise typer.Exit(code=_EXIT_APPLY_ERROR) from None
        else:
            try:
                from nohiki_scaffold.cli.prompts import prompt_service_spec

                spec = prompt_service_spec(
                    name=name,
                    friendly_name=friendly_name,
                    description=description,
                    owner=owner,
                    shape=shape,
                    env_prefix=env_prefix,
                    module_name=module_name,
                    db=db,
                    schema_name=schema_name,
                    outbox=outbox,
                    alembic=alembic,
                    redis=redis,
                    kafka_role=kafka_role,
                    handler=handler,
                    embedding_callback=embedding_callback,
                    max_concurrent_handlers=max_concurrent_handlers,
                    s3=s3,
                    s3_bucket=s3_bucket,
                    s3_key_prefix=s3_key_prefix,
                    llm=llm,
                    llm_provider=llm_provider,
                    llm_model=llm_model,
                    llm_api_key_env=llm_api_key_env,
                    qdrant=qdrant,
                    qdrant_collection_entity=qdrant_collection_entity,
                    manifest=manifest,
                    service_holder_pattern=service_holder_pattern,
                    fail_fast_validation=fail_fast_validation,
                    non_interactive=non_interactive,
                )
            except ImportError:
                msg = "prompts module not available (Phase E parallel workstream pending)"
                typer.echo(f"Error: {msg}", err=True)
                raise typer.Exit(code=_EXIT_APPLY_ERROR) from None

        problems = validate_service_spec(spec, repo_root)
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

            console.print(f"[green]✓[/green] Scaffold complete: [bold]backend/services/{spec.name}[/bold]")
        except ImportError, AttributeError:
            typer.echo(f"Scaffold complete: backend/services/{spec.name}")

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
