from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_OBSERVER = _ROOT / "infra/k8s/local/observer.py"
_SHA = "1" * 40


def _load_observer() -> ModuleType:
    name = f"kind_observer_test_{id(object())}"
    spec = importlib.util.spec_from_file_location(name, _OBSERVER)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _measurement(kubeconfig: Path, attempt: int = 1) -> dict[str, Any]:
    binding: dict[str, Any]
    if kubeconfig.exists():
        metadata = kubeconfig.stat()
        binding = {
            "device": metadata.st_dev,
            "inode": metadata.st_ino,
            "mode": "0600",
            "owner": metadata.st_uid,
            "path": str(kubeconfig),
        }
    else:
        binding = {"device": 1, "inode": 2, "mode": "0600", "owner": os.getuid(), "path": str(kubeconfig)}
    return {
        "apiVersion": "nohiki.io/v1alpha1",
        "attempt": attempt,
        "cluster": {"context": "kind-nohiki", "name": "nohiki", "uid": "cluster-uid"},
        "kubeconfig": binding,
        "kind": "KindctlMeasurements",
        "lockSha256": "a" * 64,
        "network": {"dns": True, "nodeApi": True, "podIp": True, "serviceVersion": True},
        "nodes": [],
        "schemaVersion": 1,
        "secrets": [],
        "source": {"branch": None, "remoteSha": None, "reviewedSha": None},
        "storage": {"storageClass": "standard"},
    }


def _write_inputs(tmp_path: Path, measurement: dict[str, Any]) -> tuple[Path, Path]:
    measurement_path = tmp_path / "runner-measurements.json"
    measurement_bytes = _canonical(measurement)
    measurement_path.write_bytes(measurement_bytes)
    sidecar = {
        "attempt": measurement["attempt"],
        "clusterUid": measurement["cluster"]["uid"],
        "lockSha256": measurement["lockSha256"],
        "sha256": __import__("hashlib").sha256(measurement_bytes).hexdigest(),
    }
    sidecar_path = tmp_path / "runner-measurements.sha256.json"
    sidecar_path.write_bytes(_canonical(sidecar))
    return measurement_path, sidecar_path


def _arguments(observer: ModuleType, tmp_path: Path, measurement: dict[str, Any]) -> argparse.Namespace:
    measurement_path, sidecar_path = _write_inputs(tmp_path, measurement)
    return observer.parse_arguments(
        [
            "--attempt",
            str(measurement["attempt"]),
            "--phase",
            "zero-state",
            "--output",
            str(tmp_path / "observation.json"),
            "--branch",
            "runtime-control/local/test",
            "--reviewed-sha",
            _SHA,
            "--remote-sha",
            _SHA,
            "--runner-measurements",
            str(measurement_path),
            "--runner-measurements-sidecar",
            str(sidecar_path),
        ]
    )


