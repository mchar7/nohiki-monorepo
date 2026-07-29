from pathlib import Path

import yaml
from ci_checks.core.image_inventory import load_inventory

_ROOT = Path(__file__).resolve().parents[3]
_WORKFLOW = _ROOT / ".github" / "workflows" / "build-push.yml"
_TRIVYIGNORE = _ROOT / ".trivyignore"


def test_image_publication_is_authorized_by_successful_main_checks_or_manual_dispatch() -> None:
    workflow = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))
    triggers = workflow.get("on", workflow.get(True))
    assert triggers == {
        "workflow_run": {
            "workflows": ["Checks"],
            "types": ["completed"],
            "branches": ["main"],
        },
        "workflow_dispatch": {
            "inputs": {
                "push_to_registry": {
                    "description": "Push images to container registry? (false = build + scan only)",
                    "type": "boolean",
                    "default": False,
                },
                "image_tag": {
                    "description": "Common image tag for all services (e.g., manual-build-v1; only if pushing images)",
                    "type": "string",
                    "required": False,
                },
            }
        },
    }

    jobs = workflow["jobs"]
    validation = jobs["event-validation"]
    condition = validation["if"]
    for gate in (
        "github.event_name == 'workflow_dispatch'",
        "github.event_name == 'workflow_run'",
        "github.event.workflow_run.name == 'Checks'",
        "github.event.workflow_run.event == 'push'",
        "github.event.workflow_run.conclusion == 'success'",
        "github.event.workflow_run.head_branch == 'main'",
        "github.event.workflow_run.head_repository.full_name == github.repository",
        "vars.IMAGE_PUBLICATION_ENABLED == 'true'",
    ):
        assert gate in condition
    assert condition.index("github.event_name == 'workflow_dispatch'") < condition.index("||")
    assert condition.index("||") < condition.index("vars.IMAGE_PUBLICATION_ENABLED == 'true'")
    assert condition.count("vars.IMAGE_PUBLICATION_ENABLED == 'true'") == 1
    validation_steps_env = next(step["env"] for step in validation["steps"] if step.get("id") == "validate-event")
    assert validation_steps_env["PUBLICATION_ENABLED"] == "${{ vars.IMAGE_PUBLICATION_ENABLED }}"
    assert validation["permissions"] == {"actions": "read", "contents": "read"}

    validation_steps = {step.get("id", step["name"]): step for step in validation["steps"]}
    script = validation_steps["validate-event"]["run"]
    for check in (
        '[[ "$CHECKS_NAME" == "Checks" ]]',
        '[[ "$CHECKS_EVENT" == "push" ]]',
        '[[ "$CHECKS_CONCLUSION" == "success" ]]',
        '[[ "$HEAD_BRANCH" == "main" ]]',
        '[[ "$HEAD_REPOSITORY" == "$REPOSITORY" ]]',
        '[[ "$PUBLICATION_ENABLED" == "true" ]]',
        '[[ "$WORKFLOW_RUN_SHA" =~ ^[0-9a-f]{40}$ ]]',
    ):
        assert check in script
    assert 'should_push="true"' in script
    assert 'should_push="$PUSH_TO_REGISTRY"' in script
    assert '[[ "$should_push" == "false" ]]' in script
    assert '[[ -n "$IMAGE_TAG" ]]' in script
    assert '[[ "$IMAGE_TAG" =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$ ]]' in script
    assert 'echo "Error: Image tag must match the OCI tag policy." >&2' in script
    assert "Invalid image tag format for" not in script
    assert 'tags_metadata_string="type=raw,value=${IMAGE_TAG},enable=true"' in script
    assert "enabled=" not in script
    assert 'short_source_sha="${source_sha:0:7}"' in script
    assert '[[ "$short_source_sha" =~ ^[0-9a-f]{7}$ ]]' in script
    assert 'echo "short_source_sha=$short_source_sha"' in script
    assert validation["outputs"]["short_source_sha"] == ("${{ steps.validate-event.outputs.short_source_sha }}")

    source_checkout = next(step for step in validation["steps"] if step["name"] == "Check out publication source")
    assert source_checkout["with"] == {
        "ref": "${{ steps.validate-event.outputs.source_sha }}",
        "fetch-depth": 2,
        "persist-credentials": False,
    }
    authorization = validation_steps["authorize"]["run"]
    merge_guard = 'git rev-parse --verify "$SOURCE_SHA^2^{commit}"'
    assert merge_guard in authorization
    assert authorization.index(merge_guard) < authorization.index("git diff-tree")
    assert 'git diff-tree --no-commit-id --name-only -r "$SOURCE_SHA^" "$SOURCE_SHA"' in authorization
    assert 'if [[ "$changed_paths" == "infra/k8s/helm/values.prod.digests.yaml" ]]' in authorization
    assert 'authorized="false"' in authorization

    build = jobs["build-push"]
    build_steps = {step.get("id", step["name"]): step for step in build["steps"]}
    for record in load_inventory().images:
        expected_lockfile = (
            "pnpm-lock.yaml"
            if record.name in {"frontend", "playwright-verification-runner"}
            else "infra/k8s/kafka-connect/smt/build.gradle.kts"
            if record.name == "kafka-connect"
            else "uv.lock"
        )
        assert record.lockfile == expected_lockfile
        assert (_ROOT / record.dockerfile).is_file()
        assert (_ROOT / record.lockfile).is_file()

    cache_inputs = "hashFiles(matrix.dockerfile, matrix.lockfile)"
    assert build_steps["build"]["with"]["cache-from"] == (
        "${{ matrix.name == 'ml-compute-service-gpu' && "
        "format('type=registry,ref={0}/{1}:buildcache-{2}', "
        "steps.image-base-path.outputs.image_base_path, matrix.name, "
        f"{cache_inputs}) || format('type=gha,scope={{0}}-{{1}}', matrix.name, {cache_inputs})"
        " }}"
    )
    assert build_steps["build"]["with"]["cache-to"] == (
        "${{ matrix.name == 'ml-compute-service-gpu' && "
        "(steps.mode.outputs.push == 'true' && "
        "format('type=registry,ref={0}/{1}:buildcache-{2},mode=max', "
        "steps.image-base-path.outputs.image_base_path, matrix.name, "
        f"{cache_inputs}) || '') || format('type=gha,mode=max,scope={{0}}-{{1}}', "
        f"matrix.name, {cache_inputs})"
        " }}"
    )
    assert build["needs"] == ["event-validation"]
    for gate in (
        "needs.event-validation.outputs.authorized == 'true'",
        "needs.event-validation.outputs.has_images == 'true'",
    ):
        assert gate in build["if"]
    assert build["permissions"] == {
        "contents": "read",
        "packages": "write",
    }
    assert "id-token" not in build["permissions"]
    assert build_steps["mode"]["env"]["SHOULD_PUSH"] == "${{ needs.event-validation.outputs.should_push }}"
    assert build_steps["build"]["with"]["push"] == "${{ steps.mode.outputs.push == 'true' }}"
    assert build_steps["build"]["with"]["provenance"] == "${{ steps.mode.outputs.push == 'true' }}"
    metadata_tags = build_steps["meta"]["with"]["tags"]
    assert "type=ref,event=tag" not in metadata_tags
    assert "type=raw,value=sha-${{ needs.event-validation.outputs.short_source_sha }},enable=true" in metadata_tags
    assert "needs.event-validation.outputs.source_sha" not in metadata_tags
    assert build_steps["capture-digest"]["env"]["SOURCE_SHA"] == ("${{ needs.event-validation.outputs.source_sha }}")
    trivy = build_steps["Run Trivy vulnerability scanner"]
    assert trivy["env"] == {
        "TRIVY_DISABLE_TELEMETRY": "true",
        "TRIVY_SKIP_VERSION_CHECK": "true",
    }
    assert trivy["with"] == {
        "image-ref": "${{ fromJSON(steps.meta.outputs.json).tags[0] }}",
        "format": "sarif",
        "output": "trivy-results-${{ matrix.name }}.sarif",
        "severity": "CRITICAL,HIGH",
        "exit-code": "1",
    }
    upload = build_steps["Upload Trivy scan results"]
    assert upload["uses"].startswith("actions/upload-artifact@")
    assert upload["if"] == "always()"
    assert upload["with"] == {
        "name": "trivy-results-${{ matrix.name }}",
        "path": "trivy-results-${{ matrix.name }}.sarif",
        "if-no-files-found": "error",
        "retention-days": 30,
    }
    assert all("upload-sarif" not in step.get("uses", "") for step in build["steps"])

    aggregate = jobs["aggregate-digests"]
    assert aggregate["needs"] == ["event-validation", "build-push"]
    assert aggregate["permissions"] == {
        "actions": "read",
        "contents": "write",
        "pull-requests": "write",
    }
    assert "id-token" not in aggregate["permissions"]
    aggregate_steps = {step.get("id", step["name"]): step for step in aggregate["steps"]}
    proposal = aggregate_steps["Create or update digest PR"]
    assert proposal["if"] == "env.PROPOSAL_ENABLED == 'true'"
    assert "create-pull-request" in proposal["uses"]
    assert {
        job_name
        for job_name, job in jobs.items()
        if any(job["permissions"].get(name) == "write" for name in ("contents", "pull-requests"))
    } == {"aggregate-digests"}


