"""Typed boundaries for YAML and JSON documents used by CI tests."""

from collections.abc import Mapping
from pathlib import Path
from typing import NotRequired, ReadOnly, TypedDict, TypeIs

import yaml

_SAFE_LOADER = yaml.CSafeLoader if yaml.__with_libyaml__ else yaml.SafeLoader


type Scalar = str | int | float | bool | None
type DocumentValue = Scalar | list[DocumentValue] | dict[str, DocumentValue]
type WorkflowInputValue = Scalar | list[str]
type WorkflowEnvironment = dict[str, str | int | bool]
type WorkflowPermissions = dict[str, str]


class WorkflowInput(TypedDict):
    """A declared input for a manually triggered workflow."""

    description: NotRequired[ReadOnly[str]]
    required: NotRequired[ReadOnly[bool]]
    type: NotRequired[ReadOnly[str]]
    default: NotRequired[ReadOnly[WorkflowInputValue]]
    options: NotRequired[ReadOnly[list[str]]]


class WorkflowDispatch(TypedDict):
    """Configuration for a workflow-dispatch trigger."""

    inputs: NotRequired[ReadOnly[dict[str, WorkflowInput]]]


class WorkflowRunTrigger(TypedDict):
    """Configuration for a workflow-run trigger."""

    workflows: ReadOnly[list[str]]
    types: NotRequired[ReadOnly[list[str]]]
    branches: NotRequired[ReadOnly[list[str]]]


WorkflowRefTrigger = TypedDict(
    "WorkflowRefTrigger",
    {
        "branches": NotRequired[ReadOnly[list[str]]],
        "paths": NotRequired[ReadOnly[list[str]]],
        "paths-ignore": NotRequired[ReadOnly[list[str]]],
        "types": NotRequired[ReadOnly[list[str]]],
    },
)


class WorkflowSchedule(TypedDict):
    """A scheduled workflow invocation."""

    cron: ReadOnly[str]


class WorkflowTriggers(TypedDict):
    """The trigger forms asserted by the CI workflow tests."""

    push: NotRequired[ReadOnly[WorkflowRefTrigger | None]]
    pull_request: NotRequired[ReadOnly[WorkflowRefTrigger | None]]
    workflow_dispatch: NotRequired[ReadOnly[WorkflowDispatch | None]]
    workflow_run: NotRequired[ReadOnly[WorkflowRunTrigger]]
    schedule: NotRequired[ReadOnly[list[WorkflowSchedule]]]


WorkflowStep = TypedDict(
    "WorkflowStep",
    {
        "name": NotRequired[ReadOnly[str]],
        "uses": NotRequired[ReadOnly[str]],
        "run": NotRequired[ReadOnly[str]],
        "with": NotRequired[ReadOnly[dict[str, WorkflowInputValue]]],
        "env": NotRequired[ReadOnly[WorkflowEnvironment]],
        "if": NotRequired[ReadOnly[str]],
        "id": NotRequired[ReadOnly[str]],
        "parallel": NotRequired[ReadOnly[list["WorkflowStep"]]],
    },
)


class WorkflowMatrix(TypedDict):
    """The statically named portion of a GitHub Actions matrix."""

    include: NotRequired[ReadOnly[list[dict[str, WorkflowInputValue]]]]
    unit: NotRequired[ReadOnly[str]]
    exclude: NotRequired[ReadOnly[list[dict[str, WorkflowInputValue]]]]


WorkflowStrategy = TypedDict(
    "WorkflowStrategy",
    {
        "matrix": NotRequired[ReadOnly[WorkflowMatrix]],
        "fail-fast": NotRequired[ReadOnly[bool]],
        "max-parallel": NotRequired[ReadOnly[int]],
    },
)


WorkflowJob = TypedDict(
    "WorkflowJob",
    {
        "name": NotRequired[ReadOnly[str]],
        "needs": NotRequired[ReadOnly[str | list[str]]],
        "if": NotRequired[ReadOnly[str]],
        "runs-on": NotRequired[ReadOnly[str | list[str]]],
        "timeout-minutes": NotRequired[ReadOnly[int]],
        "permissions": NotRequired[ReadOnly[WorkflowPermissions]],
        "env": NotRequired[ReadOnly[WorkflowEnvironment]],
        "outputs": NotRequired[ReadOnly[dict[str, str]]],
        "steps": NotRequired[ReadOnly[list[WorkflowStep]]],
        "strategy": NotRequired[ReadOnly[WorkflowStrategy]],
        "uses": NotRequired[ReadOnly[str]],
        "with": NotRequired[ReadOnly[dict[str, WorkflowInputValue]]],
        "environment": NotRequired[ReadOnly[str]],
    },
)


