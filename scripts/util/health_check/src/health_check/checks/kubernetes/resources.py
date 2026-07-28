"""Typed helpers for inspecting raw Kubernetes workload resources."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import cast

from health_check.core.models import JsonObject, JsonValue
from health_check.platform.kubernetes import KubernetesResourceSnapshot


def object_field(value: JsonObject, key: str) -> JsonObject:
    """Return a JSON object field or an empty object when absent/malformed."""
    field = value.get(key)
    return field if isinstance(field, dict) else {}


def object_list_field(value: JsonObject, key: str) -> list[JsonObject]:
    """Return only object entries from a JSON list field."""
    field = value.get(key)
    if not isinstance(field, list):
        return []
    return [item for item in field if isinstance(item, dict)]


def string_field(value: JsonObject, key: str, default: str = "") -> str:
    """Return a string field without coercing malformed values."""
    field = value.get(key)
    return field if isinstance(field, str) else default


def integer_field(value: JsonObject, key: str, default: int = 0) -> int:
    """Return an integer field without accepting booleans."""
    field = value.get(key)
    return field if isinstance(field, int) and not isinstance(field, bool) else default


def metadata(resource: JsonObject) -> JsonObject:
    """Return resource metadata."""
    return object_field(resource, "metadata")


def identity(resource: JsonObject) -> JsonObject:
    """Return the complete stable identity used in rollout evidence."""
    resource_metadata = metadata(resource)
    return {
        "kind": string_field(resource, "kind"),
        "namespace": string_field(resource_metadata, "namespace"),
        "name": string_field(resource_metadata, "name"),
        "uid": string_field(resource_metadata, "uid"),
    }


def identity_text(resource: JsonObject) -> str:
    """Return a readable identity without using it as a join key."""
    resource_identity = identity(resource)
    return (
        f"{resource_identity['kind']}/{resource_identity['namespace']}/"
        f"{resource_identity['name']}@{resource_identity['uid']}"
    )


def resource_uid(resource: JsonObject) -> str:
    """Return a resource UID."""
    return string_field(metadata(resource), "uid")


def controller_owner_uid(resource: JsonObject, kind: str) -> str | None:
    """Return the UID of the controller owner of the requested kind."""
    for owner in object_list_field(metadata(resource), "ownerReferences"):
        if string_field(owner, "kind") == kind and owner.get("controller") is True:
            return string_field(owner, "uid") or None
    return None


def revision(resource: JsonObject) -> str:
    """Return the Deployment controller revision annotation."""
    annotations = object_field(metadata(resource), "annotations")
    return string_field(annotations, "deployment.kubernetes.io/revision")


def conditions(resource: JsonObject) -> list[JsonValue]:
    """Return every condition object in API order without reducing its fields."""
    return [cast("JsonValue", item) for item in object_list_field(object_field(resource, "status"), "conditions")]


def condition_is_true(resource: JsonObject, condition_type: str) -> bool:
    """Return whether the named condition is explicitly true."""
    return any(
        string_field(condition, "type") == condition_type and string_field(condition, "status") == "True"
        for condition in object_list_field(object_field(resource, "status"), "conditions")
    )


def template_images(resource: JsonObject) -> list[JsonValue]:
    """Return declared container names and images from a pod template."""
    template = object_field(object_field(resource, "spec"), "template")
    pod_spec = object_field(template, "spec")
    return [
        {
            "name": string_field(container, "name"),
            "image": string_field(container, "image"),
        }
        for container in object_list_field(pod_spec, "containers")
    ]


def pod_containers(pod: JsonObject) -> list[JsonValue]:
    """Join pod container specs to statuses once by container name."""
    statuses = {
        string_field(status, "name"): status
        for status in object_list_field(object_field(pod, "status"), "containerStatuses")
    }
    containers: list[JsonValue] = []
    for container in object_list_field(object_field(pod, "spec"), "containers"):
        name = string_field(container, "name")
        status = statuses.get(name, {})
        containers.append(
            {
                "name": name,
                "declared_image": string_field(container, "image"),
                "image": string_field(status, "image"),
                "image_id": string_field(status, "imageID"),
                "ready": status.get("ready") is True,
                "restart_count": integer_field(status, "restartCount"),
                "state": object_field(status, "state"),
            }
        )
    return containers


def pod_ready(pod: JsonObject) -> bool:
    """Return true only when the pod and every declared container are ready."""
    ready_condition = any(
        string_field(condition, "type") == "Ready" and string_field(condition, "status") == "True"
        for condition in object_list_field(object_field(pod, "status"), "conditions")
    )
    statuses = object_list_field(object_field(pod, "status"), "containerStatuses")
    return ready_condition and bool(statuses) and all(status.get("ready") is True for status in statuses)


def index_owned_resources(
    snapshot: KubernetesResourceSnapshot,
) -> tuple[dict[str, list[JsonObject]], dict[str, list[JsonObject]]]:
    """Index ReplicaSets by Deployment UID and pods by ReplicaSet UID in O(n)."""
    deployment_uids = {resource_uid(deployment) for deployment in snapshot.deployments}
    replica_set_uids = {resource_uid(replica_set) for replica_set in snapshot.replica_sets}
    replica_sets_by_deployment: defaultdict[str, list[JsonObject]] = defaultdict(list)
    pods_by_replica_set: defaultdict[str, list[JsonObject]] = defaultdict(list)

    for replica_set in snapshot.replica_sets:
        owner_uid = controller_owner_uid(replica_set, "Deployment")
        if owner_uid in deployment_uids:
            replica_sets_by_deployment[owner_uid].append(replica_set)

    for pod in snapshot.pods:
        owner_uid = controller_owner_uid(pod, "ReplicaSet")
        if owner_uid in replica_set_uids:
            pods_by_replica_set[owner_uid].append(pod)

    return dict(replica_sets_by_deployment), dict(pods_by_replica_set)


def image_map(images: Iterable[JsonValue]) -> dict[str, str]:
    """Index typed image evidence by container name."""
    result: dict[str, str] = {}
    for image in images:
        if isinstance(image, dict):
            name = image.get("name")
            reference = image.get("image")
            if isinstance(name, str) and isinstance(reference, str):
                result[name] = reference
    return result
