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


def _jobs() -> dict[str, WorkflowJob]:
    return load_workflow(_CHECKS)["jobs"]


def _steps(job: WorkflowJob) -> list[WorkflowStep]:
    return job.get("steps", [])


_CONTAINER_EXECUTORS = {
    "frontend_smoke": "container-contracts",
    "frontend_e2e": "playwright-image",
    "otel_collector": "container-contracts",
}
_STANDARD_EXECUTORS = dict.fromkeys(FLAG_NAMES, "worker") | _CONTAINER_EXECUTORS
_BROAD_EXECUTORS = {
    "lint_python": "broad-policy",
    "typecheck_backend": "broad-hygiene",
    "hygiene": "broad-hygiene",
    "python_any": "broad-python",
    "nix": "broad-policy",
    "lint_proto": "broad-policy",
    "lint_markdown": "broad-frontend",
    "lint_workflows": "broad-policy",
    "lint_docker": "broad-policy",
    "api_schema_freshness": "broad-hygiene",
    "image_matrix_parity": "broad-policy",
    "proto_breaking": "broad-policy",
    "build_backend": "broad-hygiene",
    "lint_frontend": "broad-frontend",
    "typecheck_frontend": "broad-frontend",
    "frontend_tests": "broad-frontend",
    "edge_worker": "broad-frontend",
} | _CONTAINER_EXECUTORS
_BROAD_JOB_IDS = {"broad-python", "broad-frontend", "broad-hygiene", "broad-policy"}
_NON_EXECUTOR_JOB_IDS = {
    "changes",
    "commitlint",
    "checks",
    "gate-advisory",
    "broad-environment",
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


def _has_unconditional_executor(
    job_id: str,
    job: WorkflowJob,
    commit_class: CommitClass,
    flag: str,
) -> bool:
    if commit_class is not CommitClass.BROAD or _BROAD_EXECUTORS[flag] != job_id:
        return False
    return bool(_steps(job))


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
        if (
            _positive_reference(job_condition, reference)
            or step_owns_flag
            or _has_unconditional_executor(job_id, job, commit_class, flag)
        ):
            selected.add(job_id)
    return selected


def _decision_executors(
    jobs: dict[str, WorkflowJob],
    decision: GateDecision,
) -> set[str]:
    selected = {
        executor
        for flag in decision.flags
        for executor in _selected_executors(
            jobs,
            decision.commit_class,
            flag,
        )
    }
    if decision.commit_class is CommitClass.BROAD:
        selected |= _BROAD_JOB_IDS
    return selected


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
    assert _decision_executors(jobs, flake) == _BROAD_JOB_IDS | {"playwright-image"}

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


def test_standard_worker_and_broad_shards_own_each_lane_once() -> None:
    jobs = _jobs()
    worker = jobs["worker"]
    assert "needs.changes.outputs.standard == 'true'" in worker["if"]
    assert "needs.changes.outputs.broad == 'true'" not in worker["if"]

    for job_id in _BROAD_JOB_IDS:
        condition = jobs[job_id]["if"]
        assert condition.startswith("always() &&")
        assert "needs.changes.outputs.broad == 'true'" in condition
        assert "needs.broad-environment.result == 'success'" in condition
        assert "needs.broad-environment.result == 'skipped'" in condition
        assert jobs[job_id]["needs"] == ["changes", "broad-environment"]
    prewarm = jobs["broad-environment"]
    assert "github.event_name" not in prewarm["if"]
    assert "needs.changes.outputs.broad == 'true'" in prewarm["if"]
    prewarm_setup = next(step for step in _steps(prewarm) if step.get("uses") == "./.github/actions/setup-ci")
    assert prewarm_setup["with"]["lookup-only"] == "true"
    assert prewarm_setup["with"]["save-ready-cache"] == "true"
    for job_id in _BROAD_JOB_IDS:
        setup = next(step for step in _steps(jobs[job_id]) if step.get("uses") == "./.github/actions/setup-ci")
        assert setup["with"]["ready-cache"] == "true"
        assert "save-ready-cache" not in setup["with"]

    lane_names = {
        "Check flake",
        "Check Lefthook version",
        "Lint Python",
        "Check Python formatting",
        "Lint Markdown",
        "Lint protos",
        "Lint workflows (actionlint)",
        "Lint frontend",
        "Check i18n keys",
        "Lint Dockerfiles (hadolint)",
        "Scan repository for secrets",
        "Typecheck backend",
        "Check selected dead code",
        "Save Skylos static analysis cache",
        "Typecheck frontend",
        "Run selected Python tests",
        "Test frontend",
        "Lint edge worker",
        "Typecheck edge worker",
        "Test edge worker",
        "Validate PR commit messages",
        "Validate PR title (merge commit subject)",
        "Check dependencies",
        "Scan architecture",
        "Check build backends",
        "Check API schema freshness",
        "Check image matrix parity",
        "Check proto compatibility",
    }
    standard_names = [step.get("name") for step in _steps(worker)]
    broad_names = [step.get("name") for job_id in _BROAD_JOB_IDS for step in _steps(jobs[job_id])]
    for name in lane_names:
        assert standard_names.count(name) == 1
        assert broad_names.count(name) == 1

    full_scan = next(step for step in _steps(worker) if step.get("name") == "Scan repository for secrets")
    assert full_scan["if"] == "env.DOCS_ONLY != 'true'"
    assert "detect --source . --config .gitleaks.toml --no-banner --redact" in full_scan["run"]
    assert worker["outputs"] == {
        "node_group_executed": "${{ steps.setup-ci.outputs.node-group-executed }}",
        "commitlint_executed": "${{ steps.commitlint-range.outcome == 'success' }}",
    }


def test_ready_cache_save_runs_on_every_event_behind_a_key_guard() -> None:
    steps = mapping_sequence_at(load_mapping(_SETUP_CI), "runs", "steps")
    save = next(step for step in steps if step.get("name") == "Save complete CI environment")
    condition = str(save["if"])
    assert "github.event_name" not in condition
    assert "steps.ready-cache.outputs.primary-key != ''" in condition


def test_python_test_lane_uses_gate_scope_once_per_class() -> None:
    jobs = _jobs()
    worker = jobs["worker"]
    broad_python = jobs["broad-python"]

    assert worker["needs"] == ["changes"]
    assert broad_python["needs"] == ["changes", "broad-environment"]
    for job in (worker, broad_python):
        assert job["timeout-minutes"] == ("${{ fromJSON(needs.changes.outputs.worker_timeout_minutes) }}")
        assert "strategy" not in job
        run_tests = next(step for step in _steps(job) if step.get("name") == "Run selected Python tests")
        command = run_tests["run"]
        assert command.count("ci-checks tests all --scope all") == 1
        assert '--packages "$TEST_PACKAGES"' in command
        assert '--summary-title "$SUMMARY_TITLE"' in command
        assert run_tests["env"]["SUMMARY_TITLE"] == ("${{ needs.changes.outputs.commit_class }}")


def test_worker_guards_are_two_minutes_above_each_class_wall_budget() -> None:
    changes = _jobs()["changes"]
    assert changes["outputs"]["worker_timeout_minutes"] == ("${{ steps.guards.outputs.worker_timeout_minutes }}")
    guards = next(step for step in _steps(changes) if step.get("name") == "Derive worker guard")
    command = str(guards["run"])
    assert "standard) wall_budget_seconds=600 ;;" in command
    assert "broad) wall_budget_seconds=720 ;;" in command
    assert "hang_grace_minutes=2" in command
    assert "wall_budget_seconds / 60 + hang_grace_minutes" in command
    assert 600 // 60 + 2 == 12
    assert 720 // 60 + 2 == 14

    guarded_jobs = {"worker", "broad-environment"} | _BROAD_JOB_IDS
    for job_id in guarded_jobs:
        assert _jobs()[job_id]["timeout-minutes"] == ("${{ fromJSON(needs.changes.outputs.worker_timeout_minutes) }}")


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
    title_policy = jobs["commitlint"]
    substantive = jobs["checks"]
    assert title_policy["name"] == "PR title (conventional)"
    assert title_policy["if"] == (
        "needs.changes.outputs.commitlint_expected == 'true' && github.event.action == 'edited'"
    )
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
        "worker_timeout_minutes",
        "protected_main_smoke",
        "commitlint_expected",
        "full",
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


def test_runtime_accounting_enforces_only_the_frozen_class_budgets() -> None:
    report = next(step for step in _steps(_jobs()["checks"]) if step.get("name") == "Report workflow accounting")
    command = report["run"]
    env = report["env"]

    assert "if ((wall_seconds >= class_wall_budget_seconds)); then" in command
    assert "if ((billable_minutes > class_billable_budget_minutes)); then" in command
    assert '--argjson observed "$ratio"' in command
    assert '--argjson budget "$class_ratio_budget"' in command
    assert "'$observed > $budget'" in command
    assert 'exit "$budget_failure"' in command

    budget_cases = {
        (int(wall), int(billable), float(ratio))
        for wall, billable, ratio in re.findall(
            r"class_wall_budget_seconds=(\d+)\s+"
            r"class_billable_budget_minutes=(\d+)\s+"
            r"class_ratio_budget=([\d.]+)",
            command,
        )
    }
    assert budget_cases == {(600, 10, 1.3), (720, 30, 3.0)}
    assert "CONTAINER_SELECTED" not in env
    assert "PLAYWRIGHT_SELECTED" not in env
    assert "allowance" not in command
    assert "artifact_worker" not in command

    jobs = _jobs()
    assert jobs["container-contracts"]["timeout-minutes"] == 13
    assert jobs["playwright-image"]["timeout-minutes"] == 9
    assert jobs["worker"]["timeout-minutes"] == "${{ fromJSON(needs.changes.outputs.worker_timeout_minutes) }}"


def test_runtime_accounting_jq_renders_running_and_completed_jobs() -> None:
    jq = shutil.which("jq")
    if jq is None:
        pytest.skip("jq is not available")

    report = next(step for step in _steps(_jobs()["checks"]) if step.get("name") == "Report workflow accounting")
    command = report["run"]
    marker = 'jq -r --arg now "$now_iso" \''
    start = command.index(marker) + len(marker)
    program = command[start : command.index('\' <<< "$jobs"', start)]
    jobs = [
        {
            "name": "running",
            "started_at": "2026-07-23T00:00:00Z",
            "completed_at": None,
            "conclusion": None,
        },
        {
            "name": "complete",
            "started_at": "2026-07-23T00:00:00Z",
            "completed_at": "2026-07-23T00:01:01Z",
            "conclusion": "success",
        },
    ]

    result = subprocess.run(
        [jq, "-r", "--arg", "now", "2026-07-23T00:01:00Z", program],
        input=json.dumps(jobs),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "| running | 60 | 1 | in_progress |",
        "| complete | 61 | 2 | success |",
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

    required = {
        "commitlint": "$COMMITLINT_EXPECTED",
        "worker": "$WORK_EXPECTED",
        "broad-environment": "$BROAD_ENV_EXPECTED",
        "broad-python": "$BROAD_EXPECTED",
        "broad-frontend": "$BROAD_EXPECTED",
        "broad-hygiene": "$BROAD_EXPECTED",
        "broad-policy": "$BROAD_EXPECTED",
        "container-contracts": "$CONTAINER_EXPECTED",
        "playwright-image": "$PLAYWRIGHT_EXPECTED",
    }
    assert set(checks["needs"]) == {"changes"} | set(required)
    for job_id, expectation in required.items():
        assert f"require '${{{{ needs.{job_id}.result }}}}' \"{expectation}\" {job_id}" in command


def test_typescript_quality_runs_once_per_class_with_ci_native_commands() -> None:
    jobs = _jobs()
    for owner in ("worker", "broad-frontend"):
        steps = {step.get("name"): step for step in _steps(jobs[owner])}
        assert steps["Lint frontend"]["run"] == ("pnpm --filter nohiki-frontend exec biome ci --reporter=github .")
        assert "biome ci --reporter=github src/" in steps["Lint edge worker"]["run"]
        assert "exec tsc --noEmit" in steps["Typecheck edge worker"]["run"]
        assert "exec vitest run" in steps["Test edge worker"]["run"]
        assert steps["Test frontend"]["run"].endswith("test --run --maxWorkers=100%")


def test_standard_setup_and_secret_scan_remain_single_job() -> None:
    standard = _jobs()["worker"]
    job_env = standard["env"]
    assert "needs.changes.outputs.broad" not in standard["if"]
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
    assert setup["with"]["save-ready-cache"] == "${{ github.event_name == 'push' }}"
    assert setup["with"]["node"] == "${{ env.NODE_SETUP_SELECTED }}"

    for name in ("Lint Python", "Check Python formatting"):
        lint_step = steps[name]
        assert lint_step["env"]["RUFF_CACHE_DIR"] == "${{ runner.temp }}/ruff-cache"
        assert "export UV_PROJECT_ENVIRONMENT=.venv" in lint_step["run"]
        assert ".venv-lint" not in lint_step["run"]

    fan_in = next(step for step in _steps(_jobs()["checks"]) if step.get("name") == "Require every selected check")
    assert "needs.changes.outputs.standard == 'true'" in str(fan_in["env"]["NODE_GROUP_EXPECTED"])

    changed = steps["Scan changed content for secrets"]
    assert changed["if"] == "env.DOCS_ONLY == 'true'"
    assert 'git diff --binary "$BASE_SHA..$HEAD_SHA"' in changed["run"]
    assert "stdin --config /repo/.gitleaks.toml --no-banner --redact" in changed["run"]

    full = steps["Scan repository for secrets"]
    assert full["if"] == "env.DOCS_ONLY != 'true'"
    assert "detect --source . --config .gitleaks.toml --no-banner --redact" in full["run"]


def test_deadcode_runs_once_per_class_with_split_static_cache_save() -> None:
    jobs = _jobs()
    for owner in ("worker", "broad-hygiene"):
        job = jobs[owner]
        steps = _steps(job)
        deadcode = next(step for step in steps if step.get("name") == "Check selected dead code")
        assert job["env"]["SKYLOS_CACHE_DIR"] == "${{ github.workspace }}/.skylos"
        assert job["env"]["SKYLOS_CACHE_STATIC_TIER"] == "content"
        assert deadcode["env"]["SKYLOS_JOBS"] == "2"
        assert "--with" not in deadcode["run"]
        assert "ci-checks deadcode" in deadcode["run"]
        assert "--ci --fail --no-provenance" in deadcode["run"]

        save = next(step for step in steps if step.get("name") == "Save Skylos static analysis cache")
        assert str(save["if"]).startswith("always() &&")
        assert save["with"]["path"] == "${{ github.workspace }}/.skylos"
        assert save["with"]["key"] == ("${{ steps.setup-ci.outputs.skylos-cache-primary-key }}")


def test_cache_summaries_use_observed_action_outputs() -> None:
    jobs = _jobs()
    setup_owners = (
        "commitlint",
        "worker",
        "broad-environment",
        "broad-python",
        "broad-frontend",
        "broad-hygiene",
        "broad-policy",
        "container-contracts",
    )
    for owner in setup_owners:
        steps = {step.get("name"): step for step in _steps(jobs[owner])}
        setup = next(step for step in steps.values() if step.get("uses") == "./.github/actions/setup-ci")
        assert setup["id"] == "setup-ci"
        report = next(step for name, step in steps.items() if name and name.startswith("Report "))
        assert report["env"]["CACHE_OUTCOMES"] == "${{ steps.setup-ci.outputs.cache-telemetry }}"
        assert "cache_outcomes=%s" in str(report["run"])

    router_steps = {step.get("name"): step for step in _steps(jobs["changes"])}
    router_setup = router_steps["Set up uv and Python"]
    assert router_setup["id"] == "setup-uv"
    router_report = router_steps["Report router timing"]
    assert router_report["env"]["UV_CACHE_HIT"] == "${{ steps.setup-uv.outputs.cache-hit }}"
    assert router_report["env"]["UV_CACHE_KEY"] == "${{ steps.setup-uv.outputs.cache-key }}"

    workflow_text = _CHECKS.read_text(encoding="utf-8")
    assert "cache_hit=" not in workflow_text
    assert "setup-node-managed" not in workflow_text
    assert "buildx-managed" not in workflow_text
    assert "cache_outcomes=buildkit=unknown:none" in workflow_text


def test_python_test_packages_come_from_change_gate_in_both_classes() -> None:
    changes = _jobs()["changes"]
    assert changes["outputs"]["test_packages"] == "${{ steps.gate.outputs.test_packages }}"

    for owner in ("worker", "broad-python"):
        selected_tests = next(
            step for step in _steps(_jobs()[owner]) if step.get("name") == "Run selected Python tests"
        )
        assert selected_tests["env"]["TEST_PACKAGES"] == ("${{ needs.changes.outputs.test_packages }}")
        assert 'test -n "$TEST_PACKAGES"' in selected_tests["run"]
        assert '--packages "$TEST_PACKAGES"' in selected_tests["run"]
