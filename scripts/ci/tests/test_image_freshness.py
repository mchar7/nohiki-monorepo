import contextlib
import re
import subprocess
import urllib.error
import urllib.request
from email.message import Message
from http import HTTPStatus
from pathlib import Path
from typing import Never, Self

import pytest
import typer
from _documents import load_workflow
from ci_checks.checks import freshness

_DIGEST = "a" * 64
_OTHER = "b" * 64
_CHECKSUM = "c" * 64
_URL = "https://example.invalid/release/v1.34.3/bin/linux/amd64/kubectl"
_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_DIGEST_FRESHNESS = _REPOSITORY_ROOT / ".github" / "workflows" / "digest-freshness.yml"
_PINNED_NIX_INSTALLER = re.compile(r"^cachix/install-nix-action@[0-9a-f]{40}$")


def _proc(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=["skopeo"], returncode=returncode, stdout=stdout, stderr=stderr)


class _FakeResponse:
    def __init__(self, status: int) -> None:
        self.status = status

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None


def _skopeo_must_not_run(args: list[str]) -> Never:
    msg = f"skopeo must not be invoked for a URL pin: {args}"
    raise AssertionError(msg)


def test_collect_pins_matches_platform_case_and_dedupes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(freshness, "REPO_ROOT", tmp_path)
    (tmp_path / "Dockerfile").write_text(
        f"FROM --platform=linux/amd64 docker.io/library/python:3.14-slim@sha256:{_DIGEST}\n"
        f"from quay.io/x/y:1.0@sha256:{_DIGEST}\n"
        "FROM scratch\n"
        "FROM alpine:3.20\n",
        encoding="utf-8",
    )
    (tmp_path / "other.Dockerfile").write_text(
        f"FROM quay.io/x/y:1.0@sha256:{_DIGEST}\n",
        encoding="utf-8",
    )

    pins = freshness.collect_pins(["Dockerfile", "other.Dockerfile"])

    assert pins == {
        f"docker.io/library/python:3.14-slim@sha256:{_DIGEST}": ["Dockerfile"],
        f"quay.io/x/y:1.0@sha256:{_DIGEST}": ["Dockerfile", "other.Dockerfile"],
    }


