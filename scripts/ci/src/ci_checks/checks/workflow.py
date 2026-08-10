"""GitHub Checks workflow rendering, verdict and accounting helpers."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

WARM_WALL_BUDGET_SECONDS = 8040
COLD_WALL_BUDGET_SECONDS = 8040


class RunnerClass(StrEnum):
    """Supported workflow runner classes."""

    TIER_1 = "nohiki-t1"
    TIER_2 = "nohiki-t2"
    TIER_3 = "nohiki-t3"
    HOSTED = "hosted"


class TierState(StrEnum):
    """Runner tier availability states."""

    ABSENT = "absent"
    BUSY = "busy"
    DRAINING = "draining"
    ELIGIBLE = "eligible"
    OFFLINE = "offline"
    UNAVAILABLE = "unavailable"
    UNTRUSTED = "untrusted"


class FallbackReason(StrEnum):
    """Reasons routing selected a hosted runner."""

    NONE = ""
    INVENTORY_UNAVAILABLE = "RUNNER_INVENTORY_TOKEN is unavailable"
    INVENTORY_UNTRUSTED = "runner inventory is untrusted"
    INVENTORY_REQUEST_FAILED = "runner inventory request failed"
    NO_ELIGIBLE_TIER = "no self-hosted tier is eligible"


_AUTOMATIC_LABELS = frozenset({"self-hosted", "Linux", "X64"})
_TIER_NAMES = {
    RunnerClass.TIER_1: frozenset(
        {
            "nohiki-runner-02",
            "nohiki-runner-03",
            "nohiki-runner-04",
            "nohiki-runner-05",
        }
    ),
    RunnerClass.TIER_2: frozenset({"nohiki-runner-06"}),
    RunnerClass.TIER_3: frozenset({"nohiki-runner-01"}),
}
_TIER_ORDER = tuple(_TIER_NAMES)
_MANAGED_LABELS = _AUTOMATIC_LABELS | frozenset({"nohiki", *_TIER_ORDER})
_RUNNER_NAME = re.compile(r"nohiki-runner-[0-9]{2}\Z")
_TIMEOUTS = {
    RunnerClass.TIER_1: (52, 30, 20, 5),
    RunnerClass.TIER_2: (52, 30, 20, 5),
    RunnerClass.TIER_3: (52, 30, 20, 5),
    RunnerClass.HOSTED: (30, 30, 10, 5),
}
_RUNNER_INVENTORY_ERRORS = (OSError, subprocess.CalledProcessError, ValueError)

_CACHE_KEY = re.compile(r"([0-9a-f]{8})[0-9a-f]{24,}")
_WORKER_COMMANDS = (
    ("nix", "frontend", "nix flake check; lefthook version"),
    ("lint_python", "frontend", "ruff check/format (whole tree on broad, changed files on standard)"),
    ("lint_markdown", "frontend", "markdownlint-cli2 (changed Markdown files)"),
    ("lint_proto", "frontend", "buf lint"),
    ("lint_workflows", "frontend", "actionlint; check-jsonschema"),
    ("lint_docker", "frontend", "hadolint (tracked Dockerfiles)"),
    ("lint_frontend", "frontend", "Biome; i18n:check"),
    ("lint_steiger", "frontend", "Steiger FSD architecture"),
    ("typecheck_backend", "python", "ty check native source surface"),
    ("typecheck_frontend", "frontend", "frontend type-check"),
    ("python_any", "python", "ci-checks tests affected package closure"),
    ("node_workspace_contracts", "frontend", "pytest -m requires_node_modules"),
    ("frontend_tests", "frontend", "frontend Vitest"),
    ("edge_worker", "frontend", "Biome; tsc; Vitest edge worker"),
    ("hygiene", "frontend", "ci-checks deptry --packages affected closure; Semgrep architecture scan"),
    ("build_backend", "frontend", "ci-checks build-backend --packages affected closure"),
    ("api_schema_freshness", "frontend", "just api-schema-check"),
    ("image_matrix_parity", "frontend", "just image-matrix-check"),
    ("proto_breaking", "frontend", "buf breaking"),
    ("commitlint_expected", "frontend", "commitlint PR range; commitlint PR title"),
    ("frontend_smoke", "frontend", "Buildx production frontend image; hardened-runtime container smoke"),
    ("otel_collector", "frontend", "OpenTelemetry collector image and rendered config validation"),
)


@dataclass(frozen=True, slots=True)
class WallTiming:
    """Wall-clock split used by the fan-in budget."""

    run_seconds: int
    controllable_seconds: int
    dispatch_seconds: int
    start_basis: str


@dataclass(frozen=True, slots=True)
class WallBudget:
    """Selected wall budget and the cache evidence behind it."""

    seconds: int
    classification: str
    basis: str


@dataclass(frozen=True, slots=True)
class Accounting:
    """Derived run accounting values."""

    timing: WallTiming
    budget: WallBudget
    avoided_minutes: int
    avoided_cost_usd: str
    reconstructed_hosted_minutes: int
    reconstructed_hosted_cost_usd: str
    jobs: tuple[Mapping[str, object], ...]


@dataclass(frozen=True, slots=True)
class RunnerRecord:
    """Trusted repository runner inventory record."""

    name: str
    status: str
    operating_system: str
    busy: bool
    labels: frozenset[str]


@dataclass(frozen=True, slots=True)
class RouteSelection:
    """One fail-closed runner decision shared by every payload job."""

    runner_target: str
    runner_class: RunnerClass
    tier_1_state: TierState
    tier_2_state: TierState
    tier_3_state: TierState
    selected_name: str
    fallback_reason: FallbackReason


def route_outputs(selection: RouteSelection) -> dict[str, str]:
    """Return the complete atomic workflow-output contract."""
    worker, playwright, title, checks = _TIMEOUTS[selection.runner_class]
    return {
        "runner_target": selection.runner_target,
        "runner_class": selection.runner_class,
        "tier_1_state": selection.tier_1_state,
        "tier_2_state": selection.tier_2_state,
        "tier_3_state": selection.tier_3_state,
        "worker_timeout_minutes": str(worker),
        "playwright_timeout_minutes": str(playwright),
        "title_timeout_minutes": str(title),
        "checks_timeout_minutes": str(checks),
    }


def _true(value: str | None) -> bool:
    return value == "true"


def _append(path: str | Path, text: str) -> None:
    with Path(path).open("a", encoding="utf-8") as handle:
        handle.write(text)


def _hosted_selection(reason: FallbackReason, *, state: TierState = TierState.UNAVAILABLE) -> RouteSelection:
    return RouteSelection(json.dumps("ubuntu-24.04"), RunnerClass.HOSTED, state, state, state, "", reason)


def _runner_record(raw: object) -> RunnerRecord:
    if not isinstance(raw, dict):
        msg = "runner inventory contains a malformed record"
        raise TypeError(msg)
    name = raw.get("name")
    status = raw.get("status")
    busy = raw.get("busy")
    operating_system = raw.get("os")
    raw_labels = raw.get("labels")
    if (
        not isinstance(name, str)
        or not isinstance(status, str)
        or status not in {"online", "offline"}
        or not isinstance(busy, bool)
        or not isinstance(operating_system, str)
        or not isinstance(raw_labels, list)
    ):
        msg = "runner inventory contains a malformed record"
        raise ValueError(msg)
    labels: list[str] = []
    for raw_label in raw_labels:
        if not isinstance(raw_label, dict):
            msg = "runner inventory contains a malformed label"
            raise TypeError(msg)
        label = raw_label.get("name")
        if not isinstance(label, str):
            msg = "runner inventory contains a malformed label"
            raise TypeError(msg)
        labels.append(label)
    if len(labels) != len(set(labels)):
        msg = "runner inventory contains duplicate labels"
        raise ValueError(msg)
    return RunnerRecord(name, status, operating_system, busy, frozenset(labels))


def _complete_inventory(raw_pages: object) -> tuple[RunnerRecord, ...]:
    if not isinstance(raw_pages, list) or not raw_pages:
        msg = "runner inventory response is incomplete"
        raise ValueError(msg)
    records: list[RunnerRecord] = []
    expected_total: int | None = None
    for raw_page in raw_pages:
        if not isinstance(raw_page, dict):
            msg = "runner inventory response is malformed"
            raise TypeError(msg)
        total = raw_page.get("total_count")
        raw_runners = raw_page.get("runners")
        if isinstance(total, bool) or not isinstance(total, int) or total < 0 or not isinstance(raw_runners, list):
            msg = "runner inventory response is malformed"
            raise ValueError(msg)
        if expected_total is None:
            expected_total = total
        elif total != expected_total:
            msg = "runner inventory total_count changed during pagination"
            raise ValueError(msg)
        records.extend(_runner_record(raw) for raw in raw_runners)
    if expected_total != len(records):
        msg = "runner inventory response is incomplete"
        raise ValueError(msg)
    names = [record.name for record in records]
    if len(names) != len(set(names)):
        msg = "runner inventory contains duplicate names"
        raise ValueError(msg)
    return tuple(records)


def _trusted_tiers(records: Sequence[RunnerRecord]) -> dict[RunnerClass, tuple[RunnerRecord, ...]]:
    tiers: dict[RunnerClass, tuple[RunnerRecord, ...]] = {}
    for tier in _TIER_ORDER:
        members = tuple(record for record in records if tier in record.labels)
        names = frozenset(record.name for record in members)
        if not names <= _TIER_NAMES[tier]:
            msg = f"{tier} ownership is not exact"
            raise ValueError(msg)
        if tier != "nohiki-t1" and len(members) > 1:
            msg = f"{tier} ownership is not unique"
            raise ValueError(msg)
        for member in members:
            if not _RUNNER_NAME.fullmatch(member.name):
                msg = "managed runner name is invalid"
                raise ValueError(msg)
            expected_labels = _AUTOMATIC_LABELS | {"nohiki", tier}
            if member.operating_system.casefold() != "linux" or member.labels != expected_labels:
                msg = f"{tier} member OS, architecture, or labels are invalid"
                raise ValueError(msg)
        tiers[tier] = tuple(sorted(members, key=lambda member: member.name))
    return tiers


def _tier_states(
    tiers: Mapping[RunnerClass, tuple[RunnerRecord, ...]], tier_2_drain: str
) -> dict[RunnerClass, TierState]:
    states: dict[RunnerClass, TierState] = {}
    tier_1 = tiers[RunnerClass.TIER_1]
    if any(runner.status == "online" and not runner.busy for runner in tier_1):
        states[RunnerClass.TIER_1] = TierState.ELIGIBLE
    elif any(runner.status == "online" for runner in tier_1):
        states[RunnerClass.TIER_1] = TierState.BUSY
    else:
        states[RunnerClass.TIER_1] = TierState.OFFLINE if tier_1 else TierState.ABSENT

    tier_2 = tiers[RunnerClass.TIER_2]
    if not tier_2:
        states[RunnerClass.TIER_2] = TierState.ABSENT
    elif tier_2_drain.casefold() == "true":
        states[RunnerClass.TIER_2] = TierState.DRAINING
    elif any(runner.status == "online" and not runner.busy for runner in tier_2):
        states[RunnerClass.TIER_2] = TierState.ELIGIBLE
    elif any(runner.status == "online" for runner in tier_2):
        states[RunnerClass.TIER_2] = TierState.BUSY
    else:
        states[RunnerClass.TIER_2] = TierState.OFFLINE

    tier_3 = tiers[RunnerClass.TIER_3]
    states[RunnerClass.TIER_3] = (
        TierState.ELIGIBLE
        if any(runner.status == "online" for runner in tier_3)
        else TierState.OFFLINE
        if tier_3
        else TierState.ABSENT
    )
    return states


def _pick_runner(
    tiers: Mapping[RunnerClass, tuple[RunnerRecord, ...]], states: Mapping[RunnerClass, TierState]
) -> tuple[RunnerClass, RunnerRecord] | None:
    for runner_class in (RunnerClass.TIER_1, RunnerClass.TIER_2):
        if states[runner_class] == TierState.ELIGIBLE:
            return runner_class, next(
                runner for runner in tiers[runner_class] if runner.status == "online" and not runner.busy
            )
    if states[RunnerClass.TIER_3] == TierState.ELIGIBLE:
        return RunnerClass.TIER_3, next(runner for runner in tiers[RunnerClass.TIER_3] if runner.status == "online")
    return None


def select_runner(raw_pages: object, tier_2_drain: str = "") -> RouteSelection:
    """Choose one neutral runner tier from a complete repository inventory."""
    try:
        tiers = _trusted_tiers(_complete_inventory(raw_pages))
    except (TypeError, ValueError) as _error:
        return _hosted_selection(FallbackReason.INVENTORY_UNTRUSTED, state=TierState.UNTRUSTED)
    states = _tier_states(tiers, tier_2_drain)
    selected = _pick_runner(tiers, states)
    if selected is None:
        return RouteSelection(
            json.dumps("ubuntu-24.04"),
            RunnerClass.HOSTED,
            states[RunnerClass.TIER_1],
            states[RunnerClass.TIER_2],
            states[RunnerClass.TIER_3],
            "",
            FallbackReason.NO_ELIGIBLE_TIER,
        )
    runner_class, runner = selected
    target = json.dumps(["self-hosted", "Linux", "X64", "nohiki", runner_class], separators=(",", ":"))
    return RouteSelection(
        target,
        runner_class,
        states[RunnerClass.TIER_1],
        states[RunnerClass.TIER_2],
        states[RunnerClass.TIER_3],
        runner.name,
        FallbackReason.NONE,
    )


def require_outcome(outcome: str, *, expected: bool, name: str) -> None:
    """Require a selected step to succeed and an unselected step to be skipped."""
    wanted = "success" if expected else "skipped"
    if outcome != wanted:
        selection = "selected" if expected else "not selected"
        msg = f"{name} was {selection} but concluded {outcome}"
        raise ValueError(msg)


def render_cache_table(cache_outcomes: str) -> str:
    """Render setup-ci cache telemetry as the workflow's Markdown table."""
    lines = ["| Cache | Outcome | Key |", "|---|---|---|"]
    for entry in cache_outcomes.split():
        name, _, value = entry.partition("=")
        state, separator, key = value.partition(":")
        if not separator:
            key = value
        rendered_key = "—" if key == "none" else f"`{_CACHE_KEY.sub(r'\1…', key)}`"
        lines.append(f"| {name} | {state.replace('-', ' ')} | {rendered_key} |")
    return "\n".join(lines)


