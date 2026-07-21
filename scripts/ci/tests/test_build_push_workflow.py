from pathlib import Path

import yaml

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
    assert validation["permissions"] == {"contents": "read"}

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
    assert build["needs"] == ["event-validation"]
    assert build["if"] == "needs.event-validation.outputs.authorized == 'true'"
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
    assert upload["uses"] == "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"
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
    assert aggregate["permissions"] == {"contents": "read"}
    proposal = jobs["propose-digests"]
    assert proposal["needs"] == ["event-validation", "aggregate-digests"]
    assert "github.event_name == 'workflow_run'" in proposal["if"]
    assert "needs.event-validation.outputs.authorized == 'true'" in proposal["if"]
    assert proposal["permissions"] == {"contents": "write", "pull-requests": "write"}
    assert "id-token" not in proposal["permissions"]


def test_trivy_waivers_each_have_a_reason_and_expiry() -> None:
    blocks = _TRIVYIGNORE.read_text(encoding="utf-8").strip().split("\n\n")

    assert blocks
    for block in blocks:
        reason, expiry, vulnerability_id = block.splitlines()
        assert reason.startswith("# Reason: ")
        assert expiry.startswith("# Expires: 20")
        assert vulnerability_id.startswith("CVE-")
