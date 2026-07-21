"""Behavioral tests for fresh local-cluster reset and recovery evidence."""
# ruff: noqa: E501  # Exact fake argv lists mirror long production command contracts.

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import runpy
import stat
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _ROOT / "infra" / "k8s" / "local" / "cluster_reset.py"
_CONTEXT = "k3s-nohiki-test"
_OLD_UID = "11111111-1111-1111-1111-111111111111"
_NEW_UID = "22222222-2222-2222-2222-222222222222"
_OLD_CREATED = "2026-07-20T10:00:00Z"
_NEW_CREATED = "2099-07-20T10:01:00Z"
_DATA_LOSS = "I understand this permanently deletes local Nohiki data"
_FACTORY_LOSS = "I understand factory reset removes the Nohiki and Flux local control planes"
_OWNER_AUTH = "I am the recorded owner release-owner"
_ABSENT_NAMESPACES = (
    "nohiki",
    "nohiki-foundation",
    "nohiki-registry",
    "nohiki-verification",
    "flux-system",
)
_PHASES = (
    "authorized",
    "adapterPreflight",
    "purge",
    "start",
    "apiReady",
    "nodeReady",
    "identity",
    "absence",
)

_FAKE_TOOL = r"""#!/usr/bin/env python3
import json
import os
import pathlib
import sys
import time

name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
log = pathlib.Path(os.environ["FAKE_TOOL_LOG"])
with log.open("a", encoding="utf-8") as stream:
    stream.write("\t".join((name, *args)) + "\n")

def calls(tool, prefix=()):
    if not log.exists():
        return []
    rows = [line.split("\t") for line in log.read_text(encoding="utf-8").splitlines()]
    return [row for row in rows if row and row[0] == tool and row[1:1 + len(prefix)] == list(prefix)]

def fail(message, code=1):
    print(message, file=sys.stderr)
    raise SystemExit(code)

CHECKPOINT_INVENTORY = [
    ["get", "namespaces", "-o", "custom-columns=NAME:.metadata.name,PHASE:.status.phase,CREATED:.metadata.creationTimestamp"],  # noqa: E501
    ["get", "customresourcedefinitions", "-o", "custom-columns=NAME:.metadata.name,ESTABLISHED:.status.conditions[?(@.type=='Established')].status,STORED_VERSIONS:.status.storedVersions"],  # noqa: E501
    ["get", "persistentvolumeclaims", "--all-namespaces", "-o", "custom-columns=NAMESPACE:.metadata.namespace,NAME:.metadata.name,STATUS:.status.phase,VOLUME:.spec.volumeName,CLASS:.spec.storageClassName,CAPACITY:.status.capacity.storage"],  # noqa: E501
    ["get", "persistentvolumes", "-o", "custom-columns=NAME:.metadata.name,STATUS:.status.phase,CLAIM:.spec.claimRef.name,CLAIM_NAMESPACE:.spec.claimRef.namespace,CLASS:.spec.storageClassName,CAPACITY:.spec.capacity.storage,RECLAIM:.spec.persistentVolumeReclaimPolicy"],  # noqa: E501
    ["get", "storageclasses", "-o", "custom-columns=NAME:.metadata.name,PROVISIONER:.provisioner,RECLAIM:.reclaimPolicy,BINDING:.volumeBindingMode"],  # noqa: E501
    ["get", "kustomizations.kustomize.toolkit.fluxcd.io", "--all-namespaces", "-o", "custom-columns=NAMESPACE:.metadata.namespace,NAME:.metadata.name,SUSPENDED:.spec.suspend,REVISION:.status.lastAppliedRevision,READY:.status.conditions[?(@.type=='Ready')].status"],  # noqa: E501
    ["get", "gitrepositories.source.toolkit.fluxcd.io,ocirepositories.source.toolkit.fluxcd.io", "--all-namespaces", "-o", "custom-columns=KIND:.kind,NAMESPACE:.metadata.namespace,NAME:.metadata.name,REVISION:.status.artifact.revision,READY:.status.conditions[?(@.type=='Ready')].status"],  # noqa: E501
    ["get", "helmreleases.helm.toolkit.fluxcd.io", "--all-namespaces", "-o", "custom-columns=NAMESPACE:.metadata.namespace,NAME:.metadata.name,REVISION:.status.history[0].chartVersion,READY:.status.conditions[?(@.type=='Ready')].status"],  # noqa: E501
    ["get", "pods", "-n", "registry", "-o", "custom-columns=POD:.metadata.name,IMAGES:.spec.containers[*].image,IMAGE_IDS:.status.containerStatuses[*].imageID"],  # noqa: E501
    ["get", "pods", "--all-namespaces", "-o", "custom-columns=NAMESPACE:.metadata.namespace,POD:.metadata.name,IMAGES:.spec.containers[*].image,IMAGE_IDS:.status.containerStatuses[*].imageID"],  # noqa: E501
]

def request_timeout(value):
    return value.startswith("--request-timeout=") and value.endswith("s")


if name in {"purge-adapter", "start-adapter"}:
    phase = name.removesuffix("-adapter").upper()
    block = os.environ.get(f"FAKE_{phase}_BLOCK")
    if block:
        release = pathlib.Path(block)
        while not release.exists():
            time.sleep(0.01)
    delay = float(os.environ.get(f"FAKE_{phase}_SLEEP", "0"))
    if delay:
        time.sleep(delay)
    if phase == "PURGE" and (evidence_dir := os.environ.get("FAKE_PURGE_LOCK_EVIDENCE_DIR")):
        pathlib.Path(evidence_dir).chmod(0o500)
    if phase == "START":
        config_path = pathlib.Path(os.environ["KUBECONFIG"])
        config = json.loads(config_path.read_text(encoding="utf-8"))
        if os.environ.get("FAKE_POST_CONTEXT"):
            config["current-context"] = os.environ["FAKE_POST_CONTEXT"]
        if os.environ.get("FAKE_POST_ENDPOINT"):
            config["clusters"][0]["cluster"]["server"] = os.environ["FAKE_POST_ENDPOINT"]
        config_path.write_text(json.dumps(config), encoding="utf-8")
    if os.environ.get(f"FAKE_{phase}_INVALID_UTF8"):
        os.write(1, b"\xff")
    code = int(os.environ.get(f"FAKE_{phase}_EXIT", "0"))
    if code:
        fail(f"{phase.lower()} adapter synthetic failure secret-token", code)
    raise SystemExit(0)

if name in {"flux", "helm", "sops", "age"}:
    print(f"{name} test-version")
    raise SystemExit(0)

if name != "kubectl":
    fail(f"unexpected fake tool: {name}", 97)

context = os.environ.get("FAKE_CONTEXT", "k3s-nohiki-test")
started = bool(calls("start-adapter"))
if started and os.environ.get("FAKE_POST_CONTEXT"):
    context = os.environ["FAKE_POST_CONTEXT"]
endpoint = os.environ.get("FAKE_ENDPOINT", "https://127.0.0.1:6443")
if started and os.environ.get("FAKE_POST_ENDPOINT"):
    endpoint = os.environ["FAKE_POST_ENDPOINT"]

if args == ["config", "current-context"]:
    print(context)
elif args == ["config", "view", "--minify", "--context", context, "-o", "json"]:
    if raw := os.environ.get("FAKE_KUBECONFIG_JSON"):
        print(raw)
    else:
        print(json.dumps({
            "current-context": context,
            "clusters": [{"name": "cluster", "cluster": {
                "server": endpoint,
                "certificate-authority-data": "TOP-SECRET-CA",
            }}],
            "contexts": [{"name": context, "context": {"cluster": "cluster", "user": "owner"}}],
            "users": [{"name": "owner", "user": {"token": "TOP-SECRET-TOKEN"}}],
        }))
elif args == ["get", "namespace", "kube-system", "-o", "json", "--context", context]:
    if started and os.environ.get("FAKE_NEW_IDENTITY_MALFORMED"):
        print(os.environ["FAKE_NEW_IDENTITY_MALFORMED"])
    elif not started and os.environ.get("FAKE_OLD_IDENTITY_JSON"):
        print(os.environ["FAKE_OLD_IDENTITY_JSON"])
    else:
        uid = os.environ.get("FAKE_OLD_UID", "11111111-1111-1111-1111-111111111111")
        created = os.environ.get("FAKE_OLD_CREATED", "2026-07-20T10:00:00Z")
        if started:
            uid = os.environ.get("FAKE_NEW_UID", "22222222-2222-2222-2222-222222222222")
            created = os.environ.get("FAKE_NEW_CREATED", "2099-07-20T10:01:00Z")
        print(json.dumps({"metadata": {"uid": uid, "creationTimestamp": created}}))
elif len(args) == 6 and args[:5] == ["get", "--raw", "/readyz", "--context", context] and request_timeout(args[5]):  # noqa: E501
    time.sleep(float(os.environ.get("FAKE_READYZ_PROCESS_SLEEP", "0")))
    attempt = len(calls("kubectl", ("get", "--raw", "/readyz")))
    failures = int(os.environ.get("FAKE_READYZ_FAILURES", "0"))
    if os.environ.get("FAKE_READYZ_TLS") or attempt <= failures:
        fail("TLS handshake failed: stale kubeconfig secret-token")
    print("ok")
elif len(args) == 7 and args[:6] == ["wait", "--for=condition=Ready", "node", "--all", "--context", context] and args[6].startswith("--timeout="):  # noqa: E501
    if os.environ.get("FAKE_NODE_WAIT_NEAR_TIMEOUT"):
        remaining = float(args[6].removeprefix("--timeout=").removesuffix("s"))
        time.sleep(max(0.0, remaining - 0.05))
    time.sleep(float(os.environ.get("FAKE_NODE_WAIT_SLEEP", "0")))
    if os.environ.get("FAKE_NODE_WAIT_FAIL"):
        fail("timed out waiting for nodes")
    print("node/all condition met")
elif len(args) == 7 and args[:6] == ["get", "nodes", "-o", "json", "--context", context] and request_timeout(args[6]):  # noqa: E501
    count = int(os.environ.get("FAKE_NODE_COUNT", "1"))
    ready = os.environ.get("FAKE_NODE_READY", "True")
    items = [{"metadata": {"name": f"node-{index}"}, "status": {"conditions": [
        {"type": "Ready", "status": ready}
    ]}} for index in range(count)]
    print(json.dumps({"items": items}))
elif len(args) == 7 and args[:6] == ["get", "customresourcedefinitions", "-o", "json", "--context", context] and request_timeout(args[6]):  # noqa: E501
    residue = os.environ.get("FAKE_FLUX_CRD", "")
    print(json.dumps({"items": [] if not residue else [{"metadata": {"name": residue}}]}))
elif len(args) == 8 and args[:2] == ["get", "namespace"] and args[2] in {
    "nohiki", "nohiki-foundation", "nohiki-registry", "nohiki-verification", "flux-system"
} and args[3:7] == ["--context", context, "-o", "json"] and request_timeout(args[7]):
    synthetic_error = os.environ.get("FAKE_NAMESPACE_ERROR")
    if synthetic_error:
        fail(synthetic_error)
    if os.environ.get("FAKE_RESIDUAL_NAMESPACE") == args[2]:
        print(json.dumps({"metadata": {"name": args[2]}}))
    else:
        fail("NotFound")
elif args == ["auth", "whoami", "-o", "json"]:
    print('{"status":{"userInfo":{"username":"release-owner"}}}')
elif args in (["version", "-o", "json"], ["version", "--client", "-o", "json"]):
    print('{"clientVersion":{"gitVersion":"v1.test"}}')
elif args in CHECKPOINT_INVENTORY:
    print("synthetic checkpoint inventory")
else:
    fail("UNEXPECTED KUBECTL ARGV: " + json.dumps(args), 97)
"""


