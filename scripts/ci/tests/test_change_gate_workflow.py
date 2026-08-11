import ast
import json
import os
import re
import subprocess
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import ci_checks.checks.workflow as workflow_helpers
import pytest
from _documents import WorkflowJob, WorkflowStep, load_mapping, load_workflow, mapping_sequence_at
from ci_checks.checks.deadcode import STATIC_RESULT_OUTPUT
from ci_checks.checks.workflow import (
    COLD_WALL_BUDGET_SECONDS,
    WARM_WALL_BUDGET_SECONDS,
    WallTiming,
    accounting_span,
    derive_accounting,
    enforce_wall_budget,
    render_accounting,
    render_cache_table,
    render_open_summary,
    route_outputs,
    runner_minute_totals,
    select_runner,
    select_wall_budget,
)
from ci_checks.core.change_gate import (
    BroadCause,
    BroadReason,
    CommitClass,
    GateDecision,
    evaluate,
    render_outputs,
    selected_test_packages,
)
from ci_checks.core.change_rules import FLAG_NAMES
from ci_checks.core.packages import Scope, load_packages_with_deps

_ROOT = Path(__file__).resolve().parents[3]
_CHECKS = _ROOT / ".github" / "workflows" / "checks.yml"
_FRESHNESS = _ROOT / ".github" / "workflows" / "digest-freshness.yml"
_SETUP_CI = _ROOT / ".github" / "actions" / "setup-ci" / "action.yml"
_NODE_WORKSPACE_MARKER = "requires_node_modules"
_SKYLOS_MARKER = "requires_skylos"
_CI_TESTS = "scripts/ci/tests"


def _jobs() -> dict[str, WorkflowJob]:
    return load_workflow(_CHECKS)["jobs"]


def _steps(job: WorkflowJob) -> list[WorkflowStep]:
    steps: list[WorkflowStep] = []
    for step in job.get("steps", []):
        steps.extend(step.get("parallel", [step]))
    return steps


