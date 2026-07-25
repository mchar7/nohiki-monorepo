"""Health check for Kubernetes Deployment rollout convergence."""

from __future__ import annotations

import asyncio
import re
from collections import defaultdict
from typing import TYPE_CHECKING, Final, cast

from health_check.checks.kubernetes.resources import (
    condition_is_true,
    conditions,
    identity,
    identity_text,
    image_map,
    index_owned_resources,
    integer_field,
    metadata,
    object_field,
    object_list_field,
    pod_containers,
    pod_ready,
    resource_uid,
    revision,
    string_field,
    template_images,
)
from health_check.core.base import HealthCheck
from health_check.core.models import (
    CheckCategory,
    CheckEvidence,
    CheckMetadata,
    CheckResult,
    CheckStatus,
    JsonObject,
    JsonValue,
)
from health_check.platform.kubernetes import KubernetesPlatform
from health_check.platform.models import PlatformTarget

if TYPE_CHECKING:
    from health_check.platform.protocol import Platform

_EVIDENCE_SCHEMA: Final = "nohiki.health/deployment-rollout/v1"
_IMMUTABLE_IMAGE = re.compile(r"@sha256:[0-9a-fA-F]{64}$")
_IMAGE_DIGEST = re.compile(r"sha256:[0-9a-fA-F]{64}$")
_METADATA: Final[CheckMetadata] = CheckMetadata(
    check_id="k8s_deployment_rollout",
    name="K8s Deployment Rollout",
    category=CheckCategory.KUBERNETES,
    platforms=frozenset({PlatformTarget.KUBERNETES}),
    timeout_seconds=35.0,
    description="Verify every Deployment rollout, owned ReplicaSet, pod, and image identity.",
)


def _replicas(resource: JsonObject, *, deployment: bool) -> JsonObject:
    """Return normalized replica counts without hiding absent status fields."""
    spec = object_field(resource, "spec")
    status = object_field(resource, "status")
    values: JsonObject = {
        "desired": integer_field(spec, "replicas", 1),
        "current": integer_field(status, "replicas"),
        "ready": integer_field(status, "readyReplicas"),
        "available": integer_field(status, "availableReplicas"),
    }
    if deployment:
        values["updated"] = integer_field(status, "updatedReplicas")
        values["unavailable"] = integer_field(status, "unavailableReplicas")
    return values


def _condition_reason(resource: JsonObject, condition_type: str, reason: str) -> bool:
    return any(
        string_field(condition, "type") == condition_type and string_field(condition, "reason") == reason
        for condition in object_list_field(object_field(resource, "status"), "conditions")
    )


def _waiting_reason(container: JsonObject) -> str:
    state = object_field(container, "state")
    return string_field(object_field(state, "waiting"), "reason")


def _digest(reference: str) -> str | None:
    match = _IMAGE_DIGEST.search(reference)
    return match.group(0).lower() if match else None