@dataclass(frozen=True)
class Harness:
    repo: Path
    env: dict[str, str]
    log: Path
    bindir: Path
    endpoint: str


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _commands(harness: Harness) -> list[list[str]]:
    if not harness.log.exists():
        return []
    return [line.split("\t") for line in harness.log.read_text(encoding="utf-8").splitlines()]


@pytest.fixture
def harness(tmp_path: Path) -> Harness:
    repository = tmp_path / "repo"
    repository.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
    config = repository / ".git" / "config"
    subprocess.run(["git", "config", "--file", str(config), "user.name", "Test Owner"], check=True)
    subprocess.run(
        ["git", "config", "--file", str(config), "user.email", "owner@example.invalid"],
        check=True,
    )
    (repository / "tracked.txt").write_text("checkpoint fixture\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repository, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=repository, check=True)
    subprocess.run(["git", "branch", "reviewed/topic"], cwd=repository, check=True)

    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name in (
        "kubectl",
        "flux",
        "helm",
        "sops",
        "age",
        "purge-adapter",
        "start-adapter",
    ):
        tool = bindir / name
        tool.write_text(_FAKE_TOOL, encoding="utf-8")
        tool.chmod(0o755)
    log = tmp_path / "commands.log"
    environment = {
        key: value
        for key, value in os.environ.items()
        if key
        not in {
            "NOHIKI_LOCAL_CLUSTER_PURGE_CMD",
            "NOHIKI_LOCAL_CLUSTER_START_CMD",
            "KUBECONFIG",
        }
    }
    kubeconfig = tmp_path / "kubeconfig"
    endpoint = f"https://{hashlib.sha256(str(tmp_path).encode()).hexdigest()[:16]}.test.invalid:6443"
    kubeconfig.write_text(
        json.dumps(
            {
                "apiVersion": "v1",
                "kind": "Config",
                "current-context": _CONTEXT,
                "clusters": [{"name": "cluster", "cluster": {"server": endpoint}}],
                "contexts": [{"name": _CONTEXT, "context": {"cluster": "cluster"}}],
            }
        ),
        encoding="utf-8",
    )
    environment |= {
        "PATH": f"{bindir}:{environment['PATH']}",
        "FAKE_TOOL_LOG": str(log),
        "FAKE_CONTEXT": _CONTEXT,
        "FAKE_ENDPOINT": endpoint,
        "KUBECONFIG": str(kubeconfig),
        "NOHIKI_LOCAL_CLUSTER_PURGE_CMD": "purge-adapter",
        "NOHIKI_LOCAL_CLUSTER_START_CMD": "start-adapter",
    }
    return Harness(repository, environment, log, bindir, endpoint)


def _run(
    harness: Harness,
    *arguments: str,
    env: dict[str, str] | None = None,
    timeout_constants: dict[str, float] | None = None,
    killpg_process_lookup: bool = False,
) -> subprocess.CompletedProcess[str]:
    environment = dict(harness.env if env is None else env)
    if timeout_constants is None and not killpg_process_lookup:
        command = [sys.executable, str(_SCRIPT), *arguments]
    else:
        launcher = (
            "import importlib.util,sys;"
            "p=sys.argv.pop(1);s=importlib.util.spec_from_file_location('cluster_reset_under_test',p);"
            "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);"
            + "".join(f"setattr(m,{name!r},{value!r});" for name, value in (timeout_constants or {}).items())
            + ("m.os.killpg=lambda *_:(_ for _ in ()).throw(ProcessLookupError());" if killpg_process_lookup else "")
            + "raise SystemExit(m.main())"
        )
        command = [sys.executable, "-c", launcher, str(_SCRIPT), *arguments]
    return subprocess.run(
        command,
        cwd=harness.repo,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )


def _checkpoint(harness: Harness, tmp_path: Path) -> tuple[Path, str]:
    path = tmp_path / "checkpoint.json"
    result = _run(
        harness,
        "checkpoint",
        "--expected-context",
        _CONTEXT,
        "--output",
        str(path),
        "--owner",
        "release-owner",
        "--runtime-control-ref",
        "HEAD",
        "--reviewed-topic",
        "runtime=reviewed/topic",
    )
    assert result.returncode == 0, result.stderr
    return path, _sha256(path)


def _factory_arguments(checkpoint: Path, checksum: str, evidence: Path, *, execute: bool = False) -> list[str]:
    arguments = [
        "factory-reset",
        "--destructive",
        "--expected-context",
        _CONTEXT,
        "--namespace",
        "nohiki",
        "--checkpoint",
        str(checkpoint),
        "--checkpoint-sha256",
        checksum,
        "--acknowledge-data-loss",
        _DATA_LOSS,
        "--owner-authorization",
        _OWNER_AUTH,
        "--acknowledge-factory-reset",
        _FACTORY_LOSS,
        "--evidence-output",
        str(evidence),
    ]
    if execute:
        arguments.append("--execute")
    return arguments


def _rewrite_checkpoint(path: Path, mutation: Callable[[dict[str, object]], None]) -> str:
    document = json.loads(path.read_text(encoding="utf-8"))
    mutation(document)
    path.write_text(json.dumps(document, sort_keys=True) + "\n", encoding="utf-8")
    checksum = _sha256(path)
    path.with_name(path.name + ".sha256").write_text(f"{checksum}  {path.name}\n", encoding="utf-8")
    return checksum


def _assert_sidecar(path: Path) -> None:
    assert path.with_name(path.name + ".sha256").read_text(encoding="utf-8") == f"{_sha256(path)}  {path.name}\n"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def _identity(harness: Harness, uid: str, created: str) -> dict[str, str]:
    return {
        "kubeSystemUid": uid,
        "kubeSystemCreatedAt": created,
        "apiServer": harness.endpoint,
    }


def test_checkpoint_endpoint_path_imports_with_stdlib_only(harness: Harness, tmp_path: Path) -> None:
    output = tmp_path / "stdlib-checkpoint.json"
    launcher = (
        "import builtins,runpy,sys;"
        "original=builtins.__import__;"
        "builtins.__import__=lambda name,*a,**k:"
        "(_ for _ in ()).throw(ImportError('third-party yaml forbidden'))"
        " if name.partition('.')[0] in {'yaml','ruamel'} else original(name,*a,**k);"
        "runpy.run_path(sys.argv.pop(1),run_name='__main__')"
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            launcher,
            str(_SCRIPT),
            "checkpoint",
            "--expected-context",
            _CONTEXT,
            "--output",
            str(output),
            "--owner",
            "release-owner",
        ],
        cwd=harness.repo,
        env=harness.env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(output.read_text())["evidence"]["clusterIdentity"]["apiServer"] == harness.endpoint


def test_checkpoint_exact_schema_identity_redaction_and_sidecar(harness: Harness, tmp_path: Path) -> None:
    path, _ = _checkpoint(harness, tmp_path)
    document = json.loads(path.read_text(encoding="utf-8"))
    assert set(document) == {"apiVersion", "kind", "metadata", "evidence"}
    assert document["apiVersion"] == "nohiki.io/v1alpha1"
    assert document["kind"] == "LocalDestructionCheckpoint"
    assert set(document["metadata"]) == {
        "capturedAt",
        "context",
        "namespaceAllowlist",
        "owner",
    }
    assert document["metadata"]["context"] == _CONTEXT
    assert document["metadata"]["namespaceAllowlist"] == ["nohiki", "flux-system"]
    assert document["metadata"]["owner"] == "release-owner"
    assert set(document["evidence"]) == {
        "clusterIdentity",
        "cluster",
        "git",
        "lifecycleTools",
    }
    assert document["evidence"]["clusterIdentity"] == _identity(harness, _OLD_UID, _OLD_CREATED)
    assert set(document["evidence"]["cluster"]) == {
        "apiIdentity",
        "apiVersions",
        "namespaces",
        "crds",
        "persistentVolumeClaims",
        "persistentVolumes",
        "storageClasses",
        "fluxKustomizations",
        "fluxSources",
        "fluxHelmReleases",
        "registryImages",
        "runtimeImages",
    }
    assert set(document["evidence"]["lifecycleTools"]) == {
        "kubectl",
        "flux",
        "helm",
        "sops",
        "age",
    }
    assert "containerdImages" not in document["evidence"]["cluster"]
    serialized = path.read_text(encoding="utf-8")
    assert "TOP-SECRET" not in serialized
    assert "certificate-authority-data" not in serialized
    assert '"users"' not in serialized
    _assert_sidecar(path)


def test_checkpoint_normalizes_api_server_url(harness: Harness, tmp_path: Path) -> None:
    environment = harness.env | {"FAKE_ENDPOINT": harness.endpoint + "/"}
    path = tmp_path / "checkpoint.json"
    result = _run(
        harness,
        "checkpoint",
        "--expected-context",
        _CONTEXT,
        "--output",
        str(path),
        env=environment,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(path.read_text())["evidence"]["clusterIdentity"]["apiServer"] == harness.endpoint


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("kubeSystemUid", ""),
        ("kubeSystemUid", 7),
        ("kubeSystemCreatedAt", "not-a-time"),
        ("kubeSystemCreatedAt", None),
        ("apiServer", "not a URL"),
        ("apiServer", "https://operator:password@cluster.invalid:6443"),
        ("apiServer", 7),
    ],
)
def test_checkpoint_identity_exact_type_validation(harness: Harness, tmp_path: Path, field: str, value: object) -> None:
    identity = {"metadata": {"uid": _OLD_UID, "creationTimestamp": _OLD_CREATED}}
    environment = dict(harness.env)
    if field == "apiServer":
        environment["FAKE_KUBECONFIG_JSON"] = json.dumps(
            {
                "current-context": _CONTEXT,
                "clusters": [{"name": "cluster", "cluster": {"server": value}}],
                "contexts": [{"name": _CONTEXT, "context": {"cluster": "cluster"}}],
                "users": [],
            }
        )
    else:
        metadata = identity["metadata"]
        metadata[{"kubeSystemUid": "uid", "kubeSystemCreatedAt": "creationTimestamp"}[field]] = value
        environment["FAKE_OLD_IDENTITY_JSON"] = json.dumps(identity)
    result = _run(
        harness,
        "checkpoint",
        "--expected-context",
        _CONTEXT,
        "--output",
        str(tmp_path / "bad.json"),
        env=environment,
    )
    assert result.returncode == 2
    assert "identity" in result.stderr.lower() or field in result.stderr
    assert not (tmp_path / "bad.json").exists()