def test_build_push_matrix_is_resolved_from_the_affected_image_record() -> None:
    workflow = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))
    triggers = workflow.get("on", workflow.get(True))
    assert set(triggers) == {"workflow_run", "workflow_dispatch"}
    assert "schedule" not in triggers

    jobs = workflow["jobs"]
    assert set(jobs) == {"event-validation", "build-push", "aggregate-digests"}

    validation = jobs["event-validation"]
    assert validation["timeout-minutes"] == 1
    assert validation["outputs"] == {
        "authorized": "${{ steps.authorize.outputs.authorized }}",
        "source_sha": "${{ steps.validate-event.outputs.source_sha }}",
        "short_source_sha": "${{ steps.validate-event.outputs.short_source_sha }}",
        "should_push": "${{ steps.validate-event.outputs.should_push }}",
        "image_tags_metadata_string": "${{ steps.validate-event.outputs.tags_metadata_string }}",
        "common_image_tag_output": "${{ steps.validate-event.outputs.common_tag }}",
        "matrix": "${{ steps.resolve-images.outputs.matrix }}",
        "images": "${{ steps.resolve-images.outputs.images }}",
        "has_images": "${{ steps.resolve-images.outputs.has_images }}",
    }

    validation_steps = {step.get("id", step["name"]): step for step in validation["steps"]}
    download = validation_steps["affected-record"]
    assert download["if"] == "github.event_name == 'workflow_run'"
    assert download["continue-on-error"] is True
    assert download["uses"].startswith("actions/download-artifact@")
    assert download["with"]["name"] == "affected-images"
    assert download["with"]["path"] == "affected-images"
    # The record belongs to the triggering Checks run, never to this build-push run.
    assert download["with"]["run-id"] == "${{ github.event.workflow_run.id }}"
    assert "github.run_id" not in download["with"]["run-id"]
    assert download["with"]["github-token"] == "${{ github.token }}"
    assert all("sleep" not in step.get("run", "") for step in validation["steps"])
    assert (
        sum(
            1
            for job in jobs.values()
            for step in job["steps"]
            if "actions/download-artifact" in step.get("uses", "") and "run-id" in step.get("with", {})
        )
        == 1
    )

    resolve = validation_steps["resolve-images"]
    assert resolve["env"]["RECORD_OUTCOME"] == "${{ steps.affected-record.outcome }}"
    assert "$RECORD_OUTCOME" in resolve["run"]
    assert "python3 scripts/ci/image_matrix.py matrix" in resolve["run"]
    assert "uv sync" not in resolve["run"]
    assert "uv run" not in resolve["run"]

    build = jobs["build-push"]
    strategy = build["strategy"]
    assert "include" not in strategy
    assert strategy["fail-fast"] is False
    assert strategy["matrix"] == "${{ fromJSON(needs.event-validation.outputs.matrix) }}"
    assert build["timeout-minutes"] == "${{ matrix.timeout_minutes }}"
    assert {record.timeout for record in load_inventory().images} == {16}

    assemble = next(
        step
        for step in jobs["aggregate-digests"]["steps"]
        if step["name"] == "Assemble and validate production digests"
    )
    assert assemble["env"]["AFFECTED_IMAGES"] == "${{ needs.event-validation.outputs.images }}"
    assert "--existing infra/k8s/helm/values.prod.digests.yaml" in assemble["run"]
    assert '--affected "$AFFECTED_IMAGES"' in assemble["run"]


def test_trivy_waivers_each_have_a_reason_and_expiry() -> None:
    blocks = _TRIVYIGNORE.read_text(encoding="utf-8").strip().split("\n\n")

    assert blocks
    for block in blocks:
        reason, expiry, vulnerability_id = block.splitlines()
        assert reason.startswith("# Reason: ")
        assert expiry.startswith("# Expires: 20")
        assert vulnerability_id.startswith("CVE-")
