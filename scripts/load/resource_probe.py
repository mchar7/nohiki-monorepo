#!/usr/bin/env python3
"""Capture comparable resource evidence from an explicitly selected local kind cluster."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import ipaddress
import json
import math
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import cast
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[2]
API_VERSION = "nohiki.io/v1alpha1"
PHASES = ("cold-start", "idle", "moderate-load", "scale-up", "drain", "restart", "recovery")
TIERS = ("T0", "T1", "T2", "T3", "T4")
MEMORY_SUFFIXES = {
    "": 1,
    "k": 1_000,
    "K": 1_000,
    "Ki": 1024,
    "M": 1_000_000,
    "Mi": 1024**2,
    "G": 1_000_000_000,
    "Gi": 1024**3,
    "T": 1_000_000_000_000,
    "Ti": 1024**4,
}
QUANTITY = re.compile(r"(?P<number>[0-9]+(?:\.[0-9]+)?)(?P<suffix>[A-Za-z]*)\Z")


type JsonObject = dict[str, object]
type JsonList = list[object]


class ProbeError(RuntimeError):
    """Raised when a resource capture cannot produce trustworthy evidence."""


def require_object(value: object, label: str) -> JsonObject:
    """Return a JSON object or fail with a useful boundary error."""
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        message = f"{label} is not a JSON object"
        raise ProbeError(message)
    return cast("JsonObject", value)


def object_at(value: Mapping[str, object], key: str) -> JsonObject:
    """Return an object field, treating an absent field as empty."""
    item = value.get(key, {})
    return require_object(item, key)


def list_at(value: Mapping[str, object], key: str) -> JsonList:
    """Return a list field, treating an absent field as empty."""
    item = value.get(key, [])
    if not isinstance(item, list):
        message = f"{key} is not a JSON list"
        raise ProbeError(message)
    return cast("JsonList", item)


def string_at(value: Mapping[str, object], key: str, default: str = "") -> str:
    """Return a string field, treating an absent field as the supplied default."""
    item = value.get(key, default)
    if not isinstance(item, str):
        message = f"{key} is not a string"
        raise ProbeError(message)
    return item


def parse_memory_bytes(raw: str) -> int:
    """Parse a Kubernetes memory quantity into bytes."""
    match = QUANTITY.fullmatch(raw)
    if match is None or match["suffix"] not in MEMORY_SUFFIXES:
        message = f"unsupported memory quantity: {raw}"
        raise ProbeError(message)
    return math.ceil(float(match["number"]) * MEMORY_SUFFIXES[match["suffix"]])


def parse_cpu_nanocores(raw: str) -> int:
    """Parse a Kubernetes CPU quantity into nanocores."""
    suffixes = {"": 1_000_000_000, "m": 1_000_000, "u": 1_000, "n": 1}
    match = QUANTITY.fullmatch(raw)
    if match is None or match["suffix"] not in suffixes:
        message = f"unsupported CPU quantity: {raw}"
        raise ProbeError(message)
    return math.ceil(float(match["number"]) * suffixes[match["suffix"]])


def resource_values(resources: Mapping[str, object]) -> JsonObject:
    """Normalize raw request or limit values for comparable arithmetic."""
    cpu = resources.get("cpu")
    memory = resources.get("memory")
    return {
        "cpu": cpu,
        "cpuNanocores": parse_cpu_nanocores(cpu) if isinstance(cpu, str) else None,
        "memory": memory,
        "memoryBytes": parse_memory_bytes(memory) if isinstance(memory, str) else None,
    }


def sha256_file(path: Path) -> str:
    """Hash a provenance input without loading it all into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run(argv: Sequence[str], *, allow_failure: bool = False) -> subprocess.CompletedProcess[str]:
    """Run one bounded local command and preserve stderr on failure."""
    result = subprocess.run(argv, check=False, capture_output=True, text=True, timeout=60)
    if result.returncode != 0 and not allow_failure:
        detail = result.stderr.strip() or result.stdout.strip()
        message = f"command failed ({result.returncode}): {' '.join(argv)}: {detail}"
        raise ProbeError(message)
    return result


