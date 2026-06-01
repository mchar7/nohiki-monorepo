#!/usr/bin/env python3
"""Integration test runner for nohiki cross-service tests."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console(stderr=True)
app = typer.Typer(
    name="run-integration-tests",
    help="Run nohiki cross-service integration tests.",
    no_args_is_help=False,
)


@dataclass(frozen=True, slots=True)
class TestConfig:
    """Test configuration constants."""

    TIMEOUT_SECONDS: int = 1800
    COV_FAIL_UNDER: int = 75
    STDERR_LIMIT: int = 1000


CONFIG = TestConfig()

REQUIRED_PACKAGES: tuple[str, ...] = (
    "pytest",
    "pytest_asyncio",
    "testcontainers",
    "redis",
    "httpx",
    "structlog",
)

TEST_ENV_VARS: dict[str, str] = {
    "OTEL_SDK_DISABLED": "true",
    "OTEL_TRACES_EXPORTER": "none",
    "OTEL_METRICS_EXPORTER": "none",
    "OTEL_LOGS_EXPORTER": "none",
    "PYTEST_CURRENT_TEST": "integration",
}


@dataclass
class TestResults:
    """Container for test execution results."""

    success: bool = False
    return_code: int = -1
    duration_seconds: float = 0.0
    stdout: str = ""
    stderr: str = ""
    error: str = ""
    command: str = ""


@dataclass
class IntegrationTestRunner:
    """Runner for cross-service integration tests."""

    test_dir: Path = field(default_factory=lambda: Path(__file__).parent)
    project_root: Path = field(init=False)
    docker_available: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        """Initialize computed fields."""
        self.project_root = self.test_dir.parent

    def _check_docker_availability(self) -> bool:
        """Check if Docker is available and running."""
        docker_path = shutil.which("docker")
        if not docker_path:
            return False

        try:
            result = subprocess.run(
                [docker_path, "info"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except subprocess.TimeoutExpired, FileNotFoundError:
            return False

        return result.returncode == 0

    def _check_python_dependencies(self) -> list[str]:
        """Check Python dependencies and return missing packages."""
        missing: list[str] = []
        for package in REQUIRED_PACKAGES:
            try:
                __import__(package)
            except ImportError:
                missing.append(package)
        return missing

    def check_dependencies(self) -> bool:
        """Check if all required dependencies are available."""
        console.print("[blue]Checking test dependencies...[/blue]")

        self.docker_available = self._check_docker_availability()
        if not self.docker_available:
            console.print("[yellow]⚠️  Docker not available - docker-required tests will be skipped[/yellow]")

        missing_packages = self._check_python_dependencies()
        if missing_packages:
            console.print(f"[red]❌ Missing packages: {', '.join(missing_packages)}[/red]")
            return False

        console.print("[green]✅ All dependencies available[/green]")
        return True

    def setup_test_environment(self) -> None:
        """Set up the test environment."""
        console.print("[blue]Setting up test environment...[/blue]")

        for key, value in TEST_ENV_VARS.items():
            os.environ[key] = value

        console.print("[green]✅ Environment configured[/green]")

    def cleanup_test_environment(self) -> None:
        """Clean up the test environment."""
        for var in TEST_ENV_VARS:
            os.environ.pop(var, None)
        console.print("[dim]Environment cleaned up[/dim]")

    def _build_pytest_command(
        self,
        test_pattern: str | None,
        *,
        verbose: bool,
        coverage: bool,
        parallel: bool,
    ) -> list[str]:
        """Build the pytest command."""
        cmd = ["python", "-m", "pytest"]

        test_path = f"{self.test_dir}/integration/{test_pattern}" if test_pattern else f"{self.test_dir}/integration/"
        cmd.append(test_path)

        marker_expr = "integration" if self.docker_available else "integration and not requires_docker"

        cmd.extend(
            [
                "-v" if verbose else "-q",
                "--tb=short",
                "--strict-markers",
                "-m",
                marker_expr,
                "--asyncio-mode=auto",
            ],
        )

        if coverage:
            cmd.extend(
                [
                    "--cov=backend",
                    "--cov-report=html",
                    "--cov-report=term-missing",
                    f"--cov-fail-under={CONFIG.COV_FAIL_UNDER}",
                ],
            )

        if parallel:
            cmd.extend(["-n", "auto"])

        return cmd

    def run_test_suite(
        self,
        test_pattern: str | None = None,
        *,
        verbose: bool = False,
        coverage: bool = False,
        parallel: bool = False,
    ) -> TestResults:
        """Run the integration test suite."""
        console.print("[blue]Starting integration test suite...[/blue]")

        cmd = self._build_pytest_command(
            test_pattern,
            verbose=verbose,
            coverage=coverage,
            parallel=parallel,
        )
        command_str = " ".join(cmd)
        console.print(f"[dim]Command: {command_str}[/dim]")

        start_time = time.time()

        try:
            result = subprocess.run(
                cmd,
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=CONFIG.TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return TestResults(
                success=False,
                return_code=-1,
                duration_seconds=time.time() - start_time,
                error="Test execution timed out",
                command=command_str,
            )
        except Exception as e:
            return TestResults(
                success=False,
                return_code=-1,
                duration_seconds=time.time() - start_time,
                error=str(e),
                command=command_str,
            )

        return TestResults(
            success=result.returncode == 0,
            return_code=result.returncode,
            duration_seconds=time.time() - start_time,
            stdout=result.stdout,
            stderr=result.stderr,
            command=command_str,
        )

    def display_results(self, results: TestResults) -> None:
        """Display test results using rich."""
        status = "[green]PASSED[/green]" if results.success else "[red]FAILED[/red]"

        table = Table(title="Integration Test Results", show_header=True, header_style="bold")
        table.add_column("Metric", style="cyan")
        table.add_column("Value")

        table.add_row("Status", status)
        table.add_row("Duration", f"{results.duration_seconds:.2f}s")
        table.add_row("Return Code", str(results.return_code))
        table.add_row("Command", f"[dim]{results.command}[/dim]")

        console.print(table)

        if results.stdout:
            console.print(Panel(results.stdout, title="[bold]STDOUT[/bold]", expand=False))

        if results.stderr:
            stderr_display = results.stderr[: CONFIG.STDERR_LIMIT]
            if len(results.stderr) > CONFIG.STDERR_LIMIT:
                stderr_display += "\n... (truncated)"
            console.print(Panel(stderr_display, title="[bold red]STDERR[/bold red]", expand=False))

        if results.error:
            console.print(Panel(results.error, title="[bold red]ERROR[/bold red]", expand=False))

    def save_report(self, results: TestResults, report_file: Path) -> None:
        """Save test report to file."""
        report_lines = [
            "=" * 80,
            "NOHIKI INTEGRATION TEST REPORT",
            "=" * 80,
            "",
            f"Test Status: {'PASSED' if results.success else 'FAILED'}",
            f"Duration: {results.duration_seconds:.2f} seconds",
            f"Return Code: {results.return_code}",
            f"Command: {results.command}",
            "",
        ]

        if results.stdout:
            report_lines.extend(["STDOUT:", "-" * 40, results.stdout, ""])

        if results.stderr:
            report_lines.extend(["STDERR:", "-" * 40, results.stderr, ""])

        if results.error:
            report_lines.extend(["ERROR:", "-" * 40, results.error, ""])

        report_lines.extend(["=" * 80, ""])

        report_file.write_text("\n".join(report_lines))
        console.print(f"[green]Report written to: {report_file}[/green]")

    def run(
        self,
        test_pattern: str | None = None,
        *,
        verbose: bool = False,
        coverage: bool = False,
        parallel: bool = False,
        report_file: Path | None = None,
    ) -> bool:
        """Run the complete integration test workflow."""
        try:
            if not self.check_dependencies():
                console.print("[red]❌ Dependency check failed[/red]")
                return False

            self.setup_test_environment()

            results = self.run_test_suite(
                test_pattern=test_pattern,
                verbose=verbose,
                coverage=coverage,
                parallel=parallel,
            )

            self.display_results(results)

            if report_file:
                self.save_report(results, report_file)
        except Exception as e:
            console.print(f"[red]❌ Integration test run failed: {e}[/red]")
            return False
        else:
            return results.success
        finally:
            self.cleanup_test_environment()


@app.command()
def main(
    test_pattern: Annotated[
        str | None,
        typer.Option("--test-pattern", "-t", help="Specific test pattern to run."),
    ] = None,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable verbose output."),
    ] = False,
    coverage: Annotated[
        bool,
        typer.Option("--coverage", "-c", help="Enable coverage reporting."),
    ] = False,
    parallel: Annotated[
        bool,
        typer.Option("--parallel", "-p", help="Run tests in parallel."),
    ] = False,
    report_file: Annotated[
        Path | None,
        typer.Option("--report-file", "-r", help="Write test report to file."),
    ] = None,
    test_dir: Annotated[
        Path | None,
        typer.Option("--test-dir", "-d", help="Test directory path."),
    ] = None,
) -> None:
    """Run nohiki cross-service integration tests."""
    console.rule("[bold blue]Nohiki Integration Tests[/bold blue]")

    runner_test_dir = test_dir or Path(__file__).parent
    runner = IntegrationTestRunner(test_dir=runner_test_dir)

    success = runner.run(
        test_pattern=test_pattern,
        verbose=verbose,
        coverage=coverage,
        parallel=parallel,
        report_file=report_file,
    )

    if success:
        console.rule("[bold green]All tests passed![/bold green]")
    else:
        console.rule("[bold red]Tests failed![/bold red]")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
