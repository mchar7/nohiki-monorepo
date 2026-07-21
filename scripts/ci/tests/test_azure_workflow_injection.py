from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Mapping
from functools import cache
from pathlib import Path
from typing import cast

import yaml


def _mapping(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return cast("dict[str, object]", value)


def _mapping_list(value: object) -> list[dict[str, object]]:
    assert isinstance(value, list)
    return [_mapping(item) for item in value]


def _mapping_at(mapping: Mapping[str, object], key: str) -> dict[str, object]:
    return _mapping(mapping[key])


def _mapping_list_at(mapping: Mapping[str, object], key: str) -> list[dict[str, object]]:
    return _mapping_list(mapping[key])


_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_IMAGE_INVENTORY = _REPOSITORY_ROOT / "infra" / "k8s" / "local" / "images.json"


@cache
def _image_inventory_specs() -> tuple[tuple[str, str, str, str | None, bool], ...]:
    document = json.loads(_IMAGE_INVENTORY.read_text(encoding="utf-8"))
    assert document["schemaVersion"] == 1
    images = document["images"]
    assert isinstance(images, list)
    specs: list[tuple[str, str, str, str | None, bool]] = []
    for image in images:
        assert isinstance(image, dict)
        context = str(image["context"])
        build_args = image.get("buildArgs", {})
        assert isinstance(build_args, dict)
        assert len(build_args) <= 1
        local = image["local"]
        assert isinstance(local, bool)
        build_arg = next((f"{key}={value}" for key, value in sorted(build_args.items())), None)
        specs.append(
            (
                str(image["name"]),
                context,
                (Path(context) / str(image["dockerfile"])).as_posix(),
                build_arg,
                local,
            )
        )
    return tuple(specs)


@cache
def _evaluate(name: str) -> str:
    return subprocess.run(
        ["just", "--evaluate", name],
        cwd=_REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


@cache
def _first_party_image_specs() -> tuple[tuple[str, str, str, str | None], ...]:
    specs: list[tuple[str, str, str, str | None]] = []
    for spec in _evaluate("first_party_image_specs").split():
        image, context, dockerfile, *rest = spec.split("|")
        specs.append((image, context, dockerfile, rest[0] if rest else None))
    return tuple(specs)


@cache
def _build_workflow() -> dict[str, object]:
    return cast(
        "dict[str, object]",
        yaml.safe_load((_REPOSITORY_ROOT / ".github" / "workflows" / "build-push.yml").read_text(encoding="utf-8")),
    )


@cache
def _matrix_include() -> list[dict[str, object]]:
    workflow = _build_workflow()
    jobs = _mapping_at(workflow, "jobs")
    build = _mapping_at(jobs, "build-push")
    strategy = _mapping_at(build, "strategy")
    matrix = _mapping_at(strategy, "matrix")
    return _mapping_list_at(matrix, "include")


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
    document = json.loads(
        subprocess.run(
            ["just", "--dump", "--dump-format", "json"],
            cwd=_REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    recipes = document["recipes"]
    assert isinstance(recipes, dict)
    return recipes


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

    inventory_specs = {
        (image, context, dockerfile, build_arg) for image, context, dockerfile, build_arg, _ in _image_inventory_specs()
    }
    workflow_specs = {
        (
            str(entry["name"]),
            str(entry.get("context", ".")),
            str(entry["dockerfile"]),
            str(entry["build_args"]) if "build_args" in entry else None,
        )
        for entry in _matrix_include()
    }
    assert set(specs) == inventory_specs == workflow_specs
    build_args = {image: build_arg for image, _, _, build_arg in specs}
    assert build_args == {
        image: inventory_build_arg for image, _, _, inventory_build_arg, _ in _image_inventory_specs()
    }
    assert build_args["ml-compute-service-gpu"] == "ML_COMPUTE_BUILDER=sync-gpu"
    assert build_args["ml-compute-service"] is None
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
        if build_arg is not None:
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
    jobs = _mapping_at(workflow, "jobs")
    build = _mapping_at(jobs, "build-push")
    build_steps = _mapping_list_at(build, "steps")
    steps: dict[str, dict[str, object]] = {cast("str", step.get("id", step["name"])): step for step in build_steps}

    matrix = _mapping_at(_mapping_at(build, "strategy"), "matrix")
    include = _mapping_list_at(matrix, "include")
    names = [entry["name"] for entry in include]
    assert len(names) == len(set(names))
    assert set(names) == {image for image, *_ in _image_inventory_specs()}
    cpu = next(entry for entry in include if entry["name"] == "ml-compute-service")
    gpu = next(entry for entry in include if entry["name"] == "ml-compute-service-gpu")
    assert "build_args" not in cpu
    assert gpu["build_args"] == "ML_COMPUTE_BUILDER=sync-gpu"
    assert gpu["dockerfile"] == cpu["dockerfile"] == "backend/services/ml-compute-service/Dockerfile"
    build_with = _mapping_at(_mapping_at(steps, "build"), "with")
    image_base_path = "steps.image-base-path.outputs.image_base_path"
    assert build_with["cache-from"] == (
        "${{ matrix.name == 'ml-compute-service-gpu' && "
        f"format('type=registry,ref={{0}}/{{1}}:buildcache', {image_base_path}, matrix.name) "
        "|| format('type=gha,scope={0}', matrix.name) }}"
    )
    assert build_with["cache-to"] == (
        "${{ matrix.name == 'ml-compute-service-gpu' && "
        "(steps.mode.outputs.push == 'true' && "
        f"format('type=registry,ref={{0}}/{{1}}:buildcache,mode=max', {image_base_path}, matrix.name) || '') "
        "|| format('type=gha,mode=max,scope={0}', matrix.name) }}"
    )
    login_name = "Log into GitHub Container Registry"
    assert _mapping_at(steps, login_name)["if"] == (
        "steps.mode.outputs.push == 'true' || matrix.name == 'ml-compute-service-gpu'"
    )
    assert next(index for index, step in enumerate(build_steps) if step["name"] == login_name) < next(
        index for index, step in enumerate(build_steps) if step.get("id") == "build"
    )
    kafka_entry = next(entry for entry in include if entry["name"] == "kafka-connect")
    assert kafka_entry == {
        "name": "kafka-connect",
        "context": "infra/k8s/kafka-connect",
        "dockerfile": "infra/k8s/kafka-connect/Dockerfile",
    }
    assert _mapping_at(steps, "capture-digest")["if"] == "steps.mode.outputs.push == 'true'"
    assert _mapping_at(_mapping_at(steps, "capture-digest"), "env")["IMAGE_DIGEST"] == (
        "${{ steps.build.outputs.digest }}"
    )
    assert _mapping_at(steps, "upload-digest")["if"] == "steps.mode.outputs.push == 'true'"
    assert _mapping_at(_mapping_at(steps, "upload-digest"), "with")["name"] == "image-digest-${{ matrix.name }}"
    assert build["permissions"] == {"contents": "read", "packages": "write"}

    aggregate = _mapping_at(jobs, "aggregate-digests")
    assert aggregate["needs"] == ["event-validation", "build-push"]
    assert aggregate["permissions"] == {"contents": "read"}
    download = next(
        step for step in _mapping_list_at(aggregate, "steps") if step["name"] == "Download image digest records"
    )
    assert _mapping_at(download, "with")["pattern"] == "image-digest-*"
    assert _mapping_at(download, "with")["merge-multiple"] is True
    upload = next(
        step for step in _mapping_list_at(aggregate, "steps") if step["name"] == "Upload aggregate production digests"
    )
    assert _mapping_at(upload, "with")["path"] == "infra/k8s/helm/values.prod.digests.yaml"

    proposal = _mapping_at(jobs, "propose-digests")
    assert proposal["needs"] == ["event-validation", "aggregate-digests"]
    assert "github.event_name == 'workflow_run'" in str(proposal["if"])
    assert "needs.event-validation.outputs.authorized == 'true'" in str(proposal["if"])
    assert proposal["permissions"] == {"contents": "write", "pull-requests": "write"}
    proposal_steps = _mapping_list_at(proposal, "steps")
    pr = next(step for step in proposal_steps if step["name"] == "Create or update digest PR")
    assert "create-pull-request" in str(pr["uses"])
    assert _mapping_at(pr, "with")["base"] == "main"
    assert _mapping_at(pr, "with")["branch"] == "bot/update-production-image-digests"
    assert _mapping_at(pr, "with")["add-paths"] == "infra/k8s/helm/values.prod.digests.yaml"
    pr_body = _mapping_at(pr, "with")["body"]
    assert "Source revision: `${{ needs.event-validation.outputs.source_sha }}`" in pr_body
    assert (
        "Workflow run: ${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}" in pr_body
    )
    assert all("git push" not in str(step.get("run", "")) for step in proposal_steps)

    workflow_run = _mapping(workflow.get("on", workflow.get(True)))["workflow_run"]
    assert workflow_run == {
        "workflows": ["Checks"],
        "types": ["completed"],
        "branches": ["main"],
    }


def test_build_workflow_reclaims_build_cache_before_trivy_scan() -> None:
    workflow = _build_workflow()
    build = _mapping_at(_mapping_at(workflow, "jobs"), "build-push")
    steps = _mapping_list_at(build, "steps")
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


def test_local_deploy_inventory_excludes_gpu_and_kafka_connect() -> None:
    inventory = _image_inventory_specs()
    inventory_names = {image for image, *_ in inventory}
    release_names = set(_evaluate("first_party_image_names").split())
    assert len(inventory_names) == len(inventory)
    assert inventory_names == release_names == {str(entry["name"]) for entry in _matrix_include()}

    non_local_names = {image for image, *_, local in inventory if not local}
    assert non_local_names == {"ml-compute-service-gpu", "kafka-connect"}
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
