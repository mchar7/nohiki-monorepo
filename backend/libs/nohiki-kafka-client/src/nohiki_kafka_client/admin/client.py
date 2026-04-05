"""Async Kafka admin client for topic management."""

from __future__ import annotations

import ssl
from collections.abc import Mapping, Sequence
from enum import IntEnum
from typing import TYPE_CHECKING, Protocol, Self, cast

from aiokafka.admin import AIOKafkaAdminClient, NewTopic
from aiokafka.errors import KafkaError
from nohiki_observability import get_logger

from nohiki_kafka_client.config import (
    KafkaClientConfig,
    SecurityProtocol,
    create_ssl_context,
)

from .exceptions import AdminError, TopicAlreadyExistsError
from .models import EnsureTopicsResult, TopicDescription, TopicSpec

if TYPE_CHECKING:
    import types

logger = get_logger(__name__)

_INTERNAL_TOPIC_PREFIX = "__"
_ERR_CLIENT_NOT_STARTED = "Admin client not started - call start() or use as async context manager"


class _KafkaErrorCode(IntEnum):
    """Kafka protocol error codes used in admin responses.

    These are stable Apache Kafka protocol constants.
    """

    NO_ERROR = 0
    TOPIC_ALREADY_EXISTS = 36


# aiokafka's admin methods return ``Response`` (base class) with attributes
# set dynamically from the Kafka protocol schema.  These Protocols document
# the expected shapes so attribute access is fully typed.


type _TopicErrorItem = tuple[str, int, str]
"""Single topic result in a CreateTopicsResponse.

aiokafka returns tuples (topic, error_code, error_message) not objects.
"""


class _CreateTopicsResponse(Protocol):
    """Structural type for aiokafka CreateTopicsResponse."""

    @property
    def topic_errors(self) -> Sequence[_TopicErrorItem]: ...


type _DeleteTopicErrorItem = tuple[str, int]
"""Single topic result in a DeleteTopicsResponse.

aiokafka returns tuples (topic, error_code) not objects.
"""


class _DeleteTopicsResponse(Protocol):
    """Structural type for aiokafka DeleteTopicsResponse."""

    @property
    def topic_error_codes(self) -> Sequence[_DeleteTopicErrorItem]: ...


def _spec_to_new_topic(spec: TopicSpec) -> NewTopic:
    """Convert a library TopicSpec to an aiokafka NewTopic.

    Args:
        spec: Library-defined topic specification.

    Returns:
        aiokafka NewTopic for the admin client API.

    """
    return NewTopic(
        name=spec.name,
        num_partitions=spec.num_partitions,
        replication_factor=spec.replication_factor,
        topic_configs=spec.topic_configs,
    )


def _partition_by_existence(
    topics: Sequence[TopicSpec],
    existing_names: frozenset[str],
) -> tuple[list[TopicSpec], list[str]]:
    """Split topic specs into those needing creation and those that exist.

    Uses frozenset for O(1) membership testing.

    Args:
        topics: All requested topic specs.
        existing_names: Set of currently existing topic names.

    Returns:
        Tuple of (to_create specs, already existing names).

    """
    to_create: list[TopicSpec] = []
    already_existing: list[str] = []
    for spec in topics:
        if spec.name in existing_names:
            already_existing.append(spec.name)
        else:
            to_create.append(spec)
    return to_create, already_existing


def _parse_topic_metadata(
    metadata: Sequence[Mapping[str, object]],
) -> tuple[TopicDescription, ...]:
    """Parse describe_topics() response into TopicDescription objects.

    aiokafka's ``describe_topics()`` returns ``list[Any]`` where each item
    is a dict produced by ``MetadataResponse.to_object()``.

    Args:
        metadata: Raw topic metadata dicts from aiokafka.

    Returns:
        Parsed topic descriptions.

    """
    descriptions: list[TopicDescription] = []
    for topic_meta in metadata:
        name = str(topic_meta.get("topic", ""))
        partitions = topic_meta.get("partitions", [])
        num_partitions = len(partitions) if isinstance(partitions, list) else 0
        descriptions.append(
            TopicDescription(name=name, num_partitions=num_partitions),
        )
    return tuple(descriptions)