WorkflowConcurrency = TypedDict(
    "WorkflowConcurrency",
    {
        "group": ReadOnly[str],
        "cancel-in-progress": NotRequired[ReadOnly[bool | str]],
    },
)


class Workflow(TypedDict):
    """The GitHub Actions workflow fields inspected by CI tests."""

    jobs: ReadOnly[dict[str, WorkflowJob]]
    name: NotRequired[ReadOnly[str]]
    on: NotRequired[ReadOnly[str | list[str] | WorkflowTriggers]]
    permissions: NotRequired[ReadOnly[WorkflowPermissions]]
    concurrency: NotRequired[ReadOnly[str | WorkflowConcurrency]]


class ComposeService(TypedDict):
    """Docker Compose service fields inspected by CI tests."""

    image: NotRequired[ReadOnly[str]]
    environment: NotRequired[ReadOnly[dict[str, Scalar] | list[str]]]
    ports: NotRequired[ReadOnly[list[str | int | dict[str, DocumentValue]]]]
    volumes: NotRequired[ReadOnly[list[str | dict[str, DocumentValue]]]]
    depends_on: NotRequired[ReadOnly[dict[str, DocumentValue] | list[str]]]
    healthcheck: NotRequired[ReadOnly[dict[str, DocumentValue]]]
    command: NotRequired[ReadOnly[str | list[str]]]
    networks: NotRequired[ReadOnly[dict[str, DocumentValue] | list[str]]]
    restart: NotRequired[ReadOnly[str]]
    entrypoint: NotRequired[ReadOnly[str | list[str]]]


ComposeFile = TypedDict(
    "ComposeFile",
    {
        "services": ReadOnly[dict[str, ComposeService]],
        "networks": NotRequired[ReadOnly[dict[str, DocumentValue]]],
        "volumes": NotRequired[ReadOnly[dict[str, DocumentValue]]],
        "configs": NotRequired[ReadOnly[dict[str, DocumentValue]]],
        "secrets": NotRequired[ReadOnly[dict[str, DocumentValue]]],
        "x-llm-provider-endpoints": NotRequired[ReadOnly[dict[str, Scalar]]],
    },
)


class ObjectMeta(TypedDict):
    """Kubernetes object metadata inspected by manifest tests."""

    name: ReadOnly[str]
    namespace: NotRequired[ReadOnly[str]]
    labels: NotRequired[ReadOnly[dict[str, str]]]
    annotations: NotRequired[ReadOnly[dict[str, str]]]


class ContainerEnv(TypedDict):
    """A named Kubernetes container environment entry."""

    name: ReadOnly[str]
    value: NotRequired[ReadOnly[str]]
    valueFrom: NotRequired[ReadOnly[dict[str, DocumentValue]]]


class ContainerPort(TypedDict):
    """A Kubernetes container port."""

    containerPort: ReadOnly[int]
    name: NotRequired[ReadOnly[str]]
    protocol: NotRequired[ReadOnly[str]]


class ResourceRequirements(TypedDict):
    """Kubernetes container resource requests and limits."""

    requests: NotRequired[ReadOnly[dict[str, str]]]
    limits: NotRequired[ReadOnly[dict[str, str]]]


class Container(TypedDict):
    """The Kubernetes container fields inspected by manifest tests."""

    name: ReadOnly[str]
    image: ReadOnly[str]
    env: NotRequired[ReadOnly[list[ContainerEnv]]]
    ports: NotRequired[ReadOnly[list[ContainerPort]]]
    resources: NotRequired[ReadOnly[ResourceRequirements]]
    imagePullPolicy: NotRequired[ReadOnly[str]]
    command: NotRequired[ReadOnly[list[str]]]
    args: NotRequired[ReadOnly[list[str]]]
    securityContext: NotRequired[ReadOnly[dict[str, DocumentValue]]]
    livenessProbe: NotRequired[ReadOnly[dict[str, DocumentValue]]]
    readinessProbe: NotRequired[ReadOnly[dict[str, DocumentValue]]]


class PodSpec(TypedDict):
    """The Kubernetes pod fields inspected by manifest tests."""

    containers: ReadOnly[list[Container]]
    initContainers: NotRequired[ReadOnly[list[Container]]]
    serviceAccountName: NotRequired[ReadOnly[str]]
    automountServiceAccountToken: NotRequired[ReadOnly[bool]]
    restartPolicy: NotRequired[ReadOnly[str]]
    nodeSelector: NotRequired[ReadOnly[dict[str, str]]]
    tolerations: NotRequired[ReadOnly[list[dict[str, DocumentValue]]]]
    securityContext: NotRequired[ReadOnly[dict[str, DocumentValue]]]


