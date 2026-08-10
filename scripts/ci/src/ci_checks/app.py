"""CI checks Typer hub.

Entry point for the ci-checks CLI. Each subcommand delegates to its
dedicated check module for scan logic and result rendering.

Commands:
    ci-checks build-backend -- Canonical uv_build build-system enforcement
    ci-checks deadcode      -- Skylos dead code detection
    ci-checks deptry        -- Dependency hygiene (deptry)
    ci-checks fixtures      -- Unused pytest fixture detection
    ci-checks tests         -- Parallel test runner (sub-commands: affected, all)
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

import typer

from ci_checks.checks import build_backend as _build_backend
from ci_checks.checks import deadcode as _deadcode
from ci_checks.checks import deptry as _deptry
from ci_checks.checks import fixtures as _fixtures
from ci_checks.checks import freshness as _freshness
from ci_checks.checks import gate as _gate
from ci_checks.checks import migration_truth as _migration_truth
from ci_checks.checks import reporting as _reporting
from ci_checks.checks import workflow as _workflow
from ci_checks.checks.tests import tests_app
from ci_checks.core.display import console
from ci_checks.core.packages import Package, Scope, load_packages
from ci_checks.core.scanner import scan_parallel

app = typer.Typer(
    name="ci-checks",
    help="CI/CD hygiene checks with parallel execution and live TUI.",
    no_args_is_help=True,
)

# Tests has two sub-commands (affected, all) so it registers as a nested app.
app.add_typer(tests_app, name="tests")

# Change gate: maps a git diff to the minimal sound set of CI lanes.
app.command("gate")(_gate.gate_cmd)
app.command("gate-evidence")(_gate.gate_evidence_cmd)
app.command("gate-reuse")(_gate.gate_reuse_cmd)

# GitHub Checks workflow summary, verdict and accounting adapters.
app.command("workflow-guard")(_workflow.guard_cmd)
app.command("workflow-summary")(_workflow.summary_cmd)
app.command("workflow-verdict")(_workflow.verdict_cmd)
app.command("workflow-accounting")(_workflow.accounting_cmd)

# Durable lint and scheduled deprecation diagnostic surfaces.
app.command("lint-report")(_reporting.lint_report_cmd)
app.command("actionlint-report")(_reporting.actionlint_report_cmd)
app.command("deprecation-sweep")(_reporting.deprecation_sweep_cmd)


def _filter_packages(
    available: list[Package],
    selection: str,
    known: set[str],
) -> list[Package]:
    if selection == "ALL":
        return available
    requested = {name.strip() for name in selection.split(",") if name.strip()}
    if not requested:
        return []
    if unknown := requested - known:
        console.print(f"[red]Unknown packages: {', '.join(sorted(unknown))}[/red]")
        raise typer.Exit(2)
    return [package for package in available if package.name in requested]


# Image freshness: probes pinned base-image digests against their registries.

app.command("image-freshness")(_freshness.freshness_cmd)


@app.command("deadcode")
def deadcode_cmd(
    scope: Annotated[Scope, typer.Option("--scope", "-s", help="Package scope")] = Scope.ALL,
    packages: Annotated[
        str,
        typer.Option("--packages", help="CSV package names within scope; empty selects none"),
    ] = "ALL",
    confidence: Annotated[
        int,
        typer.Option("--confidence", "-c", min=0, max=100, help="Min Skylos confidence (0-100)"),
    ] = 80,
    ci: Annotated[bool, typer.Option("--ci", help="CI mode (plain-text output)")] = False,
    fail: Annotated[bool, typer.Option("--fail", help="Exit non-zero if findings found")] = False,
    llm: Annotated[bool, typer.Option("--llm", help="Enable hybrid LLM verification")] = False,
    llm_model: Annotated[str, typer.Option("--llm-model", help="LLM model for hybrid analysis")] = "gpt-5.6-luna",
    ollama_host: Annotated[
        str | None,
        typer.Option("--ollama-host", help="Ollama base URL (e.g., http://localhost:11434)"),
    ] = None,
    verify: Annotated[bool, typer.Option("--verify", help="Enable Skylos neuro-symbolic verification")] = False,
    trace: Annotated[
        bool,
        typer.Option("--trace", help="Run tests with call tracing for dynamic dispatch"),
    ] = False,
    gate: Annotated[bool, typer.Option("--gate", help="Enable Skylos quality gate mode")] = False,
    strict: Annotated[bool, typer.Option("--strict", help="Strict gate mode (fail on any issue)")] = False,
    baseline: Annotated[bool, typer.Option("--baseline", help="Only report findings not in baseline")] = False,
    provenance: Annotated[bool, typer.Option("--provenance", help="Include provenance metadata")] = False,
    no_provenance: Annotated[
        bool,
        typer.Option("--no-provenance", help="Disable automatic provenance detection"),
    ] = False,
    provenance_base: Annotated[
        str | None,
        typer.Option("--provenance-base", help="Base ref for provenance detection"),
    ] = None,
    diff: Annotated[
        str | None,
        typer.Option(
            "--diff",
            help="Line-level diff mode (use 'auto' for auto-detected base or pass explicit ref)",
        ),
    ] = None,
    diff_base: Annotated[
        str | None,
        typer.Option("--diff-base", help="File-level diff mode base ref (e.g., origin/main)"),
    ] = None,
    github: Annotated[bool, typer.Option("--github", help="Emit GitHub Actions annotations")] = False,
    summary: Annotated[
        Path | None,
        typer.Option("--summary", help="Append markdown to $GITHUB_STEP_SUMMARY"),
    ] = None,
    github_output: Annotated[
        Path | None,
        typer.Option("--github-output", envvar="GITHUB_OUTPUT", help="$GITHUB_OUTPUT file"),
    ] = None,
    severity: Annotated[
        _deadcode.SeverityLevel | None,
        typer.Option("--severity", help="Minimum severity filter: critical|high|medium|low"),
    ] = None,
    file_filter: Annotated[
        str | None,
        typer.Option("--file-filter", help="Only show findings in matching files"),
    ] = None,
    limit: Annotated[int | None, typer.Option("--limit", help="Max findings displayed per category")] = None,
    no_grep_verify: Annotated[
        bool,
        typer.Option("--no-grep-verify", help="Disable Skylos grep verification pass"),
    ] = False,
    include_tests: Annotated[
        bool,
        typer.Option(
            "--include-tests/--no-include-tests",
            help="Report dead code found in tests",
        ),
    ] = True,
    include_parameters: Annotated[
        bool,
        typer.Option(
            "--include-parameters/--no-include-parameters",
            help="Include unused-parameter findings (high-noise for framework callback signatures)",
        ),
    ] = False,
) -> None:
    """Scan workspace packages for dead code using Skylos."""
    available = load_packages(scope, require_src=True)
    known = {package.name for package in load_packages(Scope.ALL)}
    selected = _filter_packages(available, packages, known)
    if not selected:
        console.print("[yellow]No packages with src/ selected[/yellow]")
        return

    mode = "hybrid (LLM-augmented)" if llm else "static"
    diff_mode = f", diff={diff}" if diff else ""
    diff_base_mode = f", diff-base={diff_base}" if diff_base else ""
    console.print(
        f"[bold]Scanning {len(selected)} packages for dead code "
        f"({mode}, confidence={confidence}%{diff_mode}{diff_base_mode})...[/bold]"
    )

    options = _deadcode.DeadCodeScanOptions(
        confidence=confidence,
        llm=llm,
        llm_model=llm_model,
        api_base=ollama_host,
        verify=verify,
        trace=trace,
        gate=gate,
        strict=strict,
        baseline=baseline,
        provenance=provenance,
        no_provenance=no_provenance,
        provenance_base=provenance_base,
        diff=diff,
        diff_base=diff_base,
        github=github,
        summary=summary,
        severity=severity,
        file_filter=file_filter,
        limit=limit,
        no_grep_verify=no_grep_verify,
        include_tests=include_tests,
        include_parameters=include_parameters,
    )

    results = asyncio.run(_deadcode.scan_scope(selected, options))
    _deadcode.write_static_result_output(results, github_output)

    if ci:
        for result in results:
            status = "PASS" if result.passed else "FAIL"
            suffix = f" ({len(result.findings)} findings)" if result.findings else ""
            console.print(f"[{status}] {result.name}{suffix}")

    if not _deadcode.render_results(results, fail_on_findings=fail):
        raise typer.Exit(1)


# deptry


@app.command("deptry")
def deptry_cmd(
    scope: Annotated[Scope, typer.Option("--scope", "-s", help="Package scope")] = Scope.ALL,
    workers: Annotated[int, typer.Option("--workers", "-w", help="Max parallel workers")] = 4,
    ci: Annotated[bool, typer.Option("--ci", help="CI mode (plain-text output)")] = False,
    packages: Annotated[
        str,
        typer.Option("--packages", help="CSV package names within scope; empty selects none"),
    ] = "ALL",
) -> None:
    """Check selected workspace packages for dependency issues using deptry."""
    available = load_packages(scope, require_src=True)
    known = {package.name for package in load_packages(Scope.ALL)}
    selected = _filter_packages(available, packages, known)
    if not selected:
        console.print("[yellow]No packages with src/ selected[/yellow]")
        return

    console.print(f"[bold]Checking {len(selected)} packages for dependency issues...[/bold]")

    results = asyncio.run(
        scan_parallel(
            selected,
            _deptry.scan_package,
            workers,
            console,
            ci_mode=ci,
            ci_suffix=_deptry.ci_suffix,
        )
    )

    if not _deptry.render_results(results):
        raise typer.Exit(1)


# fixtures


@app.command("fixtures")
def fixtures_cmd(
    scope: Annotated[Scope, typer.Option("--scope", "-s", help="Package scope")] = Scope.ALL,
    workers: Annotated[int, typer.Option("--workers", "-w", help="Max parallel workers")] = 4,
    ci: Annotated[bool, typer.Option("--ci", help="CI mode (plain-text output)")] = False,
    fail: Annotated[bool, typer.Option("--fail", help="Exit non-zero if unused fixtures found")] = False,
) -> None:
    """Detect unused pytest fixtures across workspace packages."""
    packages = load_packages(scope, require_tests=True)
    if not packages:
        console.print("[yellow]No packages with tests/ found[/yellow]")
        return

    console.print(f"[bold]Scanning {len(packages)} packages for unused fixtures...[/bold]")

    results = asyncio.run(
        scan_parallel(
            packages,
            _fixtures.scan_package,
            workers,
            console,
            ci_mode=ci,
            ci_suffix=_fixtures.ci_suffix,
        )
    )

    if not _fixtures.render_results(results, fail_on_unused=fail):
        raise typer.Exit(1)


# build-backend


@app.command("build-backend")
def build_backend_cmd(
    scope: Annotated[Scope, typer.Option("--scope", "-s", help="Package scope")] = Scope.ALL,
    ci: Annotated[bool, typer.Option("--ci", help="CI mode (plain-text output)")] = False,
    strict: Annotated[
        bool,
        typer.Option(
            "--strict",
            help="Also fail on packages not yet migrated to uv_build (post-rollout gate)",
        ),
    ] = False,
    packages: Annotated[
        str,
        typer.Option("--packages", help="CSV package names within scope; empty selects none"),
    ] = "ALL",
) -> None:
    """Validate selected workspace packages use the canonical uv_build stanza."""
    available = load_packages(scope)
    known = {package.name for package in load_packages(Scope.ALL)}
    selected = _filter_packages(available, packages, known)
    if not selected:
        console.print("[yellow]No workspace packages selected[/yellow]")
        return

    console.print(f"[bold]Checking {len(selected)} packages for canonical build-system stanza...[/bold]")

    results = [_build_backend.scan_package(package) for package in selected]

    if ci:
        for result in results:
            status = result.status.value.upper()
            console.print(f"[{status}] {result.name}{_build_backend.ci_suffix(result)}")

    if not _build_backend.render_results(results, strict=strict):
        raise typer.Exit(1)


# migration-truth


@app.command("migration-truth")
def migration_truth_cmd(
    repo_root: Annotated[Path, typer.Option("--repo-root", help="Repository root")] = Path(),
    namespace: Annotated[str, typer.Option("--namespace", help="Kubernetes namespace")] = "nohiki",
    emit_live_verifier: Annotated[
        bool,
        typer.Option(
            "--emit-live-verifier",
            help="Also print the exact read-only live verification command",
        ),
    ] = False,
) -> None:
    """Validate and emit canonical Alembic schema-to-head inventory."""
    try:
        inventory = _migration_truth.validate_migration_truth(repo_root)
        typer.echo(_migration_truth.render_inventory(inventory))
        if emit_live_verifier:
            typer.echo(_migration_truth.render_live_verifier(inventory, namespace=namespace))
    except _migration_truth.MigrationTruthError as exc:
        console.print(f"[red]Migration truth validation failed:[/red] {exc}")
        raise typer.Exit(1) from exc
