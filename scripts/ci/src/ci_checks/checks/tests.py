"""Workspace test runner with consolidated execution and live summaries.

Runs selected workspace test suites in one pytest process, with change-based
selection, coverage gating, and CI-friendly plain output.
"""

from __future__ import annotations

import ast
import asyncio
import contextlib
import json
import os
import re
import subprocess
import tempfile
import time
import tomllib
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
from coverage.files import GlobMatcher
from rich.console import Console
from rich.panel import Panel

from ci_checks.core.display import markdown_table
from ci_checks.core.packages import (
    REPO_ROOT,
    Package,
    PackageType,
    Scope,
)
from ci_checks.core.process_env import sanitized_python_env

# Constants

PYTEST_SUCCESS = 0
_WHOLE_PACKAGE_PROCESS_WATCHDOG_SECONDS: int = 18 * 60
_UNIT_TEST_MARKERS = (
    "not integration and not e2e and not requires_docker "
    "and not requires_node_modules and not requires_skylos and not slow"
)
_PYTEST_CONTROLLER_RESULT_NAME = "pytest controller"
_UNIT_EXCLUDED_MARKERS = frozenset(
    {"integration", "e2e", "requires_docker", "requires_node_modules", "requires_skylos", "slow"}
)


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
    source_has_statements: bool = False


# Coverage parsing

_COVERAGE_LINE_PATTERN = re.compile(
    r"^([\w/.%+\x2d]+\.py)\s+(\d+)\s+(\d+)\s+(\d+)%",
    re.MULTILINE,
)
_TOTAL_COVERAGE_PATTERN = re.compile(r"^TOTAL\s+\d+\s+\d+\s+(\d+)%", re.MULTILINE)
_PACKAGE_COVERAGE_PATTERN = re.compile(r'addopts\s*=\s*"[^"]*--cov=([^\s"]+)')


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


def _string_object_mapping(value: object, context: str) -> dict[str, object]:
    if not isinstance(value, dict):
        msg = f"coverage JSON {context} must be an object"
        raise TypeError(msg)
    mapping: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            msg = f"coverage JSON {context} keys must be strings"
            raise TypeError(msg)
        mapping[key] = item
    return mapping


def _parse_coverage_json(path: Path) -> CoverageResult:
    """Parse a pytest-cov JSON report into a CoverageResult."""
    if not path.is_file():
        return CoverageResult()
    payload = _string_object_mapping(json.loads(path.read_text(encoding="utf-8")), "root")
    files = _string_object_mapping(payload.get("files"), "files")
    result = CoverageResult()
    for file_path, file_data in files.items():
        file_mapping = _string_object_mapping(file_data, f"file {file_path}")
        summary = _string_object_mapping(file_mapping.get("summary"), f"file {file_path} summary")
        statements = summary.get("num_statements")
        missed = summary.get("missing_lines")
        percent_display = summary.get("percent_covered_display")
        if not isinstance(statements, int) or not isinstance(missed, int) or not isinstance(percent_display, str):
            msg = f"coverage JSON file {file_path} summary has invalid values"
            raise TypeError(msg)
        result.files.append(
            FileCoverage(
                path=file_path,
                stmts=statements,
                miss=missed,
                cover=float(percent_display),
            )
        )
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


# Test execution