def test_collect_pins_covers_copy_from_and_checksum_but_not_build_stages(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(freshness, "REPO_ROOT", tmp_path)
    (tmp_path / "Dockerfile").write_text(
        f"FROM public.ecr.aws/docker/library/python:3.14-slim@sha256:{_DIGEST} AS builder\n"
        f"COPY --from=ghcr.io/astral-sh/uv:0.11.28@sha256:{_OTHER} /uv /usr/local/bin/uv\n"
        f"COPY --chown=app:app --from=quay.io/x/y:1.0@sha256:{_OTHER} /y /usr/local/bin/y\n"
        f"ADD --chmod=0555 --checksum=sha256:{_CHECKSUM} \\\n"
        f"    {_URL} /usr/local/bin/kubectl\n"
        "COPY --from=builder /opt/venv /opt/venv\n"
        "COPY --from=builder --chown=app:app /workspace /workspace\n"
        "COPY --from=kubectl /bin/kubectl /usr/local/bin/kubectl\n"
        "ADD https://example.invalid/unpinned /tmp/unpinned\n",
        encoding="utf-8",
    )

    pins = freshness.collect_pins(["Dockerfile"])

    assert pins == {
        f"public.ecr.aws/docker/library/python:3.14-slim@sha256:{_DIGEST}": ["Dockerfile"],
        f"ghcr.io/astral-sh/uv:0.11.28@sha256:{_OTHER}": ["Dockerfile"],
        f"quay.io/x/y:1.0@sha256:{_OTHER}": ["Dockerfile"],
        _URL: ["Dockerfile"],
    }


def test_probe_pin_reports_alive_for_reachable_checksum_url(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[str, str, float]] = []

    def fake_urlopen(request: urllib.request.Request, *, timeout: float) -> _FakeResponse:
        seen.append((request.get_method(), request.full_url, timeout))
        return _FakeResponse(200)

    monkeypatch.setattr(freshness, "_skopeo", _skopeo_must_not_run)
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    probe = freshness.probe_pin(_URL)

    assert probe.alive
    assert probe.tag_digest == ""
    assert probe.detail == ""
    assert seen == [("HEAD", _URL, 30)]


def test_probe_pin_reports_dead_when_checksum_url_is_gone(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request: urllib.request.Request, *, timeout: float) -> Never:
        assert timeout > 0
        # HTTPError is an addinfourl, so it owns a response body that only close() releases;
        # probe_pin reads the status and drops the exception, leaving nothing else to close it.
        error = urllib.error.HTTPError(request.full_url, HTTPStatus.NOT_FOUND, "Not Found", Message(), None)
        with contextlib.closing(error):
            raise error

    monkeypatch.setattr(freshness, "_skopeo", _skopeo_must_not_run)
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    probe = freshness.probe_pin(_URL)

    assert not probe.alive
    assert "404" in probe.detail


def test_probe_pin_reports_alive_and_tag_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_skopeo(args: list[str]) -> subprocess.CompletedProcess[str]:
        if "--raw" in " ".join(args):
            return _proc(0, stdout="{}")
        return _proc(0, stdout=f"sha256:{_OTHER}\n")

    monkeypatch.setattr(freshness, "_skopeo", fake_skopeo)
    probe = freshness.probe_pin(f"quay.io/x/y:1.0@sha256:{_DIGEST}")

    assert probe.alive
    assert probe.tag_digest == f"sha256:{_OTHER}"
    assert probe.detail == ""


def test_probe_pin_reports_dead_with_detail(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_skopeo(args: list[str]) -> subprocess.CompletedProcess[str]:
        if "--raw" in " ".join(args):
            return _proc(1, stderr="fatal: manifest unknown\n")
        return _proc(1)

    monkeypatch.setattr(freshness, "_skopeo", fake_skopeo)
    probe = freshness.probe_pin(f"quay.io/x/y:1.0@sha256:{_DIGEST}")

    assert not probe.alive
    assert "manifest unknown" in probe.detail
    assert probe.tag_digest == ""


def test_probe_pin_skips_tag_lookup_without_tag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake_skopeo(args: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return _proc(0, stdout="{}")

    monkeypatch.setattr(freshness, "_skopeo", fake_skopeo)
    probe = freshness.probe_pin(f"quay.io/x/y@sha256:{_DIGEST}")

    assert probe.alive
    assert len(calls) == 1


def test_freshness_cmd_fails_when_collector_finds_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(freshness, "_tracked_dockerfiles", list)

    with pytest.raises(typer.Exit) as excinfo:
        freshness.freshness_cmd()
    assert excinfo.value.exit_code == 1


def test_freshness_cmd_fails_on_dead_pin(monkeypatch: pytest.MonkeyPatch) -> None:
    ref = f"quay.io/x/y:1.0@sha256:{_DIGEST}"
    monkeypatch.setattr(freshness, "_tracked_dockerfiles", lambda: ["Dockerfile"])
    monkeypatch.setattr(freshness, "collect_pins", lambda _files: {ref: ["Dockerfile"]})
    monkeypatch.setattr(
        freshness,
        "probe_pin",
        lambda ref: freshness.PinProbe(ref=ref, alive=False, tag_digest="", detail="manifest unknown"),
    )

    with pytest.raises(typer.Exit) as excinfo:
        freshness.freshness_cmd()
    assert excinfo.value.exit_code == 1


def test_freshness_cmd_passes_when_all_alive(monkeypatch: pytest.MonkeyPatch) -> None:
    ref = f"quay.io/x/y:1.0@sha256:{_DIGEST}"
    monkeypatch.setattr(freshness, "_tracked_dockerfiles", lambda: ["Dockerfile"])
    monkeypatch.setattr(freshness, "collect_pins", lambda _files: {ref: ["Dockerfile"]})
    monkeypatch.setattr(
        freshness,
        "probe_pin",
        lambda ref: freshness.PinProbe(ref=ref, alive=True, tag_digest=f"sha256:{_DIGEST}", detail=""),
    )

    freshness.freshness_cmd()


def test_probe_pin_handles_registry_port_without_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    refs: list[str] = []

    def fake_skopeo(args: list[str]) -> subprocess.CompletedProcess[str]:
        refs.append(args[-1])
        return _proc(0, stdout="{}")

    monkeypatch.setattr(freshness, "_skopeo", fake_skopeo)
    probe = freshness.probe_pin(f"registry.example:5000/team/image@sha256:{_DIGEST}")

    assert probe.alive
    assert refs == [f"docker://registry.example:5000/team/image@sha256:{_DIGEST}"]


def test_probe_pin_handles_registry_port_with_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    refs: list[str] = []

    def fake_skopeo(args: list[str]) -> subprocess.CompletedProcess[str]:
        refs.append(args[-1])
        return _proc(0, stdout="{}")

    monkeypatch.setattr(freshness, "_skopeo", fake_skopeo)
    freshness.probe_pin(f"registry.example:5000/team/image:1.0@sha256:{_DIGEST}")

    assert refs[0] == f"docker://registry.example:5000/team/image@sha256:{_DIGEST}"
    assert refs[1] == "docker://registry.example:5000/team/image:1.0"


def test_digest_freshness_uses_pinned_nix_installer_and_all_extras_closure() -> None:
    workflow = load_workflow(_DIGEST_FRESHNESS)
    steps = workflow["jobs"]["probe"]["steps"]

    install_nix = next(step for step in steps if step.get("name") == "Install Nix")
    assert _PINNED_NIX_INSTALLER.fullmatch(str(install_nix.get("uses", "")))

    install_workspace = next(step for step in steps if step.get("name") == "Install workspace (all packages + extras)")
    assert "--all-packages --all-extras --no-extra cuda --locked" in str(install_workspace["run"])
