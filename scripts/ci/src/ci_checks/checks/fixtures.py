"""Unused pytest fixture detection check.

Uses pytest-unused-fixtures to detect fixtures defined but never exercised
during test execution. Runs per-package to avoid pytest plugin collisions
across the uv workspace monorepo.
"""

from __future__ import annotations

import ast
import asyncio
import contextlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from ci_checks.core.display import console, render_error_panel, render_summary_table
from ci_checks.core.packages import REPO_ROOT, Package, PackageType
from ci_checks.core.process_env import sanitized_python_env

_UNUSED_FIXTURES_HEADER = re.compile(r"^=+ UNUSED FIXTURES =+$")
_FIXTURE_LINE = re.compile(r"^(\S+) -- (.+)$")
_INTEGRATION_DIR_NAME = "integration"
_PACKAGE_TIMEOUT_SECONDS = 600


@dataclass(frozen=True, slots=True)
class UnusedFixture:
    """Single unused fixture finding."""

    name: str
    location: str


@dataclass(slots=True)
class FixtureResult:
    """Scan result carrying unused fixture findings."""

    name: str
    passed: bool
    duration_ms: int = 0
    error: str = ""
    fixtures: list[UnusedFixture] = field(default_factory=list)
    # Test failures are tracked separately; they don't affect the fixture exit code.
    test_failures: bool = False


def _parse_unused_fixtures(stdout: str) -> list[UnusedFixture]:
    """Parse unused fixture names from pytest output.

    Args:
        stdout: Combined pytest stdout text.

    Returns:
        List of unused fixtures found in the UNUSED FIXTURES section.
    """
    fixtures: list[UnusedFixture] = []
    in_section = False

    for line in stdout.splitlines():
        if _UNUSED_FIXTURES_HEADER.match(line.strip()):
            in_section = True
            continue
        if not in_section:
            continue
        if line.strip().startswith("---"):
            continue
        if m := _FIXTURE_LINE.match(line.strip()):
            fixtures.append(UnusedFixture(name=m.group(1), location=m.group(2)))

    return fixtures


def _integration_test_paths(tests_dir: Path) -> list[Path]:
    """Return integration test directories that should be excluded from unit hygiene.

    Args:
        tests_dir: Package tests root.

    Returns:
        Sorted list of integration directories beneath the tests root.
    """
    return sorted(path for path in tests_dir.rglob(_INTEGRATION_DIR_NAME) if path.is_dir())


def _is_fixture_decorator(decorator: ast.expr) -> bool:
    """Return whether a decorator expression invokes pytest's fixture decorator."""
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    if isinstance(target, ast.Name):
        return target.id == "fixture"
    return (
        isinstance(target, ast.Attribute)
        and isinstance(target.value, ast.Name)
        and target.value.id == "pytest"
        and target.attr == "fixture"
    )


def _defines_fixture(tree: ast.AST) -> bool:
    """Return whether an AST contains a sync or async fixture definition."""
    return any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(_is_fixture_decorator(decorator) for decorator in node.decorator_list)
        for node in ast.walk(tree)
    )


def _fixture_modules(tests_dir: Path) -> list[Path] | None:
    """Find unit-test modules defining fixtures, or None to scan the full tree."""
    modules: list[Path] = []
    for path in sorted(tests_dir.rglob("*.py")):
        relative_parts = path.relative_to(tests_dir).parts
        if _INTEGRATION_DIR_NAME in relative_parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except OSError, SyntaxError, UnicodeError:
            return None
        if _defines_fixture(tree):
            if path.name in {"conftest.py", "helpers.py"}:
                return None
            modules.append(path)
    return modules


