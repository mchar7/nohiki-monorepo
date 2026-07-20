"""Behavioral tests for guarded local reset and recovery evidence tooling."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _ROOT / "infra" / "k8s" / "local" / "cluster_reset.py"
_CONTEXT = "k3s-nohiki-test"
_DATA_LOSS = "I understand this permanently deletes local Nohiki data"
_FACTORY_LOSS = "I understand factory reset removes the Nohiki and Flux local control planes"
_OWNER_AUTH = "I am the recorded owner release-owner"
_NORMAL_KUSTOMIZATIONS = "observability\nplatform\nruntime-secrets\ninfrastructure\ngateway-api-crds\n"
_FACTORY_KUSTOMIZATIONS = (
    "playwright-verification\napi-verification\nhealth-verification\n"
    + _NORMAL_KUSTOMIZATIONS
    + "registry\nflux-system\n"
)
_FACTORY_ORDER = [
    "playwright-verification",
    "api-verification",
    "health-verification",
    "observability",
    "platform",
    "runtime-secrets",
    "infrastructure",
    "registry",
    "gateway-api-crds",
    "flux-system",
]
_FACTORY_NAMESPACES = [
    "nohiki-verification",
    "nohiki",
    "nohiki-foundation",
    "nohiki-registry",
    "flux-system",
]
_PVC_INVENTORY = json.dumps(
    {
        "items": [
            {
                "metadata": {"namespace": namespace, "name": name, "uid": uid},
                "spec": {"volumeName": volume},
            }
            for namespace, name, uid, volume in (
                ("nohiki-registry", "nohiki-registry", "uid-registry", "pv-registry"),
                (
                    "nohiki-registry",
                    "local-registry-data",
                    "uid-local-registry",
                    "pv-local-registry",
                ),
                (
                    "nohiki-verification",
                    "api-artifacts",
                    "uid-verification",
                    "pv-verification",
                ),
                (
                    "nohiki-foundation",
                    "foundation-data",
                    "uid-foundation",
                    "pv-foundation",
                ),
                ("other-team", "shared-data", "uid-unrelated", "pv-unrelated"),
            )
        ]
    }
)
_PV_INVENTORY = json.dumps(
    {
        "items": [
            {
                "metadata": {"name": volume},
                "spec": {"claimRef": {"namespace": namespace, "name": name, "uid": uid}},
            }
            for volume, namespace, name, uid in (
                ("pv-registry", "nohiki-registry", "nohiki-registry", "uid-registry"),
                (
                    "pv-local-registry",
                    "nohiki-registry",
                    "local-registry-data",
                    "uid-local-registry",
                ),
                (
                    "pv-verification",
                    "nohiki-verification",
                    "api-artifacts",
                    "uid-verification",
                ),
                (
                    "pv-foundation",
                    "nohiki-foundation",
                    "foundation-data",
                    "uid-foundation",
                ),
                ("pv-unrelated", "other-team", "shared-data", "uid-unrelated"),
            )
        ]
    }
)
_CLUSTER_RESOURCES = {
    "ValidatingWebhookConfiguration": "validatingwebhookconfigurations.admissionregistration.k8s.io",
    "MutatingWebhookConfiguration": "mutatingwebhookconfigurations.admissionregistration.k8s.io",
    "ValidatingAdmissionPolicyBinding": "validatingadmissionpolicybindings.admissionregistration.k8s.io",
    "ValidatingAdmissionPolicy": "validatingadmissionpolicies.admissionregistration.k8s.io",
    "CustomResourceDefinition": "customresourcedefinitions.apiextensions.k8s.io",
    "ClusterRoleBinding": "clusterrolebindings.rbac.authorization.k8s.io",
    "ClusterRole": "clusterroles.rbac.authorization.k8s.io",
}
_CLUSTER_QUERY = ",".join(_CLUSTER_RESOURCES.values())
_CLUSTER_INVENTORY_DOCUMENT = {
    "items": [
        {
            "kind": "ValidatingWebhookConfiguration",
            "metadata": {
                "name": "nohiki-validator",
                "labels": {
                    "kustomize.toolkit.fluxcd.io/name": "platform",
                    "kustomize.toolkit.fluxcd.io/namespace": "flux-system",
                },
            },
        },
        {
            "kind": "MutatingWebhookConfiguration",
            "metadata": {
                "name": "foundation-mutator",
                "labels": {
                    "helm.toolkit.fluxcd.io/name": "nohiki-foundation",
                    "helm.toolkit.fluxcd.io/namespace": "flux-system",
                    "app.kubernetes.io/managed-by": "Helm",
                },
                "annotations": {
                    "meta.helm.sh/release-name": "nohiki-foundation",
                    "meta.helm.sh/release-namespace": "nohiki-foundation",
                },
            },
        },
        {
            "kind": "ValidatingAdmissionPolicyBinding",
            "metadata": {
                "name": "nohiki-policy-binding",
                "labels": {
                    "helm.toolkit.fluxcd.io/name": "nohiki",
                    "helm.toolkit.fluxcd.io/namespace": "flux-system",
                },
            },
        },
        {
            "kind": "ValidatingAdmissionPolicy",
            "metadata": {
                "name": "flux-policy",
                "labels": {
                    "app.kubernetes.io/part-of": "flux",
                    "app.kubernetes.io/instance": "flux-system",
                },
            },
        },
        {
            "kind": "CustomResourceDefinition",
            "metadata": {
                "name": "widgets.nohiki.io",
                "labels": {
                    "helm.toolkit.fluxcd.io/name": "nohiki",
                    "helm.toolkit.fluxcd.io/namespace": "flux-system",
                },
                "annotations": {
                    "meta.helm.sh/release-name": "nohiki",
                    "meta.helm.sh/release-namespace": "nohiki",
                },
            },
        },
        {
            "kind": "ClusterRoleBinding",
            "metadata": {
                "name": "nohiki-infrastructure",
                "labels": {
                    "kustomize.toolkit.fluxcd.io/name": "infrastructure",
                    "kustomize.toolkit.fluxcd.io/namespace": "flux-system",
                },
            },
        },
        {
            "kind": "ClusterRole",
            "metadata": {
                "name": "flux-controller",
                "labels": {
                    "app.kubernetes.io/part-of": "flux",
                    "app.kubernetes.io/instance": "flux-system",
                },
            },
        },
        {
            "kind": "CustomResourceDefinition",
            "metadata": {"name": "unrelated.example.io", "labels": {"team": "other"}},
        },
        {
            "kind": "ClusterRole",
            "metadata": {
                "name": "system:k3s-controller",
                "labels": {"kubernetes.io/bootstrapping": "rbac-defaults"},
            },
        },
        {
            "kind": "ClusterRole",
            "metadata": {
                "name": "generic-owner-namespaces",
                "labels": {
                    "helm.toolkit.fluxcd.io/namespace": "flux-system",
                    "kustomize.toolkit.fluxcd.io/namespace": "flux-system",
                    "app.kubernetes.io/instance": "flux-system",
                },
            },
        },
        {
            "kind": "ClusterRole",
            "metadata": {
                "name": "other-owner-names",
                "labels": {
                    "helm.toolkit.fluxcd.io/name": "other-release",
                    "kustomize.toolkit.fluxcd.io/name": "other-team",
                    "app.kubernetes.io/part-of": "other-system",
                },
            },
        },
    ]
}
_CLUSTER_INVENTORY = json.dumps(_CLUSTER_INVENTORY_DOCUMENT)

_NATIVE_REFS = "\n".join(
    (
        "localhost:5000/bff-service:dev",
        "localhost:5000/frontend@sha256:" + "a" * 64,
        "localhost:5000/vendor:keep",
        "docker.io/library/alpine:3.21",
    )
)

_FAKE_TOOL = r"""#!/usr/bin/env bash
set -u
name="${0##*/}"
args=("$@")
{
  printf '%s' "$name"
  printf '\t%s' "$@"
  printf '\n'
} >>"$FAKE_TOOL_LOG"