def _sync_workspace(console: Console) -> None:
    """Synchronize the frozen workspace environment before parallel test execution.

    CI may skip this sync after installing the cached frozen workspace. Local runs use
    the canonical dev sync shape behind the exclusive venv lock so a runner invocation
    never narrows an environment that other consumers share.
    """
    if os.environ.get("CI_CHECKS_SKIP_WORKSPACE_SYNC", "").casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        console.print("[blue]INFO:[/blue] Skipping workspace sync; CI already installed the frozen workspace.")
        return
    result = subprocess.run(
        [
            "scripts/dev/env-lock.sh",
            "exclusive",
            "venv",
            "--",
            "uv",
            "sync",
            "--all-packages",
            "--all-extras",
            "--no-extra",
            "cuda",
            "--group",
            "deadcode",
            "--frozen",
        ],
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


def _parse_test_progress(line: str) -> int:
    """Count completed test markers in a pytest output line.

    Args:
        line: Single line of pytest verbose output.

    Returns:
        Number of PASSED/FAILED/ERROR/SKIPPED/XFAIL/XPASS tokens found.
    """
    return len(re.findall(r"\b(PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)\b", line))


async def _wait_for_package_process(proc: asyncio.subprocess.Process) -> None:
    await asyncio.wait_for(proc.wait(), timeout=_WHOLE_PACKAGE_PROCESS_WATCHDOG_SECONDS)


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

    stdout_reader = proc.stdout
    stderr_reader = proc.stderr
    if stdout_reader is None or stderr_reader is None:
        if proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
        await proc.wait()
        missing_stream = "stdout" if stdout_reader is None else "stderr"
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
        while chunk := await stdout_reader.read(65536):
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
        while chunk := await stderr_reader.read(65536):
            stderr_chunks.append(chunk)

    timeout_error: TimeoutError | None = None

    async def wait_for_process() -> None:
        nonlocal timeout_error
        try:
            await _wait_for_package_process(proc)
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
    pytest_passed = proc.returncode == PYTEST_SUCCESS
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
        source_has_statements=_source_has_statements(pkg),
    )


@dataclass(slots=True)
class _PackagePytestStats:
    """Per-package facts reported by pytest's JUnit output."""

    tests_run: int = 0
    tests_failed: int = 0
    duration_ms: int = 0


