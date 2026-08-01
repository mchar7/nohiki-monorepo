#!/usr/bin/env python3
"""Independent read-only observation for disposable Nohiki kind clusters."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Never

CLUSTER = "nohiki"
CONTEXT = "kind-nohiki"
BRANCH = re.compile(r"runtime-control/local/[a-z0-9][a-z0-9._-]*\Z")
SHA = re.compile(r"[0-9a-f]{40}\Z")
PHASE = re.compile(r"[a-z0-9][a-z0-9._/-]*\Z")
NODE_KEYS = {"arpIgnoreAll", "arpIgnoreDefault", "containerId", "hostsSha256", "name", "startTime"}
SECRET_KEYS = {"keyNames", "name", "namespace", "resourceVersion", "sourceFileSha256", "type", "uid"}
FORBIDDEN_KEYS = {"data", "identity", "password", "privateKey", "secret", "stringData", "token", "value"}
SECRET_METADATA_FIELD_COUNT = 4

type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]


class ObservationError(RuntimeError):
    """Report a closed-surface observation contract failure."""


def _fail(message: str, *, cause: BaseException | None = None) -> Never:
    if cause is None:
        raise ObservationError(message)
    raise ObservationError(message) from cause


def canonical_bytes(value: object) -> bytes:
    """Encode one value as canonical newline-terminated JSON."""
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha256_bytes(value: bytes) -> str:
    """Return the lowercase SHA-256 digest of bytes."""
    return hashlib.sha256(value).hexdigest()


def read_canonical_json(path: Path) -> tuple[dict[str, Any], bytes]:
    """Read one canonical JSON object through a non-symlink descriptor."""
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        _fail(f"input must be an absolute regular non-symlink file: {path}")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            data = stream.read()
    finally:
        os.close(descriptor)
    try:
        value = json.loads(data)
    except json.JSONDecodeError as error:
        _fail(f"input is not JSON: {path}", cause=error)
    if not isinstance(value, dict) or canonical_bytes(value) != data:
        _fail(f"input is not canonical JSON: {path}")
    return value, data


def write_exclusive(path: Path, value: object) -> None:
    """Create one mode-0600 canonical JSON file without replacement."""
    if not path.is_absolute() or path.exists() or path.is_symlink():
        _fail("output and its sidecar must be absent absolute paths")
    if not path.parent.is_dir():
        _fail("output parent must already exist")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        os.write(descriptor, canonical_bytes(value))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def run_readonly(argv: Sequence[str], timeout: int = 15) -> subprocess.CompletedProcess[str]:
    """Run one command through the closed read-only executable table."""
    if not argv:
        _fail("read-only command cannot be empty")
    executable, *arguments = argv
    if executable not in {"kind", "podman", "kubectl"}:
        _fail(f"executable is outside the read-only command table: {executable}")
    executable_path = shutil.which(executable)
    if executable_path is None:
        _fail(f"read-only executable is unavailable: {executable}")
    return subprocess.run(  # noqa: S603 - executable and argv passed the closed command-table validator.
        [executable_path, *arguments],
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


def require_json(argv: Sequence[str], timeout: int = 15) -> JsonValue:
    """Run a read-only command and decode its JSON response."""
    result = run_readonly(argv, timeout)
    if result.returncode != 0:
        _fail(f"read-only command failed ({result.returncode}): {' '.join(argv)}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        _fail(f"read-only command returned malformed JSON: {' '.join(argv)}", cause=error)


def reject_secret_material(value: object, path: str = "$") -> None:
    """Reject recursively any field that could contain secret material."""
    if isinstance(value, dict):
        for key, child in value.items():
            if key in FORBIDDEN_KEYS or re.search(r"(?:private|credential|agekey)", key, re.IGNORECASE):
                _fail(f"secret-bearing key is prohibited at {path}.{key}")
            reject_secret_material(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_secret_material(child, f"{path}[{index}]")


def _validate_nodes(nodes: object) -> None:
    if not isinstance(nodes, list):
        _fail("runner measurement nodes must be an array")
    for node in nodes:
        if not isinstance(node, dict) or set(node) != NODE_KEYS:
            _fail("runner measurement node keys are not closed")
        if not all(isinstance(node[key], str) for key in NODE_KEYS):
            _fail("runner measurement node values must be strings")


def _validate_secrets(secrets: object) -> None:
    if not isinstance(secrets, list):
        _fail("runner measurement secrets must be an array")
    for secret in secrets:
        if not isinstance(secret, dict) or set(secret) != SECRET_KEYS:
            _fail("runner measurement Secret keys are not closed")
        key_names = secret["keyNames"]
        if not isinstance(key_names, list) or not all(isinstance(key, str) for key in key_names):
            _fail("runner measurement Secret keyNames must be strings")


def validate_measurements(document: dict[str, Any], attempt: int) -> None:
    """Validate the closed measurement schema and reject secret material."""
    expected = {
        "apiVersion",
        "attempt",
        "cluster",
        "kubeconfig",
        "kind",
        "lockSha256",
        "network",
        "nodes",
        "schemaVersion",
        "secrets",
        "source",
        "storage",
    }
    if set(document) != expected:
        _fail("runner measurement top-level keys are not closed")
    if (
        document["apiVersion"] != "nohiki.io/v1alpha1"
        or document["kind"] != "KindctlMeasurements"
        or document["schemaVersion"] != 1
    ):
        _fail("runner measurement schema identity is invalid")
    if document["attempt"] != attempt:
        _fail("runner measurement attempt does not match observer attempt")
    cluster = document["cluster"]
    if cluster.get("name") != CLUSTER or cluster.get("context") != CONTEXT or not cluster.get("uid"):
        _fail("runner measurement cluster binding is invalid")
    if not re.fullmatch(r"[0-9a-f]{64}", str(document["lockSha256"])):
        _fail("runner measurement lock hash is invalid")
    _validate_nodes(document["nodes"])
    _validate_secrets(document["secrets"])
    reject_secret_material(document)


def validate_sidecar(sidecar: dict[str, Any], measurements: dict[str, Any], measurement_bytes: bytes) -> None:
    """Validate that a sidecar binds the exact measurement bytes and identity."""
    if set(sidecar) != {"attempt", "clusterUid", "lockSha256", "sha256"}:
        _fail("runner measurement sidecar keys are not closed")
    expected = {
        "attempt": measurements["attempt"],
        "clusterUid": measurements["cluster"]["uid"],
        "lockSha256": measurements["lockSha256"],
        "sha256": sha256_bytes(measurement_bytes),
    }
    if sidecar != expected:
        _fail("runner measurement sidecar does not bind the measurement")


def validate_kubeconfig(measurements: dict[str, Any], *, must_exist: bool) -> Path:
    """Validate the measured kubeconfig identity, allowing post-delete absence."""
    binding = measurements["kubeconfig"]
    if set(binding) != {"device", "inode", "mode", "owner", "path"}:
        _fail("kubeconfig binding keys are not closed")
    path = Path(str(binding["path"]))
    if not path.is_absolute() or path.is_symlink():
        _fail("measured kubeconfig path is invalid")
    if not path.exists():
        if must_exist:
            _fail("measured kubeconfig is absent while the cluster exists")
        return path
    if not path.is_file():
        _fail("measured kubeconfig is not a regular file")
    metadata = path.stat()
    actual = {
        "device": metadata.st_dev,
        "inode": metadata.st_ino,
        "mode": f"{stat.S_IMODE(metadata.st_mode):04o}",
        "owner": metadata.st_uid,
        "path": str(path),
    }
    if actual != binding or binding["owner"] != os.getuid() or binding["mode"] != "0600":
        _fail("measured kubeconfig identity changed")
    return path


def kind_clusters() -> list[str]:
    """Return the complete kind cluster-name inventory."""
    result = run_readonly(("kind", "get", "clusters"))
    if result.returncode != 0:
        _fail("kind cluster inventory failed")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def podman_inventory(
    measured_nodes: list[dict[str, Any]], *, kind_present: bool
) -> tuple[list[dict[str, Any]], list[str], list[str], list[str]]:
    """Collect Nohiki Podman resources and contradict changed node identity."""
    inspected: list[dict[str, Any]] = []
    if kind_present:
        node_result = run_readonly(("kind", "get", "nodes", "--name", CLUSTER))
        if node_result.returncode != 0:
            _fail("kind node inventory failed")
        observed_names = [line.strip() for line in node_result.stdout.splitlines() if line.strip()]
        expected_names = [str(node["name"]) for node in measured_nodes]
        if observed_names != expected_names:
            _fail("kind node inventory contradicts runner measurements")
        for measurement in measured_nodes:
            document = require_json(("podman", "inspect", "--type", "container", str(measurement["name"])))
            container = document[0] if isinstance(document, list) else document
            if (
                container.get("Id") != measurement["containerId"]
                or container.get("State", {}).get("StartedAt") != measurement["startTime"]
            ):
                _fail(f"node identity changed: {measurement['name']}")
            inspected.append(container)
    containers_result = run_readonly(
        ("podman", "ps", "-a", "--filter", f"label=io.x-k8s.kind.cluster={CLUSTER}", "--format", "json")
    )
    volumes_result = run_readonly(
        ("podman", "volume", "ls", "--filter", f"label=io.x-k8s.kind.cluster={CLUSTER}", "--format", "json")
    )
    network_result = run_readonly(("podman", "network", "inspect", "kind"))
    containers = (
        []
        if containers_result.returncode != 0 or not containers_result.stdout.strip()
        else json.loads(containers_result.stdout)
    )
    volumes = (
        [] if volumes_result.returncode != 0 or not volumes_result.stdout.strip() else json.loads(volumes_result.stdout)
    )
    network_attachments: list[str] = []
    if network_result.returncode == 0:
        network_documents = json.loads(network_result.stdout)
        network = (
            network_documents[0] if isinstance(network_documents, list) and network_documents else network_documents
        )
        endpoints = network.get("containers", network.get("Containers", {})) if isinstance(network, dict) else {}
        if isinstance(endpoints, dict):
            network_attachments = sorted(
                str(value.get("name", value.get("Name", identifier))) if isinstance(value, dict) else str(identifier)
                for identifier, value in endpoints.items()
                if CLUSTER in str(value) or CLUSTER in str(identifier)
            )
    container_names = sorted(
        str(item.get("Names", item.get("Id", "")))
        for item in (containers if isinstance(containers, list) else [containers])
    )
    volume_names = sorted(str(item.get("Name", "")) for item in (volumes if isinstance(volumes, list) else [volumes]))
    return (
        inspected,
        [name for name in container_names if name],
        [name for name in volume_names if name],
        network_attachments,
    )


def kubernetes_observation(
    kubeconfig: Path, measurements: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Collect Kubernetes state using only fixed metadata-safe queries."""
    prefix = ("kubectl", "--kubeconfig", str(kubeconfig))
    namespace = require_json((*prefix, "get", "namespace", "kube-system", "-o", "json"))
    nodes_document = require_json((*prefix, "get", "nodes", "-o", "json"))
    observed_nodes = []
    by_name = {str(item["name"]): item for item in measurements["nodes"]}
    for node in nodes_document.get("items", []):
        name = str(node.get("metadata", {}).get("name", ""))
        measured = by_name.get(name)
        if measured is None:
            _fail(f"unmeasured Kubernetes node: {name}")
        annotation = node.get("metadata", {}).get("annotations", {}).get("nohiki.io/hosts-sha256", "")
        if measured["hostsSha256"] and annotation != measured["hostsSha256"]:
            _fail(f"node hosts annotation contradicts measurement: {name}")
        ready = next(
            (
                condition.get("status")
                for condition in node.get("status", {}).get("conditions", [])
                if condition.get("type") == "Ready"
            ),
            None,
        )
        observed_nodes.append(
            {
                "containerId": measured["containerId"],
                "hostsSha256": measured["hostsSha256"],
                "kubeletVersion": node.get("status", {}).get("nodeInfo", {}).get("kubeletVersion"),
                "name": name,
                "ready": ready == "True",
                "startTime": measured["startTime"],
            }
        )
    secrets: list[dict[str, Any]] = []
    for measured in measurements["secrets"]:
        namespace_name = measured["namespace"]
        secret_name = measured["name"]
        metadata_result = run_readonly(
            (
                *prefix,
                "-n",
                namespace_name,
                "get",
                "secret",
                secret_name,
                "-o",
                "jsonpath={.metadata.uid}{'\\t'}{.metadata.resourceVersion}{'\\t'}{.type}{'\\t'}{.metadata.annotations.nohiki\\.io/source-file-sha256}",
            )
        )
        keys_result = run_readonly(
            (
                *prefix,
                "-n",
                namespace_name,
                "get",
                "secret",
                secret_name,
                "-o",
                'go-template={{range $k, $_ := .data}}{{$k}}{{"\\n"}}{{end}}',
            )
        )
        if metadata_result.returncode != 0 or keys_result.returncode != 0:
            _fail(f"Secret metadata observation failed: {namespace_name}/{secret_name}")
        fields = metadata_result.stdout.split("\t")
        if len(fields) != SECRET_METADATA_FIELD_COUNT:
            _fail("Secret metadata query returned the wrong shape")
        observed = {
            "keyNames": sorted(line for line in keys_result.stdout.splitlines() if line),
            "name": secret_name,
            "namespace": namespace_name,
            "resourceVersion": fields[1],
            "sourceFileSha256": fields[3],
            "type": fields[2],
            "uid": fields[0],
        }
        if observed != measured:
            _fail(f"Secret metadata contradicts measurement: {namespace_name}/{secret_name}")
        secrets.append(observed)
    cluster = {
        "context": CONTEXT,
        "createdAt": namespace.get("metadata", {}).get("creationTimestamp"),
        "kubeSystemUid": namespace.get("metadata", {}).get("uid"),
        "name": CLUSTER,
        "nodes": observed_nodes,
        "present": True,
    }
    if cluster["kubeSystemUid"] != measurements["cluster"]["uid"]:
        _fail("kube-system UID contradicts runner measurements")
    return cluster, secrets


