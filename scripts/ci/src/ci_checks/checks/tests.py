"""Intelligent test runner with parallel execution and live TUI.

Runs each workspace package's pytest suite in its own process, with
change-based selection (``affected``), coverage gating, and CI-friendly
plain output.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import re
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Annotated, ClassVar

import typer
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    ProgressColumn,
    SpinnerColumn,
    Task,
    TaskID,
    TextColumn,
)

from ci_checks.core.packages import (
    REPO_ROOT,
    Package,
    PackageType,
    Scope,
)
from ci_checks.core.process_env import sanitized_python_env

# Constants

PYTEST_SUCCESS = 0
PYTEST_NO_TESTS = 5
_WHOLE_PACKAGE_PROCESS_WATCHDOG_SECONDS: int = 30 * 60
_UNIT_TEST_MARKERS = "not integration and not e2e and not requires_docker"


# Git change detection


class GitMode(StrEnum):
    """Git change detection mode."""

    STAGED = "staged"
    PUSH = "push"


def get_changed_files(mode: GitMode) -> set[Path]:
    """Get changed files based on git mode.

    Args:
        mode: Whether to diff staged changes or changes vs. origin.

    Returns:
        Set of changed file paths relative to repo root. Deletions are
        included: removing a module can break dependents.

    Raises:
        RuntimeError: If git cannot resolve the diff. Callers must treat
            this as "run everything", never as "nothing changed".
    """
    if mode == GitMode.STAGED:
        cmd = ["git", "diff", "--cached", "--name-only"]
    else:
        branch_result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            check=False,
        )
        if branch_result.returncode != 0:
            msg = f"git rev-parse HEAD failed: {branch_result.stderr.strip()}"
            raise RuntimeError(msg)
        branch = branch_result.stdout.strip()

        base = ""
        for candidate in (f"origin/{branch}", "origin/main"):
            base_result = subprocess.run(
                ["git", "rev-parse", candidate],
                capture_output=True,
                text=True,
                cwd=REPO_ROOT,
                check=False,
            )
            if base_result.returncode == 0:
                base = base_result.stdout.strip()
                break
        if not base:
            msg = "no usable diff base: neither origin/<branch> nor origin/main resolves"
            raise RuntimeError(msg)
        # Three-dot: diff against the merge base, so upstream drift on the
        # base branch never counts as a local change.
        cmd = ["git", "diff", "--name-only", "--no-renames", f"{base}...HEAD"]

    result = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO_ROOT, check=False)
    if result.returncode != 0:
        msg = f"git diff failed: {result.stderr.strip()}"
        raise RuntimeError(msg)
    return {REPO_ROOT / f for f in result.stdout.strip().split("\n") if f}


# Coverage model


@dataclass(slots=True)
class FileCoverage:
    """Coverage data for a single source file."""

    path: str
    stmts: int
    miss: int
    cover: float


@dataclass(slots=True)
class CoverageResult:
    """Aggregate coverage data for a package."""

    total_coverage: float = 0.0
    files: list[FileCoverage] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class CoverageGate:
    """Minimum coverage thresholds for a package category."""

    file_threshold: float
    module_threshold: float
    name: str

    def check_file(self, coverage: FileCoverage) -> bool:
        """Return True if the file meets the per-file threshold."""
        return coverage.cover >= self.file_threshold

    def check_module(self, coverage: CoverageResult) -> bool:
        """Return True if the module meets the aggregate threshold."""
        return coverage.total_coverage >= self.module_threshold

    def get_failing_files(self, coverage: CoverageResult) -> list[FileCoverage]:
        """Return files that fall below the per-file threshold."""
        return [f for f in coverage.files if not self.check_file(f)]


GATE_REGISTRY: dict[str, CoverageGate] = {
    "strict": CoverageGate(file_threshold=80.0, module_threshold=90.0, name="strict"),
    "no-requirements": CoverageGate(file_threshold=0.0, module_threshold=0.0, name="no-requirements"),
    "relaxed": CoverageGate(file_threshold=70.0, module_threshold=80.0, name="relaxed"),
    "critical": CoverageGate(file_threshold=90.0, module_threshold=95.0, name="critical"),
}

_PACKAGE_TYPE_GATE_MAP: dict[PackageType, str] = {
    PackageType.SERVICE: "strict",
    PackageType.LIB: "strict",
    PackageType.JOB: "strict",
    PackageType.SCRIPTS: "no-requirements",
    PackageType.OTHER: "no-requirements",
}


def get_coverage_gate(pkg_type: PackageType) -> CoverageGate:
    """Look up the appropriate coverage gate for a package type.

    Args:
        pkg_type: The package category.

    Returns:
        CoverageGate instance; defaults to 'strict' if unmapped.
    """
    gate_name = _PACKAGE_TYPE_GATE_MAP.get(pkg_type, "strict")
    return GATE_REGISTRY.get(gate_name, GATE_REGISTRY["strict"])


# Test result model


@dataclass(slots=True)
class TestResult:
    """Test execution result for a single package."""

    name: str
    passed: bool
    duration_ms: int = 0
    output: str = ""
    tests_run: int = 0
    tests_failed: int = 0
    coverage: CoverageResult = field(default_factory=CoverageResult)
    pkg_type: PackageType = PackageType.OTHER


# Coverage parsing

_COVERAGE_LINE_PATTERN = re.compile(
    r"^([\w/.%+\x2d]+\.py)\s+(\d+)\s+(\d+)\s+(\d+)%",
    re.MULTILINE,
)
_TOTAL_COVERAGE_PATTERN = re.compile(r"^TOTAL\s+\d+\s+\d+\s+(\d+)%", re.MULTILINE)


def _parse_coverage_output(output: str) -> CoverageResult:
    """Parse pytest-cov coverage report text into a CoverageResult.

    Args:
        output: Combined stdout+stderr from the pytest run.

    Returns:
        Parsed CoverageResult (empty if no coverage data found).
    """
    result = CoverageResult()
    for match in _COVERAGE_LINE_PATTERN.finditer(output):
        path, stmts, miss, cover = match.groups()
        result.files.append(FileCoverage(path=path, stmts=int(stmts), miss=int(miss), cover=float(cover)))
    if total_match := _TOTAL_COVERAGE_PATTERN.search(output):
        result.total_coverage = float(total_match.group(1))
    return result


def _get_src_dir(pkg: Package) -> str:
    """Resolve the src/ subdirectory name for coverage collection.

    Args:
        pkg: The workspace package.

    Returns:
        Relative path like 'src/my_service' or 'src' as fallback.
    """
    src_dir = pkg.path / "src"
    if src_dir.is_dir():
        subdirs = sorted(
            [d for d in src_dir.iterdir() if d.is_dir() and (d / "__init__.py").exists()],
            key=lambda d: d.name,
        )
        if subdirs:
            return f"src/{subdirs[0].name}"
    return "src"


# Custom Rich progress columns


class PerTaskTimeColumn(ProgressColumn):
    """Elapsed time per task (uses custom start_time field, not Rich's global)."""

    def __init__(self) -> None:
        """Initialise with no extra state."""
        super().__init__()

    def render(self, task: Task) -> str:
        """Render elapsed time since the task started."""
        custom_start = task.fields.get("start_time")
        if custom_start is None:
            return "--:--"
        elapsed = time.time() - custom_start
        minutes, seconds = divmod(int(elapsed), 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes}:{seconds:02d}"


class ModuleProgressColumn(ProgressColumn):
    """Current/total test count column."""

    def __init__(self) -> None:
        """Initialise with no extra state."""
        super().__init__()

    def render(self, task: Task) -> str:
        """Render 'current/total' test count, or '?/?' when unknown."""
        current = task.fields.get("tests_current", 0)
        total = task.fields.get("tests_total", 0)
        return "?/?" if total == 0 else f"{current}/{total}"


class PendingCoverageColumn(ProgressColumn):
    """Animated coverage column -- spinner while waiting, percentage when done."""

    SPINNER_FRAMES: ClassVar[list[str]] = [
        "⠋",
        "⠙",
        "⠹",
        "⠸",
        "⠼",
        "⠴",
        "⠦",
        "⠧",
        "⠇",
        "⠏",
    ]

    def __init__(self) -> None:
        """Initialise spinner frame index."""
        super().__init__()
        self.frame_index = 0

    def render(self, task: Task) -> str:
        """Render coverage or a spinner if not yet available."""
        coverage = task.fields.get("coverage")
        if coverage == "off":
            return "[dim]  off[/dim]"
        if coverage and coverage != "--":
            return f"[cyan]{coverage:>5}[/cyan]"
        self.frame_index = (self.frame_index + 1) % len(self.SPINNER_FRAMES)
        return f"[dim]{self.SPINNER_FRAMES[self.frame_index]} wait[/dim]"


# Test execution


def _sync_workspace(console: Console) -> None:
    """Synchronize the frozen workspace environment before parallel test execution."""
    result = subprocess.run(
        ["uv", "sync", "--all-packages", "--frozen"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
        env=sanitized_python_env(),
    )
    if result.returncode == 0:
        return

    console.print("[red bold]Failed to synchronize workspace packages; tests were not started.[/red bold]")
    if stdout := result.stdout.strip():
        console.print(stdout)
    if stderr := result.stderr.strip():
        console.print(stderr)
    raise typer.Exit(result.returncode or 1)


def _order_packages_for_dispatch(packages: list[Package]) -> list[Package]:
    """Put the historically dominant ci-checks suite first, preserving all other order."""
    return [pkg for pkg in packages if pkg.name == "ci-checks"] + [pkg for pkg in packages if pkg.name != "ci-checks"]


def _parse_test_progress(line: str) -> int:
    """Count completed test markers in a pytest output line.

    Args:
        line: Single line of pytest verbose output.

    Returns:
        Number of PASSED/FAILED/ERROR/SKIPPED/XFAIL/XPASS tokens found.
    """
    return len(re.findall(r"\b(PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)\b", line))


async def run_package_tests(
    pkg: Package,
    markers: str,
    extra_args: tuple[str, ...],
    *,
    with_coverage: bool = True,
    progress_callback: Callable[[int], None] | None = None,
) -> TestResult:
    """Run pytest for a single package asynchronously.

    Args:
        pkg: Package to test.
        markers: pytest -m expression to filter tests.
        extra_args: Additional pytest arguments.
        with_coverage: Whether to enable pytest-cov reporting.
        progress_callback: Optional callback receiving running test count updates.

    Returns:
        TestResult with timing, output, and optional coverage data.
    """
    if not pkg.has_tests:
        return TestResult(
            name=pkg.name,
            passed=True,
            output="No tests directory",
            pkg_type=pkg.pkg_type,
        )

    cmd = [
        "uv",
        "run",
        "--no-sync",
        "--package",
        pkg.name,
        "pytest",
        str(pkg.path / "tests"),
        "--tb=short",
        "-v",
    ]
    if with_coverage:
        src_dir = _get_src_dir(pkg)
        cmd.extend([f"--cov={src_dir}", "--cov-report=term-missing", "--cov-fail-under=0"])
    if markers:
        cmd.extend(["-m", markers])
    cmd.extend(extra_args)

    module_start_time = time.time()
    tests_completed = 0

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=pkg.path,
        env=sanitized_python_env(),
    )

    if proc.stdout is None or proc.stderr is None:
        if proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
        await proc.wait()
        missing_stream = "stdout" if proc.stdout is None else "stderr"
        return TestResult(
            name=pkg.name,
            passed=False,
            duration_ms=int((time.time() - module_start_time) * 1000),
            output=f"Failed to capture {missing_stream}",
            pkg_type=pkg.pkg_type,
        )

    stdout_chunks: list[bytes] = []
    stderr_chunks: list[bytes] = []

    async def drain_stdout() -> None:
        nonlocal tests_completed
        pending = bytearray()
        while chunk := await proc.stdout.read(65536):
            stdout_chunks.append(chunk)
            pending.extend(chunk)
            while (newline := pending.find(b"\n")) >= 0:
                line = bytes(pending[: newline + 1])
                del pending[: newline + 1]
                tests_completed += _parse_test_progress(line.decode())
                if progress_callback:
                    progress_callback(tests_completed)
        if pending:
            tests_completed += _parse_test_progress(bytes(pending).decode())
            if progress_callback:
                progress_callback(tests_completed)

    async def drain_stderr() -> None:
        while chunk := await proc.stderr.read(65536):
            stderr_chunks.append(chunk)

    timeout_error: TimeoutError | None = None

    async def wait_for_process() -> None:
        nonlocal timeout_error
        try:
            await asyncio.wait_for(proc.wait(), timeout=_WHOLE_PACKAGE_PROCESS_WATCHDOG_SECONDS)
        except TimeoutError as exc:
            if proc.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    proc.kill()
            await proc.wait()
            timeout_error = exc
        except BaseException:
            if proc.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    proc.kill()
            await proc.wait()
            raise

    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(drain_stdout())
            tg.create_task(drain_stderr())
            tg.create_task(wait_for_process())
    except BaseException:
        if proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
        await proc.wait()
        raise

    if timeout_error is not None:
        raise timeout_error

    duration_ms = int((time.time() - module_start_time) * 1000)
    pytest_passed = proc.returncode in (PYTEST_SUCCESS, PYTEST_NO_TESTS)
    stdout = b"".join(stdout_chunks).decode()
    stderr = b"".join(stderr_chunks).decode()
    output = stdout + stderr
    passed = pytest_passed
    coverage = _parse_coverage_output(output) if with_coverage else CoverageResult()

    return TestResult(
        name=pkg.name,
        passed=passed,
        duration_ms=duration_ms,
        output=output,
        coverage=coverage,
        pkg_type=pkg.pkg_type,
    )


# Parallel execution modes


async def _run_tests_ci_mode(
    packages: list[Package],
    markers: str,
    extra_args: tuple[str, ...],
    max_workers: int,
    console: Console,
    *,
    with_coverage: bool,
) -> list[TestResult]:
    """Run tests in CI mode with a simple tabular output.

    Uses asyncio.TaskGroup so unhandled exceptions surface immediately
    rather than being silently returned as BaseException values.

    Args:
        packages: Packages to test.
        markers: pytest -m expression.
        extra_args: Additional pytest arguments.
        max_workers: Maximum concurrent test processes.
        console: Rich console for output.
        with_coverage: Whether to collect coverage data.

    Returns:
        List of TestResult in input order.
    """
    semaphore = asyncio.Semaphore(max_workers)
    cov_header = "  Cov% " if with_coverage else ""
    console.print(f"\n{'Module':<40}  Tests   Time    Status{cov_header}")
    console.print("-" * 70)

    results: list[TestResult | None] = [None] * len(packages)
    pkg_index = {pkg.name: i for i, pkg in enumerate(packages)}

    async def run(pkg: Package) -> None:
        async with semaphore:
            result = await run_package_tests(pkg, markers, extra_args, with_coverage=with_coverage)
        icon = "✓ PASS" if result.passed else "✗ FAIL"
        cov_info = f"  {result.coverage.total_coverage:>3.0f}%" if with_coverage else ""
        tests_run = 0
        if match := re.search(r"(\d+) passed", result.output):
            tests_run = int(match.group(1))
        console.print(f"{result.name:<40}  {tests_run:>5}   {result.duration_ms // 1000:>3}s   {icon}{cov_info}")
        results[pkg_index[pkg.name]] = result

    async with asyncio.TaskGroup() as tg:
        for pkg in _order_packages_for_dispatch(packages):
            tg.create_task(run(pkg))

    return [r for r in results if r is not None]


def _update_progress_on_completion(
    progress: Progress,
    task_id: TaskID,
    result: TestResult,
    name: str,
    *,
    with_coverage: bool,
    force_total: int | None = None,
) -> None:
    """Update a progress bar row when a package's tests complete.

    Args:
        progress: Rich Progress instance.
        task_id: The task row to update.
        result: Completed test result.
        name: Package name for display.
        with_coverage: Whether to show coverage percentage.
        force_total: Override total if inventory never arrived.
    """
    cov_str = f"{result.coverage.total_coverage:.0f}%" if with_coverage else "--"
    status_style = "green" if result.passed else "red"
    status_icon = "✓" if result.passed else "✗"
    tests_total = force_total if force_total is not None else progress.tasks[task_id].fields.get("tests_total", 0)
    progress.update(
        task_id,
        description=f"[{status_style}]{status_icon} {name}",
        completed=tests_total,
        tests_current=tests_total,
        coverage=cov_str,
    )


async def _run_tests_interactive(
    packages: list[Package],
    markers: str,
    extra_args: tuple[str, ...],
    max_workers: int,
    console: Console,
    *,
    with_coverage: bool,
) -> list[TestResult]:
    """Run tests with an interactive Rich TUI progress display.

    Each package gets one pytest process; progress is derived from that process's
    verbose result stream rather than a separate collection run.

    Args:
        packages: Packages to test.
        markers: pytest -m expression.
        extra_args: Additional pytest arguments.
        max_workers: Maximum concurrent test processes.
        console: Rich console for output.
        with_coverage: Whether to collect coverage data.

    Returns:
        List of TestResult in input order.
    """
    progress = Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description:<40}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        ModuleProgressColumn(),
        PerTaskTimeColumn(),
        PendingCoverageColumn(),
        console=console,
        expand=True,
    )

    async def run_with_progress(pkg: Package) -> TestResult:
        task_id = progress.add_task(
            f"[cyan]{pkg.name}",
            total=None,
            completed=0,
            tests_current=0,
            tests_total=0,
            coverage="--" if with_coverage else "off",
            start_time=time.time(),
        )
        progress.update(task_id, description=f"[yellow]⏳ {pkg.name}")
        tests_completed_count = 0

        async with semaphore:
            progress.update(task_id, description=f"[blue]🔄 {pkg.name}")

            def progress_callback(completed: int) -> None:
                nonlocal tests_completed_count
                tests_completed_count = completed
                progress.update(task_id, tests_current=completed, completed=completed)

            result = await run_package_tests(
                pkg,
                markers,
                extra_args,
                with_coverage=with_coverage,
                progress_callback=progress_callback,
            )
            final_total = max(tests_completed_count, 1)
            progress.update(task_id, total=final_total, tests_total=final_total)
            _update_progress_on_completion(
                progress,
                task_id,
                result,
                pkg.name,
                with_coverage=with_coverage,
                force_total=final_total,
            )
            return result

    with Live(progress, console=console, refresh_per_second=10):
        semaphore = asyncio.Semaphore(max_workers)
        async with asyncio.TaskGroup() as tg:
            test_tasks = {
                pkg.name: tg.create_task(run_with_progress(pkg)) for pkg in _order_packages_for_dispatch(packages)
            }

    return [test_tasks[pkg.name].result() for pkg in packages]


