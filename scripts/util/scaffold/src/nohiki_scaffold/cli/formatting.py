"""Shared formatting helpers for CLI output."""

from __future__ import annotations

from typing import cast

from nohiki_scaffold.core.models import LibSpec, ServiceSpec


def yes_no(*, value: bool) -> str:
    """Return 'yes' or 'no' for a boolean.

    Args:
        value: Boolean value.

    Returns:
        'yes' if True, 'no' if False.
    """
    return "yes" if value else "no"


def format_service_summary(spec: ServiceSpec) -> list[tuple[str, str]]:
    """Return a list of (label, value) rows describing a ServiceSpec for display.

    Args:
        spec: ServiceSpec to format.

    Returns:
        List of (label, value) tuples for display in a table.
    """
    kafka_handlers = ", ".join(sorted(h.value for h in spec.kafka.handlers)) or "(none)"
    ml_deps = []
    if spec.ml.llm.enabled:
        ml_deps.append(f"llm={spec.ml.llm.provider}/{spec.ml.llm.model}")
    if spec.ml.qdrant.enabled:
        ml_deps.append(f"qdrant={spec.ml.qdrant.collection_entity}")
    ml_deps_str = ", ".join(ml_deps) or "(none)"

    rows: list[tuple[str, str]] = [
        ("Name", spec.name),
        ("Friendly name", spec.friendly_name),
        ("Description", spec.description),
        ("Owner", spec.owner),
        ("Shape", spec.shape.value),
        ("Module name", spec.module_name),
        ("Env prefix", spec.env_prefix),
    ]

    if spec.database.enabled:
        rows.extend(
            [
                ("Database", "enabled"),
                ("  Schema", spec.database.schema_name),
                ("  Outbox", yes_no(value=spec.database.outbox)),
                ("  Alembic", yes_no(value=spec.database.alembic)),
                ("  Saga", yes_no(value=spec.database.saga)),
                ("  Freshness tracking", yes_no(value=spec.database.freshness_tracking)),
                ("  State machine", yes_no(value=spec.database.state_machine)),
            ]
        )
    else:
        rows.append(("Database", "disabled"))

    if spec.redis.enabled:
        rows.append(("Redis", "enabled"))
        if spec.redis.bootstrap_distributed_lock:
            rows.append(("  Distributed lock", "yes"))
        if spec.redis.circuit_breaker_for_ext_http:
            rows.append(("  Circuit breaker", "yes"))
    else:
        rows.append(("Redis", "disabled"))

    rows.extend(
        [
            ("Kafka role", spec.kafka.role.value),
            ("  Handlers", kafka_handlers),
            ("  Embedding callback", yes_no(value=spec.kafka.embedding_callback)),
        ]
    )
    if spec.kafka.max_concurrent_handlers is not None:
        rows.append(("  Max concurrent", str(spec.kafka.max_concurrent_handlers)))

    if spec.s3.enabled:
        rows.extend(
            [
                ("S3", "enabled"),
                ("  Bucket", cast("str", spec.s3.bucket_name)),
                ("  Key prefix", spec.s3.key_prefix or "(root)"),
            ]
        )
    else:
        rows.append(("S3", "disabled"))

    rows.append(("ML", ml_deps_str))
    if spec.ml.manifest:
        rows.append(("  Manifest", "yes"))
    if spec.ml.service_holder_pattern:
        rows.append(("  Service holder", "yes"))
    if spec.ml.fail_fast_validation:
        rows.append(("  Fail fast", "yes"))

    return rows


def format_lib_summary(spec: LibSpec) -> list[tuple[str, str]]:
    """Return a list of (label, value) rows describing a LibSpec for display.

    Args:
        spec: LibSpec to format.

    Returns:
        List of (label, value) tuples for display in a table.
    """
    extras_str = ", ".join(sorted(spec.optional_extras.keys())) if spec.optional_extras else "(none)"
    deps_str = ", ".join(sorted(spec.base_dependencies)) if spec.base_dependencies else "(none)"

    rows: list[tuple[str, str]] = [
        ("Name", spec.name),
        ("Module name", spec.module_name),
        ("Description", spec.description),
        ("Owner", spec.owner),
        ("Namespace package", yes_no(value=spec.namespace_package)),
        ("Testing module", yes_no(value=spec.ships_testing_module)),
        ("Exceptions module", yes_no(value=spec.ships_exceptions_module)),
        ("Base dependencies", deps_str),
        ("Optional extras", extras_str),
    ]

    if spec.ships_console_script:
        rows.append(("Console script", spec.ships_console_script))

    return rows


__all__ = ["format_lib_summary", "format_service_summary", "yes_no"]
