"""Canonical Alembic inventory and Helm migration Job validation."""

from __future__ import annotations

import ast
import json
import re
import shlex
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import yaml

from ci_checks.core.image_inventory import InventoryError, load_inventory


@dataclass(frozen=True, slots=True)
class MigrationInventoryEntry:
    """An enabled service's canonical database schema and Alembic head."""

    service: str
    schema: str
    head: str


@dataclass(frozen=True, slots=True)
class MigrationInventory:
    """Deterministically ordered canonical migration inventory."""

    entries: tuple[MigrationInventoryEntry, ...]


class MigrationTruthError(ValueError):
    """Deterministic fail-closed validation error."""


@dataclass(frozen=True, slots=True)
class _Revision:
    revision: str
    down_revision: str | None
    schema: str
    source: Path


_KEY = re.compile(r"^([A-Za-z0-9_-]+):(?:\s*(.*?))?\s*$")
_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")
_REVISION_ID = re.compile(r"^[A-Za-z0-9_.-]+$")
_DNS_LABEL = re.compile(r"^[a-z0-9](?:[-a-z0-9]*[a-z0-9])?$")
_BFF_REVISIONS = ("001",)


def _subchart_schema(values_path: Path, service: str) -> str | None:
    """Return a service chart's database.schema default, if declared."""
    chart_values = values_path.parent / "charts" / service / "values.yaml"
    try:
        lines = chart_values.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        msg = f"cannot read service Helm values: {chart_values}: {exc}"
        raise MigrationTruthError(msg) from exc
    in_database = False
    for raw in lines:
        line = raw.split("#", 1)[0].rstrip()
        if not line:
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.lstrip(" ")
        if indent == 0:
            in_database = stripped == "database:"
            continue
        if indent == 2 and in_database:
            match = _KEY.fullmatch(stripped)
            if match and match.group(1) == "schema" and match.group(2):
                return match.group(2).strip("\"'")
    return None


def _enabled_databases(values_path: Path) -> dict[str, str]:
    """Read the small top-level service/database surface used by the Helm template."""
    try:
        lines = values_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        msg = f"cannot read Helm values: {values_path}: {exc}"
        raise MigrationTruthError(msg) from exc

    services: dict[str, dict[str, str | bool]] = {}
    current: str | None = None
    in_database = False
    for raw in lines:
        line = raw.split("#", 1)[0].rstrip()
        if not line:
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.lstrip(" ")
        if indent == 0:
            match = _KEY.fullmatch(stripped)
            current = match.group(1) if match else None
            in_database = False
            if current is not None:
                services.setdefault(current, {})
            continue
        if current is None:
            continue
        if indent == 2:
            in_database = stripped == "database:"
            match = _KEY.fullmatch(stripped)
            if match and match.group(1) == "enabled":
                services[current]["service_enabled"] = match.group(2) == "true"
            continue
        if indent == 4 and in_database:
            match = _KEY.fullmatch(stripped)
            if not match:
                continue
            key, value = match.groups()
            if key == "enabled":
                services[current]["database_enabled"] = value == "true"
            elif key == "schema" and value:
                services[current]["schema"] = value.strip("\"'")

    enabled: dict[str, str] = {}
    for service, config in services.items():
        if config.get("service_enabled") is not True or config.get("database_enabled") is not True:
            continue
        prefix = service.removesuffix("-service").replace("-", "_")
        schema = config.get("schema") or _subchart_schema(values_path, service) or f"{prefix}_schema"
        if not isinstance(schema, str) or not _IDENTIFIER.fullmatch(schema):
            msg = f"{service}: invalid database schema {schema!r}"
            raise MigrationTruthError(msg)
        enabled[service] = schema
    return enabled


def _literal_assignment(tree: ast.Module, name: str, source: Path) -> str | None:
    matches: list[object] = []
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(isinstance(target, ast.Name) and target.id == name for target in targets):
            continue
        value = node.value
        try:
            matches.append(ast.literal_eval(value) if value is not None else None)
        except (ValueError, TypeError, SyntaxError) as exc:
            msg = f"{source}: {name} must be a string literal or None"
            raise MigrationTruthError(msg) from exc
    if len(matches) != 1:
        msg = f"{source}: expected exactly one {name} assignment"
        raise MigrationTruthError(msg)
    value = matches[0]
    if value is not None and not isinstance(value, str):
        msg = f"{source}: {name} must be a string literal or None"
        raise MigrationTruthError(msg)
    return value


