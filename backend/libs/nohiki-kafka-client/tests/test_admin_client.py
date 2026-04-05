"""Unit tests for KafkaAdmin client and module-level helpers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nohiki_kafka_client.admin.client import (
    KafkaAdmin,
    _build_admin_client,
    _detect_partition_mismatch,
    _handle_create_topic_result,
    _handle_delete_topic_result,
    _KafkaErrorCode,
    _parse_topic_metadata,
    _partition_by_existence,
    _spec_to_new_topic,
)
from nohiki_kafka_client.admin.exceptions import AdminError, TopicAlreadyExistsError
from nohiki_kafka_client.admin.models import (
    EnsureTopicsResult,
    TopicDescription,
    TopicSpec,
)
from nohiki_kafka_client.config import KafkaClientConfig


def _make_config(bootstrap_servers: str = "localhost:29092") -> KafkaClientConfig:
    """Create a minimal KafkaClientConfig for testing."""
    return KafkaClientConfig(bootstrap_servers=bootstrap_servers)


def _make_admin(client_mock: AsyncMock | None = None) -> KafkaAdmin:
    """Create a KafkaAdmin with an optionally pre-set mock client."""
    admin = KafkaAdmin(_make_config())
    if client_mock is not None:
        admin._client = client_mock
    return admin


def _topic_error(
    topic: str,
    error_code: int = _KafkaErrorCode.NO_ERROR,
    error_message: str = "",
) -> tuple[str, int, str]:
    """Create a mock topic error tuple matching aiokafka's actual return format."""
    return (topic, error_code, error_message)


def _delete_error(
    topic: str,
    error_code: int = _KafkaErrorCode.NO_ERROR,
) -> tuple[str, int]:
    """Create a mock delete topic error tuple matching aiokafka's actual return format."""
    return (topic, error_code)


class TestSpecToNewTopic:
    """Tests for _spec_to_new_topic converter."""

    def test_converts_all_fields(self) -> None:
        """Converts TopicSpec fields to NewTopic."""
        spec = TopicSpec(
            name="my-topic",
            num_partitions=6,
            replication_factor=3,
            topic_configs={"retention.ms": "86400000"},
        )
        new_topic = _spec_to_new_topic(spec)
        assert new_topic.name == "my-topic"
        assert new_topic.num_partitions == 6
        assert new_topic.replication_factor == 3
        assert new_topic.topic_configs == {"retention.ms": "86400000"}

    def test_converts_defaults(self) -> None:
        """Converts TopicSpec with default values."""
        spec = TopicSpec(name="simple")
        new_topic = _spec_to_new_topic(spec)
        assert new_topic.name == "simple"
        assert new_topic.num_partitions == 3
        assert new_topic.replication_factor == 1
        assert not new_topic.topic_configs


class TestPartitionByExistence:
    """Tests for _partition_by_existence helper."""

    def test_all_new(self) -> None:
        """All specs are new when no existing topics."""
        specs = [TopicSpec(name="a"), TopicSpec(name="b")]
        to_create, existing = _partition_by_existence(specs, frozenset())
        assert len(to_create) == 2
        assert existing == []

    def test_all_existing(self) -> None:
        """All specs already exist."""
        specs = [TopicSpec(name="a"), TopicSpec(name="b")]
        to_create, existing = _partition_by_existence(specs, frozenset({"a", "b"}))
        assert to_create == []
        assert existing == ["a", "b"]

    def test_mixed(self) -> None:
        """Some specs exist, others are new."""
        specs = [TopicSpec(name="a"), TopicSpec(name="b"), TopicSpec(name="c")]
        to_create, existing = _partition_by_existence(specs, frozenset({"b"}))
        assert [s.name for s in to_create] == ["a", "c"]
        assert existing == ["b"]

    def test_empty_input(self) -> None:
        """Empty specs list returns empty results."""
        to_create, existing = _partition_by_existence([], frozenset({"a"}))
        assert to_create == []
        assert existing == []