def _context(run_id: str, sha: str, rows: Sequence[str] = ()) -> list[str]:
    return [
        "| Context | Value |",
        "|---|---|",
        f"| Run | `{run_id}` |",
        *rows,
        f"| Tested SHA | `{sha[:7]}` |",
        "",
        "### Results",
    ]


def render_open_summary(job: str, values: dict[str, str]) -> str:
    """Render one job's unchanged summary preamble."""
    run_id = values.get("GITHUB_RUN_ID", "")
    sha = values.get("GITHUB_SHA", "")
    if job == "router":
        action = values.get("EVENT_ACTION") or "none"
        lines = [
            "## Router",
            "",
            "Classifies the tested diff into lane flags and a commit class. Runs no checks itself.",
            "",
            *_context(run_id, sha, [f"| Event | `{values.get('GITHUB_EVENT_NAME', '')}` (`{action}`) |"]),
        ]
    elif job == "worker":
        unit = values.get("UNIT", "")
        scopes = {
            "python": "the Python leg: the affected-package test closure.",
            "frontend": "the frontend leg: Node, hygiene and policy checks.",
        }
        if unit not in scopes:
            msg = f"unknown worker unit: {unit}"
            raise ValueError(msg)
        lines = [
            f"## Scoped worker ({unit})",
            "",
            f"Runs {scopes[unit]}",
            "",
            *_context(
                run_id,
                sha,
                [
                    f"| Unit | `{unit}` of `{values.get('UNITS', '')}` |",
                    f"| Commit class | `{values.get('COMMIT_CLASS', '')}` |",
                ],
            ),
        ]
    elif job == "playwright":
        lines = [
            "## Playwright runner image",
            "",
            "Builds the Playwright runner image and asserts the bundled Playwright CLI runs",
            "inside it.",
            "",
            *_context(run_id, sha),
        ]
    elif job == "title":
        reused = values.get("REUSED_RUN_ID") or "unknown"
        lines = [
            "## Title policy",
            "",
            "Re-lints the pull request title, which becomes the merge commit subject and is the",
            f"only thing an `edited` event can change. Run `{reused}` proves the tree.",
            "",
            "| Context | Value |",
            "|---|---|",
            f"| Run | `{run_id}` |",
            f"| Tested SHA | `{sha[:7]}` |",
            f"| Proven by | `{reused}` |",
            "",
            "### Results",
        ]
    elif job == "checks":
        action = values.get("EVENT_ACTION") or "none"
        rows = [
            "| Context | Value |",
            "|---|---|",
            f"| Run | `{run_id}` |",
            f"| Event | `{values.get('GITHUB_EVENT_NAME', '')}` (`{action}`) |",
            f"| Commit class | `{values.get('COMMIT_CLASS', '')}` |",
        ]
        if _true(values.get("TITLE_ONLY")):
            reused = values.get("REUSED_RUN_ID") or "unknown"
            rows.append(f"| Reuse | title-only edit, tree proven by run `{reused}` |")
        rows.extend(["", "### Results"])
        lines = [
            "## Checks",
            "",
            "Fan-in. Asserts every selected job reached the conclusion the gate required,",
            "validates the router attestation, and accounts for the run.",
            "",
            *rows,
        ]
    else:
        msg = f"unknown workflow summary job: {job}"
        raise ValueError(msg)
    return "\n".join(lines) + "\n"


