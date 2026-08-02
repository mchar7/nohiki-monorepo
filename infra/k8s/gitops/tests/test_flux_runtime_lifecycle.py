from __future__ import annotations

import contextlib
import hashlib
import importlib.machinery
import importlib.util
import json
import subprocess
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest

_ROOT = Path(__file__).resolve().parents[4]
_RUNNER = _ROOT / "infra/k8s/local/kindctl"
_REVISION = "1" * 40
_LOCK_SHA = "2" * 64
_OPERATOR_DIGEST = "sha256:" + "3" * 64


def _load_runner() -> ModuleType:
    name = f"flux_runtime_kindctl_{id(object())}"
    loader = importlib.machinery.SourceFileLoader(name, str(_RUNNER))
    spec = importlib.util.spec_from_loader(name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def _result(
    argv: tuple[str, ...],
    *,
    stdout: str = "",
    returncode: int = 0,
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(argv, returncode, stdout, "")


def test_runtime_commands_reach_their_effectful_entrypoints(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner()
    calls: list[tuple[str, object]] = []

    @contextlib.contextmanager
    def mutation_lock(command: str, _attempt: Path) -> Iterator[None]:
        calls.append(("lock", command))
        yield

    @contextlib.contextmanager
    def command_record(command: str, _attempt: Path) -> Iterator[dict[str, object]]:
        record: dict[str, object] = {}
        yield record
        calls.append(("record", (command, record)))

    monkeypatch.setattr(runner, "validate_runner_path", lambda: None)
    monkeypatch.setattr(runner, "validate_attempt_dir", lambda _raw: tmp_path)
    monkeypatch.setattr(runner, "mutation_lock", mutation_lock)
    monkeypatch.setattr(runner, "command_record", command_record)
    monkeypatch.setattr(
        runner,
        "qualify_flux_runtime",
        lambda *_args: calls.append(("runtime", _args[-1])) or {},
    )
    monkeypatch.setattr(
        runner,
        "finalize_flux_runtime",
        lambda *_args: calls.append(("finalize", _args[-1])) or {},
    )
    monkeypatch.setattr(
        runner,
        "qualify_offline_policy",
        lambda *_args: calls.append(("offline", None)) or {},
    )
    attempt_args = ("--attempt-dir", str(tmp_path))
    assert runner.main((*attempt_args, "flux-runtime", "--direction", "operator-to-core")) == 0
    publication = tmp_path / "publication.json"
    assert runner.main((*attempt_args, "flux-finalize", "--publication-record", str(publication))) == 0
    assert runner.main((*attempt_args, "flux-offline")) == 0
    assert ("runtime", "operator-to-core") in calls
    assert ("finalize", publication) in calls
    assert ("offline", None) in calls


def test_runtime_binding_rejects_a_different_live_cluster(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner()
    attempt = tmp_path / "attempt-4"
    attempt.mkdir()
    measurements = {
        "attempt": 4,
        "cluster": {"context": "kind-nohiki", "uid": "recorded-cluster"},
    }
    (attempt / "runner-measurements.json").write_bytes(runner.canonical_bytes(measurements))
    monkeypatch.setattr(runner, "validate_kubeconfig_binding", lambda *_: None)
    monkeypatch.setattr(
        runner,
        "run_command",
        lambda argv, **_: _result(argv, stdout="kind-nohiki\n"),
    )
    monkeypatch.setattr(
        runner,
        "command_json",
        lambda *_args, **_kwargs: {"metadata": {"uid": "different-cluster"}},
    )
    with pytest.raises(runner.KindctlError, match="just-created cluster"):
        runner.runtime_binding(attempt, tmp_path / "kubeconfig")


def test_attempt_configmap_is_produced_and_observed_before_runtime_apply(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner()
    calls: list[tuple[tuple[str, ...], str | None]] = []
    produced = {
        "apiVersion": "v1",
        "data": {
            "NOHIKI_ARTIFACT_LOCK_SHA256": _LOCK_SHA,
            "NOHIKI_ATTEMPT_SUFFIX": "a00000004-1234abcd",
            "RUNTIME_CONTROL_BRANCH": "runtime-control/local/test",
            "NOHIKI_SOURCE_HEAD_SHA": _REVISION,
            "NOHIKI_SOURCE_REMOTE_SHA": _REVISION,
            "NOHIKI_SOURCE_REVIEWED_SHA": _REVISION,
        },
        "kind": "ConfigMap",
        "metadata": {"name": "nohiki-verification-attempt", "namespace": "flux-system"},
    }
    producer_output = json.dumps(produced, sort_keys=True, separators=(",", ":")) + "\n"

    def run(
        argv: tuple[str, ...],
        *,
        input_text: str | None = None,
        **_: object,
    ) -> subprocess.CompletedProcess[str]:
        calls.append((argv, input_text))
        if argv[0] == "uv":
            return _result(argv, stdout=producer_output)
        return _result(argv)

    monkeypatch.setattr(runner, "run_command", run)
    monkeypatch.setattr(runner, "runtime_binding", lambda *_: ({"attempt": 4}, "1234abcd-0000"))
    monkeypatch.setattr(
        runner,
        "command_json",
        lambda *_args, **_kwargs: {
            "data": produced["data"],
            "metadata": {"resourceVersion": "9", "uid": "configmap-uid"},
        },
    )
    configmap = runner.apply_attempt_configmap(
        tmp_path,
        tmp_path / "kubeconfig",
        "runtime-control/local/test",
        _REVISION,
        {"attempt": 4},
        "1234abcd-0000",
        _LOCK_SHA,
    )
    assert configmap == {
        "configMapResourceVersion": "9",
        "configMapSha256": hashlib.sha256(producer_output.encode()).hexdigest(),
        "configMapUid": "configmap-uid",
    }
    producer = calls[0][0]
    assert producer[:6] == (
        "uv",
        "run",
        "--project",
        "infra/k8s/gitops",
        "python",
        str(runner.ATTEMPT_CONFIGMAP),
    )
    assert producer[-2:] == ("--artifact-lock-sha256", _LOCK_SHA)
    applies = [input_text for argv, input_text in calls if "apply" in argv]
    assert json.loads(applies[0] or "null")["kind"] == "Namespace"
    assert applies[1] == producer_output


def test_operator_install_requires_live_digest_and_observed_bootstrap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner()
    calls: list[tuple[str, ...]] = []

    def run(argv: tuple[str, ...], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        if "jsonpath={.spec.template.spec.containers[0].image}" in argv:
            return _result(argv, stdout="ghcr.io/controlplaneio-fluxcd/flux-operator@" + _OPERATOR_DIGEST)
        return _result(argv)

    monkeypatch.setattr(runner, "run_command", run)
    monkeypatch.setattr(runner, "runtime_binding", lambda *_: ({}, "cluster-uid"))
    observed: list[tuple[str, str]] = []
    monkeypatch.setattr(
        runner,
        "wait_flux_instance",
        lambda _kube, path, revision: observed.append((path, revision)) or "flux-uid",
    )
    uid = runner.operator_install_once(
        tmp_path,
        tmp_path / "kubeconfig",
        tmp_path / "bootstrap.yaml",
        _REVISION,
        _OPERATOR_DIGEST,
    )
    assert uid == "flux-uid"
    assert calls[0][-3:] == ("apply", "-f", str(runner.OPERATOR_INSTALL))
    crd_waits = [argv for argv in calls if "--for=condition=Established" in argv]
    assert [argv[-2] for argv in crd_waits] == [f"crd/{name}" for name in runner.OPERATOR_CRDS]
    assert any("deployment/flux-operator" in argv for argv in calls)
    assert any("jsonpath={.spec.template.spec.containers[0].image}" in argv for argv in calls)
    assert calls[-1][-3:] == ("apply", "-f", str(tmp_path / "bootstrap.yaml"))
    assert observed == [("infra/k8s/gitops/clusters/local/bootstrap", _REVISION)]


def test_finalize_applies_full_instance_and_observes_every_child_in_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner()
    monkeypatch.setenv("NOHIKI_RUNTIME_CONTROL_BRANCH", "runtime-control/local/test")
    monkeypatch.setenv("NOHIKI_REVIEWED_TOPIC_SHA", _REVISION)
    monkeypatch.setattr(runner, "validate_runtime_control", lambda *_: None)
    monkeypatch.setattr(runner, "validate_publication_record", lambda *_: {})
    monkeypatch.setattr(runner, "runtime_binding", lambda *_: ({}, "cluster-uid"))
    monkeypatch.setattr(runner, "render_branch_manifest", lambda *_: "4" * 64)
    monkeypatch.setattr(runner, "flux_source_revision", lambda *_: "refs/heads/test@sha1:" + _REVISION)
    monkeypatch.setattr(runner, "wait_flux_instance", lambda *_: "flux-uid")
    states: dict[str, object] = {
        "metadata": {"generation": 7},
        "status": {
            "lastAppliedRevision": "refs/heads/test@sha1:" + _REVISION,
            "observedGeneration": 7,
        },
    }
    gets = 0

    def command_json(argv: tuple[str, ...], **_: object) -> dict[str, object]:
        nonlocal gets
        gets += 1
        if "configmap" in argv:
            return {"metadata": {"uid": "configmap-uid"}}
        if "fluxinstance" in argv:
            return {
                "metadata": {"uid": "flux-uid"},
                "spec": {"sync": {"path": "infra/k8s/gitops/clusters/local/bootstrap"}},
            }
        return states

    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(runner, "command_json", command_json)
    monkeypatch.setattr(
        runner,
        "run_command",
        lambda argv, **_: calls.append(argv) or _result(argv),
    )
    result = runner.finalize_flux_runtime(
        tmp_path / "kubeconfig",
        tmp_path,
        tmp_path / "publication.json",
    )
    assert result["fluxInstanceUid"] == "flux-uid"
    final_apply = next(index for index, argv in enumerate(calls) if "apply" in argv)
    waits = [argv for argv in calls[final_apply + 1 :] if "--for=condition=Ready=True" in argv]
    assert [next(item for item in argv if item.startswith("kustomization/")) for argv in waits] == [
        f"kustomization/{name}" for name in runner.FULL_CHILDREN
    ]
    assert gets == len(runner.FULL_CHILDREN) + 2


def test_core_install_observes_root_readiness_and_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner()
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        runner,
        "run_command",
        lambda argv, **_: calls.append(argv) or _result(argv),
    )
    revisions: list[str] = []
    monkeypatch.setattr(
        runner,
        "flux_source_revision",
        lambda _kube, revision: revisions.append(revision) or "source-revision",
    )
    runner.install_core_runtime(tmp_path / "kubeconfig", tmp_path / "sync.yaml", _REVISION)
    assert calls[0][-3:] == ("apply", "-f", str(runner.FALLBACK_INSTALL))
    assert calls[-2][-3:] == ("apply", "-f", str(tmp_path / "sync.yaml"))
    assert "kustomization/flux-system" in calls[-1]
    assert revisions == [_REVISION]


def test_offline_policy_is_checked_loaded_observed_and_removed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner()
    monkeypatch.setattr(runner, "runtime_binding", lambda *_: ({}, "cluster-uid"))
    calls: list[tuple[str, ...]] = []

    def run(argv: tuple[str, ...], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        if argv[:4] == ("kind", "get", "nodes", "--name"):
            return _result(argv, stdout="nohiki-control-plane\n")
        if "list" in argv:
            return _result(argv, stdout="chain output { policy drop; counter } chain forward { policy drop; counter }")
        return _result(argv)

    monkeypatch.setattr(runner, "run_command", run)
    result = runner.qualify_offline_policy(tmp_path / "kubeconfig", tmp_path)
    assert result["nodes"] == "nohiki-control-plane"
    nft_calls = [argv for argv in calls if "nft" in argv]
    assert nft_calls[0][-3:] == ("-c", "-f", "-")
    assert nft_calls[1][-2:] == ("-f", "-")
    assert nft_calls[2][-4:] == ("list", "table", "inet", "nohiki_offline")
    assert nft_calls[3][-4:] == ("delete", "table", "inet", "nohiki_offline")
