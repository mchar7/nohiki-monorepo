"""Unit tests for message handler framework."""

from __future__ import annotations

import pytest
from nohiki_kafka_client.handlers import (
    CircuitBreakerConfig,
    DLQStrategy,
    ErrorAction,
    MessageContext,
    ResilienceConfig,
)
from nohiki_kafka_client.handlers.types import (
    _validate_non_empty_string,
    _validate_non_negative,
    _validate_positive,
)


class TestErrorAction:
    """Tests for ErrorAction enum."""

    def test_enum_values(self) -> None:
        """ErrorAction has expected values."""
        assert ErrorAction.SEND_TO_DLQ.value == "send_to_dlq"
        assert ErrorAction.RETRY.value == "retry"


class TestDLQStrategy:
    """Tests for DLQStrategy enum."""

    def test_enum_values(self) -> None:
        """DLQStrategy has expected values."""
        assert DLQStrategy.REPUBLISH.value == "republish"
        assert DLQStrategy.LOG_ONLY.value == "log_only"


class TestValidatePositive:
    """Tests for _validate_positive function."""

    def test_valid_positive(self) -> None:
        """Returns value when positive."""
        assert _validate_positive(1, "field") == 1
        assert _validate_positive(100, "field") == 100

    def test_invalid_zero(self) -> None:
        """Raises ValueError for zero."""
        with pytest.raises(ValueError, match="must be at least 1"):
            _validate_positive(0, "field")

    def test_invalid_negative(self) -> None:
        """Raises ValueError for negative."""
        with pytest.raises(ValueError, match="must be at least 1"):
            _validate_positive(-1, "field")


class TestValidateNonNegative:
    """Tests for _validate_non_negative function."""

    def test_valid_zero(self) -> None:
        """Returns value when zero."""
        assert _validate_non_negative(0, "field") == 0

    def test_valid_positive(self) -> None:
        """Returns value when positive."""
        assert _validate_non_negative(5, "field") == 5

    def test_invalid_negative(self) -> None:
        """Raises ValueError for negative."""
        with pytest.raises(ValueError, match="must be non-negative"):
            _validate_non_negative(-1, "field")


class TestValidateNonEmptyString:
    """Tests for _validate_non_empty_string function."""

    def test_valid_string(self) -> None:
        """Returns value when non-empty."""
        assert _validate_non_empty_string("test", "field") == "test"

    def test_invalid_empty(self) -> None:
        """Raises ValueError for empty string."""
        with pytest.raises(ValueError, match="cannot be empty"):
            _validate_non_empty_string("", "field")

    def test_invalid_whitespace(self) -> None:
        """Raises ValueError for whitespace-only string."""
        with pytest.raises(ValueError, match="cannot be empty"):
            _validate_non_empty_string("   ", "field")


class TestMessageContext:
    """Tests for MessageContext dataclass."""

    def test_create_context(self) -> None:
        """MessageContext stores all fields."""
        ctx = MessageContext(
            topic="test-topic",
            partition=1,
            offset=100,
            timestamp=1234567890000,
            headers={"key": "value"},
            key="msg-key",
        )
        assert ctx.topic == "test-topic"
        assert ctx.partition == 1
        assert ctx.offset == 100
        assert ctx.timestamp == 1234567890000
        assert ctx.headers == {"key": "value"}
        assert ctx.key == "msg-key"

    def test_context_defaults(self) -> None:
        """MessageContext has correct defaults for optional fields."""
        ctx = MessageContext(
            topic="topic",
            partition=0,
            offset=0,
            timestamp=0,
            headers={},
            key=None,
        )
        assert ctx.retry_count == 0
        assert ctx.correlation_id is None
        assert ctx.processing_metadata == {}

    def test_context_validates_partition(self) -> None:
        """MessageContext validates partition is non-negative."""
        with pytest.raises(ValueError, match="partition"):
            MessageContext(topic="topic", partition=-1, offset=0, timestamp=0, headers={}, key=None)

    def test_context_validates_offset(self) -> None:
        """MessageContext validates offset is non-negative."""
        with pytest.raises(ValueError, match="offset"):
            MessageContext(topic="topic", partition=0, offset=-1, timestamp=0, headers={}, key=None)

    def test_context_validates_retry_count(self) -> None:
        """MessageContext validates retry_count is non-negative."""
        with pytest.raises(ValueError, match="retry_count"):
            MessageContext(topic="topic", partition=0, offset=0, timestamp=0, headers={}, key=None, retry_count=-1)

    def test_context_initializes_processing_metadata(self) -> None:
        """MessageContext initializes processing_metadata if None."""
        ctx = MessageContext(topic="topic", partition=0, offset=0, timestamp=0, headers={}, key=None)
        assert ctx.processing_metadata == {}


