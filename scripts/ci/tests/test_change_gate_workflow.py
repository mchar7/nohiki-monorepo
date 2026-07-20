from pathlib import Path
from typing import cast

import yaml

_ROOT = Path(__file__).resolve().parents[3]
_CHECKS = _ROOT / ".github" / "workflows" / "checks.yml"
_FRESHNESS = _ROOT / ".github" / "workflows" / "digest-freshness.yml"


def _jobs() -> dict[str, dict[str, object]]:
    workflow = yaml.safe_load(_CHECKS.read_text(encoding="utf-8"))
    assert isinstance(workflow, dict)
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict)
    return {cast("str", job_id): cast("dict[str, object]", job) for job_id, job in jobs.items()}


def _steps(job: dict[str, object]) -> list[dict[str, object]]:
    steps = job.get("steps")
    assert isinstance(steps, list)
    return [cast("dict[str, object]", step) for step in steps]


def test_changes_job_computes_gate_from_full_history() -> None:
    changes = _jobs()["changes"]
    assert changes["name"] == "Change gate"
    assert "needs" not in changes

    steps = _steps(changes)
    checkout = next(step for step in steps if "uses" in step)
    assert checkout["with"] == {"fetch-depth": 0}

    gate = next(step for step in steps if step.get("name") == "Compute change gate")
    env = cast("dict[str, str]", gate["env"])
    assert (
        env["BASE"] == "${{ github.event_name == 'push' && github.event.before || github.event.pull_request.base.sha }}"
    )
    command = cast("str", gate["run"])
    assert "ci-checks gate" in command
    assert '--github-output "$GITHUB_OUTPUT"' in command
    assert '--summary "$GITHUB_STEP_SUMMARY"' in command
    assert "--comment-file gate-comment.md" in command


def test_changes_job_publishes_verdict_and_labels_on_prs() -> None:
    changes = _jobs()["changes"]
    permissions = cast("dict[str, str]", changes["permissions"])
    assert permissions == {
        "contents": "read",
        "actions": "write",
        "pull-requests": "write",
        "issues": "write",
    }

    steps = {cast("str", step.get("name")): step for step in _steps(changes)}
    for name in ("Publish gate verdict to PR", "Sync area labels"):
        step = steps[name]
        assert step["if"] == "github.event_name == 'pull_request'", name
    comment = cast("str", steps["Publish gate verdict to PR"]["run"])
    assert "nohiki-change-gate" in comment
    label_step = steps["Sync area labels"]
    env = cast("dict[str, str]", label_step["env"])
    assert env["LABELS"] == "${{ steps.gate.outputs.labels }}"
    labels = cast("str", label_step["run"])
    assert "jq -r '.[] | [.name, .color, .active] | @tsv'" in labels
    assert 'gh label create "$label"' in labels
    assert '--color "$color"' in labels


def test_digest_freshness_workflow_probes_on_schedule() -> None:
    workflow = yaml.safe_load(_FRESHNESS.read_text(encoding="utf-8"))
    assert isinstance(workflow, dict)
    triggers = workflow.get(True) or workflow.get("on")
    assert isinstance(triggers, dict)
    assert "workflow_dispatch" in triggers
    schedule = cast("list[dict[str, str]]", triggers["schedule"])
    assert schedule[0]["cron"]
    assert workflow["permissions"] == {"contents": "read", "issues": "write"}
    jobs = cast("dict[str, dict[str, object]]", workflow["jobs"])
    (probe,) = jobs.values()
    commands = "\n".join(cast("str", step.get("run", "")) for step in cast("list[dict[str, object]]", probe["steps"]))
    assert "ci-checks image-freshness" in commands
    assert "gh issue" in commands


def test_gated_jobs_depend_on_change_outputs() -> None:
    jobs = _jobs()
    ungated = {"changes", "checks", "commitlint", "lint"}
    for job_id, job in jobs.items():
        if job_id in ungated:
            continue
        assert "changes" in cast("list[str]", job["needs"]), job_id
        condition = job.get("if")
        assert isinstance(condition, str), job_id
        assert "needs.changes.outputs." in condition, job_id


def test_checks_aggregator_only_allows_gate_sanctioned_skips() -> None:
    checks = _jobs()["checks"]
    command = cast("str", _steps(checks)[0]["run"])
    assert "needs.changes.result" in command

    gates = {
        "nix": ("nix",),
        "frontend-smoke": ("frontend_smoke",),
        "typecheck": ("typecheck_backend", "typecheck_frontend"),
        "python-tests": ("python_any",),
        "frontend-tests": ("frontend_tests",),
        "hygiene": ("hygiene",),
        "generated-artifacts": ("generated_artifacts",),
        "proto-breaking": ("proto_breaking",),
    }
    for job_id, output_names in gates.items():
        skipped = f"test '${{{{ needs.{job_id}.result }}}}' = skipped"
        assert skipped in command, job_id
        skip_allowance = command.split(skipped, maxsplit=1)[1].split("\n}", maxsplit=1)[0]
        for output_name in output_names:
            gate_output = f"test '${{{{ needs.changes.outputs.{output_name} }}}}' != true"
            assert gate_output in skip_allowance, (job_id, output_name)


def test_gitleaks_is_unconditional() -> None:
    gitleaks = next(step for step in _steps(_jobs()["lint"]) if step.get("name") == "Scan for secrets (gitleaks)")
    assert "if" not in gitleaks


def test_python_test_matrix_comes_from_change_gate() -> None:
    python_tests = _jobs()["python-tests"]
    strategy = cast("dict[str, object]", python_tests["strategy"])
    assert strategy["matrix"] == "${{ fromJSON(needs.changes.outputs.tests_matrix) }}"
