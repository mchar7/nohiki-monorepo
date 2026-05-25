"""Interactive prompts for spec construction."""

from __future__ import annotations

from typing import cast

import click
import typer

from nohiki_scaffold.core.features import HandlerKind, KafkaRole, ServiceShape
from nohiki_scaffold.core.models import (
    DatabaseOptions,
    KafkaOptions,
    LibSpec,
    LLMOptions,
    MLOptions,
    QdrantEntity,
    QdrantOptions,
    RedisOptions,
    S3Options,
    ServiceSpec,
)
from nohiki_scaffold.core.naming import env_prefix as derive_env_prefix
from nohiki_scaffold.core.naming import module_name as derive_module_name
from nohiki_scaffold.core.naming import schema_name as derive_schema_name


def prompt_service_spec(
    *,
    name: str | None = None,
    friendly_name: str | None = None,
    description: str | None = None,
    owner: str | None = None,
    shape: ServiceShape | str | None = None,
    env_prefix: str | None = None,
    module_name: str | None = None,
    db: bool = False,
    schema_name: str | None = None,
    outbox: bool = False,
    alembic: bool = False,
    redis: bool = False,
    kafka_role: KafkaRole | str | None = None,
    handler: list[str] | None = None,
    embedding_callback: bool = False,
    max_concurrent_handlers: int | None = None,
    s3: bool = False,
    s3_bucket: str | None = None,
    s3_key_prefix: str | None = None,
    llm: bool = False,
    llm_provider: str | None = None,
    llm_model: str | None = None,
    llm_api_key_env: str | None = None,
    qdrant: bool = False,
    qdrant_collection_entity: str | None = None,
    manifest: bool = False,
    service_holder_pattern: bool = False,
    fail_fast_validation: bool = False,
    non_interactive: bool = False,
) -> ServiceSpec:
    """Interactively build a ServiceSpec, using any pre-supplied values as defaults.

    Args:
        name: Service distribution name (kebab-case).
        friendly_name: Human-friendly display name.
        description: Service description.
        owner: Owner field (team or squad).
        shape: Service shape (kafka-only, http-only, http+kafka).
        env_prefix: Env-var prefix override; derived from name if omitted.
        module_name: Python module name override; derived from name if omitted.
        db: Enable database integration.
        schema_name: Postgres schema name; derived from name if omitted when db is enabled.
        outbox: Enable transactional outbox (requires db).
        alembic: Enable Alembic migrations (requires db).
        redis: Enable Redis integration.
        kafka_role: Kafka role (none, producer-only, consumer-only, both).
        handler: Handler kinds (commands, callbacks, upstream-cdc, feedback, backfill).
        embedding_callback: Wire the embedding callback handler.
        max_concurrent_handlers: Cap on concurrent Kafka handlers (1-200).
        s3: Enable S3 integration.
        s3_bucket: S3 bucket name (required when s3=True).
        s3_key_prefix: Optional S3 key prefix.
        llm: Enable LLM integration.
        llm_provider: LLM provider (e.g. openai).
        llm_model: LLM model name (e.g. gpt-4o).
        llm_api_key_env: Env-var holding the LLM API key.
        qdrant: Enable Qdrant integration.
        qdrant_collection_entity: Qdrant collection entity (jobs/profiles/skills/occupations).
        manifest: Enable the ML encoding manifest.
        service_holder_pattern: Use the ``_ServiceHolder`` pattern for heavy ML services.
        fail_fast_validation: Enable strict manifest validation at startup.
        non_interactive: Skip prompts; rely solely on provided values.

    Returns:
        Constructed and validated ServiceSpec.
    """

    def _ask(prompt_text: str, default: str | None = None, *, show_default: bool = True) -> str:
        if non_interactive:
            return default or ""
        if default is None:
            return typer.prompt(prompt_text)
        return typer.prompt(prompt_text, default=default, show_default=show_default)

    def _confirm(prompt_text: str, *, current: bool, ask: bool) -> bool:
        if not ask or non_interactive:
            return current
        return typer.confirm(prompt_text, default=current)

    svc_name = name or _ask("Service name (kebab-case, e.g. 'job-storage-service')")
    if not svc_name:
        msg = "Service name is required"
        raise ValueError(msg)

    svc_friendly = friendly_name or _ask("Friendly name", default=svc_name.replace("-", " ").title())
    svc_description = description or _ask("Description")
    if not svc_description:
        msg = "Service description is required"
        raise ValueError(msg)
    svc_owner = owner or _ask("Owner", default="platform")

    shape_val: ServiceShape
    if isinstance(shape, ServiceShape):
        shape_val = shape
    elif isinstance(shape, str):
        shape_val = ServiceShape(shape)
    elif non_interactive:
        shape_val = ServiceShape.KAFKA_ONLY
    else:
        shape_choice = typer.prompt(
            "Service shape",
            type=click.Choice([s.value for s in ServiceShape]),
            default=ServiceShape.KAFKA_ONLY.value,
        )
        shape_val = ServiceShape(shape_choice)

    env_prefix_val = env_prefix or derive_env_prefix(svc_name)
    module_name_val = module_name or derive_module_name(svc_name)

    db_enabled = _confirm("Enable database?", current=db, ask=not db)
    db_schema = schema_name or ""
    db_outbox = outbox
    db_alembic_flag = alembic
    db_saga = False
    db_freshness = False
    db_state_machine = False

    if db_enabled:
        db_schema = schema_name or derive_schema_name(svc_name)
        db_outbox = _confirm("Enable transactional outbox?", current=outbox, ask=not outbox)
        db_alembic_flag = _confirm("Enable Alembic migrations?", current=alembic, ask=not alembic)
        db_saga = _confirm("Enable saga pattern?", current=False, ask=True)
        db_freshness = _confirm("Enable freshness tracking?", current=False, ask=True)
        db_state_machine = _confirm("Enable state machine?", current=False, ask=True)

    database = DatabaseOptions(
        enabled=db_enabled,
        schema_name=db_schema,
        outbox=db_outbox,
        alembic=db_alembic_flag,
        saga=db_saga,
        freshness_tracking=db_freshness,
        state_machine=db_state_machine,
    )

    redis_enabled = _confirm("Enable Redis?", current=redis, ask=not redis)
    redis_lock_val = False
    redis_cb_val = False
    if redis_enabled:
        redis_lock_val = _confirm("Enable distributed lock bootstrap?", current=False, ask=True)
        redis_cb_val = _confirm("Enable circuit breaker for external HTTP?", current=False, ask=True)

    redis_opts = RedisOptions(
        enabled=redis_enabled,
        bootstrap_distributed_lock=redis_lock_val,
        circuit_breaker_for_ext_http=redis_cb_val,
    )

    role_val: KafkaRole
    if isinstance(kafka_role, KafkaRole):
        role_val = kafka_role
    elif isinstance(kafka_role, str):
        role_val = KafkaRole(kafka_role)
    elif non_interactive:
        role_val = KafkaRole.NONE
    else:
        role_choice = typer.prompt(
            "Kafka role",
            type=click.Choice([r.value for r in KafkaRole]),
            default=KafkaRole.NONE.value,
        )
        role_val = KafkaRole(role_choice)

    handlers_val: frozenset[HandlerKind] = frozenset()
    if handler:
        handlers_val = frozenset(HandlerKind(h.replace("_", "-")) for h in handler)
    elif role_val in {KafkaRole.CONSUMER_ONLY, KafkaRole.BOTH} and not non_interactive:
        raw = typer.prompt(
            "Handler kinds (comma-separated: commands,callbacks,upstream-cdc,feedback,backfill) or blank",
            default="",
            show_default=False,
        )
        if raw:
            handlers_val = frozenset(HandlerKind(h.strip()) for h in raw.split(",") if h.strip())

    concurrent_val = max_concurrent_handlers
    if concurrent_val is None and role_val in {KafkaRole.CONSUMER_ONLY, KafkaRole.BOTH} and not non_interactive:
        raw = typer.prompt(
            "Max concurrent handlers (1-200, blank for default)",
            default="",
            show_default=False,
        )
        if raw:
            concurrent_val = int(raw)

    kafka_opts = KafkaOptions(
        role=role_val,
        handlers=handlers_val,
        embedding_callback=embedding_callback,
        max_concurrent_handlers=concurrent_val,
    )

    s3_enabled_flag = _confirm("Enable S3?", current=s3, ask=not s3)
    bucket_val = s3_bucket
    prefix_val = s3_key_prefix
    if s3_enabled_flag:
        if bucket_val is None:
            bucket_val = _ask("S3 bucket name")
        if prefix_val is None and not non_interactive:
            raw_prefix = _ask("S3 key prefix (blank for root)", default="", show_default=False)
            prefix_val = raw_prefix or None

    s3_opts = S3Options(
        enabled=s3_enabled_flag,
        bucket_name=bucket_val if s3_enabled_flag else None,
        key_prefix=prefix_val if s3_enabled_flag else None,
    )

    llm_enabled_flag = _confirm("Enable LLM integration?", current=llm, ask=not llm)
    provider_val = llm_provider
    model_val = llm_model
    api_key_val = llm_api_key_env
    if llm_enabled_flag:
        if provider_val is None:
            provider_val = _ask("LLM provider (e.g. 'openai')")
        if model_val is None:
            model_val = _ask("LLM model (e.g. 'gpt-4o')")
        if api_key_val is None and not non_interactive:
            raw = _ask("API key environment variable", default="", show_default=False)
            api_key_val = raw or None

    llm_opts = LLMOptions(
        enabled=llm_enabled_flag,
        provider=provider_val if llm_enabled_flag else None,
        model=model_val if llm_enabled_flag else None,
        api_key_env=api_key_val if llm_enabled_flag else None,
    )

    qdrant_enabled_flag = _confirm("Enable Qdrant integration?", current=qdrant, ask=not qdrant)
    entity_val = qdrant_collection_entity
    if qdrant_enabled_flag and entity_val is None and not non_interactive:
        entity_val = typer.prompt(
            "Qdrant collection entity",
            type=click.Choice(["jobs", "profiles", "skills", "occupations"]),
        )

    qdrant_opts = QdrantOptions(
        enabled=qdrant_enabled_flag,
        collection_entity=cast("QdrantEntity | None", entity_val) if qdrant_enabled_flag else None,
    )

    manifest_flag = _confirm("Enable ML manifest?", current=manifest, ask=not manifest)
    holder_flag = _confirm(
        "Use _ServiceHolder pattern?", current=service_holder_pattern, ask=not service_holder_pattern
    )
    fail_fast_flag = _confirm(
        "Enable fail-fast manifest validation?",
        current=fail_fast_validation,
        ask=not fail_fast_validation,
    )

    ml_opts = MLOptions(
        llm=llm_opts,
        qdrant=qdrant_opts,
        manifest=manifest_flag,
        service_holder_pattern=holder_flag,
        fail_fast_validation=fail_fast_flag,
    )

    return ServiceSpec(
        name=svc_name,
        friendly_name=svc_friendly,
        description=svc_description,
        owner=svc_owner,
        shape=shape_val,
        env_prefix=env_prefix_val,
        module_name=module_name_val,
        database=database,
        redis=redis_opts,
        kafka=kafka_opts,
        s3=s3_opts,
        ml=ml_opts,
    )


