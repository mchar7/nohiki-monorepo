"""Dead code detection check using Skylos.

This module runs a single repo-root Skylos analysis and then groups findings by
workspace package for CI output. Running one holistic graph analysis avoids the
cross-package false positives that package-isolated scans introduce.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import cast

from ci_checks.core.display import console, render_error_panel, render_summary_table
from ci_checks.core.packages import REPO_ROOT, Package
from ci_checks.core.process_env import sanitized_python_env


@dataclass(frozen=True, slots=True)
class DeadCodeFinding:
    """Single dead code finding reported by Skylos."""

    name: str
    file: str
    line: int
    kind: str
    confidence: int
    message: str


@dataclass(slots=True)
class DeadCodeResult:
    """Scan result carrying per-package Skylos findings."""

    name: str
    passed: bool
    duration_ms: int = 0
    error: str = ""
    findings: list[DeadCodeFinding] = field(default_factory=list)


class SeverityLevel(StrEnum):
    """Supported Skylos severity filters."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(frozen=True, slots=True)
class DeadCodeScanOptions:
    """Skylos command options for dead-code scanning."""

    confidence: int
    llm: bool
    llm_model: str
    api_base: str | None
    verify: bool
    trace: bool
    gate: bool
    strict: bool
    baseline: bool
    provenance: bool
    no_provenance: bool
    provenance_base: str | None
    diff: str | None
    diff_base: str | None
    github: bool
    summary: bool
    severity: SeverityLevel | None
    file_filter: str | None
    limit: int | None
    no_grep_verify: bool
    include_tests: bool
    include_parameters: bool


def _load_skylos_json(raw: str) -> dict[str, object]:
    """Parse Skylos JSON from stdout.

    Args:
        raw: Raw stdout text emitted by Skylos.

    Returns:
        Parsed JSON object; empty dict if parsing fails.
    """
    if not raw.strip():
        return {}

    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        pass

    start_index = raw.find("{")
    if start_index < 0:
        return {}

    try:
        data = json.loads(raw[start_index:])
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _parse_skylos_json(raw: str) -> list[DeadCodeFinding]:
    """Parse Skylos JSON output into structured findings.

    Args:
        raw: Raw JSON string from Skylos stdout.

    Returns:
        List of parsed findings; empty list on JSON parse error.
    """
    data = _load_skylos_json(raw)
    if not data:
        return []

    def _as_str(value: object, default: str) -> str:
        return value if isinstance(value, str) else default

    def _as_int(value: object, default: int) -> int:
        return value if isinstance(value, int) else default

    findings: list[DeadCodeFinding] = []
    for key, value in data.items():
        if not key.startswith("unused_") or not isinstance(value, list):
            continue

        kind = key.removeprefix("unused_").removesuffix("s")
        for item in value:
            if not isinstance(item, dict):
                continue

            payload = cast("dict[str, object]", item)

            findings.append(
                DeadCodeFinding(
                    name=_as_str(payload.get("name"), "?"),
                    file=_as_str(payload.get("file"), "?"),
                    line=_as_int(payload.get("line"), 0),
                    kind=kind,
                    confidence=_as_int(payload.get("confidence"), 0),
                    message=_as_str(payload.get("message"), ""),
                )
            )

    return findings


def _relative_path(path: Path, *, repo_root: Path = REPO_ROOT) -> str:
    """Return a repository-relative string for a path.

    Args:
        path: Absolute or relative filesystem path.
        repo_root: Repository root used to relativize absolute paths.

    Returns:
        Relative path string when path is under repo_root; otherwise original.
    """
    return str(path.relative_to(repo_root) if path.is_absolute() and path.is_relative_to(repo_root) else path)


