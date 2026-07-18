"""Build-backend consistency check for workspace packages.

Every workspace package must declare the canonical ``[build-system]``
stanza so the monorepo builds uniformly via uv_build. The validator is
also responsible for catching leftover ``[tool.hatch.*]`` or
``[tool.setuptools.*]`` sections — residue from backends superseded by
uv_build — after a package has migrated.

The canonical stanza is:

    [build-system]
    requires = ["uv_build>=0.11.7,<0.12"]
    build-backend = "uv_build"

Operating modes:

- Default (rollout): report migration progress. Fail only on DRIFTED
  packages (already on uv_build but diverging from the canonical
  stanza, or still carrying ``[tool.hatch.*]`` / ``[tool.setuptools.*]``
  residue).
- ``--strict`` (post-rollout gate): additionally fail on PENDING
  packages — i.e. any package still awaiting migration to uv_build.
  Wire this into ``just hygiene`` once the rollout is complete.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from enum import StrEnum
from typing import cast

from rich.markup import escape

from ci_checks.core.display import console, render_error_panel, render_summary_table
from ci_checks.core.packages import Package

# Canonical stanza

# Single source of truth for the workspace's canonical ``[build-system]``.
# Bump both constants together when migrating across a uv_build major
# version (see docs.astral.sh/uv/concepts/build-backend/).
CANONICAL_BUILD_BACKEND = "uv_build"
CANONICAL_REQUIRES: tuple[str, ...] = ("uv_build>=0.11.7,<0.12",)

# Tool-table prefixes from backends superseded by uv_build. They must be
# absent from every package: both migrated ones (to prevent residue) and
# non-buildable virtual members (to prevent dead config drift). Orphan
# ``[tool.hatch.metadata]`` blocks are a common residue from the
# setuptools → hatchling → uv_build path.
SUPERSEDED_TOOL_TABLES: tuple[str, ...] = ("hatch", "setuptools")


class BackendStatus(StrEnum):
    """Per-package classification."""

    CANONICAL = "canonical"  # uv_build with canonical pin, no superseded residue
    DRIFTED = "drifted"  # uv_build but stanza diverges, or superseded residue present
    PENDING = "pending"  # awaiting migration to uv_build (transient rollout state)
    NOT_BUILT = "not-built"  # workspace member without [build-system] (e.g. test-only)
    UNKNOWN = "unknown"  # unrecognised backend or parse failure


# Result type


@dataclass(slots=True)
class BackendResult:
    """Scan result carrying backend classification and drift details."""

    name: str
    passed: bool
    duration_ms: int = 0
    error: str = ""
    status: BackendStatus = BackendStatus.UNKNOWN
    backend: str = ""
    issues: list[str] = field(default_factory=list)


# Core check


def _superseded_tool_tables(config: dict[str, object]) -> list[str]:
    """Return the list of forbidden ``[tool.<x>.*]`` sections still present."""
    tool_section = config.get("tool")
    if not isinstance(tool_section, dict):
        return []
    tool = cast("dict[str, object]", tool_section)
    return [f"[tool.{key}]" for key in SUPERSEDED_TOOL_TABLES if key in tool]


def _classify(config: dict[str, object]) -> tuple[BackendStatus, str, list[str]]:
    """Classify a package's build-system state.

    Returns:
        Tuple of (status, backend name, list of human-readable issues).
    """
    raw_build_system = config.get("build-system")
    if not isinstance(raw_build_system, dict):
        # Workspace members without [build-system] are virtual (e.g. the tests/
        # package) and intentionally never built as wheels. They still must not
        # carry superseded tool-table residue.
        residue = _superseded_tool_tables(config)
        if residue:
            return (
                BackendStatus.DRIFTED,
                "",
                [f"superseded tool tables in non-buildable package: {', '.join(residue)}"],
            )
        return BackendStatus.NOT_BUILT, "", []
    build_system = cast("dict[str, object]", raw_build_system)

    backend_value = build_system.get("build-backend")
    backend = backend_value if isinstance(backend_value, str) else ""
    requires_value = build_system.get("requires")
    requires: list[str] = [r for r in requires_value if isinstance(r, str)] if isinstance(requires_value, list) else []

    if backend != CANONICAL_BUILD_BACKEND:
        match backend:
            case "hatchling.build" | "setuptools.build_meta":
                return BackendStatus.PENDING, backend, []
            case "":
                return BackendStatus.UNKNOWN, backend, ["no build-backend declared"]
            case _:
                return (
                    BackendStatus.UNKNOWN,
                    backend,
                    [f"unrecognised build-backend: {backend!r}"],
                )

    # Already on uv_build: enforce canonical pin + absence of superseded residue.
    issues: list[str] = []
    if tuple(requires) != CANONICAL_REQUIRES:
        expected = ", ".join(repr(r) for r in CANONICAL_REQUIRES)
        actual = ", ".join(repr(r) for r in requires) or "<empty>"
        issues.append(f"requires = [{actual}] (expected [{expected}])")

    residue = _superseded_tool_tables(config)
    if residue:
        issues.append(f"superseded tool tables present: {', '.join(residue)}")

    status = BackendStatus.CANONICAL if not issues else BackendStatus.DRIFTED
    return status, backend, issues


def scan_package(pkg: Package) -> BackendResult:
    """Classify a single package's build-system configuration."""
    pyproject = pkg.path / "pyproject.toml"
    if not pyproject.exists():
        return BackendResult(
            name=pkg.name,
            passed=False,
            status=BackendStatus.UNKNOWN,
            issues=[f"missing {pyproject}"],
        )

    try:
        config = tomllib.loads(pyproject.read_text())
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return BackendResult(
            name=pkg.name,
            passed=False,
            status=BackendStatus.UNKNOWN,
            error=str(exc),
            issues=[f"failed to parse: {exc}"],
        )

    status, backend, issues = _classify(config)
    # DRIFTED / UNKNOWN always fail. PENDING fails only under --strict
    # (rollout is complete). CANONICAL and NOT_BUILT always pass.
    passed = status in (
        BackendStatus.CANONICAL,
        BackendStatus.PENDING,
        BackendStatus.NOT_BUILT,
    )
    return BackendResult(
        name=pkg.name,
        passed=passed,
        status=status,
        backend=backend,
        issues=issues,
    )


