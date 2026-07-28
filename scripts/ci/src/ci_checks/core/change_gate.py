"""Change-gate engine: pure evaluation of a diff against the gating policy.

No subprocess, filesystem writes, or environment access: every function is
a deterministic mapping from inputs to a decision, so the whole engine is
unit-testable without git or GitHub.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from urllib.parse import quote

from ci_checks.core.change_rules import (
    API_EXPORT_SERVICES,
    BROAD_PYTHON_FLAGS,
    BROAD_RULES,
    FLAG_NAMES,
    SURFACE_RULES,
)
from ci_checks.core.display import LANE_DISPLAY_NAMES, LANE_RUNNERS, markdown_details, markdown_table
from ci_checks.core.packages import (
    REPO_ROOT,
    Package,
    build_reverse_dependency_index,
    expand_to_dependents,
)


class CommitClass(StrEnum):
    """Amount of substantive work selected for a tested tree."""

    STANDARD = "standard"
    BROAD = "broad"


class BroadCause(StrEnum):
    """Structural origin of one broad-class verdict."""

    POLICY_SOURCE = "policy_source"
    UNMATCHED_PATH = "unmatched_path"
    MISSING_SHA = "missing_sha"
    UNSUPPORTED_EVENT = "unsupported_event"
    PROTECTED_MAIN_EVIDENCE = "protected_main_evidence"
    UNRESOLVED_DIFF = "unresolved_diff"


# A bounded cause is one whose matching rule already enumerates what it selects, so the
# blast radius is known. Every other cause leaves the affected surface undetermined.
_BOUNDED_CAUSES: frozenset[BroadCause] = frozenset({BroadCause.POLICY_SOURCE})


@dataclass(frozen=True, slots=True)
class BroadReason:
    """One recorded cause of a broad-class verdict."""

    cause: BroadCause
    text: str
    path: str | None = None

    @property
    def unbounded(self) -> bool:
        """Return whether this cause leaves the affected surface undetermined."""
        return self.cause not in _BOUNDED_CAUSES

    def __str__(self) -> str:
        """Return the human-readable text, so string consumers need no unwrapping."""
        return self.text


@dataclass(frozen=True, slots=True)
class ProtectedMainEvidence:
    """Repository and pull-request evidence for a protected-main smoke."""

    associated_pr_merged: bool
    merge_commit_sha: str
    checks_run_success: bool
    tested_tree_sha: str
    pushed_tree_sha: str

    def proves_broad_tree(self, head_sha: str) -> bool:
        """Return whether the successful Checks run tested the pushed tree."""
        return (
            self.associated_pr_merged
            and self.merge_commit_sha == head_sha
            and self.checks_run_success
            and bool(self.tested_tree_sha)
            and bool(self.pushed_tree_sha)
            and self.tested_tree_sha == self.pushed_tree_sha
        )


@dataclass(frozen=True, slots=True)
class EventContext:
    """GitHub event identity used by fail-closed commit classification."""

    event: str
    base_sha: str
    head_sha: str
    ref_name: str = ""
    protected_main: ProtectedMainEvidence | None = None


@dataclass(slots=True)
class GateDecision:
    """Computed lane activation for one diff."""

    full: bool = False
    reasons: list[BroadReason] = field(default_factory=list)
    flags: set[str] = field(default_factory=set)
    affected: set[str] = field(default_factory=set)
    unmatched: list[str] = field(default_factory=list)
    protected_main_smoke: bool = False

    @property
    def commit_class(self) -> CommitClass:
        """Return the workflow topology selected by this decision."""
        return CommitClass.BROAD if self.full else CommitClass.STANDARD

    @property
    def broad_unbounded(self) -> bool:
        """Return whether a broad verdict rests on a cause with an undetermined blast radius."""
        return self.full and any(reason.unbounded for reason in self.reasons)

    def force_full(
        self,
        reason: str,
        cause: BroadCause = BroadCause.UNRESOLVED_DIFF,
        path: str | None = None,
    ) -> None:
        """Select the broad class, recording why.

        Args:
            reason: Human-readable text for the step summary.
            cause: Structural origin, which fixes whether the cause is bounded.
            path: Repo-relative path for the path-bearing causes.
        """
        self.full = True
        self.reasons.append(BroadReason(cause, reason, path))

    def flag_value(self, flag: str) -> bool:
        """Return whether a lane is selected independently of commit class."""
        return flag in self.flags


def _usable_sha(sha: str) -> bool:
    return bool(sha) and set(sha) != {"0"}


def _package_rel_paths(packages: dict[str, Package]) -> dict[str, str]:
    return {name: pkg.path.relative_to(REPO_ROOT).as_posix() for name, pkg in packages.items()}


def _owning_package(path: str, rel_paths: dict[str, str]) -> str | None:
    for name, rel in rel_paths.items():
        if path == rel or path.startswith(f"{rel}/"):
            return name
    return None


def _apply_event_context(decision: GateDecision, context: EventContext) -> None:
    if not _usable_sha(context.base_sha):
        decision.flags.update(BROAD_PYTHON_FLAGS)
        decision.force_full("missing or null base ref", BroadCause.MISSING_SHA)
        return
    if not _usable_sha(context.head_sha):
        decision.flags.update(BROAD_PYTHON_FLAGS)
        decision.force_full("missing or null tested SHA", BroadCause.MISSING_SHA)
        return

    match context.event:
        case "pull_request":
            return
        case "push":
            evidence = context.protected_main
            if context.ref_name == "main" and evidence is not None and evidence.proves_broad_tree(context.head_sha):
                decision.full = False
                decision.protected_main_smoke = True
                decision.reasons.clear()
                return
            decision.flags.update(BROAD_PYTHON_FLAGS)
            decision.force_full(
                "protected-main smoke evidence is missing or mismatched",
                BroadCause.PROTECTED_MAIN_EVIDENCE,
            )
        case _:
            decision.flags.update(BROAD_PYTHON_FLAGS)
            decision.force_full(f"event {context.event!r} selects broad", BroadCause.UNSUPPORTED_EVENT)


def evaluate(
    changed: set[str],
    packages: dict[str, Package],
    context: EventContext | None = None,
) -> GateDecision:
    """Classify changed files into lane flags, packages, and commit class.

    Args:
        changed: Repo-relative posix paths from the base-SHA-to-tested-SHA
            diff. Deleted paths are valid inputs.
        packages: Workspace packages with dependency metadata populated.
        context: Optional GitHub event identity. Local callers may omit it;
            workflow callers fail closed from incomplete event evidence.

    Returns:
        The gate decision. Policy sources and unmapped paths select ``broad``.
    """
    decision = GateDecision()
    rel_paths = _package_rel_paths(packages)
    seeds: set[str] = set()

    for path in sorted(changed):
        matched = False
        for rule in BROAD_RULES:
            if rule.matches(path):
                matched = True
                decision.flags.update(rule.flags)
                seeds.update(rule.packages)
                decision.force_full(f"broad policy source: {path}", BroadCause.POLICY_SOURCE, path)

        for rule in SURFACE_RULES:
            if rule.matches(path):
                matched = True
                decision.flags.update(rule.flags)
                seeds.update(rule.packages)

        if (owner := _owning_package(path, rel_paths)) is not None:
            matched = True
            seeds.add(owner)
            if path == f"{rel_paths[owner]}/pyproject.toml":
                decision.flags.update({"hygiene", "typecheck_backend"})
        if path.endswith(".py"):
            # Every changed Python file lints, workspace-owned or standalone;
            # unmatched standalone files still fall through to broad.
            decision.flags.add("lint_python")

        if not matched:
            decision.unmatched.append(path)
            decision.flags.update(BROAD_PYTHON_FLAGS)
            decision.force_full(f"unmatched file: {path}", BroadCause.UNMATCHED_PATH, path)

    decision.affected = expand_to_dependents(seeds, build_reverse_dependency_index(packages))
    _derive_package_flags(decision, packages)
    if context is not None:
        _apply_event_context(decision, context)
    if decision.full:
        decision.affected = set(packages)
    return decision


def _derive_package_flags(decision: GateDecision, packages: dict[str, Package]) -> None:
    """Set lane flags implied by the affected-package set."""
    if not decision.affected:
        return
    # lint_python stays file-driven (.py suffix in evaluate): dependents of
    # a changed lib have no changed source of their own to lint.
    #
    # typecheck_backend follows what the step reads, not what a package is called. It resolves
    # PACKAGE_SCOPE against the uv.lock editables, and the editable set is exactly the packages
    # carrying a src/ tree, so has_src selects the flag for every type ty reads and withholds it
    # from the one virtual member, whose empty path list would fail the step's non-empty guard.
    decision.flags |= {"python_any", "hygiene"}
    if any(packages[name].has_src for name in decision.affected if name in packages):
        decision.flags.add("typecheck_backend")
    if decision.affected & API_EXPORT_SERVICES:
        decision.flags.add("api_schema_freshness")


def selected_test_packages(decision: GateDecision, packages: dict[str, Package]) -> tuple[str, ...]:
    """Return the selected workspace packages that contain tests.

    Args:
        decision: Evaluated gate decision.
        packages: Workspace packages keyed by name.

    Returns:
        Every testable workspace package for a broad decision, otherwise the
        testable affected-package closure for a standard decision.
    """
    selected = packages.keys() if decision.full else decision.affected
    return tuple(sorted(name for name in selected if name in packages and packages[name].has_tests))


def render_outputs(
    decision: GateDecision,
    test_packages: tuple[str, ...],
    event: str,
) -> dict[str, str]:
    """Render the decision as $GITHUB_OUTPUT key/value pairs.

    Args:
        decision: Evaluated gate decision.
        test_packages: Selected testable package names.
        event: GitHub event name (drives ``commitlint_expected``).

    Returns:
        Ordered mapping of output names to lowercase string values.
    """
    outputs: dict[str, str] = {
        "commit_class": decision.commit_class.value,
        "standard": str(decision.commit_class is CommitClass.STANDARD).lower(),
        "broad": str(decision.commit_class is CommitClass.BROAD).lower(),
        # Splits the broad signal: true only when no rule enumerated the blast radius, so a
        # step that a bounded trigger cannot reach may stay skipped on the bounded half.
        "broad_unbounded": str(decision.broad_unbounded).lower(),
        "protected_main_smoke": str(decision.protected_main_smoke).lower(),
        # Gate labels consume the full spelling as the broad-class signal.
        "full": str(decision.full).lower(),
        "affected_packages": ",".join(sorted(decision.affected)),
        "test_packages": ",".join(test_packages),
    }
    for flag in FLAG_NAMES:
        outputs[flag] = str(decision.flag_value(flag)).lower()
    outputs["python_any"] = str(bool(test_packages)).lower()
    outputs["commitlint_expected"] = str(event == "pull_request").lower()
    return outputs


def render_summary(
    decision: GateDecision,
    outputs: dict[str, str],
    event: str,
    base_ref: str,
    head_ref: str,
    *,
    repository: str | None = None,
    head_sha: str | None = None,
) -> str:
    """Render the human-readable verdict for $GITHUB_STEP_SUMMARY.

    Args:
        decision: Evaluated gate decision.
        outputs: Result of :func:`render_outputs`.
        event: GitHub event name.
        base_ref: Diff base commit.
        head_ref: Diff head commit.
        repository: Optional GitHub ``owner/repo`` for changed-file links.
        head_sha: Optional commit SHA for changed-file links.

    Returns:
        Markdown for the gate block of the Router step summary, as a level-four
        section so it nests under the job's Results heading.
    """

    def link_path(path: str) -> str:
        if repository is None or head_sha is None:
            return f"`{path}`"
        url = f"https://github.com/{repository}/blob/{head_sha}/{quote(path, safe='/')}"
        return f"[`{path}`]({url})"

    def grouped(cause: BroadCause) -> list[str]:
        # Falling back to the text keeps a path-less reason visible rather than dropping it from
        # a group whose count is rendered.
        return [
            link_path(reason.path) if reason.path else reason.text
            for reason in decision.reasons
            if reason.cause is cause
        ]

    lines = ["#### Change gate", ""]
    lines += markdown_table(
        ["Verdict", "Value"],
        [
            ("Commit class", f"**{decision.commit_class}**"),
            ("Event", f"`{event}`"),
            ("Diff", f"`{base_ref}..{head_ref}`"),
        ],
    )

    unmatched = grouped(BroadCause.UNMATCHED_PATH)
    policy = grouped(BroadCause.POLICY_SOURCE)
    # Membership, not `path is None`: a future cause that gains a path must still be reported here
    # rather than silently vanish from every group.
    linked = {BroadCause.UNMATCHED_PATH, BroadCause.POLICY_SOURCE}
    other = [reason.text for reason in decision.reasons if reason.cause not in linked]
    # Unmatched leads: an unclassified path means the gate never decided about it and fell back to
    # broad, which is a stronger signal than a policy file doing exactly what policy says.
    groups = (
        (
            unmatched,
            f"**Unclassified paths ({len(unmatched)}).** No rule matches these, so the gate fails "
            "closed to broad instead of deciding:",
        ),
        (policy, f"**Broad policy sources ({len(policy)}).** Changing these selects every lane by policy:"),
        (other, f"**Other broad-class reasons ({len(other)}):**"),
    )
    for entries, heading in groups:
        if entries:
            lines += ["", heading, "", *(f"- {entry}" for entry in entries)]

    lines += [""]
    if decision.full:
        lines += ["Broad class selects every lane.", ""]
    lines += [
        "`Runs in` names the broad-class bin; a standard run executes every selected lane in the "
        "single `all` unit. Lane outcomes are not known at gate time and are reported by the "
        "`Checks` fan-in.",
        "",
    ]
    lines += markdown_table(
        ["Lane", "Selected", "Runs in"],
        [
            (
                LANE_DISPLAY_NAMES[flag],
                "✓" if decision.full or outputs[flag] == "true" else "—",
                LANE_RUNNERS[flag],
            )
            for flag in FLAG_NAMES
        ],
        align=("left", "center", "left"),
    )
    if not decision.full and decision.affected:
        affected = sorted(decision.affected)
        lines += [
            "",
            *markdown_details(
                f"Affected packages ({len(affected)})",
                ", ".join(f"`{name}`" for name in affected),
            ),
        ]
    return "\n".join(lines) + "\n"
