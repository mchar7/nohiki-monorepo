import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from _documents import WorkflowJob, WorkflowStep, load_mapping, load_workflow, mapping_sequence_at
from ci_checks.core.change_gate import (
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


_CONTAINER_EXECUTORS = {
    "frontend_smoke": "container-contracts",
    "frontend_e2e": "playwright-image",
    "otel_collector": "container-contracts",
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
    assert f"needs.{expected_job}.result" in fan_in["run"]


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
    assert _decision_executors(jobs, flake) == {"worker", "container-contracts"}

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
        "container-contracts",
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
            "Typecheck backend",
            "Check selected dead code",
            "Check dependencies",
            "Scan architecture",
            "Check build backends",
            "Check API schema freshness",
            "Check image matrix parity",
            "Check proto compatibility",
            "Run Node workspace contract tests",
            "Run Skylos cache contract tests",
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
        },
        "python": {"Run selected Python tests"},
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
    assert "detect --source . --config .gitleaks.toml --no-banner --redact" in full_scan["run"]
    # Matrix units share one outputs map. The runner skips an output whose expression is the
    # empty string and never sends it (actions/runner src/Runner.Worker/JobExtension.cs:789-805),
    # so spelling the negative case as '' makes the unit that ran the step the only writer.
    # `false` is NOT empty by that check, so a boolean-valued expression would race instead.
    assert worker["outputs"] == {
        "node_group_executed": ("${{ steps.setup-ci.outputs.node-group-executed == 'true' && 'true' || '' }}"),
        "commitlint_executed": ("${{ steps.commitlint-range.outcome == 'success' && 'true' || '' }}"),
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

    for name, value in worker_outputs.items():
        assert name.endswith("_executed"), name
        # A per-unit claim may read steps and matrix state; a commit class is not per-unit.
        assert "needs.changes.outputs.standard" not in value, name
        assert "needs.changes.outputs.broad" not in value, name
        # The negative case must be empty so a unit that skipped the step contributes nothing.
        assert value.endswith("&& 'true' || '' }}"), name

    for name in ("WORKER_COMMITLINT_EXPECTED", "NODE_GROUP_EXPECTED"):
        assert "needs.changes.outputs.standard" not in str(env[name]), name
        assert "needs.changes.outputs.broad" not in str(env[name]), name

    # The Node expectation must track the same router flags the worker uses to request the
    # group. Compared as sets: disjunct order carries no meaning and is not a contract.
    def referenced_flags(expression: str) -> set[str]:
        return set(re.findall(r"needs\.changes\.outputs\.(\w+)", expression))

    assert referenced_flags(str(env["NODE_GROUP_EXPECTED"])) == referenced_flags(
        str(_jobs()["worker"]["env"]["NODE_SETUP_SELECTED"])
    )


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


def test_ready_cache_save_runs_on_every_event_behind_a_key_guard() -> None:
    steps = mapping_sequence_at(load_mapping(_SETUP_CI), "runs", "steps")
    save = next(step for step in steps if step.get("name") == "Save complete CI environment")
    condition = str(save["if"])
    assert "github.event_name" not in condition
    assert "steps.ready-cache.outputs.primary-key != ''" in condition


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
    # The 344s test step is the long pole and the only member of its payload leg.
    condition = str(run_tests["if"])
    assert "matrix.unit == 'python'" in condition
    assert "matrix.unit == 'frontend'" not in condition


def test_node_workspace_tests_run_where_the_payload_carries_node_modules() -> None:
    worker = _jobs()["worker"]
    steps = {step.get("name"): step for step in _steps(worker)}
    node_lane = steps["Run Node workspace contract tests"]
    assert f"{_CI_TESTS} -m {_NODE_WORKSPACE_MARKER}" in str(node_lane["run"])

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


def test_skylos_cache_tests_run_only_where_the_private_analyzer_is_installed() -> None:
    worker = _jobs()["worker"]
    steps = {step.get("name"): step for step in _steps(worker)}
    lane = steps["Run Skylos cache contract tests"]
    assert f"{_CI_TESTS} -m {_SKYLOS_MARKER}" in str(lane["run"])

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


def test_worker_guards_are_two_minutes_above_the_owner_wall_target() -> None:
    changes = _jobs()["changes"]
    assert changes["outputs"]["worker_timeout_minutes"] == ("${{ steps.guards.outputs.worker_timeout_minutes }}")
    guards = next(step for step in _steps(changes) if step.get("name") == "Derive worker guard")
    command = str(guards["run"])
    # One wall budget governs the whole file, so the guard derives one timeout for both classes.
    assert "standard|broad) wall_budget_seconds=600 ;;" in command
    assert re.findall(r"wall_budget_seconds=(\d+)", command) == ["600"]
    assert "hang_grace_minutes=2" in command
    assert "wall_budget_seconds / 60 + hang_grace_minutes" in command
    assert 600 // 60 + 2 == 12

    assert _jobs()["worker"]["timeout-minutes"] == ("${{ fromJSON(needs.changes.outputs.worker_timeout_minutes) }}")


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


def test_hadolint_enumerates_canonical_and_suffixed_dockerfiles() -> None:
    lint_steps = _steps(_jobs()["worker"])
    hadolint = next(step for step in lint_steps if step.get("name") == "Lint Dockerfiles (hadolint)")

    command = hadolint["run"]
    assert "'*Dockerfile'" in command
    assert "'*Dockerfile.*'" in command


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
        "protected_main_smoke",
        "commitlint_expected",
        "full",
        # Informational only: they let the fan-in tell "skipped, not selected" apart from
        # "skipped, a prior run already proved this tree".
        "title_only",
        "reused_run_id",
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


def test_runtime_accounting_reads_run_level_metadata() -> None:
    report = next(step for step in _steps(_jobs()["checks"]) if step.get("name") == "Report workflow accounting")
    command = report["run"]

    assert 'gh api "repos/$REPO/actions/runs/$RUN_ID"' in command


def test_runtime_accounting_enforces_only_the_owner_wall_target() -> None:
    report = next(step for step in _steps(_jobs()["checks"]) if step.get("name") == "Report workflow accounting")
    command = report["run"]
    env = report["env"]

    assert "if ((wall_seconds >= wall_budget_seconds)); then" in command
    assert "exit 1" in command

    # The owner set one wall target, 10 minutes, and no billable-minute figure. Billable is
    # reported and never enforced; the dollar ceiling binds at the account spending limit,
    # because it is a monthly cumulative quantity no single run can measure.
    assert re.findall(r"wall_budget_seconds=(\d+)", command) == ["600"]
    assert "billable_budget_minutes" not in command
    assert "| Reconstructed billable minutes | $billable_minutes |" in command
    assert "| Estimated cost USD | $estimated_cost_usd |" in command
    assert "budget_failure" not in command
    # R was retired: R <= 3 rearranges to W >= 20B, a lower bound on wall time, so it could only fire
    # on runs that already passed both real ceilings. It punished intra-job speedups.
    assert "ratio" not in command
    assert "CONTAINER_SELECTED" not in env
    assert "PLAYWRIGHT_SELECTED" not in env
    assert "allowance" not in command
    assert "artifact_worker" not in command

    jobs = _jobs()
    assert jobs["container-contracts"]["timeout-minutes"] == 13
    assert jobs["playwright-image"]["timeout-minutes"] == 9
    assert jobs["worker"]["timeout-minutes"] == "${{ fromJSON(needs.changes.outputs.worker_timeout_minutes) }}"


def test_runtime_accounting_jq_distinguishes_running_completed_and_both_skips() -> None:
    jq = shutil.which("jq")
    if jq is None:
        pytest.skip("jq is not available")

    report = next(step for step in _steps(_jobs()["checks"]) if step.get("name") == "Report workflow accounting")
    command = report["run"]
    marker = 'jq -r --arg now "$now_iso" --arg reused "${REUSED_RUN_ID:-}" --argjson expected "$expected" \''
    start = command.index(marker) + len(marker)
    program = command[start : command.index('\' <<< "$jobs"', start)]
    jobs = [
        {
            "name": "Checks",
            "started_at": "2026-07-23T00:00:00Z",
            "completed_at": None,
            "conclusion": None,
        },
        {
            "name": "Router",
            "started_at": "2026-07-23T00:00:00Z",
            "completed_at": "2026-07-23T00:01:01Z",
            "conclusion": "success",
        },
        {
            "name": "Scoped worker (python)",
            "started_at": "2026-07-23T00:00:00Z",
            "completed_at": "2026-07-23T00:00:00Z",
            "conclusion": "skipped",
        },
        {
            "name": "Playwright runner image",
            "started_at": "2026-07-23T00:00:00Z",
            "completed_at": "2026-07-23T00:00:00Z",
            "conclusion": "skipped",
        },
    ]
    expected = {
        "worker": True,
        "Container contracts": False,
        "Playwright runner image": False,
        "Title policy": True,
        "Router": True,
        "Checks": True,
    }

    result = subprocess.run(
        [
            jq,
            "-r",
            "--arg",
            "now",
            "2026-07-23T00:01:00Z",
            "--arg",
            "reused",
            "18234567890",
            "--argjson",
            "expected",
            json.dumps(expected),
            program,
        ],
        input=json.dumps(jobs),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        # The fan-in cannot see its own conclusion, so it must not report itself as in_progress.
        "| Checks | 60 | 1 | running (this job) |",
        "| Router | 61 | 2 | success |",
        # Selected yet skipped: the gate is asserting a prior run already proved this tree.
        "| Scoped worker (python) | 0 | 0 | skipped: already proven by run 18234567890 |",
        # Not selected: the gate declined the work. Same runner word, opposite meaning.
        "| Playwright runner image | 0 | 0 | skipped: not selected |",
    ]


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
    command = next(step for step in _steps(checks) if step.get("name") == "Require every selected check")["run"]
    assert "case '${{ needs.changes.outputs.commit_class }}' in" in command
    assert "standard)" in command
    assert "broad)" in command

    # One matrix job covers every unit of both classes, so the fan-in has one work result to
    # require rather than one per shard; a failing unit fails the job it belongs to.
    required = {
        "worker": "$WORK_EXPECTED",
        "container-contracts": "$CONTAINER_EXPECTED",
        "playwright-image": "$PLAYWRIGHT_EXPECTED",
        "title-policy": "$TITLE_POLICY_EXPECTED",
    }
    assert set(checks["needs"]) == {"changes"} | set(required)
    for job_id, expectation in required.items():
        assert f"require '${{{{ needs.{job_id}.result }}}}' \"{expectation}\" {job_id}" in command
    assert "$BROAD_EXPECTED" not in command
    assert "broad-environment" not in command


def test_typescript_quality_runs_once_per_class_with_ci_native_commands() -> None:
    steps = {step.get("name"): step for step in _steps(_jobs()["worker"])}
    assert steps["Lint frontend"]["run"] == ("pnpm --filter nohiki-frontend exec biome ci --reporter=github .")
    assert steps["Lint frontend architecture (Steiger)"]["run"] == ("pnpm --filter nohiki-frontend run lint:fsd")
    assert "biome ci --reporter=github src/" in steps["Lint edge worker"]["run"]
    assert "exec tsc --noEmit" in steps["Typecheck edge worker"]["run"]
    assert "exec vitest run" in steps["Test edge worker"]["run"]
    # A summary label is prepended to the step; the work command must stay the final line, verbatim.
    frontend_run = str(steps["Test frontend"]["run"]).strip().splitlines()
    assert frontend_run[-1] == "pnpm -C typescript/apps/frontend test --run --maxWorkers=100%"


def test_setup_and_secret_scan_keep_one_definition_and_one_cache_writer() -> None:
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
    # Frontend is the only full-payload leg and the only possible cache writer. Pull requests
    # write only for broad decisions; main pushes write for either class.
    assert setup["with"]["save-ready-cache"] == (
        "${{ matrix.unit == 'frontend' && (needs.changes.outputs.broad == 'true' || github.event_name == 'push') }}"
    )

    for name in ("Lint Python", "Check Python formatting"):
        lint_step = steps[name]
        assert lint_step["env"]["RUFF_CACHE_DIR"] == "${{ runner.temp }}/ruff-cache"
        assert "export UV_PROJECT_ENVIRONMENT=.venv" in lint_step["run"]
        assert ".venv-lint" not in lint_step["run"]
        # Broad lints the whole tree from the same definition that lints the diff on standard.
        assert lint_step["env"]["RUFF_SCOPE"] == ("${{ needs.changes.outputs.broad == 'true' && 'ALL' || 'CHANGED' }}")
        assert "--exclude '**/alembic/**' --exclude '**/nohiki-domain-models/**' ." in lint_step["run"]
        assert '"$BASE_SHA..$HEAD_SHA"' in lint_step["run"]

    # NODE_GROUP_EXPECTED is asserted against NODE_SETUP_SELECTED in
    # test_execution_attestations_are_not_scoped_to_one_commit_class.

    changed = steps["Scan changed content for secrets"]
    assert changed["if"] == "env.DOCS_ONLY == 'true'"
    assert 'git diff --binary "$BASE_SHA..$HEAD_SHA"' in changed["run"]
    assert "stdin --config /repo/.gitleaks.toml --no-banner --redact" in changed["run"]

    full = steps["Scan repository for secrets"]
    assert full["if"].endswith("env.DOCS_ONLY != 'true'")
    assert "detect --source . --config .gitleaks.toml --no-banner --redact" in full["run"]


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
    }
    assert standalone.isdisjoint(set().union(*names))
    assert all("background" not in step and "cancel" not in step for step in worker["steps"])


def test_deadcode_runs_once_with_split_static_cache_save() -> None:
    job = _jobs()["worker"]
    steps = _steps(job)
    deadcode = next(step for step in steps if step.get("name") == "Check selected dead code")
    assert job["env"]["SKYLOS_CACHE_DIR"] == "${{ github.workspace }}/.skylos"
    assert job["env"]["SKYLOS_CACHE_STATIC_TIER"] == "content"
    assert deadcode["env"]["SKYLOS_JOBS"] == "2"
    assert "--with" not in deadcode["run"]
    assert "ci-checks deadcode" in deadcode["run"]
    assert "--ci --fail --no-provenance" in deadcode["run"]

    # Ruff and Skylos share a runner again, so the ordering the 196s rationale describes is
    # load-bearing here: ruff must not leave a .ruff_cache in the fingerprinted workspace.
    names = [step.get("name") for step in steps]
    assert names.index("Lint Python") < names.index("Check selected dead code")

    save = next(step for step in steps if step.get("name") == "Save Skylos static analysis cache")
    assert str(save["if"]).startswith("always() &&")
    assert save["with"]["path"] == "${{ github.workspace }}/.skylos"
    assert save["with"]["key"] == ("${{ steps.setup-ci.outputs.skylos-cache-primary-key }}")


def test_cache_summaries_use_observed_action_outputs() -> None:
    jobs = _jobs()
    setup_owners = (
        "worker",
        "container-contracts",
        "title-policy",
    )
    for owner in setup_owners:
        steps = {step.get("name"): step for step in _steps(jobs[owner])}
        setup = next(step for step in steps.values() if step.get("uses") == "./.github/actions/setup-ci")
        assert setup["id"] == "setup-ci"
        report = next(step for name, step in steps.items() if name and name.startswith("Report "))
        assert report["env"]["CACHE_OUTCOMES"] == "${{ steps.setup-ci.outputs.cache-telemetry }}"
        # One table row per cache, not one machine-readable log line.
        assert "| Cache | Outcome | Key |" in str(report["run"])
        # Keys are truncated to a readable prefix; the full value stays in the job log.
        assert "s/([0-9a-f]{8})[0-9a-f]{24,}/\\1…/g" in str(report["run"])

    router_steps = {step.get("name"): step for step in _steps(jobs["changes"])}
    router_setup = router_steps["Set up uv and Python"]
    assert router_setup["id"] == "setup-uv"
    router_report = router_steps["Report router cost"]
    assert router_report["env"]["UV_CACHE_HIT"] == "${{ steps.setup-uv.outputs.cache-hit }}"
    assert router_report["env"]["UV_CACHE_KEY"] == "${{ steps.setup-uv.outputs.cache-key }}"
    assert "| Cache | Outcome | Key |" in str(router_report["run"])

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
    assert upload["uses"].startswith("actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a")
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
    assert set(jobs) == {"changes", "worker", "container-contracts", "playwright-image", "title-policy", "checks"}

    # `image_matrix_parity` is a lane flag, not a build matrix; no other output may carry one.
    outputs = {name: value for name, value in jobs["changes"]["outputs"].items() if name not in FLAG_NAMES}
    assert not [name for name in outputs if "matrix" in name or "image" in name]
    assert not [name for name, value in outputs.items() if "matrix" in str(value) or "image" in str(value)]