class PodTemplate(TypedDict):
    """A Kubernetes pod template."""

    spec: ReadOnly[PodSpec]
    metadata: NotRequired[ReadOnly[ObjectMeta]]


class WorkloadSpec(TypedDict):
    """Common fields shared by Deployment-like and Job-like workloads."""

    template: ReadOnly[PodTemplate]
    replicas: NotRequired[ReadOnly[int]]
    selector: NotRequired[ReadOnly[dict[str, DocumentValue]]]
    backoffLimit: NotRequired[ReadOnly[int]]
    activeDeadlineSeconds: NotRequired[ReadOnly[int]]
    ttlSecondsAfterFinished: NotRequired[ReadOnly[int]]


type ManifestSpec = WorkloadSpec | PodSpec | dict[str, DocumentValue]


class Manifest(TypedDict):
    """The common envelope of a Kubernetes manifest."""

    apiVersion: ReadOnly[str]
    kind: ReadOnly[str]
    metadata: ReadOnly[ObjectMeta]
    spec: NotRequired[ReadOnly[ManifestSpec]]
    data: NotRequired[ReadOnly[dict[str, str]]]
    stringData: NotRequired[ReadOnly[dict[str, str]]]
    sops: NotRequired[ReadOnly[dict[str, DocumentValue]]]


def _is_object_mapping(value: object) -> TypeIs[dict[object, object]]:
    return isinstance(value, dict)


def _is_workflow_document(value: object) -> TypeIs[Workflow]:
    if not _is_object_mapping(value):
        return False
    if True in value and "on" not in value:
        value["on"] = value.pop(True)
    return True


def _is_string_mapping(value: object) -> TypeIs[dict[str, object]]:
    return isinstance(value, dict)


def _is_compose_file(value: object) -> TypeIs[ComposeFile]:
    return isinstance(value, dict)


def _is_mapping(value: object) -> TypeIs[Mapping[object, object]]:
    return isinstance(value, Mapping)


def _is_object_sequence(value: object) -> TypeIs[list[object]]:
    return isinstance(value, list)


def _is_string_sequence(value: object) -> TypeIs[list[str]]:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _is_mapping_sequence(value: object) -> TypeIs[list[dict[str, object]]]:
    return isinstance(value, list) and all(_is_string_mapping(item) for item in value)


def _is_object_meta(value: object) -> TypeIs[ObjectMeta]:
    return _is_object_mapping(value) and isinstance(value.get("name"), str)


def _is_container(value: object) -> TypeIs[Container]:
    return _is_object_mapping(value) and isinstance(value.get("name"), str) and isinstance(value.get("image"), str)


def _is_container_sequence(value: object) -> TypeIs[list[Container]]:
    return isinstance(value, list) and all(_is_container(item) for item in value)


def _is_pod_spec(value: object) -> TypeIs[PodSpec]:
    return _is_object_mapping(value) and _is_container_sequence(value.get("containers"))


def _is_pod_template(value: object) -> TypeIs[PodTemplate]:
    return _is_object_mapping(value) and _is_pod_spec(value.get("spec"))


def _is_workload_spec(value: object) -> TypeIs[WorkloadSpec]:
    return _is_object_mapping(value) and _is_pod_template(value.get("template"))


def _manifest_context(manifest: Manifest) -> str:
    kind: object = manifest.get("kind")
    metadata: object = manifest.get("metadata")
    name: object = metadata.get("name") if _is_object_mapping(metadata) else None
    return f"manifest kind {kind!r} named {name!r}"


def _manifest_type_error(manifest: Manifest, expected: str, value: object) -> TypeError:
    return TypeError(f"{_manifest_context(manifest)} expected {expected}, got {type(value).__name__}")


def _pod_spec_value(manifest: Manifest) -> object:
    spec: object = manifest.get("spec")
    if manifest.get("kind") == "Pod":
        return spec
    if not _is_object_mapping(spec):
        return spec
    template: object = spec.get("template")
    if not _is_object_mapping(template):
        return template
    return template.get("spec")


def _format_key_path(keys: tuple[str, ...]) -> str:
    return ".".join(keys) or "<root>"


def _value_at(document: Mapping[str, object], keys: tuple[str, ...]) -> object:
    current: object = document
    traversed: list[str] = []
    for key in keys:
        full_path = (*traversed, key)
        if not _is_mapping(current):
            message = (
                f"document path {_format_key_path(full_path)} cannot be traversed: "
                f"{_format_key_path(tuple(traversed))} has type {type(current).__name__}"
            )
            raise TypeError(message)
        if key not in current:
            message = (
                f"document path {_format_key_path(full_path)} is missing from parent of type {type(current).__name__}"
            )
            raise KeyError(message)
        current = current[key]
        traversed.append(key)
    return current