class TestParseTopicMetadata:
    """Tests for _parse_topic_metadata helper."""

    def test_parses_single_topic(self) -> None:
        """Parses single topic metadata dict."""
        metadata = [{"topic": "my-topic", "partitions": [1, 2, 3]}]
        result = _parse_topic_metadata(metadata)
        assert len(result) == 1
        assert result[0].name == "my-topic"
        assert result[0].num_partitions == 3

    def test_parses_multiple_topics(self) -> None:
        """Parses multiple topic metadata dicts."""
        metadata = [
            {"topic": "a", "partitions": [1]},
            {"topic": "b", "partitions": [1, 2]},
        ]
        result = _parse_topic_metadata(metadata)
        assert len(result) == 2
        assert result[0].num_partitions == 1
        assert result[1].num_partitions == 2

    def test_handles_missing_topic_key(self) -> None:
        """Missing topic key defaults to empty string."""
        result = _parse_topic_metadata([{"partitions": [1]}])
        assert result[0].name == ""

    def test_handles_missing_partitions_key(self) -> None:
        """Missing partitions key defaults to 0."""
        result = _parse_topic_metadata([{"topic": "a"}])
        assert result[0].num_partitions == 0

    def test_handles_non_list_partitions(self) -> None:
        """Non-list partitions value defaults to 0."""
        result = _parse_topic_metadata([{"topic": "a", "partitions": "invalid"}])
        assert result[0].num_partitions == 0

    def test_empty_input(self) -> None:
        """Empty metadata list returns empty tuple."""
        assert _parse_topic_metadata([]) == ()


class TestHandleCreateTopicResult:
    """Tests for _handle_create_topic_result handler."""

    def test_no_error_appends_to_created(self) -> None:
        """Successful creation appends topic name to created list."""
        created: list[str] = []
        item = _topic_error("my-topic", _KafkaErrorCode.NO_ERROR)
        _handle_create_topic_result(item, created)
        assert created == ["my-topic"]

    def test_already_exists_raises(self) -> None:
        """Topic already exists raises TopicAlreadyExistsError."""
        created: list[str] = []
        item = _topic_error("my-topic", _KafkaErrorCode.TOPIC_ALREADY_EXISTS)
        with pytest.raises(TopicAlreadyExistsError, match="my-topic"):
            _handle_create_topic_result(item, created)
        assert created == []

    def test_unknown_error_raises_admin_error(self) -> None:
        """Unknown error code raises AdminError."""
        created: list[str] = []
        item = _topic_error("my-topic", 99, "some error")
        with pytest.raises(AdminError, match="Failed to create topic"):
            _handle_create_topic_result(item, created)


class TestHandleDeleteTopicResult:
    """Tests for _handle_delete_topic_result handler."""

    def test_no_error_appends_to_deleted(self) -> None:
        """Successful deletion appends topic name to deleted list."""
        deleted: list[str] = []
        item = _delete_error("my-topic", _KafkaErrorCode.NO_ERROR)
        _handle_delete_topic_result(item, deleted)
        assert deleted == ["my-topic"]

    def test_error_raises_admin_error(self) -> None:
        """Error code raises AdminError."""
        deleted: list[str] = []
        item = _delete_error("my-topic", 99)
        with pytest.raises(AdminError, match="Failed to delete topic"):
            _handle_delete_topic_result(item, deleted)


class TestDetectPartitionMismatch:
    """Tests for _detect_partition_mismatch helper."""

    def test_no_mismatch_returns_none(self) -> None:
        """Matching partition counts return None."""
        desc_map = {"t": TopicDescription(name="t", num_partitions=3)}
        spec_map = {"t": TopicSpec(name="t", num_partitions=3)}
        assert _detect_partition_mismatch("t", desc_map, spec_map) is None

    def test_mismatch_returns_warning(self) -> None:
        """Mismatched partition counts return warning string."""
        desc_map = {"t": TopicDescription(name="t", num_partitions=3)}
        spec_map = {"t": TopicSpec(name="t", num_partitions=6)}
        result = _detect_partition_mismatch("t", desc_map, spec_map)
        assert result is not None
        assert "3" in result
        assert "6" in result

    def test_missing_description_returns_none(self) -> None:
        """Missing description returns None."""
        spec_map = {"t": TopicSpec(name="t", num_partitions=3)}
        assert _detect_partition_mismatch("t", {}, spec_map) is None

    def test_missing_spec_returns_none(self) -> None:
        """Missing spec returns None."""
        desc_map = {"t": TopicDescription(name="t", num_partitions=3)}
        assert _detect_partition_mismatch("t", desc_map, {}) is None