def _build_admin_client(config: KafkaClientConfig) -> AIOKafkaAdminClient:
    """Construct ``AIOKafkaAdminClient`` with explicitly typed arguments.

    aiokafka's admin client has typed ``__init__`` parameters, so we pass
    values directly from :class:`KafkaClientConfig` rather than unpacking
    a generic ``dict[str, object]``.

    Args:
        config: Kafka client configuration.

    Returns:
        An un-started ``AIOKafkaAdminClient`` instance.

    """
    security = config.security
    client_id = config.client_id or f"{config.observability.service_name}-admin"

    ssl_context: ssl.SSLContext | None = None
    if security.protocol in (SecurityProtocol.SSL, SecurityProtocol.SASL_SSL):
        ssl_context = create_ssl_context(security)

    sasl_mechanism = security.sasl_mechanism.value if security.sasl_mechanism else "PLAIN"

    return AIOKafkaAdminClient(
        bootstrap_servers=config.bootstrap_servers,
        client_id=client_id,
        security_protocol=security.protocol.value,
        ssl_context=ssl_context,
        sasl_mechanism=sasl_mechanism,
        sasl_oauth_token_provider=security.sasl_oauth_token_provider,
        sasl_plain_username=security.sasl_username,
        sasl_plain_password=security.sasl_password,
    )