def fixture_report_args(pkg: Package) -> tuple[str, ...]:
    """Build pytest arguments that preserve the unit fixture scan scope.

    Args:
        pkg: Package whose fixture definitions should be reported.

    Returns:
        Pytest arguments for the package's existing fixture scan scope.
    """
    fixture_modules = _fixture_modules(pkg.tests_dir)
    if fixture_modules == []:
        return ()

    args = ["--unused-fixtures"]
    if fixture_modules is not None:
        args.extend(["--unused-fixtures-context", *(str(path) for path in fixture_modules)])
    for integration_dir in _integration_test_paths(pkg.tests_dir):
        args.extend(["--unused-fixtures-ignore-path", str(integration_dir)])
    return tuple(args)


async def scan_package(pkg: Package) -> FixtureResult:
    """Run pytest --unused-fixtures on a single package.

    Args:
        pkg: Package to scan (must have a tests/ directory).

    Returns:
        FixtureResult with unused fixture findings.
    """
    fixture_modules = _fixture_modules(pkg.tests_dir)
    if fixture_modules == []:
        return FixtureResult(name=pkg.name, passed=True)
    scan_targets = [str(pkg.tests_dir)] if fixture_modules is None else [str(path) for path in fixture_modules]

    cmd = ["uv", "run", "--no-sync"]
    if pkg.pkg_type == PackageType.SCRIPTS:
        cmd.extend(["--directory", str(pkg.path)])
    else:
        cmd.extend(["--package", pkg.name])
    cmd.extend(
        [
            "pytest",
            *scan_targets,
            "-q",
            "--tb=no",
            "--no-header",
            "-m",
            "not integration and not requires_docker",
            "--unused-fixtures",
        ]
    )
    for integration_dir in _integration_test_paths(pkg.tests_dir):
        cmd.extend(["--ignore", str(integration_dir)])
    env = sanitized_python_env(extra={"OTEL_SDK_DISABLED": "true"})

    start = asyncio.get_event_loop().time()
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=REPO_ROOT,
        env=env,
    )
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=_PACKAGE_TIMEOUT_SECONDS)
    except BaseException:
        if proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
        await proc.wait()
        raise
    duration_ms = int((asyncio.get_event_loop().time() - start) * 1000)

    stdout = stdout_bytes.decode()
    stderr = stderr_bytes.decode()
    fixtures = _parse_unused_fixtures(stdout)

    # returncode 5 = no tests collected; that's fine for fixture detection.
    test_failures = proc.returncode not in (0, 5)

    return FixtureResult(
        name=pkg.name,
        passed=len(fixtures) == 0,
        duration_ms=duration_ms,
        fixtures=fixtures,
        test_failures=test_failures,
        error=stderr if test_failures else "",
    )


def ci_suffix(result: FixtureResult) -> str:
    """CI-mode suffix showing unused fixture count when non-zero."""
    count = len(result.fixtures)
    return f" ({count} unused)" if count else ""


def render_results(results: list[FixtureResult], *, fail_on_unused: bool) -> bool:
    """Render the fixture hygiene summary and per-package details.

    Args:
        results: All scan results to summarise.
        fail_on_unused: Whether unused fixtures count as a check failure.

    Returns:
        True if the check passed (no failure condition triggered).
    """
    total_unused = sum(len(r.fixtures) for r in results)
    clean_count = sum(1 for r in results if r.passed)
    dirty = [r for r in results if not r.passed]

    render_summary_table(
        "Fixture Hygiene Summary",
        clean_count=clean_count,
        failed_count=len(dirty),
        total_issues=total_unused,
    )

    for result in dirty:
        lines = [f"  {f.name} @ {f.location}" for f in result.fixtures]
        render_error_panel(
            f"{result.name} ({len(result.fixtures)} unused)",
            "\n".join(lines),
        )

    # Test failures are advisory -- they don't change the exit code.
    test_fail_pkgs = [r for r in results if r.test_failures]
    if test_fail_pkgs:
        console.print(
            f"\n[yellow]⚠ {len(test_fail_pkgs)} package(s) had test failures (fixture detection still ran)[/yellow]"
        )

    return not (fail_on_unused and total_unused > 0)
