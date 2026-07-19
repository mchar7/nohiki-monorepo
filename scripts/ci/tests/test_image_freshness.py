import subprocess
from pathlib import Path

import pytest
import typer
from ci_checks.checks import freshness

_DIGEST = "a" * 64
_OTHER = "b" * 64


def _proc(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=["skopeo"], returncode=returncode, stdout=stdout, stderr=stderr)


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
