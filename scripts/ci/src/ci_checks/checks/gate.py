"""Change-gate CLI: diff the working tree and emit workflow outputs.

Thin I/O adapter over the pure engine in ``core.change_gate``. All policy
lives in ``core.change_rules``; all classification lives in the engine.
This module runs git/GitHub CLI commands and writes workflow output files.
"""

import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from ci_checks.core.change_gate import (
    EventContext,
    GateDecision,
    ProtectedMainEvidence,
    evaluate,
    render_outputs,
    render_summary,
    selected_test_packages,
)
from ci_checks.core.change_rules import FLAG_NAMES
from ci_checks.core.image_inventory import affected_images, load_inventory, write_affected_record
from ci_checks.core.packages import REPO_ROOT, Scope, load_packages_with_deps


def _diff_files(base_ref: str, head_ref: str) -> set[str]:
    """Return changed paths from the exact base SHA to the tested SHA.

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
        ["git", "diff", "--name-only", "--no-renames", f"{base_ref}..{head_ref}"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )
    if result.returncode != 0:
        msg = f"git diff failed for {base_ref}..{head_ref}: {result.stderr.strip()}"
        raise RuntimeError(msg)
    return {line for line in result.stdout.splitlines() if line}


def _append(path: Path | None, text: str) -> None:
    if path is not None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(text)


_EVIDENCE_ARTIFACT = "checks-attestation"
_EVIDENCE_MEMBER = "checks-attestation.json"


@dataclass(frozen=True, slots=True)
class _AssociatedPullRequest:
    number: int
    head_sha: str
    base_sha: str
    merge_commit_sha: str


@dataclass(frozen=True, slots=True)
class _CommitIdentity:
    tree_sha: str
    first_parent_sha: str


@dataclass(frozen=True, slots=True)
class _ChecksRun:
    run_id: int


@dataclass(frozen=True, slots=True)
class _Attestation:
    tested_tree_sha: str
    event_action: str
    commit_class: str
    run_id: int
    # Absent from every attestation written before the reuse short-circuit existed. Empty
    # never equals a real base SHA, so an old proof fails the reuse check closed.
    base_sha: str = ""


@dataclass(frozen=True, slots=True)
class _GateEvidence:
    associated_pr_merged: bool = False
    merge_commit_sha: str = ""
    checks_run_success: bool = False
    tested_tree_sha: str = ""
    pushed_tree_sha: str = ""

    def workflow_values(self) -> dict[str, str]:
        return {
            "CI_ASSOCIATED_PR_MERGED": str(self.associated_pr_merged).lower(),
            "CI_MERGE_COMMIT_SHA": self.merge_commit_sha,
            "CI_CHECKS_RUN_SUCCESS": str(self.checks_run_success).lower(),
            "CI_TESTED_TREE_SHA": self.tested_tree_sha,
            "CI_PUSHED_TREE_SHA": self.pushed_tree_sha,
        }


class _EvidenceError(RuntimeError):
    pass


class _AttestationUnavailableError(_EvidenceError):
    pass


def _json_object(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        return None
    return {key: item for key, item in value.items() if isinstance(key, str)}


def _run_gh(args: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            ["gh", *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        msg = f"gh {args[0]} could not run: {exc}"
        raise _EvidenceError(msg) from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or "no stderr"
        msg = f"gh {args[0]} failed with exit {result.returncode}: {detail}"
        raise _EvidenceError(msg)
    return result


def _gh_json(args: list[str]) -> object:
    result = _run_gh(args)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        msg = f"gh {args[0]} returned invalid JSON"
        raise _EvidenceError(msg) from exc


def _nested_string(value: object, *keys: str) -> str | None:
    current = value
    for key in keys:
        mapping = _json_object(current)
        if mapping is None:
            return None
        current = mapping.get(key)
    return current if isinstance(current, str) and current else None


def _associated_pull_request(payload: object, head_sha: str) -> _AssociatedPullRequest:
    if not isinstance(payload, list):
        msg = "associated pull-request response is not a list"
        raise _EvidenceError(msg)
    matches: list[_AssociatedPullRequest] = []
    for raw in payload:
        item = _json_object(raw)
        if item is None:
            continue
        number = item.get("number")
        merged_at = item.get("merged_at")
        merge_commit_sha = item.get("merge_commit_sha")
        pr_head_sha = _nested_string(item, "head", "sha")
        base_sha = _nested_string(item, "base", "sha")
        if (
            type(number) is int
            and isinstance(merged_at, str)
            and merged_at
            and merge_commit_sha == head_sha
            and pr_head_sha is not None
            and base_sha is not None
        ):
            matches.append(_AssociatedPullRequest(number, pr_head_sha, base_sha, head_sha))
    if len(matches) != 1:
        msg = f"expected one associated merged PR, found {len(matches)}"
        raise _EvidenceError(msg)
    return matches[0]


def _commit_identity(payload: object, head_sha: str) -> _CommitIdentity:
    item = _json_object(payload)
    if item is None or item.get("sha") != head_sha:
        msg = "pushed commit identity is missing or mismatched"
        raise _EvidenceError(msg)
    tree_sha = _nested_string(item, "commit", "tree", "sha")
    parents = item.get("parents")
    if tree_sha is None or not isinstance(parents, list) or not parents:
        msg = "pushed commit tree or first parent is missing"
        raise _EvidenceError(msg)
    first_parent_sha = _nested_string(parents[0], "sha")
    if first_parent_sha is None:
        msg = "pushed commit first parent SHA is missing"
        raise _EvidenceError(msg)
    return _CommitIdentity(tree_sha, first_parent_sha)


def _successful_runs(payload: object, pr_head_sha: str) -> list[_ChecksRun]:
    item = _json_object(payload)
    raw_runs = item.get("workflow_runs") if item is not None else None
    if not isinstance(raw_runs, list):
        msg = "Checks runs response has no workflow_runs list"
        raise _EvidenceError(msg)
    run_ids: list[int] = []
    for raw in raw_runs:
        run = _json_object(raw)
        if run is None:
            continue
        run_id = run.get("id")
        if (
            type(run_id) is int
            and run.get("name") == "Checks"
            and run.get("event") == "pull_request"
            and run.get("status") == "completed"
            and run.get("conclusion") == "success"
            and run.get("head_sha") == pr_head_sha
        ):
            run_ids.append(run_id)
    if len(run_ids) != len(set(run_ids)):
        msg = "Checks runs response contains duplicate run IDs"
        raise _EvidenceError(msg)
    return [_ChecksRun(run_id) for run_id in sorted(run_ids, reverse=True)]


def _download_attestation(repository: str, run_id: int) -> _Attestation:
    with tempfile.TemporaryDirectory(prefix="nohiki-checks-attestation-") as temp_dir:
        destination = Path(temp_dir)
        try:
            _run_gh(
                [
                    "run",
                    "download",
                    str(run_id),
                    "--repo",
                    repository,
                    "--name",
                    _EVIDENCE_ARTIFACT,
                    "--dir",
                    str(destination),
                ]
            )
        except _EvidenceError as exc:
            msg = f"run {run_id} has no downloadable {_EVIDENCE_ARTIFACT} artifact"
            raise _AttestationUnavailableError(msg) from exc
        members = list(destination.rglob(_EVIDENCE_MEMBER))
        if len(members) != 1:
            msg = f"run {run_id} yielded {len(members)} attestation members"
            raise _EvidenceError(msg)
        try:
            raw: object = json.loads(members[0].read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            msg = f"run {run_id} attestation is unreadable"
            raise _EvidenceError(msg) from exc
    item = _json_object(raw)
    if item is None:
        msg = f"run {run_id} attestation is not an object"
        raise _EvidenceError(msg)
    tested_tree_sha = item.get("tested_tree_sha")
    event_action = item.get("event_action")
    commit_class = item.get("commit_class")
    attested_run_id = item.get("run_id")
    base_sha = item.get("base_sha", "")
    if (
        not isinstance(tested_tree_sha, str)
        or not tested_tree_sha
        or not isinstance(event_action, str)
        or not event_action
        or not isinstance(commit_class, str)
        or commit_class not in {"standard", "broad"}
        or type(attested_run_id) is not int
        or not isinstance(base_sha, str)
    ):
        msg = f"run {run_id} attestation schema is invalid"
        raise _EvidenceError(msg)
    if attested_run_id != run_id:
        msg = f"run {run_id} attestation names run {attested_run_id}"
        raise _EvidenceError(msg)
    return _Attestation(tested_tree_sha, event_action, commit_class, run_id, base_sha)


def _extract_gate_evidence(repository: str, head_sha: str) -> _GateEvidence:
    pulls = _gh_json(["api", f"repos/{repository}/commits/{head_sha}/pulls", "--method", "GET"])
    pull_request = _associated_pull_request(pulls, head_sha)
    commit = _gh_json(["api", f"repos/{repository}/commits/{head_sha}", "--method", "GET"])
    identity = _commit_identity(commit, head_sha)
    if pull_request.base_sha != identity.first_parent_sha:
        msg = "associated PR base is not the pushed merge commit first parent"
        raise _EvidenceError(msg)
    runs = _gh_json(
        [
            "api",
            f"repos/{repository}/actions/workflows/checks.yml/runs",
            "--method",
            "GET",
            "-f",
            "event=pull_request",
            "-f",
            f"head_sha={pull_request.head_sha}",
            "-f",
            "per_page=100",
        ]
    )
    candidates = _successful_runs(runs, pull_request.head_sha)
    if not candidates:
        msg = "no successful canonical Checks runs found"
        raise _EvidenceError(msg)
    for candidate in candidates:
        try:
            attestation = _download_attestation(repository, candidate.run_id)
        except _AttestationUnavailableError:
            continue
        if attestation.event_action == "edited" or attestation.commit_class != "broad":
            continue
        return _GateEvidence(
            associated_pr_merged=True,
            merge_commit_sha=pull_request.merge_commit_sha,
            checks_run_success=True,
            tested_tree_sha=attestation.tested_tree_sha,
            pushed_tree_sha=identity.tree_sha,
        )
    msg = "no successful non-edited broad Checks attestation found"
    raise _EvidenceError(msg)


def gate_evidence_cmd(
    event: Annotated[str, typer.Option("--event", help="GitHub event name")],
    repository: Annotated[str, typer.Option("--repository", help="GitHub owner/repo")],
    head_sha: Annotated[str, typer.Option("--head-sha", help="Pushed commit SHA")],
    github_env: Annotated[Path, typer.Option("--github-env", help="$GITHUB_ENV file")],
) -> None:
    """Emit protected-main smoke evidence from GitHub run attestations.

    Args:
        event: GitHub event name.
        repository: GitHub repository in ``owner/repo`` form.
        head_sha: Pushed commit SHA.
        github_env: Environment file receiving the five fail-closed values.
    """
    evidence = _GateEvidence()
    if event == "push" and repository and head_sha:
        try:
            evidence = _extract_gate_evidence(repository, head_sha)
        except _EvidenceError as exc:
            Console().print(f"[yellow]Protected-main evidence unavailable: {exc}[/yellow]")
    _append(
        github_env,
        "".join(f"{name}={value}\n" for name, value in evidence.workflow_values().items()),
    )


def _head_tree_sha() -> str:
    """Return the tree SHA of the checked-out commit.

    Returns:
        The tree object name of ``HEAD``.

    Raises:
        _EvidenceError: If git cannot resolve the tree, which fails the proof closed.
    """
    result = subprocess.run(
        ["git", "rev-parse", "HEAD^{tree}"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )
    tree_sha = result.stdout.strip()
    if result.returncode != 0 or not tree_sha:
        msg = f"cannot resolve the checked-out tree: {result.stderr.strip() or 'no stderr'}"
        raise _EvidenceError(msg)
    return tree_sha


@dataclass(frozen=True, slots=True)
class _ReuseProof:
    """A prior run's proof that this exact tree and base were already checked."""

    proven: bool = False
    run_id: int = 0

    def workflow_values(self) -> dict[str, str]:
        """Return the outputs the job gates and the fan-in renderer consume.

        Returns:
            Mapping of output name to value; the run id is empty unless a proof was found.
        """
        return {
            "title_only": str(self.proven).lower(),
            "reused_run_id": str(self.run_id) if self.proven else "",
        }


