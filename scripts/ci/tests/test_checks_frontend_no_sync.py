from __future__ import annotations

import shlex
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[3]
_CHECKS = _ROOT / ".github" / "workflows" / "checks.yml"
_SMOKE_STEP = "Smoke production frontend container"
_WORKFLOW = yaml.safe_load(_CHECKS.read_text(encoding="utf-8"))


def test_smoke_production_frontend_container_uses_complete_ci_environment() -> None:
    workflow = _WORKFLOW
    assert isinstance(workflow, dict)
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict)

    matching_steps = [
        (job_id, step)
        for job_id, job in jobs.items()
        if isinstance(job, dict)
        for step in job.get("steps", [])
        if isinstance(step, dict) and step.get("name") == _SMOKE_STEP
    ]
    assert len(matching_steps) == 1, matching_steps
    job_id, smoke_step = matching_steps[0]
    assert job_id == "container-contracts"
    container_steps = jobs["container-contracts"]["steps"]
    setup = next(
        step
        for step in container_steps
        if isinstance(step, dict) and step.get("name") == "Set up container contract environment"
    )
    assert setup["uses"] == "./.github/actions/setup-ci"
    assert setup["with"]["ready-cache"] == "true"
    commands = [step["run"] for step in container_steps if isinstance(step, dict) and isinstance(step.get("run"), str)]
    assert all("uv sync" not in command for command in commands)

    command = smoke_step.get("run")
    assert isinstance(command, str), smoke_step
    argv = shlex.split(command)
    assert argv[:4] == ["nix", "develop", ".#ci", "--command"]
    assert argv[4:8] == ["uv", "run", "--no-sync", "pytest"]

    playwright_commands = " ".join(
        step.get("run", "") for step in jobs["playwright-image"]["steps"] if isinstance(step, dict)
    )
    assert "uv " not in playwright_commands
    assert "nix develop" not in playwright_commands


def test_frontend_and_python_tests_split_only_for_broad() -> None:
    jobs = _WORKFLOW["jobs"]
    steps = {step.get("name"): step for step in jobs["worker"]["steps"]}
    frontend = steps["Test frontend"]
    python = steps["Run selected Python tests"]

    # One definition each. The class decides how many runners the same bodies spread over,
    # so the split lives in the matrix and the per-step unit selector, not in a second job.
    assert "needs.changes.outputs.standard == 'true'" in jobs["worker"]["if"]
    assert "needs.changes.outputs.broad == 'true'" in jobs["worker"]["if"]
    assert "matrix.unit == 'frontend'" in str(frontend["if"])
    assert "matrix.unit == 'python'" in str(python["if"])
    assert "pnpm -C typescript/apps/frontend test --run --maxWorkers=100%" in frontend["run"]
    assert "ci-checks tests all" in python["run"]
    assert python["env"]["SUMMARY_TITLE"] == ("${{ needs.changes.outputs.commit_class }}")


def test_container_builds_use_stable_per_image_buildkit_cache_scopes() -> None:
    jobs = _WORKFLOW["jobs"]
    cases = (
        ("container-contracts", "Build production frontend image", "frontend-smoke"),
        (
            "playwright-image",
            "Build Playwright runner image",
            "playwright-runner-smoke",
        ),
    )

    for job_name, step_name, scope in cases:
        build = next(step for step in jobs[job_name]["steps"] if step.get("name") == step_name)
        inputs = build["with"]
        assert inputs["cache-from"] == f"type=gha,scope={scope}"
        assert inputs["cache-to"] == f"type=gha,scope={scope},mode=max"
        assert "hashFiles" not in inputs["cache-from"]
        assert "hashFiles" not in inputs["cache-to"]