def empty_runtime_sections() -> dict[str, Any]:
    """Return schema-stable empty sections not populated during C1."""
    return {
        "artifacts": [],
        "errors": [],
        "flux": {
            "helmReleases": [],
            "instance": None,
            "kustomizations": [],
            "operator": None,
            "report": None,
            "sources": [],
        },
        "registry": {
            "claim": None,
            "deployment": None,
            "digestHeadResults": [],
            "image": None,
            "imageId": None,
            "nodePort": None,
            "service": None,
        },
        "storage": {"claims": [], "provisionerImages": [], "storageClasses": [], "volumes": []},
        "tests": {
            "api": {"host": None, "inCluster": None},
            "healthInventory": None,
            "healthRun": None,
            "migration": None,
            "playwright": {"host": None, "inCluster": None},
        },
        "workloads": [],
    }


def observe(arguments: argparse.Namespace) -> tuple[dict[str, Any], Path]:
    """Collect and exclusively write one bound runtime observation."""
    measurements, measurement_bytes = read_canonical_json(arguments.runner_measurements)
    sidecar, _ = read_canonical_json(arguments.runner_measurements_sidecar)
    validate_measurements(measurements, arguments.attempt)
    validate_sidecar(sidecar, measurements, measurement_bytes)
    clusters = kind_clusters()
    present = CLUSTER in clusters
    kubeconfig = validate_kubeconfig(measurements, must_exist=present)
    _, containers, volumes, attachments = podman_inventory(measurements["nodes"], kind_present=present)
    if kubeconfig.exists():
        contexts_result = run_readonly(
            ("kubectl", "--kubeconfig", str(kubeconfig), "config", "get-contexts", "-o", "name")
        )
        contexts = (
            []
            if contexts_result.returncode != 0
            else [line for line in contexts_result.stdout.splitlines() if line == CONTEXT]
        )
    else:
        contexts = []
    if present:
        cluster, secrets = kubernetes_observation(kubeconfig, measurements)
    else:
        cluster = {
            "context": CONTEXT,
            "createdAt": None,
            "kubeSystemUid": None,
            "name": CLUSTER,
            "nodes": [],
            "present": False,
        }
        secrets = []
    document: dict[str, Any] = {
        "apiVersion": "nohiki.io/v1alpha1",
        "attempt": arguments.attempt,
        "cleanup": {
            "containers": containers,
            "contexts": contexts,
            "kindClusters": [name for name in clusters if name == CLUSTER],
            "networkAttachments": attachments,
            "proxyState": [],
            "volumes": volumes,
        },
        "cluster": cluster,
        "command": "observe",
        "git": {
            "branch": arguments.branch,
            "remoteSha": arguments.remote_sha,
            "reviewedSha": arguments.reviewed_sha,
            "sourceRevision": None,
        },
        "kind": "KindRuntimeObservation",
        "observedAt": dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z"),
        "phase": arguments.phase,
        "schemaVersion": 1,
        "secrets": secrets,
        **empty_runtime_sections(),
    }
    output_sidecar = Path(f"{arguments.output}.sha256.json")
    if output_sidecar.exists():
        _fail("observer output sidecar must be absent")
    write_exclusive(arguments.output, document)
    write_exclusive(
        output_sidecar,
        {
            "attempt": arguments.attempt,
            "clusterUid": cluster["kubeSystemUid"],
            "lockSha256": measurements["lockSha256"],
            "output": str(arguments.output),
            "sha256": hashlib.sha256(arguments.output.read_bytes()).hexdigest(),
        },
    )
    return document, output_sidecar


