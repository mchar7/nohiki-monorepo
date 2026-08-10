#!/usr/bin/env python3
"""Export combined OpenAPI spec from identity-service and bff-service.

This script generates the canonical OpenAPI spec used by the frontend.
Requires the backend services to be importable.
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, cast

import typer
from fastapi import FastAPI
from rich.console import Console

console = Console(stderr=True)

type JSONValue = str | int | float | bool | None | dict[str, "JSONValue"] | list["JSONValue"]
type OpenAPISpec = dict[str, JSONValue]
type PathsDict = dict[str, JSONValue]
type SchemasDict = dict[str, JSONValue]

_OPENAPI_VERSION = "3.1.0"
_ACCESS_TOKEN_COOKIE = "__Host-nohiki_at"  # noqa: S105
_DEV_FRONTEND_ORIGIN = "http://localhost:5173"

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
OUTPUT_PATH = REPO_ROOT / "docs" / "api" / "nohiki.openapi.json"

_INTERNAL_PATHS = frozenset({"/", "/healthz", "/readyz", "/livez"})
_IDENTITY_PATH_PREFIXES = ("/api/v1/auth", "/api/v1/account", "/.well-known")


@dataclass(frozen=True, slots=True)
class ServiceConfig:
    """Configuration for a backend service to export OpenAPI from.

    Attributes:
        name: Human-readable service name (e.g. bff-service).
        module_path: Dotted Python import path to the service main module.
        package_path: Filesystem path to add to sys.path before import.
        env_vars: Environment variable defaults required for import.
    """

    name: str
    module_path: str
    package_path: Path
    env_vars: dict[str, str] = field(default_factory=dict)


BFF_CONFIG = ServiceConfig(
    name="bff-service",
    module_path="bff_service.main",
    package_path=REPO_ROOT / "backend" / "services" / "bff-service" / "src",
    env_vars={
        "BFF_DATABASE__DSN": "postgresql+asyncpg://user:pass@localhost/db?sslmode=disable",
        "BFF_DATABASE__SCHEMA_NAME": "bff",
        "BFF_REDIS__DSN": "redis://localhost:6379/0",
        "BFF_JWT__JWKS_URL": "http://localhost:8000/.well-known/jwks.json",
        "BFF_JWT__ISSUER": "nohiki",
        "BFF_JWT__AUDIENCE": "nohiki",
        "BFF_COOKIE__ACCESS_TOKEN_NAME": _ACCESS_TOKEN_COOKIE,
        "BFF_ORIGINS__CORS_ORIGINS": _DEV_FRONTEND_ORIGIN,
        "BFF_ORIGINS__CSRF_ORIGINS": _DEV_FRONTEND_ORIGIN,
        "BFF_S3__ENDPOINT": "http://localhost:9000",
        "BFF_S3__ACCESS_KEY": "minioadmin",
        "BFF_S3__SECRET_KEY": "minioadmin",
        "BFF_S3__BUCKET": "nohiki",
        "BFF_KAFKA__DSN": "kafka://localhost:29092",
        "BFF_ENVIRONMENT": "development",
    },
)

AUTH_CONFIG = ServiceConfig(
    name="user-auth-service",
    module_path="user_auth_service.main",
    package_path=REPO_ROOT / "backend" / "services" / "user-auth-service" / "src",
    env_vars={
        "USER_AUTH_DATABASE__DSN": "postgresql+asyncpg://user:pass@localhost/db",
        "USER_AUTH_DATABASE__SCHEMA_NAME": "user_auth",
        "USER_AUTH_REDIS__DSN": "redis://localhost:6379/0",
        "USER_AUTH_JWT__PRIVATE_KEY_PATH": str(Path(tempfile.gettempdir()) / "dummy_key.pem"),
        "USER_AUTH_JWT__KEY_ID": "key-1",
        "USER_AUTH_JWT__ISSUER": "nohiki",
        "USER_AUTH_JWT__AUDIENCE": "nohiki",
        "USER_AUTH_COOKIE__ACCESS_TOKEN_NAME": _ACCESS_TOKEN_COOKIE,
        "USER_AUTH_COOKIE__REFRESH_TOKEN_NAME": "__Host-nohiki_rt",
        "USER_AUTH_SECURITY__CORS_ALLOWED_ORIGINS": _DEV_FRONTEND_ORIGIN,
        "USER_AUTH_KAFKA__DSN": "kafka://localhost:29092",
    },
)


def _set_env_defaults(env_vars: dict[str, str]) -> None:
    """Set environment variable defaults without overwriting existing values."""
    for key, value in env_vars.items():
        os.environ.setdefault(key, value)


def _get_fastapi_app(module_path: str) -> FastAPI:
    """Import a module and extract its FastAPI app instance.

    Args:
        module_path: Dotted import path (e.g. bff_service.main).

    Returns:
        The FastAPI application instance.

    Raises:
        TypeError: If the module does not expose a FastAPI instance.
    """
    module = importlib.import_module(module_path)
    app = getattr(module, "app", None)
    if not isinstance(app, FastAPI):
        msg = f"Module '{module_path}' does not expose a FastAPI instance at attribute 'app'"
        raise TypeError(msg)
    return app


def _rebuild_pydantic_models(config: ServiceConfig) -> None:
    """Rebuild Pydantic models to resolve PEP 563 forward references.

    PEP 563 makes all annotations into string forward references. Pydantic
    models using these must be explicitly rebuilt so type resolution works
    before OpenAPI schema generation.

    Args:
        config: Service configuration identifying which service to rebuild.
    """
    try:
        match config.name:
            case "user-auth-service":
                from user_auth_service.core import config as config_module
                from user_auth_service.core import cookies, oauth_state
                from user_auth_service.services import oauth_service

                settings_cls = config_module.Settings
                settings_cls.model_rebuild(_types_namespace={"Settings": settings_cls})
                console.print("[dim]Rebuilt user_auth_service.Settings model[/dim]")

                for mod in (cookies, oauth_state, oauth_service):
                    mod.Settings = settings_cls

            case "bff-service":
                from bff_service.core import config as config_module

                settings_cls = config_module.Settings
                settings_cls.model_rebuild(_types_namespace={"Settings": settings_cls})
                console.print("[dim]Rebuilt bff_service.Settings model[/dim]")
    except (ImportError, AttributeError) as e:
        console.print(f"[yellow]Warning: Could not rebuild Settings: {e}[/yellow]")


def export_service_openapi(config: ServiceConfig) -> OpenAPISpec:
    """Export OpenAPI spec from a FastAPI service.

    Args:
        config: Service configuration with module path and env vars.

    Returns:
        Generated OpenAPI specification dict.

    Raises:
        ImportError: If the service module cannot be imported.
        TypeError: If the module does not expose a FastAPI app.
    """
    _set_env_defaults(config.env_vars)
    sys.path.insert(0, str(config.package_path))
    _rebuild_pydantic_models(config)

    app = _get_fastapi_app(config.module_path)
    spec: OpenAPISpec = app.openapi()

    paths = spec.get("paths")
    path_count = len(paths) if isinstance(paths, dict) else 0
    console.print(f"[green]Exported {config.name}:[/green] {path_count} paths")
    return spec


def _get_component_schemas(spec: OpenAPISpec) -> SchemasDict:
    """Extract the schemas dict from an OpenAPI spec components section.

    Args:
        spec: OpenAPI specification dict.

    Returns:
        Schemas dict, or empty dict if not present.
    """
    components = spec.get("components", {})
    if not isinstance(components, dict):
        return {}
    schemas = components.get("schemas", {})
    return schemas if isinstance(schemas, dict) else {}


def _extract_identity_paths(spec: OpenAPISpec) -> PathsDict:
    """Extract identity-service paths (auth, account, JWKS endpoints).

    Args:
        spec: OpenAPI specification from user-auth-service.

    Returns:
        Filtered paths dict containing only identity endpoints.
    """
    paths = spec.get("paths", {})
    if not isinstance(paths, dict):
        return {}
    return {p: m for p, m in paths.items() if p.startswith(_IDENTITY_PATH_PREFIXES)}


def _extract_bff_paths(spec: OpenAPISpec) -> PathsDict:
    """Extract public BFF paths, excluding internal health/readiness endpoints.

    Args:
        spec: OpenAPI specification from bff-service.

    Returns:
        Filtered paths dict with internal paths removed.
    """
    paths = spec.get("paths", {})
    if not isinstance(paths, dict):
        return {}
    return {p: m for p, m in paths.items() if p not in _INTERNAL_PATHS}


def _schemas_structurally_equal(a: JSONValue, b: JSONValue) -> bool:
    """Compare two schema dicts for structural equivalence, ignoring 'title'.

    The 'title' field is excluded because FastAPI auto-generates it from
    the class name, which may differ between services even when the schema
    structure is identical (e.g. both services produce HTTPValidationError
    from the same FastAPI internals).

    Args:
        a: First schema dict.
        b: Second schema dict.

    Returns:
        True if schemas are structurally identical (ignoring title).
    """
    if not isinstance(a, dict) or not isinstance(b, dict):
        return a == b
    a_filtered = {k: v for k, v in a.items() if k != "title"}
    b_filtered = {k: v for k, v in b.items() if k != "title"}
    return json.dumps(a_filtered, sort_keys=True) == json.dumps(b_filtered, sort_keys=True)


def _merge_schemas(
    identity_schemas: SchemasDict,
    bff_schemas: SchemasDict,
) -> SchemasDict:
    """Merge schemas from both services, deduplicating collisions.

    Non-colliding schemas are added directly. Colliding schemas must be
    structurally identical (ignoring title); the BFF version is kept.
    Raises if colliding schemas differ structurally.

    Args:
        identity_schemas: Schemas from the user-auth-service.
        bff_schemas: Schemas from the bff-service.

    Returns:
        Combined schemas dict.

    Raises:
        ValueError: If colliding schemas are not structurally identical.
    """
    collisions = frozenset(identity_schemas) & frozenset(bff_schemas)
    for name in sorted(collisions):
        if not _schemas_structurally_equal(identity_schemas[name], bff_schemas[name]):
            msg = (
                f"Schema collision for '{name}': auth-service and bff-service "
                f"define structurally different schemas with the same name. "
                f"This must be resolved before the specs can be merged."
            )
            raise ValueError(msg)
        console.print(f"[dim]Deduplicated colliding schema: {name}[/dim]")

    unique_identity = {k: v for k, v in identity_schemas.items() if k not in collisions}
    return unique_identity | bff_schemas


def _collect_unique_tags(specs: list[OpenAPISpec]) -> list[JSONValue]:
    """Collect unique tags from multiple specs, preserving first-occurrence order.

    Args:
        specs: List of OpenAPI specification dicts.

    Returns:
        De-duplicated list of tag objects.
    """
    seen: set[str] = set()
    tags: list[JSONValue] = []
    for spec in specs:
        raw_tags = spec.get("tags", [])
        if not isinstance(raw_tags, list):
            continue
        for tag in raw_tags:
            if not isinstance(tag, dict):
                continue
            tag_name = tag.get("name", "")
            if isinstance(tag_name, str) and tag_name and tag_name not in seen:
                seen.add(tag_name)
                tags.append(tag)
    return tags


def merge_specs(bff_spec: OpenAPISpec, identity_spec: OpenAPISpec) -> OpenAPISpec:
    """Merge BFF and identity OpenAPI specs into a single canonical spec.

    Schemas from both services are combined directly (no prefixing).
    Colliding schema names are deduplicated: structural equivalence is
    asserted and the BFF version is kept. The build fails loudly if
    colliding schemas differ structurally.

    Args:
        bff_spec: OpenAPI spec from the BFF service.
        identity_spec: OpenAPI spec from the user-auth service.

    Returns:
        Merged OpenAPI spec with all paths and schemas combined.

    Raises:
        ValueError: If colliding schemas are not structurally identical.
    """
    merged_schemas = _merge_schemas(
        _get_component_schemas(identity_spec),
        _get_component_schemas(bff_spec),
    )

    return {
        "openapi": _OPENAPI_VERSION,
        "info": {
            "title": "Nohiki API",
            "description": "Nohiki Platform API - combined identity and BFF endpoints",
            "version": "1.0.0",
        },
        "paths": _extract_identity_paths(identity_spec) | _extract_bff_paths(bff_spec),
        "components": {
            "schemas": merged_schemas,
            "securitySchemes": {
                "cookieAuth": {
                    "type": "apiKey",
                    "in": "cookie",
                    "name": _ACCESS_TOKEN_COOKIE,
                    "description": "JWT access token in HTTP-only cookie",
                },
            },
        },
        "tags": _collect_unique_tags([identity_spec, bff_spec]),
    }


def write_spec(spec: OpenAPISpec, output_path: Path) -> None:
    """Write OpenAPI spec to a JSON file.

    Args:
        spec: OpenAPI specification dict to serialize.
        output_path: Filesystem path for the output JSON file.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(spec, f, indent=2)
    console.print(f"[green]Wrote spec to:[/green] {output_path}")


