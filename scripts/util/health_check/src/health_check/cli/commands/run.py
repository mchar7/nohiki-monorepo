"""``health-check run`` command: execute checks and display results."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Sequence
from dataclasses import replace
from typing import Annotated

import typer
from rich.console import Console

from health_check.cli.display import (
    display_json,
    display_suite_results,
    display_suite_results_boring,
    make_live_callback,
    make_progress_bar,
)
from health_check.cli.formatting import OutputMode, detect_output_mode
from health_check.core.base import HealthCheck
from health_check.core.exceptions import DependencyCycleError, HealthCheckError
from health_check.core.models import CheckCategory, CheckSuiteResult
from health_check.core.registry import CheckRegistry
from health_check.core.runner import CheckRunner
from health_check.platform.factory import get_platform
from health_check.platform.models import PlatformTarget
from health_check.platform.protocol import Platform

_EXIT_PASS: int = 0
_EXIT_FAIL: int = 1
_EXIT_ERROR: int = 2
type RepairEnabled = bool


def _resolve_platform_target(target: str) -> PlatformTarget | None:
    """Resolve the CLI --target string to a PlatformTarget enum value.

    Args:
        target: CLI target string -- ``"compose"``, ``"k8s"``, or ``"auto"``.

    Returns:
        Resolved ``PlatformTarget``, or ``None`` for auto-detection.
    """
    match target.lower():
        case "compose":
            return PlatformTarget.COMPOSE
        case "k8s" | "kubernetes":
            return PlatformTarget.KUBERNETES
        case _:
            return None


def _resolve_categories(
    categories: list[str] | None,
) -> frozenset[CheckCategory] | None:
    """Parse and validate category strings into a frozenset.

    Args:
        categories: Raw category strings from CLI, or None.

    Returns:
        Frozenset of resolved categories, or None if no filter requested.

    Raises:
        ValueError: If any category string is not a valid CheckCategory value.
    """
    if not categories:
        return None
    return frozenset(CheckCategory(c) for c in categories)


def _init_run(
    target: str,
    categories: list[str] | None,
    check_ids: list[str] | None,
    excluded_ids: list[str] | None,
) -> tuple[Platform, list[HealthCheck], tuple[str, ...]]:
    """Initialise the platform and resolve the filtered check list.

    Deliberately does not handle ``typer.Exit`` -- the caller is responsible for
    catching exceptions and mapping them to exit codes.

    Args:
        target: CLI target string.
        categories: Optional category filter strings.
        check_ids: Optional allowlist of check IDs.
        excluded_ids: Optional denylist of check IDs.

    Returns:
        Tuple of (resolved platform, filtered check list, unexercised capability IDs).

    Raises:
        ValueError: If any category string is invalid.
        RuntimeError: If platform detection fails.
    """
    platform = get_platform(_resolve_platform_target(target))
    registry = CheckRegistry()
    registry.discover()
    requested_ids = frozenset(check_ids) if check_ids else None
    unexercised_ids: tuple[str, ...] = ()
    if (
        platform.target is PlatformTarget.KUBERNETES
        and categories is None
        and requested_ids is None
        and not excluded_ids
    ):
        checks = registry.get_k3s_checks()
        unexercised_ids = tuple(sorted(registry.inventory().inapplicable_ids))
    else:
        checks = registry.get_checks(
            platform=platform.target,
            categories=_resolve_categories(categories),
            check_ids=requested_ids,
            excluded_ids=frozenset(excluded_ids) if excluded_ids else frozenset(),
        )
    return platform, checks, unexercised_ids


def _validate_repair_request(
    _repair: RepairEnabled,
    repair_check_ids: list[str] | None,
    checks: Sequence[HealthCheck],
) -> frozenset[str]:
    """Validate the double opt-in against the exact scheduled repairable checks."""
    requested = frozenset(repair_check_ids or ())
    if _repair != bool(requested):
        message = "--repair and at least one --repair-check must be supplied together"
        raise ValueError(message)
    if not requested:
        return frozenset()
    supported = {check.metadata.check_id for check in checks if check.supports_fix and check.metadata.platforms}
    rejected = sorted(requested - supported)
    if rejected:
        message = f"Unsupported or unscheduled repair check ID(s): {', '.join(rejected)}"
        raise ValueError(message)
    return requested


async def _run_suite(
    checks: Sequence[HealthCheck],
    platform: Platform,
    console: Console,
    *,
    show_progress: bool,
    repair_check_ids: frozenset[str] = frozenset(),
    unexercised_ids: tuple[str, ...] = (),
) -> CheckSuiteResult:
    """Execute the check suite, optionally with a live progress bar.

    Progress is suppressed automatically in boring/non-interactive mode.

    Args:
        checks: Checks to execute.
        platform: Target deployment platform.
        console: Rich console for progress output.
        show_progress: If True, display an animated progress bar.
        repair_check_ids: Explicitly selected checks eligible for repair.
        unexercised_ids: Designed target capabilities omitted from execution.

    Returns:
        Completed ``CheckSuiteResult``.
    """
    if show_progress:
        progress = make_progress_bar(console)
        with progress:
            task_id = progress.add_task("Running health checks...", total=len(checks))
            runner = CheckRunner(
                checks,
                platform,
                on_check_complete=make_live_callback(progress, task_id),
                repair_check_ids=repair_check_ids,
            )
            suite = await runner.run()
    else:
        suite = await CheckRunner(checks, platform, repair_check_ids=repair_check_ids).run()
    return replace(suite, unexercised_ids=unexercised_ids)


def _resolve_output_mode(output_mode: OutputMode | None) -> OutputMode:
    """Resolve the effective output mode, auto-detecting when not specified.

    Args:
        output_mode: Explicitly requested mode, or ``None`` for auto-detection.

    Returns:
        The resolved ``OutputMode``.
    """
    return output_mode if output_mode is not None else detect_output_mode()


def run_command(
    target: Annotated[
        str,
        typer.Option("-t", "--target", help="Deployment target: compose, k8s, auto"),
    ] = "auto",
    categories: Annotated[
        list[str] | None,
        typer.Option("-c", "--category", help="Filter by category (repeatable)"),
    ] = None,
    check_ids: Annotated[
        list[str] | None,
        typer.Option("--check", help="Run only these check IDs (repeatable)"),
    ] = None,
    excluded_ids: Annotated[
        list[str] | None,
        typer.Option("--exclude", help="Exclude check IDs (repeatable)"),
    ] = None,
    verbose: Annotated[
        bool,
        typer.Option("-v", "--verbose", help="Show all check detail lines"),
    ] = False,
    quiet: Annotated[
        bool,
        typer.Option("-q", "--quiet", help="Minimal output, rely on exit code only"),
    ] = False,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Emit JSON output for CI/scripting"),
    ] = False,
    no_progress: Annotated[
        bool,
        typer.Option("--no-progress", help="Disable animated progress bar"),
    ] = False,
    output_mode: Annotated[
        OutputMode | None,
        typer.Option(
            "--output-mode",
            help="Output rendering mode: rich (default, pretty TUI) or boring (plain, CI-friendly).",
        ),
    ] = None,
    repair: Annotated[
        bool,
        typer.Option("--repair", help="Enable explicitly allowlisted safe remediation"),
    ] = False,
    repair_check_ids: Annotated[
        list[str] | None,
        typer.Option(
            "--repair-check",
            help="Allow remediation for this scheduled check ID (repeatable; requires --repair)",
        ),
    ] = None,
) -> None:
    """Execute health checks against the target deployment.

    Exit codes: 0=all passed, 1=check failures, 2=runner error.
    """
    mode = _resolve_output_mode(output_mode)
    console = Console(stderr=quiet)

    try:
        platform, checks, unexercised_ids = _init_run(target, categories, check_ids, excluded_ids)
    except (ValueError, HealthCheckError) as exc:
        _emit_error(f"Initialisation error: {exc}", mode, console)
        raise typer.Exit(_EXIT_ERROR) from exc

    try:
        validated_repairs = _validate_repair_request(repair, repair_check_ids, checks)
    except ValueError as exc:
        _emit_error(f"Initialisation error: {exc}", mode, console)
        raise typer.Exit(_EXIT_ERROR) from exc

    if not checks and not unexercised_ids:
        _emit_warning("No checks matched the given filters.", mode, console)
        raise typer.Exit(_EXIT_PASS)

    try:
        suite = asyncio.run(
            _run_suite(
                checks,
                platform,
                console,
                show_progress=not no_progress and not quiet and mode == OutputMode.RICH,
                repair_check_ids=validated_repairs,
                unexercised_ids=unexercised_ids,
            )
        )
    except (DependencyCycleError, HealthCheckError) as exc:
        _emit_error(f"Runner error: {exc}", mode, console)
        raise typer.Exit(_EXIT_ERROR) from exc

    if as_json:
        display_json(suite, Console())
    elif not quiet:
        match mode:
            case OutputMode.RICH:
                display_suite_results(suite, console, verbose=verbose)
            case OutputMode.BORING:
                display_suite_results_boring(suite, verbose=verbose)

    sys.exit(_EXIT_PASS if suite.passed else _EXIT_FAIL)


def _emit_error(message: str, mode: OutputMode, console: Console) -> None:
    """Emit an error message appropriate for the current output mode.

    Args:
        message: Error text to display.
        mode: Current output mode.
        console: Rich console (used only in RICH mode).
    """
    match mode:
        case OutputMode.RICH:
            console.print(f"[red]{message}[/red]")
        case OutputMode.BORING:
            Console(no_color=True, markup=False).print(f"ERROR: {message}")


def _emit_warning(message: str, mode: OutputMode, console: Console) -> None:
    """Emit a warning message appropriate for the current output mode.

    Args:
        message: Warning text to display.
        mode: Current output mode.
        console: Rich console (used only in RICH mode).
    """
    match mode:
        case OutputMode.RICH:
            console.print(f"[yellow]{message}[/yellow]")
        case OutputMode.BORING:
            Console(no_color=True, markup=False).print(f"WARNING: {message}")
