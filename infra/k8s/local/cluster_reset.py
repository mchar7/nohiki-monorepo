#!/usr/bin/env python3
"""Capture evidence and replace a local cluster through trusted host adapters."""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fcntl
import getpass
import hashlib
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import NoReturn, Self, cast
from urllib.parse import urlsplit, urlunsplit

API_VERSION = "nohiki.io/v1alpha1"
APP_NAMESPACE = "nohiki"
FLUX_NAMESPACE = "flux-system"
DATA_LOSS_ACK = "I understand this permanently deletes local Nohiki data"
FACTORY_ACK = "I understand factory reset removes the Nohiki and Flux local control planes"
SHA256_RE = re.compile(r"[0-9a-f]{64}")
REF_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/@+-]{0,254}")
SIDECAR_FIELD_COUNT = 2
COMMIT_FIELD_COUNT = 2
TRUSTED_COMMANDS = frozenset({"age", "flux", "git", "helm", "kubectl", "sops"})
ABSENT_NAMESPACES = (
    APP_NAMESPACE,
    "nohiki-foundation",
    "nohiki-registry",
    "nohiki-verification",
    FLUX_NAMESPACE,
)
PURGE_TIMEOUT_SECONDS = 600.0
START_TIMEOUT_SECONDS = 120.0
READINESS_TIMEOUT_SECONDS = 300.0
COMMAND_TIMEOUT_SECONDS = 60.0
REQUEST_TIMEOUT_SECONDS = 5
TRANSACTION_PHASES = (
    "authorized",
    "adapterPreflight",
    "purge",
    "start",
    "apiReady",
    "nodeReady",
    "identity",
    "absence",
)


type JsonObject = dict[str, object]
type CommandResult = dict[str, object]


class RefusalError(RuntimeError):
    """Represent a fail-closed refusal safe to show to an operator."""


def refuse(message: str) -> NoReturn:
    """Raise an operator-facing fail-closed refusal."""
    msg = f"refused: {message}"
    raise RefusalError(msg)


def now() -> str:
    """Return a UTC RFC3339 timestamp."""
    return dt.datetime.now(dt.UTC).isoformat()