def prompt_lib_spec(
    *,
    name: str | None,
    description: str | None,
    owner: str | None,
    module_name: str | None = None,
    namespace_package: bool | None = None,
    ships_testing_module: bool | None = None,
    ships_exceptions_module: bool | None = None,
    ships_console_script: str | None = None,
    non_interactive: bool = False,
) -> LibSpec:
    """Interactively build a LibSpec.

    Args:
        name: Library distribution name if provided.
        description: Library description if provided.
        owner: Owner field if provided.
        module_name: Module name if provided (auto-derived if omitted).
        namespace_package: Whether this is a namespace package.
        ships_testing_module: Whether testing module is included.
        ships_exceptions_module: Whether exceptions module is included.
        ships_console_script: Console script name if included.
        non_interactive: Skip prompts; use only values already supplied.

    Returns:
        Constructed and validated LibSpec.
    """
    lib_name = name or (None if non_interactive else typer.prompt("Library name (kebab-case, e.g. 'nohiki-my-lib')"))
    if not lib_name:
        msg = "Library name is required"
        raise ValueError(msg)

    lib_description = description or (None if non_interactive else typer.prompt("Description"))
    if not lib_description:
        msg = "Library description is required"
        raise ValueError(msg)

    lib_owner = owner or ("platform" if non_interactive else typer.prompt("Owner", default="platform"))

    lib_module_name = module_name or derive_module_name(lib_name)

    if namespace_package is None:
        lib_namespace = False if non_interactive else typer.confirm("Namespace package?", default=False)
    else:
        lib_namespace = namespace_package

    if ships_testing_module is None:
        lib_testing = False if non_interactive else typer.confirm("Include testing module?", default=False)
    else:
        lib_testing = ships_testing_module

    if ships_exceptions_module is None:
        lib_exceptions = False if non_interactive else typer.confirm("Include exceptions module?", default=False)
    else:
        lib_exceptions = ships_exceptions_module

    if ships_console_script is None and not non_interactive:
        raw_script = typer.prompt("Console script name (blank for none)", default="", show_default=False)
        lib_script = raw_script or None
    else:
        lib_script = ships_console_script or None

    return LibSpec(
        name=lib_name,
        module_name=lib_module_name,
        description=lib_description,
        owner=lib_owner,
        namespace_package=lib_namespace,
        ships_testing_module=lib_testing,
        ships_exceptions_module=lib_exceptions,
        ships_console_script=lib_script,
    )


__all__ = ["prompt_lib_spec", "prompt_service_spec"]
