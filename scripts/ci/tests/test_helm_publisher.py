from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from collections.abc import Callable
from functools import cache
from pathlib import Path
from typing import Any

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[3]
_WORKFLOW = _ROOT / ".github" / "workflows" / "release-helm-charts.yml"
_HELPER = _ROOT / "scripts" / "ci" / "helm_release_record.py"
_HELPER_SPEC = importlib.util.spec_from_file_location("helm_release_record_under_test", _HELPER)
assert _HELPER_SPEC is not None
assert _HELPER_SPEC.loader is not None
_HELPER_MODULE = importlib.util.module_from_spec(_HELPER_SPEC)
_HELPER_SPEC.loader.exec_module(_HELPER_MODULE)
_RELEASE_RECORD = "helm-release-record.json"
_REPOSITORY = "mchar7/nohiki-monorepo"
_SOURCE_SHA = "a" * 40
_OTHER_SOURCE_SHA = "a" * 12 + "b" * 28
_FOUNDATION_DIGEST = "sha256:" + "1" * 64
_APPLICATION_DIGEST = "sha256:" + "2" * 64
_FOUNDATION_PACKAGE_SHA256 = "3" * 64
_APPLICATION_PACKAGE_SHA256 = "4" * 64
_ACTION = re.compile(
    r"^\s*uses:\s*(?P<action>[^@\s]+)@(?P<ref>[^\s#]+)(?:\s+#\s*(?P<version>\S+))?\s*$",
    re.MULTILINE,
)
_CHARTS = (
    _ROOT / "infra" / "k8s" / "helm-foundation" / "Chart.yaml",
    _ROOT / "infra" / "k8s" / "helm" / "Chart.yaml",
)
_HELM_REPO_ADD = re.compile(
    r"^[ \t]*helm[ \t]+repo[ \t]+add[ \t]+"
    r"(?P<alias>[A-Za-z0-9][A-Za-z0-9._-]*)[ \t]+"
    r"(?P<repository>\"[^\"]+\"|'[^']+'|[^ \t\r\n\\]+)[ \t]*$",
    re.MULTILINE,
)


@cache
def _http_chart_repositories() -> frozenset[str]:
    repositories: set[str] = set()
    for chart_path in _CHARTS:
        chart = yaml.safe_load(chart_path.read_text(encoding="utf-8"))
        assert isinstance(chart, dict)
        dependencies = chart.get("dependencies")
        assert isinstance(dependencies, list)
        for dependency in dependencies:
            assert isinstance(dependency, dict)
            repository = dependency.get("repository")
            assert isinstance(repository, str)
            if repository.startswith(("http://", "https://")):
                repositories.add(repository)
    return frozenset(repositories)


def _repo_additions(script: str) -> list[tuple[str, str]]:
    additions = []
    for match in _HELM_REPO_ADD.finditer(script):
        repository = match["repository"].strip("\"'")
        additions.append((match["alias"], repository))
    return additions


def test_repo_additions_reject_trailing_flags() -> None:
    assert (
        _repo_additions("helm repo add grafana https://grafana.github.io/helm-charts --insecure-skip-tls-verify\n")
        == []
    )


def _foundation_version(source_sha: str) -> str:
    return f"0.1.0-{source_sha}"


def _application_version(source_sha: str) -> str:
    return f"0.2.0-{source_sha}"


@cache
def _load_workflow() -> dict[str, Any]:
    workflow = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(workflow, dict)
    return workflow


def _triggers(workflow: dict[str, Any]) -> dict[str, Any]:
    # PyYAML 1.1 treats an unquoted GitHub Actions `on` key as boolean true.
    triggers = workflow.get("on", workflow.get(True))
    assert isinstance(triggers, dict)
    return triggers


def _steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    steps = job.get("steps")
    assert isinstance(steps, list)
    return steps


