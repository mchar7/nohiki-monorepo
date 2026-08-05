from __future__ import annotations

import json
import os
import subprocess
from functools import cache
from pathlib import Path

import pytest
from _documents import Workflow, load_mapping, load_workflow
from ci_checks.core.image_inventory import load_inventory

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_IMAGE_INVENTORY = _REPOSITORY_ROOT / "infra" / "k8s" / "local" / "images.json"


@cache
def _image_inventory_specs() -> tuple[tuple[str, str, str, str | None, bool], ...]:
    document = load_mapping(_IMAGE_INVENTORY)
    assert document["schemaVersion"] == 1
    match document.get("images"):
        case list(images):
            specs: list[tuple[str, str, str, str | None, bool]] = []
            for image in images:
                match image:
                    case {
                        "name": str(name),
                        "context": str(context),
                        "dockerfile": str(dockerfile),
                        "local": bool(local),
                        **other,
                    }:
                        build_args = other.get("buildArgs", {})
                        assert isinstance(build_args, dict)
                        assert len(build_args) <= 1
                        build_arg = next(
                            (f"{key}={value}" for key, value in sorted(build_args.items())),
                            None,
                        )
                        specs.append(
                            (
                                name,
                                context,
                                (Path(context) / dockerfile).as_posix(),
                                build_arg,
                                local,
                            )
                        )
                    case _:
                        pytest.fail("inventory images must define typed build fields")
        case _:
            pytest.fail("image inventory must contain an images list")
    return tuple(specs)


@cache
def _first_party_image_specs() -> tuple[tuple[str, str, str, str], ...]:
    return tuple(
        (record.name, record.context, record.dockerfile, record.build_args) for record in load_inventory().images
    )


@cache
def _build_workflow() -> Workflow:
    return load_workflow(_REPOSITORY_ROOT / ".github" / "workflows" / "build-push.yml")


def _fake_container_runtime(tmp_path: Path) -> tuple[Path, Path]:
    runtime = tmp_path / "fake-container-runtime"
    invocation = tmp_path / "runtime-invocation.json"
    runtime.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "with open(os.environ['RUNTIME_INVOCATION'], 'w', encoding='utf-8') as output:\n"
        "    json.dump(sys.argv[1:], output)\n",
        encoding="utf-8",
    )
    runtime.chmod(0o755)
    return runtime, invocation