def _run_workflow_step(
    step: WorkflowStep,
    *,
    workflow_values: Mapping[str, str] | None = None,
    runner_values: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    raw_environment = step.get("env", {})
    assert isinstance(raw_environment, dict)
    step_environment = {
        str(name): str(value).lower() if isinstance(value, bool) else str(value)
        for name, value in raw_environment.items()
    }
    if workflow_values is not None:
        assert workflow_values.keys() <= step_environment.keys()
        step_environment.update(workflow_values)
    environment = {name: value for name, value in os.environ.items() if name not in {"PROJECT_ROOT", "VIRTUAL_ENV"}}
    environment.update(step_environment)
    if runner_values is not None:
        environment.update(runner_values)
    return subprocess.run(
        ["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", str(step["run"])],
        cwd=_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def _wall_budgets() -> dict[str, int]:
    return {
        "warm": WARM_WALL_BUDGET_SECONDS,
        "cold": COLD_WALL_BUDGET_SECONDS,
    }


def _runner(
    name: str,
    tier: str,
    *,
    status: str = "online",
    busy: bool = False,
    operating_system: str = "linux",
    labels: list[str] | None = None,
) -> dict[str, object]:
    names = labels or ["self-hosted", "Linux", "X64", "nohiki", tier]
    return {
        "name": name,
        "status": status,
        "busy": busy,
        "os": operating_system,
        "labels": [{"name": label} for label in names],
    }


def _inventory(*runners: dict[str, object], pages: int = 1) -> list[dict[str, object]]:
    size = len(runners)
    if pages == 1:
        return [{"total_count": size, "runners": list(runners)}]
    split = (size + pages - 1) // pages
    return [
        {"total_count": size, "runners": list(runners[offset : offset + split])} for offset in range(0, size, split)
    ]


def test_runner_priority_prefers_idle_tier_1_then_idle_undrained_tier_2_then_online_tier_3() -> None:
    tier_1 = _runner("nohiki-runner-02", "nohiki-t1")
    tier_2 = _runner("nohiki-runner-06", "nohiki-t2")
    tier_3 = _runner("nohiki-runner-01", "nohiki-t3")
    selected = select_runner(_inventory(tier_3, tier_2, tier_1, pages=2))
    assert (selected.runner_class, selected.selected_name) == ("nohiki-t1", "nohiki-runner-02")

    selected = select_runner(
        _inventory(
            _runner("nohiki-runner-02", "nohiki-t1", busy=True),
            _runner("nohiki-runner-03", "nohiki-t1", status="offline"),
            _runner("nohiki-runner-04", "nohiki-t1", busy=True),
            _runner("nohiki-runner-05", "nohiki-t1"),
            tier_2,
            tier_3,
        )
    )
    assert (selected.runner_class, selected.selected_name) == ("nohiki-t1", "nohiki-runner-05")

    selected = select_runner(_inventory(tier_3, tier_2, _runner("nohiki-runner-02", "nohiki-t1", status="offline")))
    assert (selected.runner_class, selected.selected_name) == ("nohiki-t2", "nohiki-runner-06")

    selected = select_runner(
        _inventory(
            tier_3,
            _runner("nohiki-runner-06", "nohiki-t2", busy=True),
            _runner("nohiki-runner-02", "nohiki-t1", busy=True),
        )
    )
    assert (selected.runner_class, selected.selected_name) == ("nohiki-t3", "nohiki-runner-01")


def test_runner_routing_handles_all_up_one_down_and_all_down() -> None:
    fleet = (
        ("nohiki-runner-01", "nohiki-t3"),
        ("nohiki-runner-02", "nohiki-t1"),
        ("nohiki-runner-03", "nohiki-t1"),
        ("nohiki-runner-04", "nohiki-t1"),
        ("nohiki-runner-05", "nohiki-t1"),
        ("nohiki-runner-06", "nohiki-t2"),
    )
    all_up = select_runner(_inventory(*(_runner(name, tier) for name, tier in fleet)))
    assert (all_up.runner_class, all_up.selected_name) == ("nohiki-t1", "nohiki-runner-02")

    one_down = select_runner(
        _inventory(
            *(_runner(name, tier, status="offline" if name == "nohiki-runner-02" else "online") for name, tier in fleet)
        )
    )
    assert (one_down.runner_class, one_down.selected_name) == ("nohiki-t1", "nohiki-runner-03")

    all_down = select_runner(_inventory(*(_runner(name, tier, status="offline") for name, tier in fleet)))
    assert all_down.runner_class == "hosted"
    assert (all_down.tier_1_state, all_down.tier_2_state, all_down.tier_3_state) == (
        "offline",
        "offline",
        "offline",
    )


def test_powered_off_tier_1_falls_through_without_waiting_and_rerun_takes_a_fresh_snapshot() -> None:
    powered_off = select_runner(
        _inventory(
            _runner("nohiki-runner-02", "nohiki-t1", status="offline"),
            _runner("nohiki-runner-01", "nohiki-t3"),
        )
    )
    assert powered_off.runner_class == "nohiki-t3"
    assert powered_off.tier_1_state == "offline"
    fresh_attempt = select_runner(
        _inventory(_runner("nohiki-runner-02", "nohiki-t1"), _runner("nohiki-runner-01", "nohiki-t3"))
    )
    assert fresh_attempt.runner_class == "nohiki-t1"


def test_busy_tier_1_and_tier_2_fall_through_but_busy_tier_3_queues() -> None:
    selected = select_runner(
        _inventory(
            _runner("nohiki-runner-02", "nohiki-t1", busy=True),
            _runner("nohiki-runner-06", "nohiki-t2", busy=True),
            _runner("nohiki-runner-01", "nohiki-t3", busy=True),
        )
    )
    assert selected.runner_class == "nohiki-t3"
    assert selected.runner_target == '["self-hosted","Linux","X64","nohiki","nohiki-t3"]'
    assert (selected.tier_1_state, selected.tier_2_state, selected.tier_3_state) == (
        "busy",
        "busy",
        "eligible",
    )


def test_tier_2_drain_skips_only_tier_2_and_absent_tiers_skip_cleanly() -> None:
    selected = select_runner(
        _inventory(_runner("nohiki-runner-06", "nohiki-t2"), _runner("nohiki-runner-01", "nohiki-t3")),
        "TRUE",
    )
    assert selected.runner_class == "nohiki-t3"
    assert (selected.tier_1_state, selected.tier_2_state) == ("absent", "draining")
    assert select_runner(_inventory()).runner_class == "hosted"


@pytest.mark.parametrize(
    "inventory",
    [
        [{"total_count": 2, "runners": [_runner("nohiki-runner-01", "nohiki-t3")]}],
        _inventory(_runner("nohiki-runner-01", "nohiki-t3"), _runner("nohiki-runner-07", "nohiki-t3")),
        _inventory(_runner("nohiki-runner-01", "nohiki-t3"), _runner("nohiki-runner-01", "nohiki-t3")),
        _inventory(
            _runner(
                "nohiki-runner-01",
                "nohiki-t3",
                labels=["self-hosted", "Linux", "ARM64", "nohiki", "nohiki-t3"],
            )
        ),
        _inventory(_runner("nohiki-runner-01", "nohiki-t3", operating_system="Windows")),
        [{"total_count": 1, "runners": [{"name": "nohiki-runner-01"}]}],
    ],
)
def test_untrusted_inventory_forces_hosted_fallback(inventory: object) -> None:
    selected = select_runner(inventory)
    assert selected.runner_class == "hosted"
    assert selected.runner_target == '"ubuntu-24.04"'
    assert selected.tier_1_state == selected.tier_2_state == selected.tier_3_state == "untrusted"


def test_runner_target_and_timeout_outputs_are_valid_for_every_class() -> None:
    inventories = {
        "nohiki-t1": _inventory(_runner("nohiki-runner-02", "nohiki-t1")),
        "nohiki-t2": _inventory(_runner("nohiki-runner-06", "nohiki-t2")),
        "nohiki-t3": _inventory(_runner("nohiki-runner-01", "nohiki-t3")),
        "hosted": _inventory(),
    }
    expected_worker = {"nohiki-t1": "52", "nohiki-t2": "52", "nohiki-t3": "52", "hosted": "30"}
    for runner_class, inventory in inventories.items():
        outputs = route_outputs(select_runner(inventory))
        assert outputs["runner_class"] == runner_class
        assert json.loads(outputs["runner_target"])
        assert outputs["worker_timeout_minutes"] == expected_worker[runner_class]
        assert outputs["playwright_timeout_minutes"] == "30"
        assert outputs["title_timeout_minutes"] == ("10" if runner_class == "hosted" else "20")
        assert outputs["checks_timeout_minutes"] == "5"


def _protected_main_fan_in(worker_result: str) -> subprocess.CompletedProcess[str]:
    step = next(step for step in _steps(_jobs()["checks"]) if step.get("name") == "Require every selected check")
    return _run_workflow_step(
        step,
        workflow_values={
            "BROAD": "false",
            "CHANGES_RESULT": "success",
            "COMMIT_CLASS": "standard",
            "CONTAINER_EXPECTED": "false",
            "FULL": "false",
            "NODE_GROUP_EXPECTED": "false",
            "PLAYWRIGHT_EXPECTED": "false",
            "PLAYWRIGHT_RESULT": "skipped",
            "STANDARD": "true",
            "TITLE_POLICY_EXPECTED": "false",
            "TITLE_POLICY_RESULT": "skipped",
            "WORKER_COMMITLINT": "",
            "WORKER_COMMITLINT_EXPECTED": "false",
            "WORKER_CONTAINER_CONTRACTS": "",
            "WORKER_NODE_GROUP": "",
            "WORKER_RESULT": worker_result,
            "WORK_EXPECTED": "true",
        },
    )


def _accounting_span(
    jobs: list[dict[str, object]],
    *,
    run_started: str = "2026-07-23T00:00:00Z",
    now_iso: str = "2026-07-23T00:02:00Z",
) -> WallTiming:
    return accounting_span(run_started, datetime.fromisoformat(now_iso), jobs)


_CONTAINER_EXECUTORS = {
    "frontend_smoke": "worker",
    "frontend_e2e": "playwright-image",
    "otel_collector": "worker",
}
# One job definition owns every lane in both classes. The gate emits only the payload legs
# selected by the decision, and never emits a third hygiene runner.
_STANDARD_EXECUTORS = dict.fromkeys(FLAG_NAMES, "worker") | _CONTAINER_EXECUTORS
_BROAD_EXECUTORS = _STANDARD_EXECUTORS
_WORKER_UNITS = ["python", "frontend"]
_NON_EXECUTOR_JOB_IDS = {
    "changes",
    "checks",
    # Runs the title lint alone on a proven edit, so it owns no lane flag.
    "title-policy",
}


def _class_compatible(condition: str, commit_class: CommitClass) -> bool:
    standard = "needs.changes.outputs.standard == 'true'" in condition
    broad = "needs.changes.outputs.broad == 'true'" in condition
    if standard and broad:
        return True
    if standard:
        return commit_class is CommitClass.STANDARD
    if broad:
        return commit_class is CommitClass.BROAD
    return True


def _positive_reference(condition: str, reference: str) -> bool:
    start = 0
    while (index := condition.find(reference, start)) >= 0:
        negation = condition.rfind("!(", 0, index)
        closed = condition.rfind(")", 0, index)
        if negation <= closed:
            return True
        start = index + len(reference)
    return False


def _job_is_selected_for_flag(
    job_condition: str,
    commit_class: CommitClass,
    reference: str,
) -> bool:
    if not _class_compatible(job_condition, commit_class):
        return False
    has_lane_gate = any(f"needs.changes.outputs.{flag}" in job_condition for flag in FLAG_NAMES)
    return not has_lane_gate or _positive_reference(job_condition, reference)


def _selected_executors(
    jobs: dict[str, WorkflowJob],
    commit_class: CommitClass,
    flag: str,
) -> set[str]:
    reference = f"needs.changes.outputs.{flag}"
    selected: set[str] = set()
    for job_id, job in jobs.items():
        if job_id in _NON_EXECUTOR_JOB_IDS:
            continue
        job_condition = job.get("if", "")
        if not _job_is_selected_for_flag(
            job_condition,
            commit_class,
            reference,
        ):
            continue
        step_owns_flag = any(
            step.get("name") != "Check API schema export freshness"
            and _positive_reference(
                step.get("if", ""),
                reference,
            )
            for step in _steps(job)
        )
        if _positive_reference(job_condition, reference) or step_owns_flag:
            selected.add(job_id)
    return selected


def _decision_executors(
    jobs: dict[str, WorkflowJob],
    decision: GateDecision,
) -> set[str]:
    # Every lane carries its own flag gate in both classes now, so a broad decision has no
    # ungated shard to add by hand: the flags alone name the executor.
    return {
        executor
        for flag in decision.flags
        for executor in _selected_executors(
            jobs,
            decision.commit_class,
            flag,
        )
    }


_REACHABILITY_CASES = [
    (commit_class, flag, executors[flag])
    for commit_class, executors in (
        (CommitClass.STANDARD, _STANDARD_EXECUTORS),
        (CommitClass.BROAD, _BROAD_EXECUTORS),
    )
    for flag in FLAG_NAMES
]


@pytest.mark.parametrize(("commit_class", "flag", "expected_job"), _REACHABILITY_CASES)
def test_every_class_flag_has_one_required_executor(
    commit_class: CommitClass,
    flag: str,
    expected_job: str,
) -> None:
    assert set(_STANDARD_EXECUTORS) == set(_BROAD_EXECUTORS) == set(FLAG_NAMES)
    selected_tests = ("fixture",) if flag == "python_any" else ()
    decision = GateDecision(full=commit_class is CommitClass.BROAD, flags={flag})
    outputs = render_outputs(decision, selected_tests, "pull_request")
    assert outputs[flag] == "true"

    jobs = _jobs()
    assert _selected_executors(jobs, commit_class, flag) == {expected_job}

    checks = jobs["checks"]
    assert expected_job in checks["needs"]
    fan_in = next(step for step in _steps(checks) if step.get("name") == "Require every selected check")
    assert any(f"needs.{expected_job}.result" in str(value) for value in fan_in["env"].values())


def test_real_multisurface_decisions_keep_the_consolidated_executor_topology() -> None:
    packages = load_packages_with_deps(Scope.ALL)
    jobs = _jobs()
    flake = evaluate(
        {
            "flake.nix",
            "docs/guide.md",
            "typescript/apps/frontend/src/api/schema.d.ts",
        },
        packages,
    )
    selected_tests = selected_test_packages(flake, packages)

    assert flake.commit_class is CommitClass.BROAD
    assert selected_tests
    assert {"lint_markdown", "api_schema_freshness"} <= flake.flags
    # schema.d.ts is a build-context input of the frontend image, not of the Playwright runner.
    assert _decision_executors(jobs, flake) == {"worker"}

    container_union = evaluate(
        {
            "typescript/apps/frontend/Dockerfile",
            "typescript/apps/frontend/Dockerfile.playwright-runner",
            "infra/k8s/observability/base/otel/collector.yaml",
        },
        packages,
    )
    assert container_union.commit_class is CommitClass.STANDARD
    assert {"frontend_smoke", "frontend_e2e", "otel_collector"} <= container_union.flags
    assert _decision_executors(jobs, container_union) == {
        "worker",
        "playwright-image",
    }


def test_one_job_definition_owns_each_lane_across_both_classes() -> None:
    jobs = _jobs()
    worker = jobs["worker"]
    assert "needs.changes.outputs.standard == 'true'" in worker["if"]
    assert "needs.changes.outputs.broad == 'true'" in worker["if"]
    assert worker["needs"] == ["changes"]

    # The gate, not the commit-class label, chooses which of the two named payload legs run.
    matrix = str(worker["strategy"]["matrix"]["unit"])
    assert worker["strategy"]["fail-fast"] is False
    assert matrix == "${{ fromJSON(needs.changes.outputs.worker_units) }}"
    assert jobs["changes"]["outputs"]["worker_units"] == "${{ steps.gate.outputs.worker_units }}"

    bins = {
        "frontend": {
            "Check flake",
            "Check Lefthook version",
            "Lint Python",
            "Check Python formatting",
            "Lint protos",
            "Lint workflows",
            "Lint Dockerfiles (hadolint)",
            "Scan repository for secrets",
            "Check selected dead code",
            "Check dependencies",
            "Scan architecture",
            "Check build backends",
            "Check API schema freshness",
            "Check image matrix parity",
            "Check proto compatibility",
            "Run Node workspace contract tests",
            "Run Skylos cache contract tests",
            "Test JVM module",
            "Lint Markdown",
            "Lint frontend",
            "Check i18n keys",
            "Typecheck frontend",
            "Test frontend",
            "Lint edge worker",
            "Typecheck edge worker",
            "Test edge worker",
            "Validate PR commit messages",
            "Validate PR title (merge commit subject)",
            "Build production frontend image",
            "Smoke production frontend container",
            "Validate OpenTelemetry collector image and configs",
            "Run container contract tests",
        },
        "python": {
            "Typecheck backend",
            "Check import boundaries",
            "Run selected Python tests",
        },
    }
    assert set(bins) == set(_WORKER_UNITS)

    # No lane may be defined twice anywhere in the file: the standard and broad paths were
    # two copies of the same checks, and that is the duplication this topology retires.
    every_name = [
        step.get("name")
        for job_id, job in jobs.items()
        # `title-policy` holds the short-circuit's copy of the title lint. It is not a second
        # definition of the lane: its job gate and the worker's are mutually exclusive, which
        # test_title_edits_have_independent_concurrency_and_check_identities pins directly.
        if job_id != "title-policy"
        for step in _steps(job)
    ]
    lane_names = set().union(*bins.values()) | {"Save Skylos static analysis cache"}
    for name in lane_names:
        assert every_name.count(name) == 1, name

    steps = {step.get("name"): step for step in _steps(worker)}
    for unit_name, members in bins.items():
        for name in members:
            condition = str(steps[name]["if"])
            # A lane may route its gate through a job-level flag when several inputs must share
            # one selector. Ownership is a claim about the expression that actually decides, so
            # resolve that one level of indirection before matching.
            for flag, expression in worker["env"].items():
                condition = condition.replace(f"env.{flag}", str(expression))
            assert f"matrix.unit == '{unit_name}'" in condition, name
            for other in set(bins) - {unit_name}:
                assert f"matrix.unit == '{other}'" not in condition, (name, other)

    full_scan = steps["Scan repository for secrets"]
    assert full_scan["if"].endswith("env.DOCS_ONLY != 'true'")
    assert "just secrets-scan" in full_scan["run"]
    # Matrix units share one outputs map. The runner skips an output whose expression is the
    # empty string and never sends it (actions/runner src/Runner.Worker/JobExtension.cs:789-805),
    # so spelling the negative case as '' makes the unit that ran the step the only writer.
    # `false` is NOT empty by that check, so a boolean-valued expression would race instead.
    assert worker["outputs"] == {
        "node_group_executed": ("${{ steps.setup-ci.outputs.node-group-executed == 'true' && 'true' || '' }}"),
        "commitlint_executed": ("${{ steps.commitlint-range.outcome == 'success' && 'true' || '' }}"),
        # Warmth publishes two names for one fact because '' cannot distinguish "this leg restored"
        # from "this leg never reported"; an unreported run must be classified cold.
        "ready_cache_missed": ("${{ steps.setup-ci.outputs.ready-cache-hit != 'true' && 'true' || '' }}"),
        "ready_cache_hit": ("${{ steps.setup-ci.outputs.ready-cache-hit == 'true' && 'true' || '' }}"),
        "deadcode_cache_missed": (
            "${{ env.DEADCODE_SELECTED == 'true' && steps.setup-ci.outputs.skylos-cache-hit != 'true' "
            "&& 'true' || '' }}"
        ),
        "deadcode_cache_hit": (
            "${{ env.DEADCODE_SELECTED == 'true' && steps.setup-ci.outputs.skylos-cache-hit == 'true' "
            "&& 'true' || '' }}"
        ),
        "container_contracts_executed": ("${{ steps.container-contracts.outputs.executed == 'true' && 'true' || '' }}"),
    }


def test_execution_attestations_are_not_scoped_to_one_commit_class() -> None:
    """Every `*_executed` claim must cover the class its step actually runs on.

    Commit policy and the Node command group execute on the standard `all` unit and on a broad
    unit alike. Scoping either the published value or the fan-in expectation to one class makes
    the pair agree with itself while both halves are false on the other class, so the fan-in
    records "not selected, did not run" for work that was selected and did run. That is silent
    accounting drift, and the attestation is the only thing standing against it.
    """
    worker_outputs = _jobs()["worker"]["outputs"]
    fan_in = next(step for step in _steps(_jobs()["checks"]) if step.get("name") == "Require every selected check")
    env = fan_in["env"]

    assert {name for name in worker_outputs if name.endswith("_executed")} == {
        "node_group_executed",
        "commitlint_executed",
        "container_contracts_executed",
    }
    for name, value in worker_outputs.items():
        # A per-unit claim may read steps and matrix state; a commit class is not per-unit.
        assert "needs.changes.outputs.standard" not in value, name
        assert "needs.changes.outputs.broad" not in value, name
        # The negative case must be empty so a unit that skipped the step contributes nothing.
        assert value.endswith("&& 'true' || '' }}"), name

    for name in ("WORKER_COMMITLINT_EXPECTED", "NODE_GROUP_EXPECTED"):
        assert "needs.changes.outputs.standard" not in str(env[name]), name
        assert "needs.changes.outputs.broad" not in str(env[name]), name

    container_expectation = str(env["CONTAINER_EXPECTED"])
    assert "needs.changes.outputs.standard == 'true'" not in container_expectation
    assert "needs.changes.outputs.broad == 'true'" not in container_expectation

    def referenced_flags(expression: str) -> set[str]:
        return set(re.findall(r"needs\.changes\.outputs\.(\w+)", expression))

    # The expectation attests the same provisioning operation the worker requests.
    assert referenced_flags(str(env["NODE_GROUP_EXPECTED"])) == referenced_flags(
        str(_jobs()["worker"]["env"]["NODE_SETUP_SELECTED"])
    )

    container_selector = str(_jobs()["worker"]["env"]["CONTAINER_CONTRACTS_SELECTED"])
    assert "matrix.unit == 'frontend'" in container_selector
    assert referenced_flags(str(env["CONTAINER_EXPECTED"])) == referenced_flags(container_selector)


def _unreachable_class_expressions(job: WorkflowJob) -> list[str]:
    """Return expressions naming the commit class a class-gated job can never run under."""
    gated = {
        name
        for name, reference in (
            ("standard", "needs.changes.outputs.standard == 'true'"),
            ("broad", "needs.changes.outputs.broad == 'true'"),
        )
        if _positive_reference(str(job.get("if", "")), reference)
    }
    if len(gated) != 1:
        return []
    opposite = "broad" if gated == {"standard"} else "standard"
    unreachable = f"needs.changes.outputs.{opposite} == 'true'"

    def walk(node: object) -> list[str]:
        match node:
            case str():
                return [node] if unreachable in node else []
            case dict():
                return [hit for value in node.values() for hit in walk(value)]
            case list():
                return [hit for value in node for hit in walk(value)]
            case _:
                return []

    return walk(job)


def test_no_job_carries_an_expression_for_a_class_it_cannot_run_under() -> None:
    """A class-gated job may not reference the class its gate excludes.

    This is the defect that grew the duplicate broad-* family. `worker` was gated on
    ``standard == 'true'`` while holding ten live-looking ``broad == 'true'`` expressions,
    including three ``PACKAGE_SCOPE`` selectors that already resolved to the value the
    broad copies hard-coded. Nothing failed, so the copies were written beside them
    instead of the gate being opened.
    """
    regressed: WorkflowJob = {
        "if": "needs.changes.outputs.standard == 'true'",
        "env": {"PACKAGE_SCOPE": "${{ needs.changes.outputs.broad == 'true' && 'ALL' || '' }}"},
    }
    assert _unreachable_class_expressions(regressed), "the detector no longer detects"

    for job_id, job in _jobs().items():
        assert not _unreachable_class_expressions(job), job_id


def test_ready_cache_saves_run_on_every_event_behind_profile_key_guards() -> None:
    steps = mapping_sequence_at(load_mapping(_SETUP_CI), "runs", "steps")
    by_name = {step.get("name"): step for step in steps}
    hosted = by_name["Save hosted complete CI environment"]
    persistent = by_name["Save persistent CI virtual environment"]
    for save in (hosted, persistent):
        assert "github.event_name" not in str(save["if"])
    assert "steps.hosted-ready-cache.outputs.primary-key != ''" in str(hosted["if"])
    assert "steps.persistent-ready-cache.outputs.cache-primary-key != ''" in str(persistent["if"])


def test_python_test_lane_uses_gate_scope_once_per_class() -> None:
    worker = _jobs()["worker"]

    assert worker["needs"] == ["changes"]
    assert worker["timeout-minutes"] == ("${{ fromJSON(needs.changes.outputs.worker_timeout_minutes) }}")
    run_tests = next(step for step in _steps(worker) if step.get("name") == "Run selected Python tests")
    command = run_tests["run"]
    assert command.count("ci-checks tests all --scope all") == 1
    assert '--packages "$TEST_PACKAGES"' in command
    assert '--summary-title "$SUMMARY_TITLE"' in command
    assert run_tests["env"]["SUMMARY_TITLE"] == ("${{ needs.changes.outputs.commit_class }}")
    # The 344s test step remains the long pole after the 8.7s backend typecheck moves beside it.
    condition = str(run_tests["if"])
    assert "matrix.unit == 'python'" in condition
    assert "matrix.unit == 'frontend'" not in condition


def test_container_contract_lane_runs_the_routed_marker_suite() -> None:
    step = next(step for step in _steps(_jobs()["worker"]) if step.get("name") == "Run container contract tests")
    command = str(step["run"])

    assert "needs.changes.outputs.container_contracts == 'true'" in str(step["if"])
    assert "ci-checks tests all --scope all" in command
    assert "--requires-docker --ci --workers 1 --no-coverage" in command
    assert '--summary "$GITHUB_STEP_SUMMARY"' in command
    assert '--summary-title "container contracts"' in command
    assert step["env"]["CI_CHECKS_SKIP_WORKSPACE_SYNC"] == "1"


def test_backend_typecheck_keeps_gate_trigger_parity_and_executes_once() -> None:
    step = next(step for step in _steps(_jobs()["worker"]) if step.get("name") == "Typecheck backend")
    condition = str(step["if"])
    assert condition.startswith("matrix.unit == 'python' && ")
    assert "matrix.unit == 'frontend'" not in condition
    assert condition.endswith(
        "needs.changes.outputs.protected_main_smoke != 'true' "
        "&& (needs.changes.outputs.broad_unbounded == 'true' "
        "|| needs.changes.outputs.typecheck_backend == 'true')"
    )
    assert step["run"] == "nix develop .#ci --command just typecheck-all"

    for protected_main_smoke in (False, True):
        for typecheck_backend in (False, True):
            for broad_cause in (None, BroadCause.POLICY_SOURCE, BroadCause.UNMATCHED_PATH):
                reasons = []
                if broad_cause is not None:
                    reasons.append(BroadReason(broad_cause, broad_cause.value))
                decision = GateDecision(
                    full=broad_cause is not None,
                    reasons=reasons,
                    flags={"typecheck_backend"} if typecheck_backend else set(),
                    protected_main_smoke=protected_main_smoke,
                )
                outputs = render_outputs(decision, (), "pull_request")
                triggered_before = outputs["protected_main_smoke"] != "true"
                triggered_before = triggered_before and "true" in (
                    outputs["broad_unbounded"],
                    outputs["typecheck_backend"],
                )
                execution_count = 0
                if triggered_before:
                    execution_count = json.loads(outputs["worker_units"]).count("python")

                assert execution_count == int(triggered_before), outputs


def test_jvm_tests_run_once_on_the_frontend_worker_with_the_pinned_shell() -> None:
    worker = _jobs()["worker"]
    step = next(step for step in _steps(worker) if step.get("name") == "Test JVM module")
    condition = str(step["if"])

    assert "matrix.unit == 'frontend'" in condition
    assert "matrix.unit == 'python'" not in condition
    assert "needs.changes.outputs.broad_unbounded == 'true'" in condition
    assert condition.endswith("needs.changes.outputs.jvm_tests == 'true')")
    assert step["run"] == "nix develop .#jvm --command just test-jvm"


def test_node_workspace_tests_run_where_the_payload_carries_node_modules() -> None:
    worker = _jobs()["worker"]
    steps = {step.get("name"): step for step in _steps(worker)}
    node_lane = steps["Run Node workspace contract tests"]
    assert "just test-node-contracts" in str(node_lane["run"])

    # The Python payload restores no node_modules, so a marked test cannot pass in that unit.
    setup = next(step for step in _steps(worker) if step.get("uses") == "./.github/actions/setup-ci")
    assert setup["with"]["payload"] == "${{ matrix.unit == 'python' && 'python' || 'full' }}"
    condition = str(node_lane["if"])
    assert "matrix.unit == 'frontend'" in condition
    assert "matrix.unit == 'python'" not in condition

    # The gate names this step's own inputs: the k8s Playwright config, the journeys it collects,
    # and the manifests that resolve the Playwright version. Borrowing the Python suite's flag both
    # skipped it on a Playwright config change and ran it on unrelated backend work.
    assert condition.endswith("needs.changes.outputs.node_workspace_contracts == 'true')")
    assert str(steps["Run selected Python tests"]["if"]).endswith("needs.changes.outputs.python_any == 'true')")

    # A marked test outside the one selected path would be deselected everywhere and run nowhere.
    marked = {
        path.relative_to(_ROOT).as_posix()
        for path in _ROOT.glob("**/tests/**/test_*.py")
        if f"pytest.mark.{_NODE_WORKSPACE_MARKER}" in path.read_text(encoding="utf-8")
    }
    assert marked
    assert all(name.startswith(f"{_CI_TESTS}/") for name in marked), marked


def test_environment_selectors_contain_every_lane_that_invokes_the_environment() -> None:
    worker = _jobs()["worker"]
    setup = next(step for step in _steps(worker) if step.get("uses") == "./.github/actions/setup-ci")
    lane_names = set(FLAG_NAMES) | {"commitlint_expected", "protected_main_smoke"}
    selected_re = re.compile(r"needs\.changes\.outputs\.(\w+)\s*==\s*'true'")

    def selected_lanes(expression: object) -> set[str]:
        return lane_names & set(selected_re.findall(str(expression)))

    clean_env = os.environ.copy()
    clean_env.pop("VIRTUAL_ENV", None)
    clean_env.pop("PROJECT_ROOT", None)
    recipes = json.loads(
        subprocess.run(
            ["just", "--dump", "--dump-format", "json"],
            cwd=_ROOT,
            env=clean_env,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    )["recipes"]

    required = {"nix": set(), "node": set(), "full-node-workspace": set()}
    for step in _steps(worker):
        run = str(step.get("run", ""))
        lanes = selected_lanes(step.get("if", ""))
        if not run or not lanes:
            continue

        recipe = re.search(r"\bjust\s+([\w-]+)", run)
        command_surface = run
        if recipe is not None and recipe.group(1) in recipes:
            command_surface += json.dumps(recipes[recipe.group(1)])

        if "nix develop" in run:
            required["nix"].update(lanes)
        if "pnpm" in command_surface or "node_modules" in command_surface:
            required["node"].update(lanes)
        if "node_modules" in command_surface or "--filter" in command_surface:
            required["full-node-workspace"].update(lanes)

    selected = {
        "nix": selected_lanes(worker["env"]["NIX_SETUP_SELECTED"]),
        "node": selected_lanes(worker["env"]["NODE_SETUP_SELECTED"]),
        "full-node-workspace": selected_lanes(setup["with"]["full-node-workspace"]),
    }
    missing = {name: sorted(lanes - selected[name]) for name, lanes in required.items()}
    missing_message = "; ".join(f"{name}={','.join(names)}" for name, names in missing.items())
    assert all(required[name] <= selected[name] for name in required), missing_message


def test_skylos_cache_tests_run_only_where_the_private_analyzer_is_installed() -> None:
    worker = _jobs()["worker"]
    steps = {step.get("name"): step for step in _steps(worker)}
    lane = steps["Run Skylos cache contract tests"]
    assert "just test-skylos-cache" in str(lane["run"])

    # One value decides both the lane and the install. Restating either condition in terms of the
    # units or the router flags it expands to is what would let the two drift, and the lane would
    # then fail on the missing distribution it exists to keep off the other units.
    assert lane["if"] == "env.DEADCODE_SELECTED == 'true'"
    assert str(steps["Check selected dead code"]["if"]) == lane["if"]
    setup = next(step for step in _steps(worker) if step.get("uses") == "./.github/actions/setup-ci")
    assert setup["with"]["skylos-cache"] == "${{ env.DEADCODE_SELECTED }}"
    install = next(
        step
        for step in mapping_sequence_at(load_mapping(_SETUP_CI), "runs", "steps")
        if step.get("name") == "Install Skylos from the pinned private fork"
    )
    assert install["if"] == "inputs.skylos-cache == 'true'"

    # A marked test outside the one selected path would be deselected everywhere and run nowhere.
    marked = {
        path.relative_to(_ROOT).as_posix()
        for path in _ROOT.glob("**/tests/**/test_*.py")
        if f"pytest.mark.{_SKYLOS_MARKER}" in path.read_text(encoding="utf-8")
    }
    assert marked
    assert all(name.startswith(f"{_CI_TESTS}/") for name in marked), marked


def test_workflow_helper_parses_on_hosted_bootstrap_python() -> None:
    source = (_ROOT / "scripts" / "ci" / "src" / "ci_checks" / "checks" / "workflow.py").read_text(encoding="utf-8")
    ast.parse(source, filename="workflow.py", feature_version=(3, 12))


def test_router_emits_one_target_and_per_class_timeout_contract() -> None:
    jobs = _jobs()
    changes = jobs["changes"]
    outputs = changes["outputs"]
    route = next(step for step in _steps(changes) if step.get("name") == "Select runner route")
    assert changes["runs-on"] == "ubuntu-24.04"
    assert changes["timeout-minutes"] == 5
    assert route["env"] == {
        "GH_TOKEN": "${{ secrets.RUNNER_INVENTORY_TOKEN }}",
        "TIER_2_DRAIN": "${{ vars.NOHIKI_T2_DRAIN }}",
    }
    assert "workflow.py route" in str(route["run"]).replace("\n", " ")
    assert outputs["runner_target"] == "${{ steps.route.outputs.runner_target }}"
    assert outputs["runner_class"] == "${{ steps.route.outputs.runner_class }}"
    assert outputs["worker_timeout_minutes"] == "${{ steps.route.outputs.worker_timeout_minutes }}"
    for job_name in ("worker", "playwright-image", "title-policy", "checks"):
        assert "needs.changes.outputs.runner_target" in str(jobs[job_name]["runs-on"])
    assert jobs["worker"]["timeout-minutes"] == "${{ fromJSON(needs.changes.outputs.worker_timeout_minutes) }}"
    assert jobs["playwright-image"]["timeout-minutes"] == (
        "${{ fromJSON(needs.changes.outputs.playwright_timeout_minutes) }}"
    )
    assert jobs["title-policy"]["timeout-minutes"] == "${{ fromJSON(needs.changes.outputs.title_timeout_minutes) }}"
    assert jobs["checks"]["timeout-minutes"] == "${{ fromJSON(needs.changes.outputs.checks_timeout_minutes || '5') }}"
    assert _wall_budgets() == {"warm": 8040, "cold": 8040}


def test_router_emits_scoping_and_tree_attestation_contracts() -> None:
    changes = _jobs()["changes"]
    outputs = changes["outputs"]
    assert outputs["affected_packages"] == "${{ steps.gate.outputs.affected_packages }}"
    assert outputs["test_packages"] == "${{ steps.gate.outputs.test_packages }}"
    assert outputs["build_backend"] == "${{ steps.gate.outputs.build_backend }}"

    steps = _steps(changes)
    evidence = next(step for step in steps if step.get("name") == "Gather protected-main evidence")
    evidence_command = evidence["run"]
    assert "ci-checks gate-evidence" in evidence_command
    assert '--event "$GITHUB_EVENT_NAME"' in evidence_command
    assert '--repository "$GITHUB_REPOSITORY"' in evidence_command
    assert '--head-sha "$GITHUB_SHA"' in evidence_command
    assert '--github-env "$GITHUB_ENV"' in evidence_command

    write = next(step for step in steps if step.get("name") == "Write Checks attestation")
    attestation_condition = "github.event_name == 'pull_request' && github.event.action != 'edited'"
    assert write["if"] == attestation_condition
    write_command = write["run"]
    assert "git rev-parse 'HEAD^{tree}'" in write_command
    for field in ("tested_tree_sha", "event_action", "commit_class", "run_id"):
        assert field in write_command

    upload = next(step for step in steps if step.get("name") == "Upload Checks attestation")
    assert upload["if"] == attestation_condition
    assert upload["with"] == {
        "name": "checks-attestation",
        "path": "checks-attestation.json",
        "if-no-files-found": "error",
    }


def test_title_edits_have_independent_concurrency_and_check_identities() -> None:
    workflow = load_workflow(_CHECKS)
    assert workflow["concurrency"] == {
        "group": (
            "${{ github.workflow }}-${{ github.event.pull_request.number || github.ref }}"
            "-${{ github.event.action == 'edited' }}"
        ),
        "cancel-in-progress": "${{ github.event_name == 'pull_request' }}",
    }

    jobs = workflow["jobs"]
    substantive = jobs["checks"]
    # Two copies, one per path, and the job gates make them mutually exclusive: the worker owns
    # every event the short-circuit does not claim, and `title-policy` owns the proven edit, where
    # the worker is skipped. The defect this guards is copies that can run together.
    title_policy = {
        job_id: step
        for job_id, job in jobs.items()
        for step in job.get("steps", [])
        if step.get("name") == "Validate PR title (merge commit subject)"
    }
    assert set(title_policy) == {"worker", "title-policy"}
    assert "needs.changes.outputs.commitlint_expected == 'true'" in str(title_policy["worker"]["if"])
    assert "needs.changes.outputs.title_only != 'true'" in str(jobs["worker"]["if"])
    assert jobs["title-policy"]["if"] == "needs.changes.outputs.title_only == 'true'"
    title_setup = next(
        step for step in _steps(jobs["title-policy"]) if step.get("name") == "Set up commit policy environment"
    )
    assert title_setup["with"] == {
        "node": "true",
        "ready-cache": "true",
        "payload": "node",
        "runner-class": "${{ needs.changes.outputs.runner_class }}",
    }
    assert substantive["name"] == "Checks"
    # Checks is a required context on protected main, so suppressing it on an edited event would
    # leave the head without its required conclusion and let a title-only pass stand for validation.
    assert substantive["if"] == "always()"


def test_changes_job_computes_gate_from_full_history() -> None:
    changes = _jobs()["changes"]
    assert changes["name"] == "Router"
    assert "needs" not in changes

    steps = _steps(changes)
    checkout = next(step for step in steps if "uses" in step)
    assert checkout["with"] == {"fetch-depth": 0, "persist-credentials": False}

    gate = next(step for step in steps if step.get("name") == "Compute change gate")
    env = gate["env"]
    assert (
        env["BASE"] == "${{ github.event_name == 'push' && github.event.before || github.event.pull_request.base.sha }}"
    )
    command = gate["run"]
    assert "ci-checks gate" in command
    assert '--github-output "$GITHUB_OUTPUT"' in command
    assert '--summary "$GITHUB_STEP_SUMMARY"' in command


def test_hadolint_uses_canonical_recipe_with_summary_fallback() -> None:
    lint_steps = _steps(_jobs()["worker"])
    hadolint = next(step for step in lint_steps if step.get("name") == "Lint Dockerfiles (hadolint)")

    command = hadolint["run"]
    assert "just docker-lint" in command
    assert "lint-results/hadolint.log" in command


def test_protected_main_reuse_preserves_cache_publication_and_checks_verdict() -> None:
    outputs = render_outputs(GateDecision(protected_main_smoke=True), (), "push")
    assert json.loads(outputs["worker_units"]) == ["frontend"]

    jobs = _jobs()
    worker_setup = next(step for step in _steps(jobs["worker"]) if step.get("uses") == "./.github/actions/setup-ci")
    assert worker_setup["with"]["payload"] == "${{ matrix.unit == 'python' && 'python' || 'full' }}"
    assert worker_setup["with"]["save-ready-cache"] == (
        "${{ (matrix.unit == 'python' || matrix.unit == 'frontend') "
        "&& (needs.changes.outputs.broad == 'true' || github.event_name == 'push') }}"
    )

    checks = jobs["checks"]
    assert checks["name"] == "Checks"
    assert checks["if"] == "always()"
    assert "worker" in checks["needs"]
    assert _protected_main_fan_in("success").returncode == 0
    rejected = _protected_main_fan_in("skipped")
    assert rejected.returncode != 0
    assert "worker was selected but concluded skipped" in rejected.stderr


def test_required_checks_uses_summary_and_sole_attestation_artifact() -> None:
    jobs = _jobs()
    changes = jobs["changes"]
    outputs = changes["outputs"]
    assert set(outputs) == set(FLAG_NAMES) | {
        "affected_packages",
        "test_packages",
        "commit_class",
        "standard",
        "broad",
        "worker_units",
        # Splits the class signal: the step disjuncts consume this, the scope selectors do not.
        "broad_unbounded",
        "worker_timeout_minutes",
        "runner_target",
        "runner_class",
        "tier_1_state",
        "tier_2_state",
        "tier_3_state",
        "playwright_timeout_minutes",
        "title_timeout_minutes",
        "checks_timeout_minutes",
        "protected_main_smoke",
        "commitlint_expected",
        "full",
        # Informational only: they let the fan-in tell "skipped, not selected" apart from
        # "skipped, a prior run already proved this tree".
        "title_only",
        "reused_run_id",
        "labels",
    }

    change_steps = _steps(changes)
    gate = next(step for step in change_steps if step.get("name") == "Compute change gate")
    gate_command = gate["run"]
    assert '--summary "$GITHUB_STEP_SUMMARY"' in gate_command

    uploads = [
        step
        for job in jobs.values()
        for step in _steps(job)
        if str(step.get("uses", "")).startswith("actions/upload-artifact@")
        and step["with"]["name"] == "checks-attestation"
    ]
    assert len(uploads) == 1
    assert uploads[0]["with"] == {
        "name": "checks-attestation",
        "path": "checks-attestation.json",
        "if-no-files-found": "error",
    }

    checks = jobs["checks"]
    assert checks["permissions"] == {
        "actions": "read",
        "contents": "read",
    }
    checks_steps = _steps(checks)
    download = next(step for step in checks_steps if step.get("name") == "Download router attestation")
    assert download["with"] == {
        "name": "checks-attestation",
        "path": "checks-attestation",
    }
    validate = next(step for step in checks_steps if step.get("name") == "Validate router attestation")
    validate_command = validate["run"]
    for field in ("run_id", "event_action", "commit_class", "tested_tree_sha"):
        assert field in validate_command
    assert "checks-attestation/checks-attestation.json" in validate_command
    assert checks["runs-on"] == "${{ fromJSON(needs.changes.outputs.runner_target || '\"ubuntu-24.04\"') }}"
    assert checks["timeout-minutes"] == "${{ fromJSON(needs.changes.outputs.checks_timeout_minutes || '5') }}"
    for job_name in ("worker", "playwright-image", "title-policy"):
        assert "||" not in str(jobs[job_name]["runs-on"])


def test_workflow_delegates_accounting_to_the_python_subcommand() -> None:
    report = next(step for step in _steps(_jobs()["checks"]) if step.get("name") == "Report workflow accounting")
    assert report["run"] == ('python3 scripts/ci/src/ci_checks/checks/workflow.py accounting "$GITHUB_STEP_SUMMARY"')
    assert report["env"]["COMMIT_CLASS"] == "${{ needs.changes.outputs.commit_class }}"
    assert "CONTAINER_SELECTED" not in report["env"]
    assert "PLAYWRIGHT_SELECTED" not in report["env"]
    assert _wall_budgets() == {"warm": 8040, "cold": 8040}
    assert _jobs()["playwright-image"]["timeout-minutes"] == (
        "${{ fromJSON(needs.changes.outputs.playwright_timeout_minutes) }}"
    )


def test_routing_entrypoint_emits_complete_atomic_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "route-output"
    summary = tmp_path / "summary"
    calls: list[list[str]] = []

    def inventory(args: list[str]) -> object:
        calls.append(args)
        return _inventory(_runner("nohiki-runner-01", "nohiki-t3"))

    monkeypatch.setenv("GH_TOKEN", "redacted")
    monkeypatch.setattr(workflow_helpers, "_gh_json", inventory)
    workflow_helpers.route_cmd("owner/repository", output, summary)
    emitted = dict(line.split("=", 1) for line in output.read_text(encoding="utf-8").splitlines())
    assert emitted == route_outputs(select_runner(_inventory(_runner("nohiki-runner-01", "nohiki-t3"))))
    assert calls == [["--paginate", "--slurp", "repos/owner/repository/actions/runners?per_page=100"]]
    rendered = summary.read_text(encoding="utf-8")
    assert "RUNNER_INVENTORY_TOKEN" not in rendered
    assert "| Selected class | `nohiki-t3` |" in rendered


def test_inventory_request_retries_once_then_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def unavailable(_args: list[str]) -> object:
        nonlocal calls
        calls += 1
        msg = "untrusted response"
        raise ValueError(msg)

    output = tmp_path / "route-output"
    monkeypatch.setenv("GH_TOKEN", "redacted")
    monkeypatch.setattr(workflow_helpers, "_gh_json", unavailable)
    workflow_helpers.route_cmd("owner/repository", output, tmp_path / "summary")
    emitted = dict(line.split("=", 1) for line in output.read_text(encoding="utf-8").splitlines())
    assert calls == 2
    assert emitted["runner_target"] == '"ubuntu-24.04"'
    assert emitted["runner_class"] == "hosted"


def test_missing_inventory_secret_fails_closed_without_an_api_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GH_TOKEN", raising=False)

    def unexpected_call(_args: list[str]) -> object:
        pytest.fail("inventory API must not be called without its credential")

    monkeypatch.setattr(workflow_helpers, "_gh_json", unexpected_call)
    output = tmp_path / "route-output"
    workflow_helpers.route_cmd("owner/repository", output, tmp_path / "summary")
    emitted = dict(line.split("=", 1) for line in output.read_text(encoding="utf-8").splitlines())
    assert emitted["runner_target"] == '"ubuntu-24.04"'
    assert emitted["runner_class"] == "hosted"


def test_router_failure_without_outputs_still_runs_hosted_fan_in() -> None:
    jobs = _jobs()
    fan_in = jobs["checks"]
    assert fan_in["if"] == "always()"
    assert fan_in["runs-on"] == "${{ fromJSON(needs.changes.outputs.runner_target || '\"ubuntu-24.04\"') }}"
    assert fan_in["timeout-minutes"] == "${{ fromJSON(needs.changes.outputs.checks_timeout_minutes || '5') }}"
    for job_name in ("worker", "playwright-image", "title-policy"):
        assert "||" not in str(jobs[job_name]["runs-on"])


def test_summary_entrypoint_writes_the_parsed_workflow_report(tmp_path: Path) -> None:
    step = next(step for step in _steps(_jobs()["changes"]) if step.get("name") == "Open router summary")
    summary = tmp_path / "summary.md"

    result = _run_workflow_step(
        step,
        workflow_values={"EVENT_ACTION": "opened"},
        runner_values={
            "GITHUB_EVENT_NAME": "pull_request",
            "GITHUB_RUN_ID": "42",
            "GITHUB_SHA": "0123456789abcdef",
            "GITHUB_STEP_SUMMARY": str(summary),
        },
    )

    assert result.returncode == 0, result.stderr
    assert summary.exists()
    rendered = summary.read_text(encoding="utf-8")
    assert rendered.startswith("## Router\n")
    assert "| Run | `42` |" in rendered
    assert "| Event | `pull_request` (`opened`) |" in rendered
    assert "| Tested SHA | `0123456` |" in rendered


def test_container_verdict_entrypoint_enforces_and_attests_the_parsed_step(tmp_path: Path) -> None:
    step = next(step for step in _steps(_jobs()["worker"]) if step.get("name") == "Attest container contract execution")
    output = tmp_path / "container-output"
    successful_values = {
        "BUILDX_OUTCOME": "success",
        "FRONTEND_SMOKE_EXPECTED": "true",
        "IMAGE_OUTCOME": "success",
        "OTEL_EXPECTED": "false",
        "OTEL_OUTCOME": "skipped",
        "SMOKE_OUTCOME": "success",
        "CONTAINER_TESTS_EXPECTED": "true",
        "CONTAINER_TESTS_OUTCOME": "success",
        "CONTAINER_TESTS_EXECUTED": "true",
    }

    succeeded = _run_workflow_step(
        step,
        workflow_values=successful_values,
        runner_values={"GITHUB_OUTPUT": str(output)},
    )

    assert succeeded.returncode == 0, succeeded.stderr
    assert output.exists()
    assert output.read_text(encoding="utf-8") == "executed=true\n"
    vacuous = _run_workflow_step(
        step,
        workflow_values=successful_values | {"CONTAINER_TESTS_EXECUTED": "false"},
        runner_values={"GITHUB_OUTPUT": str(tmp_path / "vacuous-container-output")},
    )
    assert vacuous.returncode == 1
    assert vacuous.stderr == "container-tests succeeded without execution evidence\n"

    failed = _run_workflow_step(
        step,
        workflow_values=successful_values | {"IMAGE_OUTCOME": "failure"},
        runner_values={"GITHUB_OUTPUT": str(tmp_path / "failed-container-output")},
    )
    assert failed.returncode == 1
    assert failed.stderr == "frontend-image was selected but concluded failure\n"


def test_accounting_entrypoint_enforces_the_parsed_workflow_wall_budget(tmp_path: Path) -> None:
    step = next(step for step in _steps(_jobs()["checks"]) if step.get("name") == "Report workflow accounting")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_gh = fake_bin / "gh"
    fake_gh.write_text(
        """#!/usr/bin/env python3
import json
import os
import sys
from datetime import datetime, timedelta, timezone

if any("/jobs?" in argument for argument in sys.argv):
    print(json.dumps([{"jobs": []}]))
else:
    started = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(
        seconds=int(os.environ["FAKE_CONTROLLABLE_SECONDS"])
    )
    print(json.dumps({"run_started_at": started.isoformat().replace("+00:00", "Z")}))
""",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)
    workflow_values = {
        "COMMIT_CLASS": "standard",
        "WORKER_DEADCODE_CACHE_HIT": "true",
        "WORKER_DEADCODE_CACHE_MISSED": "",
        "WORKER_READY_CACHE_HIT": "true",
        "WORKER_READY_CACHE_MISSED": "",
    }
    runner_environment = {
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
    }
    below_summary = tmp_path / "below-summary.md"

    below = _run_workflow_step(
        step,
        workflow_values=workflow_values,
        runner_values=runner_environment
        | {
            "FAKE_CONTROLLABLE_SECONDS": str(WARM_WALL_BUDGET_SECONDS - 10),
            "GITHUB_STEP_SUMMARY": str(below_summary),
        },
    )

    assert below.returncode == 0, below.stderr
    below_report = below_summary.read_text(encoding="utf-8")
    assert f"| Wall budget seconds | {WARM_WALL_BUDGET_SECONDS} |" in below_report
    assert "| Wall budget class | warm |" in below_report

    breached_summary = tmp_path / "breached-summary.md"
    breached = _run_workflow_step(
        step,
        workflow_values=workflow_values,
        runner_values=runner_environment
        | {
            "FAKE_CONTROLLABLE_SECONDS": str(WARM_WALL_BUDGET_SECONDS),
            "GITHUB_STEP_SUMMARY": str(breached_summary),
        },
    )

    assert breached.returncode == 1
    assert "wall budget breached: class=warm observed_controllable=" in breached.stderr
    assert f"budget<{WARM_WALL_BUDGET_SECONDS}s" in breached.stderr


def test_runtime_accounting_starts_at_the_first_non_skipped_job() -> None:
    result = _accounting_span(
        [
            {
                "name": "Skipped before dispatch",
                "started_at": "2026-07-23T00:00:05Z",
                "conclusion": "skipped",
            },
            {
                "name": "Router",
                "started_at": "2026-07-23T00:00:30Z",
                "conclusion": "success",
            },
            {
                "name": "Checks",
                "started_at": "2026-07-23T00:00:40Z",
                "conclusion": None,
            },
        ]
    )
    assert result.run_seconds == 120
    assert result.controllable_seconds == 90
    assert result.dispatch_seconds == 30
    assert result.start_basis == "first non-skipped job start from the Actions jobs API"


@pytest.mark.parametrize("started_at", [None, "not-a-timestamp"])
def test_runtime_accounting_falls_back_to_run_start_for_an_unusable_first_job_start(started_at: object) -> None:
    result = _accounting_span(
        [
            {
                "name": "Router",
                "started_at": started_at,
                "conclusion": "success",
            }
        ]
    )
    assert result.controllable_seconds == result.run_seconds
    assert result.dispatch_seconds == 0
    assert result.start_basis == "run_started_at fallback: first non-skipped job start unavailable or invalid"


def test_zero_step_job_has_zero_runner_minutes() -> None:
    now = datetime(2026, 7, 23, 0, 2, tzinfo=UTC)
    assert runner_minute_totals([], now) == (0, 0)
    accounting = derive_accounting(
        "2026-07-23T00:00:00Z",
        now,
        [],
        ready_missed="",
        ready_hit="",
        deadcode_missed="",
        deadcode_hit="",
    )
    assert accounting.avoided_minutes == 0
    assert accounting.avoided_cost_usd == "0.000"
    assert accounting.reconstructed_hosted_minutes == 0
    assert accounting.reconstructed_hosted_cost_usd == "0.000"
    assert accounting.jobs == ()


def test_fan_in_consumes_the_worker_cache_signals() -> None:
    report = next(step for step in _steps(_jobs()["checks"]) if step.get("name") == "Report workflow accounting")
    assert report["env"]["WORKER_READY_CACHE_MISSED"] == "${{ needs.worker.outputs.ready_cache_missed }}"
    assert report["env"]["WORKER_READY_CACHE_HIT"] == "${{ needs.worker.outputs.ready_cache_hit }}"
    assert report["env"]["WORKER_DEADCODE_CACHE_MISSED"] == "${{ needs.worker.outputs.deadcode_cache_missed }}"
    assert report["env"]["WORKER_DEADCODE_CACHE_HIT"] == "${{ needs.worker.outputs.deadcode_cache_hit }}"
    assert "worker" in _jobs()["checks"]["needs"]

    action_outputs = cast("dict[str, object]", load_mapping(_SETUP_CI)["outputs"])
    assert {"ready-cache-hit", "skylos-cache-hit"} <= action_outputs.keys()
    setup = next(step for step in _steps(_jobs()["worker"]) if step.get("uses") == "./.github/actions/setup-ci")
    assert setup["id"] == "setup-ci"


def test_cold_and_warm_budget_classification_and_breach_boundary() -> None:
    cold = select_wall_budget("true", "", "", "true")
    assert cold.seconds == 8040
    assert cold.classification == "cold"
    assert cold.basis == (
        "ready-cache primary key missed by at least one worker leg; dead-code static cache primary key restored"
    )
    assert cold.seconds - 1 < cold.seconds
    assert cold.seconds >= cold.seconds
    cold_inside = derive_accounting(
        "2026-07-23T00:00:00Z",
        datetime(2026, 7, 23, 2, 13, 59, tzinfo=UTC),
        [],
        ready_missed="true",
        ready_hit="",
        deadcode_missed="",
        deadcode_hit="true",
    )
    enforce_wall_budget(cold_inside)
    cold_breached = derive_accounting(
        "2026-07-23T00:00:00Z",
        datetime(2026, 7, 23, 2, 14, tzinfo=UTC),
        [],
        ready_missed="true",
        ready_hit="",
        deadcode_missed="",
        deadcode_hit="true",
    )
    with pytest.raises(ValueError, match=r"class=cold observed_controllable=8040s budget<8040s"):
        enforce_wall_budget(cold_breached)

    warm = select_wall_budget("", "true", "", "true")
    assert warm.seconds == 8040
    assert warm.classification == "warm"
    assert warm.basis == (
        "ready-cache primary key restored by every reporting worker leg; dead-code static cache primary key restored"
    )
    assert warm.seconds - 1 < warm.seconds
    assert warm.seconds >= warm.seconds
    warm_inside = derive_accounting(
        "2026-07-23T00:00:00Z",
        datetime(2026, 7, 23, 2, 13, 59, tzinfo=UTC),
        [],
        ready_missed="",
        ready_hit="true",
        deadcode_missed="",
        deadcode_hit="true",
    )
    enforce_wall_budget(warm_inside)
    warm_breached = derive_accounting(
        "2026-07-23T00:00:00Z",
        datetime(2026, 7, 23, 2, 14, tzinfo=UTC),
        [],
        ready_missed="",
        ready_hit="true",
        deadcode_missed="",
        deadcode_hit="true",
    )
    with pytest.raises(ValueError, match=r"class=warm observed_controllable=8040s budget<8040s"):
        enforce_wall_budget(warm_breached)


@pytest.mark.parametrize(
    ("ready_missed", "ready_hit", "deadcode_missed", "deadcode_hit", "basis"),
    [
        ("", "true", "true", "", "dead-code static cache primary key not restored"),
        ("", "true", "", "", "dead-code static cache hit unreported"),
        ("", "true", "", "not-a-cache-result", "dead-code static cache signal invalid"),
        ("", "", "", "true", "ready-cache primary key hit unreported"),
        ("true", "true", "", "true", "ready-cache primary key hit on one worker leg and missed on another"),
    ],
)
def test_non_restored_or_ambiguous_cache_signals_take_the_cold_budget(
    ready_missed: str,
    ready_hit: str,
    deadcode_missed: str,
    deadcode_hit: str,
    basis: str,
) -> None:
    budget = select_wall_budget(ready_missed, ready_hit, deadcode_missed, deadcode_hit)
    assert budget.classification == "cold"
    assert budget.seconds == COLD_WALL_BUDGET_SECONDS
    assert basis in budget.basis


def test_accounting_render_distinguishes_running_completed_and_both_skips() -> None:
    now = datetime(2026, 7, 23, 0, 1, tzinfo=UTC)
    jobs = [
        {
            "name": "Checks",
            "started_at": "2026-07-23T00:00:00Z",
            "completed_at": None,
            "conclusion": None,
            "labels": ["ubuntu-24.04"],
        },
        {
            "name": "Router",
            "started_at": "2026-07-23T00:00:00Z",
            "completed_at": "2026-07-23T00:01:01Z",
            "conclusion": "success",
            "labels": ["ubuntu-24.04"],
        },
        {
            "name": "Scoped worker (python)",
            "started_at": "2026-07-23T00:00:00Z",
            "completed_at": "2026-07-23T00:00:00Z",
            "conclusion": "skipped",
            "labels": ["self-hosted", "Linux", "X64", "nohiki", "nohiki-t3"],
        },
        {
            "name": "Playwright runner image",
            "started_at": "2026-07-23T00:00:00Z",
            "completed_at": "2026-07-23T00:00:00Z",
            "conclusion": "skipped",
            "labels": ["ubuntu-24.04"],
        },
    ]
    expected = {
        "worker": True,
        "Playwright runner image": False,
        "Title policy": True,
        "Router": True,
        "Checks": True,
    }
    accounting = derive_accounting(
        "2026-07-23T00:00:00Z",
        now,
        jobs,
        ready_missed="",
        ready_hit="true",
        deadcode_missed="",
        deadcode_hit="true",
    )
    rendered = render_accounting(accounting, expected, "18234567890", now)
    assert "| Checks | 60 | 1 | reconstructed hosted | running (this job) |" in rendered
    assert "| Router | 61 | 2 | reconstructed hosted | success |" in rendered
    assert "| Scoped worker (python) | 0 | 0 | avoided | skipped: already proven by run 18234567890 |" in rendered
    assert "| Playwright runner image | 0 | 0 | reconstructed hosted | skipped: not selected |" in rendered
    assert "| Hosted-equivalent avoided minutes | 0 |" in rendered
    assert "| Hosted-equivalent avoided cost USD | 0.000 |" in rendered
    assert "| Reconstructed hosted minutes | 3 |" in rendered
    assert "| Reconstructed hosted cost USD | 0.018 |" in rendered
    assert "billing API, not this reconstruction" in rendered


def test_runner_minutes_never_label_actual_hosted_execution_as_avoided() -> None:
    now = datetime(2026, 7, 23, 0, 2, tzinfo=UTC)
    jobs = [
        {
            "started_at": "2026-07-23T00:00:00Z",
            "completed_at": "2026-07-23T00:01:01Z",
            "labels": ["self-hosted", "Linux", "X64", "nohiki", "nohiki-t1"],
        },
        {
            "started_at": "2026-07-23T00:00:00Z",
            "completed_at": "2026-07-23T00:00:59Z",
            "labels": ["ubuntu-24.04"],
        },
    ]
    assert runner_minute_totals(jobs, now) == (2, 1)


def test_router_open_summary_text_is_unchanged() -> None:
    assert render_open_summary(
        "router",
        {
            "GITHUB_RUN_ID": "123",
            "GITHUB_EVENT_NAME": "pull_request",
            "EVENT_ACTION": "opened",
            "GITHUB_SHA": "1234567890abcdef",
        },
    ) == (
        "## Router\n\n"
        "Classifies the tested diff into lane flags and a commit class. Runs no checks itself.\n\n"
        "| Context | Value |\n"
        "|---|---|\n"
        "| Run | `123` |\n"
        "| Event | `pull_request` (`opened`) |\n"
        "| Tested SHA | `1234567` |\n\n"
        "### Results\n"
    )


def test_digest_freshness_workflow_probes_on_schedule() -> None:
    workflow = load_workflow(_FRESHNESS)
    triggers = workflow["on"]
    if not isinstance(triggers, dict):
        pytest.fail("digest freshness workflow triggers must be a mapping")
    assert "workflow_dispatch" in triggers
    schedule = triggers["schedule"]
    assert schedule[0]["cron"]
    assert workflow["permissions"] == {"contents": "read"}
    jobs = workflow["jobs"]
    probe = jobs["probe"]
    assert probe["permissions"] == {
        "actions": "read",
        "contents": "read",
        "issues": "write",
    }
    assert set(jobs) == {"probe"}
    commands = "\n".join(step.get("run", "") for step in probe["steps"])
    assert "ci-checks image-freshness" in commands
    assert "gh issue" in commands
    assert probe["runs-on"] == ["self-hosted", "linux", "x64", "nohiki"]
    sweep_steps = [step for step in probe["steps"] if step.get("name") == "Sweep dependency deprecations"]
    assert len(sweep_steps) == 1
    assert sweep_steps[0]["if"] == "always()"
    assert sweep_steps[0]["continue-on-error"] is True
    assert "ci-checks deprecation-sweep" in sweep_steps[0]["run"]


def test_gated_jobs_depend_on_change_outputs() -> None:
    jobs = _jobs()
    ungated = {"changes", "checks"}
    for job_id, job in jobs.items():
        if job_id in ungated:
            continue
        assert "changes" in job["needs"], job_id
        condition = job.get("if")
        assert condition is not None, job_id
        assert "needs.changes.outputs." in condition, job_id


def test_checks_aggregator_only_allows_router_sanctioned_skips() -> None:
    checks = _jobs()["checks"]
    fan_in = next(step for step in _steps(checks) if step.get("name") == "Require every selected check")
    command = str(fan_in["run"])
    assert command.endswith("workflow.py verdict checks")
    assert fan_in["env"]["COMMIT_CLASS"] == "${{ needs.changes.outputs.commit_class }}"
    assert fan_in["env"]["STANDARD"] == "${{ needs.changes.outputs.standard }}"
    assert fan_in["env"]["BROAD"] == "${{ needs.changes.outputs.broad }}"

    required = {
        "worker": ("WORKER_RESULT", "WORK_EXPECTED"),
        "playwright-image": ("PLAYWRIGHT_RESULT", "PLAYWRIGHT_EXPECTED"),
        "title-policy": ("TITLE_POLICY_RESULT", "TITLE_POLICY_EXPECTED"),
    }
    assert set(checks["needs"]) == {"changes"} | set(required)
    for job_id, (result_name, expectation_name) in required.items():
        assert f"needs.{job_id}.result" in str(fan_in["env"][result_name])
        assert expectation_name in fan_in["env"]
    assert "BROAD_EXPECTED" not in fan_in["env"]
    assert "WORKER_CONTAINER_CONTRACTS" in fan_in["env"]
    assert "needs.container-contracts" not in str(fan_in)
    assert "broad-environment" not in str(fan_in)


def test_typescript_quality_runs_once_per_class_with_ci_native_commands() -> None:
    steps = {step.get("name"): step for step in _steps(_jobs()["worker"])}
    assert "biome check --reporter=sarif" in steps["Lint frontend"]["run"]
    assert "biome-frontend.sarif" in steps["Lint frontend"]["run"]
    assert "just fe-fsd" in steps["Lint frontend architecture (Steiger)"]["run"]
    assert "exec tsc --noEmit" in steps["Typecheck edge worker"]["run"]
    assert "exec vitest run" in steps["Test edge worker"]["run"]
    assert str(steps["Test frontend"]["run"]).endswith("just fe-test")
    assert steps["Test frontend"]["env"]["VITEST_MAX_WORKERS"] == (
        "${{ needs.changes.outputs.runner_class == 'hosted' && '2' || '' }}"
    )


def test_lint_diagnostics_are_uploaded_and_summarized_with_least_privilege() -> None:
    worker = _jobs()["worker"]
    assert worker["permissions"]["security-events"] == "write"
    steps = {step.get("name"): step for step in _steps(worker)}
    detection = steps["Detect code scanning availability"]
    assert detection["env"]["REPOSITORY_PUBLIC"] == (
        "${{ github.event.repository && github.event.repository.private == false }}"
    )
    assert "code-scanning/alerts?per_page=1" in detection["run"]
    assert "available=$available" in detection["run"]
    upload = steps["Upload lint diagnostics"]
    assert upload["uses"] == ("github/codeql-action/upload-sarif@e4fba868fa4b1b91e1fdab776edc8cfbe6e9fb81")
    assert "steps.code-scanning.outputs.available == 'true'" in upload["if"]
    assert "head.repo.full_name == github.repository" in upload["if"]
    assert upload["with"] == {
        "sarif_file": "lint-results",
        "category": "lint/${{ matrix.unit }}",
        "wait-for-processing": False,
    }
    summary = steps["Summarize lint diagnostics"]
    assert summary["if"] == "always() && matrix.unit == 'frontend'"
    assert "ci-checks lint-report" in summary["run"]


def test_setup_and_secret_scan_keep_one_definition_and_one_writer_per_payload() -> None:
    standard = _jobs()["worker"]
    job_env = standard["env"]
    assert "lint_markdown" not in str(job_env["NIX_SETUP_SELECTED"])
    assert "commitlint_expected" not in str(job_env["NIX_SETUP_SELECTED"])
    assert "lint_markdown" in str(job_env["NODE_SETUP_SELECTED"])
    assert "protected_main_smoke != 'true'" in str(job_env["NODE_SETUP_SELECTED"])
    assert job_env["DOCS_ONLY"] == (
        "${{ needs.changes.outputs.standard == 'true' "
        "&& needs.changes.outputs.lint_markdown == 'true' "
        "&& needs.changes.outputs.affected_packages == '' }}"
    )

    steps = {step.get("name"): step for step in _steps(standard)}
    setup = steps["Set up selected environments"]
    assert setup["uses"] == "./.github/actions/setup-ci"
    assert setup["with"]["ready-cache"] == "${{ env.NIX_SETUP_SELECTED }}"
    assert setup["with"]["node"] == "${{ env.NODE_SETUP_SELECTED }}"
    # Python and frontend are the stable writers for their distinct payloads. Pull requests write
    # only for broad decisions; main pushes write for either class.
    assert setup["with"]["save-ready-cache"] == (
        "${{ (matrix.unit == 'python' || matrix.unit == 'frontend') "
        "&& (needs.changes.outputs.broad == 'true' || github.event_name == 'push') }}"
    )

    for name in ("Lint Python", "Check Python formatting"):
        lint_step = steps[name]
        assert lint_step["env"]["RUFF_CACHE_DIR"] == "${{ runner.temp }}/ruff-cache"
        assert "export UV_PROJECT_ENVIRONMENT=.venv" in lint_step["run"]
        assert ".venv-lint" not in lint_step["run"]
        # Broad lints the whole tree from the same definition that lints the diff on standard.
        assert lint_step["env"]["RUFF_SCOPE"] == ("${{ needs.changes.outputs.broad == 'true' && 'ALL' || 'CHANGED' }}")
    assert "--output-format=sarif" in str(steps["Lint Python"]["run"])
    assert "ruff-lint.sarif" in str(steps["Lint Python"]["run"])
    assert "just format-check" in str(steps["Check Python formatting"]["run"])
    assert "ruff-format.log" in str(steps["Check Python formatting"]["run"])
    assert "--exclude" not in lint_step["run"]
    # test_execution_attestations_are_not_scoped_to_one_commit_class.

    changed = steps["Scan changed content for secrets"]
    assert changed["if"] == "env.DOCS_ONLY == 'true'"
    assert 'git diff --binary "$BASE_SHA..$HEAD_SHA"' in changed["run"]
    assert "stdin --config /repo/.gitleaks.toml --no-banner --redact" in changed["run"]

    full = steps["Scan repository for secrets"]
    assert full["if"].endswith("env.DOCS_ONLY != 'true'")
    assert "just secrets-scan" in full["run"]


def test_native_overlap_is_memory_bounded_to_measured_low_rss_pairs() -> None:
    worker = _jobs()["worker"]
    groups = [step["parallel"] for step in worker["steps"] if "parallel" in step]
    names = [{nested["name"] for nested in group} for group in groups]

    assert all(len(group) == 2 for group in groups)
    assert names == [
        {"Check flake", "Check Lefthook version"},
        {"Lint frontend architecture (Steiger)", "Check i18n keys"},
        {"Scan architecture", "Check build backends"},
        {"Check API schema freshness", "Check image matrix parity"},
    ]
    standalone = {
        "Scan repository for secrets",
        "Typecheck backend",
        "Check selected dead code",
        "Typecheck frontend",
        "Run selected Python tests",
        "Run Node workspace contract tests",
        "Run Skylos cache contract tests",
        "Test frontend",
        "Check dependencies",
        "Check import boundaries",
        "Check test import closure",
    }
    assert standalone.isdisjoint(set().union(*names))
    assert all("background" not in step and "cancel" not in step for step in worker["steps"])


def test_deadcode_runs_once_with_split_static_cache_save() -> None:
    job = _jobs()["worker"]
    steps = _steps(job)
    deadcode = next(step for step in steps if step.get("name") == "Check selected dead code")
    assert job["env"]["SKYLOS_CACHE_DIR"] == "${{ github.workspace }}/.skylos"
    assert deadcode["env"]["SKYLOS_JOBS"] == "2"
    assert "--with" not in deadcode["run"]
    assert "just hygiene-deadcode-strict" in deadcode["run"]

    # Ruff and Skylos share a runner again, so the ordering the 196s rationale describes is
    # load-bearing here: ruff must not leave a .ruff_cache in the fingerprinted workspace.
    names = [step.get("name") for step in steps]
    assert names.index("Lint Python") < names.index("Check selected dead code")

    save = next(step for step in steps if step.get("name") == "Save Skylos static analysis cache")
    assert save["if"] == (
        "always() && (steps.deadcode.conclusion == 'success' || steps.deadcode.conclusion == 'failure') && "
        f"steps.deadcode.outputs.{STATIC_RESULT_OUTPUT} == 'true' && "
        "steps.setup-ci.outputs.skylos-cache-hit != 'true'"
    )
    assert save["with"]["path"] == "${{ github.workspace }}/.skylos"
    assert save["with"]["key"] == ("${{ steps.setup-ci.outputs.skylos-cache-primary-key }}")


def test_cache_summaries_use_observed_action_outputs() -> None:
    jobs = _jobs()
    setup_owners = {
        "worker",
        "title-policy",
    }
    for owner in setup_owners:
        steps = {step.get("name"): step for step in _steps(jobs[owner])}
        setup = next(step for step in steps.values() if step.get("uses") == "./.github/actions/setup-ci")
        assert setup["id"] == "setup-ci"
        report = next(step for name, step in steps.items() if name and name.startswith("Report "))
        assert report["env"]["CACHE_OUTCOMES"] == "${{ steps.setup-ci.outputs.cache-telemetry }}"
        assert "workflow.py summary report" in str(report["run"])

    assert render_cache_table("uv=cache-hit:1234567890abcdef1234567890abcdef") == (
        "| Cache | Outcome | Key |\n|---|---|---|\n| uv | cache hit | `12345678…` |"
    )

    router_steps = {step.get("name"): step for step in _steps(jobs["changes"])}
    router_setup = router_steps["Set up uv and Python"]
    assert router_setup["id"] == "setup-uv"
    router_report = router_steps["Report router cost"]
    assert router_report["env"]["UV_CACHE_HIT"] == "${{ steps.setup-uv.outputs.cache-hit }}"
    assert router_report["env"]["UV_CACHE_KEY"] == "${{ steps.setup-uv.outputs.cache-key }}"
    assert "workflow.py summary report router" in str(router_report["run"])

    workflow_text = _CHECKS.read_text(encoding="utf-8")
    assert "cache_hit=" not in workflow_text
    assert "setup-node-managed" not in workflow_text
    assert "buildx-managed" not in workflow_text
    # No job may name a cache outcome it never observed. `playwright-image` queries no
    # actions/cache entry at all and previously claimed `buildkit=unknown:none`; `title-policy`
    # claimed a bare `unknown:none` while its composite was in fact restoring caches.
    assert "cache_outcomes=" not in workflow_text
    assert "unknown:none" not in workflow_text


def test_python_test_packages_come_from_change_gate_in_both_classes() -> None:
    changes = _jobs()["changes"]
    assert changes["outputs"]["test_packages"] == "${{ steps.gate.outputs.test_packages }}"

    selected_tests = next(step for step in _steps(_jobs()["worker"]) if step.get("name") == "Run selected Python tests")
    assert selected_tests["env"]["TEST_PACKAGES"] == ("${{ needs.changes.outputs.test_packages }}")
    assert 'test -n "$TEST_PACKAGES"' in selected_tests["run"]
    assert '--packages "$TEST_PACKAGES"' in selected_tests["run"]


def test_label_sync_is_an_advisory_job_off_the_required_router_path() -> None:
    jobs = _jobs()
    changes = jobs["changes"]
    label_sync = jobs["label-sync"]
    assert changes["permissions"] == {
        "actions": "read",
        "contents": "read",
        "pull-requests": "read",
    }
    assert changes["outputs"]["labels"] == "${{ steps.gate.outputs.labels }}"
    assert label_sync["needs"] == ["changes"]
    assert label_sync["runs-on"] == "ubuntu-24.04"
    assert label_sync["timeout-minutes"] == 1
    assert label_sync["continue-on-error"] is True
    assert label_sync["permissions"] == {"issues": "write", "pull-requests": "write"}
    for name, job in jobs.items():
        if name == "label-sync":
            continue
        needs = job.get("needs", [])
        dependencies = [needs] if isinstance(needs, str) else needs
        assert "label-sync" not in dependencies

    sync = next(step for step in _steps(label_sync) if step.get("name") == "Sync area labels")
    assert sync["env"] == {
        "GH_TOKEN": "${{ github.token }}",
        "PR": "${{ github.event.pull_request.number }}",
        "REPO": "${{ github.repository }}",
        "LABELS": "${{ needs.changes.outputs.labels }}",
    }
    assert cast("dict[str, object]", sync)["shell"] == "bash"
    command = str(sync["run"])
    for operation in (
        'gh api --paginate --slurp "repos/${REPO}/issues/${PR}/labels?per_page=100"',
        'gh api "repos/${REPO}/labels/${encoded}"',
        'gh api --method PATCH "repos/${REPO}/labels/${encoded}"',
        'gh api --method POST "repos/${REPO}/labels"',
        'gh api --method POST "repos/${REPO}/issues/${PR}/labels"',
        'gh api --method DELETE "repos/${REPO}/issues/${PR}/labels/${encoded}"',
    ):
        assert operation in command
    assert "|| true" not in command


def test_required_checks_verdict_ignores_a_failed_advisory_job() -> None:
    """Executes the real fan-in with a red advisory job present in the run."""
    checks = _jobs()["checks"]
    fan_in = next(step for step in _steps(checks) if step.get("name") == "Require every selected check")
    assert "label-sync" not in str(fan_in)

    hostile = _run_workflow_step(
        fan_in,
        workflow_values={
            "BROAD": "false",
            "CHANGES_RESULT": "success",
            "COMMIT_CLASS": "standard",
            "CONTAINER_EXPECTED": "false",
            "FULL": "false",
            "NODE_GROUP_EXPECTED": "false",
            "PLAYWRIGHT_EXPECTED": "false",
            "PLAYWRIGHT_RESULT": "skipped",
            "STANDARD": "true",
            "TITLE_POLICY_EXPECTED": "false",
            "TITLE_POLICY_RESULT": "skipped",
            "WORKER_COMMITLINT": "",
            "WORKER_COMMITLINT_EXPECTED": "false",
            "WORKER_CONTAINER_CONTRACTS": "",
            "WORKER_NODE_GROUP": "",
            "WORKER_RESULT": "success",
            "WORK_EXPECTED": "true",
        },
        runner_values={"LABEL_SYNC_RESULT": "failure"},
    )

    assert hostile.returncode == 0, hostile.stderr


def test_label_sync_identifies_dependabot_from_the_immutable_pr_author() -> None:
    condition = str(_jobs()["label-sync"]["if"])

    assert "github.event.pull_request.user.login != 'dependabot[bot]'" in condition
    assert "github.actor" not in condition


def test_label_sync_skips_title_edits_that_can_overlap_substantive_runs() -> None:
    assert "github.event.action != 'edited'" in str(_jobs()["label-sync"]["if"])


def test_label_sync_reconciles_definitions_and_pr_membership(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_gh = fake_bin / "gh"
    fake_gh.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> "$GH_LOG"
case "$*" in
  "api --paginate --slurp repos/example/repo/issues/7/labels?per_page=100")
    printf '%s\\n' '[[{"name":"area:frontend"}]]'
    ;;
  "api repos/example/repo/labels/ci%3Afull-run")
    exit 1
    ;;
  *"repos/example/repo/issues/7/labels --input -")
    cat > /dev/null
    printf '{}\\n'
    ;;
  *)
    printf '{}\\n'
    ;;