deleted() {
  local resource="$1" object_name="$2" command tool action logged_resource logged_name rest
  while IFS=$'\t' read -r tool action logged_resource logged_name rest; do
    if [[ "$tool" == kubectl && "$action" == delete \
      && "$logged_resource" == "$resource" && "$logged_name" == "$object_name" ]]; then
      return 0
    fi
  done <"$FAKE_TOOL_LOG"
  return 1
}

if [[ "$name" == kubectl ]]; then
  if [[ "${args[*]}" == "config current-context" ]]; then
    printf '%s\n' "${FAKE_CONTEXT:-k3s-nohiki-test}"
  elif [[ "${args[0]:-} ${args[1]:-}" == "auth whoami" ]]; then
    printf '%s\n' '{"status":{"userInfo":{"username":"release-owner"}}}'
  elif [[ "${args[0]:-} ${args[1]:-}" == "delete namespace" && "${FAKE_MISSING_NAMESPACE:-}" == "${args[2]:-}" ]]; then
    printf '%s\n' "not found" >&2
    [[ " ${args[*]} " == *" --ignore-not-found "* ]] || exit 1
  elif [[ "${args[0]:-} ${args[1]:-}" == "delete persistentvolume" \
      && "${FAKE_RECLAIMED_PV:-}" == "${args[2]:-}" ]]; then
    printf '%s\n' "not found" >&2
    [[ " ${args[*]} " == *" --ignore-not-found "* ]] || exit 1
  elif [[ "${args[0]:-}" == delete && "${FAKE_MISSING_CLUSTER_OBJECT:-}" == "${args[1]:-}/${args[2]:-}" ]]; then
    printf '%s\n' "not found" >&2
    [[ " ${args[*]} " == *" --ignore-not-found "* ]] || exit 1
  elif [[ "${args[0]:-}" == get && "${args[*]}" == *"jsonpath={.metadata.deletionTimestamp}"* ]]; then
    printf '%s\n' "2026-07-14T00:00:00Z finalizers=[protect.nohiki.io]"
  elif [[ "${args[0]:-} ${args[1]:-}" == "get kustomizations.kustomize.toolkit.fluxcd.io" ]]; then
    while IFS= read -r item; do
      [[ -z "$item" ]] || deleted "kustomizations.kustomize.toolkit.fluxcd.io" "$item" || printf '%s\n' "$item"
    done <<<"${FAKE_KUSTOMIZATIONS:-}"
  elif [[ "${args[*]}" == "get $FAKE_CLUSTER_QUERY -o json" ]]; then
    python3 -c '
import json, os
commands = [line.split("\t") for line in open(os.environ["FAKE_TOOL_LOG"], encoding="utf-8").read().splitlines()]
resources = json.loads(os.environ["FAKE_CLUSTER_RESOURCES"])
document = json.loads(os.environ["FAKE_CLUSTER_INVENTORY"])
def deleted(resource, name):
    return any(command[:4] == ["kubectl", "delete", resource, name] for command in commands)