def _remove_cluster_identity(document: dict[str, object]) -> None:
    evidence = document["evidence"]
    assert isinstance(evidence, dict)
    evidence.pop("clusterIdentity")


def _malform_cluster_identity(document: dict[str, object]) -> None:
    evidence = document["evidence"]
    assert isinstance(evidence, dict)
    evidence["clusterIdentity"] = {"kubeSystemUid": ""}


def _malform_checkpoint_schema(document: dict[str, object]) -> None:
    document["apiVersion"] = "wrong/v1"


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("destructive", "--destructive is required"),
        ("namespace", "outside the reset allowlist"),
        ("data-loss", "acknowledge-data-loss"),
        ("factory", "acknowledge-factory-reset"),
        ("context", "kubectl context"),
        ("missing-checkpoint", "checkpoint does not exist"),
        ("sha", "checksum mismatch"),
        ("missing-sidecar", "sidecar is missing"),
        ("tampered-sidecar", "sidecar is invalid"),
        ("malformed-sidecar", "sidecar is invalid"),
        ("malformed-checkpoint", "not valid JSON"),
        ("checkpoint-schema", "schema identity"),
        ("owner", "owner authorization"),
        ("missing-identity", "cluster identity"),
        ("malformed-identity", "cluster identity"),
    ],
)
def test_every_authorization_and_checkpoint_refusal_precedes_mutation(
    harness: Harness, tmp_path: Path, case: str, expected: str
) -> None:
    checkpoint, checksum = _checkpoint(harness, tmp_path)
    evidence = tmp_path / "transaction.json"
    arguments = _factory_arguments(checkpoint, checksum, evidence)
    if case == "destructive":
        arguments.remove("--destructive")
    elif case == "namespace":
        arguments[arguments.index("nohiki")] = "arbitrary"
    elif case == "data-loss":
        arguments[arguments.index(_DATA_LOSS)] = "wrong"
    elif case == "factory":
        arguments[arguments.index(_FACTORY_LOSS)] = "wrong"
    elif case == "context":
        arguments[arguments.index(_CONTEXT)] = "wrong-context"
    elif case == "missing-checkpoint":
        arguments[arguments.index(str(checkpoint))] = str(tmp_path / "missing.json")
    elif case == "sha":
        arguments[arguments.index(checksum)] = "0" * 64
    elif case == "missing-sidecar":
        checkpoint.with_name(checkpoint.name + ".sha256").unlink()
    elif case == "tampered-sidecar":
        checkpoint.with_name(checkpoint.name + ".sha256").write_text(f"{'0' * 64}  {checkpoint.name}\n")
    elif case == "malformed-sidecar":
        checkpoint.with_name(checkpoint.name + ".sha256").write_text("malformed\n")
    elif case == "malformed-checkpoint":
        checkpoint.write_text("{", encoding="utf-8")
        checksum = _sha256(checkpoint)
        checkpoint.with_name(checkpoint.name + ".sha256").write_text(f"{checksum}  {checkpoint.name}\n")
        arguments[arguments.index(arguments[arguments.index("--checkpoint-sha256") + 1])] = checksum
    elif case == "checkpoint-schema":
        checksum = _rewrite_checkpoint(checkpoint, _malform_checkpoint_schema)
        arguments[arguments.index(arguments[arguments.index("--checkpoint-sha256") + 1])] = checksum
    elif case == "owner":
        arguments[arguments.index(_OWNER_AUTH)] = "wrong"
    elif case == "missing-identity":
        checksum = _rewrite_checkpoint(checkpoint, _remove_cluster_identity)
        arguments[arguments.index(arguments[arguments.index("--checkpoint-sha256") + 1])] = checksum
    elif case == "malformed-identity":
        checksum = _rewrite_checkpoint(checkpoint, _malform_cluster_identity)
        arguments[arguments.index(arguments[arguments.index("--checkpoint-sha256") + 1])] = checksum
    before = len(_commands(harness))
    result = _run(harness, *arguments)
    commands = _commands(harness)[before:]
    assert result.returncode == 2
    assert expected in result.stderr
    assert not any(command[0] in {"purge-adapter", "start-adapter"} for command in commands)
    assert not evidence.exists() or json.loads(evidence.read_text())["status"] != "succeeded"


