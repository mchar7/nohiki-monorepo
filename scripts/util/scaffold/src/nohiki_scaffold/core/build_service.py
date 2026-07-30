"""Build plan for service packages.

Handles all four service archetypes via feature-driven template selection.
The archetype choice is NOT a top-level enum — it emerges from the combination
of `ServiceShape`, `KafkaRole`, and the database/redis/s3/ml option blocks on
the spec. Templates are conditionally included based on those flags.
"""

from __future__ import annotations

from pathlib import Path

from nohiki_scaffold.core.build import (
    BuildPlan,
    FileWrite,
    TomlEdit,
    _add_ty_root,
    _add_workspace_member,
    _service_section_comment,
)
from nohiki_scaffold.core.features import KafkaRole, ServiceShape
from nohiki_scaffold.core.models import ServiceSpec
from nohiki_scaffold.templates.loader import get_environment


def _render_context(spec: ServiceSpec) -> dict[str, object]:
    """Build the Jinja rendering context from a ServiceSpec.

    Everything templates need is exposed here by name. Templates do not reach
    into `spec.X.Y` — they consume pre-computed helpers so the spec shape can
    evolve without rewriting every template.
    """
    return {
        "spec": spec,
        "module_name": spec.module_name,
        "service_name": spec.name,
        "friendly_name": spec.friendly_name,
        "description": spec.description,
        "owner": spec.owner,
        "env_prefix_no_trailing": spec.env_prefix.rstrip("_"),
        "env_prefix": spec.env_prefix,
        "shape": spec.shape,
        "kafka": spec.kafka,
        "database": spec.database,
        "redis": spec.redis,
        "s3": spec.s3,
        "ml": spec.ml,
        "has_http": spec.shape is not ServiceShape.KAFKA_ONLY,
        "has_consumer": spec.kafka.role in {KafkaRole.CONSUMER_ONLY, KafkaRole.BOTH},
        "has_producer": spec.kafka.role in {KafkaRole.PRODUCER_ONLY, KafkaRole.BOTH},
    }


def _service_file(target: Path, rel: str, template: str, env_ctx: dict[str, object], trigger: str) -> FileWrite:
    env = get_environment()
    return FileWrite(
        path=target / rel,
        content=env.get_template(template).render(env_ctx),
        trigger=trigger,
    )