def _prove_tree_already_checked(
    repository: str,
    pr_head_sha: str,
    tested_tree_sha: str,
    base_sha: str,
) -> _ReuseProof:
    """Find a successful non-edited run whose attestation covers this tree and this base.

    Args:
        repository: GitHub repository in ``owner/repo`` form.
        pr_head_sha: Head SHA of the pull request being edited.
        tested_tree_sha: Tree SHA of the merge commit under test.
        base_sha: Base SHA this run resolves its diff against.

    Returns:
        A proof naming the run that already covered this tree.

    Raises:
        _EvidenceError: If no candidate matches, so the caller runs the full suite.
    """
    runs = _gh_json(
        [
            "api",
            f"repos/{repository}/actions/workflows/checks.yml/runs",
            "--method",
            "GET",
            "-f",
            "event=pull_request",
            "-f",
            f"head_sha={pr_head_sha}",
            "-f",
            "per_page=100",
        ]
    )
    for candidate in _successful_runs(runs, pr_head_sha):
        try:
            attestation = _download_attestation(repository, candidate.run_id)
        except _AttestationUnavailableError:
            continue
        # An edited run's verdict is never proof: it may itself have been short-circuited.
        if attestation.event_action == "edited":
            continue
        # The tree fixes the content. The base fixes the diff, and with it the selected lane
        # set, the commit range and the proto baseline. Retargeting onto an ancestor of head
        # leaves the tree byte-identical, so the base is the only thing that catches it.
        if attestation.tested_tree_sha != tested_tree_sha or attestation.base_sha != base_sha:
            continue
        return _ReuseProof(proven=True, run_id=candidate.run_id)
    msg = "no successful non-edited attestation covers this tree and base"
    raise _EvidenceError(msg)