def _read_revision(path: Path) -> _Revision:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError) as exc:
        msg = f"cannot parse migration {path}: {exc}"
        raise MigrationTruthError(msg) from exc
    revision = _literal_assignment(tree, "revision", path)
    schema = _literal_assignment(tree, "SCHEMA_NAME", path)
    down_revision = _literal_assignment(tree, "down_revision", path)
    if revision is None or schema is None:
        msg = f"{path}: revision and SCHEMA_NAME must be nonempty strings"
        raise MigrationTruthError(msg)
    if not revision or not _REVISION_ID.fullmatch(revision):
        msg = f"{path}: unsafe revision {revision!r}"
        raise MigrationTruthError(msg)
    if down_revision is not None and (not down_revision or not _REVISION_ID.fullmatch(down_revision)):
        msg = f"{path}: unsafe down_revision {down_revision!r}"
        raise MigrationTruthError(msg)
    if not schema:
        msg = f"{path}: SCHEMA_NAME must be a nonempty string"
        raise MigrationTruthError(msg)
    return _Revision(revision, down_revision, schema, path)


def _head_for(service: str, expected_schema: str, versions: Path) -> str:
    files = sorted(versions.glob("*.py"))
    if not files:
        msg = f"{service}: no committed Alembic revisions"
        raise MigrationTruthError(msg)
    revisions = [_read_revision(path) for path in files if path.name != "__init__.py"]
    by_id: dict[str, _Revision] = {}
    issues: list[str] = []
    for item in revisions:
        if item.revision in by_id:
            issues.append(f"duplicate revision {item.revision!r}")
        by_id[item.revision] = item
        if item.schema != expected_schema:
            issues.append(f"revision {item.revision!r} uses schema {item.schema!r}, expected {expected_schema!r}")
    roots = sorted(item.revision for item in revisions if item.down_revision is None)
    missing_parents = sorted(
        (item.revision, item.down_revision)
        for item in revisions
        if item.down_revision is not None and item.down_revision not in by_id
    )
    children: dict[str, list[str]] = {revision: [] for revision in by_id}
    for item in revisions:
        if item.down_revision in children:
            children[item.down_revision].append(item.revision)
    forks = sorted((parent, sorted(child_ids)) for parent, child_ids in children.items() if len(child_ids) > 1)
    heads = sorted(revision for revision, child_ids in children.items() if not child_ids)
    if roots != ["001"]:
        issues.append(f"roots are {roots!r}, expected ['001']")
    reachable: set[str] = set()
    pending = ["001"] if "001" in by_id else []
    while pending:
        revision = pending.pop()
        if revision in reachable:
            continue
        reachable.add(revision)
        pending.extend(children[revision])
    unreachable = sorted(set(by_id) - reachable)
    if unreachable:
        issues.append(f"revisions unreachable from 001 {unreachable!r}")
    if missing_parents:
        issues.append(f"missing parent revisions {missing_parents!r}")
    if forks:
        issues.append(f"forked revisions {forks!r}")
    if len(heads) != 1:
        issues.append(f"heads are {heads!r}, expected exactly one")
    numeric = sorted(int(revision) for revision in by_id if revision.isdecimal())
    if len(numeric) == len(by_id) and numeric != list(range(1, max(numeric, default=0) + 1)):
        issues.append(f"numeric revision gap: {numeric!r}")
    if service == "bff-service" and tuple(sorted(by_id)) != _BFF_REVISIONS:
        issues.append(f"BFF revisions are {tuple(sorted(by_id))!r}, expected {_BFF_REVISIONS!r}")
    if issues:
        raise MigrationTruthError(f"{service}: " + "; ".join(sorted(issues)))
    return heads[0]


def derive_inventory(repo_root: Path) -> MigrationInventory:
    """Derive enabled database services, schemas, and unique Alembic heads."""
    root = repo_root.resolve()
    enabled = _enabled_databases(root / "infra/k8s/helm/values.yaml")
    services_root = root / "backend/services"
    issues: list[str] = []
    entries: list[MigrationInventoryEntry] = []
    for service, schema in sorted(enabled.items()):
        versions = services_root / service / "alembic/versions"
        try:
            head = _head_for(service, schema, versions)
        except MigrationTruthError as exc:
            issues.append(str(exc))
        else:
            entries.append(MigrationInventoryEntry(service, schema, head))
    if not enabled:
        issues.append("Helm values enable no database-backed services")
    if issues:
        raise MigrationTruthError("\n".join(sorted(issues)))
    schemas = [entry.schema for entry in entries]
    duplicates = sorted({schema for schema in schemas if schemas.count(schema) > 1})
    if duplicates:
        msg = f"duplicate live schemas: {duplicates!r}"
        raise MigrationTruthError(msg)
    return MigrationInventory(tuple(entries))