def command_json(argv: Sequence[str], *, allow_failure: bool = False) -> JsonObject:
    """Run a command that returns one JSON object."""
    result = run(argv, allow_failure=allow_failure)
    if result.returncode != 0:
        return {"items": []}
    try:
        return require_object(json.loads(result.stdout), "command output")
    except json.JSONDecodeError as error:
        message = f"command returned malformed JSON: {' '.join(argv)}"
        raise ProbeError(message) from error


def kubectl_json(context: str, resources: str, namespace: str | None, *, optional: bool = False) -> JsonObject:
    """Read a Kubernetes resource list from the named local kind context."""
    scope = ("-A",) if namespace is None else ("-n", namespace)
    return command_json(
        ("kubectl", "--context", context, "get", resources, *scope, "-o", "json"),
        allow_failure=optional,
    )


def kubectl_raw_json(context: str, path: str, *, optional: bool = False) -> JsonObject:
    """Read one Kubernetes API path from the named local kind context."""
    return command_json(("kubectl", "--context", context, "get", "--raw", path), allow_failure=optional)


def validate_local_context(context: str) -> None:
    """Bind the requested context to the repository's loopback kind cluster."""
    if context != "kind-nohiki":
        message = "--context must be kind-nohiki"
        raise ProbeError(message)
    config = command_json(("kubectl", "--context", context, "config", "view", "--minify", "--raw", "-o", "json"))
    clusters = list_at(config, "clusters")
    if len(clusters) != 1:
        message = "kind-nohiki context must resolve to exactly one cluster"
        raise ProbeError(message)
    cluster_entry = require_object(clusters[0], "cluster entry")
    cluster = object_at(cluster_entry, "cluster")
    server = string_at(cluster, "server")
    hostname = urlparse(server).hostname
    try:
        loopback = hostname == "localhost" or (hostname is not None and ipaddress.ip_address(hostname).is_loopback)
    except ValueError:
        loopback = False
    if cluster_entry.get("name") != "kind-nohiki" or not loopback:
        message = "kind-nohiki context must resolve to the loopback kind-nohiki API"
        raise ProbeError(message)


def validate_local_nodes(document: Mapping[str, object]) -> None:
    """Reject a loopback proxy that does not expose the expected local kind nodes."""
    items = list_at(document, "items")
    if not items:
        message = "kind-nohiki returned no nodes"
        raise ProbeError(message)
    for raw in items:
        node = require_object(raw, "node")
        name = string_at(metadata(node), "name")
        if not name.startswith("nohiki-"):
            message = f"unexpected node in kind-nohiki context: {name}"
            raise ProbeError(message)


def metadata(item: Mapping[str, object]) -> JsonObject:
    """Return the metadata object for a Kubernetes item."""
    return object_at(item, "metadata")


def owner(metadata_value: Mapping[str, object]) -> JsonObject | None:
    """Return the controlling owner reference without leaking unrelated metadata."""
    references = list_at(metadata_value, "ownerReferences")
    selected: JsonObject | None = None
    for raw in references:
        reference = require_object(raw, "ownerReference")
        if reference.get("controller") is True:
            selected = reference
            break
        if selected is None:
            selected = reference
    if selected is None:
        return None
    return {"kind": selected.get("kind"), "name": selected.get("name")}


def metric_usage(metrics: Mapping[str, object]) -> dict[tuple[str, str, str], JsonObject]:
    """Index Metrics API usage by namespace, pod, and container."""
    indexed: dict[tuple[str, str, str], JsonObject] = {}
    for raw_pod in list_at(metrics, "items"):
        pod = require_object(raw_pod, "pod metric")
        pod_meta = metadata(pod)
        namespace = string_at(pod_meta, "namespace")
        pod_name = string_at(pod_meta, "name")
        for raw_container in list_at(pod, "containers"):
            container = require_object(raw_container, "container metric")
            usage = object_at(container, "usage")
            indexed[(namespace, pod_name, string_at(container, "name"))] = resource_values(usage)
    return indexed


def container_statuses(status: Mapping[str, object]) -> dict[str, JsonObject]:
    """Index pod container status by name."""
    indexed: dict[str, JsonObject] = {}
    for field in ("initContainerStatuses", "containerStatuses", "ephemeralContainerStatuses"):
        for raw in list_at(status, field):
            item = require_object(raw, field)
            indexed[string_at(item, "name")] = item
    return indexed