def _is_manifest(value: object) -> TypeIs[Manifest]:
    return isinstance(value, dict)


def load_workflow(path: Path) -> Workflow:
    """Load a GitHub Actions workflow through its typed boundary.

    Args:
        path: Workflow YAML file.

    Returns:
        The workflow mapping. The YAML 1.1 boolean spelling of ``on`` is normalized.

    Raises:
        TypeError: The document root is not a mapping.
    """
    document: object = yaml.load(
        path.read_text(encoding="utf-8"),
        Loader=_SAFE_LOADER,  # noqa: S506 -- This always selects a PyYAML safe loader.
    )
    if not _is_workflow_document(document):
        message = f"workflow {path} must contain a mapping, got {type(document).__name__}"
        raise TypeError(message)
    return document


def load_mapping(path: Path) -> dict[str, object]:
    """Load a YAML or JSON file whose root must be a mapping.

    Args:
        path: Document path.

    Returns:
        The top-level mapping.

    Raises:
        TypeError: The document root is not a mapping.
    """
    document: object = yaml.load(
        path.read_text(encoding="utf-8"),
        Loader=_SAFE_LOADER,  # noqa: S506 -- This always selects a PyYAML safe loader.
    )
    if not _is_string_mapping(document):
        message = f"document {path} must contain a mapping, got {type(document).__name__}"
        raise TypeError(message)
    return document


def load_compose(path: Path) -> ComposeFile:
    """Load a Docker Compose file through its typed boundary.

    Args:
        path: Compose YAML file.

    Returns:
        The Compose file mapping.

    Raises:
        TypeError: The document root is not a mapping.
    """
    document: object = yaml.load(
        path.read_text(encoding="utf-8"),
        Loader=_SAFE_LOADER,  # noqa: S506 -- This always selects a PyYAML safe loader.
    )
    if not _is_compose_file(document):
        message = f"compose file {path} must contain a mapping, got {type(document).__name__}"
        raise TypeError(message)
    return document


def load_manifests(text: str) -> list[Manifest]:
    """Load non-empty Kubernetes manifests from multi-document YAML.

    Args:
        text: Multi-document YAML text.

    Returns:
        Typed manifest mappings, with empty YAML documents omitted.

    Raises:
        TypeError: A non-empty document root is not a mapping.
    """
    manifests: list[Manifest] = []
    for index, document in enumerate(yaml.load_all(text, Loader=_SAFE_LOADER), start=1):
        if document is None:
            continue
        if not _is_manifest(document):
            message = f"manifest document {index} must contain a mapping, got {type(document).__name__}"
            raise TypeError(message)
        manifests.append(document)
    return manifests


def metadata_of(manifest: Manifest) -> ObjectMeta:
    """Return validated metadata for a Kubernetes manifest.

    Args:
        manifest: Manifest whose metadata is required.

    Returns:
        The manifest metadata.

    Raises:
        TypeError: The metadata is not a mapping with a string name.
    """
    metadata: object = manifest.get("metadata")
    if not _is_object_meta(metadata):
        raise _manifest_type_error(manifest, "metadata with a string name", metadata)
    return metadata


def workload_spec_of(manifest: Manifest) -> WorkloadSpec:
    """Return a validated Deployment-like workload spec.

    Args:
        manifest: Manifest whose workload spec is required.

    Returns:
        The workload spec.

    Raises:
        TypeError: The spec does not contain a pod template.
    """
    spec: object = manifest.get("spec")
    if not _is_workload_spec(spec):
        raise _manifest_type_error(manifest, "spec with a pod template", spec)
    return spec


def pod_template_of(manifest: Manifest) -> PodTemplate:
    """Return a validated pod template from a workload manifest.

    Args:
        manifest: Manifest whose pod template is required.

    Returns:
        The workload's pod template.

    Raises:
        TypeError: The manifest does not contain a pod template.
    """
    spec: object = manifest.get("spec")
    template: object = spec.get("template") if _is_object_mapping(spec) else spec
    if not _is_pod_template(template):
        raise _manifest_type_error(manifest, "spec.template to be a pod template", template)
    return template


