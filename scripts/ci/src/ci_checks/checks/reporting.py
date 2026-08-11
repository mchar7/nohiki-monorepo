"""Durable lint and dependency deprecation reporting for GitHub Actions."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, cast
from urllib.parse import unquote, urlsplit

import typer
from rich.console import Console

from ci_checks.checks.tests import (
    _UNIT_TEST_MARKERS,
    _load_testable_packages,
    run_tests_parallel,
)

_SUMMARY_LIMIT = 40
_DEPRECATION_LABEL = "dependency-deprecation"
_DEPRECATION_TITLE = "Dependency deprecation diagnostics"
_DEPRECATION_MARKER = "<!-- dependency-deprecation-tracker -->"
_WARNING_PATTERN = re.compile(
    r"^(?P<path>.+?):(?P<line>\d+): (?P<category>PendingDeprecationWarning|DeprecationWarning): (?P<message>.+)$"
)
_FINDING_SET_PATTERN = re.compile(r"<!-- finding-set: ([0-9a-f]{64}) -->")
_ACTIONLINT_PARALLEL_MESSAGE = 'step must run script with "run" section or run action with "uses" section'


@dataclass(frozen=True, order=True, slots=True)
class LintFinding:
    """One normalized linter diagnostic."""

    tool: str
    rule: str
    path: str
    line: int
    message: str


@dataclass(frozen=True, order=True, slots=True)
class DeprecationFinding:
    """One normalized deprecation warning."""

    category: str
    site: str
    line: int
    message: str


@dataclass(frozen=True, order=True, slots=True)
class ActionlintDiagnostic:
    """One actionlint JSON diagnostic."""

    message: str
    path: str
    line: int
    column: int
    end_column: int
    kind: str


def _mapping(value: object) -> dict[str, object]:
    return cast(dict[str, object], value) if isinstance(value, dict) else {}


def _sequence(value: object) -> list[object]:
    return cast(list[object], value) if isinstance(value, list) else []


def _string(value: object, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _integer(value: object, default: int = 0) -> int:
    return value if isinstance(value, int) else default


def _markdown(value: str) -> str:
    return " ".join(value.split()).replace("|", "\\|").replace("`", "\\`")


def _actionlint_diagnostic(value: object) -> ActionlintDiagnostic:
    item = _mapping(value)
    return ActionlintDiagnostic(
        message=_string(item.get("message")),
        path=_string(item.get("filepath")),
        line=_integer(item.get("line")),
        column=_integer(item.get("column")),
        end_column=_integer(item.get("end_column")),
        kind=_string(item.get("kind"), "syntax-check"),
    )


def _is_native_parallel_diagnostic(diagnostic: ActionlintDiagnostic, workflow_lines: list[str]) -> bool:
    if (
        diagnostic.kind != "syntax-check"
        or diagnostic.message != _ACTIONLINT_PARALLEL_MESSAGE
        or diagnostic.path != ".github/workflows/checks.yml"
        or diagnostic.line < 1
    ):
        return False
    try:
        source_line = workflow_lines[diagnostic.line - 1]
    except IndexError:
        return False
    return source_line.strip() == "- parallel:"


def convert_actionlint_sarif(input_path: Path, output_path: Path, repository_root: Path) -> int:
    """Convert actionlint JSON while suppressing only the runner-native parallel nodes."""
    diagnostics = [
        _actionlint_diagnostic(value) for value in _sequence(json.loads(input_path.read_text(encoding="utf-8")))
    ]
    try:
        workflow_lines = (repository_root / ".github/workflows/checks.yml").read_text(encoding="utf-8").splitlines()
    except OSError:
        workflow_lines = []
    reportable = [
        diagnostic for diagnostic in diagnostics if not _is_native_parallel_diagnostic(diagnostic, workflow_lines)
    ]
    results = [
        {
            "ruleId": diagnostic.kind,
            "level": "error",
            "message": {"text": diagnostic.message},
            "locations": [
                {
                    "physicalLocation": {
                        "artifactLocation": {
                            "uri": _display_path(diagnostic.path, repository_root),
                            "uriBaseId": "%SRCROOT%",
                        },
                        "region": {
                            "startLine": diagnostic.line,
                            "startColumn": diagnostic.column,
                            "endColumn": diagnostic.end_column,
                        },
                    }
                }
            ],
        }
        for diagnostic in reportable
    ]
    document = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "actionlint",
                        "informationUri": "https://github.com/rhysd/actionlint",
                    }
                },
                "results": results,
            }
        ],
    }
    output_path.write_text(json.dumps(document, separators=(",", ":")), encoding="utf-8")
    return len(reportable)


def actionlint_report_cmd(
    input_path: Annotated[Path, typer.Option("--input", help="actionlint JSON report")],
    output_path: Annotated[Path, typer.Option("--output", help="SARIF output file")],
    repository_root: Annotated[Path, typer.Option("--repository-root", help="Checked-out repository root")] = Path(),
) -> None:
    """Convert actionlint JSON to SARIF and retain its blocking verdict."""
    if convert_actionlint_sarif(input_path, output_path, repository_root):
        raise typer.Exit(1)


def _sarif_findings(path: Path, repository_root: Path) -> list[LintFinding]:
    """Read normalized findings from one SARIF document."""
    try:
        document = _mapping(json.loads(path.read_text(encoding="utf-8")))
    except OSError, json.JSONDecodeError:
        return []

    findings: list[LintFinding] = []
    for raw_run in _sequence(document.get("runs")):
        run = _mapping(raw_run)
        driver = _mapping(_mapping(run.get("tool")).get("driver"))
        tool = _string(driver.get("name"), path.stem)
        for raw_result in _sequence(run.get("results")):
            result = _mapping(raw_result)
            location = _mapping(_sequence(result.get("locations"))[0]) if _sequence(result.get("locations")) else {}
            physical = _mapping(location.get("physicalLocation"))
            artifact = _mapping(physical.get("artifactLocation"))
            region = _mapping(physical.get("region"))
            message = _string(_mapping(result.get("message")).get("text"))
            findings.append(
                LintFinding(
                    tool=tool,
                    rule=_string(result.get("ruleId"), "diagnostic"),
                    path=_display_path(_string(artifact.get("uri"), "workspace"), repository_root),
                    line=_integer(region.get("startLine")),
                    message=message,
                )
            )
    return findings


def render_lint_summary(directory: Path, repository_root: Path | None = None) -> str:
    """Render a compact, deduplicated table for native and summary-only reports."""
    repository_root = repository_root or Path.cwd()
    sarif_paths = sorted(directory.glob("*.sarif"))
    log_paths = sorted(directory.glob("*.log"))
    if not sarif_paths and not log_paths:
        return "### Lint diagnostics\n\nNo lint diagnostic reports were produced.\n"

    findings = sorted({finding for path in sarif_paths for finding in _sarif_findings(path, repository_root)})
    lines = ["### Lint diagnostics", ""]
    if findings:
        lines.extend(("| Tool | Rule | Location | Finding |", "|---|---|---|---|"))
        for finding in findings:
            location = f"{finding.path}:{finding.line}" if finding.line else finding.path
            lines.append(
                f"| {_markdown(finding.tool)} | `{_markdown(finding.rule)}` | "
                f"`{_markdown(location)}` | {_markdown(finding.message)} |"
            )
    else:
        lines.append(f"{len(sarif_paths)} machine-readable report(s), no findings.")

    log_findings = sorted(
        {
            (path.stem, _markdown(line))
            for path in log_paths
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
            if line.strip()
        }
    )
    if log_findings:
        lines.extend(("", "#### Summary-only tools", "", "| Tool | Finding |", "|---|---|"))
        for tool, finding in log_findings[:_SUMMARY_LIMIT]:
            lines.append(f"| `{_markdown(tool)}` | {finding} |")
        if len(log_findings) > _SUMMARY_LIMIT:
            lines.extend(("", f"{len(log_findings) - _SUMMARY_LIMIT} additional lines remain in the step log."))
    return "\n".join(lines) + "\n"


def lint_report_cmd(
    directory: Annotated[
        Path,
        typer.Option("--directory", help="Directory containing .sarif and failure-only .log reports"),
    ],
    summary: Annotated[Path, typer.Option("--summary", help="$GITHUB_STEP_SUMMARY file")],
) -> None:
    """Append compact lint findings to a GitHub step summary."""
    with summary.open("a", encoding="utf-8") as output:
        output.write(render_lint_summary(directory, Path.cwd()))


def _display_path(raw_path: str, repository_root: Path) -> str:
    parsed = urlsplit(raw_path)
    path = unquote(parsed.path) if parsed.scheme == "file" else raw_path
    path = path.replace("\\", "/")
    for package_directory in ("site-packages", "dist-packages"):
        marker = f"/{package_directory}/"
        if marker in f"/{path.lstrip('/')}":
            return f"{package_directory}/{path.split(marker, 1)[1]}"

    root = repository_root.resolve()
    candidate = Path(path)
    resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    try:
        relative = resolved.relative_to(root).as_posix()
    except ValueError:
        name = Path(path).name
        return f"external/{name}" if name else "external/path"
    return relative or "."


def _normalize_warning_site(raw_path: str, repository_root: Path) -> str:
    return _display_path(raw_path, repository_root)


def parse_deprecation_findings(output: str, repository_root: Path) -> list[DeprecationFinding]:
    """Parse and deduplicate pytest's warnings summary."""
    findings: set[DeprecationFinding] = set()
    for line in output.splitlines():
        if match := _WARNING_PATTERN.match(line.strip()):
            findings.add(
                DeprecationFinding(
                    category=match["category"],
                    site=_normalize_warning_site(match["path"], repository_root),
                    line=int(match["line"]),
                    message=match["message"],
                )
            )
    return sorted(findings)


