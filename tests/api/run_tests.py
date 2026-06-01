#!/usr/bin/env python3
"""E2E test runner with proper setup and cleanup."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Final

import pytest
import typer
from rich.console import Console
from rich.panel import Panel

console = Console(stderr=True)
app = typer.Typer(
    name="run-e2e-tests",
    help="Run Nohiki E2E tests using Docker Compose deployment.",
    no_args_is_help=False,
)


@dataclass(frozen=True, slots=True)
class E2EConfig:
    """E2E test configuration constants."""

    DEFAULT_TIMEOUT: int = 1800
    CLEANUP_TIMEOUT: int = 120
    DOCKER_CHECK_TIMEOUT: int = 10
    SIGINT_EXIT_CODE: int = 130


CONFIG = E2EConfig()

REQUIRED_API_KEYS: Final[tuple[str, ...]] = (
    "OPENAI_API_KEY_E2E",
    "OPENROUTER_API_KEY_E2E",
)


def _setup_e2e_environment() -> None:
    """Set up environment for E2E testing."""
    os.environ["PYTEST_CURRENT_TEST"] = "e2e"

    missing_keys = [key for key in REQUIRED_API_KEYS if not os.getenv(key)]

    if missing_keys:
        console.print("[yellow]⚠️  Missing E2E API keys for full testing:[/yellow]")
        for key in missing_keys:
            console.print(f"   [dim]- {key}[/dim]")
        console.print("\n[dim]To run complete E2E tests with LLM processing:[/dim]")
        console.print("   [cyan]export OPENAI_API_KEY_E2E='your-dedicated-e2e-openai-key'[/cyan]")
        console.print("   [cyan]export OPENROUTER_API_KEY_E2E='your-dedicated-e2e-openrouter-key'[/cyan]")
        console.print("[dim]Continuing with limited E2E testing (no LLM processing)...[/dim]\n")


def _validate_docker_environment() -> bool:
    """Validate that Docker and Docker Compose are available."""
    docker_path = shutil.which("docker")
    if not docker_path:
        console.print("[red]❌ Docker is not installed or not accessible[/red]")
        return False

    try:
        result = subprocess.run(
            [docker_path, "version"],
            capture_output=True,
            text=True,
            timeout=CONFIG.DOCKER_CHECK_TIMEOUT,
            check=False,
        )
        if result.returncode != 0:
            console.print("[red]❌ Docker is not running or not accessible[/red]")
            return False

        result = subprocess.run(
            [docker_path, "compose", "version"],
            capture_output=True,
            text=True,
            timeout=CONFIG.DOCKER_CHECK_TIMEOUT,
            check=False,
        )
        if result.returncode != 0:
            console.print("[red]❌ Docker Compose is not available[/red]")
            return False

        console.print("[green]✅ Docker environment validated[/green]")
    except subprocess.TimeoutExpired, FileNotFoundError:
        console.print("[red]❌ Docker environment check failed[/red]")
        return False

    return True


def _get_compose_dir() -> Path:
    """Get the Docker Compose directory."""
    current_file = Path(__file__)
    project_root = current_file.parent.parent.parent
    return project_root / "infrastructure" / "compose"


def _cleanup_environment() -> None:
    """Clean up Docker environment after tests."""
    compose_dir = _get_compose_dir()
    docker_path = shutil.which("docker")

    if not docker_path:
        console.print("[yellow]⚠️  Docker not found for cleanup[/yellow]")
        return

    cmd = [
        docker_path,
        "compose",
        "-f",
        "docker-compose.test.yml",
        "down",
        "-v",
        "--remove-orphans",
    ]

    console.print("[blue]Cleaning up test environment...[/blue]")
    try:
        subprocess.run(
            cmd,
            cwd=compose_dir,
            timeout=CONFIG.CLEANUP_TIMEOUT,
            check=False,
            text=True,
            capture_output=True,
        )
        console.print("[green]✅ Cleanup completed[/green]")
    except subprocess.TimeoutExpired:
        console.print("[yellow]⚠️  Cleanup timed out[/yellow]")
    except FileNotFoundError:
        console.print("[yellow]⚠️  Docker not found for cleanup[/yellow]")


def _build_pytest_args(
    timeout: int,
    *,
    verbose: bool,
    workflows_only: bool,
) -> list[str]:
    """Build pytest command arguments."""
    pytest_args = [
        "tests/api/",
        "-m",
        "e2e",
        "--asyncio-mode=auto",
        f"--timeout={timeout}",
        "--tb=short",
    ]

    if verbose:
        pytest_args.append("-v")

    if workflows_only:
        pytest_args.extend(["-k", "TestE2EWorkflowsOnly"])
        console.print("[blue]Running workflow-only tests (assuming services are running)[/blue]")
    else:
        pytest_args.extend(["-k", "TestCompleteE2EDeployment"])
        console.print("[blue]Running complete deployment tests[/blue]")

    return pytest_args


def _run_e2e_tests(
    timeout: int,
    *,
    verbose: bool,
    workflows_only: bool,
    keep_deployment: bool,
    no_observability: bool,
) -> int:
    """Run the E2E tests."""
    if keep_deployment:
        os.environ["E2E_KEEP_DEPLOYMENT"] = "true"
        console.print("[dim]Deployment will be kept running after tests[/dim]")

    if no_observability:
        os.environ["E2E_VERIFY_OBSERVABILITY"] = "false"
        console.print("[dim]Skipping observability stack[/dim]")

    console.print(f"[dim]Test timeout: {timeout} seconds[/dim]")
    console.print("[blue]Starting tests...[/blue]\n")

    pytest_args = _build_pytest_args(timeout, verbose=verbose, workflows_only=workflows_only)

    return pytest.main(pytest_args)


def _display_success_info(*, keep_deployment: bool) -> None:
    """Display success information."""
    console.print("\n[green]✅ All E2E tests passed successfully![/green]")

    if keep_deployment:
        info_lines = [
            "[bold]Deployment is still running for debugging:[/bold]",
            "",
            "  • API Gateway (Traefik): http://localhost:8000",
            "  • Traefik Dashboard: http://localhost:8080",
            "  • Grafana: http://localhost:3001 (admin/admin)",
            "  • Prometheus: http://localhost:9090",
            "",
            "[bold]To clean up manually:[/bold]",
            "  sh infra/compose/scripts/preflight.sh down -v",
        ]
        console.print(Panel("\n".join(info_lines), title="[green]Deployment Info[/green]"))


def _display_failure_info(*, verbose: bool) -> None:
    """Display failure information."""
    console.print("\n[red]❌ Some E2E tests failed[/red]")

    if not verbose:
        console.print("[dim]For more details, run with --verbose[/dim]")
        console.print("[dim]Or check deployment logs manually:[/dim]")
        console.print("   sh infra/compose/scripts/preflight.sh logs")


@app.command()
def main(
    *,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Verbose test output."),
    ] = False,
    timeout: Annotated[
        int,
        typer.Option("--timeout", "-t", help="Test timeout in seconds."),
    ] = CONFIG.DEFAULT_TIMEOUT,
    keep_deployment: Annotated[
        bool,
        typer.Option("--keep-deployment", "-k", help="Keep deployment running after tests."),
    ] = False,
    no_observability: Annotated[
        bool,
        typer.Option("--no-observability", help="Skip observability stack deployment."),
    ] = False,
    workflows_only: Annotated[
        bool,
        typer.Option(
            "--workflows-only",
            "-w",
            help="Run workflow tests only (assume services running).",
        ),
    ] = False,
    no_cleanup: Annotated[
        bool,
        typer.Option("--no-cleanup", help="Skip initial cleanup."),
    ] = False,
) -> None:
    """Run Nohiki E2E tests using Docker Compose deployment."""
    console.rule("[bold blue]Nohiki E2E Tests[/bold blue]")

    _setup_e2e_environment()

    if not _validate_docker_environment():
        console.print("[red]Docker environment validation failed[/red]")
        raise typer.Exit(1)

    if not no_cleanup:
        _cleanup_environment()

    try:
        exit_code = _run_e2e_tests(
            timeout,
            verbose=verbose,
            workflows_only=workflows_only,
            keep_deployment=keep_deployment,
            no_observability=no_observability,
        )

        if exit_code == 0:
            _display_success_info(keep_deployment=keep_deployment)
        else:
            _display_failure_info(verbose=verbose)

        final_exit_code = exit_code

    except KeyboardInterrupt:
        console.print("\n[yellow]Tests interrupted by user[/yellow]")

        if not keep_deployment:
            console.print("[blue]Cleaning up deployment...[/blue]")
            _cleanup_environment()

        final_exit_code = CONFIG.SIGINT_EXIT_CODE

    except typer.Exit:
        raise

    except Exception as e:
        _handle_unexpected_error(e, keep_deployment=keep_deployment)

    if final_exit_code != 0:
        raise typer.Exit(final_exit_code)


def _handle_unexpected_error(error: Exception, *, keep_deployment: bool) -> None:
    """Handle unexpected errors during test execution."""
    console.print(f"\n[red]❌ Unexpected error during test execution: {error}[/red]")

    if not keep_deployment:
        console.print("[blue]Cleaning up deployment...[/blue]")
        _cleanup_environment()

    raise typer.Exit(1) from error


if __name__ == "__main__":
    app()