async def run_tests_parallel(
    packages: list[Package],
    markers: str,
    extra_args: tuple[str, ...],
    max_workers: int,
    console: Console,
    *,
    ci_mode: bool,
    with_coverage: bool = True,
) -> list[TestResult]:
    """Dispatch to CI or interactive parallel test execution.

    Args:
        packages: Packages to test.
        markers: pytest -m expression.
        extra_args: Additional pytest arguments.
        max_workers: Maximum concurrent test processes.
        console: Rich console for output.
        ci_mode: Use plain-text CI output when True.
        with_coverage: Whether to collect coverage data.

    Returns:
        List of TestResult.
    """
    _sync_workspace(console)
    available_workers = os.process_cpu_count() or 1
    pytest_workers = max(1, available_workers // max(1, max_workers))
    bounded_args = ("-n", str(pytest_workers), *extra_args)
    if ci_mode:
        return await _run_tests_ci_mode(
            packages,
            markers,
            bounded_args,
            max_workers,
            console,
            with_coverage=with_coverage,
        )
    return await _run_tests_interactive(
        packages,
        markers,
        bounded_args,
        max_workers,
        console,
        with_coverage=with_coverage,
    )


# Display helpers


def _coverage_color(pct: float, threshold: float) -> str:
    """Map a coverage percentage to a Rich colour name."""
    if pct >= threshold:
        return "green"
    if pct >= threshold - 10:
        return "yellow"
    return "red"


@dataclass(frozen=True, slots=True)
class _CoverageRowData:
    """Computed display data for a single coverage table row."""

    name: str
    mod_pct: str
    files_str: str
    status: str


def _coverage_meets_policy(result: TestResult) -> bool:
    """Return whether a result satisfies its package-type coverage policy."""
    gate = get_coverage_gate(result.pkg_type)
    return not gate.get_failing_files(result.coverage) and gate.check_module(result.coverage)


def _create_coverage_row(result: TestResult) -> _CoverageRowData:
    """Build coverage table row data for a single result."""
    cov = result.coverage
    gate = get_coverage_gate(result.pkg_type)

    mod_color = _coverage_color(cov.total_coverage, gate.module_threshold)
    mod_pct = f"[{mod_color}]{cov.total_coverage:.0f}%[/{mod_color}]"

    failing_files = gate.get_failing_files(cov)
    files_below = len(failing_files)
    files_color = "green" if files_below == 0 else "red"
    files_str = f"[{files_color}]{files_below}[/{files_color}]"
    status = "[green]✓[/green]" if _coverage_meets_policy(result) else "[red]✗[/red]"

    return _CoverageRowData(name=result.name, mod_pct=mod_pct, files_str=files_str, status=status)


def display_coverage_summary(results: list[TestResult], console: Console) -> None:
    """Display a per-package coverage summary table with failing-file details.

    Args:
        results: All test results to summarise.
        console: Rich console for output.
    """
    from rich.table import Table  # local import to avoid polluting module-level imports

    table = Table(
        title="Coverage Summary (per-package policy)",
        show_header=True,
        header_style="bold",
    )
    table.add_column("Package", style="cyan")
    table.add_column("Module %", justify="right")
    table.add_column("Files Below Policy", justify="right")
    table.add_column("Status", justify="center")

    for result in sorted(results, key=lambda r: r.name):
        row = _create_coverage_row(result)
        table.add_row(row.name, row.mod_pct, row.files_str, row.status)

    console.print()
    console.print(table)

    for result in results:
        gate = get_coverage_gate(result.pkg_type)
        failing_files = gate.get_failing_files(result.coverage)
        if failing_files:
            console.print(f"\n[yellow]Files below {gate.file_threshold:.0f}% in {result.name}:[/yellow]")
            for file in failing_files:
                console.print(f"  {file.path}: {file.cover:.0f}%")


def display_summary(
    results: list[TestResult],
    console: Console,
    *,
    ci_mode: bool,
    with_coverage: bool = True,
) -> None:
    """Display overall test and coverage summary.

    Args:
        results: All test results.
        console: Rich console for output.
        ci_mode: Whether to use plain-text CI format.
        with_coverage: Whether to show coverage summary.
    """
    from rich.table import Table

    passed = sum(1 for r in results if r.passed)
    failed = len(results) - passed

    coverage_ok = all(_coverage_meets_policy(result) for result in results)

    if ci_mode:
        console.print(f"\n{'=' * 70}")
        console.print(f"TESTS: {passed} passed, {failed} failed")
        if with_coverage:
            cov_status = "[green]OK[/green]" if coverage_ok else "[red]BELOW THRESHOLD[/red]"
            console.print(f"COVERAGE: {cov_status}")
        console.print(f"{'=' * 70}")
    else:
        table = Table(title="Test Summary", show_header=True, header_style="bold")
        table.add_column("Metric", style="bold")
        table.add_column("Value", justify="right")
        table.add_row("[green]Tests Passed[/green]", str(passed))
        table.add_row("[red]Tests Failed[/red]", str(failed))
        console.print()
        console.print(table)

    if with_coverage:
        display_coverage_summary(results, console)


def render_github_summary(results: list[TestResult], title: str) -> str:
    """Render one test batch as a GitHub-flavored Markdown summary.

    Args:
        results: Package test results in the batch.
        title: Batch name displayed in the heading.

    Returns:
        Markdown containing the batch totals and per-package results.
    """
    passed = sum(result.passed for result in results)
    lines = [
        f"## Python tests ({title})",
        "",
        f"**{passed}/{len(results)} packages passed.**",
        "",
        "| Package | Duration | Coverage | Status |",
        "| --- | ---: | ---: | :---: |",
    ]
    for result in sorted(results, key=lambda item: item.name):
        status = "Pass" if result.passed else "Fail"
        lines.append(
            f"| `{result.name}` | {result.duration_ms / 1000:.1f}s | {result.coverage.total_coverage:.0f}% | {status} |"
        )
    return "\n".join(lines) + "\n"


def display_failures(results: list[TestResult], console: Console, *, ci_mode: bool) -> None:
    """Display failed test output panels.

    Args:
        results: All test results.
        console: Rich console for output.
        ci_mode: Whether to use plain-text CI format.
    """
    failed = [r for r in results if not r.passed]
    if not failed:
        return
    console.print()
    for result in failed:
        if ci_mode:
            console.print(f"\n{'=' * 60}\nFAILED: {result.name}\n{'=' * 60}")
            console.print(result.output)
        else:
            console.print(
                Panel(
                    result.output,
                    title=f"[red bold]✗ {result.name}[/red bold]",
                    border_style="red",
                )
            )


# CLI sub-commands

tests_app = typer.Typer(
    name="tests",
    help="Run tests in parallel with coverage and live TUI.",
    no_args_is_help=True,
)


def _load_testable_packages(scope_str: str) -> list[Package]:
    """Load workspace packages filtered by scope and presence of a tests/ dir."""
    from ci_checks.core.packages import load_packages_with_deps

    scope = Scope(scope_str) if scope_str in Scope.__members__.values() else Scope.ALL
    packages = load_packages_with_deps(scope)
    return [p for p in packages.values() if p.has_tests]


def _build_markers(*, integration: bool) -> str:
    """Build the pytest -m expression for the given flags."""
    return "integration" if integration else _UNIT_TEST_MARKERS


def _check_exit_conditions(
    results: list[TestResult],
    *,
    strict: bool,
    with_coverage: bool,
) -> bool:
    """Return True if the run should exit non-zero.

    Args:
        results: All test results.
        strict: Whether coverage gating is enforced.
        with_coverage: Whether coverage was collected.

    Returns:
        True if tests failed or coverage is below threshold in strict mode.
    """
    has_failures = any(not r.passed for r in results)
    coverage_failed = strict and with_coverage and any(not _coverage_meets_policy(result) for result in results)
    return has_failures or coverage_failed


@tests_app.command("affected")
def affected_cmd(
    mode: Annotated[GitMode, typer.Option("--mode", "-m", help="Git change detection mode")] = GitMode.STAGED,
    integration: Annotated[bool, typer.Option("--integration", "-i", help="Run integration tests")] = False,
    workers: Annotated[int, typer.Option("--workers", "-w", help="Max parallel workers")] = 4,
    ci: Annotated[bool, typer.Option("--ci", help="CI mode (simple output)")] = False,
    coverage: Annotated[bool, typer.Option("--coverage/--no-coverage", help="Enable coverage")] = True,
    strict: Annotated[bool, typer.Option("--strict", help="Fail if coverage below threshold")] = False,
) -> None:
    """Run tests for packages affected by git changes (fail-closed).

    Uses the change-gate engine: a git failure or a file no gating rule
    understands falls back to the full suite, never to a silent skip.
    """
    from ci_checks.core.change_gate import evaluate
    from ci_checks.core.packages import load_packages_with_deps

    console = Console()
    packages = load_packages_with_deps(Scope.ALL)
    try:
        files = get_changed_files(mode)
    except RuntimeError as exc:
        console.print(f"[yellow]{exc}[/yellow]")
        console.print("[yellow]Fail-closed: running the full suite[/yellow]")
        testable = [package for package in packages.values() if package.has_tests]
    else:
        if not files:
            console.print("[green]No files changed[/green]")
            return
        rel_paths = {file.relative_to(REPO_ROOT).as_posix() for file in files}
        decision = evaluate(rel_paths, packages)
        if decision.full:
            console.print("[yellow]Fail-closed: running the full suite[/yellow]")
            for reason in decision.reasons:
                console.print(f"  - {reason}")
            testable = [package for package in packages.values() if package.has_tests]
        else:
            testable = [packages[name] for name in sorted(decision.affected) if packages[name].has_tests]
    if not testable:
        console.print("[green]No testable packages affected[/green]")
        return

    console.print(f"[bold]Running tests for {len(testable)} affected packages...[/bold]")
    markers = _build_markers(integration=integration)
    results = asyncio.run(
        run_tests_parallel(testable, markers, (), workers, console, ci_mode=ci, with_coverage=coverage)
    )

    display_summary(results, console, ci_mode=ci, with_coverage=coverage)
    display_failures(results, console, ci_mode=ci)

    if _check_exit_conditions(results, strict=strict, with_coverage=coverage):
        raise typer.Exit(1)


@tests_app.command("all")
def all_packages_cmd(
    scope: Annotated[
        str,
        typer.Option("--scope", "-s", help="Filter: all, services, libs, jobs, scripts, other"),
    ] = "all",
    integration: Annotated[bool, typer.Option("--integration", "-i", help="Run integration tests")] = False,
    workers: Annotated[int, typer.Option("--workers", "-w", help="Max parallel workers")] = 4,
    ci: Annotated[bool, typer.Option("--ci", help="CI mode (simple output)")] = False,
    coverage: Annotated[bool, typer.Option("--coverage/--no-coverage", help="Enable coverage")] = True,
    strict: Annotated[bool, typer.Option("--strict", help="Fail if coverage below threshold")] = False,
    packages: Annotated[
        str,
        typer.Option(
            "--packages",
            help="CSV of package names to run within scope; 'ALL' or empty runs the whole scope",
        ),
    ] = "ALL",
    summary: Annotated[Path | None, typer.Option("--summary", help="$GITHUB_STEP_SUMMARY file")] = None,
    summary_title: Annotated[str, typer.Option("--summary-title", help="Batch name for the summary")] = "all",
) -> None:
    """Run tests for all workspace packages with coverage reporting."""
    console = Console()
    testable = _load_testable_packages(scope)

    if packages not in ("", "ALL"):
        requested = {name.strip() for name in packages.split(",") if name.strip()}
        known = {package.name for package in testable}
        if unknown := requested - known:
            # A gate/runner mismatch must fail loudly, never shrink silently.
            console.print(f"[red]Unknown packages for scope {scope!r}: {', '.join(sorted(unknown))}[/red]")
            raise typer.Exit(2)
        testable = [package for package in testable if package.name in requested]

    if not testable:
        console.print("[yellow]No testable packages found[/yellow]")
        return

    console.print(f"[bold]Running tests for {len(testable)} packages with coverage...[/bold]")
    markers = _build_markers(integration=integration)
    results = asyncio.run(
        run_tests_parallel(testable, markers, (), workers, console, ci_mode=ci, with_coverage=coverage)
    )

    display_summary(results, console, ci_mode=ci, with_coverage=coverage)
    display_failures(results, console, ci_mode=ci)
    if summary is not None:
        with summary.open("a", encoding="utf-8") as summary_file:
            summary_file.write(render_github_summary(results, summary_title))

    if _check_exit_conditions(results, strict=strict, with_coverage=coverage):
        raise typer.Exit(1)