def _check_image_identity(
    deployment: JsonObject,
    active_replica_sets: list[JsonObject],
    active_pods: list[JsonObject],
    issues: list[str],
) -> None:
    """Validate immutable, uniform declared and runtime image identities."""
    deployment_name = identity_text(deployment)
    declared: defaultdict[str, set[str]] = defaultdict(set)
    runtime: defaultdict[str, set[str]] = defaultdict(set)

    for name, image in image_map(template_images(deployment)).items():
        declared[name].add(image)
        if not _IMMUTABLE_IMAGE.search(image):
            issues.append(f"{deployment_name}: container {name!r} uses mutable image {image!r}")

    for replica_set in active_replica_sets:
        for name, image in image_map(template_images(replica_set)).items():
            declared[name].add(image)
            if not _IMMUTABLE_IMAGE.search(image):
                issues.append(f"{identity_text(replica_set)}: container {name!r} uses mutable image {image!r}")

    for pod in active_pods:
        for raw_container in pod_containers(pod):
            if not isinstance(raw_container, dict):
                continue
            container = raw_container
            name = string_field(container, "name")
            declared_image = string_field(container, "declared_image")
            runtime_image = string_field(container, "image")
            image_id = string_field(container, "image_id")
            declared[name].add(declared_image)
            if not _IMMUTABLE_IMAGE.search(declared_image):
                issues.append(f"{identity_text(pod)}: container {name!r} uses mutable image {declared_image!r}")
            if not runtime_image:
                issues.append(f"{identity_text(pod)}: container {name!r} has no runtime image")
            else:
                declared[name].add(runtime_image)
                if not _IMMUTABLE_IMAGE.search(runtime_image):
                    issues.append(
                        f"{identity_text(pod)}: container {name!r} uses mutable runtime image {runtime_image!r}"
                    )
            if not image_id:
                issues.append(f"{identity_text(pod)}: container {name!r} has no runtime image ID")
            elif (digest := _digest(image_id)) is None:
                issues.append(f"{identity_text(pod)}: container {name!r} has mutable runtime image ID {image_id!r}")
            else:
                runtime[name].add(digest)

    for name, references in declared.items():
        if len(references) > 1:
            issues.append(
                f"{deployment_name}: container {name!r} has non-uniform image references {sorted(references)!r}"
            )
        desired_digest = next(
            (_digest(reference) for reference in references if _digest(reference) is not None),
            None,
        )
        runtime_digests = runtime.get(name, set())
        if len(runtime_digests) > 1:
            issues.append(
                f"{deployment_name}: container {name!r} has non-uniform runtime images {sorted(runtime_digests)!r}"
            )
        if desired_digest is not None and runtime_digests and runtime_digests != {desired_digest}:
            issues.append(f"{deployment_name}: container {name!r} runtime digest does not match its declared image")


def _pod_evidence(pod: JsonObject, issues: list[str]) -> JsonObject:
    pod_status = object_field(pod, "status")
    containers = pod_containers(pod)
    restart_count = sum(
        integer_field(container, "restart_count") for container in containers if isinstance(container, dict)
    )
    ready = pod_ready(pod)
    phase = string_field(pod_status, "phase", "Unknown")
    pod_name = identity_text(pod)

    if phase in {"Pending", "Failed"}:
        issues.append(f"{pod_name}: pod phase is {phase}")
    if not ready:
        issues.append(f"{pod_name}: pod is not ready")
    if restart_count:
        issues.append(f"{pod_name}: pod has restarted {restart_count} time(s)")
    issues.extend(
        f"{pod_name}: container {string_field(raw_container, 'name')!r} is in CrashLoopBackOff"
        for raw_container in containers
        if isinstance(raw_container, dict) and _waiting_reason(raw_container) == "CrashLoopBackOff"
    )

    return {
        "identity": identity(pod),
        "phase": phase,
        "ready": ready,
        "restart_count": restart_count,
        "conditions": conditions(pod),
        "containers": containers,
    }


def _replica_set_evidence(
    replica_set: JsonObject,
    *,
    desired: bool,
    pods: list[JsonObject],
    issues: list[str],
) -> JsonObject:
    replica_set_name = identity_text(replica_set)
    replicas = _replicas(replica_set, deployment=False)
    if condition_is_true(replica_set, "ReplicaFailure"):
        qualifier = "stale " if not desired else ""
        issues.append(f"{replica_set_name}: {qualifier}ReplicaSet reports ReplicaFailure")

    if desired:
        desired_count = cast("int", replicas["desired"])
        issues.extend(
            f"{replica_set_name}: {field} replicas {replicas[field]} != desired {desired_count}"
            for field in ("current", "ready", "available")
            if replicas[field] != desired_count
        )
        if len(pods) != desired_count:
            issues.append(f"{replica_set_name}: owns {len(pods)} pod(s), expected {desired_count}")

    return {
        "identity": identity(replica_set),
        "revision": revision(replica_set),
        "desired": desired,
        "replicas": replicas,
        "conditions": conditions(replica_set),
        "images": template_images(replica_set),
        "pods": [_pod_evidence(pod, issues) for pod in pods],
    }