class KafkaAdmin:
    """Async Kafka admin client for topic management.

    Wraps aiokafka's ``AIOKafkaAdminClient`` with consistent configuration
    from ``KafkaClientConfig``, lifecycle management, structured logging,
    and error translation to library exception types.

    Usage::

        async with KafkaAdmin(config) as admin:
            await admin.create_topic("my-topic", num_partitions=6)

    """

    __slots__ = ("_client", "_config")

    def __init__(self, config: KafkaClientConfig) -> None:
        """Initialize admin client with configuration.

        Args:
            config: Kafka client configuration.

        """
        self._config = config
        self._client: AIOKafkaAdminClient | None = None

    async def __aenter__(self) -> Self:
        """Start admin client as async context manager."""
        await self.start()
        return self

    async def __aexit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_val: BaseException | None,
        _exc_tb: types.TracebackType | None,
    ) -> None:
        """Close admin client resources."""
        await self.close()

    async def start(self) -> None:
        """Start the underlying admin client.

        Raises:
            AdminError: If the client fails to connect.

        """
        try:
            self._client = _build_admin_client(self._config)
            await self._client.start()
        except KafkaError as exc:
            self._client = None
            msg = "Failed to start Kafka admin client"
            raise AdminError(msg, details={"error": str(exc)}) from exc

        logger.info(
            "Kafka admin client started",
            bootstrap_servers=self._config.bootstrap_servers,
        )

    async def close(self) -> None:
        """Close the admin client and release resources.

        Safe to call multiple times.  Logs warnings but does not raise.

        """
        if self._client is None:
            return
        try:
            await self._client.close()
            logger.info("Kafka admin client closed")
        except KafkaError as exc:
            logger.warning("Error closing admin client", error=str(exc))
        finally:
            self._client = None

    def _require_client(self) -> AIOKafkaAdminClient:
        """Return the active admin client or raise.

        Returns:
            The active ``AIOKafkaAdminClient`` instance.

        Raises:
            AdminError: If the client has not been started.

        """
        if self._client is None:
            raise AdminError(_ERR_CLIENT_NOT_STARTED)
        return self._client

    async def create_topic(
        self,
        name: str,
        *,
        num_partitions: int = 3,
        replication_factor: int = 1,
        topic_configs: dict[str, str] | None = None,
    ) -> None:
        """Create a single Kafka topic.

        Convenience wrapper around :meth:`create_topics`.

        Args:
            name: Topic name.
            num_partitions: Number of partitions.
            replication_factor: Replication factor.
            topic_configs: Optional topic-level configuration overrides.

        Raises:
            TopicAlreadyExistsError: If the topic already exists.
            AdminError: If creation fails.

        """
        spec = TopicSpec(
            name=name,
            num_partitions=num_partitions,
            replication_factor=replication_factor,
            topic_configs=topic_configs,
        )
        await self.create_topics([spec])

    async def create_topics(self, topics: Sequence[TopicSpec]) -> tuple[str, ...]:
        """Create multiple Kafka topics.

        Args:
            topics: Specifications for topics to create.

        Returns:
            Names of successfully created topics.

        Raises:
            TopicAlreadyExistsError: If any topic already exists.
            AdminError: If creation fails.

        """
        client = self._require_client()
        if not topics:
            return ()

        new_topics = [_spec_to_new_topic(spec) for spec in topics]
        try:
            raw_response = await client.create_topics(new_topics)
        except KafkaError as exc:
            msg = "Failed to create topics"
            raise AdminError(msg, details={"error": str(exc)}) from exc

        response = cast(_CreateTopicsResponse, raw_response)
        created: list[str] = []
        for item in response.topic_errors:
            _handle_create_topic_result(item, created)
        return tuple(created)

    async def delete_topics(self, topic_names: Sequence[str]) -> tuple[str, ...]:
        """Delete Kafka topics.

        Args:
            topic_names: Names of topics to delete.

        Returns:
            Names of successfully deleted topics.

        Raises:
            AdminError: If any topic deletion fails.

        """
        client = self._require_client()
        if not topic_names:
            return ()

        try:
            raw_response = await client.delete_topics(list(topic_names))
        except KafkaError as exc:
            msg = "Failed to delete topics"
            raise AdminError(msg, details={"error": str(exc)}) from exc

        response = cast(_DeleteTopicsResponse, raw_response)
        deleted: list[str] = []
        for item in response.topic_error_codes:
            _handle_delete_topic_result(item, deleted)
        return tuple(deleted)

    async def list_topics(self, *, include_internal: bool = False) -> tuple[str, ...]:
        """List Kafka topics.

        Args:
            include_internal: If True, include Kafka internal topics
                (prefixed with ``__``).  Defaults to False.

        Returns:
            Topic names as a tuple.

        Raises:
            AdminError: If the operation fails.

        """
        client = self._require_client()
        try:
            all_topics = await client.list_topics()
        except KafkaError as exc:
            msg = "Failed to list topics"
            raise AdminError(msg, details={"error": str(exc)}) from exc

        if include_internal:
            return tuple(all_topics)
        return tuple(t for t in all_topics if not t.startswith(_INTERNAL_TOPIC_PREFIX))

    async def topic_exists(self, topic_name: str) -> bool:
        """Check if a specific topic exists.

        Checks all topics including internal ones for a definitive answer.

        Args:
            topic_name: Name of the topic to check.

        Returns:
            True if the topic exists, False otherwise.

        Raises:
            AdminError: If the operation fails due to connection issues.

        """
        all_topics = await self.list_topics(include_internal=True)
        return topic_name in all_topics

    async def describe_topics(
        self,
        topic_names: Sequence[str],
    ) -> tuple[TopicDescription, ...]:
        """Describe existing Kafka topics.

        Args:
            topic_names: Names of topics to describe.

        Returns:
            Topic descriptions with partition metadata.

        Raises:
            AdminError: If the operation fails.

        """
        client = self._require_client()
        if not topic_names:
            return ()

        try:
            metadata = await client.describe_topics(list(topic_names))
        except KafkaError as exc:
            msg = "Failed to describe topics"
            raise AdminError(msg, details={"error": str(exc)}) from exc

        return _parse_topic_metadata(metadata)

    async def ensure_topics_exist(
        self,
        topics: Sequence[TopicSpec],
    ) -> EnsureTopicsResult:
        """Ensure all specified topics exist, creating any that are missing.

        Idempotent: safe to call repeatedly.  Topics that already exist are
        skipped.  If an existing topic has a different partition count than
        the spec, a warning is emitted but no error is raised.

        Args:
            topics: Specifications for required topics.

        Returns:
            Result indicating created topics, existing topics, and warnings.

        Raises:
            AdminError: If creation or inspection fails.

        """
        if not topics:
            return EnsureTopicsResult()

        existing_names = frozenset(await self.list_topics(include_internal=True))
        specs_by_name: dict[str, TopicSpec] = {spec.name: spec for spec in topics}
        to_create, already_existing = _partition_by_existence(topics, existing_names)

        created, race_existing = await self._create_missing_topics(to_create)
        all_existing = already_existing + race_existing
        warnings = await self._check_partition_mismatches(
            all_existing,
            specs_by_name,
        )

        return EnsureTopicsResult(
            created=tuple(created),
            existing=tuple(all_existing),
            warnings=tuple(warnings),
        )

    async def _create_missing_topics(
        self,
        to_create: list[TopicSpec],
    ) -> tuple[list[str], list[str]]:
        """Create topics that don't exist yet.

        Handles race conditions where a topic appears between the
        existence check and the create call.

        Args:
            to_create: Topic specs to create.

        Returns:
            Tuple of (newly created names, race-condition existing names).

        """
        if not to_create:
            return [], []

        client = self._require_client()
        new_topics = [_spec_to_new_topic(s) for s in to_create]

        try:
            raw_response = await client.create_topics(new_topics)
        except KafkaError as exc:
            msg = "Failed to create topics during ensure"
            raise AdminError(msg, details={"error": str(exc)}) from exc

        response = cast(_CreateTopicsResponse, raw_response)
        created: list[str] = []
        race_existing: list[str] = []
        for item in response.topic_errors:
            topic, error_code, error_message = item
            match error_code:
                case _KafkaErrorCode.NO_ERROR:
                    created.append(topic)
                    logger.info("Created topic", topic=topic)
                case _KafkaErrorCode.TOPIC_ALREADY_EXISTS:
                    race_existing.append(topic)
                    logger.debug(
                        "Topic already exists (race condition)",
                        topic=topic,
                    )
                case _:
                    msg = f"Failed to create topic {topic!r}: {error_message}"
                    raise AdminError(
                        msg,
                        details={
                            "topic": topic,
                            "error_code": error_code,
                        },
                    )
        return created, race_existing

    async def _check_partition_mismatches(
        self,
        existing_names: list[str],
        specs_by_name: dict[str, TopicSpec],
    ) -> list[str]:
        """Check for partition count mismatches on existing topics.

        Args:
            existing_names: Names of topics that already exist.
            specs_by_name: Expected specs keyed by topic name.

        Returns:
            Human-readable warning messages for any mismatches.

        """
        if not existing_names:
            return []

        descriptions = await self.describe_topics(existing_names)
        desc_by_name: dict[str, TopicDescription] = {d.name: d for d in descriptions}

        return [
            warning
            for name in existing_names
            if (warning := _detect_partition_mismatch(name, desc_by_name, specs_by_name))
        ]