def _merge_values(base: dict[str, object], overlay: dict[str, object]) -> dict[str, object]:
    """Return Helm-style recursive map merge without mutating either input."""
    merged = dict(base)
    for key, value in overlay.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = _merge_values(cast(dict[str, object], current), cast(dict[str, object], value))
        else:
            merged[key] = value
    return merged


def _load_values(path: Path) -> dict[str, object]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        msg = f"cannot read Helm values {path}: {exc}"
        raise MigrationTruthError(msg) from exc
    if not isinstance(payload, dict):
        msg = f"Helm values {path} must be a mapping"
        raise MigrationTruthError(msg)
    return payload


def _canonical_image(values: dict[str, object], service: str) -> tuple[str, str]:
    global_values = values.get("global")
    service_values = values.get(service)
    if not isinstance(global_values, dict) or not isinstance(service_values, dict):
        msg = f"missing Helm values for {service}"
        raise MigrationTruthError(msg)
    global_image = global_values.get("nohikiImage", {})
    service_image = service_values.get("image", {})
    if not isinstance(global_image, dict) or not isinstance(service_image, dict):
        msg = f"invalid image values for {service}"
        raise MigrationTruthError(msg)
    name = service_image.get("name") or service_image.get("repository") or service
    registry = service_image.get("registry") or global_image.get("registry") or ""
    owner = service_image.get("owner") or global_image.get("owner") or ""
    repository_name = service_image.get("repositoryName") or global_image.get("repositoryName") or ""
    if not all(isinstance(item, str) for item in (name, registry, owner, repository_name)):
        msg = f"invalid image coordinates for {service}"
        raise MigrationTruthError(msg)
    repository = str(name)
    if registry and owner and repository_name:
        repository = f"{registry}/{owner}/{repository_name}/{name}"
    elif registry:
        repository = f"{registry}/{name}"
    digests = global_values.get("imageDigests", {})
    if not isinstance(digests, dict):
        msg = "global.imageDigests must be a mapping"
        raise MigrationTruthError(msg)
    digest = digests.get(name)
    if digest:
        if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            msg = f"invalid digest for image {repository}"
            raise MigrationTruthError(msg)
        return repository, f"{repository}@{digest}"
    if global_values.get("environment") == "prod":
        msg = f"production image digest is required for {repository}"
        raise MigrationTruthError(msg)
    tag = service_image.get("tag") or global_values.get("imageTag") or "latest"
    if not isinstance(tag, str):
        msg = f"invalid image tag for {service}"
        raise MigrationTruthError(msg)
    return repository, f"{repository}:{tag}"


def _validation_digests(values: dict[str, object], inventory: MigrationInventory, repo_root: Path) -> dict[str, str]:
    nonproduction = _merge_values(values, {"global": {"environment": "validation"}})
    names = {_canonical_image(nonproduction, entry.service)[0].rsplit("/", 1)[-1] for entry in inventory.entries}
    try:
        image_names = load_inventory(repo_root / "scripts/ci/image_inventory.json", repo_root).names
    except InventoryError as exc:
        msg = f"canonical image inventory is unusable: {exc}"
        raise MigrationTruthError(msg) from exc
    names.update(image_names)
    return {name: f"sha256:{index:064x}" for index, name in enumerate(sorted(names), start=1)}


def _render_environment_jobs(
    chart: Path,
    values_path: Path,
    values: dict[str, object],
    inventory: MigrationInventory,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    environment = values_path.stem.removeprefix("values.")
    effective_values = values
    temporary_path: Path | None = None
    if environment == "prod":
        digest_values: dict[str, object] = {
            "global": {"imageDigests": _validation_digests(values, inventory, chart.parents[2])}
        }
        effective_values = _merge_values(values, digest_values)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".json", delete=False) as handle:
            json.dump(digest_values, handle)
            temporary_path = Path(handle.name)
    command = [
        "helm",
        "template",
        "nohiki",
        str(chart),
        "--namespace",
        f"nohiki-{environment}",
        "--values",
        str(values_path),
        "--show-only",
        "templates/migration-jobs.yaml",
    ]
    if environment in {"dev", "staging", "prod"}:
        command.extend(
            [
                "--set-string",
                "global.eso.azure.keyVaultUrl=https://migration-validation.vault.azure.net",
                "--set-string",
                "global.eso.azure.clientId=00000000-0000-4000-8000-000000000000",
                "--set-string",
                "global.eso.azure.tenantId=11111111-1111-4111-8111-111111111111",
            ]
        )
    if temporary_path is not None:
        command.extend(["--values", str(temporary_path)])
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
    except OSError as exc:
        msg = "cannot execute helm template"
        raise MigrationTruthError(msg) from exc
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    if result.returncode != 0:
        msg = f"Helm migration render failed for {environment}: {result.stderr.strip()}"
        raise MigrationTruthError(msg)
    try:
        jobs = [
            document
            for document in yaml.safe_load_all(result.stdout)
            if isinstance(document, dict) and document.get("kind") == "Job"
        ]
    except yaml.YAMLError as exc:
        msg = f"invalid Helm migration render for {environment}: {exc}"
        raise MigrationTruthError(msg) from exc
    return jobs, effective_values