class TestResilienceConfig:
    """Tests for ResilienceConfig dataclass."""

    def test_defaults_are_none(self) -> None:
        """All fields default to None (inherit from global)."""
        config = ResilienceConfig()
        assert config.max_retries is None
        assert config.retry_backoff_ms is None
        assert config.max_backoff_ms is None
        assert config.strategy is None

    def test_custom_overrides(self) -> None:
        """ResilienceConfig accepts custom override values."""
        config = ResilienceConfig(
            max_retries=5,
            retry_backoff_ms=200,
            max_backoff_ms=10000,
            strategy=DLQStrategy.LOG_ONLY,
        )
        assert config.max_retries == 5
        assert config.retry_backoff_ms == 200
        assert config.max_backoff_ms == 10000
        assert config.strategy == DLQStrategy.LOG_ONLY

    def test_is_frozen(self) -> None:
        """ResilienceConfig is immutable."""
        import dataclasses

        assert dataclasses.fields(ResilienceConfig)  # is a dataclass
        assert ResilienceConfig.__dataclass_params__.frozen  # is frozen


class TestCircuitBreakerConfig:
    """Tests for CircuitBreakerConfig dataclass."""

    def test_default_config(self) -> None:
        """CircuitBreakerConfig has correct defaults."""
        config = CircuitBreakerConfig()
        assert config.failure_threshold == 10
        assert config.timeout_seconds == 60
        assert config.half_open_max_calls == 5

    def test_custom_config(self) -> None:
        """CircuitBreakerConfig accepts custom values."""
        config = CircuitBreakerConfig(
            failure_threshold=5,
            timeout_seconds=30,
            half_open_max_calls=3,
        )
        assert config.failure_threshold == 5
        assert config.timeout_seconds == 30
        assert config.half_open_max_calls == 3


class TestMessageContextPublish:
    """Tests for MessageContext.publish method."""

    @pytest.mark.asyncio
    async def test_publish_without_client_raises(self) -> None:
        """Publish raises RuntimeError when kafka_client is None."""
        from dataclasses import dataclass

        import betterproto2

        @dataclass
        class MockMessage(betterproto2.Message):
            value: str = ""

        context = MessageContext(
            topic="test-topic",
            partition=0,
            offset=0,
            timestamp=0,
            headers={},
            key=None,
            kafka_client=None,
        )

        with pytest.raises(RuntimeError, match="not available"):
            await context.publish("out-topic", MockMessage(value="test"))

    @pytest.mark.asyncio
    async def test_publish_with_client_delegates(self) -> None:
        """Publish delegates to kafka_client."""
        from dataclasses import dataclass
        from unittest.mock import AsyncMock, MagicMock

        import betterproto2

        @dataclass
        class MockMessage(betterproto2.Message):
            value: str = ""

        mock_client = MagicMock()
        mock_client.publish = AsyncMock(return_value=MagicMock())

        context = MessageContext(
            topic="test-topic",
            partition=0,
            offset=0,
            timestamp=0,
            headers={},
            key=None,
            kafka_client=mock_client,
        )

        await context.publish("out-topic", MockMessage(value="test"))

        mock_client.publish.assert_called_once()