def state_name(status: Mapping[str, object]) -> str | None:
    """Return the active Kubernetes container state name."""
    state = object_at(status, "state")
    return next((name for name in ("running", "waiting", "terminated") if name in state), None)


def last_termination(status: Mapping[str, object]) -> JsonObject | None:
    """Return only non-sensitive last termination evidence."""
    terminated = object_at(object_at(status, "lastState"), "terminated")
    if not terminated:
        return None
    return {
        "exitCode": terminated.get("exitCode"),
        "finishedAt": terminated.get("finishedAt"),
        "reason": terminated.get("reason"),
        "signal": terminated.get("signal"),
    }


def summarize_containers(
    pod_meta: Mapping[str, object],
    spec: Mapping[str, object],
    status: Mapping[str, object],
    usage: Mapping[tuple[str, str, str], JsonObject],
) -> JsonList:
    """Create a closed, comparable container resource record for one pod."""
    namespace = string_at(pod_meta, "namespace")
    pod_name = string_at(pod_meta, "name")
    statuses = container_statuses(status)
    summarized: JsonList = []
    container_groups = (
        ("initContainers", "init"),
        ("containers", "persistent"),
        ("ephemeralContainers", "ephemeral"),
    )
    for field, lifecycle in container_groups:
        for raw in list_at(spec, field):
            container = require_object(raw, field)
            name = string_at(container, "name")
            resources = object_at(container, "resources")
            requests = object_at(resources, "requests")
            limits = object_at(resources, "limits")
            current = statuses.get(name, {})
            summarized.append(
                {
                    "image": container.get("image"),
                    "imageId": current.get("imageID"),
                    "lastTermination": last_termination(current),
                    "lifecycle": lifecycle,
                    "limits": resource_values(limits),
                    "missingCpuLimit": "cpu" not in limits,
                    "missingCpuRequest": "cpu" not in requests,
                    "missingMemoryLimit": "memory" not in limits,
                    "missingMemoryRequest": "memory" not in requests,
                    "name": name,
                    "ready": current.get("ready"),
                    "requests": resource_values(requests),
                    "restartCount": current.get("restartCount"),
                    "state": state_name(current),
                    "usage": usage.get((namespace, pod_name, name)),
                }
            )
    return summarized


def summarize_pods(document: Mapping[str, object], metrics: Mapping[str, object]) -> JsonList:
    """Summarize every pod while excluding environment and secret payloads."""
    usage = metric_usage(metrics)
    result: JsonList = []
    for raw in list_at(document, "items"):
        pod = require_object(raw, "pod")
        pod_meta = metadata(pod)
        spec = object_at(pod, "spec")
        status = object_at(pod, "status")
        result.append(
            {
                "containers": summarize_containers(pod_meta, spec, status, usage),
                "name": string_at(pod_meta, "name"),
                "namespace": string_at(pod_meta, "namespace"),
                "node": spec.get("nodeName"),
                "owner": owner(pod_meta),
                "phase": status.get("phase"),
                "qosClass": status.get("qosClass"),
                "startTime": status.get("startTime"),
            }
        )
    return sorted(
        result,
        key=lambda item: (
            str(require_object(item, "pod").get("namespace")),
            str(require_object(item, "pod").get("name")),
        ),
    )


def pod_template(item: Mapping[str, object]) -> JsonObject:
    """Locate the pod template across supported workload controllers."""
    kind = string_at(item, "kind")
    spec = object_at(item, "spec")
    if kind == "CronJob":
        return object_at(object_at(object_at(spec, "jobTemplate"), "spec"), "template")
    return object_at(spec, "template")


def workload_state(kind: str, spec: Mapping[str, object], status: Mapping[str, object]) -> JsonObject:
    """Normalize controller-specific replica and completion state."""
    if kind in {"Deployment", "StatefulSet"}:
        return {
            "available": status.get("availableReplicas"),
            "current": status.get("currentReplicas"),
            "desired": spec.get("replicas"),
            "ready": status.get("readyReplicas"),
        }
    if kind == "DaemonSet":
        return {
            "available": status.get("numberAvailable"),
            "current": status.get("currentNumberScheduled"),
            "desired": status.get("desiredNumberScheduled"),
            "ready": status.get("numberReady"),
        }
    if kind == "Job":
        return {
            "active": status.get("active"),
            "desired": spec.get("completions", 1),
            "failed": status.get("failed"),
            "ready": status.get("ready"),
            "succeeded": status.get("succeeded"),
        }
    if kind == "CronJob":
        return {
            "active": len(list_at(status, "active")),
            "lastScheduleTime": status.get("lastScheduleTime"),
            "schedule": spec.get("schedule"),
            "suspended": spec.get("suspend", False),
        }
    message = f"unsupported workload kind: {kind}"
    raise ProbeError(message)