@cache
def _just_recipes() -> dict[str, dict[str, object]]:
    document: object = json.loads(
        subprocess.run(
            ["just", "--dump", "--dump-format", "json"],
            cwd=_REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    match document:
        case {"recipes": dict(recipes)}:
            typed_recipes: dict[str, dict[str, object]] = {}
            for name, recipe in recipes.items():
                if not isinstance(name, str) or not isinstance(recipe, dict):
                    pytest.fail("just recipes must be string-keyed mappings")
                typed_recipe: dict[str, object] = {}
                for key, value in recipe.items():
                    if not isinstance(key, str):
                        pytest.fail("just recipe fields must have string keys")
                    typed_recipe[key] = value
                typed_recipes[name] = typed_recipe
            return typed_recipes
        case _:
            pytest.fail("just dump must contain recipes")


def _recipe_commands(recipe: dict[str, object]) -> list[str]:
    body = recipe["body"]
    assert isinstance(body, list)
    commands: list[str] = []
    for fragments in body:
        assert isinstance(fragments, list)
        parts: list[str] = []
        for fragment in fragments:
            if isinstance(fragment, str):
                parts.append(fragment)
                continue
            assert fragment == [["variable", "args"]]
            parts.append("{{ args }}")
        commands.append("".join(parts))
    return commands


def _collecting_runtime(tmp_path: Path) -> tuple[Path, Path]:
    runtime = tmp_path / "collecting-runtime"
    calls = tmp_path / "calls"
    calls.mkdir()
    runtime.write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        "previous=\n"
        "for argument do\n"
        '    if [ "$previous" = "-t" ]; then tag=$argument; break; fi\n'
        "    previous=$argument\n"
        "done\n"
        'test -n "${tag:-}"\n'
        'printf "%s\\n" "$@" > "$RUNTIME_CALLS/$tag"\n',
        encoding="utf-8",
    )
    runtime.chmod(0o755)
    return runtime, calls


def test_single_image_build_uses_every_canonical_spec(tmp_path: Path) -> None:
    runtime, calls = _collecting_runtime(tmp_path)
    specs = _first_party_image_specs()
    env = os.environ | {
        "CONTAINER_RUNTIME": str(runtime),
        "RUNTIME_CALLS": str(calls),
    }

    local_specs = {
        (image, context, dockerfile, build_arg or "")
        for image, context, dockerfile, build_arg, _ in _image_inventory_specs()
    }
    assert set(specs) == local_specs
    build_args = {image: build_arg for image, _, _, build_arg in specs}
    assert build_args == {image: local_build_arg or "" for image, _, _, local_build_arg, _ in _image_inventory_specs()}
    assert build_args["ml-compute-service-gpu"] == "ML_COMPUTE_BUILDER=sync-gpu"
    assert build_args["ml-compute-service"] == ""
    command = ["just"]
    for image, *_ in specs:
        command.extend(("build", image))
    subprocess.run(command, cwd=_REPOSITORY_ROOT, env=env, check=True)
    invocations = {
        argv[argv.index("-t") + 1]: argv
        for path in calls.iterdir()
        if (argv := path.read_text(encoding="utf-8").splitlines())
    }
    for image, context, dockerfile, build_arg in specs:
        expected = ["build", "-f", dockerfile]
        if build_arg:
            expected += ["--build-arg", build_arg]
        expected += ["-t", f"{image}:latest", context]
        assert invocations[f"{image}:latest"] == expected


def test_single_image_build_rejects_unknown_name_before_runtime(tmp_path: Path) -> None:
    runtime, invocation = _fake_container_runtime(tmp_path)
    result = subprocess.run(
        ["just", "build", "not-a-first-party-image"],
        cwd=_REPOSITORY_ROOT,
        env=os.environ | {"CONTAINER_RUNTIME": str(runtime), "RUNTIME_INVOCATION": str(invocation)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "unknown first-party image: not-a-first-party-image" in result.stderr
    assert not invocation.exists()


def test_build_workflow_isolates_digest_gitops_permissions_and_triggers() -> None:
    workflow = _build_workflow()
    jobs = workflow["jobs"]
    validation = jobs["event-validation"]
    assert validation["permissions"] == {"actions": "read", "contents": "read"}
    build = jobs["build-push"]
    build_steps = build["steps"]
    steps = {step.get("id", step["name"]): step for step in build_steps}

    records = {record.name: record for record in load_inventory().images}
    assert len(records) == len(load_inventory().names)
    assert set(records) == {image for image, *_ in _image_inventory_specs()}
    cpu = records["ml-compute-service"]
    gpu = records["ml-compute-service-gpu"]
    assert cpu.build_args == ""
    assert gpu.build_args == "ML_COMPUTE_BUILDER=sync-gpu"
    assert gpu.dockerfile == cpu.dockerfile == "backend/services/ml-compute-service/Dockerfile"
    build_with = steps["build"]["with"]
    image_base_path = "steps.image-base-path.outputs.image_base_path"
    cache_from = build_with["cache-from"]
    cache_to = build_with["cache-to"]
    assert isinstance(cache_from, str)
    assert isinstance(cache_to, str)
    assert cache_from == (
        "${{ case(matrix.name == 'ml-compute-service-gpu', "
        f"format('type=registry,ref={{0}}/{{1}}:buildcache', {image_base_path}, matrix.name), "
        "format('type=gha,scope={0}', matrix.name)) }}"
    )
    assert cache_to == (
        "${{ case(matrix.name == 'ml-compute-service-gpu', "
        "case(steps.mode.outputs.push == 'true', "
        f"format('type=registry,ref={{0}}/{{1}}:buildcache,mode=max', {image_base_path}, matrix.name), "
        "''), format('type=gha,scope={0},mode=max', matrix.name)) }}"
    )
    assert "hashFiles" not in cache_from
    assert "hashFiles" not in cache_to
    login_name = "Log into GitHub Container Registry"
    assert steps[login_name]["if"] == ("steps.mode.outputs.push == 'true' || matrix.name == 'ml-compute-service-gpu'")
    assert next(index for index, step in enumerate(build_steps) if step["name"] == login_name) < next(
        index for index, step in enumerate(build_steps) if step.get("id") == "build"
    )
    kafka_entry = records["kafka-connect"]
    assert kafka_entry.context == "infra/k8s/kafka-connect"
    assert kafka_entry.dockerfile == "infra/k8s/kafka-connect/Dockerfile"
    assert kafka_entry.lockfile == "infra/k8s/kafka-connect/smt/build.gradle.kts"
    assert kafka_entry.build_args == ""
    assert steps["capture-digest"]["if"] == "steps.mode.outputs.push == 'true'"
    assert steps["capture-digest"]["env"]["IMAGE_DIGEST"] == "${{ steps.build.outputs.digest }}"
    assert steps["upload-digest"]["if"] == "steps.mode.outputs.push == 'true'"
    assert steps["upload-digest"]["with"]["name"] == "image-digest-${{ matrix.name }}"
    assert build["permissions"] == {"contents": "read", "packages": "write"}

    aggregate = jobs["aggregate-digests"]
    assert aggregate["needs"] == ["event-validation", "build-push"]
    assert aggregate["permissions"] == {
        "actions": "read",
        "contents": "write",
        "pull-requests": "write",
    }
    aggregate_steps = aggregate["steps"]
    download = next(step for step in aggregate_steps if step["name"] == "Download image digest records")
    assert download["with"]["pattern"] == "image-digest-*"
    assert download["with"]["merge-multiple"] is True
    upload = next(step for step in aggregate_steps if step["name"] == "Upload aggregate production digests")
    assert upload["with"]["path"] == "infra/k8s/helm/values.prod.digests.yaml"

    pr = next(step for step in aggregate_steps if step["name"] == "Create or update digest PR")
    assert pr["if"] == "env.PROPOSAL_ENABLED == 'true'"
    assert "create-pull-request" in str(pr["uses"])
    assert pr["with"]["base"] == "main"
    assert pr["with"]["branch"] == "bot/update-production-image-digests"
    assert pr["with"]["add-paths"] == "infra/k8s/helm/values.prod.digests.yaml"
    pr_body = pr["with"]["body"]
    assert isinstance(pr_body, str)
    assert "Source revision: `${{ needs.event-validation.outputs.source_sha }}`" in pr_body
    assert (
        "Workflow run: ${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}" in pr_body
    )
    assert all("git push" not in str(step.get("run", "")) for step in aggregate_steps)
    write_jobs = {
        job_name
        for job_name, job in jobs.items()
        if any(job.get("permissions", {}).get(name) == "write" for name in ("contents", "pull-requests"))
    }
    assert write_jobs == {"aggregate-digests"}

    match workflow.get("on"):
        case {"workflow_run": workflow_run}:
            pass
        case _:
            pytest.fail("build workflow must define workflow_run")
    assert workflow_run == {
        "workflows": ["Checks"],
        "types": ["completed"],
        "branches": ["main"],
    }


def test_build_workflow_reclaims_build_cache_before_trivy_scan() -> None:
    build = _build_workflow()["jobs"]["build-push"]
    steps = build["steps"]
    names = [step["name"] for step in steps]
    build_index = names.index("Build container image for ${{ matrix.name }}")
    scan_index = names.index("Run Trivy vulnerability scanner")
    prune_steps = [
        (index, step)
        for index, step in enumerate(steps)
        if str(step.get("run", "")).rstrip("\n") == "docker buildx prune --all --force"
    ]

    assert len(prune_steps) == 1
    prune_index, prune_step = prune_steps[0]
    assert str(prune_step["run"]).rstrip("\n") == "docker buildx prune --all --force"
    assert build_index < prune_index < scan_index


def test_local_deploy_inventory_excludes_only_the_gpu_image() -> None:
    inventory = _image_inventory_specs()
    inventory_names = {image for image, *_ in inventory}
    release_names = set(load_inventory().names)
    assert len(inventory_names) == len(inventory)
    assert inventory_names == release_names

    non_local_names = {image for image, *_, local in inventory if not local}
    assert non_local_names == {"ml-compute-service-gpu"}
    assert {image for image, *_, local in inventory if local} == (release_names - non_local_names)

    expected_lifecycle_commands = {
        "k8s-preflight-local": "preflight",
        "k8s-bootstrap-local": "bootstrap",
        "k8s-publish-local-images": "publish",
        "k8s-reconcile-local": "reconcile",
        "k8s-verify-local": "verify",
        "k8s-diagnostics-local": "diagnostics",
        "k8s-factory-reset-local": "factory-reset {{ args }}",
    }
    recipes = _just_recipes()
    recipe_names = {name for name, recipe in recipes.items() if not recipe["private"]}
    assert {name for name in recipe_names if name.startswith("k8s-") and "-local" in name} == set(
        expected_lifecycle_commands
    )
    for recipe, action in expected_lifecycle_commands.items():
        commands = _recipe_commands(recipes[recipe])
        assert commands == [f"infra/k8s/local/lifecycle.sh {action}"], recipe


def test_build_all_emits_every_release_spec_including_gpu_and_kafka_connect(
    tmp_path: Path,
) -> None:
    runtime, calls = _collecting_runtime(tmp_path)
    subprocess.run(
        ["just", "build-all"],
        cwd=_REPOSITORY_ROOT,
        env=os.environ | {"CONTAINER_RUNTIME": str(runtime), "RUNTIME_CALLS": str(calls)},
        check=True,
    )
    invocations = [path.read_text(encoding="utf-8").splitlines() for path in calls.iterdir()]
    specs = _first_party_image_specs()
    tags = {argv[argv.index("-t") + 1] for argv in invocations}
    assert len(invocations) == len(specs)
    assert tags == {f"{image}:latest" for image, *_ in specs}
    assert {"ml-compute-service-gpu:latest", "kafka-connect:latest"} <= tags
    gpu = next(argv for argv in invocations if argv[argv.index("-t") + 1] == "ml-compute-service-gpu:latest")
    assert "--build-arg" in gpu
    assert gpu[gpu.index("--build-arg") + 1] == "ML_COMPUTE_BUILDER=sync-gpu"