class TestBuildAdminClient:
    """Tests for _build_admin_client factory."""

    @patch("nohiki_kafka_client.admin.client.AIOKafkaAdminClient")
    def test_passes_bootstrap_servers(self, mock_cls: MagicMock) -> None:
        """Factory passes bootstrap_servers from config."""
        config = _make_config("broker1:9092,broker2:9092")
        _build_admin_client(config)
        mock_cls.assert_called_once()
        assert mock_cls.call_args.kwargs["bootstrap_servers"] == "broker1:9092,broker2:9092"

    @patch("nohiki_kafka_client.admin.client.AIOKafkaAdminClient")
    def test_uses_plaintext_security(self, mock_cls: MagicMock) -> None:
        """Factory defaults to PLAINTEXT security protocol."""
        config = _make_config()
        _build_admin_client(config)
        assert mock_cls.call_args.kwargs["security_protocol"] == "PLAINTEXT"

    @patch("nohiki_kafka_client.admin.client.AIOKafkaAdminClient")
    def test_sets_client_id(self, mock_cls: MagicMock) -> None:
        """Factory constructs a client_id with -admin suffix."""
        config = _make_config()
        _build_admin_client(config)
        client_id = mock_cls.call_args.kwargs["client_id"]
        assert "-admin" in client_id

    @patch("nohiki_kafka_client.admin.client.AIOKafkaAdminClient")
    @patch("nohiki_kafka_client.admin.client.create_ssl_context")
    def test_ssl_protocol_creates_ssl_context(
        self,
        mock_create_ssl: MagicMock,
        mock_cls: MagicMock,
    ) -> None:
        """Factory creates SSL context for SSL security protocol."""
        from nohiki_kafka_client.config import SecurityConfig, SecurityProtocol

        mock_ctx = MagicMock()
        mock_create_ssl.return_value = mock_ctx
        config = KafkaClientConfig(
            bootstrap_servers="localhost:29092",
            security=SecurityConfig(protocol=SecurityProtocol.SSL),
        )
        _build_admin_client(config)
        mock_create_ssl.assert_called_once_with(config.security)
        assert mock_cls.call_args.kwargs["ssl_context"] is mock_ctx


class TestKafkaAdminLifecycle:
    """Tests for KafkaAdmin start/close/context manager."""

    @pytest.mark.asyncio
    async def test_start_success(self) -> None:
        """start() creates and starts the underlying client."""
        mock_client = AsyncMock()
        with patch(
            "nohiki_kafka_client.admin.client._build_admin_client",
            return_value=mock_client,
        ):
            admin = KafkaAdmin(_make_config())
            await admin.start()
            mock_client.start.assert_awaited_once()
            assert admin._client is mock_client

    @pytest.mark.asyncio
    async def test_start_failure_raises_admin_error(self) -> None:
        """start() raises AdminError on connection failure."""
        from aiokafka.errors import KafkaError

        mock_client = AsyncMock()
        mock_client.start.side_effect = KafkaError("connection refused")
        admin = KafkaAdmin(_make_config())
        with (
            patch(
                "nohiki_kafka_client.admin.client._build_admin_client",
                return_value=mock_client,
            ),
            pytest.raises(AdminError, match="Failed to start"),
        ):
            await admin.start()

    @pytest.mark.asyncio
    async def test_close_success(self) -> None:
        """close() closes client and sets it to None."""
        mock_client = AsyncMock()
        admin = _make_admin(mock_client)
        await admin.close()
        mock_client.close.assert_awaited_once()
        assert admin._client is None

    @pytest.mark.asyncio
    async def test_close_when_not_started(self) -> None:
        """close() is a no-op when client was never started."""
        admin = KafkaAdmin(_make_config())
        await admin.close()
        assert admin._client is None

    @pytest.mark.asyncio
    async def test_close_suppresses_error(self) -> None:
        """close() logs but does not raise on error."""
        from aiokafka.errors import KafkaError

        mock_client = AsyncMock()
        mock_client.close.side_effect = KafkaError("close failed")
        admin = _make_admin(mock_client)
        await admin.close()
        assert admin._client is None

    @pytest.mark.asyncio
    async def test_context_manager(self) -> None:
        """Async context manager starts and closes the client."""
        mock_client = AsyncMock()
        with patch(
            "nohiki_kafka_client.admin.client._build_admin_client",
            return_value=mock_client,
        ):
            async with KafkaAdmin(_make_config()) as admin:
                assert admin._client is mock_client
            mock_client.close.assert_awaited_once()

    def test_require_client_raises_when_not_started(self) -> None:
        """_require_client raises AdminError when client is None."""
        admin = KafkaAdmin(_make_config())
        with pytest.raises(AdminError, match="not started"):
            admin._require_client()

    def test_require_client_returns_client(self) -> None:
        """_require_client returns the active client."""
        mock_client = AsyncMock()
        admin = _make_admin(mock_client)
        assert admin._require_client() is mock_client