def summarize_workloads(document: Mapping[str, object]) -> JsonList:
    """Summarize desired state and declared resources for every workload controller."""
    result: JsonList = []
    for raw in list_at(document, "items"):
        item = require_object(raw, "workload")
        item_meta = metadata(item)
        kind = string_at(item, "kind")
        spec = object_at(item, "spec")
        status = object_at(item, "status")
        template_spec = object_at(pod_template(item), "spec")
        containers: JsonList = []
        for field, lifecycle in (("initContainers", "init"), ("containers", "persistent")):
            for raw_container in list_at(template_spec, field):
                container = require_object(raw_container, field)
                resources = object_at(container, "resources")
                requests = object_at(resources, "requests")
                limits = object_at(resources, "limits")
                containers.append(
                    {
                        "lifecycle": lifecycle,
                        "limits": resource_values(limits),
                        "missingCpuLimit": "cpu" not in limits,
                        "missingCpuRequest": "cpu" not in requests,
                        "missingMemoryLimit": "memory" not in limits,
                        "missingMemoryRequest": "memory" not in requests,
                        "name": container.get("name"),
                        "requests": resource_values(requests),
                    }
                )
        result.append(
            {
                "containers": containers,
                "kind": kind,
                "name": item_meta.get("name"),
                "namespace": item_meta.get("namespace"),
                "state": workload_state(kind, spec, status),
            }
        )
    return sorted(
        result,
        key=lambda item: (
            str(require_object(item, "workload").get("namespace")),
            str(require_object(item, "workload").get("kind")),
            str(require_object(item, "workload").get("name")),
        ),
    )


def node_resource(resource: Mapping[str, object], name: str, parser: Callable[[str], int]) -> int | None:
    """Parse one node resource with a supplied quantity parser."""
    raw = resource.get(name)
    return parser(raw) if isinstance(raw, str) else None


def summarize_nodes(document: Mapping[str, object], metrics: Mapping[str, object]) -> JsonList:
    """Summarize node capacity, allocatable reserve, conditions, and live usage."""
    usage_by_name: dict[str, JsonObject] = {}
    for raw in list_at(metrics, "items"):
        item = require_object(raw, "node metric")
        usage_by_name[string_at(metadata(item), "name")] = resource_values(object_at(item, "usage"))
    result: JsonList = []
    for raw in list_at(document, "items"):
        node = require_object(raw, "node")
        node_meta = metadata(node)
        name = string_at(node_meta, "name")
        status = object_at(node, "status")
        capacity = object_at(status, "capacity")
        allocatable = object_at(status, "allocatable")
        capacity_memory = node_resource(capacity, "memory", parse_memory_bytes)
        allocatable_memory = node_resource(allocatable, "memory", parse_memory_bytes)
        capacity_cpu = node_resource(capacity, "cpu", parse_cpu_nanocores)
        allocatable_cpu = node_resource(allocatable, "cpu", parse_cpu_nanocores)
        conditions: JsonObject = {}
        for raw_condition in list_at(status, "conditions"):
            condition = require_object(raw_condition, "node condition")
            condition_type = string_at(condition, "type")
            if condition_type in {"Ready", "MemoryPressure", "DiskPressure", "PIDPressure"}:
                conditions[condition_type] = condition.get("status")
        result.append(
            {
                "allocatable": resource_values(allocatable),
                "capacity": resource_values(capacity),
                "conditions": conditions,
                "name": name,
                "reserve": {
                    "cpuNanocores": (
                        capacity_cpu - allocatable_cpu
                        if capacity_cpu is not None and allocatable_cpu is not None
                        else None
                    ),
                    "memoryBytes": (
                        capacity_memory - allocatable_memory
                        if capacity_memory is not None and allocatable_memory is not None
                        else None
                    ),
                },
                "usage": usage_by_name.get(name),
            }
        )
    return sorted(result, key=lambda item: str(require_object(item, "node").get("name")))