esac
""",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)
    log = tmp_path / "gh.log"
    sync = next(step for step in _steps(_jobs()["label-sync"]) if step.get("name") == "Sync area labels")
    result = _run_workflow_step(
        sync,
        workflow_values={
            "GH_TOKEN": "test-token",
            "PR": "7",
            "REPO": "example/repo",
            "LABELS": json.dumps(
                [
                    {"name": "area:backend", "color": "1D76DB", "active": "true"},
                    {"name": "area:frontend", "color": "D4C5F9", "active": "false"},
                    {"name": "ci:full-run", "color": "B60205", "active": "true"},
                ],
                separators=(",", ":"),
            ),
        },
        runner_values={
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "GH_LOG": str(log),
        },
    )

    assert result.returncode == 0, result.stderr
    calls = log.read_text(encoding="utf-8").splitlines()
    assert any("--method PATCH repos/example/repo/labels/area%3Abackend" in call for call in calls)
    assert any("--method POST repos/example/repo/labels -f name=ci:full-run" in call for call in calls)
    assert any("--method DELETE repos/example/repo/issues/7/labels/area%3Afrontend" in call for call in calls)
    additions = [call for call in calls if "--method POST repos/example/repo/issues/7/labels --input -" in call]
    assert len(additions) == 2


@pytest.mark.parametrize("list_mode", ["failed", "malformed"])
def test_label_sync_rejects_untrusted_label_lists_before_writes(tmp_path: Path, list_mode: str) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_gh = fake_bin / "gh"
    fake_gh.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> "$GH_LOG"
case "$*" in
  "api --paginate --slurp repos/example/repo/issues/7/labels?per_page=100")
    if [[ "$LIST_MODE" == failed ]]; then
      exit 1
    fi
    printf '%s\\n' '{"name":"not-a-page-list"}'
    ;;
  *)
    printf '%s\\n' "unexpected write: $*" >&2
    exit 99
    ;;
esac
""",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)
    log = tmp_path / "gh.log"
    label_sync = _jobs()["label-sync"]
    sync = next(step for step in _steps(label_sync) if step.get("name") == "Sync area labels")
    result = _run_workflow_step(
        sync,
        workflow_values={
            "GH_TOKEN": "test-token",
            "PR": "7",
            "REPO": "example/repo",
            "LABELS": json.dumps(
                [{"name": "area:backend", "color": "1D76DB", "active": "true"}],
                separators=(",", ":"),
            ),
        },
        runner_values={
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "GH_LOG": str(log),
            "LIST_MODE": list_mode,
        },
    )

    assert result.returncode != 0
    # The command still fails closed, while Actions keeps that advisory failure out of Router.
    assert label_sync["continue-on-error"] is True
    assert log.read_text(encoding="utf-8").splitlines() == [
        "api --paginate --slurp repos/example/repo/issues/7/labels?per_page=100"
    ]


