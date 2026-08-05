"""Fail-closed tests for the seven local Kubernetes lifecycle commands."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shlex
import socket
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import NamedTuple

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_JUSTFILE = _ROOT / "Justfile"
_LIFECYCLE = _ROOT / "infra" / "k8s" / "local" / "lifecycle.sh"
_GATEWAY_PROXY = _ROOT / "infra" / "k8s" / "local" / "gateway_proxy.py"
_RECIPES = {
    "k8s-preflight-local": "preflight",
    "k8s-bootstrap-local": "bootstrap",
    "k8s-publish-local-images": "publish",
    "k8s-reconcile-local": "reconcile",
    "k8s-verify-local": "verify",
    "k8s-diagnostics-local": "diagnostics",
    "k8s-factory-reset-local": "factory-reset",
}


def _recipe_body(source: str, name: str) -> str:
    lines = source.splitlines()
    start = next(
        index for index, line in enumerate(lines) if re.match(rf"^{re.escape(name)}(?:\s+[^:]*)?\s*:(?![=])", line)
    )
    body: list[str] = []
    for line in lines[start + 1 :]:
        if line and not line[0].isspace():
            break
        body.append(line)
    return "\n".join(body)


def test_justfile_exposes_only_the_seven_canonical_kubernetes_lifecycle_commands() -> None:
    source = _JUSTFILE.read_text(encoding="utf-8")
    public = {
        match.group(1)
        for line in source.splitlines()
        if (match := re.match(r"^(k8s-[a-z0-9-]+)(?:\s+[^:]*)?\s*:(?![=])", line))
    }
    assert public == set(_RECIPES)


def test_every_lifecycle_recipe_delegates_to_one_authority_mode() -> None:
    source = _JUSTFILE.read_text(encoding="utf-8")
    for recipe, mode in _RECIPES.items():
        body = _recipe_body(source, recipe)
        calls = [line.strip() for line in body.splitlines() if "infra/k8s/local/lifecycle.sh" in line]
        assert len(calls) == 1, f"{recipe} must have exactly one lifecycle delegation"
        assert re.search(rf"lifecycle\.sh\s+{re.escape(mode)}(?:\s|$)", calls[0]), calls[0]


def test_lifecycle_dispatch_rejects_unknown_modes_before_running_tools(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "called"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for name in ("flux", "git", "helm", "kubectl", "podman", "docker", "uv"):
        tool = fake_bin / name
        tool.write_text(f"#!/bin/sh\ntouch '{marker}'\n", encoding="utf-8")
        tool.chmod(0o755)
    result = subprocess.run(
        ["bash", str(_LIFECYCLE), "not-a-mode"],
        cwd=_ROOT,
        env=os.environ | {"PATH": f"{fake_bin}:{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert not marker.exists(), "unknown lifecycle mode invoked an external tool"


def _load_gateway(monkeypatch: pytest.MonkeyPatch, runtime_dir: Path) -> ModuleType:
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime_dir))
    monkeypatch.delenv("K8S_NAMESPACE", raising=False)
    monkeypatch.delenv("K8S_GATEWAY", raising=False)
    monkeypatch.delenv("K8S_GATEWAY_HOST", raising=False)
    monkeypatch.delenv("K8S_GATEWAY_PORT", raising=False)
    name = f"gateway_proxy_{id(runtime_dir)}"
    spec = importlib.util.spec_from_file_location(name, _GATEWAY_PROXY)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _gateway_document(*, accepted: str = "True", programmed: str = "True") -> dict[str, object]:
    return {
        "metadata": {"name": "nohiki-gateway", "uid": "gateway-uid"},
        "status": {
            "addresses": [{"type": "IPAddress", "value": "10.43.0.80"}],
            "conditions": [
                {"type": "Accepted", "status": accepted},
                {"type": "Programmed", "status": programmed},
            ],
        },
    }


def _route_document(*, accepted: str = "True", resolved: str = "True") -> dict[str, object]:
    return {
        "metadata": {"name": "nohiki-routes"},
        "status": {
            "parents": [
                {
                    "parentRef": {"name": "nohiki-gateway", "namespace": "nohiki"},
                    "conditions": [
                        {"type": "Accepted", "status": accepted},
                        {"type": "ResolvedRefs", "status": resolved},
                    ],
                }
            ]
        },
    }


def _service_document(name: str, *, owned: bool) -> dict[str, object]:
    metadata: dict[str, object] = {"name": name, "namespace": "gateway-system"}
    if owned:
        metadata["labels"] = {
            "gateway.networking.k8s.io/gateway-name": "nohiki-gateway",
            "gateway.networking.k8s.io/gateway-namespace": "nohiki",
        }
    return {
        "metadata": metadata,
        "spec": {
            "clusterIP": "10.43.0.80",
            "ports": [{"name": "http", "port": 80, "appProtocol": "http"}],
        },
    }


def test_gateway_proxy_defaults_to_the_declared_same_origin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    gateway = _load_gateway(monkeypatch, tmp_path)
    assert (gateway.NAMESPACE, gateway.GATEWAY) == ("nohiki", "nohiki-gateway")
    assert (gateway.HOST, gateway.LOCAL_PORT) == ("nohiki.localhost", 8080)
    assert tmp_path / "nohiki-k8s" == gateway.STATE_DIR


@pytest.mark.parametrize(
    (
        "gateway_accepted",
        "gateway_programmed",
        "route_accepted",
        "route_resolved",
        "message",
    ),
    [
        ("False", "True", "True", "True", "Accepted=True and Programmed=True"),
        ("True", "False", "True", "True", "Accepted=True and Programmed=True"),
        ("True", "True", "False", "True", "Accepted=True and ResolvedRefs=True"),
        ("True", "True", "True", "False", "Accepted=True and ResolvedRefs=True"),
    ],
)
def test_gateway_proxy_requires_exact_gateway_and_route_conditions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gateway_accepted: str,
    gateway_programmed: str,
    route_accepted: str,
    route_resolved: str,
    message: str,
) -> None:
    gateway = _load_gateway(monkeypatch, tmp_path)

    def fake_kubectl(*args: str) -> dict[str, object]:
        if "httproute" in args:
            return {"items": [_route_document(accepted=route_accepted, resolved=route_resolved)]}
        return _gateway_document(accepted=gateway_accepted, programmed=gateway_programmed)

    monkeypatch.setattr(gateway, "kubectl_json", fake_kubectl)
    with pytest.raises(RuntimeError, match=re.escape(message)):
        gateway.require_gateway_ready()


def test_gateway_service_discovery_prefers_the_gateway_owned_status_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gateway = _load_gateway(monkeypatch, tmp_path)
    gateway_document = _gateway_document()
    services = {
        "items": [
            _service_document("foreign-address-collision", owned=False),
            _service_document("nohiki-gateway-service", owned=True),
        ]
    }
    monkeypatch.setattr(gateway, "kubectl_json", lambda *_args: services)
    assert gateway.discover_service(gateway_document, {"10.43.0.80"}) == (
        "gateway-system",
        "nohiki-gateway-service",
        80,
    )


def _unused_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _write_fake_kubectl(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env python3
import http.server
import json
import signal
import sys

args = sys.argv[1:]
if "port-forward" in args:
    mapping = next(value for value in args if ":" in value and value[0].isdigit())
    port = int(mapping.split(":", 1)[0])
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            status = (
                200
                if self.path == "/healthz"
                and self.headers.get("Host", "").startswith("nohiki.localhost")
                else 404
            )
            self.send_response(status)
            self.end_headers()
        def log_message(self, *_args):
            pass
    server = http.server.HTTPServer(("127.0.0.1", port), Handler)
    signal.signal(signal.SIGTERM, lambda *_args: sys.exit(0))
    server.serve_forever()
elif "gateway" in args:
    print(json.dumps({"metadata":{"name":"nohiki-gateway","uid":"gateway-uid"},"status":{"addresses":[{"value":"10.43.0.80"}],"conditions":[{"type":"Accepted","status":"True"},{"type":"Programmed","status":"True"}]}}))
elif "httproute" in args:
    print(json.dumps({"items":[{"metadata":{"name":"route"},"status":{"parents":[{"parentRef":{"name":"nohiki-gateway","namespace":"nohiki"},"conditions":[{"type":"Accepted","status":"True"},{"type":"ResolvedRefs","status":"True"}]}]}}]}))
elif "service" in args:
    print(json.dumps({"items":[{"metadata":{"name":"gateway-service","namespace":"gateway-system","labels":{"gateway.networking.k8s.io/gateway-name":"nohiki-gateway","gateway.networking.k8s.io/gateway-namespace":"nohiki"}},"spec":{"clusterIP":"10.43.0.80","ports":[{"name":"http","port":80,"appProtocol":"http"}]}}]}))
else:
    raise SystemExit(64)
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def test_gateway_proxy_tracks_readiness_pid_and_cleanup_with_fake_kubectl(
    tmp_path: Path,
) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_fake_kubectl(fake_bin / "kubectl")
    port = _unused_port()
    env = os.environ | {
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "XDG_RUNTIME_DIR": str(tmp_path / "runtime"),
        "K8S_GATEWAY_PORT": str(port),
    }
    start = subprocess.run(
        [sys.executable, str(_GATEWAY_PROXY), "start"],
        cwd=_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert start.returncode == 0, start.stderr
    assert f"http://nohiki.localhost:{port}" in start.stdout
    state_path = tmp_path / "runtime" / "nohiki-k8s" / "gateway-proxy.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state == {
        "host": "nohiki.localhost",
        "local_port": port,
        "namespace": "gateway-system",
        "pid": state["pid"],
        "service": "gateway-service",
    }
    status = subprocess.run(
        [sys.executable, str(_GATEWAY_PROXY), "status"],
        cwd=_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert status.returncode == 0, status.stderr
    assert f"PID {state['pid']} is ready" in status.stdout
    stop = subprocess.run(
        [sys.executable, str(_GATEWAY_PROXY), "stop"],
        cwd=_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert stop.returncode == 0, stop.stderr
    assert not state_path.exists()


def test_gateway_proxy_rejects_an_unmanaged_port_conflict(
    tmp_path: Path,
) -> None:
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        port = occupied.getsockname()[1]
        result = subprocess.run(
            [sys.executable, str(_GATEWAY_PROXY), "start"],
            cwd=_ROOT,
            env=os.environ
            | {
                "XDG_RUNTIME_DIR": str(tmp_path),
                "K8S_GATEWAY_PORT": str(port),
            },
            capture_output=True,
            text=True,
            check=False,
        )
    assert result.returncode != 0
    assert f"localhost:{port} is occupied by an unmanaged process" in result.stderr


def test_gateway_proxy_failed_readiness_stops_and_removes_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gateway = _load_gateway(monkeypatch, tmp_path)
    process = type(
        "FakeProcess",
        (),
        {"pid": 4242, "poll": lambda _self: None},
    )()
    stopped: list[bool] = []
    monkeypatch.setattr(gateway, "port_open", lambda: False)
    monkeypatch.setattr(gateway, "require_gateway_ready", lambda: (_gateway_document(), {"10.43.0.80"}))
    monkeypatch.setattr(
        gateway,
        "discover_service",
        lambda *_args: ("gateway-system", "gateway-service", 80),
    )
    monkeypatch.setattr(gateway, "_POPEN_TRUSTED", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(gateway, "http_ready", lambda: False)
    monkeypatch.setattr(gateway.time, "sleep", lambda _seconds: None)

    def fake_stop() -> None:
        stopped.append(True)
        gateway.STATE_FILE.unlink(missing_ok=True)

    monkeypatch.setattr(gateway, "stop", fake_stop)
    with pytest.raises(RuntimeError, match="did not become HTTP-ready"):
        gateway.start()
    assert stopped == [True]
    assert not gateway.STATE_FILE.exists()


def _write_executable(path: Path, source: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    path.chmod(0o755)


def _lifecycle_sandbox(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    root = tmp_path / "repo"
    lifecycle = root / "infra" / "k8s" / "local" / "lifecycle.sh"
    lifecycle.parent.mkdir(parents=True)
    lifecycle.write_text(_LIFECYCLE.read_text(encoding="utf-8"), encoding="utf-8")
    lifecycle.chmod(0o755)
    log = tmp_path / "calls.log"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    common = """#!/bin/sh