def _cost(setup_seconds: int, unique_seconds: int) -> list[str]:
    return [
        "### Cost",
        "",
        "| Phase | Seconds |",
        "|---|---:|",
        f"| Setup | {setup_seconds} |",
        f"| Unique work | {unique_seconds} |",
    ]


def _timings(values: dict[str, str], now: int) -> tuple[int, int]:
    unique_started = int(values.get("UNIQUE_STARTED") or 0)
    return unique_started - int(values.get("JOB_STARTED") or 0), now - unique_started


def render_report_summary(job: str, values: dict[str, str], *, now: int) -> str:
    """Render one job's unchanged result, timing, cache and command report."""
    setup_seconds, unique_seconds = _timings(values, now)
    if job == "router":
        lines: list[str] = []
        if _true(values.get("TITLE_ONLY")):
            lines.extend(
                [
                    "",
                    "**Substantive units short-circuited.** This event changed only the pull request",
                    "title, which cannot change the tree, so run "
                    f"`{values.get('REUSED_RUN_ID', '')}` already proves every",
                    "verdict above. Commit policy still runs in `Title policy`.",
                ]
            )
        uv_state = "hit" if _true(values.get("UV_CACHE_HIT")) else "miss"
        cache = f"uv={uv_state}:{values.get('UV_CACHE_KEY') or 'none'}"
        lines.extend(["", *_cost(setup_seconds, unique_seconds), "", render_cache_table(cache), "", "### Commands", ""])
        if values.get("GITHUB_EVENT_NAME") == "push":
            lines.append("- `ci-checks gate-evidence`")
        lines.extend(["- `ci-checks gate`", "- `ci-checks gate-reuse`"])
        if values.get("GITHUB_EVENT_NAME") == "pull_request" and values.get("EVENT_ACTION") != "edited":
            lines.append("- `git rev-parse HEAD^{tree}`; `jq` attestation")
    elif job == "worker":
        unit = values.get("UNIT", "")
        smoke = _true(values.get("SMOKE"))
        commands = [
            command
            for flag, owner, command in _WORKER_COMMANDS
            if not smoke and _true(values.get(f"FLAG_{flag.upper()}")) and unit == owner
        ]
        lines = []
        if smoke:
            lines.extend(["", "Protected-main smoke only. No check in this unit reports findings."])
        elif not commands:
            lines.extend(
                [
                    "",
                    f"The gate selected no check for the `{unit}` bin on this change, so there is",
                    "nothing to report here. The secret scan below is the only work this unit did.",
                ]
            )
        lines.append("")
        if _true(values.get("CONTAINER_SELECTED")):
            lines.extend(
                [
                    "",
                    "| Container check | Outcome |",
                    "|---|---|",
                    f"| Production frontend image build | {values.get('IMAGE_OUTCOME', '')} |",
                    f"| Frontend container hardened-runtime smoke | {values.get('SMOKE_OUTCOME', '')} |",
                    f"| OpenTelemetry collector image and rendered configs | {values.get('OTEL_OUTCOME', '')} |",
                ]
            )
        lines.extend(
            [
                *_cost(setup_seconds, unique_seconds),
                "",
                render_cache_table(values.get("CACHE_OUTCOMES", "")),
                "",
                "### Commands",
                "",
            ]
        )
        if smoke:
            lines.append("- `ci-checks --help` (protected-main smoke)")
        lines.extend(f"- `{command}`" for command in commands)
        lines.append("- changed-content or repository-wide `gitleaks` scan")
    elif job == "playwright":
        lines = [
            "",
            "| Check | Outcome |",
            "|---|---|",
            f"| Playwright runner image build | {values.get('BUILD_OUTCOME', '')} |",
            f"| `playwright --version` inside the built image | {values.get('VERIFY_OUTCOME', '')} |",
            "",
            *_cost(setup_seconds, unique_seconds),
            "",
            "This job restores no `actions/cache` entries. Image layers come from the",
            "BuildKit `type=gha` cache, which reports its hit rate in the build step log.",
            "",
            "### Commands",
            "",
            "- Buildx build of `typescript/apps/frontend/Dockerfile.playwright-runner`",
            "- `playwright --version` inside the built image",
        ]
    elif job == "title":
        lines = [
            "",
            "| Check | Outcome |",
            "|---|---|",
            f"| commitlint on the pull request title | {values.get('TITLE_OUTCOME', '')} |",
            "",
            *_cost(setup_seconds, unique_seconds),
            "",
            render_cache_table(values.get("CACHE_OUTCOMES", "")),
            "",
            "### Commands",
            "",
            "- `commitlint` on the pull request title",
        ]
    else:
        msg = f"unknown workflow report job: {job}"
        raise ValueError(msg)
    return "\n".join(lines) + "\n"


