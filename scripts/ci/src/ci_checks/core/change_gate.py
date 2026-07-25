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
from ci_checks.core.display import LANE_DISPLAY_NAMES
from ci_checks.core.packages import (
    REPO_ROOT,
    Package,
    PackageType,
    build_reverse_dependency_index,
    expand_to_dependents,
)

_BACKEND_TYPES: frozenset[PackageType] = frozenset({PackageType.SERVICE, PackageType.LIB, PackageType.JOB})


class CommitClass(StrEnum):
    """Amount of substantive work selected for a tested tree."""

    STANDARD = "standard"
    BROAD = "broad"


# Worker runaway guards; the aggregator enforces class wall budgets.
WORKER_TIMEOUT_MINUTES: dict[CommitClass, int] = {
    commit_class: 18 if commit_class is CommitClass.BROAD else 9 for commit_class in CommitClass
}


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
    reasons: list[str] = field(default_factory=list)
    flags: set[str] = field(default_factory=set)
    affected: set[str] = field(default_factory=set)
    unmatched: list[str] = field(default_factory=list)
    protected_main_smoke: bool = False

    @property
    def commit_class(self) -> CommitClass:
        """Return the workflow topology selected by this decision."""
        return CommitClass.BROAD if self.full else CommitClass.STANDARD

    def force_full(self, reason: str) -> None:
        """Select the broad class, recording why."""
        self.full = True
        self.reasons.append(reason)

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
        decision.force_full("missing or null base ref")
        return
    if not _usable_sha(context.head_sha):
        decision.flags.update(BROAD_PYTHON_FLAGS)
        decision.force_full("missing or null tested SHA")
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
            decision.force_full("protected-main smoke evidence is missing or mismatched")
        case _:
            decision.flags.update(BROAD_PYTHON_FLAGS)
            decision.force_full(f"event {context.event!r} selects broad")


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
                decision.force_full(f"broad policy source: {path}")

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
            decision.force_full(f"unmatched file: {path}")

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
    decision.flags |= {"python_any", "hygiene"}
    if any(packages[name].pkg_type in _BACKEND_TYPES for name in decision.affected if name in packages):
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
        "worker_timeout_minutes": str(WORKER_TIMEOUT_MINUTES[decision.commit_class]),
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
        Markdown text with the verdict, reasons, lane table, and the
        affected-package list for scoped runs.
    """

    def link_path(path: str) -> str:
        if repository is None or head_sha is None:
            return f"`{path}`"
        url = f"https://github.com/{repository}/blob/{head_sha}/{quote(path, safe='/')}"
        return f"[`{path}`]({url})"

    def render_reason(reason: str) -> str:
        for prefix in ("broad policy source: ", "unmatched file: "):
            if reason.startswith(prefix):
                return f"{prefix}{link_path(reason.removeprefix(prefix))}"
        return reason

    lines = [
        "## Change gate",
        "",
        f"- Event: `{event}`",
        f"- Diff: `{base_ref}..{head_ref}`",
        f"- Verdict: **{decision.commit_class}**",
    ]
    if decision.reasons:
        lines += ["", "**Broad-class reasons:**"]
        lines.extend(f"- {render_reason(reason)}" for reason in decision.reasons)
    lines += ["", "| Lane | Run |", "|---|:---:|"]
    lines.extend(f"| {LANE_DISPLAY_NAMES[flag]} | {'✓' if outputs[flag] == 'true' else '—'} |" for flag in FLAG_NAMES)
    if not decision.full and decision.affected:
        lines += [
            "",
            f"Affected packages ({len(decision.affected)}): {', '.join(sorted(decision.affected))}",
        ]
    return "\n".join(lines) + "\n"