class TestKafkaAdminCreateTopics:
    """Tests for create_topic and create_topics methods."""

    @pytest.mark.asyncio
    async def test_create_topics_success(self) -> None:
        """create_topics returns names of created topics."""
        mock_client = AsyncMock()
        response = SimpleNamespace(
            topic_errors=[
                _topic_error("topic-a"),
                _topic_error("topic-b"),
            ]
        )
        mock_client.create_topics.return_value = response

        admin = _make_admin(mock_client)
        result = await admin.create_topics(
            [
                TopicSpec(name="topic-a"),
                TopicSpec(name="topic-b"),
            ]
        )
        assert result == ("topic-a", "topic-b")

    @pytest.mark.asyncio
    async def test_create_topics_empty_input(self) -> None:
        """create_topics with empty list returns empty tuple."""
        admin = _make_admin(AsyncMock())
        result = await admin.create_topics([])
        assert result == ()

    @pytest.mark.asyncio
    async def test_create_topics_already_exists_raises(self) -> None:
        """create_topics raises TopicAlreadyExistsError."""
        mock_client = AsyncMock()
        response = SimpleNamespace(
            topic_errors=[
                _topic_error("exists-topic", _KafkaErrorCode.TOPIC_ALREADY_EXISTS),
            ]
        )
        mock_client.create_topics.return_value = response

        admin = _make_admin(mock_client)
        with pytest.raises(TopicAlreadyExistsError):
            await admin.create_topics([TopicSpec(name="exists-topic")])

    @pytest.mark.asyncio
    async def test_create_topics_kafka_error(self) -> None:
        """create_topics raises AdminError on KafkaError."""
        from aiokafka.errors import KafkaError

        mock_client = AsyncMock()
        mock_client.create_topics.side_effect = KafkaError("boom")

        admin = _make_admin(mock_client)
        with pytest.raises(AdminError, match="Failed to create topics"):
            await admin.create_topics([TopicSpec(name="test")])

    @pytest.mark.asyncio
    async def test_create_topic_convenience(self) -> None:
        """create_topic delegates to create_topics."""
        mock_client = AsyncMock()
        response = SimpleNamespace(topic_errors=[_topic_error("my-topic")])
        mock_client.create_topics.return_value = response

        admin = _make_admin(mock_client)
        await admin.create_topic("my-topic", num_partitions=6)
        mock_client.create_topics.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_topic_not_started_raises(self) -> None:
        """create_topic raises AdminError when client not started."""
        admin = KafkaAdmin(_make_config())
        with pytest.raises(AdminError, match="not started"):
            await admin.create_topic("test")


class TestKafkaAdminDeleteTopics:
    """Tests for delete_topics method."""

    @pytest.mark.asyncio
    async def test_delete_topics_success(self) -> None:
        """delete_topics returns names of deleted topics."""
        mock_client = AsyncMock()
        response = SimpleNamespace(
            topic_error_codes=[
                _delete_error("topic-a"),
                _delete_error("topic-b"),
            ]
        )
        mock_client.delete_topics.return_value = response

        admin = _make_admin(mock_client)
        result = await admin.delete_topics(["topic-a", "topic-b"])
        assert result == ("topic-a", "topic-b")

    @pytest.mark.asyncio
    async def test_delete_topics_empty_input(self) -> None:
        """delete_topics with empty list returns empty tuple."""
        admin = _make_admin(AsyncMock())
        result = await admin.delete_topics([])
        assert result == ()

    @pytest.mark.asyncio
    async def test_delete_topics_error_raises(self) -> None:
        """delete_topics raises AdminError on error code."""
        mock_client = AsyncMock()
        response = SimpleNamespace(topic_error_codes=[_delete_error("test", 99)])
        mock_client.delete_topics.return_value = response

        admin = _make_admin(mock_client)
        with pytest.raises(AdminError, match="Failed to delete topic"):
            await admin.delete_topics(["test"])

    @pytest.mark.asyncio
    async def test_delete_topics_kafka_error(self) -> None:
        """delete_topics raises AdminError on KafkaError."""
        from aiokafka.errors import KafkaError

        mock_client = AsyncMock()
        mock_client.delete_topics.side_effect = KafkaError("boom")

        admin = _make_admin(mock_client)
        with pytest.raises(AdminError, match="Failed to delete topics"):
            await admin.delete_topics(["test"])


