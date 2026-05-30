"""Post-apply verification runner.

Executes a sequence of static analysis and test collection checks against a
freshly-scaffolded package to ensure structural and static validity.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from nohiki_scaffold.config.constants import DEFAULT_VERIFY_TIMEOUT_S
from nohiki_scaffold.config.paths import get_repo_root
from nohiki_scaffold.core.features import VerifyMode
from nohiki_scaffold.core.models.lib import LibSpec
from nohiki_scaffold.core.models.service import ServiceSpec

if TYPE_CHECKING:
    from nohiki_scaffold.core.build import BuildPlan


@dataclass(frozen=True, slots=True)
class CheckResult:
    """Outcome of a single verification check."""

    name: str
    passed: bool
    stdout: str
    stderr: str
    duration_s: float


@dataclass(frozen=True, slots=True)
class VerifyResult:
    """Outcome of a verification pass."""

    mode: VerifyMode
    passed: bool
    checks_run: tuple[str, ...] = field(default_factory=tuple)
    failures: tuple[str, ...] = field(default_factory=tuple)
    checks: tuple[CheckResult, ...] = field(default_factory=tuple)


def _resolve_package_path(plan: BuildPlan, repo_root: Path) -> Path:
    """Derive the target package directory from the plan and repo root."""
    if isinstance(plan.spec, LibSpec):
        return repo_root / "backend" / "libs" / plan.spec.name
    if isinstance(plan.spec, ServiceSpec):
        return repo_root / "backend" / "services" / plan.spec.name
    msg = f"Unknown spec type: {type(plan.spec)}"
    raise TypeError(msg)


def _resolve_package_name(plan: BuildPlan) -> str:
    """Return the distribution name of the package."""
    return plan.spec.name


def _run_check(
    name: str,
    args: list[str],
    *,
    repo_root: Path,
    timeout_s: int = DEFAULT_VERIFY_TIMEOUT_S,
) -> CheckResult:
    """Generic subprocess runner for verification checks."""
    start = time.perf_counter()
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            cwd=repo_root,
            check=False,
        )
        passed = proc.returncode == 0
        stdout = proc.stdout
        stderr = proc.stderr
    except subprocess.TimeoutExpired as e:
        passed = False
        stdout = e.stdout.decode() if e.stdout else ""
        stderr = f"Check timed out after {timeout_s}s\n{e.stderr.decode() if e.stderr else ''}"
    except FileNotFoundError:
        passed = False
        stdout = ""
        stderr = "Executable not found (is 'uv' on PATH?)"
    except OSError as e:
        passed = False
        stdout = ""
        stderr = str(e)

    return CheckResult(
        name=name,
        passed=passed,
        stdout=stdout,
        stderr=stderr,
        duration_s=time.perf_counter() - start,
    )


def _run_uv_sync(package_name: str, *, repo_root: Path) -> CheckResult:
    return _run_check("uv sync", ["uv", "sync", "--package", package_name], repo_root=repo_root)


def _run_ruff_check(pkg_dir: Path, *, repo_root: Path) -> CheckResult:
    return _run_check("ruff check", ["uv", "run", "ruff", "check", str(pkg_dir)], repo_root=repo_root)


def _run_ruff_format_check(pkg_dir: Path, *, repo_root: Path) -> CheckResult:
    return _run_check(
        "ruff format",
        ["uv", "run", "ruff", "format", "--check", str(pkg_dir)],
        repo_root=repo_root,
    )


def _run_ty_check(pkg_dir: Path, *, repo_root: Path) -> CheckResult:
    return _run_check("ty check", ["uv", "run", "ty", "check", str(pkg_dir / "src")], repo_root=repo_root)


def _run_pytest_collect(package_name: str, *, repo_root: Path) -> CheckResult:
    return _run_check(
        "pytest collect",
        ["uv", "run", "--package", package_name, "pytest", "--collect-only"],
        repo_root=repo_root,
    )


def _run_pytest(package_name: str, *, repo_root: Path) -> CheckResult:
    return _run_check(
        "pytest",
        ["uv", "run", "--package", package_name, "pytest"],
        repo_root=repo_root,
    )


def run_verify(
    plan: BuildPlan,
    *,
    mode: VerifyMode = VerifyMode.DEFAULT,
    repo_root: Path | None = None,
) -> VerifyResult:
    """Execute the verify pipeline for the given scaffold plan.

    Args:
        plan: The build plan whose target package will be verified.
        mode: Desired verification depth (default/full/none).
        repo_root: Optional monorepo root (derived if None).

    Returns:
        A VerifyResult describing the outcome.
    """
    if mode == VerifyMode.NONE:
        return VerifyResult(mode=mode, passed=True)

    root = repo_root or get_repo_root()
    pkg_dir = _resolve_package_path(plan, root)
    pkg_name = _resolve_package_name(plan)

    results: list[CheckResult] = []

    # All modes >= DEFAULT run these
    results.append(_run_uv_sync(pkg_name, repo_root=root))
    results.append(_run_ruff_check(pkg_dir, repo_root=root))
    results.append(_run_ruff_format_check(pkg_dir, repo_root=root))
    results.append(_run_ty_check(pkg_dir, repo_root=root))

    if mode == VerifyMode.FULL:
        results.append(_run_pytest(pkg_name, repo_root=root))
    else:
        results.append(_run_pytest_collect(pkg_name, repo_root=root))

    checks = tuple(results)
    passed = all(c.passed for c in checks)
    checks_run = tuple(c.name for c in checks if c.passed)
    failures = tuple(c.name for c in checks if not c.passed)

    return VerifyResult(
        mode=mode,
        passed=passed,
        checks_run=checks_run,
        failures=failures,
        checks=checks,
    )


__all__ = ["CheckResult", "VerifyResult", "run_verify"]