def run(
    command: Sequence[str],
    *,
    required: bool = True,
    timeout: float = COMMAND_TIMEOUT_SECONDS,
) -> CommandResult:
    """Run an allowlisted read-only command with a bounded process deadline."""
    parts = tuple(command)
    if not parts or parts[0] not in TRUSTED_COMMANDS:
        refuse("command is outside the trusted executable allowlist")
    executable = shutil.which(parts[0])
    if executable is None:
        if required:
            refuse(f"cannot execute {parts[0]}: executable not found")
        return {
            "command": list(parts),
            "exitCode": None,
            "stdout": "",
            "stderr": "executable not found",
        }
    try:
        result = subprocess.run(  # noqa: S603  # Executable is resolved from the fixed allowlist.
            (executable, *parts[1:]),
            check=False,
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as error:
        detail = f"command timed out after {timeout:g}s ({' '.join(parts)})"
        if required:
            raise RefusalError(detail) from error
        return {
            "command": list(parts),
            "exitCode": None,
            "stdout": "",
            "stderr": detail,
        }
    except OSError as error:
        if required:
            msg = f"cannot execute {parts[0]}: {error}"
            raise RefusalError(msg) from error
        return {
            "command": list(parts),
            "exitCode": None,
            "stdout": "",
            "stderr": str(error),
        }
    stdout = result.stdout.decode(errors="replace").rstrip()
    stderr = result.stderr.decode(errors="replace").rstrip()
    captured = {
        "command": list(parts),
        "exitCode": result.returncode,
        "stdout": stdout,
        "stderr": stderr,
    }
    if required and result.returncode != 0:
        detail = stderr or stdout or "no diagnostic"
        msg = f"read-only command failed ({' '.join(parts)}): {detail}"
        raise RefusalError(msg)
    return captured


def kubectl(
    *arguments: str,
    required: bool = True,
    timeout: float = COMMAND_TIMEOUT_SECONDS,
) -> CommandResult:
    """Run kubectl with trusted executable resolution and a process timeout."""
    return run(("kubectl", *arguments), required=required, timeout=timeout)


def current_context() -> str:
    """Return the active kubectl context."""
    return str(kubectl("config", "current-context")["stdout"])


def require_context(expected: str) -> str:
    """Require and return an exact kubectl context match."""
    actual = current_context()
    if not expected or actual != expected:
        refuse(f"kubectl context is {actual!r}, expected exact context {expected!r}")
    return actual


def sha256(path: Path) -> str:
    """Return the SHA-256 digest of a file."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write(path: Path, content: bytes) -> None:
    """Atomically write private file content without creating parent directories."""
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(path)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _evidence_commit_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.commit")


def _evidence_generation_path(path: Path, checksum: str) -> Path:
    return path.with_name(f".{path.name}.{checksum}.generation")


def _evidence_commit(path: Path) -> tuple[str, str] | None:
    marker = _evidence_commit_path(path)
    if not marker.is_file():
        return None
    try:
        fields = marker.read_text(encoding="ascii").split()
    except OSError, UnicodeError:
        return None
    if (
        len(fields) != COMMIT_FIELD_COUNT
        or fields[0] not in {"pending", "complete"}
        or SHA256_RE.fullmatch(fields[1]) is None
    ):
        return None
    return fields[0], fields[1]


def _committed_checksum(path: Path) -> str | None:
    commit = _evidence_commit(path)
    return None if commit is None else commit[1]


def _recover_committed_evidence(path: Path) -> None:
    commit = _evidence_commit(path)
    if commit is None or commit[0] == "complete":
        return
    checksum = commit[1]
    generation = _evidence_generation_path(path, checksum)
    if not generation.is_file() or sha256(generation) != checksum:
        refuse("evidence commit generation is missing or corrupt")
    sidecar = path.with_name(path.name + ".sha256")
    expected_sidecar = f"{checksum}  {path.name}\n".encode()
    atomic_write(path, generation.read_bytes())
    atomic_write(sidecar, expected_sidecar)
    atomic_write(_evidence_commit_path(path), f"complete {checksum}\n".encode())


def write_evidence(path: Path, document: JsonObject) -> str:
    """Commit a recoverable evidence generation before materializing its sealed pair."""
    payload = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode()
    checksum = hashlib.sha256(payload).hexdigest()
    sidecar = path.with_name(path.name + ".sha256")
    generation = _evidence_generation_path(path, checksum)
    marker = _evidence_commit_path(path)
    previous_checksum = _committed_checksum(path)
    if previous_checksum is not None:
        _recover_committed_evidence(path)
    atomic_write(generation, payload)
    atomic_write(marker, f"pending {checksum}\n".encode())
    atomic_write(path, payload)
    atomic_write(sidecar, f"{checksum}  {path.name}\n".encode())
    atomic_write(marker, f"complete {checksum}\n".encode())
    if previous_checksum is not None and previous_checksum != checksum:
        _evidence_generation_path(path, previous_checksum).unlink(missing_ok=True)
        _fsync_directory(path.parent)
    return checksum


def git_sha(ref: str) -> str:
    """Resolve a validated Git ref to a commit SHA."""
    if not REF_RE.fullmatch(ref):
        refuse(f"invalid Git ref {ref!r}")
    value = str(run(("git", "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}"))["stdout"])
    if not re.fullmatch(r"[0-9a-f]{40,64}", value):
        refuse(f"Git ref {ref!r} did not resolve to a commit SHA")
    return value


def parse_topics(values: Sequence[str]) -> dict[str, JsonObject]:
    """Parse reviewed topic assignments and resolve their refs."""
    topics: dict[str, JsonObject] = {}
    for value in values:
        name, separator, ref = value.partition("=")
        if not separator or not REF_RE.fullmatch(name) or not ref:
            refuse(f"reviewed topic must be NAME=GIT_REF, got {value!r}")
        topics[name] = {"ref": ref, "sha": git_sha(ref)}
    return topics


def command_inventory() -> dict[str, CommandResult]:
    """Capture the portable read-only cluster command inventory."""
    return {
        "apiIdentity": kubectl("auth", "whoami", "-o", "json", required=False),
        "apiVersions": kubectl("version", "-o", "json"),
        "namespaces": kubectl(
            "get",
            "namespaces",
            "-o",
            "custom-columns=NAME:.metadata.name,PHASE:.status.phase,CREATED:.metadata.creationTimestamp",
        ),
        "crds": kubectl(
            "get",
            "customresourcedefinitions",
            "-o",
            "custom-columns=NAME:.metadata.name,ESTABLISHED:.status.conditions[?(@.type=='Established')].status,STORED_VERSIONS:.status.storedVersions",
        ),
        "persistentVolumeClaims": kubectl(
            "get",
            "persistentvolumeclaims",
            "--all-namespaces",
            "-o",
            "custom-columns=NAMESPACE:.metadata.namespace,NAME:.metadata.name,STATUS:.status.phase,VOLUME:.spec.volumeName,CLASS:.spec.storageClassName,CAPACITY:.status.capacity.storage",
        ),
        "persistentVolumes": kubectl(
            "get",
            "persistentvolumes",
            "-o",
            "custom-columns=NAME:.metadata.name,STATUS:.status.phase,CLAIM:.spec.claimRef.name,CLAIM_NAMESPACE:.spec.claimRef.namespace,CLASS:.spec.storageClassName,CAPACITY:.spec.capacity.storage,RECLAIM:.spec.persistentVolumeReclaimPolicy",
        ),
        "storageClasses": kubectl(
            "get",
            "storageclasses",
            "-o",
            "custom-columns=NAME:.metadata.name,PROVISIONER:.provisioner,RECLAIM:.reclaimPolicy,BINDING:.volumeBindingMode",
        ),
        "fluxKustomizations": kubectl(
            "get",
            "kustomizations.kustomize.toolkit.fluxcd.io",
            "--all-namespaces",
            "-o",
            "custom-columns=NAMESPACE:.metadata.namespace,NAME:.metadata.name,SUSPENDED:.spec.suspend,REVISION:.status.lastAppliedRevision,READY:.status.conditions[?(@.type=='Ready')].status",
        ),
        "fluxSources": kubectl(
            "get",
            "gitrepositories.source.toolkit.fluxcd.io,ocirepositories.source.toolkit.fluxcd.io",
            "--all-namespaces",
            "-o",
            "custom-columns=KIND:.kind,NAMESPACE:.metadata.namespace,NAME:.metadata.name,REVISION:.status.artifact.revision,READY:.status.conditions[?(@.type=='Ready')].status",
            required=False,
        ),
        "fluxHelmReleases": kubectl(
            "get",
            "helmreleases.helm.toolkit.fluxcd.io",
            "--all-namespaces",
            "-o",
            "custom-columns=NAMESPACE:.metadata.namespace,NAME:.metadata.name,REVISION:.status.history[0].chartVersion,READY:.status.conditions[?(@.type=='Ready')].status",
            required=False,
        ),
        "registryImages": kubectl(
            "get",
            "pods",
            "-n",
            "registry",
            "-o",
            "custom-columns=POD:.metadata.name,IMAGES:.spec.containers[*].image,IMAGE_IDS:.status.containerStatuses[*].imageID",
            required=False,
        ),
        "runtimeImages": kubectl(
            "get",
            "pods",
            "--all-namespaces",
            "-o",
            "custom-columns=NAMESPACE:.metadata.namespace,POD:.metadata.name,IMAGES:.spec.containers[*].image,IMAGE_IDS:.status.containerStatuses[*].imageID",
        ),
    }


def tool_versions() -> dict[str, CommandResult]:
    """Capture portable lifecycle tool versions."""
    return {
        "kubectl": kubectl("version", "--client", "-o", "json"),
        "flux": run(("flux", "--version"), required=False),
        "helm": run(("helm", "version", "--short"), required=False),
        "sops": run(("sops", "--version"), required=False),
        "age": run(("age", "--version"), required=False),
    }


def _json_mapping(value: object, description: str) -> JsonObject:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        refuse(f"{description} is malformed")
    return cast(JsonObject, value)


def _json_list(value: object, description: str) -> list[object]:
    if not isinstance(value, list):
        refuse(f"{description} is malformed")
    return cast(list[object], value)


def _parse_json_output(result: CommandResult, description: str) -> JsonObject:
    try:
        return _json_mapping(json.loads(str(result["stdout"])), description)
    except json.JSONDecodeError as error:
        msg = f"refused: {description} is malformed: {error}"
        raise RefusalError(msg) from error


def _parse_timestamp(value: object, description: str) -> dt.datetime:
    if not isinstance(value, str) or not value:
        refuse(f"{description} is invalid")
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError as error:
        msg = f"refused: {description} is invalid"
        raise RefusalError(msg) from error
    if parsed.tzinfo is None:
        refuse(f"{description} is invalid")
    return parsed


def normalize_api_server(value: object) -> str:
    """Validate and normalize a Kubernetes API server URL."""
    if not isinstance(value, str) or not value:
        refuse("cluster identity apiServer is invalid")
    try:
        parsed = urlsplit(value)
    except ValueError as error:
        msg = f"kubeconfig apiServer URL is malformed: {error}"
        refuse(msg)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        refuse("cluster identity apiServer is invalid")
    path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, "", ""))


def kubeconfig_api_server(expected_context: str) -> str:
    """Read the redacted minified endpoint without contacting the API server."""
    require_explicit_kubeconfig()
    return capture_api_server(expected_context)


def validate_identity(value: object, description: str = "cluster identity") -> JsonObject:
    """Validate the shared cluster identity record schema."""
    identity = _json_mapping(value, description)
    if set(identity) != {"kubeSystemUid", "kubeSystemCreatedAt", "apiServer"}:
        refuse(f"{description} schema is invalid")
    uid = identity["kubeSystemUid"]
    if not isinstance(uid, str) or not uid:
        refuse(f"{description} kubeSystemUid is invalid")
    created = identity["kubeSystemCreatedAt"]
    _parse_timestamp(created, f"{description} kubeSystemCreatedAt")
    endpoint = normalize_api_server(identity["apiServer"])
    return {"kubeSystemUid": uid, "kubeSystemCreatedAt": created, "apiServer": endpoint}


def capture_api_server(expected_context: str) -> str:
    """Capture only the selected context endpoint from minified kubeconfig JSON."""
    document = _parse_json_output(
        kubectl("config", "view", "--minify", "--context", expected_context, "-o", "json"),
        "minified kubeconfig",
    )
    contexts = _json_list(document.get("contexts"), "minified kubeconfig contexts")
    clusters = _json_list(document.get("clusters"), "minified kubeconfig clusters")
    selected_cluster: str | None = None
    for item in contexts:
        context_record = _json_mapping(item, "minified kubeconfig context")
        if context_record.get("name") != expected_context:
            continue
        context = _json_mapping(context_record.get("context"), "minified kubeconfig context")
        cluster_name = context.get("cluster")
        if isinstance(cluster_name, str) and cluster_name:
            selected_cluster = cluster_name
            break
    if selected_cluster is None:
        refuse("minified kubeconfig does not contain the expected context")
    for item in clusters:
        cluster_record = _json_mapping(item, "minified kubeconfig cluster")
        if cluster_record.get("name") == selected_cluster:
            cluster = _json_mapping(cluster_record.get("cluster"), "minified kubeconfig cluster")
            return normalize_api_server(cluster.get("server"))
    refuse("minified kubeconfig does not contain the selected cluster")


def capture_cluster_identity_record(expected_context: str) -> JsonObject:
    """Capture the unvalidated identity fields for durable diagnostics."""
    namespace = _parse_json_output(
        kubectl(
            "get",
            "namespace",
            "kube-system",
            "-o",
            "json",
            "--context",
            expected_context,
        ),
        "kube-system namespace",
    )
    metadata = _json_mapping(namespace.get("metadata"), "kube-system metadata")
    return {
        "kubeSystemUid": metadata.get("uid"),
        "kubeSystemCreatedAt": metadata.get("creationTimestamp"),
        "apiServer": capture_api_server(expected_context),
    }


def capture_cluster_identity(expected_context: str) -> JsonObject:
    """Capture and validate kube-system identity and the selected API endpoint."""
    return validate_identity(capture_cluster_identity_record(expected_context))


def checkpoint(args: argparse.Namespace) -> int:
    """Capture a guarded pre-destruction checkpoint."""
    endpoint = kubeconfig_api_server(args.expected_context)
    with target_lock_endpoint(endpoint, exclusive=False):
        context = require_context(args.expected_context)
        identity = capture_cluster_identity(context)
        if identity["apiServer"] != endpoint:
            refuse("KUBECONFIG endpoint changed while capturing checkpoint identity")
        owner = args.owner or getpass.getuser()
        if not owner or any(character.isspace() for character in owner):
            refuse("owner must be a non-empty identifier without whitespace")
        document: JsonObject = {
            "apiVersion": API_VERSION,
            "kind": "LocalDestructionCheckpoint",
            "metadata": {
                "capturedAt": now(),
                "context": context,
                "namespaceAllowlist": [APP_NAMESPACE, FLUX_NAMESPACE],
                "owner": owner,
            },
            "evidence": {
                "clusterIdentity": identity,
                "cluster": command_inventory(),
                "git": {
                    "head": git_sha("HEAD"),
                    "runtimeControl": {
                        "ref": args.runtime_control_ref,
                        "sha": git_sha(args.runtime_control_ref),
                    },
                    "reviewedTopics": parse_topics(args.reviewed_topic),
                    "status": run(("git", "status", "--porcelain=v1")),
                },
                "lifecycleTools": tool_versions(),
            },
        }
        checksum = write_evidence(args.output, document)
    sys.stdout.write(json.dumps({"checkpoint": str(args.output), "sha256": checksum}, sort_keys=True) + "\n")
    return 0


def _read_sidecar(path: Path, expected_checksum: str, label: str = "checkpoint") -> None:
    sidecar = path.with_name(path.name + ".sha256")
    if not sidecar.is_file():
        refuse(f"{label} checksum sidecar is missing: {sidecar}")
    try:
        fields = sidecar.read_text(encoding="utf-8").split()
    except (OSError, UnicodeError) as error:
        msg = f"{label} checksum sidecar is invalid: {error}"
        raise RefusalError(msg) from error
    if len(fields) != SIDECAR_FIELD_COUNT or fields[0] != expected_checksum or fields[1] != path.name:
        refuse(f"{label} checksum sidecar is invalid")


def _read_document(path: Path, label: str) -> JsonObject:
    try:
        return _json_mapping(json.loads(path.read_text(encoding="utf-8")), f"{label} schema")
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        msg = f"{label} is not valid JSON: {error}"
        raise RefusalError(msg) from error


def _load_sealed_document(path: Path, expected_checksum: str, label: str) -> JsonObject:
    _recover_committed_evidence(path)
    if not path.is_file():
        refuse(f"{label} does not exist: {path}")
    if not SHA256_RE.fullmatch(expected_checksum):
        refuse(f"{label} checksum must be exactly 64 lowercase hexadecimal characters")
    actual = sha256(path)
    if actual != expected_checksum:
        refuse(f"{label} checksum mismatch: actual {actual}")
    _read_sidecar(path, expected_checksum, label)
    return _read_document(path, label)


def load_checkpoint(path: Path, expected_checksum: str, expected_context: str) -> JsonObject:
    """Load and validate a destruction checkpoint and checksum sidecar."""
    document = _load_sealed_document(path, expected_checksum, "checkpoint")
    if document.get("apiVersion") != API_VERSION or document.get("kind") != "LocalDestructionCheckpoint":
        refuse("checkpoint schema identity is invalid")
    metadata = _json_mapping(document.get("metadata"), "checkpoint metadata")
    if metadata.get("context") != expected_context:
        refuse("checkpoint context does not match expected context")
    if metadata.get("namespaceAllowlist") != [APP_NAMESPACE, FLUX_NAMESPACE]:
        refuse("checkpoint namespace allowlist is invalid")
    if not isinstance(metadata.get("owner"), str) or not metadata["owner"]:
        refuse("checkpoint owner is invalid")
    evidence = _json_mapping(document.get("evidence"), "checkpoint evidence")
    evidence["clusterIdentity"] = validate_identity(evidence.get("clusterIdentity"), "checkpoint cluster identity")
    return document


def validate_reset(args: argparse.Namespace) -> JsonObject:
    """Validate every destructive factory-reset authorization guard in stable order."""
    if not args.destructive:
        refuse("--destructive is required")
    if args.namespace != APP_NAMESPACE:
        refuse(f"namespace {args.namespace!r} is outside the reset allowlist")
    if args.acknowledge_data_loss != DATA_LOSS_ACK:
        refuse("exact --acknowledge-data-loss text is required")
    if args.acknowledge_factory_reset != FACTORY_ACK:
        refuse("exact --acknowledge-factory-reset text is required")
    context = require_context(args.expected_context)
    document = load_checkpoint(args.checkpoint, args.checkpoint_sha256, context)
    metadata = _json_mapping(document["metadata"], "checkpoint metadata")
    owner = metadata["owner"]
    if args.owner_authorization != f"I am the recorded owner {owner}":
        refuse("owner authorization does not match the checkpoint owner")
    return document


def _preflight_adapter(variable: str) -> list[str]:
    raw = os.environ.get(variable)
    if raw is None or not raw.strip():
        refuse(f"{variable} is unset or blank")
    try:
        argv = shlex.split(raw)
    except ValueError as error:
        msg = f"refused: {variable} is unparsable: {error}"
        raise RefusalError(msg) from error
    if not argv:
        refuse(f"{variable} is unset or blank")
    executable = shutil.which(argv[0])
    if executable is None or not Path(executable).is_file() or not os.access(executable, os.X_OK):
        refuse(f"{variable} executable is missing or non-executable: {argv[0]}")
    return [str(Path(executable).resolve()), *argv[1:]]


def preflight_adapters() -> tuple[list[str], list[str]]:
    """Resolve both trusted adapters before any destructive invocation."""
    purge = _preflight_adapter("NOHIKI_LOCAL_CLUSTER_PURGE_CMD")
    start = _preflight_adapter("NOHIKI_LOCAL_CLUSTER_START_CMD")
    return purge, start


class HeldLock:
    """Hold a non-blocking per-target advisory lock."""

    def __init__(self, descriptor: int) -> None:
        """Initialize a held descriptor."""
        self.descriptor = descriptor

    def __enter__(self) -> Self:
        """Return this held lock."""
        return self

    def __exit__(self, *_exc: object) -> None:
        """Release the held descriptor."""
        os.close(self.descriptor)


def target_lock_endpoint(endpoint: str, *, exclusive: bool) -> HeldLock:
    """Acquire the lock keyed by a normalized API server endpoint."""
    key = hashlib.sha256(normalize_api_server(endpoint).encode()).hexdigest()
    path = Path(tempfile.gettempdir()) / f"nohiki-local-cluster-{key}.lock"
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        fcntl.flock(descriptor, mode | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(descriptor)
        refuse("a factory-reset transaction is active for this cluster")
    return HeldLock(descriptor)


def target_lock(identity: JsonObject, *, exclusive: bool) -> HeldLock:
    """Acquire the lock keyed by normalized API server identity."""
    return target_lock_endpoint(str(identity["apiServer"]), exclusive=exclusive)


def _resolved_evidence_paths(path: Path) -> set[Path]:
    return {
        path.resolve(),
        path.with_name(path.name + ".sha256").resolve(),
    }


def require_disjoint_evidence_output(output: Path, *inputs: Path) -> None:
    """Refuse output aliases that could overwrite immutable input evidence."""
    output_paths = _resolved_evidence_paths(output)
    input_paths = set().union(*(_resolved_evidence_paths(path) for path in inputs))
    if output_paths & input_paths:
        refuse("evidence output aliases immutable input evidence")


def _checkpoint_identity(document: JsonObject) -> JsonObject:
    evidence = _json_mapping(document["evidence"], "checkpoint evidence")
    return validate_identity(evidence["clusterIdentity"], "checkpoint cluster identity")


def require_explicit_kubeconfig() -> None:
    """Refuse ambiguous ambient kubeconfig selection."""
    if not os.environ.get("KUBECONFIG", "").strip():
        refuse("KUBECONFIG must be explicitly set and non-empty")


def require_bound_live_identity(expected_context: str, expected: JsonObject) -> JsonObject:
    """Bind the live target to the checkpoint context, endpoint, and identity."""
    require_explicit_kubeconfig()
    require_context(expected_context)
    live = capture_cluster_identity(expected_context)
    if live != expected:
        refuse("live cluster identity does not match the checkpoint identity")
    return live


def _sanitize(text: str) -> str:
    if not text:
        return "no diagnostic"
    if re.search(r"secret|token|password|credential", text, re.IGNORECASE):
        return "sensitive diagnostic redacted"
    return text[:1000]


def _adapter(argv: Sequence[str], timeout: float) -> tuple[int, str]:
    """Run one trusted adapter without a shell or retries, killing its process group on timeout."""
    try:
        process = subprocess.Popen(  # noqa: S603  # argv[0] was resolved and validated during preflight.
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except OSError as error:
        return 127, f"spawn failed: {error}"
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        stdout, stderr = process.communicate()
        detail = (stderr or stdout).decode(errors="replace")
        return 124, f"adapter timed out after {timeout:g}s: {detail}"
    detail = (stderr or stdout).decode(errors="replace").strip()
    return process.returncode, detail


def _phase(name: str, *, argv: Sequence[str] | None = None) -> JsonObject:
    record: JsonObject = {"phase": name, "startedAt": now()}
    if argv is not None:
        record["argv"] = list(argv)
    return record


def _persist(path: Path, document: JsonObject) -> None:
    try:
        write_evidence(path, document)
    except OSError as error:
        msg = f"refused: evidence write failed: {error}"
        raise RefusalError(msg) from error


def _complete_phase(path: Path, document: JsonObject, record: JsonObject, *, detail: str | None = None) -> None:
    record["completedAt"] = now()
    if detail:
        record["detail"] = detail
    _persist(path, document)


def _fail_transaction(path: Path, document: JsonObject, message: str) -> NoReturn:
    diagnostic = _sanitize(message)
    document["status"] = "failed"
    document["diagnostic"] = diagnostic
    _persist(path, document)
    refuse(diagnostic)


def _adapter_phase(path: Path, document: JsonObject, name: str, argv: Sequence[str], timeout: float) -> None:
    phases = cast(list[object], document["phases"])
    record = _phase(name, argv=argv)
    phases.append(record)
    _persist(path, document)
    exit_code, detail = _adapter(argv, timeout)
    record["exitCode"] = exit_code
    record["completedAt"] = now()
    if detail:
        record["detail"] = _sanitize(detail)
    if exit_code != 0:
        _fail_transaction(path, document, f"{name} adapter failed: {detail}")
    _persist(path, document)


def _readyz(context: str, deadline: float) -> None:
    last = "API did not become ready"
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            refuse(f"readyz deadline exhausted; stale KUBECONFIG may select the wrong cluster: {last}")
        request_timeout = max(0.001, min(float(REQUEST_TIMEOUT_SECONDS), remaining))
        result = kubectl(
            "get",
            "--raw",
            "/readyz",
            "--context",
            context,
            f"--request-timeout={request_timeout:g}s",
            required=False,
            timeout=min(COMMAND_TIMEOUT_SECONDS, remaining),
        )
        if result["exitCode"] == 0:
            return
        last = str(result["stderr"] or result["stdout"])
        time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))


def _wait_nodes(context: str, deadline: float) -> None:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        refuse("node readiness deadline exhausted; stale KUBECONFIG may select the wrong cluster")
    result = kubectl(
        "wait",
        "--for=condition=Ready",
        "node",
        "--all",
        "--context",
        context,
        f"--timeout={remaining:g}s",
        required=False,
        timeout=remaining + 1.0,
    )
    if result["exitCode"] != 0:
        refuse(f"node readiness failed; stale KUBECONFIG may select the wrong cluster: {result['stderr']}")


def _nodes_ready(context: str, deadline: float) -> tuple[bool, str]:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return False, "node verification deadline exhausted"
    request_timeout = max(0.001, min(float(REQUEST_TIMEOUT_SECONDS), remaining))
    document = _parse_json_output(
        kubectl(
            "get",
            "nodes",
            "-o",
            "json",
            "--context",
            context,
            f"--request-timeout={request_timeout:g}s",
            timeout=min(COMMAND_TIMEOUT_SECONDS, remaining),
        ),
        "node list",
    )
    items = _json_list(document.get("items"), "node list items")
    if not items:
        return False, "zero nodes found"
    for item in items:
        node = _json_mapping(item, "node")
        status = _json_mapping(node.get("status"), "node status")
        conditions = _json_list(status.get("conditions"), "node conditions")
        if not any(
            isinstance(condition, dict)
            and condition.get("type") == "Ready"
            and str(condition.get("status")).lower() == "true"
            for condition in conditions
        ):
            return False, "node is not Ready"
    return True, "all nodes Ready"


def verify_absence(  # noqa: C901  # Each fail-closed observation is persisted in audit order.
    context: str,
    deadline: float,
    *,
    record: Callable[[JsonObject], None] | None = None,
) -> list[JsonObject]:
    """Verify the complete fresh-cluster absence and node invariants."""
    ready, node_detail = _nodes_ready(context, deadline)
    if not ready:
        refuse(node_detail)
    checks: list[JsonObject] = []

    def observed(check: JsonObject) -> None:
        checks.append(check)
        if record is not None:
            record(check)

    for namespace in ABSENT_NAMESPACES:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            refuse("absence verification deadline exhausted")
        request_timeout = max(0.001, min(float(REQUEST_TIMEOUT_SECONDS), remaining))
        result = kubectl(
            "get",
            "namespace",
            namespace,
            "--context",
            context,
            "-o",
            "json",
            f"--request-timeout={request_timeout:g}s",
            required=False,
            timeout=min(COMMAND_TIMEOUT_SECONDS, remaining),
        )
        if result["exitCode"] == 0:
            observed({"check": f"namespace {namespace} absent", "passed": False})
            refuse(f"namespace {namespace} remains present")
        diagnostic = str(result["stderr"] or result["stdout"])
        canonical_not_found = diagnostic.strip() == "NotFound" or re.fullmatch(
            r'Error from server \(NotFound\): namespaces? "[^"]+" not found',
            diagnostic.strip(),
        )
        if canonical_not_found is None or canonical_not_found is False:
            observed({"check": f"namespace {namespace} absent", "passed": False})
            refuse(f"namespace {namespace} absence check failed: {diagnostic}")
        observed({"check": f"namespace {namespace} absent", "passed": True})
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        refuse("absence verification deadline exhausted")
    request_timeout = max(0.001, min(float(REQUEST_TIMEOUT_SECONDS), remaining))
    crds = _parse_json_output(
        kubectl(
            "get",
            "customresourcedefinitions",
            "-o",
            "json",
            "--context",
            context,
            f"--request-timeout={request_timeout:g}s",
            timeout=min(COMMAND_TIMEOUT_SECONDS, remaining),
        ),
        "CRD list",
    )
    residue: list[str] = []
    for item in _json_list(crds.get("items"), "CRD list items"):
        metadata = _json_mapping(_json_mapping(item, "CRD").get("metadata"), "CRD metadata")
        name = metadata.get("name")
        if isinstance(name, str) and name.endswith(".fluxcd.io"):
            residue.append(name)
    observed({"check": "no CRD ending .fluxcd.io", "passed": not residue})
    if residue:
        refuse(f"Flux CRD residue ending .fluxcd.io: {', '.join(residue)}")
    return checks


def _validate_new_identity(old: JsonObject, new: JsonObject, started_at: str) -> None:
    if new["apiServer"] != old["apiServer"]:
        refuse("post-start API endpoint does not match checkpoint apiServer")
    if new["kubeSystemUid"] == old["kubeSystemUid"]:
        refuse("fresh cluster identity UID is unchanged")
    created = _parse_timestamp(new["kubeSystemCreatedAt"], "new cluster identity createdAt")
    old_created = _parse_timestamp(old["kubeSystemCreatedAt"], "old cluster identity createdAt")
    transaction_started = _parse_timestamp(started_at, "transaction startedAt")
    if created <= old_created:
        refuse("new cluster identity createdAt is not later than old identity")
    if created < transaction_started:
        refuse("new cluster identity createdAt predates the reset transaction")


def factory_reset(args: argparse.Namespace) -> int:  # noqa: PLR0915  # Preserve the audit-visible phase order.
    """Validate, preview, or execute a fresh-cluster factory reset."""
    checkpoint_document = validate_reset(args)
    require_disjoint_evidence_output(args.evidence_output, args.checkpoint)
    purge_argv, start_argv = preflight_adapters()
    old = _checkpoint_identity(checkpoint_document)
    endpoint = kubeconfig_api_server(args.expected_context)
    if endpoint != old["apiServer"]:
        refuse("live cluster apiServer does not match the checkpoint identity")
    with target_lock_endpoint(endpoint, exclusive=args.execute):
        live = require_bound_live_identity(args.expected_context, old)
        if not args.execute:
            sys.stdout.write(
                json.dumps(
                    {"purge": purge_argv, "start": start_argv, "oldIdentity": live},
                    sort_keys=True,
                )
                + "\n"
            )
            return 0
        metadata = _json_mapping(checkpoint_document["metadata"], "checkpoint metadata")
        started_at = now()
        document: JsonObject = {
            "apiVersion": API_VERSION,
            "kind": "LocalFactoryResetTransaction",
            "metadata": {
                "startedAt": started_at,
                "context": args.expected_context,
                "owner": metadata["owner"],
                "checkpoint": {
                    "basename": args.checkpoint.name,
                    "sha256": args.checkpoint_sha256,
                },
            },
            "phases": [],
            "identity": {"old": old},
            "absence": [],
            "status": "failed",
        }
        phases = cast(list[object], document["phases"])
        authorized = _phase("authorized")
        phases.append(authorized)
        _complete_phase(args.evidence_output, document, authorized)
        adapter_preflight = _phase("adapterPreflight")
        phases.append(adapter_preflight)
        _complete_phase(args.evidence_output, document, adapter_preflight)
        _adapter_phase(args.evidence_output, document, "purge", purge_argv, PURGE_TIMEOUT_SECONDS)
        _adapter_phase(args.evidence_output, document, "start", start_argv, START_TIMEOUT_SECONDS)
        readiness_deadline = time.monotonic() + READINESS_TIMEOUT_SECONDS
        api_phase = _phase("apiReady")
        phases.append(api_phase)
        _persist(args.evidence_output, document)
        try:
            endpoint = kubeconfig_api_server(args.expected_context)
            if endpoint != old["apiServer"]:
                refuse("post-start KUBECONFIG apiServer does not match checkpoint apiServer")
            _readyz(args.expected_context, readiness_deadline)
        except RefusalError as error:
            _fail_transaction(args.evidence_output, document, str(error))
        _complete_phase(args.evidence_output, document, api_phase)
        node_phase = _phase("nodeReady")
        phases.append(node_phase)
        _persist(args.evidence_output, document)
        try:
            _wait_nodes(args.expected_context, readiness_deadline)
        except RefusalError as error:
            _fail_transaction(args.evidence_output, document, str(error))
        _complete_phase(args.evidence_output, document, node_phase)
        identity_phase = _phase("identity")
        phases.append(identity_phase)
        _persist(args.evidence_output, document)
        try:
            require_context(args.expected_context)
            observed_identity = capture_cluster_identity_record(args.expected_context)
            identity = cast(JsonObject, document["identity"])
            identity["observed"] = observed_identity
            _persist(args.evidence_output, document)
            new = validate_identity(observed_identity, "new cluster identity")
            _validate_new_identity(old, new, started_at)
        except RefusalError as error:
            _fail_transaction(args.evidence_output, document, str(error))
        identity.pop("observed")
        identity["new"] = new
        _complete_phase(args.evidence_output, document, identity_phase)
        absence_phase = _phase("absence")
        phases.append(absence_phase)
        _persist(args.evidence_output, document)

        def record_absence(check: JsonObject) -> None:
            cast(list[object], document["absence"]).append(check)
            _persist(args.evidence_output, document)

        absence_deadline = time.monotonic() + READINESS_TIMEOUT_SECONDS
        try:
            verify_absence(
                args.expected_context,
                absence_deadline,
                record=record_absence,
            )
        except RefusalError as error:
            _fail_transaction(args.evidence_output, document, str(error))
        _complete_phase(args.evidence_output, document, absence_phase)
        document["status"] = "succeeded"
        _persist(args.evidence_output, document)
    sys.stdout.write(
        json.dumps(
            {"factoryReset": "succeeded", "evidence": str(args.evidence_output)},
            sort_keys=True,
        )
        + "\n"
    )
    return 0


def _fresh_identity_against_checkpoint(args: argparse.Namespace, live: JsonObject) -> JsonObject | None:
    if args.checkpoint is None and args.checkpoint_sha256 is None:
        return None
    if args.checkpoint is None or args.checkpoint_sha256 is None:
        refuse("--checkpoint and --checkpoint-sha256 must be provided together")
    checkpoint_document = load_checkpoint(args.checkpoint, args.checkpoint_sha256, args.expected_context)
    old = _checkpoint_identity(checkpoint_document)
    _validate_new_identity(
        old,
        live,
        str(_json_mapping(checkpoint_document["metadata"], "checkpoint metadata")["capturedAt"]),
    )
    return old


def zero_state(args: argparse.Namespace) -> int:
    """Verify read-only fresh-cluster zero state."""
    if args.namespace != APP_NAMESPACE:
        refuse(f"namespace {args.namespace!r} is outside the reset allowlist")
    inputs = () if args.checkpoint is None else (args.checkpoint,)
    require_disjoint_evidence_output(args.evidence_output, *inputs)
    endpoint = kubeconfig_api_server(args.expected_context)
    with target_lock_endpoint(endpoint, exclusive=False):
        context = require_context(args.expected_context)
        live = capture_cluster_identity(context)
        if live["apiServer"] != endpoint:
            refuse("KUBECONFIG endpoint changed during zero-state verification")
        old = _fresh_identity_against_checkpoint(args, live)
        deadline = time.monotonic() + READINESS_TIMEOUT_SECONDS
        absence = verify_absence(context, deadline)
        document: JsonObject = {
            "apiVersion": API_VERSION,
            "kind": "LocalZeroStateEvidence",
            "metadata": {"capturedAt": now(), "context": context},
            "identity": {"old": old, "new": live} if old is not None else {"new": live},
            "absence": absence,
            "status": "succeeded",
        }
        checksum = write_evidence(args.evidence_output, document)
    sys.stdout.write(json.dumps({"evidence": str(args.evidence_output), "sha256": checksum}, sort_keys=True) + "\n")
    return 0


def _validate_transaction_metadata(
    value: object, *, context: str, checkpoint: Path, checkpoint_checksum: str
) -> dt.datetime:
    metadata = _json_mapping(value, "reset transaction metadata")
    if set(metadata) != {"startedAt", "context", "owner", "checkpoint"}:
        refuse("reset transaction metadata schema is invalid")
    started = _parse_timestamp(metadata.get("startedAt"), "reset transaction startedAt")
    if metadata.get("context") != context:
        refuse("reset transaction context does not match expected context")
    if not isinstance(metadata.get("owner"), str) or not metadata["owner"]:
        refuse("reset transaction owner is invalid")
    binding = _json_mapping(metadata.get("checkpoint"), "reset transaction checkpoint")
    if binding != {"basename": checkpoint.name, "sha256": checkpoint_checksum}:
        refuse("reset transaction is not bound to the checkpoint")
    return started


def _validate_transaction_phase(value: object, expected_phase: str, previous: dt.datetime) -> dt.datetime:
    record = _json_mapping(value, "reset transaction phase")
    adapter = expected_phase in {"purge", "start"}
    allowed = {"phase", "startedAt", "completedAt", "detail"}
    if adapter:
        allowed |= {"argv", "exitCode"}
    if set(record) - allowed or record.get("phase") != expected_phase:
        refuse("reset transaction phase schema is invalid")
    started = _parse_timestamp(record.get("startedAt"), "reset transaction phase startedAt")
    completed = _parse_timestamp(record.get("completedAt"), "reset transaction phase completedAt")
    if started < previous or completed < started:
        refuse("reset transaction phase ordering is invalid")
    detail = record.get("detail")
    if detail is not None and not isinstance(detail, str):
        refuse("reset transaction phase detail is invalid")
    if not adapter:
        if "argv" in record or "exitCode" in record:
            refuse("reset transaction non-adapter phase is invalid")
        return completed
    argv = _json_list(record.get("argv"), "reset transaction adapter argv")
    if (
        not argv
        or not all(isinstance(part, str) for part in argv)
        or not Path(cast(str, argv[0])).is_absolute()
        or type(record.get("exitCode")) is not int
        or record["exitCode"] != 0
    ):
        refuse("reset transaction adapter phase is invalid")
    return completed


def _validate_transaction_phases(value: object, transaction_started: dt.datetime) -> None:
    phases = _json_list(value, "reset transaction phases")
    if len(phases) != len(TRANSACTION_PHASES):
        refuse("reset transaction phase schema is invalid")
    previous = transaction_started
    for expected_phase, record in zip(TRANSACTION_PHASES, phases, strict=True):
        previous = _validate_transaction_phase(record, expected_phase, previous)


def _validate_transaction_identity(value: object, checkpoint_document: JsonObject) -> JsonObject:
    identities = _json_mapping(value, "reset transaction identity")
    if set(identities) != {"old", "new"}:
        refuse("reset transaction identity schema is invalid")
    old = validate_identity(identities.get("old"), "reset transaction old identity")
    if old != _checkpoint_identity(checkpoint_document):
        refuse("reset transaction old identity does not match the checkpoint")
    return validate_identity(identities.get("new"), "reset transaction new identity")


def _validate_transaction_absence(value: object) -> None:
    absence = _json_list(value, "reset transaction absence")
    expected_checks = [f"namespace {namespace} absent" for namespace in ABSENT_NAMESPACES]
    expected_checks.append("no CRD ending .fluxcd.io")
    if len(absence) != len(expected_checks):
        refuse("reset transaction absence schema is invalid")
    for expected_check, record_value in zip(expected_checks, absence, strict=True):
        record = _json_mapping(record_value, "reset transaction absence record")
        if record != {"check": expected_check, "passed": True}:
            refuse("reset transaction absence proof is invalid")


def _validate_success_transaction(
    transaction: JsonObject,
    *,
    context: str,
    checkpoint: Path,
    checkpoint_checksum: str,
    checkpoint_document: JsonObject,
) -> JsonObject:
    if set(transaction) != {
        "apiVersion",
        "kind",
        "metadata",
        "phases",
        "identity",
        "absence",
        "status",
    }:
        refuse("reset transaction schema or status is invalid")
    if (
        transaction.get("apiVersion") != API_VERSION
        or transaction.get("kind") != "LocalFactoryResetTransaction"
        or transaction.get("status") != "succeeded"
    ):
        refuse("reset transaction schema or status is invalid")
    started = _validate_transaction_metadata(
        transaction.get("metadata"),
        context=context,
        checkpoint=checkpoint,
        checkpoint_checksum=checkpoint_checksum,
    )
    _validate_transaction_phases(transaction.get("phases"), started)
    new = _validate_transaction_identity(transaction.get("identity"), checkpoint_document)
    _validate_new_identity(
        _checkpoint_identity(checkpoint_document),
        new,
        started.isoformat(),
    )
    _validate_transaction_absence(transaction.get("absence"))
    return new


def recovery_evidence(args: argparse.Namespace) -> int:
    """Bind recovery evidence to a succeeded reset transaction."""
    require_disjoint_evidence_output(
        args.output,
        args.checkpoint,
        args.reset_transaction,
    )
    endpoint = kubeconfig_api_server(args.expected_context)
    with target_lock_endpoint(endpoint, exclusive=False):
        context = require_context(args.expected_context)
        checkpoint_document = load_checkpoint(args.checkpoint, args.checkpoint_sha256, context)
        transaction = _load_sealed_document(args.reset_transaction, args.reset_transaction_sha256, "reset transaction")
        expected_new = _validate_success_transaction(
            transaction,
            context=context,
            checkpoint=args.checkpoint,
            checkpoint_checksum=args.checkpoint_sha256,
            checkpoint_document=checkpoint_document,
        )
        live = capture_cluster_identity(context)
        if live["apiServer"] != endpoint:
            refuse("KUBECONFIG endpoint changed during recovery evidence capture")
        if live != expected_new:
            refuse("live recovery identity does not match the reset transaction")
        old = _checkpoint_identity(checkpoint_document)
        document: JsonObject = {
            "apiVersion": API_VERSION,
            "kind": "LocalRecoveryEvidence",
            "metadata": {"capturedAt": now(), "context": context},
            "evidence": {
                "clusterIdentity": live,
                "checkpointIdentity": old,
                "resetTransaction": {
                    "basename": args.reset_transaction.name,
                    "sha256": args.reset_transaction_sha256,
                },
            },
        }
        checksum = write_evidence(args.output, document)
    sys.stdout.write(json.dumps({"evidence": str(args.output), "sha256": checksum}, sort_keys=True) + "\n")
    return 0


def add_context(parser: argparse.ArgumentParser) -> None:
    """Add the exact-context guard argument."""
    parser.add_argument("--expected-context", required=True)


def parser() -> argparse.ArgumentParser:
    """Build the fresh-cluster evidence CLI."""
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)

    checkpoint_parser = commands.add_parser("checkpoint")
    add_context(checkpoint_parser)
    checkpoint_parser.add_argument("--output", type=Path, required=True)
    checkpoint_parser.add_argument("--owner")
    checkpoint_parser.add_argument("--runtime-control-ref", default="HEAD")
    checkpoint_parser.add_argument("--reviewed-topic", action="append", default=[])
    checkpoint_parser.set_defaults(handler=checkpoint)

    factory = commands.add_parser("factory-reset")
    add_context(factory)
    factory.add_argument("--namespace", required=True)
    factory.add_argument("--checkpoint", type=Path, required=True)
    factory.add_argument("--checkpoint-sha256", required=True)
    factory.add_argument("--acknowledge-data-loss", required=True)
    factory.add_argument("--owner-authorization", required=True)
    factory.add_argument("--acknowledge-factory-reset", required=True)
    factory.add_argument("--destructive", action="store_true")
    factory.add_argument("--execute", action="store_true")
    factory.add_argument("--evidence-output", type=Path, required=True)
    factory.set_defaults(handler=factory_reset)

    zero = commands.add_parser("zero-state")
    add_context(zero)
    zero.add_argument("--namespace", required=True)
    zero.add_argument("--checkpoint", type=Path)
    zero.add_argument("--checkpoint-sha256")
    zero.add_argument("--evidence-output", type=Path, required=True)
    zero.set_defaults(handler=zero_state)

    recovery = commands.add_parser("recovery-evidence")
    add_context(recovery)
    recovery.add_argument("--checkpoint", type=Path, required=True)
    recovery.add_argument("--checkpoint-sha256", required=True)
    recovery.add_argument("--reset-transaction", type=Path, required=True)
    recovery.add_argument("--reset-transaction-sha256", required=True)
    recovery.add_argument("--output", type=Path, required=True)
    recovery.set_defaults(handler=recovery_evidence)
    return root


def main() -> int:
    """Run the CLI and preserve refusal exit semantics."""
    args = parser().parse_args()
    handler = cast(Callable[[argparse.Namespace], int], args.handler)
    try:
        return handler(args)
    except RefusalError as error:
        sys.stderr.write(f"{error}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