# Rendering


def ci_suffix(result: BackendResult) -> str:
    """CI-mode suffix summarising backend + drift state."""
    label = result.backend or result.status.value
    return f" ({label})"


def render_results(results: list[BackendResult], *, strict: bool) -> bool:
    """Render the summary + drift panels. Return True if all gates pass.

    In non-strict (rollout) mode, PENDING packages are informational —
    migration is in progress. In strict (post-rollout) mode, any package
    not on uv_build fails.
    """
    by_status: dict[BackendStatus, list[BackendResult]] = {s: [] for s in BackendStatus}
    for r in results:
        by_status[r.status].append(r)

    canonical = by_status[BackendStatus.CANONICAL]
    drifted = by_status[BackendStatus.DRIFTED]
    pending = by_status[BackendStatus.PENDING]
    not_built = by_status[BackendStatus.NOT_BUILT]
    unknown = by_status[BackendStatus.UNKNOWN]

    render_summary_table(
        "Build-backend Summary",
        clean_count=len(canonical),
        failed_count=len(drifted) + len(unknown),
        total_issues=sum(len(r.issues) for r in results),
        extra_rows=[
            ("[yellow]Pending migration to uv_build[/yellow]", str(len(pending))),
            ("[dim]Not built (virtual workspace members)[/dim]", str(len(not_built))),
            ("[bold]Total packages[/bold]", str(len(results))),
            ("[bold]Canonical pin[/bold]", CANONICAL_REQUIRES[0]),
        ],
    )

    if pending:
        names = ", ".join(sorted(r.name for r in pending))
        console.print(f"\n[yellow]Pending migration to uv_build ({len(pending)})[/yellow]: {escape(names)}")

    for r in drifted:
        render_error_panel(r.name, escape("\n".join(r.issues)), border_style="red")

    for r in unknown:
        render_error_panel(
            r.name,
            escape("\n".join(r.issues) or "unknown state"),
            border_style="yellow",
        )

    if drifted:
        console.print(f"\n[red]✗ {len(drifted)} package(s) drifted from canonical stanza[/red]")
    if unknown:
        console.print(f"[yellow]⚠ {len(unknown)} package(s) in unknown state[/yellow]")

    if strict and pending:
        console.print(f"[red]✗ strict mode: {len(pending)} package(s) not yet on uv_build[/red]")

    hard_fail = bool(drifted) or bool(unknown) or (strict and bool(pending))
    return not hard_fail