def git_provenance(*, allow_dirty: bool) -> JsonObject:
    """Record the exact source revision and reject accidental mixed-tree trials."""
    revision = run(("git", "-C", str(REPO_ROOT), "rev-parse", "HEAD")).stdout.strip()
    status = run(("git", "-C", str(REPO_ROOT), "status", "--porcelain")).stdout
    dirty = bool(status.strip())
    if dirty and not allow_dirty:
        message = "repository is dirty; commit the trial revision or pass --allow-dirty for exploratory evidence"
        raise ProbeError(message)
    return {"dirty": dirty, "revision": revision}


def fingerprint(paths: Iterable[str]) -> JsonObject:
    """Hash a stable ordered set of repository-relative configuration inputs."""
    entries: JsonList = []
    combined = hashlib.sha256()
    for raw in sorted(set(paths)):
        path = (REPO_ROOT / raw).resolve()
        if not path.is_relative_to(REPO_ROOT) or not path.is_file():
            message = f"provenance path is not a repository file: {raw}"
            raise ProbeError(message)
        relative = path.relative_to(REPO_ROOT).as_posix()
        digest = sha256_file(path)
        entries.append({"path": relative, "sha256": digest})
        combined.update(f"{relative}\0{digest}\n".encode())
    return {"entries": entries, "sha256": combined.hexdigest()}


def summarize_scalers(document: Mapping[str, object]) -> JsonList:
    """Record scaler desired state without copying authentication references or metadata."""
    result: JsonList = []
    for raw in list_at(document, "items"):
        item = require_object(raw, "scaler")
        item_meta = metadata(item)
        spec = object_at(item, "spec")
        result.append(
            {
                "kind": item.get("kind"),
                "maxReplicas": spec.get("maxReplicaCount", spec.get("maxReplicas")),
                "minReplicas": spec.get("minReplicaCount", spec.get("minReplicas")),
                "name": item_meta.get("name"),
                "namespace": item_meta.get("namespace"),
                "scaleTarget": object_at(spec, "scaleTargetRef").get("name"),
            }
        )
    return sorted(
        result,
        key=lambda item: (
            str(require_object(item, "scaler").get("namespace")),
            str(require_object(item, "scaler").get("kind")),
            str(require_object(item, "scaler").get("name")),
        ),
    )


def capture(args: argparse.Namespace) -> JsonObject:
    """Capture one lifecycle-state evidence point."""
    context = str(args.context)
    validate_local_context(context)
    namespace = str(args.namespace) if args.namespace else None
    nodes = kubectl_json(context, "nodes", None)
    validate_local_nodes(nodes)
    pods = kubectl_json(context, "pods", namespace)
    workloads = kubectl_json(context, "deployments,statefulsets,daemonsets,jobs,cronjobs", namespace)
    pod_metrics = kubectl_raw_json(context, "/apis/metrics.k8s.io/v1beta1/pods")
    node_metrics = kubectl_raw_json(context, "/apis/metrics.k8s.io/v1beta1/nodes")
    hpas = kubectl_json(context, "horizontalpodautoscalers.autoscaling", namespace, optional=True)
    scaled_objects = kubectl_json(context, "scaledobjects.keda.sh", namespace, optional=True)
    return {
        "apiVersion": API_VERSION,
        "capturedAt": dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z"),
        "fixtureVersion": args.fixture_version,
        "kind": "ResourceEvidencePoint",
        "namespace": namespace,
        "nodes": summarize_nodes(nodes, node_metrics),
        "phase": args.phase,
        "pods": summarize_pods(pods, pod_metrics),
        "provenance": {
            "signalConfiguration": fingerprint(args.signal_config),
            "source": git_provenance(allow_dirty=args.allow_dirty),
            "topology": {"context": context, "provider": "kind", "scope": "local-only"},
            "values": fingerprint(args.values_path),
        },
        "scalers": summarize_scalers(hpas) + summarize_scalers(scaled_objects),
        "testTier": args.tier,
        "workloads": summarize_workloads(workloads),
    }


