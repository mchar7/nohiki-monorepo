from __future__ import annotations

import shlex
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[3]
_CHECKS = _ROOT / ".github" / "workflows" / "checks.yml"
_SMOKE_STEP = "Smoke production frontend container"
_WORKFLOW = yaml.safe_load(_CHECKS.read_text(encoding="utf-8"))


def test_smoke_production_frontend_container_reuses_synced_uv_environment() -> None:
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
    assert job_id == "frontend-smoke"

    command = smoke_step.get("run")
    assert isinstance(command, str), smoke_step
    argv = shlex.split(command)
    assert argv[:4] == ["nix", "develop", ".#ci", "--command"]
    assert argv[4:8] == ["uv", "run", "--no-sync", "pytest"]


def test_frontend_and_python_tests_use_distinct_jobs() -> None:
    workflow = _WORKFLOW
    jobs = workflow["jobs"]
    frontend_commands = " ".join(step.get("run", "") for step in jobs["frontend-tests"]["steps"])
    python_commands = " ".join(step.get("run", "") for step in jobs["python-tests"]["steps"])

    assert "pnpm -C typescript/apps/frontend test --run --maxWorkers=50%" in frontend_commands
    assert "ci-checks tests all" not in frontend_commands
    assert "ci-checks tests all" in python_commands
    assert "pnpm test --run" not in python_commands