def gate_reuse_cmd(
    event: Annotated[str, typer.Option("--event", help="GitHub event name")],
    action: Annotated[str, typer.Option("--action", help="GitHub event action")],
    repository: Annotated[str, typer.Option("--repository", help="GitHub owner/repo")],
    pr_head_sha: Annotated[str, typer.Option("--pr-head-sha", help="Pull request head SHA")],
    base_sha: Annotated[str, typer.Option("--base-sha", help="Pull request base SHA")],
    github_output: Annotated[Path, typer.Option("--github-output", help="$GITHUB_OUTPUT file")],
) -> None:
    """Emit whether a prior run already proved the tree that an edit cannot have changed.

    Only a title or body edit reaches the positive case: the tree and the base must both match
    an earlier successful non-edited run. Every other path, an unreachable API and a retargeted
    base included, emits the negative pair so the full selected suite runs.

    Args:
        event: GitHub event name.
        action: GitHub event action.
        repository: GitHub repository in ``owner/repo`` form.
        pr_head_sha: Head SHA of the pull request.
        base_sha: Base SHA of the pull request.
        github_output: Output file receiving both values on every path.
    """
    proof = _ReuseProof()
    if event == "pull_request" and action == "edited" and repository and pr_head_sha and base_sha:
        try:
            proof = _prove_tree_already_checked(repository, pr_head_sha, _head_tree_sha(), base_sha)
        except _EvidenceError as exc:
            Console().print(f"[yellow]No reusable Checks proof: {exc}[/yellow]")
    _append(
        github_output,
        "".join(f"{name}={value}\n" for name, value in proof.workflow_values().items()),
    )