printf '%s %s\\n' "$(basename "$0")" "$*" >> "$CALL_LOG"
exit 0
"""
    for name in ("flux", "helm", "kustomize"):
        _write_executable(fake_bin / name, common)
    _write_executable(
        fake_bin / "uv",
        """#!/bin/sh
printf 'uv %s\\n' "$*" >> "$CALL_LOG"
case "$*" in
  *'validate_local_secret_sources.py'*)
    if [ "${SECRET_VALIDATION_FAIL:-0}" = 1 ]; then exit 73; fi ;;
  *'python -m health_check.acceptance.live_cluster_cdc'*)
    while [ "$#" -gt 0 ] && [ "$1" != python ]; do shift; done
    [ "$#" -gt 0 ] || exit 76
    shift
    PYTHONPATH="$PWD/scripts/util/health_check/src" python "$@"
    exit $? ;;
  *'health-check inventory'*)
    printf 'health-evidence %s\\n' "$CDC_ACCEPTANCE_EVIDENCE" >> "$CALL_LOG" ;;
esac
exit 0
""",
    )
    _write_executable(
        fake_bin / "git",
        """#!/bin/sh
printf 'git %s\\n' "$*" >> "$CALL_LOG"
case "$*" in
  'branch --show-current') printf '%s\\n' "$NOHIKI_RUNTIME_CONTROL_BRANCH" ;;
  'rev-parse HEAD')
    if [ -f "$GIT_COMMITTED" ]; then
      printf '%s\\n' 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'
    else
      printf '%s\\n' "$NOHIKI_REVIEWED_TOPIC_SHA"
    fi ;;
  'ls-remote --heads origin '*)
    printf '%s\\t%s\\n' "$NOHIKI_REVIEWED_TOPIC_SHA" "refs/heads/$NOHIKI_RUNTIME_CONTROL_BRANCH" ;;
  'diff --name-only HEAD'|'ls-files --others --exclude-standard') ;;
  'hash-object '*) printf '%064d\\n' 0 ;;
  'diff --cached --name-only') printf '%s\\n' 'infra/k8s/gitops/platform/local/image-digests.values.yaml' ;;
  'commit '*) : > "$GIT_COMMITTED" ;;
  'diff-tree '*) printf '%s\\n' 'infra/k8s/gitops/platform/local/image-digests.values.yaml' ;;