class TestMessageContextRequireDbSession:
    """Tests for MessageContext.require_db_session method."""

    def test_returns_session_when_set(self) -> None:
        """require_db_session returns the session when injected."""
        from unittest.mock import MagicMock

        mock_session = MagicMock()
        ctx = MessageContext(
            topic="test-topic",
            partition=0,
            offset=0,
            timestamp=0,
            headers={},
            key=None,
            db_session=mock_session,
        )
        result = ctx.require_db_session()
        assert result is mock_session

    def test_raises_when_none(self) -> None:
        """require_db_session raises RuntimeError when db_session is None."""
        ctx = MessageContext(
            topic="test-topic",
            partition=0,
            offset=0,
            timestamp=0,
            headers={},
            key=None,
        )
        with pytest.raises(RuntimeError, match="db_session not available"):
            ctx.require_db_session()


class TestMessageContextRequireOutbox:
    """Tests for MessageContext.require_outbox method."""

    def test_returns_outbox_when_set(self) -> None:
        """require_outbox returns the outbox when injected."""
        from unittest.mock import MagicMock

        mock_outbox = MagicMock()
        ctx = MessageContext(
            topic="test-topic",
            partition=0,
            offset=0,
            timestamp=0,
            headers={},
            key=None,
            outbox=mock_outbox,
        )
        result = ctx.require_outbox()
        assert result is mock_outbox

    def test_raises_when_none(self) -> None:
        """require_outbox raises RuntimeError when outbox is None."""
        ctx = MessageContext(
            topic="test-topic",
            partition=0,
            offset=0,
            timestamp=0,
            headers={},
            key=None,
        )
        with pytest.raises(RuntimeError, match="outbox not available"):
            ctx.require_outbox()


class TestHandlerRegistration:
    """Tests for HandlerRegistration dataclass."""

    def test_resilience_config_is_none_by_default(self) -> None:
        """resilience_config is None when not configured."""
        from dataclasses import dataclass

        import betterproto2
        from nohiki_kafka_client.handlers import HandlerRegistration

        @dataclass
        class MockMessage(betterproto2.Message):
            value: str = ""

        async def handler(message: MockMessage, context: MessageContext) -> None:
            pass  # Handler intentionally empty - testing registration

        reg = HandlerRegistration(
            topic="test.topic.v1",
            message_type=MockMessage,
            handler_func=handler,
            group_id="test-group",
        )

        assert reg.resilience_config is None

    def test_resilience_config_stores_typed_instance(self) -> None:
        """resilience_config stores ResilienceConfig dataclass directly."""
        from dataclasses import dataclass

        import betterproto2
        from nohiki_kafka_client.handlers import HandlerRegistration

        @dataclass
        class MockMessage(betterproto2.Message):
            value: str = ""

        async def handler(message: MockMessage, context: MessageContext) -> None:
            pass  # Handler intentionally empty - testing resilience config

        resilience_cfg = ResilienceConfig(max_retries=5, strategy=DLQStrategy.LOG_ONLY)
        reg = HandlerRegistration(
            topic="test.topic.v1",
            message_type=MockMessage,
            handler_func=handler,
            group_id="test-group",
            resilience_config=resilience_cfg,
        )

        assert reg.resilience_config is not None
        assert reg.resilience_config.max_retries == 5
        assert reg.resilience_config.strategy == DLQStrategy.LOG_ONLY
        assert reg.resilience_config is resilience_cfg

    def test_topic_naming_warning(self) -> None:
        """HandlerRegistration warns on short topic names."""
        import warnings
        from dataclasses import dataclass

        import betterproto2
        from nohiki_kafka_client.handlers import HandlerRegistration

        @dataclass
        class MockMessage(betterproto2.Message):
            value: str = ""

        async def handler(message: MockMessage, context: MessageContext) -> None:
            pass  # Handler intentionally empty - testing topic naming warning

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            HandlerRegistration(
                topic="short",
                message_type=MockMessage,
                handler_func=handler,
                group_id="test-group",
            )
            assert len(w) == 1
            assert "naming pattern" in str(w[0].message)