def build_service_plan(spec: ServiceSpec, *, repo_root: Path) -> BuildPlan:
    """Return a BuildPlan for a service package.

    The file list is constructed in a single pass keyed off feature flags.
    Order does not matter for writes (each is atomic) but keeping it stable
    makes goldens diff-friendly.
    """
    target = repo_root / "backend" / "services" / spec.name
    ctx = _render_context(spec)
    files: list[FileWrite] = []

    files.append(_service_file(target, "pyproject.toml", "service/pyproject.toml.j2", ctx, "core"))
    files.append(_service_file(target, "Dockerfile", "service/Dockerfile.j2", ctx, "core"))
    files.append(_service_file(target, "README.md", "service/README.md.j2", ctx, "core"))
    files.append(_service_file(target, ".env.example", "service/env.example.j2", ctx, "core"))
    files.append(
        _service_file(target, f"src/{spec.module_name}/__init__.py", "service/src/__init__.py.j2", ctx, "core")
    )
    files.append(_service_file(target, f"src/{spec.module_name}/main.py", "service/src/main.py.j2", ctx, "core"))
    files.append(
        _service_file(
            target, f"src/{spec.module_name}/core/__init__.py", "service/src/core/__init__.py.j2", ctx, "core"
        )
    )
    files.append(
        _service_file(target, f"src/{spec.module_name}/core/config.py", "service/src/core/config.py.j2", ctx, "core")
    )
    files.append(
        _service_file(target, f"src/{spec.module_name}/core/kafka.py", "service/src/core/kafka.py.j2", ctx, "core")
    )
    files.append(
        FileWrite(
            path=target / "src" / spec.module_name / "services" / "__init__.py",
            content='"""Business service layer."""\n',
            trigger="core",
        )
    )

    if spec.database.enabled:
        files.append(
            _service_file(
                target,
                f"src/{spec.module_name}/db/__init__.py",
                "service/src/db/__init__.py.j2",
                ctx,
                "database.enabled",
            )
        )
        files.append(
            _service_file(
                target,
                f"src/{spec.module_name}/db/models.py",
                "service/src/db/models.py.j2",
                ctx,
                "database.enabled",
            )
        )
        if spec.database.alembic:
            files.append(_service_file(target, "alembic.ini", "service/alembic.ini.j2", ctx, "database.alembic"))
            files.append(_service_file(target, "alembic/env.py", "service/alembic/env.py.j2", ctx, "database.alembic"))
            # script.py.mako is verbatim (no Jinja rendering)
            files.append(
                _service_file(
                    target,
                    "alembic/script.py.mako",
                    "service/alembic/script.py.mako.j2",
                    ctx,
                    "database.alembic",
                )
            )
            files.append(
                FileWrite(
                    path=target / "alembic" / "versions" / ".gitkeep",
                    content="",
                    trigger="database.alembic",
                )
            )

    if spec.shape is not ServiceShape.KAFKA_ONLY:
        if spec.database.enabled:
            files.append(
                _service_file(target, f"src/{spec.module_name}/core/db.py", "service/src/core/db.py.j2", ctx, "http.db")
            )
        files.append(
            _service_file(
                target,
                f"src/{spec.module_name}/api/__init__.py",
                "service/src/api/__init__.py.j2",
                ctx,
                "http",
            )
        )
        files.append(
            _service_file(
                target,
                f"src/{spec.module_name}/api/routers/__init__.py",
                "service/src/api/routers/__init__.py.j2",
                ctx,
                "http",
            )
        )
        files.append(
            _service_file(
                target,
                f"src/{spec.module_name}/api/schemas/__init__.py",
                "service/src/api/schemas/__init__.py.j2",
                ctx,
                "http",
            )
        )

    has_consumer = spec.kafka.role in {KafkaRole.CONSUMER_ONLY, KafkaRole.BOTH}
    if has_consumer:
        files.append(
            _service_file(
                target,
                f"src/{spec.module_name}/events/__init__.py",
                "service/src/events/__init__.py.j2",
                ctx,
                "kafka.consumer",
            )
        )
        for kind in sorted(spec.kafka.handlers, key=lambda k: k.value):
            kind_val = kind.value.replace("-", "_")
            files.append(
                _service_file(
                    target,
                    f"src/{spec.module_name}/events/{kind_val}.py",
                    f"service/src/events/{kind_val}.py.j2",
                    ctx,
                    f"kafka.handlers.{kind_val}",
                )
            )
        if spec.ml.service_holder_pattern:
            files.append(
                _service_file(
                    target,
                    f"src/{spec.module_name}/events/handlers.py",
                    "service/src/events/handlers.py.j2",
                    ctx,
                    "ml.service_holder_pattern",
                )
            )

    if spec.kafka.role in {KafkaRole.PRODUCER_ONLY, KafkaRole.BOTH} or spec.database.outbox:
        # Ensure events/ package exists if producer-only (no consumer created it).
        events_init_path = target / "src" / spec.module_name / "events" / "__init__.py"
        if not any(fw.path == events_init_path for fw in files):
            files.append(
                FileWrite(
                    path=events_init_path,
                    content='"""Event publishers for this service."""\n',
                    trigger="kafka.producer",
                )
            )
        files.append(
            _service_file(
                target,
                f"src/{spec.module_name}/events/publishers.py",
                "service/src/events/publishers.py.j2",
                ctx,
                "kafka.publishers",
            )
        )

    if spec.redis.enabled:
        files.append(
            _service_file(
                target,
                f"src/{spec.module_name}/core/cache.py",
                "service/src/core/cache.py.j2",
                ctx,
                "redis.enabled",
            )
        )
    if spec.redis.bootstrap_distributed_lock:
        files.append(
            _service_file(
                target,
                f"src/{spec.module_name}/core/seeder.py",
                "service/src/core/seeder.py.j2",
                ctx,
                "redis.bootstrap_distributed_lock",
            )
        )

    if spec.s3.enabled:
        files.append(
            _service_file(
                target,
                f"src/{spec.module_name}/services/storage.py",
                "service/src/services/storage.py.j2",
                ctx,
                "s3",
            )
        )

    if spec.kafka.embedding_callback:
        files.append(
            _service_file(
                target,
                f"src/{spec.module_name}/core/embedding.py",
                "service/src/core/embedding.py.j2",
                ctx,
                "kafka.embedding_callback",
            )
        )
    if spec.ml.fail_fast_validation:
        files.append(
            _service_file(
                target,
                f"src/{spec.module_name}/core/validation.py",
                "service/src/core/validation.py.j2",
                ctx,
                "ml.fail_fast_validation",
            )
        )

    files.append(
        FileWrite(
            path=target / "tests" / "__init__.py",
            content='"""Test suite."""\n',
            trigger="core",
        )
    )
    files.append(_service_file(target, "tests/conftest.py", "service/tests/conftest.py.j2", ctx, "core"))
    files.append(
        FileWrite(
            path=target / "tests" / "unit" / "__init__.py",
            content='"""Unit tests."""\n',
            trigger="core",
        )
    )
    files.append(_service_file(target, "tests/unit/test_smoke.py", "service/tests/test_smoke.py.j2", ctx, "core"))

    member_path = f"backend/services/{spec.name}"
    src_path = f"backend/services/{spec.name}/src"
    root_edits: tuple[TomlEdit, ...] = (
        _add_workspace_member(member_path, section_comment=_service_section_comment(spec.name)),
        _add_ty_root(src_path),
    )

    hints: list[str] = [
        f"[dim]Service [bold]{spec.name}[/bold] is now a workspace member.[/dim]",
    ]
    if spec.kafka.handlers or spec.kafka.role is not KafkaRole.NONE:
        hints.append(
            "[yellow]Kafka topics[/yellow]: add topic constants to "
            "[cyan]backend/libs/nohiki-kafka-client/src/nohiki_kafka_client/topics.py[/cyan] "
            "and wire them into the handler decorators.",
        )
    if spec.shape is not ServiceShape.KAFKA_ONLY:
        hints.append(
            "[yellow]Gateway[/yellow]: register HTTP routes with Traefik / kgateway under "
            "[cyan]infra/[/cyan] if this service should be externally reachable.",
        )
    hints.append(
        "[yellow]Infra[/yellow]: add [cyan]docker-compose[/cyan] and "
        "[cyan]helm[/cyan] entries under [cyan]infra/[/cyan]; scaffolder intentionally "
        "does not auto-edit these.",
    )
    hints.append(
        '[yellow]CONTRIBUTING.md[/yellow]: add an entry to the "Service Kafka Roles" table '
        "describing this service's Produces/Consumes/Pattern.",
    )

    return BuildPlan(spec=spec, files=tuple(files), root_edits=root_edits, hints=tuple(hints))