def _completed(argv: Sequence[str], stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(list(argv), returncode, stdout, "")


def test_arguments_reject_invalid_attempt_source_and_existing_output(tmp_path: Path) -> None:
    observer = _load_observer()
    measurement = _measurement(tmp_path / "absent-kubeconfig")
    arguments = _arguments(observer, tmp_path, measurement)
    assert arguments.attempt == 1
    argv = [
        "--attempt",
        "0",
        "--phase",
        "zero-state",
        "--output",
        str(tmp_path / "other.json"),
        "--branch",
        "main",
        "--reviewed-sha",
        _SHA.upper(),
        "--remote-sha",
        _SHA,
        "--runner-measurements",
        str(arguments.runner_measurements),
        "--runner-measurements-sidecar",
        str(arguments.runner_measurements_sidecar),
    ]
    with pytest.raises(SystemExit):
        observer.parse_arguments(argv)
    arguments.output.write_text("occupied", encoding="utf-8")
    with pytest.raises(SystemExit):
        observer.parse_arguments(
            [
                "--attempt",
                "1",
                "--phase",
                "zero-state",
                "--output",
                str(arguments.output),
                "--branch",
                "runtime-control/local/test",
                "--reviewed-sha",
                _SHA,
                "--remote-sha",
                _SHA,
                "--runner-measurements",
                str(arguments.runner_measurements),
                "--runner-measurements-sidecar",
                str(arguments.runner_measurements_sidecar),
            ]
        )


def test_zero_state_observation_has_stable_schema_and_bound_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observer = _load_observer()
    measurement = _measurement(tmp_path / "deleted-kubeconfig")
    arguments = _arguments(observer, tmp_path, measurement)
    calls: list[tuple[str, ...]] = []

    def fake_readonly(argv: Sequence[str], _timeout: int = 15) -> subprocess.CompletedProcess[str]:
        command = tuple(argv)
        calls.append(command)
        if command == ("kind", "get", "clusters"):
            return _completed(argv)
        if command[:2] == ("podman", "ps") or command[:3] == ("podman", "volume", "ls"):
            return _completed(argv, "[]")
        if command[:3] == ("podman", "network", "inspect"):
            return _completed(argv, returncode=1)
        message = f"unexpected command: {command}"
        raise AssertionError(message)

    monkeypatch.setattr(observer, "run_readonly", fake_readonly)
    document, sidecar_path = observer.observe(arguments)
    assert document["kind"] == "KindRuntimeObservation"
    assert document["schemaVersion"] == 1
    assert document["attempt"] == 1
    assert document["phase"] == "zero-state"
    assert document["cluster"] == {
        "context": "kind-nohiki",
        "createdAt": None,
        "kubeSystemUid": None,
        "name": "nohiki",
        "nodes": [],
        "present": False,
    }
    assert all(not value for value in document["cleanup"].values())
    assert set(document) == {
        "apiVersion",
        "artifacts",
        "attempt",
        "cleanup",
        "cluster",
        "command",
        "errors",
        "flux",
        "git",
        "kind",
        "observedAt",
        "phase",
        "registry",
        "schemaVersion",
        "secrets",
        "storage",
        "tests",
        "workloads",
    }
    assert arguments.output.read_bytes() == _canonical(document)
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    assert sidecar["attempt"] == 1
    assert sidecar["clusterUid"] is None
    assert sidecar["lockSha256"] == "a" * 64
    assert sidecar["sha256"] == __import__("hashlib").sha256(arguments.output.read_bytes()).hexdigest()
    assert {call[0] for call in calls} == {"kind", "podman"}


def test_measurements_and_sidecar_are_canonical_closed_and_attempt_bound(tmp_path: Path) -> None:
    observer = _load_observer()
    measurement = _measurement(tmp_path / "kubeconfig", attempt=2)
    measurement_path, sidecar_path = _write_inputs(tmp_path, measurement)
    document, data = observer.read_canonical_json(measurement_path)
    observer.validate_measurements(document, 2)
    sidecar, _ = observer.read_canonical_json(sidecar_path)
    observer.validate_sidecar(sidecar, document, data)
    with pytest.raises(observer.ObservationError, match="attempt"):
        observer.validate_measurements(document, 1)
    sidecar["sha256"] = "0" * 64
    with pytest.raises(observer.ObservationError, match="does not bind"):
        observer.validate_sidecar(sidecar, document, data)
    measurement_path.write_text(json.dumps(measurement, indent=2), encoding="utf-8")
    with pytest.raises(observer.ObservationError, match="canonical"):
        observer.read_canonical_json(measurement_path)


def test_secret_material_is_rejected_before_emission() -> None:
    observer = _load_observer()
    for value in (
        {"data": {"identity": "base64"}},
        {"nested": {"password": "value"}},
        {"privateKey": "value"},
        {"ageKey": "value"},
    ):
        with pytest.raises(observer.ObservationError, match="secret-bearing"):
            observer.reject_secret_material(value)


def test_node_container_identity_mismatch_contradicts_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observer = _load_observer()
    measured = [
        {
            "arpIgnoreAll": "0",
            "arpIgnoreDefault": "0",
            "containerId": "expected-id",
            "hostsSha256": "",
            "name": "nohiki-control-plane",
            "startTime": "expected-start",
        }
    ]
    monkeypatch.setattr(
        observer,
        "run_readonly",
        lambda argv, _timeout=15: (
            _completed(argv, "nohiki-control-plane\n")
            if tuple(argv)[:3] == ("kind", "get", "nodes")
            else _completed(argv, "[]")
        ),
    )
    monkeypatch.setattr(
        observer,
        "require_json",
        lambda *_args, **_kwargs: [{"Id": "different-id", "State": {"StartedAt": "expected-start"}}],
    )
    with pytest.raises(observer.ObservationError, match="node identity changed"):
        observer.podman_inventory(measured, kind_present=True)


def test_observer_has_no_lifecycle_runner_dependency() -> None:
    source = _OBSERVER.read_text(encoding="utf-8")
    assert "infra/k8s/local/kindctl" not in source
    assert "import kindctl" not in source
    assert "from kindctl" not in source
    assert "shell=True" not in source