def _repo_relative(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _coverage_src_dir(pkg: Package) -> str:
    pyproject = pkg.path / "pyproject.toml"
    if pyproject.is_file() and (match := _PACKAGE_COVERAGE_PATTERN.search(pyproject.read_text(encoding="utf-8"))):
        return match.group(1)
    return _get_src_dir(pkg)


def _coverage_target(pkg: Package) -> str:
    return _repo_relative(pkg.path / _coverage_src_dir(pkg))


def _module_measures_statements(path: Path) -> bool:
    """Return whether coverage.py would count at least one statement in a module.

    Args:
        path: Python source file inside a package's coverage target.

    Returns:
        False only for the cases coverage.py also reports as zero statements: an
        empty module and a module holding nothing but its docstring. Unreadable
        or unparseable source counts as code, so it cannot mask a blanked package.
    """
    try:
        body = ast.parse(path.read_bytes(), filename=str(path)).body
    except OSError, SyntaxError:
        return True
    if len(body) != 1:
        return bool(body)
    docstring = body[0]
    return not (
        isinstance(docstring, ast.Expr)
        and isinstance(docstring.value, ast.Constant)
        and isinstance(docstring.value.value, str)
    )


def _source_has_statements(pkg: Package) -> bool:
    """Return whether a package's coverage target holds any measurable code.

    Args:
        pkg: Package whose coverage target is inspected.

    Returns:
        True when at least one module under the target contributes statements.
        A code-free namespace package returns False and is legitimately unmeasured.
    """
    target = pkg.path / _coverage_src_dir(pkg)
    return any(_module_measures_statements(path) for path in target.rglob("*.py"))


def _omit_blanks_source(pattern: str, targets: list[str]) -> bool:
    """Return whether a root omit pattern would blank a selected package's own source.

    Args:
        pattern: A ``tool.coverage.run.omit`` entry from the root pyproject.
        targets: Repo-relative coverage target directories of the selected packages.

    Returns:
        True when coverage.py's own matcher would apply the pattern to a target.
        GlobMatcher is what coverage.py builds its omit matcher from, and its
        trailing ``/*`` token spans path separators (coverage/files.py
        G2RX_TOKENS), so pattern and target component counts need not line up.
    """
    matcher = GlobMatcher([pattern], name="omit-cancel")
    return any(matcher.match(target) for target in targets)


def _root_coverage_values(section: str, option: str) -> list[str]:
    current: object = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    keys = ("tool", "coverage", section, option)
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            msg = f"root pyproject.toml must define {'.'.join(keys)}"
            raise ValueError(msg)
        current = current[key]
    if not isinstance(current, list) or not all(isinstance(value, str) for value in current):
        msg = f"root pyproject.toml {'.'.join(keys)} must be a list of strings"
        raise ValueError(msg)
    return [value for value in current if isinstance(value, str)]


def _write_consolidated_coverage_config(path: Path, packages: list[Package]) -> None:
    source = [str((pkg.path / _coverage_src_dir(pkg)).resolve()) for pkg in packages]
    source_targets = [_coverage_target(pkg) for pkg in packages]
    omit = [
        pattern for pattern in _root_coverage_values("run", "omit") if not _omit_blanks_source(pattern, source_targets)
    ]
    exclude_also = _root_coverage_values("report", "exclude_lines")
    path.write_text(
        "\n".join(
            [
                "[run]",
                f"data_file = {path.parent / '.coverage'}",
                "source =",
                *(f"    {value}" for value in source),
                "omit =",
                *(f"    {value}" for value in omit),
                "",
                "[report]",
                # Extending instead of replacing preserves coverage.py's built-in exclusions.
                "exclude_also =",
                *(f"    {value}" for value in exclude_also),
                "",
            ]
        ),
        encoding="utf-8",
    )


def _parse_package_coverage(path: Path, packages: list[Package]) -> dict[str, CoverageResult]:
    combined = _parse_coverage_json(path)
    targets = {pkg.name: Path(_coverage_target(pkg)).as_posix().removeprefix("./") for pkg in packages}
    results: dict[str, CoverageResult] = {}
    for pkg in packages:
        target = targets[pkg.name]
        files = [
            file
            for file in combined.files
            if (file_path := Path(file.path).as_posix().removeprefix("./")) == target
            or file_path.startswith(f"{target}/")
        ]
        statements = sum(file.stmts for file in files)
        missed = sum(file.miss for file in files)
        percentage = round((statements - missed) * 100 / statements) if statements else 0
        results[pkg.name] = CoverageResult(total_coverage=float(percentage), files=files)
    return results


def _test_helper_module_owners(packages: list[Package]) -> dict[str, set[str]]:
    owners: dict[str, set[str]] = {}
    for pkg in packages:
        for path in (pkg.path / "tests").rglob("*.py"):
            if path.name.startswith("test_") or path.name in {
                "__init__.py",
                "conftest.py",
            }:
                continue
            owners.setdefault(path.name, set()).add(pkg.name)
    return owners


def _pythonpath_test_dirs(packages: list[Package]) -> list[Path]:
    ci_checks = next((pkg for pkg in packages if pkg.name == "ci-checks"), None)
    if ci_checks is None:
        return []
    helper_owners = _test_helper_module_owners(packages)
    ci_helpers = {
        path.name
        for path in (ci_checks.path / "tests").rglob("*.py")
        if not path.name.startswith("test_") and path.name not in {"__init__.py", "conftest.py"}
    }
    collisions = {name: helper_owners[name] for name in ci_helpers if len(helper_owners[name]) > 1}
    if collisions:
        details = ", ".join(f"{name}: {', '.join(sorted(owners))}" for name, owners in sorted(collisions.items()))
        message = f"Cannot isolate consolidated pytest helper imports: {details}"
        raise RuntimeError(message)
    return [ci_checks.path / "tests"]


def _pytest_marker_name(node: ast.expr) -> str | None:
    candidate = node.func if isinstance(node, ast.Call) else node
    if (
        isinstance(candidate, ast.Attribute)
        and isinstance(candidate.value, ast.Attribute)
        and isinstance(candidate.value.value, ast.Name)
        and candidate.value.value.id == "pytest"
        and candidate.value.attr == "mark"
    ):
        return candidate.attr
    return None


def _has_excluded_marker(decorators: list[ast.expr], excluded: frozenset[str]) -> bool:
    return any(_pytest_marker_name(decorator) in excluded for decorator in decorators)


def _module_has_excluded_pytestmark(module: ast.Module, excluded: frozenset[str]) -> bool:
    for statement in module.body:
        if not isinstance(statement, ast.Assign) or not any(
            isinstance(target, ast.Name) and target.id == "pytestmark" for target in statement.targets
        ):
            continue
        values = statement.value.elts if isinstance(statement.value, (ast.List, ast.Tuple)) else [statement.value]
        if any(_pytest_marker_name(value) in excluded for value in values):
            return True
    return False


def _class_tests_are_excluded(node: ast.ClassDef, excluded: frozenset[str]) -> tuple[bool, bool]:
    if _has_excluded_marker(node.decorator_list, excluded):
        return True, True
    if node.bases:
        return False, True
    found = False
    for statement in node.body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)) and statement.name.startswith("test"):
            found = True
            if not _has_excluded_marker(statement.decorator_list, excluded):
                return False, True
        elif isinstance(statement, ast.ClassDef) and statement.name.startswith("Test"):
            nested_excluded, nested_found = _class_tests_are_excluded(statement, excluded)
            found = found or nested_found
            if not nested_excluded:
                return False, found
    return True, found


