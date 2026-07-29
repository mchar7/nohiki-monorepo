from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator
from functools import cache
from pathlib import Path

from _documents import Workflow, WorkflowStep, load_workflow

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_WORKFLOWS = _REPOSITORY_ROOT / ".github" / "workflows"
_DOWNLOAD_ARTIFACT = re.compile(
    r"^\s*uses:\s*actions/download-artifact@(?P<ref>\S+)(?:\s+#\s*(?P<version>\S+))?\s*$",
    re.MULTILINE,
)
_ACTION = re.compile(
    r"^\s*uses:\s*(?P<action>[^@\s]+)@(?P<ref>[^\s#]+)(?:\s+#\s*(?P<version>\S+))?\s*$",
    re.MULTILINE,
)
_DOWNLOAD_ARTIFACT_MAJOR = "v8"
_OPENTOFU_VERSION = "1.12.3"
_INFRASTRUCTURE_SETUP_COUNTS = {
    "cd_deploy-to-aks_nohiki.yml": 1,
    "cd_destroy-aks_nohiki.yml": 1,
}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DOWNLOAD = re.compile(r"\b(?:curl|wget)\b.*https://")

_GATEWAY_API_CRDS = _REPOSITORY_ROOT / "infra/k8s/gitops/gateway-api-crds/gateway-api-crds.yaml"
_GATEWAY_API_VERSION = "v1.6.0"
_GATEWAY_API_EXPECTED_HEX = "a557172e8348f758479e9ee4000bbbb4b4aa48302a6b73461823ea5349bad56d"
_VENDOR_MARKER = b"# ---8<--- BEGIN VENDORED CONTENT ---8<---\n"


@cache
def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _run_scripts(workflow: Workflow) -> Iterator[str]:
    for job in workflow["jobs"].values():
        for step in job.get("steps", []):
            if script := step.get("run"):
                yield script


def _action_steps(workflow: Workflow, action: str) -> Iterator[WorkflowStep]:
    for job in workflow["jobs"].values():
        for step in job.get("steps", []):
            if (uses := step.get("uses")) is not None and uses.startswith(f"{action}@"):
                yield step


def test_direct_workflow_downloads_are_verified_before_use() -> None:
    downloads = [
        (workflow_path.name, line.strip())
        for workflow_path in sorted(_WORKFLOWS.glob("*.yml"))
        for script in _run_scripts(load_workflow(workflow_path))
        for line in script.splitlines()
        if _DOWNLOAD.search(line)
    ]
    assert not downloads, f"workflow toolchains come from the flake; found direct downloads: {downloads}"


def test_vendored_gateway_api_crds_match_pinned_release_checksum() -> None:
    raw = _GATEWAY_API_CRDS.read_bytes()
    header, marker, vendored = raw.partition(_VENDOR_MARKER)
    assert marker, "vendored provenance marker missing"

    provenance = header.decode("utf-8")
    assert _GATEWAY_API_VERSION in provenance
    assert _GATEWAY_API_EXPECTED_HEX in provenance
    assert f"releases/download/{_GATEWAY_API_VERSION}/standard-install.yaml" in provenance

    # Bytes after the marker are the upstream asset verbatim, so their digest must match the pin.
    assert vendored, "no vendored CRD content after provenance marker"
    assert hashlib.sha256(vendored).hexdigest() == _GATEWAY_API_EXPECTED_HEX


def test_every_download_artifact_action_supports_cross_run_retrieval() -> None:
    occurrences = [
        (workflow_path, match["version"])
        for workflow_path in sorted(_WORKFLOWS.glob("*.yml"))
        for match in _DOWNLOAD_ARTIFACT.finditer(_read_text(workflow_path))
    ]

    assert occurrences, "no download-artifact actions discovered"
    # Cross-run retrieval requires the run-id and github-token inputs supported by v8.
    # Revalidate those inputs before changing the required major.
    assert all(
        version is not None and version.partition(".")[0] == _DOWNLOAD_ARTIFACT_MAJOR for _, version in occurrences
    ), occurrences


def test_buf_comes_from_the_flake_not_workflow_actions() -> None:
    occurrences = [
        (workflow_path, step.get("with", {}).get("version"))
        for workflow_path in sorted(_WORKFLOWS.glob("*.yml"))
        for step in _action_steps(load_workflow(workflow_path), "bufbuild/buf-action")
    ]

    assert not occurrences, occurrences


def test_infrastructure_workflows_use_the_declared_opentofu_toolchain() -> None:
    occurrences: list[tuple[Path, str | None, object]] = []
    counts: dict[str, int] = {}
    setup_terraform: list[Path] = []
    tofu_invocations: dict[str, bool] = {}

    for workflow_path in sorted(_WORKFLOWS.glob("*.yml")):
        workflow = load_workflow(workflow_path)
        setup_steps = list(_action_steps(workflow, "opentofu/setup-opentofu"))
        if setup_steps:
            counts[workflow_path.name] = len(setup_steps)
            tofu_invocations[workflow_path.name] = any(
                re.search(r"\btofu\b", script) is not None for script in _run_scripts(workflow)
            )
        if list(_action_steps(workflow, "hashicorp/setup-terraform")):
            setup_terraform.append(workflow_path)
        for step in setup_steps:
            with_inputs = step.get("with", {})
            tofu_version = with_inputs.get("tofu_version")
            assert tofu_version is None or isinstance(tofu_version, str)
            occurrences.append(
                (
                    workflow_path,
                    tofu_version,
                    with_inputs.get("tofu_wrapper", True),
                )
            )

    assert not setup_terraform, f"infrastructure workflows must use only setup-opentofu: {setup_terraform}"
    assert counts == _INFRASTRUCTURE_SETUP_COUNTS
    assert all(tofu_invocations.values()), tofu_invocations
    assert all((version, wrapper) == (_OPENTOFU_VERSION, True) for _, version, wrapper in occurrences), occurrences


def test_third_party_actions_are_immutable_and_duplicate_pins_stay_aligned() -> None:
    occurrences: dict[str, list[tuple[Path, str, str | None]]] = {}
    for workflow_path in sorted(_WORKFLOWS.glob("*.yml")):
        for match in _ACTION.finditer(_read_text(workflow_path)):
            action = match["action"]
            if action.startswith("./"):
                continue
            repository = "/".join(action.split("/")[:2])
            occurrences.setdefault(repository, []).append((workflow_path, match["ref"], match["version"]))

    assert occurrences, "no third-party workflow actions discovered"
    invalid_refs = [
        (path, repository, ref)
        for repository, uses in occurrences.items()
        for path, ref, _ in uses
        if not re.fullmatch(r"[0-9a-f]{40}", ref)
    ]
    assert not invalid_refs, f"third-party actions must use immutable commit SHAs: {invalid_refs}"

    inconsistent = {
        repository: sorted({(ref, version) for _, ref, version in uses})
        for repository, uses in occurrences.items()
        if len(uses) > 1 and len({(ref, version) for _, ref, version in uses}) > 1
    }
    assert not inconsistent, f"duplicate action pins disagree: {inconsistent}"
