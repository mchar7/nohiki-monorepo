"""Change-gate CLI: diff the working tree and emit workflow outputs.

Thin I/O adapter over the pure engine in ``core.change_gate``. All policy
lives in ``core.change_rules``; all classification lives in the engine.
This module only runs git, writes $GITHUB_OUTPUT / $GITHUB_STEP_SUMMARY,
and prints the verdict.
"""

import json
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
from ci_checks.core.display import GATE_LABELS
from ci_checks.core.image_inventory import (
    affected_images,
    image_names,
    load_inventory,
    write_affected_record,
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


def _label_output(outputs: dict[str, str]) -> str:
    labels = [{"name": name, "color": color, "active": outputs[flag]} for flag, (name, color) in GATE_LABELS.items()]
    return json.dumps(labels, separators=(",", ":"))


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
    repository: Annotated[
        str | None,
        typer.Option(
            "--repository",
            envvar="GITHUB_REPOSITORY",
            help="GitHub owner/repo for changed-file links",
        ),
    ] = None,
    affected_images_record: Annotated[
        Path | None,
        typer.Option(
            "--affected-images-record",
            help="Write the main-push affected-image artifact",
        ),
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
        repository: Optional GitHub ``owner/repo`` for changed-file links.
        affected_images_record: Optional path receiving ``{head_sha, images[]}``
            for a push event.
    """
    console = Console()
    packages = load_packages_with_deps(Scope.ALL)
    decision = GateDecision()
    changed: set[str] | None = None

    if (event == "pull_request" or affected_images_record is not None) and base_ref and set(base_ref) != {"0"}:
        try:
            changed = _diff_files(base_ref, head_ref)
        except RuntimeError as exc:
            decision.force_full(str(exc))

    if event != "pull_request":
        decision.force_full(f"event {event!r} always runs everything")
    elif changed is None:
        if not decision.full:
            decision.force_full("missing or null base ref")
    else:
        decision = evaluate(changed, packages)

    matrix = tests_matrix(decision, packages)
    outputs = render_outputs(decision, matrix, event)
    emitted_outputs = outputs | {"labels": _label_output(outputs)}
    if affected_images_record is not None:
        if event != "push":
            msg = "--affected-images-record is valid only for push events"
            raise ValueError(msg)
        images = load_inventory()
        names = image_names(images) if changed is None else affected_images(changed, images)
        write_affected_record(affected_images_record, head_ref, names)
    _append(
        github_output,
        "".join(f"{key}={value}\n" for key, value in emitted_outputs.items()),
    )
    text = render_summary(
        decision,
        outputs,
        event,
        base_ref,
        head_ref,
        repository=repository,
        head_sha=head_ref if repository is not None else None,
    )
    _append(summary, text)
    if comment_file is not None:
        comment_file.write_text(f"{COMMENT_MARKER}\n{text}", encoding="utf-8")
    console.print(text)
