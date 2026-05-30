"""Archetype spec factories for invariant tests.

Seven canonical archetypes that exercise the full feature matrix:

Services (4):
  * kafka_only_consumer  -- kafka-only with db + alembic + outbox, commands handler
  * kafka_only_producer  -- kafka-only producer (e.g. scheduler)
  * http_only_producer   -- HTTP-only auth-style service, publishers only
  * http_and_kafka_ml    -- HTTP+Kafka ml-heavy: llm, qdrant, manifest, holder

Libraries (3):
  * plain_lib            -- minimal library with no extras
  * namespace_lib        -- nohiki-domain-models-style namespace package
  * lib_with_testing     -- library shipping a testing extra
"""

from __future__ import annotations

from nohiki_scaffold.core.features import HandlerKind, KafkaRole, ServiceShape
from nohiki_scaffold.core.models import (
    DatabaseOptions,
    KafkaOptions,
    LibSpec,
    LLMOptions,
    MLOptions,
    QdrantOptions,
    RedisOptions,
    S3Options,
    ServiceSpec,
)


def kafka_only_consumer() -> ServiceSpec:
    """Canonical kafka consumer with db + alembic + outbox + commands handler."""
    return ServiceSpec(
        name="demo-consumer-service",
        friendly_name="Demo Consumer Service",
        description="Canonical kafka-only consumer archetype.",
        owner="platform",
        shape=ServiceShape.KAFKA_ONLY,
        env_prefix="DEMO_CONSUMER_",
        module_name="demo_consumer_service",
        database=DatabaseOptions(
            enabled=True,
            schema_name="demo_consumer_schema",
            outbox=True,
            alembic=True,
        ),
        redis=RedisOptions(),
        kafka=KafkaOptions(
            role=KafkaRole.CONSUMER_ONLY,
            handlers=frozenset({HandlerKind.COMMANDS}),
        ),
        s3=S3Options(),
        ml=MLOptions(),
    )


def kafka_only_producer() -> ServiceSpec:
    """Producer-only kafka service (e.g. a scheduler)."""
    return ServiceSpec(
        name="demo-scheduler-service",
        friendly_name="Demo Scheduler",
        description="Kafka producer-only archetype.",
        owner="platform",
        shape=ServiceShape.KAFKA_ONLY,
        env_prefix="DEMO_SCHEDULER_",
        module_name="demo_scheduler_service",
        database=DatabaseOptions(enabled=True, schema_name="demo_scheduler_schema", outbox=True),
        redis=RedisOptions(),
        kafka=KafkaOptions(role=KafkaRole.PRODUCER_ONLY),
        s3=S3Options(),
        ml=MLOptions(),
    )


def http_only_producer() -> ServiceSpec:
    """HTTP-only service with kafka producer for outbox-style publishing (auth-service shape)."""
    return ServiceSpec(
        name="demo-auth-service",
        friendly_name="Demo Auth",
        description="HTTP-only producer archetype.",
        owner="platform",
        shape=ServiceShape.HTTP_ONLY,
        env_prefix="DEMO_AUTH_",
        module_name="demo_auth_service",
        database=DatabaseOptions(enabled=True, schema_name="demo_auth_schema", outbox=True, alembic=True),
        redis=RedisOptions(enabled=True),
        kafka=KafkaOptions(role=KafkaRole.PRODUCER_ONLY),
        s3=S3Options(),
        ml=MLOptions(),
    )


def http_and_kafka_ml() -> ServiceSpec:
    """HTTP+Kafka ml-heavy: llm, qdrant, manifest, service_holder_pattern."""
    return ServiceSpec(
        name="demo-scorer-service",
        friendly_name="Demo Scorer",
        description="HTTP+Kafka ml-heavy archetype.",
        owner="ml-platform",
        shape=ServiceShape.HTTP_AND_KAFKA,
        env_prefix="DEMO_SCORER_",
        module_name="demo_scorer_service",
        database=DatabaseOptions(enabled=True, schema_name="demo_scorer_schema", outbox=True, alembic=True),
        redis=RedisOptions(enabled=True),
        kafka=KafkaOptions(
            role=KafkaRole.BOTH,
            handlers=frozenset({HandlerKind.COMMANDS, HandlerKind.CALLBACKS}),
            embedding_callback=True,
            max_concurrent_handlers=2,
        ),
        s3=S3Options(enabled=True, bucket_name="demo-scorer-artifacts"),
        ml=MLOptions(
            llm=LLMOptions(enabled=True, provider="openai", model="gpt-4o", api_key_env="OPENAI_API_KEY"),
            qdrant=QdrantOptions(enabled=True, collection_entity="jobs"),
            manifest=True,
            service_holder_pattern=True,
            fail_fast_validation=True,
        ),
    )


def plain_lib() -> LibSpec:
    """Minimal library with no extras."""
    return LibSpec(
        name="nohiki-demo-utils",
        description="Minimal library archetype.",
        owner="platform",
        module_name="nohiki_demo_utils",
    )


def namespace_lib() -> LibSpec:
    """Namespace package (nohiki-domain-models shape)."""
    return LibSpec(
        name="nohiki-demo-models",
        description="Namespace library archetype.",
        owner="platform",
        module_name="nohiki",
        namespace_package=True,
    )


def lib_with_testing() -> LibSpec:
    """Library shipping a testing fixture module."""
    return LibSpec(
        name="nohiki-demo-test-utils",
        description="Lib with testing extra archetype.",
        owner="platform",
        module_name="nohiki_demo_test_utils",
        ships_testing_module=True,
    )