def _named_steps(job: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {step["name"]: step for step in _steps(job) if isinstance(step.get("name"), str)}


def _action_step(job: dict[str, Any], action: str) -> dict[str, Any]:
    matches = [step for step in _steps(job) if str(step.get("uses", "")).startswith(f"{action}@")]
    assert len(matches) == 1, f"expected exactly one {action} step, found {len(matches)}"
    return matches[0]


def _helper_arguments(
    output: Path,
    *,
    repository: str = _REPOSITORY,
    source_sha: str = _SOURCE_SHA,
    workflow_run_id: str = "12345",
    foundation_version: str | None = None,
    application_version: str | None = None,
    foundation_digest: str = _FOUNDATION_DIGEST,
    application_digest: str = _APPLICATION_DIGEST,
    foundation_package_sha256: str = _FOUNDATION_PACKAGE_SHA256,
    application_package_sha256: str = _APPLICATION_PACKAGE_SHA256,
) -> list[str]:
    return [
        str(_HELPER),
        "--repository",
        repository,
        "--source-sha",
        source_sha,
        "--workflow-run-id",
        workflow_run_id,
        "--foundation-version",
        foundation_version if foundation_version is not None else _foundation_version(source_sha),
        "--application-version",
        application_version if application_version is not None else _application_version(source_sha),
        "--foundation-digest",
        foundation_digest,
        "--application-digest",
        application_digest,
        "--foundation-package-sha256",
        foundation_package_sha256,
        "--application-package-sha256",
        application_package_sha256,
        "--output",
        str(output),
    ]


def _run_helper(tmp_path: Path, **values: str) -> tuple[subprocess.CompletedProcess[str], Path]:
    assert _HELPER.is_file(), f"missing release-record helper: {_HELPER.relative_to(_ROOT)}"
    output = tmp_path / _RELEASE_RECORD
    result = subprocess.run(
        [sys.executable, *_helper_arguments(output, **values)],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result, output


def _run_invalid_helper_in_process(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **values: str) -> Path:
    output = tmp_path / _RELEASE_RECORD
    monkeypatch.setattr(sys, "argv", _helper_arguments(output, **values))
    with pytest.raises(SystemExit) as raised:
        _HELPER_MODULE.main()
    assert raised.value.code != 0
    return output


def test_workflow_runs_only_after_successful_checks_on_main() -> None:
    workflow = _load_workflow()
    assert workflow["name"] == "Publish Helm charts"
    assert _triggers(workflow) == {
        "workflow_run": {
            "workflows": ["Checks"],
            "types": ["completed"],
            "branches": ["main"],
        }
    }

    assert set(workflow["jobs"]) == {"publish"}
    job = workflow["jobs"]["publish"]
    assert job["name"] == "Publish signed Helm charts"
    assert job["if"] == (
        "${{ github.event.workflow_run.conclusion == 'success' && github.event.workflow_run.head_branch == 'main'"
        " && vars.CHART_PUBLICATION_ENABLED == 'true' }}"
    )
    assert job["permissions"] == {
        "contents": "read",
        "id-token": "write",
        "packages": "write",
    }

    steps = _named_steps(job)
    validation = steps["Validate triggering Checks run"]["run"]
    assert "${{ github.event.workflow_run.head_sha }}" in validation
    assert "${{ github.event.workflow_run.conclusion }}" in validation
    assert "${{ github.event.workflow_run.head_branch }}" in validation

    checkout = _action_step(job, "actions/checkout")
    assert checkout["with"]["ref"] == "${{ github.event.workflow_run.head_sha }}"
    assert checkout["with"]["persist-credentials"] is False
    verification = steps["Verify checked-out source"]["run"]
    assert "git rev-parse HEAD" in verification
    assert "${{ github.event.workflow_run.head_sha }}" in verification


def test_workflow_actions_are_immutable_and_credentials_are_ephemeral() -> None:
    raw = _WORKFLOW.read_text(encoding="utf-8")
    actions = list(_ACTION.finditer(raw))
    assert actions
    assert all(re.fullmatch(r"[0-9a-f]{40}", match["ref"]) for match in actions)
    assert all(re.fullmatch(r"v\d+(?:\.\d+)*", match["version"] or "") for match in actions)
    action_identities = {match["action"] for match in actions}
    assert {
        "azure/setup-helm",
        "sigstore/cosign-installer",
        "docker/login-action",
        "actions/upload-artifact",
    } <= action_identities

    job = _load_workflow()["jobs"]["publish"]
    cosign = _action_step(job, "sigstore/cosign-installer")
    assert set(cosign["with"]) == {"cosign-release"}
    assert re.fullmatch(r"v\d+(?:\.\d+)*", cosign["with"]["cosign-release"])
    login = _action_step(job, "docker/login-action")
    assert login["env"]["DOCKER_CONFIG"] == "${{ runner.temp }}/helm-registry"
    assert login["with"] == {
        "registry": "ghcr.io",
        "username": "${{ github.actor }}",
        "password": "${{ github.token }}",
    }
    sign = _named_steps(job)["Sign and verify chart digests"]
    assert sign["env"]["DOCKER_CONFIG"] == login["env"]["DOCKER_CONFIG"]

    lowered = raw.lower()
    forbidden = (
        "${{ secrets.",
        "api.github.com",
        "gh api",
        "personal_access_token",
        "ghcr_pat",
        "cosign_private",
        "private-key",
        "registry_password",
        "kubernetes.io/dockerconfigjson",
        "imagepullsecrets",
        "kubectl create secret",
    )
    assert not [token for token in forbidden if token in lowered]
    assert re.search(r"\bpat\b", lowered) is None


def test_chart_versions_are_exact_source_sha_prereleases_and_are_published_in_order() -> None:
    job = _load_workflow()["jobs"]["publish"]
    steps = _named_steps(job)
    ordered_names = [step.get("name") for step in _steps(job)]
    required_order = [
        "Validate triggering Checks run",
        "Verify checked-out source",
        "Set up Helm",
        "Install Cosign",
        "Log in to GHCR",
        "Package and publish charts",
        "Sign and verify chart digests",
        "Write release record",
        "Upload release record",
    ]
    assert [ordered_names.index(name) for name in required_order] == sorted(
        ordered_names.index(name) for name in required_order
    )

    package_index = ordered_names.index("Package and publish charts")
    prior_scripts = "\n".join(str(step.get("run", "")) for step in _steps(job)[:package_index])
    assert "helm package" not in prior_scripts
    assert "helm push" not in prior_scripts

    package_step = steps["Package and publish charts"]
    assert package_step["env"]["SOURCE_SHA"] == "${{ github.event.workflow_run.head_sha }}"
    script = package_step["run"]
    expected_fragments = (
        '[[ "$SOURCE_SHA" =~ ^[0-9a-f]{40}$ ]]',
        'foundation_version="0.1.0-${SOURCE_SHA}"',
        'application_version="0.2.0-${SOURCE_SHA}"',
        '[[ "$foundation_version" =~ ^0\\.1\\.0-[0-9a-f]{40}$ ]]',
        '[[ "$application_version" =~ ^0\\.2\\.0-[0-9a-f]{40}$ ]]',
        'printf \'foundation_version=%s\\n\' "$foundation_version" >> "$GITHUB_OUTPUT"',
        'printf \'application_version=%s\\n\' "$application_version" >> "$GITHUB_OUTPUT"',
        "publish_chart infra/k8s/helm-foundation nohiki-foundation "
        '"$foundation_version" foundation_digest foundation_package_sha256',
        'publish_chart infra/k8s/helm nohiki "$application_version" application_digest application_package_sha256',
    )
    for fragment in expected_fragments:
        assert fragment in script

    assert 'repository="${GITHUB_REPOSITORY,,}"' in script
    assert 'registry_root="ghcr.io/${repository}/charts"' in script
    assert 'release_dir="${RUNNER_TEMP}/helm-release"' in script
    assert 'packages_dir="${release_dir}/packages"' in script
    assert 'cp -a "$chart_dir" "$chart_copy"' in script
    assert 'helm dependency build "$chart_copy" --skip-refresh' in script
    assert 'cmp --silent "$chart_dir/Chart.lock" "$chart_copy/Chart.lock"' in script
    assert "helm dependency update" not in script
    assert 'helm lint "$chart_copy"' in script
    assert re.search(
        r'helm package "\$chart_copy" --version "\$chart_version" --destination "\$[A-Za-z_]+"',
        script,
    )
    assert 'helm push "$package_path" "oci://${registry_root}"' in script
    assert script.count("helm push ") == 1
    assert "helm pull" in script
    assert '[[ "$digest" =~ ^sha256:[0-9a-f]{64}$ ]]' in script
    assert '[[ "$digest" != "sha256:' + "0" * 64 + '" ]]' in script
    assert 'pushed_digest="$(digest_from_output "$push_output")"' in script
    assert 'resolved_digest="$(digest_from_output "$resolve_output")"' in script
    assert '[[ "$resolved_digest" == "$pushed_digest" ]]' in script
    assert 'package_sha256="$(sha256sum "$package_path")"' in script
    assert 'package_sha256="${package_sha256%% *}"' in script
    assert '[[ "$package_sha256" =~ ^[0-9a-f]{64}$ ]]' in script
    assert '[[ "$package_sha256" != "' + "0" * 64 + '" ]]' in script
    assert 'printf \'%s=%s\\n\' "$package_hash_output" "$package_sha256" >> "$GITHUB_OUTPUT"' in script

    dependency = script.index('helm dependency build "$chart_copy" --skip-refresh')
    lock_preservation = script.index('cmp --silent "$chart_dir/Chart.lock" "$chart_copy/Chart.lock"')
    lint = script.index('helm lint "$chart_copy"')
    package = script.index('helm package "$chart_copy" --version "$chart_version"')
    push = script.index('helm push "$package_path" "oci://${registry_root}"')
    pull = script.index("helm pull")
    assert dependency < lock_preservation < lint < package < pull < push

    mutable_refs = re.compile(r"nohiki(?:-foundation)?:(?:0\.[12]\.0|latest|main|stable)(?:[\"'\s@]|$)")
    assert mutable_refs.search(script) is None

    release_archives = {
        _ROOT / "nohiki-foundation-0.1.0.tgz",
        _ROOT / "nohiki-0.2.0.tgz",
        _ROOT / "infra/k8s/helm-foundation/nohiki-foundation-0.1.0.tgz",
        _ROOT / "infra/k8s/helm/nohiki-0.2.0.tgz",
    }
    assert not [path for path in release_archives if path.exists()]
    tracked = subprocess.run(
        [
            "git",
            "ls-files",
            "--",
            *(str(path.relative_to(_ROOT)) for path in release_archives),
        ],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert not tracked.stdout.strip(), f"release archives must not be tracked: {tracked.stdout}"


def test_chart_http_repositories_are_registered_exactly_before_dependency_build() -> None:
    workflow = _load_workflow()
    job = workflow["jobs"]["publish"]
    workflow_script = "\n".join(str(step.get("run", "")) for step in _steps(job))
    expected_repositories = _http_chart_repositories()
    expected_aliases = {
        "cloudnative-pg",
        "external-secrets",
        "opentelemetry",
        "strimzi",
        "bitnami",
        "qdrant",
        "maikumori",
        "prometheus-community",
        "grafana",
    }

    additions = _repo_additions(workflow_script)
    command_count = len(re.findall(r"^\s*helm\s+repo\s+add\b", workflow_script, re.MULTILINE))
    assert command_count == len(additions), "all repo registrations must use explicit URL arguments"
    assert len(additions) == len(expected_repositories)
    assert len({alias for alias, _ in additions}) == len(additions)
    assert len({repository for _, repository in additions}) == len(additions)
    assert {alias for alias, _ in additions} == expected_aliases
    assert {repository for _, repository in additions} == expected_repositories
    assert all(repository.startswith(("http://", "https://")) for _, repository in additions)

    dependency_builds = list(re.finditer(r"\bhelm\s+dependency\s+build\b", workflow_script))
    assert dependency_builds
    first_dependency_build = dependency_builds[0].start()
    for match in _HELM_REPO_ADD.finditer(workflow_script):
        assert match.start() < first_dependency_build, "repositories must be registered before dependency builds"


def test_canonical_package_is_reproducible_and_existing_tag_is_fail_closed() -> None:
    script = _named_steps(_load_workflow()["jobs"]["publish"])["Package and publish charts"]["run"]

    assert 'build_package "$chart_dir" "$release_dir/build-$chart_name" "$chart_version" "$raw_dir"' in script
    assert (
        'build_package "$chart_dir" "$release_dir/proof-build-$chart_name" "$chart_version" "$proof_raw_dir"' in script
    )
    assert (
        "uv run --no-sync python infra/k8s/oci-proof/proof.py canonicalize "
        '--source "$raw_package" --destination "$package_path"' in script
    )
    assert (
        "uv run --no-sync python infra/k8s/oci-proof/proof.py canonicalize "
        '--source "$proof_raw_package" --destination "$proof_package"' in script
    )
    reproducible = script.index('cmp --silent "$package_path" "$proof_package"')
    package_hash = script.index('package_sha256="$(sha256sum "$package_path")"')

    preflight = script.index('resolve_output="$(helm pull "oci://${registry_root}/${chart_name}"')
    status_capture = script.index("resolve_status=$?", preflight)
    existing = script.index('if [[ "$resolve_status" == 0 ]]; then', status_capture)
    absent = script.index("else", existing)
    push = script.index('helm push "$package_path" "oci://${registry_root}"', absent)
    assert reproducible < package_hash < preflight < status_capture < existing < absent < push
    assert script.index("set +e") < preflight < script.index("set -e", status_capture)

    existing_branch = script[existing:absent]
    assert 'resolved_digest="$(digest_from_output "$resolve_output")"' in existing_branch
    assert 'cmp --silent "$package_path" "$resolved_package"' in existing_branch
    assert "Immutable Helm tag collision" in existing_branch
    assert "exit 1" in existing_branch
    assert "helm push" not in existing_branch

    unproven_absence = script.index(
        'if [[ "$resolve_output" != *"not found"* && "$resolve_output" != *"manifest unknown"* ]]; then',
        absent,
    )
    refusal = script.index("refusing to push", unproven_absence)
    refusal_exit = script.index("exit 1", refusal)
    assert absent < unproven_absence < refusal < refusal_exit < push
    post_push_pull = script.index('helm pull "oci://${registry_root}/${chart_name}"', push)
    digest_match = script.index('[[ "$resolved_digest" == "$pushed_digest" ]]', post_push_pull)
    resolved_compare = script.index('cmp --silent "$package_path" "$resolved_package"', digest_match)
    assert push < post_push_pull < digest_match < resolved_compare
    assert "|| true" not in script


def test_cosign_uses_keyless_identity_and_only_exact_versioned_digests() -> None:
    job = _load_workflow()["jobs"]["publish"]
    step = _named_steps(job)["Sign and verify chart digests"]
    package_id = _named_steps(job)["Package and publish charts"]["id"]
    assert step["env"]["FOUNDATION_VERSION"] == f"${{{{ steps.{package_id}.outputs.foundation_version }}}}"
    assert step["env"]["APPLICATION_VERSION"] == f"${{{{ steps.{package_id}.outputs.application_version }}}}"
    script = step["run"]
    expected_assignments = (
        'foundation_ref="${registry_root}/nohiki-foundation:${FOUNDATION_VERSION}"',
        'application_ref="${registry_root}/nohiki:${APPLICATION_VERSION}"',
        'foundation_digest="$FOUNDATION_DIGEST"',
        'application_digest="$APPLICATION_DIGEST"',
        'certificate_identity="https://github.com/mchar7/nohiki-monorepo/.github/workflows/'
        'release-helm-charts.yml@refs/heads/main"',
        'certificate_issuer="https://token.actions.githubusercontent.com"',
    )
    for assignment in expected_assignments:
        assert assignment in script

    evidence_dir = "$RUNNER_TEMP/helm-verification"
    assert f'evidence_dir="{evidence_dir}"' in script
    assert 'mkdir -p "$evidence_dir"' in script
    evidence_files = {
        "foundation_ref": "nohiki-foundation.json",
        "application_ref": "nohiki.json",
    }
    for ref, digest in (
        ("foundation_ref", "foundation_digest"),
        ("application_ref", "application_digest"),
    ):
        exact = f'"${{{ref}}}@${{{digest}}}"'
        assert f"cosign sign --yes {exact}" in script
        verify = re.compile(
            rf"cosign verify\s+"
            rf"--output json\s+"
            rf"--certificate-identity \"\$certificate_identity\"\s+"
            rf"--certificate-oidc-issuer \"\$certificate_issuer\"\s+"
            rf"{re.escape(exact)}\s+>\s+"
            rf'"\$evidence_dir/{re.escape(evidence_files[ref])}"'
        )
        assert verify.search(script), f"missing retained exact verification for {ref}"

    assert "COSIGN_EXPERIMENTAL" not in script
    assert "--key" not in script
    assert re.search(r"nohiki(?:-foundation)?:0\.[12]\.0(?:[\"'\s@]|$)", script) is None


def test_anonymous_exact_digest_gate_fails_closed_before_record_emission() -> None:
    job = _load_workflow()["jobs"]["publish"]
    steps = _named_steps(job)
    ordered_names = [step.get("name") for step in _steps(job)]
    gate_step = steps["Sign and verify chart digests"]
    assert gate_step["env"]["HELM_REGISTRY_CONFIG"] == "${{ runner.temp }}/helm-registry/config.json"
    script = gate_step["run"]

    logout = script.index("helm registry logout ghcr.io")
    remove_config = script.index('rm -f "$HELM_REGISTRY_CONFIG"')
    foundation_read = script.index(
        'if ! helm show chart "oci://${registry_root}/nohiki-foundation@${FOUNDATION_DIGEST}" >/dev/null; then'
    )
    application_read = script.index(
        'if ! helm show chart "oci://${registry_root}/nohiki@${APPLICATION_DIGEST}" >/dev/null; then'
    )
    failure_check = script.index('if [[ "$visibility_failure" != 0 ]]; then')
    failure_exit = script.index("exit 1", failure_check)
    assert logout < remove_config < foundation_read < application_read < failure_check < failure_exit
    verification_write = script.index('> "$evidence_dir/nohiki.json"')
    assert verification_write < logout

    assert script.index("visibility_failure=0") < foundation_read
    assert script.count("visibility_failure=1") == 2
    assert "not anonymously readable at its exact digest" in script
    assert "Set both chart packages to Public in GitHub Package settings" in script
    assert "no Flux auth secret is supported and no promotion record was emitted" in script
    assert "|| true" not in script
    assert "helm-release-record.json" not in script
    assert ordered_names.index("Sign and verify chart digests") < ordered_names.index("Write release record")
    assert ordered_names.index("Write release record") < ordered_names.index("Upload release record")


def test_release_record_step_and_artifact_receive_exact_versions_and_digests() -> None:
    job = _load_workflow()["jobs"]["publish"]
    steps = _named_steps(job)
    package_id = steps["Package and publish charts"].get("id")
    assert package_id

    record = steps["Write release record"]["run"]
    assert "scripts/ci/helm_release_record.py" in record
    assert '--repository "${GITHUB_REPOSITORY}"' in record
    assert '--source-sha "${{ github.event.workflow_run.head_sha }}"' in record
    assert '--workflow-run-id "${GITHUB_RUN_ID}"' in record
    for field in (
        "foundation_version",
        "application_version",
        "foundation_digest",
        "application_digest",
        "foundation_package_sha256",
        "application_package_sha256",
    ):
        cli_name = field.replace("_", "-")
        assert f'--{cli_name} "${{{{ steps.{package_id}.outputs.{field} }}}}"' in record
    assert f'--output "{_RELEASE_RECORD}"' in record

    upload = steps["Upload release record"]
    assert upload["with"]["name"] == "helm-release-record"
    assert upload["with"]["path"].splitlines() == [
        _RELEASE_RECORD,
        "${{ runner.temp }}/helm-verification/nohiki-foundation.json",
        "${{ runner.temp }}/helm-verification/nohiki.json",
    ]
    assert upload["with"].get("if-no-files-found") == "error"
    uploaded = upload["with"]["path"].lower()
    assert not any(token in uploaded for token in ("config.json", "docker_config", "helm_registry_config", "token"))


def test_helper_writes_complete_deterministic_provenance_atomically(
    tmp_path: Path,
) -> None:
    result, output = _run_helper(tmp_path)
    assert result.returncode == 0, result.stderr
    raw = output.read_bytes()
    assert raw.endswith(b"\n")
    assert json.loads(raw) == {
        "charts": [
            {
                "digest": _FOUNDATION_DIGEST,
                "package_sha256": _FOUNDATION_PACKAGE_SHA256,
                "name": "nohiki-foundation",
                "ref": f"ghcr.io/mchar7/nohiki-monorepo/charts/nohiki-foundation:{_foundation_version(_SOURCE_SHA)}",
                "version": _foundation_version(_SOURCE_SHA),
            },
            {
                "digest": _APPLICATION_DIGEST,
                "package_sha256": _APPLICATION_PACKAGE_SHA256,
                "name": "nohiki",
                "ref": f"ghcr.io/mchar7/nohiki-monorepo/charts/nohiki:{_application_version(_SOURCE_SHA)}",
                "version": _application_version(_SOURCE_SHA),
            },
        ],
        "source_sha": _SOURCE_SHA,
        "workflow_url": "https://github.com/mchar7/nohiki-monorepo/actions/runs/12345",
        "verification": {
            "certificate_identity": "https://github.com/mchar7/nohiki-monorepo/.github/workflows/"
            "release-helm-charts.yml@refs/heads/main",
            "certificate_oidc_issuer": "https://token.actions.githubusercontent.com",
        },
    }

    second, _ = _run_helper(tmp_path)
    assert second.returncode == 0, second.stderr
    assert output.read_bytes() == raw


def test_distinct_source_shas_cannot_resolve_to_the_same_chart_tags(
    tmp_path: Path,
) -> None:
    records = []
    for source_sha in (_SOURCE_SHA, _OTHER_SOURCE_SHA):
        output_dir = tmp_path / source_sha
        output_dir.mkdir()
        result, output = _run_helper(output_dir, source_sha=source_sha)
        assert result.returncode == 0, result.stderr
        records.append(json.loads(output.read_bytes()))

    first, second = records
    assert first["source_sha"] != second["source_sha"]
    for first_chart, second_chart in zip(first["charts"], second["charts"], strict=True):
        assert first_chart["version"] != second_chart["version"]
        assert first_chart["ref"] != second_chart["ref"]
        assert first_chart["ref"].endswith(f":{first_chart['version']}")
        assert second_chart["ref"].endswith(f":{second_chart['version']}")


def test_helper_rejects_valid_wrong_repository_without_replacing_output(
    tmp_path: Path,
) -> None:
    output = tmp_path / _RELEASE_RECORD
    sentinel = b"existing provenance\n"
    output.write_bytes(sentinel)

    result, actual_output = _run_helper(tmp_path, repository="mchar7/different-repository")

    assert result.returncode != 0
    assert actual_output.read_bytes() == sentinel


@pytest.mark.parametrize(
    "mutate",
    [
        lambda values: values.update(foundation_digest="sha256:" + "0" * 64),
        lambda values: values.update(application_digest="sha512:" + "2" * 64),
        lambda values: values.update(application_digest="sha256:" + "A" * 64),
        lambda values: values.update(application_digest=values["foundation_digest"]),
        lambda values: values.update(foundation_package_sha256="0" * 64),
        lambda values: values.update(foundation_package_sha256="3" * 63),
        lambda values: values.update(application_package_sha256="A" * 64),
        lambda values: values.update(application_package_sha256=values["foundation_package_sha256"]),
        lambda values: values.update(foundation_version="0.1.0"),
        lambda values: values.update(application_version=f"0.2.0-{'b' * 12}"),
        lambda values: values.update(source_sha="A" * 40),
    ],
    ids=[
        "zero-digest",
        "wrong-digest-algorithm",
        "uppercase-digest",
        "duplicate-digest",
        "zero-package-hash",
        "malformed-package-hash",
        "uppercase-package-hash",
        "duplicate-package-hash",
        "fixed-version",
        "version-from-different-source",
        "uppercase-source-sha",
    ],
)
def test_helper_rejects_invalid_identity_without_replacing_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutate: Callable[[dict[str, str]], None],
) -> None:
    output = tmp_path / _RELEASE_RECORD
    sentinel = b"existing provenance\n"
    output.write_bytes(sentinel)
    values = {
        "source_sha": _SOURCE_SHA,
        "foundation_version": _foundation_version(_SOURCE_SHA),
        "application_version": _application_version(_SOURCE_SHA),
        "foundation_digest": _FOUNDATION_DIGEST,
        "application_digest": _APPLICATION_DIGEST,
        "foundation_package_sha256": _FOUNDATION_PACKAGE_SHA256,
        "application_package_sha256": _APPLICATION_PACKAGE_SHA256,
    }
    mutate(values)

    actual_output = _run_invalid_helper_in_process(tmp_path, monkeypatch, **values)
    assert actual_output.read_bytes() == sentinel

    fresh_dir = tmp_path / "fresh"
    fresh_dir.mkdir()
    fresh_output = _run_invalid_helper_in_process(fresh_dir, monkeypatch, **values)
    assert not fresh_output.exists()
