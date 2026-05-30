"""Tests for spec construction and ``__post_init__`` validation."""

from __future__ import annotations

import pytest
from nohiki_scaffold.core.exceptions import ValidationError
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


def _minimal_kafka_only_spec(
    *,
    name: str = "demo-service",
    owner: str = "platform",
    env_prefix: str = "DEMO_",
    description: str = "demo",
    shape: ServiceShape = ServiceShape.KAFKA_ONLY,
    kafka: KafkaOptions | None = None,
) -> ServiceSpec:
    """Return a valid kafka-only consumer service spec (test factory)."""
    return ServiceSpec(
        name=name,
        friendly_name="Demo",
        description=description,
        owner=owner,
        shape=shape,
        env_prefix=env_prefix,
        module_name="demo_service",
        database=DatabaseOptions(),
        redis=RedisOptions(),
        kafka=kafka if kafka is not None else KafkaOptions(role=KafkaRole.CONSUMER_ONLY),
        s3=S3Options(),
        ml=MLOptions(),
    )


class TestServiceSpecRegex:
    @pytest.mark.parametrize("bad_name", ["", "A-bad", "1-leading-digit", "no_underscores", "x" * 50])
    def test_rejects_bad_name(self, bad_name: str) -> None:
        with pytest.raises(ValidationError, match="Invalid service name"):
            _minimal_kafka_only_spec(name=bad_name)

    def test_rejects_bad_owner(self) -> None:
        with pytest.raises(ValidationError, match="Invalid owner"):
            _minimal_kafka_only_spec(owner="bad owner!")

    def test_rejects_bad_env_prefix(self) -> None:
        with pytest.raises(ValidationError, match="Invalid env_prefix"):
            _minimal_kafka_only_spec(env_prefix="demo_")

    def test_rejects_too_long_description(self) -> None:
        with pytest.raises(ValidationError, match="description exceeds"):
            _minimal_kafka_only_spec(description="x" * 500)


class TestServiceSpecConsistency:
    def test_http_only_cannot_be_consumer(self) -> None:
        with pytest.raises(ValidationError, match="HTTP_ONLY shape cannot"):
            _minimal_kafka_only_spec(
                shape=ServiceShape.HTTP_ONLY,
                kafka=KafkaOptions(role=KafkaRole.CONSUMER_ONLY),
            )

    def test_kafka_only_requires_kafka_role(self) -> None:
        with pytest.raises(ValidationError, match="KAFKA_ONLY shape requires"):
            _minimal_kafka_only_spec(kafka=KafkaOptions(role=KafkaRole.NONE))


class TestDatabaseOptions:
    def test_enabled_requires_schema_name(self) -> None:
        with pytest.raises(ValidationError, match="schema_name is required"):
            DatabaseOptions(enabled=True)

    def test_invalid_schema_name_rejected(self) -> None:
        with pytest.raises(ValidationError, match="Invalid schema_name"):
            DatabaseOptions(enabled=True, schema_name="Has-Hyphen")

    def test_sub_feature_without_enabled_rejected(self) -> None:
        with pytest.raises(ValidationError, match=r"require database\.enabled"):
            DatabaseOptions(enabled=False, outbox=True)


class TestRedisOptions:
    def test_sub_feature_without_enabled_rejected(self) -> None:
        with pytest.raises(ValidationError, match=r"require redis\.enabled"):
            RedisOptions(enabled=False, bootstrap_distributed_lock=True)


class TestKafkaOptions:
    def test_handlers_require_consumer(self) -> None:
        with pytest.raises(ValidationError, match="requires a consumer"):
            KafkaOptions(role=KafkaRole.PRODUCER_ONLY, handlers=frozenset({HandlerKind.COMMANDS}))

    def test_embedding_callback_requires_consumer(self) -> None:
        with pytest.raises(ValidationError, match="embedding_callback requires"):
            KafkaOptions(role=KafkaRole.PRODUCER_ONLY, embedding_callback=True)

    @pytest.mark.parametrize("bad", [0, -1, 201, 1000])
    def test_max_concurrent_bounds(self, bad: int) -> None:
        with pytest.raises(ValidationError, match="max_concurrent_handlers"):
            KafkaOptions(role=KafkaRole.CONSUMER_ONLY, max_concurrent_handlers=bad)