def gate_cmd(
    event: Annotated[str, typer.Option("--event", help="GitHub event name")],
    base_ref: Annotated[str, typer.Option("--base-ref", help="Diff base commit")] = "",
    head_ref: Annotated[str, typer.Option("--head-ref", help="Diff head commit")] = "HEAD",
    ref_name: Annotated[
        str,
        typer.Option("--ref-name", envvar="GITHUB_REF_NAME", help="GitHub short ref name"),
    ] = "",
    associated_pr_merged: Annotated[
        bool,
        typer.Option(envvar="CI_ASSOCIATED_PR_MERGED"),
    ] = False,
    checks_run_success: Annotated[
        bool,
        typer.Option(envvar="CI_CHECKS_RUN_SUCCESS"),
    ] = False,
    merge_commit_sha: Annotated[
        str,
        typer.Option(envvar="CI_MERGE_COMMIT_SHA"),
    ] = "",
    tested_tree_sha: Annotated[
        str,
        typer.Option(envvar="CI_TESTED_TREE_SHA"),
    ] = "",
    pushed_tree_sha: Annotated[
        str,
        typer.Option(envvar="CI_PUSHED_TREE_SHA"),
    ] = "",
    github_output: Annotated[Path | None, typer.Option("--github-output", help="$GITHUB_OUTPUT file")] = None,
    summary: Annotated[Path | None, typer.Option("--summary", help="$GITHUB_STEP_SUMMARY file")] = None,
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
        typer.Option("--affected-images-record", help="Push-only affected-image record to write"),
    ] = None,
) -> None:
    """Compute lane activation for the current diff and emit workflow outputs.

    Args:
        event: GitHub event name.
        base_ref: Exact base commit for the diff.
        head_ref: Tested commit for the diff.
        ref_name: GitHub short ref name.
        associated_pr_merged: Whether the associated PR is merged.
        checks_run_success: Whether its canonical Checks run succeeded.
        merge_commit_sha: Merge SHA recorded by the associated PR.
        tested_tree_sha: Tree SHA tested by the successful Checks run.
        pushed_tree_sha: Tree SHA of the pushed merge commit.
        github_output: Optional $GITHUB_OUTPUT path to append key=value lines.
        summary: Optional $GITHUB_STEP_SUMMARY path for the verdict table.
        repository: Optional GitHub ``owner/repo`` for changed-file links.
        affected_images_record: Optional push-only path for the SHA-bound affected-image record.

    Raises:
        typer.BadParameter: If the record is requested for anything but a push.
    """
    console = Console()
    packages = load_packages_with_deps(Scope.ALL)
    evidence = (
        ProtectedMainEvidence(
            associated_pr_merged=associated_pr_merged,
            merge_commit_sha=merge_commit_sha,
            checks_run_success=checks_run_success,
            tested_tree_sha=tested_tree_sha,
            pushed_tree_sha=pushed_tree_sha,
        )
        if event == "push"
        else None
    )
    context = EventContext(
        event=event,
        base_sha=base_ref,
        head_sha=head_ref,
        ref_name=ref_name,
        protected_main=evidence,
    )
    if affected_images_record is not None and event != "push":
        msg = "--affected-images-record is a push-only producer output"
        raise typer.BadParameter(msg)
    decision = GateDecision()
    # None means the changed set is unknown, which images treat as "build everything" while the
    # Checks classification keeps its own fail-closed verdict.
    changed: set[str] | None = None

    if not base_ref or set(base_ref) == {"0"}:
        decision = evaluate(set(), packages, context)
    else:
        try:
            changed = _diff_files(base_ref, head_ref)
        except RuntimeError as exc:
            decision.force_full(str(exc))
            decision.affected = set(packages)
            # An unresolved diff means the changed paths are unknown, so no rule can select
            # a lane. Class alone does not imply flags, and flag-only consumers (container
            # contracts, the Playwright image) would silently not run precisely when the
            # router knows least. Fail closed by selecting every lane.
            decision.flags.update(FLAG_NAMES)
        else:
            decision = evaluate(changed, packages, context)

    if affected_images_record is not None:
        inventory = load_inventory()
        names = inventory.names if changed is None else affected_images(changed, inventory)
        write_affected_record(affected_images_record, head_ref, names)

    selected_tests = selected_test_packages(decision, packages)
    outputs = render_outputs(decision, selected_tests, event)
    _append(
        github_output,
        "".join(f"{key}={value}\n" for key, value in outputs.items()),
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
    console.print(text)