def _collect_scan_paths(
    packages: list[Package],
    *,
    include_tests: bool,
    repo_root: Path = REPO_ROOT,
) -> list[str]:
    """Collect tracked Python inputs for a deterministic Skylos scan.

    The repository index is the source-of-truth input contract. This includes
    staged additions while excluding ignored caches, virtual environments, and
    generated outputs regardless of what happens to exist in a worktree.

    Args:
        packages: Packages selected by scope.
        include_tests: Whether to include package tests directories.
        repo_root: Repository root whose index defines tracked inputs.

    Returns:
        Sorted unique repository-relative Python file paths.
    """
    roots: set[str] = set()
    for pkg in packages:
        roots.add(_relative_path(pkg.src_dir, repo_root=repo_root))
        if include_tests and pkg.has_tests:
            roots.add(_relative_path(pkg.tests_dir, repo_root=repo_root))

    if not roots:
        return []

    completed = subprocess.run(
        ["git", "ls-files", "--cached", "-z", "--", *sorted(roots)],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return sorted({path for path in completed.stdout.split("\0") if path.endswith(".py")})


def _build_skylos_cmd(scan_paths: list[str], options: DeadCodeScanOptions) -> list[str]:
    """Construct the uvx Skylos command for repo-root dead-code scanning.

    Args:
        scan_paths: Scope paths to analyze.
        options: Scan options.

    Returns:
        Command list suitable for asyncio.create_subprocess_exec.
    """
    cmd = [
        "uvx",
        # pin tool AND interpreter: fresh environments otherwise resolve
        # different versions and flip gate verdicts
        "--python",
        "3.14",
        "skylos==4.28.0",
        *scan_paths,
        "--json",
        "--category",
        "dead_code",
        f"--confidence={options.confidence}",
        # false-positive whitelist lives in [tool.skylos.whitelist]
        "--config-file",
        str(REPO_ROOT / "pyproject.toml"),
        "--no-upload",
        "--no-cache",
    ]

    if options.trace:
        cmd.append("--trace")
    if options.verify:
        cmd.append("--verify")
    if options.gate:
        cmd.append("--gate")
    if options.strict:
        cmd.append("--strict")
    if options.baseline:
        cmd.append("--baseline")
    if options.provenance:
        cmd.append("--provenance")
    if options.no_provenance:
        cmd.append("--no-provenance")
    if options.provenance_base:
        cmd.extend(["--provenance-base", options.provenance_base])
    if options.github:
        cmd.append("--github")
    if options.summary:
        cmd.append("--summary")
    if options.no_grep_verify:
        cmd.append("--no-grep-verify")
    if options.severity:
        cmd.extend(["--severity", options.severity.value])
    if options.file_filter:
        cmd.extend(["--file-filter", options.file_filter])
    if options.limit is not None:
        cmd.extend(["--limit", str(options.limit)])

    if options.diff:
        if options.diff == "auto":
            cmd.append("--diff")
        else:
            cmd.extend(["--diff", options.diff])

    if options.diff_base:
        cmd.extend(["--diff-base", options.diff_base])

    if options.llm:
        cmd.append("--llm")
        cmd.extend(["--model", options.llm_model])
        if options.api_base:
            cmd.extend(["--api-base", options.api_base])

    return cmd


def _package_for_file(file_path: str, packages: list[Package]) -> str | None:
    """Map a finding file path to a package name.

    Args:
        file_path: Finding file path from Skylos output.
        packages: Candidate workspace packages.

    Returns:
        Matching package name, or None when unmatched.
    """
    path = Path(file_path)
    if not path.is_absolute():
        path = REPO_ROOT / path

    for pkg in packages:
        if path.is_relative_to(pkg.path):
            return pkg.name
    return None


async def scan_scope(packages: list[Package], options: DeadCodeScanOptions) -> list[DeadCodeResult]:
    """Run Skylos once for scope and group findings by package.

    Args:
        packages: Scope-filtered packages.
        options: Dead code scan options.

    Returns:
        Per-package grouped scan results.
    """
    env = sanitized_python_env(extra={"OTEL_SDK_DISABLED": "true", "SKYLOS_GREP_BUDGET": "120"})
    if shutil.which("rg", path=env.get("PATH")) is None:
        return [
            DeadCodeResult(
                name="scanner-preflight",
                passed=False,
                error="ripgrep (rg) is required for deterministic Skylos grep verification",
            )
        ]
    scan_paths = _collect_scan_paths(packages, include_tests=options.include_tests)
    cmd = _build_skylos_cmd(scan_paths, options)

    start = asyncio.get_event_loop().time()
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=REPO_ROOT,
        env=env,
    )
    stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=600)
    duration_ms = int((asyncio.get_event_loop().time() - start) * 1000)

    findings = _parse_skylos_json(stdout_bytes.decode())
    if not options.include_parameters:
        findings = [finding for finding in findings if finding.kind != "parameter"]
    stderr = stderr_bytes.decode().strip()
    error_message = stderr if proc.returncode not in (0, 1) else ""

    findings_by_package: dict[str, list[DeadCodeFinding]] = {pkg.name: [] for pkg in packages}
    unmapped: list[DeadCodeFinding] = []

    for finding in findings:
        if pkg_name := _package_for_file(finding.file, packages):
            findings_by_package[pkg_name].append(finding)
        else:
            unmapped.append(finding)

    results = [
        DeadCodeResult(
            name=pkg.name,
            passed=len(findings_by_package[pkg.name]) == 0 and not error_message,
            duration_ms=duration_ms,
            findings=findings_by_package[pkg.name],
            error=error_message,
        )
        for pkg in packages
    ]

    if unmapped:
        results.append(
            DeadCodeResult(
                name="unmapped-findings",
                passed=False,
                duration_ms=duration_ms,
                findings=unmapped,
                error=error_message,
            )
        )

    return results


def render_results(results: list[DeadCodeResult], *, fail_on_findings: bool) -> bool:
    """Render the deadcode summary and per-package finding details.

    Args:
        results: All scan results to summarise.
        fail_on_findings: Whether findings count as a check failure.

    Returns:
        True if the check passed (no failure condition triggered).
    """
    total_findings = sum(len(r.findings) for r in results)
    clean_count = sum(1 for r in results if r.passed)
    dirty = [r for r in results if not r.passed]

    by_kind: dict[str, int] = {}
    for result in results:
        for finding in result.findings:
            by_kind[finding.kind] = by_kind.get(finding.kind, 0) + 1

    extra_rows = [(f"  [dim]{kind}[/dim]", str(count)) for kind, count in sorted(by_kind.items())]
    render_summary_table(
        "Dead Code Summary (Skylos)",
        clean_count=clean_count,
        failed_count=len(dirty),
        total_issues=total_findings,
        extra_rows=extra_rows,
    )

    for result in dirty:
        lines = [f"  [{f.kind}] {f.name} @ {f.file}:{f.line} (confidence={f.confidence}%)" for f in result.findings]
        render_error_panel(
            f"{result.name} ({len(result.findings)} findings)",
            "\n".join(lines),
            border_style="yellow",
        )

    error_pkgs = [r for r in results if r.error]
    if error_pkgs:
        console.print(f"\n[red]⚠ {len(error_pkgs)} package(s) had errors during analysis[/red]")
        for r in error_pkgs:
            console.print(f"  [red]{r.name}:[/red] {r.error[:200]}")

    # analysis errors must fail the gate: zero findings from a broken run is
    # not a clean verdict
    return not (fail_on_findings and (total_findings > 0 or any(r.error for r in results)))
