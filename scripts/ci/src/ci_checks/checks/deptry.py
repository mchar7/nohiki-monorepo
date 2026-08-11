"""Dependency hygiene check using deptry.

Detects undeclared, unused, and transitive dependencies per workspace package.
Runs deptry via the Python executable to avoid a separate ephemeral install.
Per-package exceptions live in each package's own [tool.deptry.per_rule_ignores]
section, which deptry reads from the pyproject.toml in its working directory.
"""

from __future__ import annotations

import asyncio
import sys
import tomllib
from dataclasses import dataclass

from ci_checks.core.display import console, render_error_panel, render_summary_table
from ci_checks.core.packages import Package
from ci_checks.core.process_env import sanitized_python_env

_DEPTRY_PROCESS_WATCHDOG_SECONDS = 6 * 60 * 60


_DEV_OPTIONAL_GROUPS = ("dev", "test", "testing")
_DOMAIN_MODEL_MODULES = "nohiki-domain-models=nohiki|nohiki_proto_google|nohiki_domain_utils|message_pool"


def _dev_optional_groups(pkg: Package) -> tuple[str, ...]:
    """Return optional dependency groups that contain test tooling."""
    with (pkg.path / "pyproject.toml").open("rb") as project_file:
        config = tomllib.load(project_file)
    project = config.get("project")
    if not isinstance(project, dict):
        return ()
    optional = project.get("optional-dependencies")
    if not isinstance(optional, dict):
        return ()
    return tuple(group for group in _DEV_OPTIONAL_GROUPS if group in optional)


@dataclass(slots=True)
class DeptryResult:
    """Scan result carrying raw deptry output and issue count."""

    name: str
    passed: bool
    duration_ms: int = 0
    error: str = ""
    output: str = ""
    issues_found: int = 0


async def scan_package(pkg: Package) -> DeptryResult:
    """Run deptry on a single package.

    Args:
        pkg: Package to scan.

    Returns:
        DeptryResult with output and issue count.
    """
    cmd = [
        sys.executable,
        "-m",
        "deptry",
        str(pkg.src_dir),
        "--no-ansi",
        "--extend-exclude",
        "alembic|tests",
        "--package-module-name-map",
        _DOMAIN_MODEL_MODULES,
    ]
    if dev_groups := _dev_optional_groups(pkg):
        cmd.extend(("--optional-dependencies-dev-groups", ",".join(dev_groups)))
    start = asyncio.get_event_loop().time()
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=pkg.path,
        env=sanitized_python_env(),
    )
    stdout, stderr = await asyncio.wait_for(
        proc.communicate(),
        timeout=_DEPTRY_PROCESS_WATCHDOG_SECONDS,
    )
    duration_ms = int((asyncio.get_event_loop().time() - start) * 1000)

    output = stdout.decode() + stderr.decode()
    issues = len([line for line in output.split("\n") if "DEP00" in line])

    return DeptryResult(
        name=pkg.name,
        passed=proc.returncode == 0,
        duration_ms=duration_ms,
        output=output,
        issues_found=issues,
    )


def ci_suffix(result: DeptryResult) -> str:
    """CI-mode suffix showing issue count when non-zero."""
    return f" ({result.issues_found} issues)" if result.issues_found else ""


def render_results(results: list[DeptryResult]) -> bool:
    """Render the deptry summary and per-package output panels.

    Args:
        results: All scan results to summarise.

    Returns:
        True if all packages passed.
    """
    passed_count = sum(1 for r in results if r.passed)
    failed = [r for r in results if not r.passed]
    total_issues = sum(r.issues_found for r in results)

    render_summary_table(
        "Dependency Hygiene Summary",
        clean_count=passed_count,
        failed_count=len(failed),
        total_issues=total_issues,
    )

    for r in failed:
        render_error_panel(r.name, r.output)

    if any(r.error for r in results):
        error_pkgs = [r for r in results if r.error]
        console.print(f"\n[red]⚠ {len(error_pkgs)} package(s) had errors[/red]")

    return len(failed) == 0