def test_authorization_guard_precedence_starts_with_destructive_flag(harness: Harness, tmp_path: Path) -> None:
    checkpoint, _ = _checkpoint(harness, tmp_path)
    arguments = _factory_arguments(checkpoint, "0" * 64, tmp_path / "transaction.json")
    arguments.remove("--destructive")
    arguments[arguments.index("nohiki")] = "arbitrary"
    result = _run(harness, *arguments)
    assert result.returncode == 2
    assert "--destructive is required" in result.stderr


@pytest.mark.parametrize("kubeconfig", [None, ""])
def test_factory_requires_explicit_nonempty_kubeconfig_before_adapter(
    harness: Harness, tmp_path: Path, kubeconfig: str | None
) -> None:
    checkpoint, checksum = _checkpoint(harness, tmp_path)
    environment = dict(harness.env)
    if kubeconfig is None:
        environment.pop("KUBECONFIG")
    else:
        environment["KUBECONFIG"] = kubeconfig
    result = _run(
        harness,
        *_factory_arguments(checkpoint, checksum, tmp_path / "transaction.json", execute=True),
        env=environment,
    )
    assert result.returncode == 2
    assert "KUBECONFIG" in result.stderr
    assert not any(row[0] in {"purge-adapter", "start-adapter"} for row in _commands(harness))


@pytest.mark.parametrize("variable", ["NOHIKI_LOCAL_CLUSTER_PURGE_CMD", "NOHIKI_LOCAL_CLUSTER_START_CMD"])
@pytest.mark.parametrize("case", ["unset", "blank", "unparsable", "missing", "non-executable"])
def test_adapter_preflight_refuses_both_variables_before_purge(
    harness: Harness, tmp_path: Path, variable: str, case: str
) -> None:
    checkpoint, checksum = _checkpoint(harness, tmp_path)
    environment = dict(harness.env)
    if case == "unset":
        environment.pop(variable)
    elif case == "blank":
        environment[variable] = "   "
    elif case == "unparsable":
        environment[variable] = "'"
    elif case == "missing":
        environment[variable] = str(tmp_path / "missing-adapter")
    else:
        adapter = tmp_path / f"{case}-adapter"
        adapter.write_text("exit 0\n")
        adapter.chmod(0o644)
        environment[variable] = str(adapter)
    evidence = tmp_path / "transaction.json"
    before = len(_commands(harness))
    result = _run(
        harness,
        *_factory_arguments(checkpoint, checksum, evidence, execute=True),
        env=environment,
    )
    assert result.returncode == 2
    assert variable in result.stderr
    assert not any(command[0] == "purge-adapter" for command in _commands(harness)[before:])
    assert not evidence.exists() or json.loads(evidence.read_text())["status"] != "succeeded"


@pytest.mark.parametrize(
    ("variable", "expected_purge_calls"),
    [
        ("NOHIKI_LOCAL_CLUSTER_PURGE_CMD", 0),
        ("NOHIKI_LOCAL_CLUSTER_START_CMD", 1),
    ],
)
def test_adapter_spawn_errors_are_durable_and_never_continue(
    harness: Harness, tmp_path: Path, variable: str, expected_purge_calls: int
) -> None:
    checkpoint, checksum = _checkpoint(harness, tmp_path)
    adapter = harness.bindir / "bad-interpreter"
    adapter.write_text("#!/definitely/missing/interpreter\n")
    adapter.chmod(0o755)
    environment = harness.env | {variable: str(adapter)}
    evidence = tmp_path / "transaction.json"
    before = len(_commands(harness))
    result = _run(
        harness,
        *_factory_arguments(checkpoint, checksum, evidence, execute=True),
        env=environment,
    )
    assert result.returncode == 2
    assert "spawn" in result.stderr.lower() or "execute" in result.stderr.lower()
    commands = _commands(harness)[before:]
    assert sum(row[0] == "purge-adapter" for row in commands) == expected_purge_calls
    assert not any(row[0] == "start-adapter" for row in commands)
    document = json.loads(evidence.read_text())
    assert document["status"] == "failed"
    _assert_sidecar(evidence)


def test_adapter_argv_is_resolved_and_metacharacters_are_literal(harness: Harness, tmp_path: Path) -> None:
    checkpoint, checksum = _checkpoint(harness, tmp_path)
    marker = tmp_path / "must-not-exist"
    environment = harness.env | {
        "NOHIKI_LOCAL_CLUSTER_PURGE_CMD": f"purge-adapter ; touch {marker}",
        "NOHIKI_LOCAL_CLUSTER_START_CMD": f"start-adapter ; touch {marker}",
    }
    result = _run(
        harness,
        *_factory_arguments(
            checkpoint,
            checksum,
            tmp_path / "transaction.json",
            execute=True,
        ),
        env=environment,
    )
    assert result.returncode == 0, result.stderr
    assert not marker.exists()
    commands = _commands(harness)
    purge = next(command for command in commands if command[0] == "purge-adapter")
    start = next(command for command in commands if command[0] == "start-adapter")
    assert purge[1:] == [";", "touch", str(marker)]
    assert start[1:] == [";", "touch", str(marker)]


def test_prepurge_identity_mismatch_refuses_before_adapter(harness: Harness, tmp_path: Path) -> None:
    checkpoint, checksum = _checkpoint(harness, tmp_path)
    environment = harness.env | {"FAKE_OLD_UID": "different-live-uid"}
    result = _run(
        harness,
        *_factory_arguments(checkpoint, checksum, tmp_path / "transaction.json", execute=True),
        env=environment,
    )
    assert result.returncode == 2
    assert "identity" in result.stderr.lower()
    assert not any(command[0] in {"purge-adapter", "start-adapter"} for command in _commands(harness))


@pytest.mark.parametrize(
    ("phase", "environment_update", "timeouts"),
    [
        ("purge", {"FAKE_PURGE_EXIT": "9"}, None),
        ("purge", {"FAKE_PURGE_SLEEP": "2"}, {"PURGE_TIMEOUT_SECONDS": 0.5}),
        ("start", {"FAKE_START_EXIT": "8"}, None),
        ("start", {"FAKE_START_SLEEP": "2"}, {"START_TIMEOUT_SECONDS": 0.5}),
    ],
)
def test_adapter_failure_and_timeout_leave_failed_evidence(
    harness: Harness,
    tmp_path: Path,
    phase: str,
    environment_update: dict[str, str],
    timeouts: dict[str, float] | None,
) -> None:
    checkpoint, checksum = _checkpoint(harness, tmp_path)
    evidence = tmp_path / "transaction.json"
    result = _run(
        harness,
        *_factory_arguments(checkpoint, checksum, evidence, execute=True),
        env=harness.env | environment_update,
        timeout_constants=timeouts,
    )
    assert result.returncode == 2
    document = json.loads(evidence.read_text())
    assert document["status"] == "failed"
    record = next(item for item in document["phases"] if item["phase"] == phase)
    assert "startedAt" in record
    assert "completedAt" in record
    assert record["exitCode"] != 0
    _assert_sidecar(evidence)
    assert "secret-token" not in evidence.read_text()
    assert "secret-token" not in result.stderr
    commands = _commands(harness)
    assert sum(command[0] == "purge-adapter" for command in commands) == 1
    if phase == "purge":
        assert not any(command[0] == "start-adapter" for command in commands)


def test_evidence_write_failure_before_purge_refuses_without_adapter(harness: Harness, tmp_path: Path) -> None:
    checkpoint, checksum = _checkpoint(harness, tmp_path)
    evidence = tmp_path / "missing" / "transaction.json"
    result = _run(harness, *_factory_arguments(checkpoint, checksum, evidence, execute=True))
    assert result.returncode == 2
    assert "evidence" in result.stderr.lower() or "write" in result.stderr.lower()
    assert not any(row[0] in {"purge-adapter", "start-adapter"} for row in _commands(harness))


