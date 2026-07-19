from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator
from functools import cache
from pathlib import Path
from typing import Any

import yaml

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
_DOWNLOAD_ARTIFACT_REF = "3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c"
_DOWNLOAD_ARTIFACT_VERSION = "v8.0.1"
_OPENTOFU_VERSION = "1.12.3"
_SETUP_OPENTOFU_REF = "a1320f892987e89d278cc92dc5adc984fb93aca4"
_SETUP_OPENTOFU_RELEASE = "v2.0.2"
_INFRASTRUCTURE_SETUP_COUNTS = {
    "cd_deploy-to-aks_nohiki.yml": 1,
    "cd_destroy-aks_nohiki.yml": 1,
}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DOWNLOAD = re.compile(r"\b(?:curl|wget)\b.*https://")

_FOUNDATION_CHART = _REPOSITORY_ROOT / "infra" / "k8s" / "helm-foundation"
_GATEWAY_API_CRDS = _REPOSITORY_ROOT / "infra/k8s/gitops/gateway-api-crds/gateway-api-crds.yaml"
_GATEWAY_API_VERSION = "v1.6.0"
_GATEWAY_API_EXPECTED_HEX = "a557172e8348f758479e9ee4000bbbb4b4aa48302a6b73461823ea5349bad56d"
_KGATEWAY_VERSION = "v2.3.6"
_CNPG_VERSION = "0.29.0"
_VENDOR_MARKER = b"# ---8<--- BEGIN VENDORED CONTENT ---8<---\n"


@cache
def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@cache
def _load(path: Path) -> dict[str, Any]:
    return yaml.safe_load(_read_text(path))


def _run_scripts(value: object) -> Iterator[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "run" and isinstance(child, str):
                yield child
            else:
                yield from _run_scripts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _run_scripts(child)


def _action_steps(value: object, action: str) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        if isinstance(value.get("uses"), str) and value["uses"].startswith(f"{action}@"):
            yield value
        for child in value.values():
            yield from _action_steps(child, action)
    elif isinstance(value, list):
        for child in value:
            yield from _action_steps(child, action)


def test_direct_workflow_downloads_are_verified_before_use() -> None:
    downloads = [
        (workflow_path.name, line.strip())
        for workflow_path in sorted(_WORKFLOWS.glob("*.yml"))
        for script in _run_scripts(_load(workflow_path))
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


def test_foundation_chart_pins_kgateway_and_cnpg() -> None:
    chart = _load(_FOUNDATION_CHART / "Chart.yaml")
    versions = {dep["name"]: dep["version"] for dep in chart["dependencies"]}
    assert versions["kgateway"] == _KGATEWAY_VERSION
    assert versions["kgateway-crds"] == _KGATEWAY_VERSION
    assert versions["cloudnative-pg"] == _CNPG_VERSION


def test_every_download_artifact_action_uses_the_audited_release() -> None:
    occurrences = [
        (workflow_path, match["ref"], match["version"])
        for workflow_path in sorted(_WORKFLOWS.glob("*.yml"))
        for match in _DOWNLOAD_ARTIFACT.finditer(_read_text(workflow_path))
    ]

    assert occurrences, "no download-artifact actions discovered"
    assert all(
        (ref, version) == (_DOWNLOAD_ARTIFACT_REF, _DOWNLOAD_ARTIFACT_VERSION) for _, ref, version in occurrences
    ), occurrences


def test_buf_comes_from_the_flake_not_workflow_actions() -> None:
    occurrences = [
        (workflow_path, step.get("with", {}).get("version"))
        for workflow_path in sorted(_WORKFLOWS.glob("*.yml"))
        for step in _action_steps(_load(workflow_path), "bufbuild/buf-action")
    ]

    assert not occurrences, occurrences


def test_infrastructure_workflows_use_only_the_audited_opentofu_setup() -> None:
    occurrences: list[tuple[Path, str, str | None, object]] = []
    setup_pins: list[tuple[Path, str, str | None]] = []
    counts: dict[str, int] = {}
    setup_terraform: list[Path] = []

    for workflow_path in sorted(_WORKFLOWS.glob("*.yml")):
        workflow = _load(workflow_path)
        setup_steps = list(_action_steps(workflow, "opentofu/setup-opentofu"))
        if setup_steps:
            counts[workflow_path.name] = len(setup_steps)
        if list(_action_steps(workflow, "hashicorp/setup-terraform")):
            setup_terraform.append(workflow_path)
        occurrences.extend(
            (
                workflow_path,
                step["uses"].partition("@")[2],
                step.get("with", {}).get("tofu_version"),
                step.get("with", {}).get("tofu_wrapper", True),
            )
            for step in setup_steps
        )
        setup_pins.extend(
            (workflow_path, match["ref"], match["version"])
            for match in _ACTION.finditer(_read_text(workflow_path))
            if match["action"] == "opentofu/setup-opentofu"
        )

    assert not setup_terraform, f"infrastructure workflows must use only setup-opentofu: {setup_terraform}"
    assert counts == _INFRASTRUCTURE_SETUP_COUNTS
    assert all(
        (ref, version, wrapper) == (_SETUP_OPENTOFU_REF, _OPENTOFU_VERSION, True)
        for _, ref, version, wrapper in occurrences
    ), occurrences
    assert all((ref, release) == (_SETUP_OPENTOFU_REF, _SETUP_OPENTOFU_RELEASE) for _, ref, release in setup_pins), (
        setup_pins
    )


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