def _test_module_is_wholly_excluded(path: Path, excluded: frozenset[str]) -> bool:
    try:
        module = ast.parse(path.read_bytes(), filename=str(path))
    except OSError, SyntaxError:
        return False
    if _module_has_excluded_pytestmark(module, excluded):
        return True
    found = False
    for statement in module.body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)) and statement.name.startswith("test"):
            found = True
            if not _has_excluded_marker(statement.decorator_list, excluded):
                return False
        elif isinstance(statement, ast.ClassDef) and statement.name.startswith("Test"):
            class_excluded, class_found = _class_tests_are_excluded(statement, excluded)
            found = found or class_found
            if not class_excluded:
                return False
        elif isinstance(statement, (ast.Assign, ast.AnnAssign)):
            targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
            if any(
                isinstance(target, ast.Name)
                and (target.id.startswith("test") or target.id.startswith("Test"))
                and target.id != "pytestmark"
                for target in targets
            ):
                return False
    return found


def _unit_excluded_test_modules(packages: list[Package], markers: str) -> list[Path]:
    if markers != _UNIT_TEST_MARKERS:
        return []
    return [
        path
        for pkg in packages
        for path in sorted((pkg.path / "tests").rglob("test_*.py"))
        if _test_module_is_wholly_excluded(path, _UNIT_EXCLUDED_MARKERS)
    ]


def _junit_prefix(pkg: Package) -> str:
    path = _repo_relative(pkg.path)
    return Path(path).as_posix().replace("/", ".") + ".tests"


def _parse_package_stats(junit_path: Path, packages: list[Package]) -> dict[str, _PackagePytestStats]:
    stats = {pkg.name: _PackagePytestStats() for pkg in packages}
    classname_prefixes = sorted(((_junit_prefix(pkg), pkg.name) for pkg in packages), reverse=True)
    file_prefixes = sorted(
        (
            (
                Path(_repo_relative(pkg.path / "tests")).as_posix().removeprefix("./"),
                pkg.name,
            )
            for pkg in packages
        ),
        reverse=True,
    )
    # pytest writes this local temporary file; it is not an untrusted input.
    for testcase in ET.parse(junit_path).getroot().iter("testcase"):  # noqa: S314
        classname = testcase.get("classname", "")
        file = Path(testcase.get("file", "")).as_posix().removeprefix("./")
        package_name = next((name for prefix, name in file_prefixes if file.startswith(prefix)), None)
        if package_name is None:
            package_name = next(
                (name for prefix, name in classname_prefixes if classname.startswith(prefix)),
                None,
            )
        if package_name is None:
            continue
        package_stats = stats[package_name]
        package_stats.tests_run += 1
        package_stats.duration_ms += round(float(testcase.get("time", "0")) * 1000)
        if testcase.find("failure") is not None or testcase.find("error") is not None:
            package_stats.tests_failed += 1
    return stats


