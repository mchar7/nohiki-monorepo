#!/usr/bin/env python3
"""Capture local-cluster evidence and guard destructive Nohiki resets."""

from __future__ import annotations

import argparse
import datetime as dt
import getpass
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any, NoReturn

API_VERSION = "nohiki.io/v1alpha1"
APP_NAMESPACE = "nohiki"
FLUX_NAMESPACE = "flux-system"
DATA_LOSS_ACK = "I understand this permanently deletes local Nohiki data"
FACTORY_ACK = "I understand factory reset removes the Nohiki and Flux local control planes"
SHA256_RE = re.compile(r"[0-9a-f]{64}")
REF_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/@+-]{0,254}")
IMAGE_NAME_RE = re.compile(r"[a-z0-9]+(?:[._-][a-z0-9]+)*")
IMAGE_REF_RE = re.compile(
    r"localhost:5000/[a-z0-9]+(?:[._-][a-z0-9]+)*(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)*(?::[A-Za-z0-9_][A-Za-z0-9._-]{0,127}|@sha256:[0-9a-f]{64})"
)
SIDECAR_FIELD_COUNT = 2
TRUSTED_COMMANDS = frozenset({"age", "flux", "git", "helm", "k3s", "kubectl", "sops", "sudo"})
NORMAL_RESET_KUSTOMIZATIONS = (
    "observability",
    "platform",
    "runtime-secrets",
    "infrastructure",
    "gateway-api-crds",
)
FACTORY_RESET_KUSTOMIZATIONS = (
    "playwright-verification",
    "api-verification",
    "health-verification",
    "observability",
    "platform",
    "runtime-secrets",
    "infrastructure",
    "registry",
    "gateway-api-crds",
    FLUX_NAMESPACE,
)
FACTORY_NAMESPACES = (
    "nohiki-verification",
    APP_NAMESPACE,
    "nohiki-foundation",
    "nohiki-registry",
    FLUX_NAMESPACE,
)
VERIFY_STAGES = ("browser", "api", "health")
CLUSTER_RESOURCE_BY_KIND = {
    "ValidatingWebhookConfiguration": "validatingwebhookconfigurations.admissionregistration.k8s.io",
    "MutatingWebhookConfiguration": "mutatingwebhookconfigurations.admissionregistration.k8s.io",
    "ValidatingAdmissionPolicyBinding": "validatingadmissionpolicybindings.admissionregistration.k8s.io",
    "ValidatingAdmissionPolicy": "validatingadmissionpolicies.admissionregistration.k8s.io",
    "CustomResourceDefinition": "customresourcedefinitions.apiextensions.k8s.io",
    "ClusterRoleBinding": "clusterrolebindings.rbac.authorization.k8s.io",
    "ClusterRole": "clusterroles.rbac.authorization.k8s.io",
}
CLUSTER_RESOURCE_QUERY = ",".join(CLUSTER_RESOURCE_BY_KIND.values())
HELM_STORAGE_NAMESPACES = {
    "nohiki": APP_NAMESPACE,
    "nohiki-foundation": "nohiki-foundation",
}
HELM_NAME_LABEL = "helm.toolkit.fluxcd.io/name"
HELM_NAMESPACE_LABEL = "helm.toolkit.fluxcd.io/namespace"
KUSTOMIZE_NAME_LABEL = "kustomize.toolkit.fluxcd.io/name"
KUSTOMIZE_NAMESPACE_LABEL = "kustomize.toolkit.fluxcd.io/namespace"
FLUX_PART_OF_LABEL = "app.kubernetes.io/part-of"
FLUX_INSTANCE_LABEL = "app.kubernetes.io/instance"


class RefusalError(RuntimeError):
    """Represent a fail-closed refusal safe to show to an operator."""


def refuse(message: str) -> NoReturn:
    """Raise an operator-facing, fail-closed refusal."""
    msg = f"refused: {message}"
    raise RefusalError(msg)