class TestKafkaAdminListTopics:
    """Tests for list_topics and topic_exists methods."""

    @pytest.mark.asyncio
    async def test_list_topics_filters_internal(self) -> None:
        """list_topics excludes internal topics by default."""
        mock_client = AsyncMock()
        mock_client.list_topics.return_value = ["user-topic", "__consumer_offsets", "__transaction_state"]

        admin = _make_admin(mock_client)
        result = await admin.list_topics()
        assert result == ("user-topic",)

    @pytest.mark.asyncio
    async def test_list_topics_include_internal(self) -> None:
        """list_topics includes internal topics when requested."""
        mock_client = AsyncMock()
        mock_client.list_topics.return_value = ["user-topic", "__consumer_offsets"]

        admin = _make_admin(mock_client)
        result = await admin.list_topics(include_internal=True)
        assert result == ("user-topic", "__consumer_offsets")

    @pytest.mark.asyncio
    async def test_list_topics_kafka_error(self) -> None:
        """list_topics raises AdminError on failure."""
        from aiokafka.errors import KafkaError

        mock_client = AsyncMock()
        mock_client.list_topics.side_effect = KafkaError("boom")

        admin = _make_admin(mock_client)
        with pytest.raises(AdminError, match="Failed to list topics"):
            await admin.list_topics()

    @pytest.mark.asyncio
    async def test_topic_exists_true(self) -> None:
        """topic_exists returns True for existing topic."""
        mock_client = AsyncMock()
        mock_client.list_topics.return_value = ["my-topic", "other-topic"]

        admin = _make_admin(mock_client)
        assert await admin.topic_exists("my-topic") is True

    @pytest.mark.asyncio
    async def test_topic_exists_false(self) -> None:
        """topic_exists returns False for non-existing topic."""
        mock_client = AsyncMock()
        mock_client.list_topics.return_value = ["other-topic"]

        admin = _make_admin(mock_client)
        assert await admin.topic_exists("missing-topic") is False


class TestKafkaAdminDescribeTopics:
    """Tests for describe_topics method."""

    @pytest.mark.asyncio
    async def test_describe_topics_success(self) -> None:
        """describe_topics returns parsed TopicDescription objects."""
        mock_client = AsyncMock()
        mock_client.describe_topics.return_value = [
            {"topic": "a", "partitions": [1, 2, 3]},
            {"topic": "b", "partitions": [1]},
        ]

        admin = _make_admin(mock_client)
        result = await admin.describe_topics(["a", "b"])
        assert len(result) == 2
        assert result[0] == TopicDescription(name="a", num_partitions=3)
        assert result[1] == TopicDescription(name="b", num_partitions=1)

    @pytest.mark.asyncio
    async def test_describe_topics_empty_input(self) -> None:
        """describe_topics with empty list returns empty tuple."""
        admin = _make_admin(AsyncMock())
        result = await admin.describe_topics([])
        assert result == ()

    @pytest.mark.asyncio
    async def test_describe_topics_kafka_error(self) -> None:
        """describe_topics raises AdminError on failure."""
        from aiokafka.errors import KafkaError

        mock_client = AsyncMock()
        mock_client.describe_topics.side_effect = KafkaError("boom")

        admin = _make_admin(mock_client)
        with pytest.raises(AdminError, match="Failed to describe topics"):
            await admin.describe_topics(["test"])