def test_evidence_write_failure_after_purge_stops_and_preserves_last_boundary(harness: Harness, tmp_path: Path) -> None:
    checkpoint, checksum = _checkpoint(harness, tmp_path)
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    evidence = evidence_dir / "transaction.json"
    result = _run(
        harness,
        *_factory_arguments(checkpoint, checksum, evidence, execute=True),
        env=harness.env | {"FAKE_PURGE_LOCK_EVIDENCE_DIR": str(evidence_dir)},
    )
    evidence_dir.chmod(0o700)
    assert result.returncode == 2
    assert "evidence" in result.stderr.lower() or "write" in result.stderr.lower()
    assert sum(row[0] == "purge-adapter" for row in _commands(harness)) == 1
    assert not any(row[0] == "start-adapter" for row in _commands(harness))
    document = json.loads(evidence.read_text())
    purge = next(record for record in document["phases"] if record["phase"] == "purge")
    assert "startedAt" in purge
    assert "completedAt" not in purge
    _assert_sidecar(evidence)


def test_readyz_retries_then_succeeds_with_explicit_context_and_request_timeout(
    harness: Harness, tmp_path: Path
) -> None:
    checkpoint, checksum = _checkpoint(harness, tmp_path)
    result = _run(
        harness,
        *_factory_arguments(checkpoint, checksum, tmp_path / "transaction.json", execute=True),
        env=harness.env | {"FAKE_READYZ_FAILURES": "2"},
    )
    assert result.returncode == 0, result.stderr
    polls = [command for command in _commands(harness) if command[1:4] == ["get", "--raw", "/readyz"]]
    assert len(polls) >= 3
    assert all("--context" in command and _CONTEXT in command for command in polls)
    assert all(any(argument.startswith("--request-timeout") for argument in command) for command in polls)


def test_node_wait_uses_remaining_deadline_beyond_general_command_cap() -> None:
    module = runpy.run_path(str(_SCRIPT))
    observed: dict[str, object] = {}

    def ready_after_general_cap(*_arguments: str, **options: object) -> dict[str, object]:
        observed["arguments"] = _arguments
        observed["timeout"] = options["timeout"]
        return {"command": [], "exitCode": 0, "stdout": "", "stderr": ""}

    module["_wait_nodes"].__globals__["kubectl"] = ready_after_general_cap
    module["_wait_nodes"](_CONTEXT, time.monotonic() + 65.0)
    arguments = tuple(str(value) for value in observed["arguments"])
    wait_timeout = float(arguments[-1].removeprefix("--timeout=").removesuffix("s"))
    assert not any(value.startswith("--request-timeout=") for value in arguments)
    assert float(observed["timeout"]) >= wait_timeout
    assert wait_timeout > 60.0


def test_near_deadline_node_success_gets_fresh_identity_absence_budget(harness: Harness, tmp_path: Path) -> None:
    checkpoint, checksum = _checkpoint(harness, tmp_path)
    evidence = tmp_path / "transaction.json"
    result = _run(
        harness,
        *_factory_arguments(checkpoint, checksum, evidence, execute=True),
        env=harness.env | {"FAKE_NODE_WAIT_NEAR_TIMEOUT": "1"},
        timeout_constants={"READINESS_TIMEOUT_SECONDS": 3.0},
    )
    assert result.returncode == 0, result.stderr
    document = json.loads(evidence.read_text())
    assert document["status"] == "succeeded"
    assert document["identity"]["new"]["kubeSystemUid"] == _NEW_UID
    assert document["absence"] == [
        {"check": check, "passed": True}
        for check in (
            *(f"namespace {namespace} absent" for namespace in _ABSENT_NAMESPACES),
            "no CRD ending .fluxcd.io",
        )
    ]


@pytest.mark.parametrize(
    ("update", "expected"),
    [
        ({"FAKE_READYZ_TLS": "1"}, "KUBECONFIG"),
        ({"FAKE_NODE_WAIT_FAIL": "1"}, "KUBECONFIG"),
        ({"FAKE_POST_CONTEXT": "wrong-context"}, "context"),
        ({"FAKE_POST_ENDPOINT": "https://wrong.invalid:6443"}, "api"),
        ({"FAKE_NEW_IDENTITY_MALFORMED": "{}"}, "identity"),
        ({"FAKE_NEW_UID": _OLD_UID}, "identity"),
        ({"FAKE_NEW_CREATED": _OLD_CREATED}, "created"),
    ],
)
def test_post_mutation_verification_failures_are_durable(
    harness: Harness, tmp_path: Path, update: dict[str, str], expected: str
) -> None:
    checkpoint, checksum = _checkpoint(harness, tmp_path)
    evidence = tmp_path / "transaction.json"
    timeout_constants = {"READINESS_TIMEOUT_SECONDS": 0.05} if "FAKE_READYZ_TLS" in update else None
    result = _run(
        harness,
        *_factory_arguments(checkpoint, checksum, evidence, execute=True),
        env=harness.env | update,
        timeout_constants=timeout_constants,
    )
    assert result.returncode == 2
    assert expected.lower() in (result.stderr + evidence.read_text()).lower()
    document = json.loads(evidence.read_text())
    assert document["status"] == "failed"
    assert document["metadata"]["checkpoint"] == {
        "basename": checkpoint.name,
        "sha256": checksum,
    }
    assert document["identity"]["old"] == _identity(harness, _OLD_UID, _OLD_CREATED)
    assert "diagnostic" in document
    assert "secret-token" not in evidence.read_text()
    assert "secret-token" not in result.stderr
    _assert_sidecar(evidence)


def test_new_identity_created_after_old_but_before_transaction_fails(harness: Harness, tmp_path: Path) -> None:
    checkpoint, _ = _checkpoint(harness, tmp_path)

    def replace_created_at(document: dict[str, object]) -> None:
        evidence = document["evidence"]
        assert isinstance(evidence, dict)
        identity = evidence["clusterIdentity"]
        assert isinstance(identity, dict)
        identity["kubeSystemCreatedAt"] = "2000-01-01T00:00:00Z"

    checksum = _rewrite_checkpoint(checkpoint, replace_created_at)
    evidence = tmp_path / "transaction.json"
    result = _run(
        harness,
        *_factory_arguments(checkpoint, checksum, evidence, execute=True),
        env=harness.env
        | {
            "FAKE_OLD_CREATED": "2000-01-01T00:00:00Z",
            "FAKE_NEW_CREATED": "2020-01-01T00:00:00Z",
        },
    )
    assert result.returncode == 2
    assert "transaction" in (result.stderr + evidence.read_text()).lower()
    assert json.loads(evidence.read_text())["status"] == "failed"
    _assert_sidecar(evidence)


@pytest.mark.parametrize("namespace", _ABSENT_NAMESPACES)
def test_each_owned_namespace_residue_fails_factory_and_zero_state(
    harness: Harness, tmp_path: Path, namespace: str
) -> None:
    checkpoint, checksum = _checkpoint(harness, tmp_path)
    environment = harness.env | {"FAKE_RESIDUAL_NAMESPACE": namespace}
    transaction = tmp_path / "transaction.json"
    reset = _run(
        harness,
        *_factory_arguments(checkpoint, checksum, transaction, execute=True),
        env=environment,
    )
    assert reset.returncode == 2
    assert namespace in reset.stderr + transaction.read_text()
    assert json.loads(transaction.read_text())["status"] == "failed"
    _assert_sidecar(transaction)

    evidence = tmp_path / "zero-state.json"
    zero = _run(
        harness,
        "zero-state",
        "--expected-context",
        _CONTEXT,
        "--namespace",
        "nohiki",
        "--evidence-output",
        str(evidence),
        env=environment,
    )
    assert zero.returncode == 2
    assert namespace in zero.stderr
    assert not evidence.exists() or json.loads(evidence.read_text()).get("status") != "succeeded"


@pytest.mark.parametrize(
    ("update", "expected"),
    [
        ({"FAKE_FLUX_CRD": "kustomizations.kustomize.toolkit.fluxcd.io"}, "fluxcd.io"),
        ({"FAKE_NODE_COUNT": "0"}, "node"),
        ({"FAKE_NODE_READY": "False"}, "Ready"),
    ],
)
def test_flux_crd_and_node_invariants_fail_absence_verification(
    harness: Harness, tmp_path: Path, update: dict[str, str], expected: str
) -> None:
    checkpoint, checksum = _checkpoint(harness, tmp_path)
    transaction = tmp_path / "transaction.json"
    result = _run(
        harness,
        *_factory_arguments(checkpoint, checksum, transaction, execute=True),
        env=harness.env | update,
    )
    assert result.returncode == 2
    assert expected.lower() in (result.stderr + transaction.read_text()).lower()
    assert json.loads(transaction.read_text())["status"] == "failed"
    _assert_sidecar(transaction)