def pod_spec_of(manifest: Manifest) -> PodSpec:
    """Return a validated pod spec from a workload or bare Pod manifest.

    Args:
        manifest: Manifest whose pod spec is required.

    Returns:
        The workload template's pod spec, or a bare Pod's direct spec.

    Raises:
        TypeError: Neither supported manifest shape contains a pod spec.
    """
    pod_spec = _pod_spec_value(manifest)
    if not _is_pod_spec(pod_spec):
        expected = "spec to be a pod spec" if manifest.get("kind") == "Pod" else "spec.template.spec to be a pod spec"
        raise _manifest_type_error(manifest, expected, pod_spec)
    return pod_spec


def containers_of(manifest: Manifest) -> list[Container]:
    """Return validated containers from a workload or bare Pod manifest.

    Args:
        manifest: Manifest whose containers are required.

    Returns:
        The containers from the supported manifest shape.

    Raises:
        TypeError: Neither supported manifest shape contains a valid container list.
    """
    pod_spec = _pod_spec_value(manifest)
    containers: object = pod_spec.get("containers") if _is_object_mapping(pod_spec) else pod_spec
    if not _is_container_sequence(containers):
        path = "spec.containers" if manifest.get("kind") == "Pod" else "spec.template.spec.containers"
        raise _manifest_type_error(manifest, f"{path} to be a list of containers", containers)
    return containers


def mapping_at(document: Mapping[str, object], *keys: str) -> dict[str, object]:
    """Return the mapping at a validated document path.

    Args:
        document: Document mapping to navigate.
        *keys: Mapping keys from the document root to the requested value.

    Returns:
        The mapping at the requested path.

    Raises:
        KeyError: A requested key is missing.
        TypeError: An intermediate or final value is not a mapping.
    """
    value = _value_at(document, keys)
    if not _is_string_mapping(value):
        message = f"document path {_format_key_path(keys)} must contain a mapping, got {type(value).__name__}"
        raise TypeError(message)
    return value


def string_at(document: Mapping[str, object], *keys: str) -> str:
    """Return the string at a validated document path.

    Args:
        document: Document mapping to navigate.
        *keys: Mapping keys from the document root to the requested value.

    Returns:
        The string at the requested path.

    Raises:
        KeyError: A requested key is missing.
        TypeError: An intermediate or final value is not a string.
    """
    value = _value_at(document, keys)
    if not isinstance(value, str):
        message = f"document path {_format_key_path(keys)} must contain a string, got {type(value).__name__}"
        raise TypeError(message)
    return value


def sequence_at(document: Mapping[str, object], *keys: str) -> list[object]:
    """Return the sequence at a validated document path.

    Args:
        document: Document mapping to navigate.
        *keys: Mapping keys from the document root to the requested value.

    Returns:
        The sequence at the requested path.

    Raises:
        KeyError: A requested key is missing.
        TypeError: An intermediate or final value is not a list.
    """
    value = _value_at(document, keys)
    if not _is_object_sequence(value):
        message = f"document path {_format_key_path(keys)} must contain a list, got {type(value).__name__}"
        raise TypeError(message)
    return value


def mapping_sequence_at(document: Mapping[str, object], *keys: str) -> list[dict[str, object]]:
    """Return the mapping sequence at a validated document path.

    Args:
        document: Document mapping to navigate.
        *keys: Mapping keys from the document root to the requested value.

    Returns:
        The sequence of mappings at the requested path.

    Raises:
        KeyError: A requested key is missing.
        TypeError: An intermediate, final, or sequence item value has the wrong type.
    """
    value = _value_at(document, keys)
    if _is_mapping_sequence(value):
        return value
    if _is_object_sequence(value):
        for index, item in enumerate(value):
            if not _is_string_mapping(item):
                message = (
                    f"document path {_format_key_path(keys)}[{index}] must contain a mapping, got {type(item).__name__}"
                )
                raise TypeError(message)
    message = f"document path {_format_key_path(keys)} must contain a list of mappings, got {type(value).__name__}"
    raise TypeError(message)


def string_sequence_at(document: Mapping[str, object], *keys: str) -> list[str]:
    """Return the string sequence at a validated document path.

    Args:
        document: Document mapping to navigate.
        *keys: Mapping keys from the document root to the requested value.

    Returns:
        The string sequence at the requested path.

    Raises:
        KeyError: A requested key is missing.
        TypeError: An intermediate or final value is not a list of strings.
    """
    value = _value_at(document, keys)
    if _is_string_sequence(value):
        return value
    if _is_object_sequence(value):
        for index, item in enumerate(value):
            if not isinstance(item, str):
                message = (
                    f"document path {_format_key_path(keys)}[{index}] must contain a string, got {type(item).__name__}"
                )
                raise TypeError(message)
    message = f"document path {_format_key_path(keys)} must contain a list of strings, got {type(value).__name__}"
    raise TypeError(message)
