"""Load ServiceSpec / LibSpec from TOML config files."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import cast

from nohiki_scaffold.core.exceptions import ValidationError
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
from nohiki_scaffold.core.naming import env_prefix, module_name, schema_name


def load_service_spec(path: Path) -> ServiceSpec:
    """Load a ServiceSpec from a TOML file.

    Expected TOML schema (all top-level keys required unless default-able):
        name = "my-service"
        friendly_name = "My Service"
        description = "..."
        owner = "platform"
        shape = "kafka-only"          # ServiceShape value
        env_prefix = "MY_"             # auto-derived if omitted
        module_name = "my_service"     # auto-derived if omitted

        [database]
        enabled = true
        schema_name = "my_schema"
        outbox = true
        alembic = true
        saga = false
        freshness_tracking = false
        state_machine = false

        [redis]
        enabled = false
        bootstrap_distributed_lock = false
        circuit_breaker_for_ext_http = false

        [kafka]
        role = "consumer-only"
        handlers = ["commands", "callbacks"]
        embedding_callback = false
        max_concurrent_handlers = 10

        [s3]
        enabled = true
        bucket_name = "my-bucket"
        key_prefix = "docs/"

        [ml]
        manifest = true
        service_holder_pattern = true
        fail_fast_validation = true

        [ml.llm]
        enabled = true
        provider = "openai"
        model = "gpt-4o"
        api_key_env = "OPENAI_API_KEY"

        [ml.qdrant]
        enabled = true
        collection_entity = "jobs"

    Args:
        path: Path to TOML file.

    Returns:
        Constructed ServiceSpec with all validations applied.

    Raises:
        ValidationError: On schema violations (missing required field, unknown key, bad enum value).
        FileNotFoundError: If the TOML file does not exist.
        tomllib.TOMLDecodeError: If the TOML file is malformed.
    """
    content = path.read_text(encoding="utf-8")
    data = tomllib.loads(content)

    svc_name = _get_str(data, "name", required=True)
    svc_friendly = _get_str(data, "friendly_name", required=True)
    svc_description = _get_str(data, "description", required=True)
    svc_owner = _get_str(data, "owner", required=True)

    shape_str = _get_str(data, "shape", required=True)
    try:
        svc_shape = ServiceShape(shape_str)
    except ValueError as exc:
        msg = f"Invalid shape {shape_str!r}: must be one of {[s.value for s in ServiceShape]}"
        raise ValidationError(msg) from exc

    svc_env_prefix = _get_str(data, "env_prefix") or env_prefix(svc_name)
    svc_module_name = _get_str(data, "module_name") or module_name(svc_name)

    database = _load_database_options(data.get("database", {}))
    redis = _load_redis_options(data.get("redis", {}))
    kafka = _load_kafka_options(data.get("kafka", {}))
    s3 = _load_s3_options(data.get("s3", {}))
    ml = _load_ml_options(data.get("ml", {}))

    return ServiceSpec(
        name=svc_name,
        friendly_name=svc_friendly,
        description=svc_description,
        owner=svc_owner,
        shape=svc_shape,
        env_prefix=svc_env_prefix,
        module_name=svc_module_name,
        database=database,
        redis=redis,
        kafka=kafka,
        s3=s3,
        ml=ml,
    )


def load_lib_spec(path: Path) -> LibSpec:
    """Load a LibSpec from a TOML file.

    Expected TOML schema:
        name = "nohiki-my-lib"
        description = "..."
        owner = "platform"
        module_name = "nohiki_my_lib"     # auto-derived if omitted
        namespace_package = false
        ships_testing_module = false
        ships_exceptions_module = false
        ships_console_script = null

    Args:
        path: Path to TOML file.

    Returns:
        Constructed LibSpec with all validations applied.

    Raises:
        ValidationError: On schema violations.
        FileNotFoundError: If the TOML file does not exist.
        tomllib.TOMLDecodeError: If the TOML file is malformed.
    """
    content = path.read_text(encoding="utf-8")
    data = tomllib.loads(content)

    lib_name = _get_str(data, "name", required=True)
    lib_description = _get_str(data, "description", required=True)
    lib_owner = _get_str(data, "owner", required=True)

    lib_module_name = _get_str(data, "module_name") or module_name(lib_name)
    lib_namespace = _get_bool(data, "namespace_package", default=False)
    lib_testing = _get_bool(data, "ships_testing_module", default=False)
    lib_exceptions = _get_bool(data, "ships_exceptions_module", default=False)
    lib_script = _get_str(data, "ships_console_script")

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


def _load_database_options(data: object) -> DatabaseOptions:
    """Parse [database] section."""
    if not isinstance(data, dict):
        data = {}
    data = cast(dict[str, object], data)

    enabled = _get_bool(data, "enabled", default=False)
    schema = _get_str(data, "schema_name") or (schema_name("") if enabled else "")
    outbox = _get_bool(data, "outbox", default=False)
    alembic = _get_bool(data, "alembic", default=False)
    saga = _get_bool(data, "saga", default=False)
    freshness = _get_bool(data, "freshness_tracking", default=False)
    state_machine = _get_bool(data, "state_machine", default=False)

    return DatabaseOptions(
        enabled=enabled,
        schema_name=schema,
        outbox=outbox,
        alembic=alembic,
        saga=saga,
        freshness_tracking=freshness,
        state_machine=state_machine,
    )


def _load_redis_options(data: object) -> RedisOptions:
    """Parse [redis] section."""
    if not isinstance(data, dict):
        data = {}
    data = cast(dict, data)

    enabled = _get_bool(data, "enabled", default=False)
    lock = _get_bool(data, "bootstrap_distributed_lock", default=False)
    circuit_breaker = _get_bool(data, "circuit_breaker_for_ext_http", default=False)

    return RedisOptions(
        enabled=enabled,
        bootstrap_distributed_lock=lock,
        circuit_breaker_for_ext_http=circuit_breaker,
    )


def _load_kafka_options(data: object) -> KafkaOptions:
    """Parse [kafka] section."""
    if not isinstance(data, dict):
        data = {}
    data = cast(dict, data)

    role_str = _get_str(data, "role", default=KafkaRole.NONE.value)
    try:
        role = KafkaRole(role_str)
    except ValueError as exc:
        msg = f"Invalid kafka.role {role_str!r}: must be one of {[r.value for r in KafkaRole]}"
        raise ValidationError(msg) from exc

    handlers_raw = data.get("handlers", [])
    if not isinstance(handlers_raw, list):
        msg = "kafka.handlers must be a list of strings"
        raise ValidationError(msg)

    handlers = frozenset()
    if handlers_raw:
        try:
            handlers = frozenset(HandlerKind(h) for h in handlers_raw)
        except ValueError as exc:
            msg = f"Invalid kafka.handler: {exc}"
            raise ValidationError(msg) from exc

    embedding = _get_bool(data, "embedding_callback", default=False)

    concurrent_raw = data.get("max_concurrent_handlers")
    concurrent: int | None = None
    if concurrent_raw is not None:
        if not isinstance(concurrent_raw, int):
            msg = "kafka.max_concurrent_handlers must be an integer"
            raise ValidationError(msg)
        concurrent = concurrent_raw

    return KafkaOptions(
        role=role,
        handlers=handlers,
        embedding_callback=embedding,
        max_concurrent_handlers=concurrent,
    )


def _load_s3_options(data: object) -> S3Options:
    """Parse [s3] section."""
    if not isinstance(data, dict):
        data = {}
    data = cast(dict, data)

    enabled = _get_bool(data, "enabled", default=False)
    bucket = _get_str(data, "bucket_name")
    prefix = _get_str(data, "key_prefix")

    return S3Options(
        enabled=enabled,
        bucket_name=bucket,
        key_prefix=prefix,
    )


def _load_ml_options(data: object) -> MLOptions:
    """Parse [ml] section."""
    if not isinstance(data, dict):
        data = {}
    data = cast(dict, data)

    llm = _load_llm_options(data.get("llm", {}))
    qdrant = _load_qdrant_options(data.get("qdrant", {}))

    manifest = _get_bool(data, "manifest", default=False)
    holder = _get_bool(data, "service_holder_pattern", default=False)
    fail_fast = _get_bool(data, "fail_fast_validation", default=False)

    return MLOptions(
        llm=llm,
        qdrant=qdrant,
        manifest=manifest,
        service_holder_pattern=holder,
        fail_fast_validation=fail_fast,
    )


def _load_llm_options(data: object) -> LLMOptions:
    """Parse [ml.llm] section."""
    if not isinstance(data, dict):
        data = {}
    data = cast(dict, data)

    enabled = _get_bool(data, "enabled", default=False)
    provider = _get_str(data, "provider")
    model = _get_str(data, "model")
    api_key = _get_str(data, "api_key_env")

    return LLMOptions(
        enabled=enabled,
        provider=provider,
        model=model,
        api_key_env=api_key,
    )


def _load_qdrant_options(data: object) -> QdrantOptions:
    """Parse [ml.qdrant] section."""
    if not isinstance(data, dict):
        data = {}
    data = cast(dict, data)

    enabled = _get_bool(data, "enabled", default=False)
    entity = _get_str(data, "collection_entity")

    if entity is not None and enabled and entity not in {"jobs", "profiles", "skills", "occupations"}:
        msg = f"Invalid qdrant.collection_entity {entity!r}"
        raise ValidationError(msg)

    return QdrantOptions(
        enabled=enabled,
        collection_entity=cast("QdrantEntity | None", entity),
    )


def _get_str(data: dict, key: str, *, required: bool = False, default: str = "") -> str:
    """Extract string from dict, raising ValidationError if required and missing."""
    value = data.get(key, default)
    if required and not value:
        msg = f"Required field {key!r} is missing or empty"
        raise ValidationError(msg)
    if not isinstance(value, str):
        msg = f"Field {key!r} must be a string, got {type(value).__name__}"
        raise ValidationError(msg)
    return value


def _get_bool(data: dict, key: str, *, default: bool = False) -> bool:
    """Extract boolean from dict."""
    value = data.get(key, default)
    if not isinstance(value, bool):
        msg = f"Field {key!r} must be a boolean, got {type(value).__name__}"
        raise ValidationError(msg)
    return value


__all__ = ["load_lib_spec", "load_service_spec"]