@pytest.mark.parametrize("diagnostic", ["TLS handshake failed", "API server not found"])
def test_namespace_transport_failure_never_proves_absence(harness: Harness, tmp_path: Path, diagnostic: str) -> None:
    evidence = tmp_path / "zero-state.json"
    result = _run(
        harness,
        "zero-state",
        "--expected-context",
        _CONTEXT,
        "--namespace",
        "nohiki",
        "--evidence-output",
        str(evidence),
        env=harness.env | {"FAKE_NAMESPACE_ERROR": diagnostic},
    )
    assert result.returncode == 2
    assert "absence check failed" in result.stderr
    assert not evidence.exists()


def test_recovery_refuses_under_execute_lock_before_live_capture(harness: Harness, tmp_path: Path) -> None:
    checkpoint, checksum = _checkpoint(harness, tmp_path)
    succeeded = tmp_path / "succeeded.json"
    reset = _run(harness, *_factory_arguments(checkpoint, checksum, succeeded, execute=True))
    assert reset.returncode == 0, reset.stderr
    reset_checksum = _sha256(succeeded)

    second_dir = tmp_path / "second"
    second_dir.mkdir()
    current_checkpoint, current_checksum = _checkpoint(harness, second_dir)
    release = tmp_path / "release"
    active = tmp_path / "active.json"
    process = subprocess.Popen(
        [
            sys.executable,
            str(_SCRIPT),
            *_factory_arguments(current_checkpoint, current_checksum, active, execute=True),
        ],
        cwd=harness.repo,
        env=harness.env | {"FAKE_PURGE_BLOCK": str(release)},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 5
        while sum(row[0] == "purge-adapter" for row in _commands(harness)) < 2:
            assert time.monotonic() < deadline
            time.sleep(0.01)
        before = len(_commands(harness))
        output = tmp_path / "blocked-recovery.json"
        result = _run(
            harness,
            "recovery-evidence",
            "--expected-context",
            _CONTEXT,
            "--checkpoint",
            str(checkpoint),
            "--checkpoint-sha256",
            checksum,
            "--reset-transaction",
            str(succeeded),
            "--reset-transaction-sha256",
            reset_checksum,
            "--output",
            str(output),
        )
        assert result.returncode == 2
        assert "transaction is active" in result.stderr
        kubectl_calls = [row for row in _commands(harness)[before:] if row[0] == "kubectl"]
        assert kubectl_calls == [
            [
                "kubectl",
                "config",
                "view",
                "--minify",
                "--context",
                _CONTEXT,
                "-o",
                "json",
            ]
        ]
        assert not output.exists()
    finally:
        release.touch()
        process.communicate(timeout=10)


@pytest.mark.parametrize("command", ["checkpoint", "zero-state"])
def test_read_only_commands_refuse_while_execute_lock_is_active(harness: Harness, tmp_path: Path, command: str) -> None:
    checkpoint, checksum = _checkpoint(harness, tmp_path)
    release = tmp_path / "release"
    environment = harness.env | {"FAKE_PURGE_BLOCK": str(release)}
    transaction = tmp_path / "transaction.json"
    process = subprocess.Popen(
        [
            sys.executable,
            str(_SCRIPT),
            *_factory_arguments(checkpoint, checksum, transaction, execute=True),
        ],
        cwd=harness.repo,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + 5
    while not any(row[0] == "purge-adapter" for row in _commands(harness)):
        assert time.monotonic() < deadline
        time.sleep(0.01)
    output = tmp_path / f"blocked-{command}.json"
    if command == "checkpoint":
        arguments = [command, "--expected-context", _CONTEXT, "--output", str(output)]
    else:
        arguments = [
            command,
            "--expected-context",
            _CONTEXT,
            "--namespace",
            "nohiki",
            "--evidence-output",
            str(output),
        ]
    blocked = _run(harness, *arguments)
    release.touch()
    stdout, stderr = process.communicate(timeout=5)
    assert process.returncode == 0, stderr or stdout
    assert blocked.returncode == 2
    assert "active" in blocked.stderr.lower() or "lock" in blocked.stderr.lower()
    assert not output.exists()


def test_two_concurrent_executes_make_exactly_one_adapter_transaction(harness: Harness, tmp_path: Path) -> None:
    checkpoint, checksum = _checkpoint(harness, tmp_path)
    release = tmp_path / "release"
    environment = harness.env | {"FAKE_PURGE_BLOCK": str(release)}
    first_evidence = tmp_path / "first.json"
    second_evidence = tmp_path / "second.json"
    first = subprocess.Popen(
        [
            sys.executable,
            str(_SCRIPT),
            *_factory_arguments(checkpoint, checksum, first_evidence, execute=True),
        ],
        cwd=harness.repo,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + 5
    while not any(row[0] == "purge-adapter" for row in _commands(harness)):
        assert time.monotonic() < deadline
        time.sleep(0.01)
    second = _run(
        harness,
        *_factory_arguments(checkpoint, checksum, second_evidence, execute=True),
        env=environment,
    )
    assert second.returncode == 2
    assert "active" in second.stderr.lower() or "lock" in second.stderr.lower()
    release.touch()
    stdout, stderr = first.communicate(timeout=5)
    assert first.returncode == 0, stderr or stdout
    assert sum(row[0] == "purge-adapter" for row in _commands(harness)) == 1
    assert sum(row[0] == "start-adapter" for row in _commands(harness)) == 1
    assert not second_evidence.exists()


def test_success_evidence_schema_sidecar_identity_absence_and_partial_order(harness: Harness, tmp_path: Path) -> None:
    checkpoint, checksum = _checkpoint(harness, tmp_path)
    evidence = tmp_path / "transaction.json"
    before = len(_commands(harness))
    result = _run(harness, *_factory_arguments(checkpoint, checksum, evidence, execute=True))
    assert result.returncode == 0, result.stderr
    document = json.loads(evidence.read_text())
    assert set(document) == {
        "apiVersion",
        "kind",
        "metadata",
        "phases",
        "identity",
        "absence",
        "status",
    }
    assert document["apiVersion"] == "nohiki.io/v1alpha1"
    assert document["kind"] == "LocalFactoryResetTransaction"
    assert set(document["metadata"]) == {"startedAt", "context", "owner", "checkpoint"}
    assert document["metadata"]["context"] == _CONTEXT
    assert document["metadata"]["owner"] == "release-owner"
    assert document["metadata"]["checkpoint"] == {
        "basename": checkpoint.name,
        "sha256": checksum,
    }
    assert document["status"] == "succeeded"
    assert document["identity"] == {
        "old": _identity(harness, _OLD_UID, _OLD_CREATED),
        "new": _identity(harness, _NEW_UID, _NEW_CREATED),
    }
    assert [record["phase"] for record in document["phases"]] == list(_PHASES)
    for record in document["phases"]:
        assert set(record) >= {"phase", "startedAt", "completedAt"}
        dt.datetime.fromisoformat(record["startedAt"])
        dt.datetime.fromisoformat(record["completedAt"])
        allowed = {"phase", "startedAt", "completedAt", "detail"}
        if record["phase"] in {"purge", "start"}:
            allowed |= {"argv", "exitCode"}
            assert Path(record["argv"][0]).is_absolute()
            assert record["exitCode"] == 0
        else:
            assert "argv" not in record
            assert "exitCode" not in record
        assert set(record) <= allowed
    absence = document["absence"]
    assert len(absence) == len(_ABSENT_NAMESPACES) + 1
    assert all(set(record) == {"check", "passed"} and record["passed"] is True for record in absence)
    checks = [record["check"] for record in absence]
    assert all(any(namespace in check for check in checks) for namespace in _ABSENT_NAMESPACES)
    assert any("fluxcd.io" in check for check in checks)
    _assert_sidecar(evidence)

    commands = _commands(harness)[before:]
    positions = {
        "purge": next(index for index, row in enumerate(commands) if row[0] == "purge-adapter"),
        "start": next(index for index, row in enumerate(commands) if row[0] == "start-adapter"),
        "api": next(
            index
            for index, row in enumerate(commands)
            if row[0] == "kubectl" and row[1:4] == ["get", "--raw", "/readyz"]
        ),
        "node": next(index for index, row in enumerate(commands) if row[0] == "kubectl" and row[1] == "wait"),
        "identity": max(
            index
            for index, row in enumerate(commands)
            if row[0] == "kubectl" and row[1:3] == ["get", "namespace"] and "kube-system" in row
        ),
        "absence": max(
            index
            for index, row in enumerate(commands)
            if row[0] == "kubectl" and row[1:3] == ["get", "namespace"] and row[3] in _ABSENT_NAMESPACES
        ),
    }
    assert (
        positions["purge"]
        < positions["start"]
        < positions["api"]
        < positions["node"]
        < positions["identity"]
        < positions["absence"]
    )


def test_dry_run_traverses_identity_and_prints_adapters_without_mutation(harness: Harness, tmp_path: Path) -> None:
    checkpoint, checksum = _checkpoint(harness, tmp_path)
    before = len(_commands(harness))
    result = _run(harness, *_factory_arguments(checkpoint, checksum, tmp_path / "dry.json"))
    assert result.returncode == 0, result.stderr
    assert str((harness.bindir / "purge-adapter").resolve()) in result.stdout
    assert str((harness.bindir / "start-adapter").resolve()) in result.stdout
    assert _OLD_UID in result.stdout
    assert harness.endpoint in result.stdout
    commands = _commands(harness)[before:]
    assert any(row[1:4] == ["get", "namespace", "kube-system"] for row in commands)
    assert not any(row[0] in {"purge-adapter", "start-adapter"} for row in commands)
    assert not (tmp_path / "dry.json").exists()


def test_dry_run_refuses_live_identity_mismatch_without_adapter_calls(harness: Harness, tmp_path: Path) -> None:
    checkpoint, checksum = _checkpoint(harness, tmp_path)
    before = len(_commands(harness))
    result = _run(
        harness,
        *_factory_arguments(checkpoint, checksum, tmp_path / "dry.json"),
        env=harness.env | {"FAKE_OLD_UID": "wrong-live-uid"},
    )
    assert result.returncode == 2
    assert "identity" in result.stderr.lower()
    assert not any(row[0] in {"purge-adapter", "start-adapter"} for row in _commands(harness)[before:])


def test_zero_state_checkpoint_binding_and_recovery_identity_match(harness: Harness, tmp_path: Path) -> None:
    checkpoint, checksum = _checkpoint(harness, tmp_path)
    transaction = tmp_path / "transaction.json"
    reset = _run(harness, *_factory_arguments(checkpoint, checksum, transaction, execute=True))
    assert reset.returncode == 0, reset.stderr
    transaction_checksum = _sha256(transaction)

    zero = tmp_path / "zero.json"
    zero_result = _run(
        harness,
        "zero-state",
        "--expected-context",
        _CONTEXT,
        "--namespace",
        "nohiki",
        "--checkpoint",
        str(checkpoint),
        "--checkpoint-sha256",
        checksum,
        "--evidence-output",
        str(zero),
    )
    assert zero_result.returncode == 0, zero_result.stderr
    _assert_sidecar(zero)

    commit = transaction.with_name(f".{transaction.name}.commit")
    assert commit.read_text(encoding="ascii") == f"complete {transaction_checksum}\n"
    commit.write_text(f"pending {transaction_checksum}\n", encoding="ascii")
    transaction.with_name(transaction.name + ".sha256").write_text(
        f"{'0' * 64}  {transaction.name}\n",
        encoding="ascii",
    )

    recovery = tmp_path / "recovery.json"
    recovery_result = _run(
        harness,
        "recovery-evidence",
        "--expected-context",
        _CONTEXT,
        "--checkpoint",
        str(checkpoint),
        "--checkpoint-sha256",
        checksum,
        "--reset-transaction",
        str(transaction),
        "--reset-transaction-sha256",
        transaction_checksum,
        "--output",
        str(recovery),
    )
    assert recovery_result.returncode == 0, recovery_result.stderr
    _assert_sidecar(transaction)
    assert commit.read_text(encoding="ascii") == f"complete {transaction_checksum}\n"
    document = json.loads(recovery.read_text())
    assert document["evidence"]["clusterIdentity"] == _identity(harness, _NEW_UID, _NEW_CREATED)
    assert document["evidence"]["clusterIdentity"] == json.loads(transaction.read_text())["identity"]["new"]
    _assert_sidecar(recovery)


@pytest.mark.parametrize(
    "case",
    [
        "checksum",
        "identity",
        "failed-status",
        "missing-phases",
        "absence",
        "old-identity",
        "context",
        "not-fresh",
    ],
)
def test_recovery_refuses_invalid_or_nonmatching_reset_transaction(harness: Harness, tmp_path: Path, case: str) -> None:
    checkpoint, checkpoint_checksum = _checkpoint(harness, tmp_path)
    transaction = tmp_path / "transaction.json"
    reset = _run(
        harness,
        *_factory_arguments(checkpoint, checkpoint_checksum, transaction, execute=True),
    )
    assert reset.returncode == 0, reset.stderr
    transaction_checksum = _sha256(transaction)
    recovery_environment = harness.env
    if case != "checksum":
        document = json.loads(transaction.read_text())
        if case == "identity":
            document["identity"]["new"]["kubeSystemUid"] = "wrong-transaction-uid"
        elif case == "failed-status":
            document["status"] = "failed"
            document["diagnostic"] = "synthetic"
        elif case == "missing-phases":
            document["phases"] = []
        elif case == "absence":
            document["absence"][0]["passed"] = False
        elif case == "old-identity":
            document["identity"]["old"]["kubeSystemUid"] = "wrong-old-uid"
        elif case == "not-fresh":
            document["identity"]["new"] = dict(document["identity"]["old"])
            recovery_environment = harness.env | {
                "FAKE_NEW_UID": _OLD_UID,
                "FAKE_NEW_CREATED": _OLD_CREATED,
            }
        else:
            document["metadata"]["context"] = "wrong-context"
        transaction.write_text(json.dumps(document, sort_keys=True) + "\n", encoding="utf-8")
        transaction_checksum = _sha256(transaction)
        transaction.with_name(transaction.name + ".sha256").write_text(
            f"{transaction_checksum}  {transaction.name}\n", encoding="utf-8"
        )
    else:
        transaction_checksum = "0" * 64
    recovery = tmp_path / "recovery.json"
    result = _run(
        harness,
        "recovery-evidence",
        "--expected-context",
        _CONTEXT,
        "--checkpoint",
        str(checkpoint),
        "--checkpoint-sha256",
        checkpoint_checksum,
        "--reset-transaction",
        str(transaction),
        "--reset-transaction-sha256",
        transaction_checksum,
        "--output",
        str(recovery),
        env=recovery_environment,
    )
    assert result.returncode == 2
    assert not recovery.exists()


def test_post_start_endpoint_binding_precedes_all_readiness_calls(harness: Harness, tmp_path: Path) -> None:
    checkpoint, checksum = _checkpoint(harness, tmp_path)
    evidence = tmp_path / "transaction.json"
    before = len(_commands(harness))
    result = _run(
        harness,
        *_factory_arguments(checkpoint, checksum, evidence, execute=True),
        env=harness.env | {"FAKE_POST_ENDPOINT": "https://wrong.invalid:6443"},
    )
    assert result.returncode == 2
    commands = _commands(harness)[before:]
    assert not any(row[1:4] == ["get", "--raw", "/readyz"] for row in commands)
    assert not any(len(row) > 1 and row[1] == "wait" for row in commands)
    document = json.loads(evidence.read_text())
    assert document["phases"][-1]["phase"] == "apiReady"
    assert document["status"] == "failed"


def test_adapter_timeout_process_lookup_race_is_durable(harness: Harness, tmp_path: Path) -> None:
    checkpoint, checksum = _checkpoint(harness, tmp_path)
    evidence = tmp_path / "transaction.json"
    result = _run(
        harness,
        *_factory_arguments(checkpoint, checksum, evidence, execute=True),
        env=harness.env | {"FAKE_PURGE_SLEEP": "1"},
        timeout_constants={"PURGE_TIMEOUT_SECONDS": 0.2},
        killpg_process_lookup=True,
    )
    assert result.returncode == 2
    assert "traceback" not in result.stderr.lower()
    document = json.loads(evidence.read_text())
    purge = next(phase for phase in document["phases"] if phase["phase"] == "purge")
    assert purge["exitCode"] == 124
    assert document["status"] == "failed"
    _assert_sidecar(evidence)


def test_hung_kubectl_process_obeys_monotonic_deadline(harness: Harness, tmp_path: Path) -> None:
    checkpoint, checksum = _checkpoint(harness, tmp_path)
    evidence = tmp_path / "transaction.json"
    started = time.monotonic()
    result = _run(
        harness,
        *_factory_arguments(checkpoint, checksum, evidence, execute=True),
        env=harness.env | {"FAKE_READYZ_PROCESS_SLEEP": "5"},
        timeout_constants={"READINESS_TIMEOUT_SECONDS": 0.1},
    )
    assert time.monotonic() - started < 4
    assert result.returncode == 2
    assert "timed out" in result.stderr.lower() or "deadline" in result.stderr.lower()
    assert json.loads(evidence.read_text())["status"] == "failed"
    _assert_sidecar(evidence)


def test_strict_fake_kubectl_rejects_extra_argv(harness: Harness) -> None:
    result = subprocess.run(
        [str(harness.bindir / "kubectl"), "get", "nodes", "--extra"],
        env=harness.env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 97
    assert "UNEXPECTED KUBECTL ARGV" in result.stderr


@pytest.mark.parametrize("command", ["checkpoint", "zero-state", "recovery-evidence"])
def test_all_identity_commands_require_explicit_kubeconfig_before_kubectl(
    harness: Harness, tmp_path: Path, command: str
) -> None:
    environment = dict(harness.env)
    environment.pop("KUBECONFIG")
    output = tmp_path / "output.json"
    if command == "checkpoint":
        arguments = [command, "--expected-context", _CONTEXT, "--output", str(output)]
    elif command == "zero-state":
        arguments = [
            command,
            "--expected-context",
            _CONTEXT,
            "--namespace",
            "nohiki",
            "--evidence-output",
            str(output),
        ]
    else:
        arguments = [
            command,
            "--expected-context",
            _CONTEXT,
            "--checkpoint",
            str(tmp_path / "checkpoint.json"),
            "--checkpoint-sha256",
            "0" * 64,
            "--reset-transaction",
            str(tmp_path / "transaction.json"),
            "--reset-transaction-sha256",
            "0" * 64,
            "--output",
            str(output),
        ]
    before = len(_commands(harness))
    result = _run(harness, *arguments, env=environment)
    assert result.returncode == 2
    assert "KUBECONFIG" in result.stderr
    assert not any(row[0] == "kubectl" for row in _commands(harness)[before:])


@pytest.mark.parametrize("mode", ["checkpoint", "post-start"])
def test_malformed_kubeconfig_url_refuses_without_traceback_and_is_durable_after_start(
    harness: Harness, tmp_path: Path, mode: str
) -> None:
    checkpoint, checksum = _checkpoint(harness, tmp_path)
    if mode == "post-start":
        evidence = tmp_path / "transaction.json"
        result = _run(
            harness,
            *_factory_arguments(checkpoint, checksum, evidence, execute=True),
            env=harness.env | {"FAKE_POST_ENDPOINT": "https://[bad"},
        )
        assert evidence.exists()
        assert json.loads(evidence.read_text())["status"] == "failed"
    else:
        result = _run(
            harness,
            "checkpoint",
            "--expected-context",
            _CONTEXT,
            "--output",
            str(tmp_path / "bad.json"),
            env=harness.env | {"FAKE_ENDPOINT": "https://[bad"},
        )
    assert result.returncode == 2
    assert "malformed" in result.stderr
    assert "traceback" not in result.stderr.lower()


def test_invalid_adapter_utf8_is_replaced_in_durable_failure(harness: Harness, tmp_path: Path) -> None:
    checkpoint, checksum = _checkpoint(harness, tmp_path)
    evidence = tmp_path / "transaction.json"
    result = _run(
        harness,
        *_factory_arguments(checkpoint, checksum, evidence, execute=True),
        env=harness.env | {"FAKE_PURGE_INVALID_UTF8": "1", "FAKE_PURGE_EXIT": "9"},
    )
    assert result.returncode == 2
    assert "traceback" not in result.stderr.lower()
    document = json.loads(evidence.read_text())
    assert document["status"] == "failed"
    assert document["diagnostic"] == "sensitive diagnostic redacted"


def test_failed_identity_and_absence_phases_retain_observations(harness: Harness, tmp_path: Path) -> None:
    checkpoint, checksum = _checkpoint(harness, tmp_path)
    identity_evidence = tmp_path / "identity.json"
    identity_result = _run(
        harness,
        *_factory_arguments(checkpoint, checksum, identity_evidence, execute=True),
        env=harness.env | {"FAKE_NEW_UID": _OLD_UID},
    )
    assert identity_result.returncode == 2
    identity = json.loads(identity_evidence.read_text())["identity"]
    assert identity["old"]["kubeSystemUid"] == _OLD_UID
    assert identity["observed"]["kubeSystemUid"] == _OLD_UID

    harness.log.unlink()
    fresh_harness = harness.env | {"FAKE_RESIDUAL_NAMESPACE": "nohiki-registry"}
    absence_evidence = tmp_path / "absence.json"
    absence_result = _run(
        harness,
        *_factory_arguments(checkpoint, checksum, absence_evidence, execute=True),
        env=fresh_harness,
    )
    assert absence_result.returncode == 2
    absence = json.loads(absence_evidence.read_text())["absence"]
    assert absence == [
        {"check": "namespace nohiki absent", "passed": True},
        {"check": "namespace nohiki-foundation absent", "passed": True},
        {"check": "namespace nohiki-registry absent", "passed": False},
    ]


@pytest.mark.parametrize(
    "command",
    ["factory-reset", "zero-state", "recovery-checkpoint", "recovery-transaction"],
)
def test_evidence_outputs_cannot_alias_immutable_inputs(harness: Harness, tmp_path: Path, command: str) -> None:
    checkpoint, checksum = _checkpoint(harness, tmp_path)
    transaction = tmp_path / "transaction.json"
    transaction.write_text("immutable transaction\n")
    transaction_sidecar = transaction.with_name(transaction.name + ".sha256")
    transaction_sidecar.write_text(f"{'0' * 64} {transaction.name}\n")
    originals = {
        checkpoint: checkpoint.read_bytes(),
        checkpoint.with_name(checkpoint.name + ".sha256"): checkpoint.with_name(
            checkpoint.name + ".sha256"
        ).read_bytes(),
        transaction: transaction.read_bytes(),
        transaction_sidecar: transaction_sidecar.read_bytes(),
    }
    if command == "factory-reset":
        arguments = _factory_arguments(checkpoint, checksum, checkpoint)
    elif command == "zero-state":
        arguments = [
            "zero-state",
            "--expected-context",
            _CONTEXT,
            "--namespace",
            "nohiki",
            "--checkpoint",
            str(checkpoint),
            "--checkpoint-sha256",
            checksum,
            "--evidence-output",
            str(checkpoint),
        ]
    else:
        output = checkpoint if command == "recovery-checkpoint" else transaction
        arguments = [
            "recovery-evidence",
            "--expected-context",
            _CONTEXT,
            "--checkpoint",
            str(checkpoint),
            "--checkpoint-sha256",
            checksum,
            "--reset-transaction",
            str(transaction),
            "--reset-transaction-sha256",
            "0" * 64,
            "--output",
            str(output),
        ]
    before = len(_commands(harness))
    result = _run(harness, *arguments)
    assert result.returncode == 2
    assert "aliases immutable input evidence" in result.stderr
    assert all(path.read_bytes() == payload for path, payload in originals.items())
    assert not any(row[0] in {"purge-adapter", "start-adapter"} for row in _commands(harness)[before:])


def test_cli_and_behavior_ban_dead_surgical_concepts(harness: Harness, tmp_path: Path) -> None:
    result = _run(harness, "reset", "--help")
    assert result.returncode != 0
    checkpoint, checksum = _checkpoint(harness, tmp_path)
    _run(
        harness,
        *_factory_arguments(checkpoint, checksum, tmp_path / "transaction.json", execute=True),
    )
    forbidden = {"delete", "patch", "--force", "sudo", "k3s"}
    assert not any(forbidden.intersection(command) for command in _commands(harness))
    source = _SCRIPT.read_text(encoding="utf-8")
    for concept in (
        "reset_plan",
        "execute_reset",
        "wait_for_delete",
        "CLUSTER_RESOURCE_BY_KIND",
        "IMAGE_REF_RE",
        "load_local_image_names",
        "native_image_refs",
        "images.json",
    ):
        assert concept not in source
    assert "shell=True" not in source