def export_service_spec(config: ServiceConfig) -> OpenAPISpec:
    """Export one service in an isolated interpreter.

    Importing multiple instrumented FastAPI applications in one interpreter
    mutates OpenTelemetry global providers and emits duplicate-instrumentation
    warnings. A short-lived child process gives every application a clean
    runtime while the parent retains deterministic merge and output handling.

    Args:
        config: Service configuration to export.

    Returns:
        Generated OpenAPI specification dict.

    Raises:
        RuntimeError: If the isolated export fails or returns invalid JSON.
    """
    with tempfile.TemporaryDirectory(prefix="nohiki-openapi-") as tmpdir:
        spec_path = Path(tmpdir) / "spec.json"
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--service", config.name, "--output", str(spec_path)],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            details = result.stderr.strip() or result.stdout.strip() or "unknown child-process failure"
            msg = f"Failed to export {config.name}: {details}"
            raise RuntimeError(msg)

        value: object = json.loads(spec_path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            msg = f"Invalid OpenAPI document returned by {config.name}"
            raise TypeError(msg)
        return cast("OpenAPISpec", value)


cli = typer.Typer(
    name="export-openapi",
    help="Export combined OpenAPI spec from identity-service and bff-service.",
    no_args_is_help=False,
)


@cli.command()
def main(
    output: Annotated[
        Path,
        typer.Option("--output", "-o", help="Output path for the OpenAPI spec."),
    ] = OUTPUT_PATH,
    service: Annotated[
        str | None,
        typer.Option("--service", hidden=True, help="Export one service in an isolated child process."),
    ] = None,
) -> None:
    """Export combined OpenAPI spec to docs/api/nohiki.openapi.json."""
    if service is not None:
        configs = {config.name: config for config in (BFF_CONFIG, AUTH_CONFIG)}
        config = configs.get(service)
        if config is None:
            choices = ", ".join(sorted(configs))
            msg = f"Unknown service {service!r}; expected one of: {choices}"
            raise typer.BadParameter(msg)
        write_spec(export_service_openapi(config), output)
        return

    console.print("[blue]Exporting OpenAPI specs...[/blue]")

    with ThreadPoolExecutor(max_workers=2) as executor:
        bff_spec, auth_spec = executor.map(export_service_spec, (BFF_CONFIG, AUTH_CONFIG))

    console.print("[blue]Merging specs...[/blue]")
    merged = merge_specs(bff_spec, auth_spec)

    paths = merged.get("paths")
    components = merged.get("components")
    schemas = components.get("schemas") if isinstance(components, dict) else None
    path_count = len(paths) if isinstance(paths, dict) else 0
    schema_count = len(schemas) if isinstance(schemas, dict) else 0
    console.print(f"[green]Total paths:[/green] {path_count}, [green]Total schemas:[/green] {schema_count}")

    write_spec(merged, output)
    console.print("[green]Done![/green]")


if __name__ == "__main__":
    cli()