def validate_migration_jobs(repo_root: Path, inventory: MigrationInventory) -> None:
    """Render all deployed values and validate exact Job and image equality."""
    root = repo_root.resolve()
    chart = root / "infra/k8s/helm"
    base = _load_values(chart / "values.yaml")
    expected_services = {entry.service for entry in inventory.entries}
    issues: list[str] = []
    for environment in ("local", "dev", "staging", "prod"):
        values_path = chart / f"values.{environment}.yaml"
        values = _merge_values(base, _load_values(values_path))
        jobs, effective_values = _render_environment_jobs(chart, values_path, values, inventory)
        names: list[str] = []
        for job in jobs:
            metadata = job.get("metadata", {})
            metadata_map = cast(dict[str, object], metadata) if isinstance(metadata, dict) else {}
            names.append(str(metadata_map.get("name", "")).removesuffix("-db-migrate"))
        if len(jobs) != len(inventory.entries):
            issues.append(f"{environment}: rendered {len(jobs)} migration Jobs, expected {len(inventory.entries)}")
        if len(set(names)) != len(names) or set(names) != expected_services:
            issues.append(f"{environment}: migration Job services are {sorted(names)!r}")
        for service, job in zip(names, jobs, strict=False):
            if service not in expected_services:
                continue
            spec = job.get("spec", {})
            spec_map = cast(dict[str, object], spec) if isinstance(spec, dict) else {}
            template = spec_map.get("template", {})
            template_map = cast(dict[str, object], template) if isinstance(template, dict) else {}
            pod = template_map.get("spec", {})
            pod_map = cast(dict[str, object], pod) if isinstance(pod, dict) else {}
            containers = pod_map.get("containers", [])
            actual = (
                containers[0].get("image")
                if isinstance(containers, list) and containers and isinstance(containers[0], dict)
                else None
            )
            expected = _canonical_image(effective_values, service)[1]
            if actual != expected:
                issues.append(f"{environment}: {service} migration image {actual!r} != {expected!r}")
    generated_path = root / "infra/k8s/verification/health/files/migration-heads.json"
    try:
        generated = generated_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        msg = f"cannot read generated migration inventory: {exc}"
        raise MigrationTruthError(msg) from exc
    if generated != render_inventory(inventory):
        issues.append("health migration inventory is not derived from canonical inventory")
    if issues:
        raise MigrationTruthError("migration Jobs: " + "; ".join(issues))


def validate_migration_truth(repo_root: Path) -> MigrationInventory:
    """Derive and validate canonical migration truth; raise MigrationTruthError."""
    inventory = derive_inventory(repo_root)
    validate_migration_jobs(repo_root, inventory)
    return inventory


def render_inventory(inventory: MigrationInventory) -> str:
    """Return deterministic JSON without secret-bearing configuration."""
    payload = {
        "entries": [
            {"head": entry.head, "schema": entry.schema, "service": entry.service} for entry in inventory.entries
        ]
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def render_live_verifier(inventory: MigrationInventory, *, namespace: str) -> str:
    """Return an exact read-only in-cluster verification invocation."""
    if not (1 <= len(namespace) <= 63) or not _DNS_LABEL.fullmatch(namespace):
        msg = f"invalid Kubernetes namespace {namespace!r}"
        raise MigrationTruthError(msg)
    inventory_json = shlex.quote(render_inventory(inventory))
    namespace_arg = shlex.quote(namespace)
    return (
        "inventory_file=$(mktemp) && "
        "trap 'rm -f \"$inventory_file\"' EXIT HUP INT TERM && "
        f"printf '%s' {inventory_json} >\"$inventory_file\" && "
        "python3 infra/k8s/scripts/verify-migration-heads.py "
        f'--inventory "$inventory_file" --namespace {namespace_arg} '
        "--evidence migration-head-evidence.json"
    )
