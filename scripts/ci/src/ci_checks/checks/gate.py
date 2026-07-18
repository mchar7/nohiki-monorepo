"""Change-gate CLI: diff the working tree and emit workflow outputs.

Thin I/O adapter over the pure engine in ``core.change_gate``. All policy
lives in ``core.change_rules``; all classification lives in the engine.
This module only runs git, writes $GITHUB_OUTPUT / $GITHUB_STEP_SUMMARY,
and prints the verdict.
"""

import subprocess
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from ci_checks.core.change_gate import (
    GateDecision,
    evaluate,
    render_outputs,
    render_summary,
    tests_matrix,
)
from ci_checks.core.packages import REPO_ROOT, Scope, load_packages_with_deps


def _diff_files(base_ref: str, head_ref: str) -> set[str]:
    """Return changed paths for merge-base(base, head)..head.

    Args:
        base_ref: Diff base commit.
        head_ref: Diff head commit.

    Returns:
        Repo-relative posix paths, deletions included.

    Raises:
        RuntimeError: If git cannot resolve the diff. Callers must treat
            this as "run everything", never as "nothing changed".
    """
    result = subprocess.run(
        ["git", "diff", "--name-only", "--no-renames", f"{base_ref}...{head_ref}"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )
    if result.returncode != 0:
        msg = f"git diff failed for {base_ref}...{head_ref}: {result.stderr.strip()}"
        raise RuntimeError(msg)
    return {line for line in result.stdout.splitlines() if line}


def _append(path: Path | None, text: str) -> None:
    if path is not None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(text)


COMMENT_MARKER = "<!-- nohiki-change-gate -->"


def gate_cmd(
    event: Annotated[str, typer.Option("--event", help="GitHub event name")],
    base_ref: Annotated[str, typer.Option("--base-ref", help="Diff base commit")] = "",
    head_ref: Annotated[str, typer.Option("--head-ref", help="Diff head commit")] = "HEAD",
    github_output: Annotated[Path | None, typer.Option("--github-output", help="$GITHUB_OUTPUT file")] = None,
    summary: Annotated[Path | None, typer.Option("--summary", help="$GITHUB_STEP_SUMMARY file")] = None,
    comment_file: Annotated[
        Path | None,
        typer.Option("--comment-file", help="Write a marker-prefixed PR comment body"),
    ] = None,
) -> None:
    """Compute lane activation for the current diff and emit workflow outputs.

    Args:
        event: GitHub event name; anything but pull_request forces full.
        base_ref: Base commit for the three-dot diff.
        head_ref: Head commit for the three-dot diff.
        github_output: Optional $GITHUB_OUTPUT path to append key=value lines.
        summary: Optional $GITHUB_STEP_SUMMARY path for the verdict table.
        comment_file: Optional path receiving the marker-prefixed verdict
            body for a sticky PR comment.
    """
    console = Console()
    packages = load_packages_with_deps(Scope.ALL)
    decision = GateDecision()

    if event != "pull_request":
        decision.force_full(f"event {event!r} always runs everything")
    elif not base_ref or set(base_ref) == {"0"}:
        decision.force_full("missing or null base ref")
    else:
        try:
            changed = _diff_files(base_ref, head_ref)
        except RuntimeError as exc:
            decision.force_full(str(exc))
        else:
            decision = evaluate(changed, packages)

    matrix = tests_matrix(decision, packages)
    outputs = render_outputs(decision, matrix, event)
    _append(github_output, "".join(f"{key}={value}\n" for key, value in outputs.items()))
    text = render_summary(decision, outputs, event, base_ref, head_ref)
    _append(summary, text)
    if comment_file is not None:
        comment_file.write_text(f"{COMMENT_MARKER}\n{text}", encoding="utf-8")
    console.print(text)