esac
""",
    )
    _write_executable(
        fake_bin / "kubectl",
        """#!/bin/sh
printf 'kubectl %s\\n' "$*" >> "$CALL_LOG"
case "$*" in
  *'config current-context'*) printf '%s\\n' "$K8S_LOCAL_CONTEXT" ;;
  *'--for=create kustomization/registry'*)
    if [ "${REGISTRY_CREATE_WAIT_FAIL:-0}" = 1 ]; then exit 70; fi ;;
  *'--for=condition=Ready=True kustomization/registry'*)
    if [ "${REGISTRY_READY_WAIT_FAIL:-0}" = 1 ]; then exit 71; fi ;;
  *'.status.artifact.revision'*) printf '%s\\n' 'main@sha1:abc' ;;
  *'.metadata.generation'*) printf '%s\\n' '1' ;;
  *'.status.observedGeneration'*) printf '%s\\n' '1' ;;
  *'.status.lastAppliedRevision'*) printf '%s\\n' 'main@sha1:abc' ;;
esac
""",
    )
    _write_executable(
        root / "infra" / "k8s" / "gitops" / "install" / "bootstrap.sh",
        """#!/bin/sh
printf 'bootstrap %s\\n' "$*" >> "$CALL_LOG"
if [ "${BOOTSTRAP_PARTIAL:-0}" = 1 ] && [ "$1" = --validate ]; then exit 42; fi
""",
    )
    for relative in (
        "scripts/infra/validate_local_secret_sources.py",
        "infra/k8s/local/image_foundation.py",
        "infra/k8s/local/gateway_proxy.py",
        "scripts/infra/verify-k8s-jobs.py",
        "infra/k8s/scripts/verify-migration-heads.py",
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# synthetic lifecycle helper\n", encoding="utf-8")
    adapter = root / "scripts" / "util" / "health_check" / "src" / "health_check" / "acceptance"
    adapter.mkdir(parents=True)
    adapter.parent.joinpath("__init__.py").write_text("", encoding="utf-8")
    adapter.joinpath("__init__.py").write_text("", encoding="utf-8")
    adapter.joinpath("live_cluster_cdc.py").write_text(
        """from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--namespace", required=True)