def run(command: Sequence[str], *, required: bool = True) -> dict[str, Any]:
    """Run an allowlisted command and capture its result."""
    command_parts = tuple(command)
    if not command_parts or command_parts[0] not in TRUSTED_COMMANDS:
        refuse("command is outside the trusted executable allowlist")
    executable = shutil.which(command_parts[0])
    if executable is None:
        error = FileNotFoundError(command_parts[0])
        if required:
            msg = f"cannot execute {command_parts[0]}: {error}"
            raise RefusalError(msg) from error
        return {
            "command": list(command_parts),
            "exitCode": None,
            "stdout": "",
            "stderr": str(error),
        }
    argv = (executable, *command_parts[1:])
    try:
        with (
            tempfile.TemporaryFile(mode="w+", encoding="utf-8") as stdout,
            tempfile.TemporaryFile(mode="w+", encoding="utf-8") as stderr,
        ):
            file_actions = (
                (os.POSIX_SPAWN_DUP2, stdout.fileno(), sys.stdout.fileno()),
                (os.POSIX_SPAWN_DUP2, stderr.fileno(), sys.stderr.fileno()),
            )
            process_id = os.posix_spawn(executable, argv, os.environ, file_actions=file_actions)
            _, wait_status = os.waitpid(process_id, 0)
            stdout.seek(0)
            stderr.seek(0)
            exit_code = os.waitstatus_to_exitcode(wait_status)
            captured_stdout = stdout.read()
            captured_stderr = stderr.read()
    except OSError as error:
        if required:
            msg = f"cannot execute {command_parts[0]}: {error}"
            raise RefusalError(msg) from error
        return {
            "command": list(command_parts),
            "exitCode": None,
            "stdout": "",
            "stderr": str(error),
        }
    result = {
        "command": list(command_parts),
        "exitCode": exit_code,
        "stdout": captured_stdout.rstrip(),
        "stderr": captured_stderr.rstrip(),
    }
    if required and exit_code != 0:
        detail = captured_stderr.strip() or captured_stdout.strip() or "no diagnostic"
        msg = f"read-only command failed ({' '.join(command_parts)}): {detail}"
        raise RefusalError(msg)
    return result


def kubectl(*arguments: str, required: bool = True) -> dict[str, Any]:
    """Run kubectl with trusted executable resolution."""
    return run(("kubectl", *arguments), required=required)


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