async def run_consolidated_tests(
    packages: list[Package],
    markers: str,
    extra_args: tuple[str, ...],
    *,
    pytest_workers: int,
    with_coverage: bool = True,
) -> list[TestResult]:
    """Run all selected packages in one pytest process.

    Args:
        packages: Packages whose test directories pytest should collect.
        markers: pytest -m expression to filter tests.
        extra_args: Additional pytest arguments.
        pytest_workers: Memory- and CPU-bounded xdist worker count.
        with_coverage: Whether to enable per-package pytest-cov reporting.

    Returns:
        One attributed result per selected package, plus a controller result on a nonzero pytest exit.
    """
    with tempfile.TemporaryDirectory(prefix="ci-checks-pytest-") as temp_dir:
        junit_path = Path(temp_dir) / "junit.xml"
        coverage_config = Path(temp_dir) / "coverage.ini"
        coverage_json = Path(temp_dir) / "coverage.json"
        cmd = [
            "uv",
            "run",
            "--no-sync",
            "pytest",
            f"--rootdir={REPO_ROOT}",
            *(_repo_relative(pkg.path / "tests") for pkg in packages),
            *(f"--ignore={_repo_relative(path)}" for path in _unit_excluded_test_modules(packages, markers)),
            "--tb=short",
            f"--junitxml={junit_path}",
            "-o",
            "junit_family=legacy",
            "-n",
            str(pytest_workers),
            "--dist=worksteal",
        ]
        if with_coverage:
            _write_consolidated_coverage_config(coverage_config, packages)
            cmd.extend(
                [
                    "--cov",
                    f"--cov-config={coverage_config}",
                    f"--cov-report=json:{coverage_json}",
                    "--cov-fail-under=0",
                ]
            )
        if markers:
            cmd.extend(["-m", markers])
        cmd.extend(extra_args)

        test_env = sanitized_python_env()
        test_paths = [str(path) for path in _pythonpath_test_dirs(packages)]
        if existing_pythonpath := test_env.get("PYTHONPATH"):
            test_paths.append(existing_pythonpath)
        if test_paths:
            test_env["PYTHONPATH"] = os.pathsep.join(test_paths)

        started = time.time()
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=REPO_ROOT,
            env=test_env,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=_WHOLE_PACKAGE_PROCESS_WATCHDOG_SECONDS,
            )
        except TimeoutError:
            if proc.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    proc.kill()
            await proc.wait()
            raise

        output = stdout.decode() + stderr.decode()
        exit_code = proc.returncode if proc.returncode is not None else -1
        stats = (
            _parse_package_stats(junit_path, packages)
            if junit_path.is_file()
            else {pkg.name: _PackagePytestStats() for pkg in packages}
        )
        coverage = (
            _parse_package_coverage(coverage_json, packages)
            if with_coverage
            else {pkg.name: CoverageResult() for pkg in packages}
        )
        failed_packages = {name for name, package_stats in stats.items() if package_stats.tests_failed}
        wall_duration_ms = int((time.time() - started) * 1000)
        results: list[TestResult] = []
        for pkg in packages:
            package_stats = stats[pkg.name]
            has_tests = package_stats.tests_run > 0
            if not has_tests:
                package_output = f"No selected tests were collected for package {pkg.name}."
            elif package_stats.tests_failed:
                package_output = output
            else:
                package_output = ""
            results.append(
                TestResult(
                    name=pkg.name,
                    passed=has_tests and package_stats.tests_failed == 0,
                    duration_ms=package_stats.duration_ms or (wall_duration_ms if not has_tests else 0),
                    output=package_output,
                    tests_run=package_stats.tests_run,
                    tests_failed=package_stats.tests_failed,
                    coverage=coverage[pkg.name],
                    pkg_type=pkg.pkg_type,
                    source_has_statements=_source_has_statements(pkg),
                )
            )
        if exit_code != PYTEST_SUCCESS:
            controller_output = f"pytest controller exited with status {exit_code}."
            if not failed_packages:
                controller_output = f"{controller_output}\n\n{output}"
            results.append(
                TestResult(
                    name=_PYTEST_CONTROLLER_RESULT_NAME,
                    passed=False,
                    duration_ms=wall_duration_ms,
                    output=controller_output,
                )
            )
        return results


def _display_consolidated_results(results: list[TestResult], console: Console, *, with_coverage: bool) -> None:
    cov_header = " Cov% " if with_coverage else ""
    console.print(f"\n{'Module':<40} {'Tests':>5} {'Time':>6} {'Status':>9}{cov_header}")
    console.print("-" * 70)
    for result in results:
        icon = "✓ PASS" if result.passed else "✗ FAIL"
        cov_info = f"  {result.coverage.total_coverage:>3.0f}%" if with_coverage else ""
        console.print(f"{result.name:<40} {result.tests_run:>5} {result.duration_ms / 1000:>5.1f}s {icon:>9}{cov_info}")


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
    """Run all selected tests in one memory- and CPU-bounded pytest process.

    Args:
        packages: Packages to test.
        markers: pytest -m expression.
        extra_args: Additional pytest arguments.
        max_workers: Maximum xdist workers allowed by the memory budget.
        console: Rich console for output.
        ci_mode: Retained for the stable CLI output contract.
        with_coverage: Whether to collect coverage data.

    Returns:
        List of per-package TestResult values.
    """
    del ci_mode
    _sync_workspace(console)
    available_workers = os.process_cpu_count() or 1
    pytest_workers = max(1, min(available_workers, max_workers))
    results = await run_consolidated_tests(
        packages,
        markers,
        extra_args,
        pytest_workers=pytest_workers,
        with_coverage=with_coverage,
    )
    _display_consolidated_results(results, console, with_coverage=with_coverage)
    return results


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