def _deployment_evidence(
    deployment: JsonObject,
    replica_sets: list[JsonObject],
    pods_by_replica_set: dict[str, list[JsonObject]],
    issues: list[str],
) -> JsonObject:
    deployment_name = identity_text(deployment)
    deployment_metadata = metadata(deployment)
    generation = integer_field(deployment_metadata, "generation")
    observed_generation = integer_field(object_field(deployment, "status"), "observedGeneration")
    deployment_revision = revision(deployment)
    replicas = _replicas(deployment, deployment=True)

    if observed_generation < generation:
        issues.append(f"{deployment_name}: observedGeneration {observed_generation} lags generation {generation}")

    desired_count = cast("int", replicas["desired"])
    issues.extend(
        f"{deployment_name}: {field} replicas {replicas[field]} != desired {desired_count}"
        for field in ("current", "updated", "ready", "available")
        if replicas[field] != desired_count
    )
    if replicas["unavailable"] != 0:
        issues.append(f"{deployment_name}: {replicas['unavailable']} unavailable replica(s)")
    if condition_is_true(deployment, "ReplicaFailure"):
        issues.append(f"{deployment_name}: Deployment reports ReplicaFailure")
    if _condition_reason(deployment, "Progressing", "ProgressDeadlineExceeded"):
        issues.append(f"{deployment_name}: Deployment reports ProgressDeadlineExceeded")

    desired_replica_sets = [
        rs
        for rs in replica_sets
        if deployment_revision
        and revision(rs) == deployment_revision
        and integer_field(object_field(rs, "spec"), "replicas", 1) > 0
    ]
    if len(desired_replica_sets) != 1:
        issues.append(
            f"{deployment_name}: expected exactly one desired owned ReplicaSet for revision "
            f"{deployment_revision!r}, found {len(desired_replica_sets)}"
        )

    desired_uids = {resource_uid(rs) for rs in desired_replica_sets}
    active_replica_sets = [
        rs
        for rs in replica_sets
        if resource_uid(rs) in desired_uids or integer_field(object_field(rs, "spec"), "replicas", 1) > 0
    ]
    for replica_set in active_replica_sets:
        replica_set_revision = revision(replica_set)
        if replica_set_revision != deployment_revision:
            issues.append(
                f"{identity_text(replica_set)}: active stale ReplicaSet revision "
                f"{replica_set_revision!r} differs from Deployment revision {deployment_revision!r}"
            )
    active_pods = [pod for rs in active_replica_sets for pod in pods_by_replica_set.get(resource_uid(rs), [])]
    _check_image_identity(deployment, active_replica_sets, active_pods, issues)

    return {
        "identity": identity(deployment),
        "generation": generation,
        "observed_generation": observed_generation,
        "revision": deployment_revision,
        "replicas": replicas,
        "conditions": conditions(deployment),
        "images": template_images(deployment),
        "replica_sets": [
            _replica_set_evidence(
                rs,
                desired=resource_uid(rs) in desired_uids,
                pods=pods_by_replica_set.get(resource_uid(rs), []),
                issues=issues,
            )
            for rs in replica_sets
        ],
    }


class K8sDeploymentRolloutCheck(HealthCheck):
    """Verify converged Deployment rollouts and every owned workload resource."""

    @property
    def metadata(self) -> CheckMetadata:
        """Return check metadata."""
        return _METADATA

    async def execute(self, platform: Platform) -> CheckResult:
        """Fetch one workload snapshot and evaluate indexed ownership joins."""
        if not isinstance(platform, KubernetesPlatform):
            return self._make_result(CheckStatus.SKIPPED, "Not applicable (compose mode)")

        snapshot = await asyncio.to_thread(platform.get_deployment_rollout_resources)
        replica_sets_by_deployment, pods_by_replica_set = index_owned_resources(snapshot)
        issues: list[str] = []
        deployments: list[JsonValue] = [
            _deployment_evidence(
                deployment,
                replica_sets_by_deployment.get(resource_uid(deployment), []),
                pods_by_replica_set,
                issues,
            )
            for deployment in snapshot.deployments
        ]
        evidence = CheckEvidence(
            schema=_EVIDENCE_SCHEMA,
            data={
                "namespace": platform.namespace,
                "issues": cast("JsonValue", issues),
                "deployments": deployments,
            },
        )

        if issues:
            return self._make_result(
                CheckStatus.FAILED,
                f"{len(issues)} Deployment rollout issue(s) across {len(deployments)} Deployment(s)",
                details=tuple(issues),
                remediation_hint="Inspect the named Deployment, ReplicaSet, and pod resources with kubectl describe.",
                evidence=evidence,
            )
        return self._make_result(
            CheckStatus.PASSED,
            f"{len(deployments)} Deployment rollout(s) converged",
            evidence=evidence,
        )