def _parse_time(value: object) -> int | None:
    if not isinstance(value, str):
        return None
    try:
        return int(datetime.fromisoformat(value).timestamp())
    except ValueError:
        return None


def _json_mapping(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        return None
    return {key: item for key, item in value.items() if isinstance(key, str)}


def accounting_span(run_started_at: str, now: datetime, jobs: Sequence[Mapping[str, object]]) -> WallTiming:
    """Split total run wall time into GitHub dispatch and controllable time."""
    run_started = _parse_time(run_started_at)
    if run_started is None:
        msg = f"invalid run_started_at: {run_started_at}"
        raise ValueError(msg)
    accounting_epoch = int(now.timestamp())
    run_seconds = accounting_epoch - run_started
    eligible = [job for job in jobs if job.get("conclusion") != "skipped"]
    starts = [_parse_time(job.get("started_at")) for job in eligible]
    if eligible and all(start is not None for start in starts):
        first = min(start for start in starts if start is not None)
        if run_started <= first <= accounting_epoch:
            return WallTiming(
                run_seconds,
                accounting_epoch - first,
                first - run_started,
                "first non-skipped job start from the Actions jobs API",
            )
    return WallTiming(
        run_seconds,
        run_seconds,
        0,
        "run_started_at fallback: first non-skipped job start unavailable or invalid",
    )


def _cache_state(kind: str, missed: str, hit: str) -> tuple[str, str]:
    signals = f"{missed}:{hit}"
    if kind == "ready":
        states = {
            "true:": ("missed", "ready-cache primary key missed by at least one worker leg"),
            ":true": ("restored", "ready-cache primary key restored by every reporting worker leg"),
            "true:true": ("mixed", "ready-cache primary key hit on one worker leg and missed on another"),
            ":": ("unreported", "ready-cache primary key hit unreported"),
        }
        return states.get(signals, ("invalid", "ready-cache signal invalid"))
    states = {
        "true:": ("missed", "dead-code static cache primary key not restored"),
        ":true": ("restored", "dead-code static cache primary key restored"),
        ":": ("unreported", "dead-code static cache hit unreported"),
    }
    return states.get(signals, ("invalid", "dead-code static cache signal invalid"))


def select_wall_budget(ready_missed: str, ready_hit: str, deadcode_missed: str, deadcode_hit: str) -> WallBudget:
    """Select the exact warm or cold wall target from single-writer cache signals."""
    ready_state, ready_basis = _cache_state("ready", ready_missed, ready_hit)
    deadcode_state, deadcode_basis = _cache_state("deadcode", deadcode_missed, deadcode_hit)
    warm = ready_state == deadcode_state == "restored"
    return WallBudget(
        WARM_WALL_BUDGET_SECONDS if warm else COLD_WALL_BUDGET_SECONDS,
        "warm" if warm else "cold",
        f"{ready_basis}; {deadcode_basis}",
    )


def _job_is_self_hosted(job: Mapping[str, object]) -> bool:
    labels = job.get("labels")
    return isinstance(labels, list) and any(
        isinstance(label, str) and label.casefold() == "self-hosted" for label in labels
    )


def runner_minute_totals(jobs: Sequence[Mapping[str, object]], now: datetime) -> tuple[int, int]:
    """Split rounded self-hosted avoided minutes from actual hosted reconstruction."""
    now_epoch = int(now.timestamp())
    avoided = 0
    reconstructed = 0
    for job in jobs:
        started = _parse_time(job.get("started_at"))
        if started is None:
            continue
        completed = _parse_time(job.get("completed_at")) or now_epoch
        minutes = math.ceil((completed - started) / 60)
        if _job_is_self_hosted(job):
            avoided += minutes
        else:
            reconstructed += minutes
    return avoided, reconstructed


def _job_conclusion(job: Mapping[str, object], expected: Mapping[str, bool], reused_run_id: str) -> str:
    conclusion = job.get("conclusion")
    if conclusion is None:
        return "running (this job)"
    if conclusion != "skipped":
        return str(conclusion)
    name = str(job.get("name", ""))
    wanted = expected["worker"] if name.startswith("Scoped worker") else expected.get(name, False)
    if wanted and reused_run_id:
        return f"skipped: already proven by run {reused_run_id}"
    if wanted:
        return "skipped: expected to run"
    return "skipped: not selected"


def derive_accounting(
    run_started_at: str,
    now: datetime,
    jobs: Sequence[Mapping[str, object]],
    *,
    ready_missed: str,
    ready_hit: str,
    deadcode_missed: str,
    deadcode_hit: str,
) -> Accounting:
    """Derive every arithmetic value rendered and enforced by the fan-in."""
    started_jobs = tuple(job for job in jobs if job.get("started_at") is not None)
    avoided, reconstructed = runner_minute_totals(started_jobs, now)
    return Accounting(
        accounting_span(run_started_at, now, jobs),
        select_wall_budget(ready_missed, ready_hit, deadcode_missed, deadcode_hit),
        avoided,
        f"{avoided * 6 // 1000}.{avoided * 6 % 1000:03d}",
        reconstructed,
        f"{reconstructed * 6 // 1000}.{reconstructed * 6 % 1000:03d}",
        started_jobs,
    )


def enforce_wall_budget(accounting: Accounting) -> None:
    """Fail when controllable wall time reaches the selected strict ceiling."""
    if accounting.timing.controllable_seconds < accounting.budget.seconds:
        return
    budget = accounting.budget
    msg = (
        f"wall budget breached: class={budget.classification} "
        f"observed_controllable={accounting.timing.controllable_seconds}s "
        f"budget<{budget.seconds}s basis={budget.basis}"
    )
    raise ValueError(msg)


def render_accounting(accounting: Accounting, expected: dict[str, bool], reused_run_id: str, now: datetime) -> str:
    """Render truthful self-hosted avoidance and hosted execution reconstruction."""
    lines = [
        "",
        "| Job | Exact seconds | Rounded standard-Linux minutes | Accounting | Conclusion |",
        "|---|---:|---:|---|---|",
    ]
    now_epoch = int(now.timestamp())
    for job in accounting.jobs:
        started = _parse_time(job.get("started_at"))
        if started is None:
            continue
        completed = _parse_time(job.get("completed_at")) or now_epoch
        seconds = completed - started
        accounting_kind = "avoided" if _job_is_self_hosted(job) else "reconstructed hosted"
        lines.append(
            f"| {job.get('name', '')} | {seconds} | {math.ceil(seconds / 60)} | "
            f"{accounting_kind} | {_job_conclusion(job, expected, reused_run_id)} |"
        )
    timing = accounting.timing
    budget = accounting.budget
    lines.extend(
        [
            "",
            "### Runner-minute accounting",
            "",
            (
                "Self-hosted jobs contribute only hosted-equivalent avoided minutes. "
                "Hosted jobs contribute only reconstructed hosted minutes. The billing API, "
                "not this reconstruction, is the authority for actual charges."
            ),
            "",
            "| Measure | Value |",
            "|---|---:|",
            f"| Run wall seconds (includes GitHub dispatch) | {timing.run_seconds} |",
            f"| Controllable wall seconds (budgeted) | {timing.controllable_seconds} |",
            f"| GitHub dispatch seconds (not budgeted) | {timing.dispatch_seconds} |",
            f"| Accounting start | {timing.start_basis} |",
            f"| Wall budget seconds | {budget.seconds} |",
            f"| Wall budget class | {budget.classification} |",
            f"| Wall budget basis | {budget.basis} |",
            f"| Hosted-equivalent avoided minutes | {accounting.avoided_minutes} |",
            f"| Hosted-equivalent avoided cost USD | {accounting.avoided_cost_usd} |",
            f"| Reconstructed hosted minutes | {accounting.reconstructed_hosted_minutes} |",
            f"| Reconstructed hosted cost USD | {accounting.reconstructed_hosted_cost_usd} |",
            "",
            "### Commands",
            "",
            "- router attestation validation",
            "- jobs API accounting aggregation",
        ]
    )
    return "\n".join(lines) + "\n"


def _gh_json(args: list[str]) -> object:
    result = subprocess.run(["gh", "api", *args], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def _route_summary(selection: RouteSelection, tier_2_drain: str) -> str:
    drain = "true" if tier_2_drain.casefold() == "true" else "false"
    selected_name = selection.selected_name or "none"
    fallback = selection.fallback_reason or "none"
    return (
        "\n### Runner route\n\n"
        "| Measure | Value |\n"
        "|---|---|\n"
        f"| Selected class | `{selection.runner_class}` |\n"
        f"| Selected runner | `{selected_name}` |\n"
        f"| Tier 1 state | `{selection.tier_1_state}` |\n"
        f"| Tier 2 state | `{selection.tier_2_state}` |\n"
        f"| Tier 3 state | `{selection.tier_3_state}` |\n"
        f"| Tier 2 drain | `{drain}` |\n"
        f"| Hosted fallback reason | {fallback} |\n"
    )


def route_cmd(repository: str, github_output: Path, summary: Path, tier_2_drain: str = "") -> None:
    """Read complete runner inventory and emit one atomic fail-closed route."""
    selection: RouteSelection | None = None
    if not os.environ.get("GH_TOKEN"):
        selection = _hosted_selection(FallbackReason.INVENTORY_UNAVAILABLE)
    else:
        endpoint = f"repos/{repository}/actions/runners?per_page=100"
        for _attempt in range(2):
            try:
                selection = select_runner(_gh_json(["--paginate", "--slurp", endpoint]), tier_2_drain)
                break
            except _RUNNER_INVENTORY_ERRORS:
                continue
    if selection is None:
        selection = _hosted_selection(FallbackReason.INVENTORY_REQUEST_FAILED)
    output_text = "".join(f"{name}={value}\n" for name, value in route_outputs(selection).items())
    _append(github_output, output_text)
    _append(summary, _route_summary(selection, tier_2_drain))


def summary_cmd(phase: str, job: str, summary: Path) -> None:
    """Append a workflow job summary frame or report."""
    values = dict(os.environ)
    if phase == "open":
        text = render_open_summary(job, values)
    elif phase == "report":
        text = render_report_summary(job, values, now=int(datetime.now(tz=UTC).timestamp()))
    else:
        msg = f"unknown workflow summary phase: {phase}"
        raise ValueError(msg)
    _append(summary, text)


def verdict_cmd(kind: str, github_output: Path | None = None) -> None:
    """Enforce selected-step verdicts without duplicating shell predicates."""
    values = os.environ
    if kind == "container":
        require_outcome(
            values.get("BUILDX_OUTCOME", ""),
            expected=_true(values.get("FRONTEND_SMOKE_EXPECTED")),
            name="container-buildx",
        )
        require_outcome(
            values.get("IMAGE_OUTCOME", ""),
            expected=_true(values.get("FRONTEND_SMOKE_EXPECTED")),
            name="frontend-image",
        )
        require_outcome(
            values.get("SMOKE_OUTCOME", ""),
            expected=_true(values.get("FRONTEND_SMOKE_EXPECTED")),
            name="frontend-smoke",
        )
        require_outcome(
            values.get("OTEL_OUTCOME", ""),
            expected=_true(values.get("OTEL_EXPECTED")),
            name="otel-collector",
        )
        if github_output is None:
            msg = "container verdict requires a GitHub output path"
            raise ValueError(msg)
        _append(github_output, "executed=true\n")
        return
    if kind != "checks":
        msg = f"unknown workflow verdict: {kind}"
        raise ValueError(msg)
    if values.get("CHANGES_RESULT") != "success":
        msg = "Router was selected but did not succeed"
        raise ValueError(msg)
    if values.get("FULL") != values.get("BROAD"):
        msg = "router full and broad outputs disagree"
        raise ValueError(msg)
    commit_class = values.get("COMMIT_CLASS", "")
    standard = _true(values.get("STANDARD"))
    broad = _true(values.get("BROAD"))
    if commit_class == "standard":
        valid_class = standard and not broad
    elif commit_class == "broad":
        valid_class = broad and not standard
    else:
        msg = "router emitted an invalid commit class"
        raise ValueError(msg)
    if not valid_class:
        msg = f"router emitted inconsistent {commit_class} class flags"
        raise ValueError(msg)
    require_outcome(
        values.get("WORKER_RESULT", ""),
        expected=_true(values.get("WORK_EXPECTED")),
        name="worker",
    )
    pairs = (
        ("WORKER_COMMITLINT", "WORKER_COMMITLINT_EXPECTED", "the selected worker did not execute commit policy"),
        ("WORKER_NODE_GROUP", "NODE_GROUP_EXPECTED", "the selected worker did not execute the Node command group"),
        (
            "WORKER_CONTAINER_CONTRACTS",
            "CONTAINER_EXPECTED",
            "the selected worker did not complete every container contract",
        ),
    )
    for actual_name, expected_name, error in pairs:
        actual = _true(values.get(actual_name))
        expected_value = _true(values.get(expected_name))
        if actual != expected_value:
            raise ValueError(error)
    require_outcome(
        values.get("PLAYWRIGHT_RESULT", ""),
        expected=_true(values.get("PLAYWRIGHT_EXPECTED")),
        name="playwright-image",
    )
    require_outcome(
        values.get("TITLE_POLICY_RESULT", ""),
        expected=_true(values.get("TITLE_POLICY_EXPECTED")),
        name="title-policy",
    )


def accounting_cmd(summary: Path) -> None:
    """Fetch Actions metadata, render accounting and enforce the selected wall budget."""
    values = os.environ
    commit_class = values.get("COMMIT_CLASS", "")
    if commit_class not in {"standard", "broad"}:
        msg = "cannot account for an invalid commit class"
        raise ValueError(msg)
    repository = values["REPO"]
    run_id = values["RUN_ID"]
    run = _gh_json([f"repos/{repository}/actions/runs/{run_id}"])
    pages = _gh_json(["--paginate", "--slurp", f"repos/{repository}/actions/runs/{run_id}/jobs?per_page=100"])
    if not isinstance(run, dict) or not isinstance(pages, list):
        msg = "GitHub Actions accounting response has an invalid shape"
        raise TypeError(msg)
    raw_jobs: list[Mapping[str, object]] = []
    for raw_page in pages:
        page = _json_mapping(raw_page)
        page_jobs = page.get("jobs") if page is not None else None
        if not isinstance(page_jobs, list):
            continue
        raw_jobs.extend(job for raw_job in page_jobs if (job := _json_mapping(raw_job)) is not None)
    now = datetime.now(tz=UTC).replace(microsecond=0)
    accounting = derive_accounting(
        str(run.get("run_started_at", "")),
        now,
        raw_jobs,
        ready_missed=values.get("WORKER_READY_CACHE_MISSED", ""),
        ready_hit=values.get("WORKER_READY_CACHE_HIT", ""),
        deadcode_missed=values.get("WORKER_DEADCODE_CACHE_MISSED", ""),
        deadcode_hit=values.get("WORKER_DEADCODE_CACHE_HIT", ""),
    )
    expected = {
        "worker": _true(values.get("WORK_EXPECTED")),
        "Playwright runner image": _true(values.get("PLAYWRIGHT_EXPECTED")),
        "Title policy": _true(values.get("TITLE_POLICY_EXPECTED")),
        "Router": True,
        "Checks": True,
    }
    _append(summary, render_accounting(accounting, expected, values.get("REUSED_RUN_ID", ""), now))
    enforce_wall_budget(accounting)


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    route = subparsers.add_parser("route")
    route.add_argument("repository")
    route.add_argument("github_output", type=Path)
    route.add_argument("summary", type=Path)
    route.add_argument("tier_2_drain", nargs="?", default="")
    summary = subparsers.add_parser("summary")
    summary.add_argument("phase", choices=("open", "report"))
    summary.add_argument("job", choices=("router", "worker", "playwright", "title", "checks"))
    summary.add_argument("summary", type=Path)
    verdict = subparsers.add_parser("verdict")
    verdict.add_argument("kind", choices=("container", "checks"))
    verdict.add_argument("github_output", type=Path, nargs="?")
    accounting = subparsers.add_parser("accounting")
    accounting.add_argument("summary", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "route":
            route_cmd(args.repository, args.github_output, args.summary, args.tier_2_drain)
        elif args.command == "summary":
            summary_cmd(args.phase, args.job, args.summary)
        elif args.command == "verdict":
            verdict_cmd(args.kind, args.github_output)
        else:
            accounting_cmd(args.summary)
    except (KeyError, OSError, TypeError, subprocess.CalledProcessError, ValueError) as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