class TestKafkaAdminEnsureTopicsExist:
    """Tests for ensure_topics_exist idempotent operation."""

    @pytest.mark.asyncio
    async def test_all_new_topics(self) -> None:
        """All topics created when none exist."""
        mock_client = AsyncMock()
        mock_client.list_topics.return_value = []
        create_response = SimpleNamespace(
            topic_errors=[
                _topic_error("a"),
                _topic_error("b"),
            ]
        )
        mock_client.create_topics.return_value = create_response

        admin = _make_admin(mock_client)
        result = await admin.ensure_topics_exist(
            [
                TopicSpec(name="a"),
                TopicSpec(name="b"),
            ]
        )
        assert set(result.created) == {"a", "b"}
        assert result.existing == ()

    @pytest.mark.asyncio
    async def test_all_existing_topics(self) -> None:
        """No topics created when all exist."""
        mock_client = AsyncMock()
        mock_client.list_topics.return_value = ["a", "b"]
        mock_client.describe_topics.return_value = [
            {"topic": "a", "partitions": [1, 2, 3]},
            {"topic": "b", "partitions": [1, 2, 3]},
        ]

        admin = _make_admin(mock_client)
        result = await admin.ensure_topics_exist(
            [
                TopicSpec(name="a", num_partitions=3),
                TopicSpec(name="b", num_partitions=3),
            ]
        )
        assert result.created == ()
        assert set(result.existing) == {"a", "b"}
        assert result.warnings == ()

    @pytest.mark.asyncio
    async def test_mixed_new_and_existing(self) -> None:
        """Mix of new and existing topics."""
        mock_client = AsyncMock()
        mock_client.list_topics.return_value = ["a"]
        create_response = SimpleNamespace(topic_errors=[_topic_error("b")])
        mock_client.create_topics.return_value = create_response
        mock_client.describe_topics.return_value = [
            {"topic": "a", "partitions": [1, 2, 3]},
        ]

        admin = _make_admin(mock_client)
        result = await admin.ensure_topics_exist(
            [
                TopicSpec(name="a", num_partitions=3),
                TopicSpec(name="b", num_partitions=3),
            ]
        )
        assert result.created == ("b",)
        assert result.existing == ("a",)

    @pytest.mark.asyncio
    async def test_partition_mismatch_warning(self) -> None:
        """Existing topic with different partition count produces warning."""
        mock_client = AsyncMock()
        mock_client.list_topics.return_value = ["a"]
        mock_client.describe_topics.return_value = [
            {"topic": "a", "partitions": [1, 2, 3]},
        ]

        admin = _make_admin(mock_client)
        result = await admin.ensure_topics_exist(
            [
                TopicSpec(name="a", num_partitions=6),
            ]
        )
        assert len(result.warnings) == 1
        assert "3" in result.warnings[0]
        assert "6" in result.warnings[0]

    @pytest.mark.asyncio
    async def test_empty_input(self) -> None:
        """Empty specs returns empty result."""
        admin = _make_admin(AsyncMock())
        result = await admin.ensure_topics_exist([])
        assert result == EnsureTopicsResult()

    @pytest.mark.asyncio
    async def test_race_condition_already_exists(self) -> None:
        """Topic created between list and create is handled gracefully."""
        mock_client = AsyncMock()
        mock_client.list_topics.return_value = []
        create_response = SimpleNamespace(
            topic_errors=[
                _topic_error("a", _KafkaErrorCode.TOPIC_ALREADY_EXISTS),
            ]
        )
        mock_client.create_topics.return_value = create_response
        mock_client.describe_topics.return_value = [
            {"topic": "a", "partitions": [1, 2, 3]},
        ]

        admin = _make_admin(mock_client)
        result = await admin.ensure_topics_exist([TopicSpec(name="a")])
        assert result.created == ()
        assert "a" in result.existing

    @pytest.mark.asyncio
    async def test_ensure_kafka_error_during_create(self) -> None:
        """ensure_topics_exist raises AdminError when create call fails."""
        from aiokafka.errors import KafkaError

        mock_client = AsyncMock()
        mock_client.list_topics.return_value = []
        mock_client.create_topics.side_effect = KafkaError("network timeout")

        admin = _make_admin(mock_client)
        with pytest.raises(AdminError, match="Failed to create topics during ensure"):
            await admin.ensure_topics_exist([TopicSpec(name="a")])

    @pytest.mark.asyncio
    async def test_ensure_unknown_error_code_raises(self) -> None:
        """ensure_topics_exist raises AdminError on unexpected error codes."""
        mock_client = AsyncMock()
        mock_client.list_topics.return_value = []
        create_response = SimpleNamespace(
            topic_errors=[
                _topic_error("a", error_code=99, error_message="Unknown failure"),
            ]
        )
        mock_client.create_topics.return_value = create_response

        admin = _make_admin(mock_client)
        with pytest.raises(AdminError, match="Failed to create topic 'a'"):
            await admin.ensure_topics_exist([TopicSpec(name="a")])
