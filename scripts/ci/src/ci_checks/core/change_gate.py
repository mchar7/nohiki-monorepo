"""Change-gate engine: pure evaluation of a diff against the gating policy.

No subprocess, filesystem writes, or environment access: every function is
a deterministic mapping from inputs to a decision, so the whole engine is
unit-testable without git or GitHub.
"""

import json
from dataclasses import dataclass, field
from urllib.parse import quote

from ci_checks.core.change_rules import (
    API_EXPORT_SERVICES,
    FLAG_NAMES,
    GLOBAL_TRIGGERS,
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
from ci_checks.core.test_batches import load_test_batches

_BACKEND_TYPES: frozenset[PackageType] = frozenset({PackageType.SERVICE, PackageType.LIB, PackageType.JOB})


@dataclass(slots=True)
class GateDecision:
    """Computed lane activation for one diff."""

    full: bool = False
    reasons: list[str] = field(default_factory=list)
    flags: set[str] = field(default_factory=set)
    affected: set[str] = field(default_factory=set)
    unmatched: list[str] = field(default_factory=list)

    def force_full(self, reason: str) -> None:
        """Switch to a full run, recording why."""
        self.full = True
        self.reasons.append(reason)

    def flag_value(self, flag: str) -> bool:
        """Effective value of a lane flag (full run activates everything)."""
        return self.full or flag in self.flags


def _matches_global(path: str) -> bool:
    import fnmatch

    return any(path == pattern or fnmatch.fnmatch(path, pattern) for pattern in GLOBAL_TRIGGERS)


def _package_rel_paths(packages: dict[str, Package]) -> dict[str, str]:
    return {name: pkg.path.relative_to(REPO_ROOT).as_posix() for name, pkg in packages.items()}


def _owning_package(path: str, rel_paths: dict[str, str]) -> str | None:
    for name, rel in rel_paths.items():
        if path == rel or path.startswith(f"{rel}/"):
            return name
    return None


def evaluate(changed: set[str], packages: dict[str, Package]) -> GateDecision:
    """Classify changed files into lane flags and affected packages.

    Args:
        changed: Repo-relative posix paths from the diff. Deleted paths are
            valid inputs; nothing here touches the filesystem.
        packages: Workspace packages with dependency metadata populated.

    Returns:
        The gate decision. ``full`` is set when any file hits a global
        trigger or is understood by no rule (fail-closed).
    """
    decision = GateDecision()
    rel_paths = _package_rel_paths(packages)
    seeds: set[str] = set()

    for path in sorted(changed):
        if _matches_global(path):
            decision.force_full(f"global trigger: {path}")
            continue

        matched = False
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
            # unmatched standalone files still fall through to the full run.
            decision.flags.add("lint_python")

        if not matched:
            decision.unmatched.append(path)
            decision.force_full(f"unmatched file: {path}")

    decision.affected = expand_to_dependents(seeds, build_reverse_dependency_index(packages))
    _derive_package_flags(decision, packages)
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


def tests_matrix(decision: GateDecision, packages: dict[str, Package]) -> dict[str, list[dict[str, str | bool]]]:
    """Build the duration-balanced python-tests strategy matrix.

    Args:
        decision: Evaluated gate decision.
        packages: Workspace packages keyed by name.

    Returns:
        A GitHub Actions matrix object containing the affected portion of each
        committed batch, or all three complete batches for a full run.

    Raises:
        ValueError: If the committed batches do not partition the workspace.
    """
    if not decision.full and not decision.affected:
        return {"include": []}
    batches = load_test_batches()
    assigned = [name for batch in batches for name in batch.packages]
    workspace = set(packages)
    if set(assigned) != workspace or len(assigned) != len(workspace):
        missing = sorted(workspace - set(assigned))
        extra = sorted(set(assigned) - workspace)
        duplicates = sorted(name for name in set(assigned) if assigned.count(name) > 1)
        msg = f"invalid Python test batch assignment: missing={missing}, extra={extra}, duplicates={duplicates}"
        raise ValueError(msg)

    include: list[dict[str, str | bool]] = []
    for batch in batches:
        names = sorted(
            name for name in batch.packages if packages[name].has_tests and (decision.full or name in decision.affected)
        )
        if names:
            include.append(
                {
                    "batch": batch.name,
                    "packages": ",".join(names),
                    "needs_pnpm": batch.needs_pnpm,
                }
            )
    return {"include": include}


def render_outputs(
    decision: GateDecision,
    matrix: dict[str, list[dict[str, str | bool]]],
    event: str,
) -> dict[str, str]:
    """Render the decision as $GITHUB_OUTPUT key/value pairs.

    Args:
        decision: Evaluated gate decision.
        matrix: Result of :func:`tests_matrix` for the same decision.
        event: GitHub event name (drives ``commitlint_expected``).

    Returns:
        Ordered mapping of output names to lowercase string values.
    """
    outputs: dict[str, str] = {"full": str(decision.full).lower()}
    for flag in FLAG_NAMES:
        outputs[flag] = str(decision.flag_value(flag)).lower()
    outputs["python_any"] = str(decision.full or bool(matrix["include"])).lower()
    outputs["tests_matrix"] = json.dumps(matrix, separators=(",", ":"))
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
        for prefix in ("global trigger: ", "unmatched file: "):
            if reason.startswith(prefix):
                return f"{prefix}{link_path(reason.removeprefix(prefix))}"
        return reason

    lines = [
        "## Change gate",
        "",
        f"- Event: `{event}`",
        f"- Diff: `{base_ref}...{head_ref}`",
        f"- Verdict: {'**full run**' if decision.full else 'scoped run'}",
    ]
    if decision.reasons:
        lines += ["", "**Full-run reasons:**"]
        lines.extend(f"- {render_reason(reason)}" for reason in decision.reasons)
    lines += ["", "| Lane | Run |", "|---|:---:|"]
    lines.extend(f"| {LANE_DISPLAY_NAMES[flag]} | {'✓' if outputs[flag] == 'true' else '—'} |" for flag in FLAG_NAMES)
    if not decision.full and decision.affected:
        lines += [
            "",
            f"Affected packages ({len(decision.affected)}): {', '.join(sorted(decision.affected))}",
        ]
    return "\n".join(lines) + "\n"