parser.add_argument("--evidence", type=Path, required=True)
args = parser.parse_args()
with Path(os.environ["CALL_LOG"]).open("a", encoding="utf-8") as call_log:
    call_log.write(
        f"adapter --namespace {args.namespace} --evidence {args.evidence} "
        f"CDC_ACCEPTANCE_EVIDENCE={os.environ.get('CDC_ACCEPTANCE_EVIDENCE', '')}\\n"
    )
if os.environ.get("CDC_ADAPTER_FAIL") == "1":
    raise SystemExit(74)
args.evidence.parent.mkdir(parents=True, exist_ok=True)
args.evidence.write_text(
    json.dumps({"check": "live-cluster-cdc", "status": "passed"}) + "\\n",
    encoding="utf-8",
)
""",
        encoding="utf-8",
    )
    _write_executable(
        root / "infra" / "k8s" / "local" / "cluster_reset.py",
        '#!/bin/sh\nprintf \'factory-reset %s\\n\' "$*" >> "$CALL_LOG"\n',
    )
    (root / "infra" / "k8s" / "gitops" / "clusters" / "local").mkdir(parents=True)
    (root / "infra" / "k8s" / "helm-foundation").mkdir(parents=True)
    (root / "infra" / "k8s" / "gitops" / "platform" / "local").mkdir(parents=True)
    secrets_dir = tmp_path / "external-secrets"
    secrets_dir.mkdir(mode=0o700)
    env = os.environ | {
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "CALL_LOG": str(log),
        "K8S_LOCAL_CONTEXT": "k3s-nohiki-test",
        "K3S_REGISTRIES_CONFIG": str(tmp_path / "registries.yaml"),
        "K8S_EVIDENCE_DIR": str(tmp_path / "evidence"),
        "NOHIKI_LOCAL_SECRETS_DIR": str(secrets_dir),
        "NOHIKI_RUNTIME_CONTROL_BRANCH": "runtime-control/local/focused-test",
        "NOHIKI_REVIEWED_TOPIC_SHA": "a" * 40,
        "GIT_COMMITTED": str(tmp_path / "git-committed"),
    }
    return lifecycle, log, env


def _run_lifecycle(lifecycle: Path, mode: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(lifecycle), mode],
        cwd=lifecycle.parents[3],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _new_calls(log: Path, offset: int = 0) -> list[str]:
    if not log.exists():
        return []
    return log.read_text(encoding="utf-8").splitlines()[offset:]


class _LifecycleProbe(NamedTuple):
    mode: str
    returncode: int
    stderr: str
    calls: tuple[str, ...]


@pytest.fixture(scope="module")
def lifecycle_probes(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[_LifecycleProbe, ...]:
    """Run the shared happy-path lifecycle matrix once."""
    lifecycle, log, env = _lifecycle_sandbox(tmp_path_factory.mktemp("lifecycle-probes"))
    probes: list[_LifecycleProbe] = []
    for mode in ("preflight", "bootstrap", "publish", "reconcile", "diagnostics"):
        before = len(_new_calls(log))
        result = _run_lifecycle(lifecycle, mode, env)
        probes.append(_LifecycleProbe(mode, result.returncode, result.stderr, tuple(_new_calls(log, before))))
    return tuple(probes)


def _probe(probes: tuple[_LifecycleProbe, ...], mode: str) -> _LifecycleProbe:
    return next(probe for probe in probes if probe.mode == mode)


_KUBECTL_MUTATING_VERBS = frozenset({"apply", "create", "delete", "edit", "patch", "replace", "rollout"})


def _is_mutating_kubectl(call: str) -> bool:
    tokens = shlex.split(call)
    return bool(tokens and tokens[0] == "kubectl" and not _KUBECTL_MUTATING_VERBS.isdisjoint(tokens[1:]))


@pytest.mark.parametrize(
    "call",
    [
        "kubectl apply -f manifest.yaml",
        "kubectl create namespace nohiki",
        "kubectl -n nohiki delete pod stale",
        "kubectl --context local patch deployment api",
    ],
)
def test_kubectl_mutation_detection_catches_immediate_and_option_prefixed_verbs(
    call: str,
) -> None:
    assert _is_mutating_kubectl(call)


@pytest.mark.parametrize(
    "call",
    [
        "kubectl -n flux-system wait --for=create kustomization/registry",
        "kubectl get pods",
    ],
)
def test_kubectl_mutation_detection_ignores_observational_calls(call: str) -> None:
    assert not _is_mutating_kubectl(call)


@pytest.mark.parametrize(("mode", "expected_count"), [("preflight", 1), ("bootstrap", 2)])
def test_secret_validation_receives_the_exact_absolute_source_directory(
    lifecycle_probes: tuple[_LifecycleProbe, ...],
    mode: str,
    expected_count: int,
) -> None:
    probe = _probe(lifecycle_probes, mode)
    assert probe.returncode == 0, probe.stderr
    secrets_dir = Path(probe.calls[0].split(" --secrets-dir ", 1)[1])
    expected = f"uv run python scripts/infra/validate_local_secret_sources.py --secrets-dir {secrets_dir}"
    assert probe.calls.count(expected) == expected_count
    assert probe.calls[0] == expected
    if mode == "bootstrap":
        assert probe.calls.index(expected, 1) < probe.calls.index("bootstrap --execute")


@pytest.mark.parametrize("mode", ["preflight", "bootstrap"])
@pytest.mark.parametrize(
    ("source", "message"),
    [
        ("", "NOHIKI_LOCAL_SECRETS_DIR is required"),
        ("relative/secrets", "NOHIKI_LOCAL_SECRETS_DIR must be an absolute path"),
    ],
)
def test_missing_or_relative_secret_source_fails_before_any_external_call(
    tmp_path: Path,
    mode: str,
    source: str,
    message: str,
) -> None:
    lifecycle, log, env = _lifecycle_sandbox(tmp_path)
    result = _run_lifecycle(
        lifecycle,
        mode,
        env | {"NOHIKI_LOCAL_SECRETS_DIR": source},
    )
    assert result.returncode != 0
    assert message in result.stderr
    assert _new_calls(log) == []


@pytest.mark.parametrize("mode", ["preflight", "bootstrap"])
def test_invalid_secret_source_stops_before_git_cluster_or_registry_mutation(
    tmp_path: Path,
    mode: str,
) -> None:
    lifecycle, log, env = _lifecycle_sandbox(tmp_path)
    missing = tmp_path / "missing-secret-source"
    result = _run_lifecycle(
        lifecycle,
        mode,
        env
        | {
            "NOHIKI_LOCAL_SECRETS_DIR": str(missing),
            "SECRET_VALIDATION_FAIL": "1",
        },
    )
    assert result.returncode == 73
    assert _new_calls(log) == [f"uv run python scripts/infra/validate_local_secret_sources.py --secrets-dir {missing}"]


def test_preflight_and_diagnostics_are_read_only_and_redacted_with_fake_tools(
    lifecycle_probes: tuple[_LifecycleProbe, ...],
) -> None:
    for mode in ("preflight", "diagnostics"):
        calls = _probe(lifecycle_probes, mode).calls
        joined = "\n".join(calls).lower()
        assert not re.search(
            r"\b(apply|create|delete|patch|replace|edit|rollout|publish|push)\b",
            joined,
        ), calls
        assert not re.search(r"\b(secret|secretlist|\.data|stringdata)\b", joined), calls
    diagnostics = "\n".join(_probe(lifecycle_probes, "diagnostics").calls).lower()
    assert "health-check inventory --target k8s --json" in diagnostics
    assert "get gateway,httproute" in diagnostics
    health_evidence = [
        call.removeprefix("health-evidence ")
        for mode in ("preflight", "diagnostics")
        for call in _probe(lifecycle_probes, mode).calls
        if call.startswith("health-evidence ")
    ]
    assert len(health_evidence) == 2
    assert all(path.endswith("/evidence/live-cdc.json") for path in health_evidence)


def test_publish_is_the_only_build_and_publish_authority(
    lifecycle_probes: tuple[_LifecycleProbe, ...],
) -> None:
    calls_by_mode = {probe.mode: probe.calls for probe in lifecycle_probes}
    for probe in lifecycle_probes:
        assert probe.returncode == 0, f"{probe.mode}: {probe.stderr}"
    assert any("image_foundation.py build" in call for call in calls_by_mode["publish"])
    assert any("image_foundation.py publish" in call for call in calls_by_mode["publish"])
    assert any("image_foundation.py render-values" in call for call in calls_by_mode["publish"])
    publish_calls = calls_by_mode["publish"]
    create_wait = "kubectl -n flux-system wait --for=create kustomization/registry --timeout=20m"
    ready_wait = "kubectl -n flux-system wait --for=condition=Ready=True kustomization/registry --timeout=20m"
    build = "uv run python infra/k8s/local/image_foundation.py build --runtime docker"
    assert publish_calls.index(create_wait) < publish_calls.index(ready_wait)
    assert publish_calls.index(ready_wait) < publish_calls.index(build)
    assert not any(call.startswith("flux reconcile ") or _is_mutating_kubectl(call) for call in publish_calls), (
        publish_calls
    )
    artifact = "infra/k8s/gitops/platform/local/image-digests.values.yaml"
    assert f"git add -- {artifact}" in publish_calls
    assert f"git commit -m chore(kind): publish local image digests -- {artifact}" in publish_calls
    assert not any(call.startswith("git push ") for call in publish_calls)
    for mode, calls in calls_by_mode.items():
        if mode == "publish":
            continue
        assert not any(
            re.search(
                r"image_foundation\.py (?:build|publish)|\b(?:docker|podman) (?:build|push)\b|"
                r"git (?:add|commit|push)",
                call,
            )
            for call in calls
        ), f"{mode} crossed publish authority: {calls}"


def test_publish_rejects_an_unapproved_branch_before_build(
    tmp_path: Path,
) -> None:
    lifecycle, log, env = _lifecycle_sandbox(tmp_path)
    result = _run_lifecycle(
        lifecycle,
        "publish",
        env | {"NOHIKI_RUNTIME_CONTROL_BRANCH": "main"},
    )
    assert result.returncode != 0
    assert "not an approved local runtime-control branch" in result.stderr
    assert not any("image_foundation.py build" in call for call in _new_calls(log))


@pytest.mark.parametrize(
    ("failure", "returncode", "expected_calls"),
    [
        (
            "REGISTRY_CREATE_WAIT_FAIL",
            70,
            [
                "kubectl config current-context",
                "kubectl -n flux-system wait --for=create kustomization/registry --timeout=20m",
            ],
        ),
        (
            "REGISTRY_READY_WAIT_FAIL",
            71,
            [
                "kubectl config current-context",
                "kubectl -n flux-system wait --for=create kustomization/registry --timeout=20m",
                "kubectl -n flux-system wait --for=condition=Ready=True kustomization/registry --timeout=20m",
            ],
        ),
    ],
)
def test_publish_registry_wait_failure_stops_before_build_or_mutation(
    tmp_path: Path,
    failure: str,
    returncode: int,
    expected_calls: list[str],
) -> None:
    lifecycle, log, env = _lifecycle_sandbox(tmp_path)
    result = _run_lifecycle(lifecycle, "publish", env | {failure: "1"})
    assert result.returncode == returncode
    assert _new_calls(log) == expected_calls
    assert not (
        tmp_path / "repo" / "infra" / "k8s" / "gitops" / "platform" / "local" / "image-digests.values.yaml"
    ).exists()


def test_bootstrap_rejects_partial_state_before_execute(
    tmp_path: Path,
) -> None:
    lifecycle, log, env = _lifecycle_sandbox(tmp_path)
    result = _run_lifecycle(lifecycle, "bootstrap", env | {"BOOTSTRAP_PARTIAL": "1"})
    assert result.returncode == 42
    calls = _new_calls(log)
    assert "bootstrap --validate" in calls
    assert "bootstrap --execute" not in calls


def test_reconcile_has_exact_ordered_flux_authority_and_second_run_is_observational(
    tmp_path: Path,
) -> None:
    lifecycle, log, env = _lifecycle_sandbox(tmp_path)
    first = _run_lifecycle(lifecycle, "reconcile", env)
    assert first.returncode == 0, first.stderr
    first_calls = _new_calls(log)
    second = _run_lifecycle(lifecycle, "reconcile", env)
    assert second.returncode == 0, second.stderr
    second_calls = _new_calls(log, len(first_calls))
    assert second_calls == first_calls
    assert first_calls == [
        "kubectl config current-context",
        "flux reconcile source git flux-system --namespace flux-system",
        "flux reconcile kustomization flux-system --namespace flux-system",
        "kubectl -n flux-system wait --for=create kustomization/flux-system --timeout=20m",
        "kubectl -n flux-system wait --for=condition=Ready=True kustomization/flux-system --timeout=20m",
        "flux reconcile kustomization gateway-api-crds --namespace flux-system",
        "kubectl -n flux-system wait --for=create kustomization/gateway-api-crds --timeout=20m",
        "kubectl -n flux-system wait --for=condition=Ready=True kustomization/gateway-api-crds --timeout=20m",
        "flux reconcile kustomization registry --namespace flux-system",
        "kubectl -n flux-system wait --for=create kustomization/registry --timeout=20m",
        "kubectl -n flux-system wait --for=condition=Ready=True kustomization/registry --timeout=20m",
        "flux reconcile kustomization infrastructure --namespace flux-system",
        "kubectl -n flux-system wait --for=create kustomization/infrastructure --timeout=20m",
        "kubectl -n flux-system wait --for=condition=Ready=True kustomization/infrastructure --timeout=20m",
        "flux reconcile kustomization runtime-secrets --namespace flux-system",
        "kubectl -n flux-system wait --for=create kustomization/runtime-secrets --timeout=20m",
        "kubectl -n flux-system wait --for=condition=Ready=True kustomization/runtime-secrets --timeout=20m",
        "flux reconcile kustomization platform --namespace flux-system",
        "kubectl -n flux-system wait --for=create kustomization/platform --timeout=20m",
        "kubectl -n flux-system wait --for=condition=Ready=True kustomization/platform --timeout=20m",
        "flux reconcile kustomization observability --namespace flux-system",
        "kubectl -n flux-system wait --for=create kustomization/observability --timeout=20m",
        "kubectl -n flux-system wait --for=condition=Ready=True kustomization/observability --timeout=20m",
        "flux reconcile kustomization health-verification --namespace flux-system",
        "kubectl -n flux-system wait --for=create kustomization/health-verification --timeout=20m",
        "kubectl -n flux-system wait --for=condition=Ready=True kustomization/health-verification --timeout=20m",
        "flux reconcile kustomization api-verification --namespace flux-system",
        "kubectl -n flux-system wait --for=create kustomization/api-verification --timeout=20m",
        "kubectl -n flux-system wait --for=condition=Ready=True kustomization/api-verification --timeout=20m",
        "flux reconcile kustomization playwright-verification --namespace flux-system",
        "kubectl -n flux-system wait --for=create kustomization/playwright-verification --timeout=20m",
        "kubectl -n flux-system wait --for=condition=Ready=True kustomization/playwright-verification --timeout=20m",
    ]
    forbidden = re.compile(
        r"git (?:add|commit|checkout|switch|push)|\b(?:build|publish|push)\b|"
        r"bootstrap --execute|namespace .*reset|database .*reset",
        re.IGNORECASE,
    )
    assert not any(forbidden.search(call) or _is_mutating_kubectl(call) for call in first_calls)
    assert not (tmp_path / "evidence").exists()


def test_verify_invokes_every_declared_gate_and_managed_proxy_cleanup(
    tmp_path: Path,
) -> None:
    lifecycle, log, env = _lifecycle_sandbox(tmp_path)
    result = _run_lifecycle(lifecycle, "verify", env)
    assert result.returncode == 0, result.stderr
    calls = _new_calls(log)
    joined = "\n".join(calls)
    required = (
        "health_check.acceptance.live_cluster_cdc",
        "live-cdc.json",
        "migration-truth",
        "verify-migration-heads.py",
        "kustomization health-verification",
        "kustomization api-verification",
        "kustomization playwright-verification",
        "gateway_proxy.py start",
        "verify-k8s-jobs.py --namespace nohiki-verification",
        "--api-job nohiki-api-verification-v1",
        "--playwright-job nohiki-playwright-verification-v1",
        "image_foundation.py status",
        "image_foundation.py verify-pulls",
        "gateway_proxy.py stop",
    )
    for gate in required:
        assert gate in joined, f"verify omitted gate {gate!r}: {calls}"

    evidence = tmp_path / "evidence" / "live-cdc.json"
    adapter_command = (
        "uv run --no-sync --project scripts/util/health_check python -m "
        f"health_check.acceptance.live_cluster_cdc --namespace nohiki --evidence {evidence}"
    )
    adapter_call = f"adapter --namespace nohiki --evidence {evidence} CDC_ACCEPTANCE_EVIDENCE={evidence}"
    assert calls.count(adapter_command) == 1
    assert calls.count(adapter_call) == 1
    assert evidence.is_file()
    assert joined.index("gateway_proxy.py start") < joined.index(adapter_command)
    assert joined.index(adapter_command) < joined.index("migration-truth")
    assert joined.index("gateway_proxy.py start") < joined.index("verify-k8s-jobs.py")
    assert joined.rindex("gateway_proxy.py stop") > joined.index("verify-k8s-jobs.py")


def test_verify_fails_closed_when_live_cdc_adapter_fails(
    tmp_path: Path,
) -> None:
    lifecycle, log, env = _lifecycle_sandbox(tmp_path)
    result = _run_lifecycle(lifecycle, "verify", env | {"CDC_ADAPTER_FAIL": "1"})
    assert result.returncode == 74
    calls = _new_calls(log)
    assert any(call.startswith("adapter --namespace nohiki --evidence ") for call in calls)
    assert not any("migration-truth" in call for call in calls)
    assert any("gateway_proxy.py stop" in call for call in calls)
    assert not (tmp_path / "evidence" / "live-cdc.json").exists()


def test_verify_fails_closed_when_live_cdc_adapter_is_absent(
    tmp_path: Path,
) -> None:
    lifecycle, log, env = _lifecycle_sandbox(tmp_path)
    adapter = (
        lifecycle.parents[3]
        / "scripts"
        / "util"
        / "health_check"
        / "src"
        / "health_check"
        / "acceptance"
        / "live_cluster_cdc.py"
    )
    adapter.unlink()
    result = _run_lifecycle(lifecycle, "verify", env)
    assert result.returncode != 0
    assert "required lifecycle helper is absent" in result.stderr
    assert not any("health_check.acceptance.live_cluster_cdc" in call for call in _new_calls(log))