@pytest.mark.parametrize(("create_mode", "expected_returncode"), [("race", 0), ("failure", 1)])
def test_label_sync_tolerates_only_verified_concurrent_label_creation(
    tmp_path: Path,
    create_mode: str,
    expected_returncode: int,
) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_gh = fake_bin / "gh"
    fake_gh.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> "$GH_LOG"
case "$*" in
  "api --paginate --slurp repos/example/repo/issues/7/labels?per_page=100")
    printf '%s\\n' '[[]]'
    ;;
  "api repos/example/repo/labels/area%3Abackend")
    [[ -f "$CREATED" ]]
    ;;
  "api --method POST repos/example/repo/labels -f name=area:backend -f color=1D76DB -f description=Gate-managed label")
    if [[ "$CREATE_MODE" == race ]]; then
      touch "$CREATED"
    fi
    printf '%s\\n' 'HTTP 422: label already exists' >&2
    exit 1
    ;;
  "api --method POST repos/example/repo/issues/7/labels --input -")
    cat > /dev/null
    printf '{}\\n'
    ;;
  *)
    printf '%s\\n' "unexpected operation: $*" >&2
    exit 99
    ;;
esac
""",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)
    log = tmp_path / "gh.log"
    created = tmp_path / "created"
    sync = next(step for step in _steps(_jobs()["label-sync"]) if step.get("name") == "Sync area labels")
    result = _run_workflow_step(
        sync,
        workflow_values={
            "GH_TOKEN": "test-token",
            "PR": "7",
            "REPO": "example/repo",
            "LABELS": json.dumps(
                [{"name": "area:backend", "color": "1D76DB", "active": "true"}],
                separators=(",", ":"),
            ),
        },
        runner_values={
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "GH_LOG": str(log),
            "CREATED": str(created),
            "CREATE_MODE": create_mode,
        },
    )

    assert result.returncode == expected_returncode, result.stderr
    calls = log.read_text(encoding="utf-8").splitlines()
    assert calls.count("api repos/example/repo/labels/area%3Abackend") == 2
    additions = [call for call in calls if "repos/example/repo/issues/7/labels --input -" in call]
    assert len(additions) == (1 if create_mode == "race" else 0)


def test_router_syncs_only_the_gate_package_and_runs_it_without_resyncing() -> None:
    """The router owns one dependency install, scoped to the package that computes the gate."""
    changes = _jobs()["changes"]
    steps = _steps(changes)

    checkout = next(step for step in steps if "actions/checkout@" in str(step.get("uses", "")))
    assert checkout["with"]["fetch-depth"] == 0

    syncs = [step for step in steps if "uv sync" in str(step.get("run", ""))]
    assert [step["run"].strip() for step in syncs] == ["uv sync --locked --package ci-checks -q"]

    gate = next(step for step in steps if step.get("name") == "Compute change gate")
    assert "uv run --no-sync ci-checks gate " in gate["run"]


def test_gate_step_requests_the_affected_image_record_on_push_alone() -> None:
    gate = next(step for step in _steps(_jobs()["changes"]) if step.get("name") == "Compute change gate")
    assert gate["id"] == "gate"

    command = gate["run"]
    assert gate["env"]["EVENT"] == "${{ github.event_name }}"
    assert "--affected-images-record affected-images.json" in command
    # The option sits behind a push guard, so a pull_request run expands the array to nothing.
    assert '[ "$EVENT" = push ]' in command
    assert '"${record[@]}"' in command


def test_affected_image_record_uploads_immediately_after_the_gate_computes_it() -> None:
    steps = _steps(_jobs()["changes"])
    names = [step.get("name") for step in steps]
    upload = steps[names.index("Compute change gate") + 1]

    assert upload["name"] == "Upload affected image record"
    assert upload["if"] == "github.event_name == 'push'"
    assert upload["uses"].startswith("actions/upload-artifact@")
    assert upload["with"] == {
        "name": "affected-images",
        "path": "affected-images.json",
        "if-no-files-found": "error",
        "retention-days": 7,
    }


def test_push_and_pull_request_runs_each_upload_exactly_one_router_artifact() -> None:
    """The record is a push producer and the attestation a pull_request producer, never both."""
    uploads = [
        (step["with"]["name"], step["if"])
        for job in _jobs().values()
        for step in _steps(job)
        if "actions/upload-artifact@" in str(step.get("uses", ""))
    ]

    # A dict alone cannot count: duplicate artifact names would collapse and pass.
    assert len(uploads) == 2
    assert dict(uploads) == {
        "affected-images": "github.event_name == 'push'",
        "checks-attestation": "github.event_name == 'pull_request' && github.event.action != 'edited'",
    }


def test_router_publishes_the_image_selection_as_an_artifact_not_a_job_output() -> None:
    jobs = _jobs()
    assert set(jobs) == {"changes", "label-sync", "worker", "playwright-image", "title-policy", "checks"}

    # `image_matrix_parity` is a lane flag, not a build matrix; no other output may carry one.
    outputs = {name: value for name, value in jobs["changes"]["outputs"].items() if name not in FLAG_NAMES}
    assert not [name for name in outputs if "matrix" in name or "image" in name]
    assert not [name for name, value in outputs.items() if "matrix" in str(value) or "image" in str(value)]


def test_fan_in_container_verdict_reads_the_worker_not_a_retired_job() -> None:
    workflow = (_ROOT / ".github/workflows/checks.yml").read_text(encoding="utf-8")

    assert "needs.container-contracts" not in workflow, "fan-in still references the retired job"

    checks = _jobs()["checks"]
    step = next(s for s in _steps(checks) if s.get("name") == "Require every selected check")
    assert step["env"]["WORKER_CONTAINER_CONTRACTS"] == "${{ needs.worker.outputs.container_contracts_executed }}"
    assert "container-contracts" not in checks["needs"]