class TestMLOptions:
    def test_fail_fast_requires_manifest(self) -> None:
        with pytest.raises(ValidationError, match="fail_fast_validation requires"):
            MLOptions(llm=LLMOptions(enabled=True, provider="openai", model="gpt-4o"), fail_fast_validation=True)

    def test_service_holder_requires_any_ml(self) -> None:
        with pytest.raises(ValidationError, match="service_holder_pattern requires"):
            MLOptions(service_holder_pattern=True)


class TestS3Options:
    def test_enabled_requires_bucket(self) -> None:
        with pytest.raises(ValidationError, match="bucket_name"):
            S3Options(enabled=True)

    @pytest.mark.parametrize("bad", ["Bad-Bucket", "x", "a" * 64, "-bad", "bad-"])
    def test_rejects_bad_bucket(self, bad: str) -> None:
        with pytest.raises(ValidationError, match=r"Invalid s3\.bucket_name"):
            S3Options(enabled=True, bucket_name=bad)

    def test_rejects_bad_key_prefix(self) -> None:
        with pytest.raises(ValidationError, match=r"Invalid s3\.key_prefix"):
            S3Options(enabled=True, bucket_name="ok-bucket", key_prefix="BAD CHARS $$")

    def test_disabled_forbids_sub_features(self) -> None:
        with pytest.raises(ValidationError, match=r"s3\.enabled=True"):
            S3Options(enabled=False, bucket_name="some-bucket")


class TestQdrantOptions:
    def test_enabled_requires_entity(self) -> None:
        with pytest.raises(ValidationError, match="collection_entity"):
            QdrantOptions(enabled=True)

    def test_rejects_unknown_entity(self) -> None:
        # runtime-only: pass through via cast because Literal forbids at type level
        from typing import cast

        from nohiki_scaffold.core.models import QdrantEntity

        with pytest.raises(ValidationError, match="collection_entity"):
            QdrantOptions(enabled=True, collection_entity=cast("QdrantEntity", "widgets"))

    def test_valid(self) -> None:
        opt = QdrantOptions(enabled=True, collection_entity="jobs")
        assert opt.collection_entity == "jobs"


class TestLLMOptions:
    def test_enabled_requires_provider_and_model(self) -> None:
        with pytest.raises(ValidationError, match="provider"):
            LLMOptions(enabled=True, model="gpt-4o")
        with pytest.raises(ValidationError, match="model"):
            LLMOptions(enabled=True, provider="openai")

    @pytest.mark.parametrize("bad", ["has space", "Upper", "bad/slash"])
    def test_rejects_bad_provider(self, bad: str) -> None:
        with pytest.raises(ValidationError, match="provider"):
            LLMOptions(enabled=True, provider=bad, model="gpt-4o")

    def test_rejects_bad_api_key_env(self) -> None:
        with pytest.raises(ValidationError, match="api_key_env"):
            LLMOptions(enabled=True, provider="openai", model="gpt-4o", api_key_env="lowercase")

    def test_valid(self) -> None:
        opt = LLMOptions(enabled=True, provider="openai", model="gpt-4o", api_key_env="OPENAI_API_KEY")
        assert opt.provider == "openai"


class TestLibSpec:
    def _mk(
        self,
        *,
        name: str = "nohiki-foo-utils",
        module_name: str = "nohiki_foo_utils",
        owner: str = "platform",
    ) -> LibSpec:
        return LibSpec(name=name, module_name=module_name, description="Foo utilities", owner=owner)

    def test_valid_construction(self) -> None:
        spec = self._mk()
        assert spec.name == "nohiki-foo-utils"

    @pytest.mark.parametrize("bad_name", ["foo-utils", "nohiki", "nohiki-", "NOHIKI-foo"])
    def test_rejects_bad_name(self, bad_name: str) -> None:
        with pytest.raises(ValidationError, match="Invalid lib name"):
            self._mk(name=bad_name)

    def test_rejects_invalid_module_name(self) -> None:
        with pytest.raises(ValidationError, match="not a valid Python identifier"):
            self._mk(module_name="has-hyphen")