def parse_arguments(argv: Sequence[str]) -> argparse.Namespace:
    """Parse and validate the closed observer command-line surface."""
    parser = argparse.ArgumentParser(prog="observer.py")
    parser.add_argument("--attempt", type=int, required=True)
    parser.add_argument("--phase", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--reviewed-sha", required=True)
    parser.add_argument("--remote-sha", required=True)
    parser.add_argument("--runner-measurements", type=Path, required=True)
    parser.add_argument("--runner-measurements-sidecar", type=Path, required=True)
    arguments = parser.parse_args(argv)
    if arguments.attempt < 1:
        parser.error("--attempt must be at least 1")
    if PHASE.fullmatch(arguments.phase) is None:
        parser.error("--phase has an invalid shape")
    if BRANCH.fullmatch(arguments.branch) is None:
        parser.error("--branch must match runtime-control/local/<name>")
    if SHA.fullmatch(arguments.reviewed_sha) is None or SHA.fullmatch(arguments.remote_sha) is None:
        parser.error("source SHAs must be 40 lowercase hexadecimal characters")
    if not arguments.output.is_absolute() or arguments.output.exists():
        parser.error("--output must be an absent absolute path")
    return arguments


def main(argv: Sequence[str] | None = None) -> int:
    """Run one observation from validated command-line arguments."""
    arguments = parse_arguments(sys.argv[1:] if argv is None else argv)
    observe(arguments)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ObservationError, OSError, subprocess.TimeoutExpired, ValueError) as error:
        sys.stderr.write(f"observer: {error}\n")
        raise SystemExit(1) from error