def percentile(values: Sequence[int], percent: int) -> int | None:
    """Return the nearest-rank percentile for a non-empty integer sample."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(percent / 100 * len(ordered)))
    return ordered[rank - 1]


def usage_distributions(points: Sequence[Mapping[str, object]]) -> JsonList:
    """Aggregate per-container memory and CPU distributions across matched samples."""
    values: dict[tuple[str, str, str], dict[str, list[int]]] = {}
    for point in points:
        for raw_pod in list_at(point, "pods"):
            pod = require_object(raw_pod, "pod")
            namespace = string_at(pod, "namespace")
            pod_name = string_at(pod, "name")
            for raw_container in list_at(pod, "containers"):
                container = require_object(raw_container, "container")
                usage = container.get("usage")
                if not isinstance(usage, dict):
                    continue
                key = (namespace, pod_name, string_at(container, "name"))
                samples = values.setdefault(key, {"cpuNanocores": [], "memoryBytes": []})
                for resource in samples:
                    value = usage.get(resource)
                    if isinstance(value, int):
                        samples[resource].append(value)
    result: JsonList = []
    for (namespace, pod_name, container_name), resources in sorted(values.items()):
        result.append(
            {
                "container": container_name,
                "cpuNanocores": {
                    "highWater": max(resources["cpuNanocores"], default=None),
                    "p50": percentile(resources["cpuNanocores"], 50),
                    "p95": percentile(resources["cpuNanocores"], 95),
                    "samples": len(resources["cpuNanocores"]),
                },
                "memoryBytes": {
                    "highWater": max(resources["memoryBytes"], default=None),
                    "p50": percentile(resources["memoryBytes"], 50),
                    "p95": percentile(resources["memoryBytes"], 95),
                    "samples": len(resources["memoryBytes"]),
                },
                "namespace": namespace,
                "pod": pod_name,
            }
        )
    return result


def write_all(descriptor: int, data: bytes) -> None:
    """Write every evidence byte or fail on a stalled filesystem write."""
    remaining = memoryview(data)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            message = "filesystem write made no progress"
            raise ProbeError(message)
        remaining = remaining[written:]


def write_json(path: Path, document: object) -> None:
    """Create a private evidence file without overwriting a prior trial."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    data = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        write_all(descriptor, data)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def build_parser() -> argparse.ArgumentParser:
    """Build the fail-closed command-line contract."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("capture", "sample"))
    parser.add_argument("--context", required=True, help="Explicit local kind context, for example kind-nohiki")
    parser.add_argument("--namespace", help="Optional namespace; omit to capture the complete cluster")
    parser.add_argument("--phase", choices=PHASES, required=True)
    parser.add_argument("--tier", choices=TIERS, required=True)
    parser.add_argument("--fixture-version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--duration-seconds", type=float, default=60.0)
    parser.add_argument("--interval-seconds", type=float, default=5.0)
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument(
        "--values-path",
        action="append",
        default=["infra/k8s/helm/values.yaml", "infra/k8s/helm/values.local.yaml"],
    )
    parser.add_argument(
        "--signal-config",
        action="append",
        default=["infra/k8s/observability/base/kube-prometheus-stack/helmrelease.yaml"],
    )
    return parser


def validate_sampling_args(args: argparse.Namespace) -> None:
    """Reject sampling intervals that cannot produce a bounded evidence series."""
    values = (args.duration_seconds, args.interval_seconds)
    if not all(math.isfinite(value) and value > 0 for value in values):
        message = "sample duration and interval must be positive"
        raise ProbeError(message)


def main(argv: Sequence[str] | None = None) -> int:
    """Capture one point or a repeated distribution and write the evidence once."""
    args = build_parser().parse_args(argv)
    try:
        if args.command == "capture":
            document: object = capture(args)
        else:
            validate_sampling_args(args)
            points: list[JsonObject] = []
            deadline = time.monotonic() + args.duration_seconds
            while True:
                points.append(capture(args))
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                time.sleep(min(args.interval_seconds, remaining))
            document = {
                "apiVersion": API_VERSION,
                "distributions": usage_distributions(points),
                "kind": "ResourceEvidenceSeries",
                "points": points,
            }
        write_json(args.output, document)
    except (OSError, ProbeError, subprocess.SubprocessError) as error:
        sys.stderr.write(f"resource probe failed: {error}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