def _render_deprecation_table(findings: list[DeprecationFinding]) -> list[str]:
    lines = ["| Class | Site | Finding |", "|---|---|---|"]
    lines.extend(
        f"| `{finding.category}` | `{_markdown(finding.site)}:{finding.line}` | {_markdown(finding.message)} |"
        for finding in findings[:_SUMMARY_LIMIT]
    )
    if not findings:
        lines.append("| - | - | No deprecation findings |")
    elif len(findings) > _SUMMARY_LIMIT:
        lines.append(f"| - | - | {len(findings) - _SUMMARY_LIMIT} additional deduplicated findings |")
    return lines


def render_deprecation_summary(findings: list[DeprecationFinding], failed_packages: list[str]) -> str:
    """Render the scheduled report-only sweep summary."""
    lines = ["### Dependency deprecation sweep", "", *_render_deprecation_table(findings), ""]
    status = (
        "all test suites completed"
        if not failed_packages
        else f"test failures ignored (report-only): {', '.join(failed_packages)}"
    )
    lines.append(f"{len(findings)} deduplicated finding(s); {status}.")
    return "\n".join(lines) + "\n"


def _finding_set(findings: list[DeprecationFinding]) -> str:
    payload = json.dumps(
        [(finding.category, finding.site, finding.line, finding.message) for finding in findings],
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _gh(*args: str) -> str:
    completed = subprocess.run(["gh", *args], capture_output=True, text=True, check=False)
    if completed.returncode:
        message = completed.stderr.strip() or completed.stdout.strip() or "gh failed"
        raise RuntimeError(message)
    return completed.stdout


def _issue_body(findings: list[DeprecationFinding], run_url: str, finding_set: str) -> str:
    lines = [
        _DEPRECATION_MARKER,
        "Tracks time-triggered dependency deprecations reported by the scheduled test sweep.",
        "The sweep is report-only; normal pull request checks retain their configured warning policy.",
        "",
        *_render_deprecation_table(findings),
        "",
        f"Last changed finding set: {run_url}",
        f"<!-- finding-set: {finding_set} -->",
    ]
    return "\n".join(lines)


def _deprecation_issue(repository: str) -> dict[str, object]:
    raw = _gh(
        "issue",
        "list",
        "--repo",
        repository,
        "--label",
        _DEPRECATION_LABEL,
        "--state",
        "all",
        "--limit",
        "100",
        "--json",
        "number,state,title,body",
    )
    trackers = [
        issue
        for value in _sequence(json.loads(raw))
        if (issue := _mapping(value))
        and (_string(issue.get("title")) == _DEPRECATION_TITLE or _DEPRECATION_MARKER in _string(issue.get("body")))
    ]
    if len(trackers) > 1:
        numbers = ", ".join(
            str(_integer(issue.get("number")))
            for issue in sorted(trackers, key=lambda item: _integer(item.get("number")))
        )
        message = f"multiple dependency deprecation trackers found: {numbers}"
        raise RuntimeError(message)
    return trackers[0] if trackers else {}


def _create_deprecation_issue(repository: str, body: str) -> None:
    _gh(
        "label",
        "create",
        _DEPRECATION_LABEL,
        "--repo",
        repository,
        "--force",
        "--color",
        "D4C5F9",
        "--description",
        "Time-triggered dependency deprecation diagnostics",
    )
    _gh(
        "issue",
        "create",
        "--repo",
        repository,
        "--title",
        _DEPRECATION_TITLE,
        "--label",
        _DEPRECATION_LABEL,
        "--body",
        body,
    )


def _update_deprecation_issue(
    repository: str,
    issue: dict[str, object],
    findings: list[DeprecationFinding],
    body: str,
    finding_set: str,
) -> None:
    number = str(_integer(issue.get("number")))
    previous = _FINDING_SET_PATTERN.search(_string(issue.get("body")))
    if previous is None or previous.group(1) != finding_set:
        _gh("issue", "edit", number, "--repo", repository, "--body", body)

    state = _string(issue.get("state")).upper()
    if findings and state == "CLOSED":
        _gh("issue", "reopen", number, "--repo", repository)
    elif not findings and state == "OPEN":
        _gh("issue", "close", number, "--repo", repository, "--reason", "completed")


def sync_deprecation_issue(repository: str, findings: list[DeprecationFinding], run_url: str) -> None:
    """Create or update the single tracking issue only when its finding set changes."""
    issue = _deprecation_issue(repository)
    if not issue and not findings:
        return

    finding_set = _finding_set(findings)
    body = _issue_body(findings, run_url, finding_set)
    if not issue:
        _create_deprecation_issue(repository, body)
        return
    _update_deprecation_issue(repository, issue, findings, body, finding_set)


def deprecation_sweep_cmd(
    summary: Annotated[Path, typer.Option("--summary", help="$GITHUB_STEP_SUMMARY file")],
    repository: Annotated[str, typer.Option("--repository", envvar="GITHUB_REPOSITORY", help="GitHub owner/repo")],
    run_url: Annotated[str, typer.Option("--run-url", help="URL of the scheduled workflow run")],
    workers: Annotated[int, typer.Option("--workers", min=1, help="Maximum pytest-xdist workers")] = 2,
) -> None:
    """Run unit suites with deprecations visible, summarize them, and synchronize one issue."""
    packages = _load_testable_packages("all")
    results = asyncio.run(
        run_tests_parallel(
            packages,
            _UNIT_TEST_MARKERS,
            (
                "-W",
                "always::DeprecationWarning",
                "-W",
                "always::PendingDeprecationWarning",
            ),
            workers,
            Console(),
            ci_mode=True,
            with_coverage=False,
        )
    )
    findings = parse_deprecation_findings("\n".join(result.output for result in results), Path.cwd())
    failed_packages = sorted(result.name for result in results if not result.passed)
    with summary.open("a", encoding="utf-8") as output:
        output.write(render_deprecation_summary(findings, failed_packages))
    # An incomplete suite cannot prove that a disappeared finding is gone.
    if not failed_packages:
        sync_deprecation_issue(repository, findings, run_url)