def _handle_create_topic_result(
    item: _TopicErrorItem,
    created: list[str],
) -> None:
    """Process a single topic result from a CreateTopicsResponse.

    Args:
        item: Tuple of (topic, error_code, error_message).
        created: Mutable list to append successfully created topic names.

    Raises:
        TopicAlreadyExistsError: If the topic already exists.
        AdminError: On any other Kafka error code.

    """
    topic, error_code, error_message = item
    match error_code:
        case _KafkaErrorCode.NO_ERROR:
            created.append(topic)
            logger.info("Created topic", topic=topic)
        case _KafkaErrorCode.TOPIC_ALREADY_EXISTS:
            msg = f"Topic already exists: {topic!r}"
            raise TopicAlreadyExistsError(
                msg,
                details={"topic": topic},
            )
        case _:
            msg = f"Failed to create topic {topic!r}: {error_message}"
            raise AdminError(
                msg,
                details={"topic": topic, "error_code": error_code},
            )


def _handle_delete_topic_result(
    item: _DeleteTopicErrorItem,
    deleted: list[str],
) -> None:
    """Process a single topic result from a DeleteTopicsResponse.

    Args:
        item: Tuple of (topic, error_code).
        deleted: Mutable list to append successfully deleted topic names.

    Raises:
        AdminError: On any Kafka error code.

    """
    topic, error_code = item
    match error_code:
        case _KafkaErrorCode.NO_ERROR:
            deleted.append(topic)
            logger.info("Deleted topic", topic=topic)
        case _:
            msg = f"Failed to delete topic {topic!r}"
            raise AdminError(
                msg,
                details={"topic": topic, "error_code": error_code},
            )


def _detect_partition_mismatch(
    topic_name: str,
    desc_by_name: dict[str, TopicDescription],
    specs_by_name: dict[str, TopicSpec],
) -> str | None:
    """Detect and log a partition count mismatch for a single topic.

    Args:
        topic_name: Topic name to check.
        desc_by_name: Actual descriptions keyed by name.
        specs_by_name: Expected specs keyed by name.

    Returns:
        Warning message string if mismatched, None otherwise.

    """
    desc = desc_by_name.get(topic_name)
    spec = specs_by_name.get(topic_name)
    if not desc or not spec or desc.num_partitions == spec.num_partitions:
        return None

    warning = f"Topic {topic_name!r} has {desc.num_partitions} partitions but spec requests {spec.num_partitions}"
    logger.warning(
        "Topic partition mismatch",
        topic=topic_name,
        actual_partitions=desc.num_partitions,
        expected_partitions=spec.num_partitions,
    )
    return warning