remaining = [item for item in document["items"] if not deleted(resources[item["kind"]], item["metadata"]["name"])]
if any(len(command) > 2 and command[:2] == ["kubectl", "delete"] and command[2] in resources.values()
       for command in commands):
    if raw := os.environ.get("FAKE_NEW_CLUSTER_OBJECT"):
        remaining.append(json.loads(raw))
print(json.dumps({"items": remaining}))
'
  elif [[ "${args[*]}" == "get persistentvolumeclaims --all-namespaces -o json" ]]; then
    printf '%s\n' "$FAKE_PVC_INVENTORY"
  elif [[ "${args[*]}" == "get persistentvolumes -o json" ]]; then
    printf '%s\n' "$FAKE_PV_INVENTORY"
  elif [[ "${args[0]:-} ${args[1]:-}" == "get deployments,statefulsets,daemonsets,jobs,persistentvolumeclaims" ]]; then
    printf '%s' "${FAKE_APP_RESOURCES:-}"
  elif [[ "${args[0]:-} ${args[1]:-}" == "get namespace" ]]; then
    namespace="${args[2]}"
    if [[ "${FAKE_RESIDUAL_NAMESPACE:-}" == "$namespace" ]] || ! deleted namespace "$namespace"; then
      printf 'namespace/%s\n' "$namespace"
    else
      printf '%s\n' "not found" >&2
      exit 1
    fi
  elif [[ "${args[0]:-} ${args[1]:-}" == "get persistentvolumeclaim" ]]; then
    namespace=""
    for ((index = 0; index < ${#args[@]}; index++)); do
      [[ "${args[index]}" != -n ]] || namespace="${args[index + 1]}"
    done
    pvc_name="${args[2]}"
    if [[ "${FAKE_RESIDUAL_PVC:-}" == "$namespace/$pvc_name" ]]; then
      printf 'persistentvolumeclaim/%s\n' "$pvc_name"
    else
      printf '%s\n' "not found" >&2
      exit 1
    fi
  elif [[ "${args[0]:-} ${args[1]:-}" == "get persistentvolume" ]]; then
    pv_name="${args[2]}"
    if [[ "${FAKE_RESIDUAL_PV:-}" == "$pv_name" ]] || ! deleted persistentvolume "$pv_name"; then
      printf 'persistentvolume/%s\n' "$pv_name"
    else
      printf '%s\n' "not found" >&2
      exit 1
    fi
  elif [[ "${args[0]:-}" == get && "${args[1]:-}" != pods ]]; then
    resource="${args[1]}"
    object_name="${args[2]}"
    if deleted "$resource" "$object_name"; then
      printf '%s\n' "not found" >&2
      exit 1
    fi
    printf '%s/%s\n' "$resource" "$object_name"
  elif [[ "${args[0]:-}" == wait && "${FAKE_STUCK_FINALIZER:-}" == 1 ]]; then
    printf '%s\n' "timed out waiting for deletion" >&2
    exit 1
  elif [[ "${args[0]:-} ${args[1]:-}" == "get pods" ]]; then
    printf '%s\n' "NAMESPACE POD IMAGES IMAGE_IDS" "nohiki app registry.local/app@sha256:abc containerd://sha256:abc"
  else
    printf '%s\n' "synthetic metadata inventory"
  fi
elif [[ "$name" == sudo ]]; then
  if [[ "${args[*]}" == "-n k3s ctr -n k8s.io images ls -q" ]]; then
    while IFS= read -r ref; do
      [[ -z "$ref" ]] && continue
      if deleted_ref=0; then
        while IFS=$'\t' read -r tool a b c d e f action removed; do
          [[ "$tool $a $b $c $d $e $f $action $removed" != \
            "sudo -n k3s ctr -n k8s.io images rm $ref" ]] || deleted_ref=1
        done <"$FAKE_TOOL_LOG"
        [[ "$deleted_ref" == 0 || "${FAKE_NATIVE_REF_STICKS:-}" == "$ref" ]] && printf '%s\n' "$ref"
      fi
    done <<<"${FAKE_NATIVE_REFS:-}"
  elif [[ "${args[*]:0:7}" == "-n k3s ctr -n k8s.io images rm"* ]]; then
    if [[ "${FAKE_IMAGE_RM_FAILURE:-}" == "${args[-1]}" ]]; then
      printf '%s\n' "containerd removal failed" >&2
      exit 1
    fi
  else
    printf '%s\n' "registry.local/app@sha256:abc"
  fi
elif [[ "$name" == flux ]]; then
  printf '%s\n' "flux version 2.test"
elif [[ "$name" == helm ]]; then
  printf '%s\n' "v3.test"
elif [[ "$name" == k3s ]]; then
  printf '%s\n' "k3s version test"
elif [[ "$name" == sops ]]; then
  printf '%s\n' "sops test"
elif [[ "$name" == age ]]; then
  printf '%s\n' "age test"
fi
"""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _commands(log: Path) -> list[list[str]]:
    if not log.exists():
        return []
    return [line.split("\t") for line in log.read_text(encoding="utf-8").splitlines()]


@pytest.fixture
def harness(tmp_path: Path) -> dict[str, object]:
    repository = tmp_path / "repo"
    repository.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
    subprocess.run(["git", "config", "user.name", "Test Owner"], cwd=repository, check=True)
    subprocess.run(
        ["git", "config", "user.email", "owner@example.invalid"],
        cwd=repository,
        check=True,
    )
    (repository / "tracked.txt").write_text("checkpoint fixture\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repository, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=repository, check=True)
    subprocess.run(["git", "branch", "reviewed/topic"], cwd=repository, check=True)

    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name in ("kubectl", "flux", "helm", "k3s", "sops", "age", "sudo"):
        tool = bindir / name
        tool.write_text(_FAKE_TOOL, encoding="utf-8")
        tool.chmod(tool.stat().st_mode | stat.S_IXUSR)
    log = tmp_path / "commands.jsonl"
    environment = os.environ | {
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "FAKE_TOOL_LOG": str(log),
        "FAKE_CONTEXT": _CONTEXT,
        "FAKE_KUSTOMIZATIONS": _FACTORY_KUSTOMIZATIONS,
        "FAKE_PVC_INVENTORY": _PVC_INVENTORY,
        "FAKE_PV_INVENTORY": _PV_INVENTORY,
        "FAKE_NATIVE_REFS": _NATIVE_REFS,
        "FAKE_CLUSTER_RESOURCES": json.dumps(_CLUSTER_RESOURCES),
        "FAKE_CLUSTER_QUERY": _CLUSTER_QUERY,
        "FAKE_CLUSTER_INVENTORY": _CLUSTER_INVENTORY,
    }
    return {"repo": repository, "env": environment, "log": log}


def _run(
    harness: dict[str, object], *arguments: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    environment = dict(harness["env"] if env is None else env)
    return subprocess.run(
        ["python3", str(_SCRIPT), *arguments],
        cwd=Path(harness["repo"]),
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def _checkpoint(harness: dict[str, object], tmp_path: Path) -> tuple[Path, str]:
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


def _reset_arguments(path: Path, checksum: str) -> list[str]:
    return [
        "--destructive",
        "--expected-context",
        _CONTEXT,
        "--namespace",
        "nohiki",
        "--checkpoint",
        str(path),
        "--checkpoint-sha256",
        checksum,
        "--acknowledge-data-loss",
        _DATA_LOSS,
        "--owner-authorization",
        _OWNER_AUTH,
    ]


def test_checkpoint_has_exact_evidence_shape_redaction_and_checksum(harness: dict[str, object], tmp_path: Path) -> None:
    path, checksum = _checkpoint(harness, tmp_path)
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
    assert set(document["evidence"]) == {"cluster", "git", "lifecycleTools"}
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
        "containerdImages",
    }
    assert set(document["evidence"]["git"]) == {
        "head",
        "runtimeControl",
        "reviewedTopics",
        "status",
    }
    assert set(document["evidence"]["lifecycleTools"]) == {
        "kubectl",
        "flux",
        "helm",
        "k3s",
        "sops",
        "age",
    }
    for record in (
        *document["evidence"]["cluster"].values(),
        *document["evidence"]["lifecycleTools"].values(),
    ):
        assert set(record) == {"command", "exitCode", "stdout", "stderr"}
    assert document["evidence"]["git"]["reviewedTopics"]["runtime"]["sha"] == document["evidence"]["git"]["head"]
    assert path.with_name(path.name + ".sha256").read_text(encoding="utf-8") == f"{checksum}  {path.name}\n"
    serialized = path.read_text(encoding="utf-8")
    assert "Secret" not in serialized
    assert not any(
        command[:2] == ["kubectl", "get"] and any("secret" in part.lower() for part in command)
        for command in _commands(Path(harness["log"]))
    )
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        (lambda args: args.remove("--destructive"), "--destructive is required"),
        (
            lambda args: args.__setitem__(args.index(_CONTEXT), "wrong-context"),
            "kubectl context",
        ),
        (
            lambda args: args.__setitem__(args.index("nohiki"), "arbitrary"),
            "outside the reset allowlist",
        ),
        (
            lambda args: args.__setitem__(args.index("--checkpoint") + 1, "/missing/checkpoint.json"),
            "checkpoint does not exist",
        ),
        (
            lambda args: args.__setitem__(args.index("--checkpoint-sha256") + 1, "0" * 64),
            "checksum mismatch",
        ),
        (
            lambda args: args.__setitem__(args.index(_DATA_LOSS), "not acknowledged"),
            "acknowledge-data-loss",
        ),
        (
            lambda args: args.__setitem__(args.index(_OWNER_AUTH), "not authorized"),
            "owner authorization",
        ),
    ],
)
def test_reset_refuses_every_missing_or_invalid_authority(
    harness: dict[str, object],
    tmp_path: Path,
    mutation: Callable[[list[str]], object],
    expected: str,
) -> None:
    path, checksum = _checkpoint(harness, tmp_path)
    arguments = _reset_arguments(path, checksum)
    mutation(arguments)
    before = len(_commands(Path(harness["log"])))
    result = _run(harness, "reset", *arguments)
    commands = _commands(Path(harness["log"]))[before:]

    assert result.returncode == 2
    assert expected in result.stderr
    assert not any(command[0] == "flux" or "delete" in command for command in commands)


def test_reset_and_factory_reset_have_separate_authority_and_scope(harness: dict[str, object], tmp_path: Path) -> None:
    path, checksum = _checkpoint(harness, tmp_path)
    reset = _run(harness, "reset", *_reset_arguments(path, checksum))
    assert reset.returncode == 0, reset.stderr
    reset_plan = json.loads(reset.stdout)["commands"]
    assert not any(command[:3] == ["kubectl", "delete", "namespace"] for command in reset_plan)
    assert [command[3] for command in reset_plan if command[:3] == ["flux", "suspend", "kustomization"]] == [
        *_FACTORY_ORDER[3:7],
        _FACTORY_ORDER[-2],
    ]
    assert not any("registry" in command or "flux-system" in command[3:4] for command in reset_plan)

    refused = _run(
        harness,
        "factory-reset",
        *_reset_arguments(path, checksum),
        "--acknowledge-factory-reset",
        "wrong",
    )
    assert refused.returncode == 2
    assert "acknowledge-factory-reset" in refused.stderr

    factory = _run(
        harness,
        "factory-reset",
        *_reset_arguments(path, checksum),
        "--acknowledge-factory-reset",
        _FACTORY_LOSS,
    )
    assert factory.returncode == 0, factory.stderr
    factory_plan = json.loads(factory.stdout)["commands"]
    namespaces = [command[3] for command in factory_plan if command[:3] == ["kubectl", "delete", "namespace"]]
    assert namespaces == _FACTORY_NAMESPACES
    assert [
        command[3] for command in factory_plan if command[:3] == ["flux", "suspend", "kustomization"]
    ] == _FACTORY_ORDER
    assert [command[3] for command in factory_plan if command[:3] == ["kubectl", "delete", "persistentvolume"]] == [
        "pv-registry",
        "pv-local-registry",
        "pv-verification",
        "pv-foundation",
    ]
    assert [
        command[-1]
        for command in factory_plan
        if command[:8] == ["sudo", "-n", "k3s", "ctr", "-n", "k8s.io", "images", "rm"]
    ] == [
        "localhost:5000/bff-service:dev",
        "localhost:5000/frontend@sha256:" + "a" * 64,
    ]
    first_namespace_delete = next(
        index for index, command in enumerate(factory_plan) if command[:3] == ["kubectl", "delete", "namespace"]
    )
    assert all(
        index < first_namespace_delete
        for index, command in enumerate(factory_plan)
        if command[:3] == ["flux", "suspend", "kustomization"]
    )
    assert all(
        protected not in command
        for command in factory_plan
        for protected in ("kube-system", "local-path-storage", "default")
    )


def test_dry_run_prunes_reverse_dag_after_suspension_without_mutation(
    harness: dict[str, object], tmp_path: Path
) -> None:
    path, checksum = _checkpoint(harness, tmp_path)
    before = len(_commands(Path(harness["log"])))
    result = _run(harness, "reset", *_reset_arguments(path, checksum))
    plan = json.loads(result.stdout)["commands"]
    expected = [
        "observability",
        "platform",
        "runtime-secrets",
        "infrastructure",
        "gateway-api-crds",
    ]
    suspensions = [command[3] for command in plan if command[:3] == ["flux", "suspend", "kustomization"]]
    deletions = [
        command[3]
        for command in plan
        if command[:3] == ["kubectl", "delete", "kustomizations.kustomize.toolkit.fluxcd.io"]
    ]
    assert suspensions == expected
    assert deletions == expected
    assert max(i for i, command in enumerate(plan) if command[0] == "flux") < min(
        i
        for i, command in enumerate(plan)
        if command[:3] == ["kubectl", "delete", "kustomizations.kustomize.toolkit.fluxcd.io"]
    )
    assert all("source.toolkit.fluxcd.io" not in " ".join(command) for command in plan)
    assert not any(command[0] == "flux" or "delete" in command for command in _commands(Path(harness["log"]))[before:])


def test_factory_execute_deletes_only_exact_owned_state_in_dependency_order(
    harness: dict[str, object], tmp_path: Path
) -> None:
    path, checksum = _checkpoint(harness, tmp_path)
    before = len(_commands(Path(harness["log"])))
    result = _run(
        harness,
        "factory-reset",
        *_reset_arguments(path, checksum),
        "--acknowledge-factory-reset",
        _FACTORY_LOSS,
        "--execute",
    )
    assert result.returncode == 0, result.stderr
    commands = _commands(Path(harness["log"]))[before:]

    destructive = [command for command in commands if command[0] == "flux" or command[:2] == ["kubectl", "delete"]]
    suspension_names = [command[3] for command in destructive if command[:3] == ["flux", "suspend", "kustomization"]]
    namespace_names = [command[3] for command in destructive if command[:3] == ["kubectl", "delete", "namespace"]]
    pv_names = [command[3] for command in destructive if command[:3] == ["kubectl", "delete", "persistentvolume"]]
    cluster_deletes = [
        (command[2], command[3])
        for command in destructive
        if command[:2] == ["kubectl", "delete"] and command[2] in _CLUSTER_RESOURCES.values()
    ]
    assert suspension_names == _FACTORY_ORDER
    assert namespace_names == _FACTORY_NAMESPACES
    assert pv_names == [
        "pv-registry",
        "pv-local-registry",
        "pv-verification",
        "pv-foundation",
    ]
    assert cluster_deletes == [
        (_CLUSTER_RESOURCES[kind], name)
        for kind, name in (
            ("ValidatingWebhookConfiguration", "nohiki-validator"),
            ("MutatingWebhookConfiguration", "foundation-mutator"),
            ("ValidatingAdmissionPolicyBinding", "nohiki-policy-binding"),
            ("ValidatingAdmissionPolicy", "flux-policy"),
            ("CustomResourceDefinition", "widgets.nohiki.io"),
            ("ClusterRoleBinding", "nohiki-infrastructure"),
            ("ClusterRole", "flux-controller"),
        )
    ]
    assert all(
        "--ignore-not-found" in command
        for command in destructive
        if command[:2] == ["kubectl", "delete"]
        and (
            command[:3]
            in (
                ["kubectl", "delete", "namespace"],
                ["kubectl", "delete", "persistentvolume"],
            )
            or command[2] in _CLUSTER_RESOURCES.values()
        )
    )

    delete_positions = [
        index
        for index, command in enumerate(commands)
        if command[:2] == ["kubectl", "delete"]
        and (
            command[:3]
            in (
                ["kubectl", "delete", "kustomizations.kustomize.toolkit.fluxcd.io"],
                ["kubectl", "delete", "namespace"],
                ["kubectl", "delete", "persistentvolume"],
            )
            or command[2] in _CLUSTER_RESOURCES.values()
        )
    ]
    for index in delete_positions:
        deleted = commands[index]
        assert commands[index + 1][:3] == [
            "kubectl",
            "wait",
            "--for=delete",
        ]
        assert commands[index + 1][3] == f"{deleted[2]}/{deleted[3]}"
    assert max(
        index
        for index, command in enumerate(commands)
        if command[:3] == ["kubectl", "delete", "kustomizations.kustomize.toolkit.fluxcd.io"]
    ) < min(
        index
        for index, command in enumerate(commands)
        if command[:2] == ["kubectl", "delete"] and command[2] in _CLUSTER_RESOURCES.values()
    )
    assert max(
        index
        for index, command in enumerate(commands)
        if command[:2] == ["kubectl", "delete"] and command[2] in _CLUSTER_RESOURCES.values()
    ) < min(index for index, command in enumerate(commands) if command[:3] == ["kubectl", "delete", "namespace"])
    assert max(
        index for index, command in enumerate(commands) if command[:3] == ["kubectl", "delete", "namespace"]
    ) < min(index for index, command in enumerate(commands) if command[:3] == ["kubectl", "delete", "persistentvolume"])

    removed_refs = [
        command[-1]
        for command in commands
        if command[:8] == ["sudo", "-n", "k3s", "ctr", "-n", "k8s.io", "images", "rm"]
    ]
    assert removed_refs == [
        "localhost:5000/bff-service:dev",
        "localhost:5000/frontend@sha256:" + "a" * 64,
    ]
    joined = [" ".join(command) for command in commands]
    assert not any("other-team" in command for command in joined)
    assert not any("pv-unrelated" in command and "delete" in command for command in joined)
    assert not any("unrelated.example.io" in command and "delete" in command for command in joined)
    assert not any("system:k3s-controller" in command and "delete" in command for command in joined)
    assert not any(
        ("generic-owner-namespaces" in command or "other-owner-names" in command) and "delete" in command
        for command in joined
    )
    assert not any("localhost:5000/vendor:keep" in command and " rm " in command for command in joined)
    assert not any("docker.io/library/alpine:3.21" in command and " rm " in command for command in joined)
    assert not any(
        token in command for command in joined for token in (" patch ", "--force", "/var/lib", "finalizers-")
    )


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("partial", "partial ownership label tuples"),
        ("label-mismatch", "partial ownership label tuples"),
        ("system", "protected system/bootstrap/k3s objectset ownership"),
        ("helm-annotations", "mismatched release annotations"),
        ("owner-reference", "unexpected ownerReferences"),
        ("ambiguous", "ambiguous overlapping ownership"),
        ("malformed", "malformed label metadata"),
    ],
)
def test_factory_refuses_spoofed_or_malformed_cluster_ownership_before_mutation(
    harness: dict[str, object],
    tmp_path: Path,
    case: str,
    expected: str,
) -> None:
    path, checksum = _checkpoint(harness, tmp_path)
    document = json.loads(_CLUSTER_INVENTORY)
    if case == "partial":
        document["items"][7]["metadata"]["labels"] = {"kustomize.toolkit.fluxcd.io/name": "platform"}
    elif case == "label-mismatch":
        document["items"][1]["metadata"]["labels"]["helm.toolkit.fluxcd.io/namespace"] = "wrong"
    elif case == "system":
        document["items"][0]["metadata"]["labels"]["objectset.rio.cattle.io/hash"] = "protected"
    elif case == "helm-annotations":
        document["items"][1]["metadata"]["annotations"]["meta.helm.sh/release-namespace"] = "wrong"
    elif case == "owner-reference":
        document["items"][0]["metadata"]["ownerReferences"] = [{"name": "owner"}]
    elif case == "ambiguous":
        document["items"][0]["metadata"]["labels"] |= {
            "app.kubernetes.io/part-of": "flux",
            "app.kubernetes.io/instance": "flux-system",
        }
    else:
        document["items"][0]["metadata"]["labels"] = []
    environment = dict(harness["env"])
    environment["FAKE_CLUSTER_INVENTORY"] = json.dumps(document)
    before = len(_commands(Path(harness["log"])))
    result = _run(
        harness,
        "factory-reset",
        *_reset_arguments(path, checksum),
        "--acknowledge-factory-reset",
        _FACTORY_LOSS,
        "--execute",
        env=environment,
    )
    commands = _commands(Path(harness["log"]))[before:]
    assert result.returncode == 2
    assert expected in result.stderr
    assert not any(command[0] == "flux" or "delete" in command for command in commands)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda document: document["items"][0]["spec"].pop("claimRef"),
        lambda document: document["items"][0]["spec"]["claimRef"].update({"uid": "conflicting-uid"}),
        lambda document: document["items"][0]["spec"]["claimRef"].update({"name": "different-claim"}),
    ],
)
def test_factory_refuses_missing_malformed_or_conflicting_pv_ownership(
    harness: dict[str, object],
    tmp_path: Path,
    mutation: Callable[[dict[str, object]], object],
) -> None:
    path, checksum = _checkpoint(harness, tmp_path)
    pv_document = json.loads(_PV_INVENTORY)
    mutation(pv_document)
    environment = dict(harness["env"])
    environment["FAKE_PV_INVENTORY"] = json.dumps(pv_document)
    before = len(_commands(Path(harness["log"])))
    result = _run(
        harness,
        "factory-reset",
        *_reset_arguments(path, checksum),
        "--acknowledge-factory-reset",
        _FACTORY_LOSS,
        "--execute",
        env=environment,
    )
    commands = _commands(Path(harness["log"]))[before:]
    assert result.returncode == 2
    assert "PV" in result.stderr
    assert "claimRef" in result.stderr or "ownership" in result.stderr
    assert not any(command[0] == "flux" or "delete" in command for command in commands)


def test_factory_refuses_malformed_local_ref_before_mutation(harness: dict[str, object], tmp_path: Path) -> None:
    path, checksum = _checkpoint(harness, tmp_path)
    environment = dict(harness["env"])
    environment["FAKE_NATIVE_REFS"] = _NATIVE_REFS + "\nlocalhost:5000/bff-service:bad tag"
    before = len(_commands(Path(harness["log"])))
    result = _run(
        harness,
        "factory-reset",
        *_reset_arguments(path, checksum),
        "--acknowledge-factory-reset",
        _FACTORY_LOSS,
        "--execute",
        env=environment,
    )
    commands = _commands(Path(harness["log"]))[before:]
    assert result.returncode == 2
    assert "malformed local-registry containerd image ref" in result.stderr
    assert not any(command[0] == "flux" or "delete" in command for command in commands)


def test_factory_refuses_exact_image_removal_failure_without_broad_cleanup(
    harness: dict[str, object], tmp_path: Path
) -> None:
    path, checksum = _checkpoint(harness, tmp_path)
    environment = dict(harness["env"])
    environment["FAKE_IMAGE_RM_FAILURE"] = "localhost:5000/bff-service:dev"
    before = len(_commands(Path(harness["log"])))
    result = _run(
        harness,
        "factory-reset",
        *_reset_arguments(path, checksum),
        "--acknowledge-factory-reset",
        _FACTORY_LOSS,
        "--execute",
        env=environment,
    )
    commands = _commands(Path(harness["log"]))[before:]
    assert result.returncode == 2
    assert "containerd removal failed" in result.stderr
    image_commands = [
        command for command in commands if command[:7] == ["sudo", "-n", "k3s", "ctr", "-n", "k8s.io", "images"]
    ]
    assert image_commands[-1] == [
        "sudo",
        "-n",
        "k3s",
        "ctr",
        "-n",
        "k8s.io",
        "images",
        "rm",
        "localhost:5000/bff-service:dev",
    ]
    assert not any("*" in argument or argument == "prune" for command in image_commands for argument in command)


@pytest.mark.parametrize(
    ("key", "value", "expected"),
    [
        ("FAKE_RESIDUAL_NAMESPACE", "nohiki-registry", "factory-reset namespace"),
        ("FAKE_RESIDUAL_PVC", "nohiki-registry/nohiki-registry", "captured PVC"),
        ("FAKE_RESIDUAL_PV", "pv-registry", "owned PV"),
        (
            "FAKE_NATIVE_REF_STICKS",
            "localhost:5000/bff-service:dev",
            "first-party native-k3s image refs remain",
        ),
    ],
)
def test_factory_zero_state_refuses_residual_owned_state(
    harness: dict[str, object],
    tmp_path: Path,
    key: str,
    value: str,
    expected: str,
) -> None:
    path, checksum = _checkpoint(harness, tmp_path)
    environment = dict(harness["env"])
    environment[key] = value
    result = _run(
        harness,
        "factory-reset",
        *_reset_arguments(path, checksum),
        "--acknowledge-factory-reset",
        _FACTORY_LOSS,
        "--execute",
        env=environment,
    )
    assert result.returncode == 2
    assert "zero-state verification failed" in result.stderr
    assert expected in result.stderr


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("FAKE_MISSING_NAMESPACE", "nohiki-foundation"),
        ("FAKE_RECLAIMED_PV", "pv-local-registry"),
        (
            "FAKE_MISSING_CLUSTER_OBJECT",
            f"{_CLUSTER_RESOURCES['CustomResourceDefinition']}/widgets.nohiki.io",
        ),
    ],
)
def test_factory_tolerates_already_absent_namespace_or_reclaimed_owned_pv(
    harness: dict[str, object],
    tmp_path: Path,
    key: str,
    value: str,
) -> None:
    path, checksum = _checkpoint(harness, tmp_path)
    environment = dict(harness["env"])
    environment[key] = value
    result = _run(
        harness,
        "factory-reset",
        *_reset_arguments(path, checksum),
        "--acknowledge-factory-reset",
        _FACTORY_LOSS,
        "--execute",
        env=environment,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["zeroState"] is True


def test_factory_zero_state_refuses_new_exact_owned_cluster_residue(harness: dict[str, object], tmp_path: Path) -> None:
    path, checksum = _checkpoint(harness, tmp_path)
    environment = dict(harness["env"])
    environment["FAKE_NEW_CLUSTER_OBJECT"] = json.dumps(
        {
            "kind": "ClusterRole",
            "metadata": {
                "name": "late-flux-role",
                "labels": {
                    "app.kubernetes.io/part-of": "flux",
                    "app.kubernetes.io/instance": "flux-system",
                },
            },
        }
    )
    result = _run(
        harness,
        "factory-reset",
        *_reset_arguments(path, checksum),
        "--acknowledge-factory-reset",
        _FACTORY_LOSS,
        "--execute",
        env=environment,
    )
    assert result.returncode == 2
    assert "new exact-owned cluster-scoped objects remain" in result.stderr
    assert "late-flux-role" in result.stderr


def test_unrelated_flux_resources_are_protected(harness: dict[str, object], tmp_path: Path) -> None:
    path, checksum = _checkpoint(harness, tmp_path)
    environment = dict(harness["env"])
    environment["FAKE_KUSTOMIZATIONS"] = _FACTORY_KUSTOMIZATIONS + "unrelated-team-stack\n"
    before = len(_commands(Path(harness["log"])))
    result = _run(
        harness,
        "reset",
        *_reset_arguments(path, checksum),
        "--execute",
        env=environment,
    )
    commands = _commands(Path(harness["log"]))[before:]
    assert result.returncode == 2
    assert "unrelated Flux Kustomizations" in result.stderr
    assert not any(command[0] == "flux" or "delete" in command for command in commands)


def test_stuck_finalizer_stops_with_diagnostic_and_never_forces(harness: dict[str, object], tmp_path: Path) -> None:
    path, checksum = _checkpoint(harness, tmp_path)
    environment = dict(harness["env"])
    environment["FAKE_STUCK_FINALIZER"] = "1"
    before = len(_commands(Path(harness["log"])))
    result = _run(
        harness,
        "reset",
        *_reset_arguments(path, checksum),
        "--execute",
        env=environment,
    )
    commands = _commands(Path(harness["log"]))[before:]
    assert result.returncode == 2
    assert "finalizers were not forced" in result.stderr
    assert "protect.nohiki.io" in result.stderr
    assert not any("patch" in command or "--type=json" in command or "--type=merge" in command for command in commands)
    assert not any(command[:3] == ["kubectl", "delete", "namespace"] for command in commands)


def test_zero_state_proves_empty_owned_scope_without_touching_system_resources(
    harness: dict[str, object],
) -> None:
    environment = dict(harness["env"])
    environment["FAKE_KUSTOMIZATIONS"] = ""
    result = _run(
        harness,
        "zero-state",
        "--expected-context",
        _CONTEXT,
        "--namespace",
        "nohiki",
        env=environment,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "context": _CONTEXT,
        "namespace": "nohiki",
        "zeroState": True,
    }
    commands = _commands(Path(harness["log"]))
    assert not any("kube-system" in command or "local-path-storage" in command for command in commands)
    assert not any("delete" in command for command in commands)


def test_zero_state_fails_closed_when_owned_resources_remain(
    harness: dict[str, object],
) -> None:
    environment = dict(harness["env"])
    environment["FAKE_KUSTOMIZATIONS"] = "platform\n"
    environment["FAKE_APP_RESOURCES"] = "deployment.apps/nohiki-bff\n"
    result = _run(
        harness,
        "zero-state",
        "--expected-context",
        _CONTEXT,
        "--namespace",
        "nohiki",
        env=environment,
    )
    assert result.returncode == 2
    assert "managed Flux Kustomizations remain: platform" in result.stderr
    assert "deployment.apps/nohiki-bff" in result.stderr


def test_recovery_evidence_links_checkpoint_and_writes_independent_checksum(
    harness: dict[str, object], tmp_path: Path
) -> None:
    checkpoint, checkpoint_checksum = _checkpoint(harness, tmp_path)
    output = tmp_path / "recovery.json"
    result = _run(
        harness,
        "recovery-evidence",
        "--expected-context",
        _CONTEXT,
        "--checkpoint",
        str(checkpoint),
        "--checkpoint-sha256",
        checkpoint_checksum,
        "--output",
        str(output),
    )
    assert result.returncode == 0, result.stderr
    document = json.loads(output.read_text(encoding="utf-8"))
    assert document["kind"] == "LocalRecoveryEvidence"
    assert document["metadata"]["sourceCheckpoint"] == {
        "path": str(checkpoint),
        "sha256": checkpoint_checksum,
    }
    assert document["metadata"]["owner"] == "release-owner"
    assert set(document["evidence"]) == {"cluster", "git", "lifecycleTools"}
    recovery_checksum = _sha256(output)
    assert recovery_checksum != checkpoint_checksum
    assert (
        output.with_name(output.name + ".sha256").read_text(encoding="utf-8") == f"{recovery_checksum}  {output.name}\n"
    )
    assert json.loads(result.stdout) == {
        "recoveryEvidence": str(output),
        "sha256": recovery_checksum,
    }