def _coverage_is_blanked(result: TestResult) -> bool:
    """Return whether coverage measured nothing for a package whose source holds code."""
    return result.source_has_statements and not any(file.stmts for file in result.coverage.files)


def _coverage_meets_policy(result: TestResult) -> bool:
    """Return whether a result satisfies its package-type coverage policy."""
    if _coverage_is_blanked(result):
        return False
    if not any(file.stmts for file in result.coverage.files):
        return True
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
        if _coverage_is_blanked(result):
            console.print(
                f"\n[red]{result.name}: source files carry statements but coverage measured none. "
                f"The package is unmeasured, not passing.[/red]"
            )
            continue
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


def _coverage_cells(result: TestResult) -> tuple[str, str]:
    """Render one package's coverage percentage and its policy verdict.

    Args:
        result: One package's test and coverage result.

    Returns:
        The coverage cell and the policy cell, in that order.
    """
    gate = get_coverage_gate(result.pkg_type)
    thresholds = f"module >= {gate.module_threshold:.0f}%, file >= {gate.file_threshold:.0f}%"
    # Three states share "no percentage", and they are not interchangeable. Blanked coverage is a
    # policy FAILURE: the source carries code that coverage never saw. A code-free package is
    # neutral. Rendering either as 0% would instead claim measured code that is entirely uncovered.
    if _coverage_is_blanked(result):
        return "none", "unmeasured: source carries statements but coverage measured none"
    if not any(file.stmts for file in result.coverage.files):
        return "n/a", "no policy: the package carries no measurable statements"
    percentage = f"{result.coverage.total_coverage:.0f}%"
    if gate.name == "no-requirements":
        return percentage, f"no policy: {result.pkg_type} packages carry the no-requirements gate ({thresholds})"
    below = gate.get_failing_files(result.coverage)
    if below or not gate.check_module(result.coverage):
        plural = "" if len(below) == 1 else "s"
        detail = f", {len(below)} file{plural} under {gate.file_threshold:.0f}%" if below else ""
        return percentage, f"below {gate.name} policy: {thresholds}{detail}"
    return percentage, f"meets {gate.name} policy: {thresholds}"


def render_github_summary(results: list[TestResult], title: str, *, strict: bool = False) -> str:
    """Render one test batch as a GitHub-flavored Markdown summary.

    Args:
        results: Package test results in the batch.
        title: Batch name displayed in the heading.
        strict: Whether coverage gates the run, which decides what the header claims.

    Returns:
        Markdown for the batch block of a job step summary, as a level-four
        section so it nests under the job's Results heading.
    """
    passed = sum(result.passed for result in results)
    enforcement = (
        "Coverage is enforced: a package below its policy fails this lane."
        if strict
        else "Coverage is reported, not enforced: this lane runs without `--strict`."
    )
    lines = [
        f"#### Python tests ({title})",
        "",
        f"**{passed}/{len(results)} packages passed.** {enforcement}",
        "",
    ]
    lines += markdown_table(
        ["Package", "Duration", "Tests", "Coverage", "Coverage policy"],
        [
            (
                f"`{result.name}`",
                f"{result.duration_ms / 1000:.1f}s",
                "Pass" if result.passed else "Fail",
                *_coverage_cells(result),
            )
            for result in sorted(results, key=lambda item: item.name)
        ],
        align=("left", "right", "center", "right", "left"),
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
            console.print(result.output, markup=False)
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
            summary_file.write(render_github_summary(results, summary_title, strict=strict))

    if _check_exit_conditions(results, strict=strict, with_coverage=coverage):
        raise typer.Exit(1)