def atomic_write(path: Path, content: bytes) -> None:
    """Atomically write private file content."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def write_evidence(path: Path, document: dict[str, Any]) -> str:
    """Write evidence and its checksum sidecar, returning the digest."""
    payload = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode()
    atomic_write(path, payload)
    checksum = sha256(path)
    atomic_write(path.with_name(path.name + ".sha256"), f"{checksum}  {path.name}\n".encode())
    return checksum


def git_sha(ref: str) -> str:
    """Resolve a validated Git ref to a commit SHA."""
    if not REF_RE.fullmatch(ref):
        refuse(f"invalid Git ref {ref!r}")
    result = run(("git", "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}"))
    value = str(result["stdout"])
    if not re.fullmatch(r"[0-9a-f]{40,64}", value):
        refuse(f"Git ref {ref!r} did not resolve to a commit SHA")
    return value


def parse_topics(values: Sequence[str]) -> dict[str, dict[str, str]]:
    """Parse reviewed topic assignments and resolve their refs."""
    topics: dict[str, dict[str, str]] = {}
    for value in values:
        name, separator, ref = value.partition("=")
        if not separator or not REF_RE.fullmatch(name) or not ref:
            refuse(f"reviewed topic must be NAME=GIT_REF, got {value!r}")
        topics[name] = {"ref": ref, "sha": git_sha(ref)}
    return topics


def command_inventory() -> dict[str, dict[str, Any]]:
    """Capture the read-only cluster command inventory."""
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
        "containerdImages": run(("sudo", "-n", "k3s", "ctr", "images", "list"), required=False),
    }


def tool_versions() -> dict[str, dict[str, Any]]:
    """Capture available lifecycle tool versions."""
    return {
        "kubectl": kubectl("version", "--client", "-o", "json"),
        "flux": run(("flux", "--version"), required=False),
        "helm": run(("helm", "version", "--short"), required=False),
        "k3s": run(("k3s", "--version"), required=False),
        "sops": run(("sops", "--version"), required=False),
        "age": run(("age", "--version"), required=False),
    }


def checkpoint(args: argparse.Namespace) -> int:
    """Capture a guarded pre-destruction checkpoint."""
    context = require_context(args.expected_context)
    owner = args.owner or getpass.getuser()
    if not owner or any(character.isspace() for character in owner):
        refuse("owner must be a non-empty identifier without whitespace")
    document = {
        "apiVersion": API_VERSION,
        "kind": "LocalDestructionCheckpoint",
        "metadata": {
            "capturedAt": dt.datetime.now(dt.UTC).isoformat(),
            "context": context,
            "namespaceAllowlist": [APP_NAMESPACE, FLUX_NAMESPACE],
            "owner": owner,
        },
        "evidence": {
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


def _read_sidecar(path: Path, expected_checksum: str) -> None:
    sidecar = path.with_name(path.name + ".sha256")
    if not sidecar.is_file():
        refuse(f"checkpoint checksum sidecar is missing: {sidecar}")
    try:
        sidecar_fields = sidecar.read_text(encoding="utf-8").split()
    except (OSError, UnicodeError) as error:
        msg = f"checkpoint checksum sidecar is invalid: {error}"
        raise RefusalError(msg) from error
    if (
        len(sidecar_fields) != SIDECAR_FIELD_COUNT
        or sidecar_fields[0] != expected_checksum
        or sidecar_fields[1] != path.name
    ):
        refuse("checkpoint checksum sidecar is invalid")


def _read_checkpoint_document(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        msg = f"checkpoint is not valid JSON: {error}"
        raise RefusalError(msg) from error
    if not isinstance(document, dict):
        refuse("checkpoint schema identity is invalid")
    return document


def load_checkpoint(path: Path, expected_checksum: str, expected_context: str) -> dict[str, Any]:
    """Load and validate a destruction checkpoint and checksum sidecar."""
    if not path.is_file():
        refuse(f"checkpoint does not exist: {path}")
    if not SHA256_RE.fullmatch(expected_checksum):
        refuse("checkpoint checksum must be exactly 64 lowercase hexadecimal characters")
    actual_checksum = sha256(path)
    if actual_checksum != expected_checksum:
        refuse(f"checkpoint checksum mismatch: actual {actual_checksum}")
    _read_sidecar(path, expected_checksum)
    document = _read_checkpoint_document(path)
    if document.get("apiVersion") != API_VERSION or document.get("kind") != "LocalDestructionCheckpoint":
        refuse("checkpoint schema identity is invalid")
    metadata = document.get("metadata")
    if not isinstance(metadata, dict) or metadata.get("context") != expected_context:
        refuse("checkpoint context does not match expected context")
    if metadata.get("namespaceAllowlist") != [APP_NAMESPACE, FLUX_NAMESPACE]:
        refuse("checkpoint namespace allowlist is invalid")
    if not isinstance(metadata.get("owner"), str) or not metadata["owner"]:
        refuse("checkpoint owner is invalid")
    return document


def validate_reset(args: argparse.Namespace, *, factory: bool) -> dict[str, Any]:
    """Validate every destructive-reset authorization guard."""
    if not args.destructive:
        refuse("--destructive is required")
    if args.namespace != APP_NAMESPACE:
        refuse(f"namespace {args.namespace!r} is outside the reset allowlist")
    if args.acknowledge_data_loss != DATA_LOSS_ACK:
        refuse("exact --acknowledge-data-loss text is required")
    if factory and args.acknowledge_factory_reset != FACTORY_ACK:
        refuse("exact --acknowledge-factory-reset text is required")
    context = require_context(args.expected_context)
    document = load_checkpoint(args.checkpoint, args.checkpoint_sha256, context)
    owner = document["metadata"]["owner"]
    if args.owner_authorization != f"I am the recorded owner {owner}":
        refuse("owner authorization does not match the checkpoint owner")
    return document


def existing_kustomizations(*, factory: bool) -> list[str]:
    """Return the ordered reset scope after refusing unrelated Flux objects."""
    result = kubectl(
        "get",
        "kustomizations.kustomize.toolkit.fluxcd.io",
        "-n",
        FLUX_NAMESPACE,
        "-o",
        "jsonpath={range .items[*]}{.metadata.name}{'\\n'}{end}",
    )
    existing = set(str(result["stdout"]).splitlines())
    unexpected = sorted(existing.difference(FACTORY_RESET_KUSTOMIZATIONS))
    if unexpected:
        refuse(f"unrelated Flux Kustomizations are present and protected: {', '.join(unexpected)}")
    allowlist = FACTORY_RESET_KUSTOMIZATIONS if factory else NORMAL_RESET_KUSTOMIZATIONS
    return [name for name in allowlist if name in existing]


def _json_items(result: dict[str, Any], description: str) -> list[object]:
    try:
        document = json.loads(str(result["stdout"]))
    except json.JSONDecodeError as error:
        refuse(f"{description} returned malformed Kubernetes JSON: {error}")
    if not isinstance(document, dict) or not isinstance(document.get("items"), list):
        refuse(f"{description} returned malformed Kubernetes JSON items")
    return document["items"]


def _capture_managed_pvcs(
    items: Sequence[object],
) -> dict[tuple[str, str], tuple[str, str | None]]:
    captured: dict[tuple[str, str], tuple[str, str | None]] = {}
    for item in items:
        if not isinstance(item, dict):
            refuse("PVC inventory contains a malformed item")
        metadata = item.get("metadata")
        if not isinstance(metadata, dict):
            refuse("PVC inventory contains malformed ownership metadata")
        namespace = metadata.get("namespace")
        if namespace not in FACTORY_NAMESPACES:
            continue
        name = metadata.get("name")
        spec = item.get("spec")
        if not isinstance(namespace, str) or not isinstance(name, str) or not name:
            refuse("managed PVC has missing or malformed namespace/name metadata")
        if not isinstance(spec, dict):
            refuse(f"managed PVC {namespace}/{name} has malformed spec")
        volume_name = spec.get("volumeName", "")
        uid = metadata.get("uid")
        if not isinstance(volume_name, str):
            refuse(f"managed PVC {namespace}/{name} has malformed volumeName")
        if uid is not None and not isinstance(uid, str):
            refuse(f"managed PVC {namespace}/{name} has malformed UID metadata")
        key = (namespace, name)
        if key in captured:
            refuse(f"PVC inventory contains duplicate ownership metadata for {namespace}/{name}")
        captured[key] = (volume_name, uid)
    return captured


def _index_pvs(items: Sequence[object]) -> dict[str, dict[str, object]]:
    pvs: dict[str, dict[str, object]] = {}
    for item in items:
        if not isinstance(item, dict):
            refuse("PV inventory contains a malformed item")
        metadata = item.get("metadata")
        if not isinstance(metadata, dict) or not isinstance(metadata.get("name"), str):
            refuse("PV inventory contains malformed name metadata")
        name = metadata["name"]
        if not name or name in pvs:
            refuse(f"PV inventory contains conflicting name metadata for {name!r}")
        pvs[name] = item
    return pvs


def _pv_claim_owner(
    pv_name: str,
    item: dict[str, object],
    bound_pv_names: frozenset[str],
) -> tuple[str, str, object] | None:
    spec = item.get("spec")
    claim_ref = spec.get("claimRef") if isinstance(spec, dict) else None
    if not isinstance(claim_ref, dict):
        if pv_name in bound_pv_names:
            refuse(f"bound PV {pv_name} has missing or malformed claimRef")
        return None
    namespace = claim_ref.get("namespace")
    name = claim_ref.get("name")
    if not isinstance(namespace, str) or not isinstance(name, str) or not namespace or not name:
        if namespace in FACTORY_NAMESPACES or pv_name in bound_pv_names:
            refuse(f"PV {pv_name} has missing or malformed claimRef ownership")
        return None
    return namespace, name, claim_ref.get("uid")


def capture_factory_storage() -> list[tuple[str, str, str]]:
    """Capture managed PVCs and prove exact ownership of their bound PVs."""
    captured = _capture_managed_pvcs(
        _json_items(
            kubectl("get", "persistentvolumeclaims", "--all-namespaces", "-o", "json"),
            "PVC inventory",
        )
    )
    pvs = _index_pvs(
        _json_items(
            kubectl("get", "persistentvolumes", "-o", "json"),
            "PV inventory",
        )
    )
    bound_names = frozenset(volume_name for volume_name, _ in captured.values() if volume_name)
    owned: dict[tuple[str, str], str] = {}
    for pv_name, item in pvs.items():
        owner = _pv_claim_owner(pv_name, item, bound_names)
        if owner is None:
            continue
        key = owner[:2]
        if key not in captured:
            if key[0] in FACTORY_NAMESPACES:
                refuse(
                    f"PV {pv_name} claimRef ownership {key[0]}/{key[1]} "
                    "is absent from the captured managed PVC inventory"
                )
            continue
        volume_name, pvc_uid = captured[key]
        if volume_name != pv_name or (pvc_uid is not None and owner[2] != pvc_uid) or key in owned:
            refuse(f"PV {pv_name} has conflicting ownership metadata for {key[0]}/{key[1]}")
        owned[key] = pv_name

    records: list[tuple[str, str, str]] = []
    for (namespace, name), (volume_name, _) in captured.items():
        if volume_name and owned.get((namespace, name)) != volume_name:
            refuse(f"bound PVC {namespace}/{name} has no matching PV claimRef")
        records.append((namespace, name, volume_name))
    return records


def load_local_image_names() -> frozenset[str]:
    """Load the strict first-party local image owner inventory."""
    path = Path(__file__).with_name("images.json")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        refuse(f"cannot load local image ownership inventory {path}: {error}")
    if (
        not isinstance(document, dict)
        or document.get("schemaVersion") != 1
        or not isinstance(document.get("images"), list)
    ):
        refuse("local image ownership inventory has an invalid schema")
    names: set[str] = set()
    seen: set[str] = set()
    for item in document["images"]:
        if not isinstance(item, dict):
            refuse("local image ownership inventory contains a malformed entry")
        name = item.get("name")
        local = item.get("local")
        if (
            not isinstance(name, str)
            or IMAGE_NAME_RE.fullmatch(name) is None
            or not isinstance(local, bool)
            or name in seen
        ):
            refuse("local image ownership inventory contains an invalid or duplicate name")
        seen.add(name)
        if local:
            names.add(name)
    if not names:
        refuse("local image ownership inventory contains no owned local images")
    return frozenset(names)


def native_image_refs(local_names: frozenset[str]) -> list[str]:
    """Return exact owned native-k3s refs, refusing malformed local refs."""
    result = run(("sudo", "-n", "k3s", "ctr", "-n", "k8s.io", "images", "ls", "-q"))
    owned: list[str] = []
    for ref in str(result["stdout"]).splitlines():
        if not ref.startswith("localhost:5000/"):
            continue
        if IMAGE_REF_RE.fullmatch(ref) is None:
            refuse(f"malformed local-registry containerd image ref {ref!r}")
        repository = ref.removeprefix("localhost:5000/").split("@", 1)[0].split(":", 1)[0]
        if repository in local_names:
            owned.append(ref)
    return owned


def _metadata_strings(value: object, description: str) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict) or not all(
        isinstance(key, str) and isinstance(item, str) for key, item in value.items()
    ):
        refuse(f"cluster-scoped object has malformed {description} metadata")
    return value


def _has_protected_cluster_ownership(labels: dict[str, str], annotations: dict[str, str]) -> bool:
    protected_keys = (
        "kubernetes.io/bootstrapping",
        "rbac.authorization.kubernetes.io/autoupdate",
    )
    return any(
        key in protected_keys or key.startswith(("objectset.rio.cattle.io/", "k3s.io/")) for key in labels | annotations
    )


def _cluster_owner(
    labels: dict[str, str],
    annotations: dict[str, str],
    identity: str,
) -> str | None:
    helm_name = labels.get(HELM_NAME_LABEL)
    claims_helm = helm_name in HELM_STORAGE_NAMESPACES
    claims_kustomize = labels.get(KUSTOMIZE_NAME_LABEL) in FACTORY_RESET_KUSTOMIZATIONS
    claims_flux = labels.get(FLUX_PART_OF_LABEL) == "flux"
    if (
        (claims_helm and labels.get(HELM_NAMESPACE_LABEL) != FLUX_NAMESPACE)
        or (claims_kustomize and labels.get(KUSTOMIZE_NAMESPACE_LABEL) != FLUX_NAMESPACE)
        or (claims_flux and labels.get(FLUX_INSTANCE_LABEL) != FLUX_NAMESPACE)
    ):
        refuse(f"{identity} has mismatched partial ownership label tuples")
    owners = [
        owner
        for owner, selected in (
            ("Helm", claims_helm),
            ("Kustomize", claims_kustomize),
            ("Flux", claims_flux),
        )
        if selected
    ]
    if len(owners) > 1:
        refuse(f"{identity} has ambiguous overlapping ownership")
    if not owners:
        return None
    if owners[0] == "Helm":
        expected_namespace = HELM_STORAGE_NAMESPACES[str(helm_name)]
        has_helm_annotations = any(key.startswith("meta.helm.sh/") for key in annotations)
        if has_helm_annotations and (
            annotations.get("meta.helm.sh/release-name") != helm_name
            or annotations.get("meta.helm.sh/release-namespace") != expected_namespace
        ):
            refuse(f"{identity}: selected Helm object has mismatched release annotations")
        if labels.get("app.kubernetes.io/managed-by", "Helm") != "Helm":
            refuse(f"{identity} has conflicting Helm managed-by ownership")
    if _has_protected_cluster_ownership(labels, annotations):
        refuse(f"{identity} has protected system/bootstrap/k3s objectset ownership")
    return owners[0]


def capture_factory_cluster_objects() -> list[tuple[str, str]]:
    """Capture exact-owned built-in cluster-scoped objects."""
    items = _json_items(
        kubectl("get", CLUSTER_RESOURCE_QUERY, "-o", "json"),
        "cluster-scoped inventory",
    )
    captured: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        if not isinstance(item, dict):
            refuse("cluster-scoped inventory contains a malformed item")
        kind = item.get("kind")
        metadata = item.get("metadata")
        if kind not in CLUSTER_RESOURCE_BY_KIND or not isinstance(metadata, dict):
            refuse("cluster-scoped inventory contains malformed kind/metadata")
        name = metadata.get("name")
        if not isinstance(name, str) or not name:
            refuse("cluster-scoped object has malformed name metadata")
        labels = _metadata_strings(metadata.get("labels"), "label")
        annotations = _metadata_strings(metadata.get("annotations"), "annotation")
        identity = f"{kind}/{name}"
        owner = _cluster_owner(labels, annotations, identity)
        owner_references = metadata.get("ownerReferences", [])
        if not isinstance(owner_references, list):
            refuse("cluster-scoped object has malformed ownerReferences metadata")
        if owner is None:
            continue
        if owner_references:
            refuse(f"{identity} has unexpected ownerReferences")
        key = (CLUSTER_RESOURCE_BY_KIND[str(kind)], name)
        if key in seen:
            refuse(f"cluster-scoped inventory contains duplicate object {key[0]}/{name}")
        seen.add(key)
        captured.append(key)
    order = {resource: index for index, resource in enumerate(CLUSTER_RESOURCE_BY_KIND.values())}
    return sorted(captured, key=lambda item: (order[item[0]], item[1]))


def reset_plan(
    names: Sequence[str],
    *,
    factory: bool,
    storage: Sequence[tuple[str, str, str]] = (),
    cluster_objects: Sequence[tuple[str, str]] = (),
    image_refs: Sequence[str] = (),
) -> list[list[str]]:
    """Build the ordered reset command DAG."""
    plan = [["flux", "suspend", "kustomization", name, "-n", FLUX_NAMESPACE] for name in names]
    plan.extend(
        [
            "kubectl",
            "delete",
            "jobs.batch",
            "-n",
            APP_NAMESPACE,
            "-l",
            f"nohiki.io/verification-stage={stage}",
            "--ignore-not-found",
            "--wait=true",
        ]
        for stage in VERIFY_STAGES
    )
    plan.extend(
        [
            "kubectl",
            "delete",
            "kustomizations.kustomize.toolkit.fluxcd.io",
            name,
            "-n",
            FLUX_NAMESPACE,
            "--wait=false",
        ]
        for name in names
    )
    if factory:
        plan.extend(
            [
                "kubectl",
                "delete",
                resource,
                object_name,
                "--ignore-not-found",
                "--wait=false",
            ]
            for resource, object_name in cluster_objects
        )
        plan.extend(
            [
                "kubectl",
                "delete",
                "namespace",
                namespace,
                "--ignore-not-found",
                "--wait=false",
            ]
            for namespace in FACTORY_NAMESPACES
        )
        plan.extend(
            [
                "kubectl",
                "delete",
                "persistentvolume",
                pv_name,
                "--ignore-not-found",
                "--wait=false",
            ]
            for _, _, pv_name in storage
            if pv_name
        )
        plan.extend(["sudo", "-n", "k3s", "ctr", "-n", "k8s.io", "images", "rm", ref] for ref in image_refs)
    return plan


def wait_for_delete(resource: str, name: str, namespace: str | None = None) -> None:
    """Wait for deletion without ever forcing finalizer removal."""
    command = ["kubectl", "wait", "--for=delete", f"{resource}/{name}"]
    if namespace:
        command.extend(("-n", namespace))
    command.append("--timeout=60s")
    result = run(command, required=False)
    if result["exitCode"] == 0:
        return
    diagnostic = ["kubectl", "get", resource, name]
    if namespace:
        diagnostic.extend(("-n", namespace))
    diagnostic.extend(
        (
            "-o",
            "jsonpath={.metadata.deletionTimestamp}{' finalizers='}{.metadata.finalizers}{'\\n'}",
        )
    )
    details = run(diagnostic, required=False)
    refuse(f"deletion stopped; finalizers were not forced; diagnostic: {details['stdout'] or details['stderr']}")


def execute_reset(args: argparse.Namespace, *, factory: bool) -> int:
    """Validate, preview, or execute an ordered guarded reset."""
    validate_reset(args, factory=factory)
    names = existing_kustomizations(factory=factory)
    cluster_objects = capture_factory_cluster_objects() if factory else []
    storage = capture_factory_storage() if factory else []
    local_names = load_local_image_names() if factory else frozenset()
    image_refs = native_image_refs(local_names) if factory else []
    plan = reset_plan(
        names,
        factory=factory,
        cluster_objects=cluster_objects,
        storage=storage,
        image_refs=image_refs,
    )
    if not args.execute:
        sys.stdout.write(json.dumps({"mode": "dry-run", "commands": plan}, indent=2) + "\n")
        return 0
    for command in plan:
        result = run(command, required=False)
        if result["exitCode"] != 0:
            refuse(
                "destructive command failed without finalizer forcing "
                f"({' '.join(command)}): {result['stderr'] or result['stdout']}"
            )
        if command[:3] == [
            "kubectl",
            "delete",
            "kustomizations.kustomize.toolkit.fluxcd.io",
        ]:
            wait_for_delete(command[2], command[3], FLUX_NAMESPACE)
        elif command[:2] == ["kubectl", "delete"] and command[2] in CLUSTER_RESOURCE_BY_KIND.values():
            wait_for_delete(command[2], command[3])
        elif command[:3] == ["kubectl", "delete", "namespace"]:
            wait_for_delete("namespace", command[3])
        elif command[:3] == ["kubectl", "delete", "persistentvolume"]:
            wait_for_delete("persistentvolume", command[3])
    return zero_state(
        args,
        require_empty=factory,
        captured_storage=storage,
        captured_cluster_objects=cluster_objects,
        local_image_names=local_names,
    )


def _absence_failure(
    command: Sequence[str],
    description: str,
) -> str | None:
    result = run(command, required=False)
    if result["exitCode"] == 0:
        if result["stdout"]:
            return f"{description} remains: {result['stdout']}"
        return None
    if "not found" not in str(result["stderr"]).lower():
        return f"could not verify {description} absence: {result['stderr'] or result['stdout']}"
    return None


def _factory_absence_failures(
    captured_storage: Sequence[tuple[str, str, str]],
    captured_cluster_objects: Sequence[tuple[str, str]],
    local_image_names: frozenset[str],
) -> list[str]:
    failures = [
        failure
        for namespace in FACTORY_NAMESPACES
        if (
            failure := _absence_failure(
                ("kubectl", "get", "namespace", namespace, "-o", "name"),
                f"factory-reset namespace {namespace}",
            )
        )
    ]
    for namespace, pvc_name, pv_name in captured_storage:
        pvc_failure = _absence_failure(
            (
                "kubectl",
                "get",
                "persistentvolumeclaim",
                pvc_name,
                "-n",
                namespace,
                "-o",
                "name",
            ),
            f"captured PVC {namespace}/{pvc_name}",
        )
        if pvc_failure:
            failures.append(pvc_failure)
        if pv_name and (
            pv_failure := _absence_failure(
                ("kubectl", "get", "persistentvolume", pv_name, "-o", "name"),
                f"owned PV {pv_name}",
            )
        ):
            failures.append(pv_failure)
    for resource, object_name in captured_cluster_objects:
        if failure := _absence_failure(
            ("kubectl", "get", resource, object_name, "-o", "name"),
            f"captured cluster-scoped object {resource}/{object_name}",
        ):
            failures.append(failure)
    if new_owned := capture_factory_cluster_objects():
        failures.append(
            "new exact-owned cluster-scoped objects remain: "
            + ", ".join(f"{resource}/{name}" for resource, name in new_owned)
        )
    if remaining_refs := native_image_refs(local_image_names):
        failures.append("first-party native-k3s image refs remain: " + ", ".join(remaining_refs))
    return failures


def zero_state(
    args: argparse.Namespace,
    *,
    require_empty: bool = False,
    captured_storage: Sequence[tuple[str, str, str]] = (),
    captured_cluster_objects: Sequence[tuple[str, str]] = (),
    local_image_names: frozenset[str] = frozenset(),
) -> int:
    """Verify that managed resources reached the requested zero-state."""
    require_context(args.expected_context)
    if args.namespace != APP_NAMESPACE:
        refuse(f"namespace {args.namespace!r} is outside the verification allowlist")
    failures: list[str] = []
    kustomizations = kubectl(
        "get",
        "kustomizations.kustomize.toolkit.fluxcd.io",
        "-n",
        FLUX_NAMESPACE,
        "-o",
        "jsonpath={range .items[*]}{.metadata.name}{'\\n'}{end}",
        required=False,
    )
    if kustomizations["exitCode"] != 0 and "not found" not in str(kustomizations["stderr"]).lower():
        failures.append(
            "could not verify Flux zero-state: " + str(kustomizations["stderr"] or kustomizations["stdout"])
        )
    allowlist = FACTORY_RESET_KUSTOMIZATIONS if require_empty else NORMAL_RESET_KUSTOMIZATIONS
    present = set(str(kustomizations["stdout"]).splitlines()).intersection(allowlist)
    if present:
        failures.append(f"managed Flux Kustomizations remain: {', '.join(sorted(present))}")
    resources = kubectl(
        "get",
        "deployments,statefulsets,daemonsets,jobs,persistentvolumeclaims",
        "-n",
        APP_NAMESPACE,
        "-o",
        "name",
        required=False,
    )
    if resources["exitCode"] != 0 and "not found" not in str(resources["stderr"]).lower():
        failures.append("could not verify application zero-state: " + str(resources["stderr"] or resources["stdout"]))
    if resources["exitCode"] == 0 and resources["stdout"]:
        failures.append(f"application resources remain in {APP_NAMESPACE}: {resources['stdout']}")
    if require_empty:
        failures.extend(
            _factory_absence_failures(
                captured_storage,
                captured_cluster_objects,
                local_image_names,
            )
        )
    if failures:
        refuse("zero-state verification failed: " + "; ".join(failures))
    sys.stdout.write(
        json.dumps(
            {
                "context": args.expected_context,
                "namespace": APP_NAMESPACE,
                "zeroState": True,
            },
            sort_keys=True,
        )
        + "\n"
    )
    return 0


def recovery_evidence(args: argparse.Namespace) -> int:
    """Capture evidence after recovery from a guarded reset."""
    context = require_context(args.expected_context)
    checkpoint_document = load_checkpoint(args.checkpoint, args.checkpoint_sha256, context)
    document = {
        "apiVersion": API_VERSION,
        "kind": "LocalRecoveryEvidence",
        "metadata": {
            "capturedAt": dt.datetime.now(dt.UTC).isoformat(),
            "context": context,
            "namespaceAllowlist": [APP_NAMESPACE, FLUX_NAMESPACE],
            "owner": checkpoint_document["metadata"]["owner"],
            "sourceCheckpoint": {
                "path": str(args.checkpoint),
                "sha256": args.checkpoint_sha256,
            },
        },
        "evidence": {
            "cluster": command_inventory(),
            "git": {
                "head": git_sha("HEAD"),
                "status": run(("git", "status", "--porcelain=v1")),
            },
            "lifecycleTools": tool_versions(),
        },
    }
    checksum = write_evidence(args.output, document)
    sys.stdout.write(json.dumps({"recoveryEvidence": str(args.output), "sha256": checksum}, sort_keys=True) + "\n")
    return 0


def add_context(parser: argparse.ArgumentParser) -> None:
    """Add the exact-context guard argument to a command parser."""
    parser.add_argument("--expected-context", required=True)


def add_reset_arguments(parser: argparse.ArgumentParser, *, factory: bool) -> None:
    """Add destructive reset guards to a command parser."""
    add_context(parser)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--checkpoint-sha256", required=True)
    parser.add_argument("--destructive", action="store_true")
    parser.add_argument("--acknowledge-data-loss", required=True)
    parser.add_argument("--owner-authorization", required=True)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="execute after all guards; omission prints a dry-run plan",
    )
    if factory:
        parser.add_argument("--acknowledge-factory-reset", required=True)


def parser() -> argparse.ArgumentParser:
    """Build the reset evidence command-line parser."""
    root = argparse.ArgumentParser(description=__doc__)
    subparsers = root.add_subparsers(dest="command", required=True)

    capture = subparsers.add_parser("checkpoint", help="capture read-only pre-destruction evidence")
    add_context(capture)
    capture.add_argument("--output", required=True, type=Path)
    capture.add_argument("--owner")
    capture.add_argument("--runtime-control-ref", default="HEAD")
    capture.add_argument("--reviewed-topic", action="append", default=[])
    capture.set_defaults(handler=checkpoint)

    reset = subparsers.add_parser("reset", help="guard and optionally reset the Nohiki local stack")
    add_reset_arguments(reset, factory=False)
    reset.set_defaults(handler=lambda arguments: execute_reset(arguments, factory=False))

    factory = subparsers.add_parser("factory-reset", help="separately guard full local control-plane removal")
    add_reset_arguments(factory, factory=True)
    factory.set_defaults(handler=lambda arguments: execute_reset(arguments, factory=True))

    verify = subparsers.add_parser("zero-state", help="read-only reset verification")
    add_context(verify)
    verify.add_argument("--namespace", required=True)
    verify.set_defaults(handler=zero_state)

    recovery = subparsers.add_parser("recovery-evidence", help="capture post-recovery evidence")
    add_context(recovery)
    recovery.add_argument("--checkpoint", required=True, type=Path)
    recovery.add_argument("--checkpoint-sha256", required=True)
    recovery.add_argument("--output", required=True, type=Path)
    recovery.set_defaults(handler=recovery_evidence)
    return root


def main() -> int:
    """Run the reset evidence CLI and preserve refusal exit semantics."""
    try:
        arguments = parser().parse_args()
        return int(arguments.handler(arguments))
    except RefusalError as error:
        sys.stderr.write(f"{error}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
