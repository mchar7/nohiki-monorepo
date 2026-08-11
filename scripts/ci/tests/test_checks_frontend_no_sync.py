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
    assert job_id == "worker"
    worker_steps = jobs["worker"]["steps"]
    setup = next(
        step for step in worker_steps if isinstance(step, dict) and step.get("name") == "Set up selected environments"
    )
    assert setup["uses"] == "./.github/actions/setup-ci"
    assert setup["with"]["ready-cache"] == "${{ env.NIX_SETUP_SELECTED }}"
    assert setup["with"]["payload"] == "${{ matrix.unit == 'python' && 'python' || 'full' }}"
    assert setup["with"]["runner-class"] == "${{ needs.changes.outputs.runner_class }}"
    commands = [step["run"] for step in worker_steps if isinstance(step, dict) and isinstance(step.get("run"), str)]
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
    assert str(frontend["run"]).endswith("just fe-test")
    assert "ci-checks tests all" in python["run"]
    assert python["env"]["SUMMARY_TITLE"] == ("${{ needs.changes.outputs.commit_class }}")


def test_container_build_caches_split_by_runner_environment() -> None:
    assert (_ROOT / ".github" / "buildkitd-self-hosted.toml").read_text(encoding="utf-8") == (
        '[registry."cache-registry:5000"]\n  http = true\n  insecure = true\n'
    )

    jobs = _WORKFLOW["jobs"]
    cases = (
        ("worker", "Build production frontend image", "frontend-smoke"),
        (
            "playwright-image",
            "Build Playwright runner image",
            "playwright-runner-smoke",
        ),
    )

    for job_name, step_name, scope in cases:
        steps = jobs[job_name]["steps"]
        setup = next(step for step in steps if step.get("name") == "Set up Docker Buildx")
        assert setup["with"] == {
            "driver-opts": "${{ runner.environment == 'self-hosted' && 'network=host' || '' }}",
            "buildkitd-config": (
                "${{ runner.environment == 'self-hosted' && '.github/buildkitd-self-hosted.toml' || '' }}"
            ),
        }

        build = next(step for step in steps if step.get("name") == step_name)
        inputs = build["with"]
        assert inputs["cache-from"] == (
            f"${{{{ runner.environment == 'self-hosted' && "
            f"'type=registry,ref=cache-registry:5000/nohiki/{scope}:buildcache' || "
            f"'type=gha,scope={scope}' }}}}"
        )
        assert inputs["cache-to"] == (
            f"${{{{ runner.environment == 'self-hosted' && "
            f"'type=registry,ref=cache-registry:5000/nohiki/{scope}:buildcache,"
            f"mode=max,ignore-error=true' || '' }}}}"
        )
        assert "hashFiles" not in inputs["cache-from"]
