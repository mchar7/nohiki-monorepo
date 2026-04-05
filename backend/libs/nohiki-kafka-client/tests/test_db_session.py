"""Tests for with_db_session decorator and db_session_middleware."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import betterproto2
import pytest
from nohiki_db_utils.testing import create_mock_session
from nohiki_kafka_client.client.auto_client import AutoKafkaClient
from nohiki_kafka_client.config import KafkaClientConfig
from nohiki_kafka_client.exceptions import KafkaClientError
from nohiki_kafka_client.handlers import (
    DbSessionConfig,
    HandlerRegistration,
    MessageContext,
)
from nohiki_kafka_client.handlers.registry import HandlerRegistryMixin, _HandlerMetadata
from nohiki_kafka_client.middleware.db_session import execute_with_db_session


class _StubMessage(betterproto2.Message):
    """Minimal betterproto2 message for testing."""


def _make_context() -> MessageContext:
    return MessageContext(
        topic="test.topic.v1",
        partition=0,
        offset=0,
        timestamp=0,
        headers={},
        key=None,
    )


# execute_with_db_session middleware tests


class TestExecuteWithDbSession:
    """Tests for the execute_with_db_session middleware function."""

    @pytest.mark.asyncio
    async def test_injects_db_session_into_context(self) -> None:
        """Session is injected into context.db_session before handler runs."""
        mock_session = create_mock_session()
        mock_factory = MagicMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        handler = AsyncMock()
        handler.__name__ = "handler"
        handler.__module__ = __name__

        config = DbSessionConfig(auto_commit=True)
        context = _make_context()
        await execute_with_db_session(handler, _StubMessage(), context, config, mock_factory)

        assert context.db_session is mock_session

    @pytest.mark.asyncio
    async def test_auto_commit_true_commits(self) -> None:
        """Session is committed when auto_commit is True."""
        mock_session = create_mock_session()
        mock_factory = MagicMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        handler = AsyncMock()
        handler.__name__ = "handler"
        handler.__module__ = __name__

        config = DbSessionConfig(auto_commit=True)
        context = _make_context()
        await execute_with_db_session(handler, _StubMessage(), context, config, mock_factory)

        mock_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_auto_commit_false_skips_commit(self) -> None:
        """Session is NOT committed when auto_commit is False."""
        mock_session = create_mock_session()
        mock_factory = MagicMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        handler = AsyncMock()
        handler.__name__ = "handler"
        handler.__module__ = __name__

        config = DbSessionConfig(auto_commit=False)
        context = _make_context()
        await execute_with_db_session(handler, _StubMessage(), context, config, mock_factory)

        mock_session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_handler_exception_rolls_back_and_propagates(self) -> None:
        """Handler exceptions trigger rollback, then propagate."""
        mock_session = create_mock_session()
        mock_factory = MagicMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        handler = AsyncMock(side_effect=ValueError("handler failed"))
        handler.__name__ = "handler"
        handler.__module__ = __name__

        config = DbSessionConfig(auto_commit=True)
        context = _make_context()
        with pytest.raises(ValueError, match="handler failed"):
            await execute_with_db_session(handler, _StubMessage(), context, config, mock_factory)

        mock_session.commit.assert_not_awaited()
        mock_session.rollback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handler_cancellation_rolls_back_and_propagates(self) -> None:
        """Cancellation is transactional failure, not a publishable handler error."""
        mock_session = create_mock_session()
        lifecycle: list[str] = []

        async def _rollback() -> None:
            lifecycle.append("rollback")

        async def _exit(
            _exc_type: object,
            _exc: object,
            _traceback: object,
        ) -> bool:
            lifecycle.append("exit")
            return False

        mock_session.rollback.side_effect = _rollback
        context_manager = MagicMock()
        context_manager.__aenter__ = AsyncMock(return_value=mock_session)
        context_manager.__aexit__ = AsyncMock(side_effect=_exit)
        session_factory = MagicMock(return_value=context_manager)
        cancellation = asyncio.CancelledError()
        handler = AsyncMock(side_effect=cancellation)

        with pytest.raises(asyncio.CancelledError) as raised:
            await execute_with_db_session(
                handler,
                _StubMessage(),
                _make_context(),
                DbSessionConfig(auto_commit=True),
                session_factory,
            )

        assert raised.value is cancellation
        assert lifecycle == ["rollback", "exit"]
        mock_session.rollback.assert_awaited_once_with()
        mock_session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_outbox_injected_when_schema_provided(self) -> None:
        """OutboxWriter is injected into context.outbox when config.schema is set."""
        mock_session = create_mock_session()
        mock_factory = MagicMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        handler = AsyncMock()
        handler.__name__ = "handler"
        handler.__module__ = __name__

        config = DbSessionConfig(schema="test_schema", auto_commit=True)
        context = _make_context()

        with patch("nohiki_db_utils.OutboxWriter") as mock_outbox_cls:
            mock_outbox_instance = MagicMock()
            mock_outbox_cls.return_value = mock_outbox_instance
            await execute_with_db_session(handler, _StubMessage(), context, config, mock_factory)

            mock_outbox_cls.assert_called_once_with(schema="test_schema")
            assert context.outbox is mock_outbox_instance

    @pytest.mark.asyncio
    async def test_outbox_not_injected_when_no_schema(self) -> None:
        """OutboxWriter is NOT injected when config.schema is None."""
        mock_session = create_mock_session()
        mock_factory = MagicMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        handler = AsyncMock()
        handler.__name__ = "handler"
        handler.__module__ = __name__

        config = DbSessionConfig(auto_commit=True)
        context = _make_context()
        await execute_with_db_session(handler, _StubMessage(), context, config, mock_factory)

        assert context.outbox is None


# with_db_session decorator tests (metadata-only, no db deps)


class _ConcreteRegistry(HandlerRegistryMixin):
    """Concrete HandlerRegistryMixin for testing."""

    def __init__(self) -> None:
        self._handlers: dict[str, HandlerRegistration] = {}
        self._handler_metadata: dict[int, _HandlerMetadata] = {}


class TestWithDbSessionDecorator:
    """Tests for the @with_db_session decorator metadata propagation."""

    def test_stores_config_when_applied_before_message_handler(self) -> None:
        """with_db_session applied before message_handler propagates config."""
        registry = _ConcreteRegistry()

        @registry.with_db_session(schema="test_schema", auto_commit=False)
        @registry.message_handler("test.topic.v1", _StubMessage, group_id="test-group")
        async def handler(
            _message: _StubMessage, _context: MessageContext
        ) -> None: ...  # handler body unused; testing decorator metadata propagation

        reg = next(iter(registry._handlers.values()))
        assert reg.db_session_config == DbSessionConfig(schema="test_schema", auto_commit=False)

    def test_stores_config_when_applied_after_message_handler(self) -> None:
        """with_db_session applied after message_handler propagates config."""
        registry = _ConcreteRegistry()

        @registry.message_handler("test.topic.v1", _StubMessage, group_id="test-group")
        @registry.with_db_session(schema="my_schema")
        async def handler(
            _message: _StubMessage, _context: MessageContext
        ) -> None: ...  # handler body unused; testing decorator metadata propagation

        reg = next(iter(registry._handlers.values()))
        assert reg.db_session_config == DbSessionConfig(schema="my_schema", auto_commit=True)

    def test_default_schema_is_none(self) -> None:
        """with_db_session defaults schema to None."""
        registry = _ConcreteRegistry()

        @registry.with_db_session()
        @registry.message_handler("test.topic.v1", _StubMessage, group_id="test-group")
        async def handler(
            _message: _StubMessage, _context: MessageContext
        ) -> None: ...  # handler body unused; testing decorator metadata propagation

        reg = next(iter(registry._handlers.values()))
        assert reg.db_session_config == DbSessionConfig(schema=None, auto_commit=True)

    def test_no_config_when_not_decorated(self) -> None:
        """Handlers without with_db_session have None db_session_config."""
        registry = _ConcreteRegistry()

        @registry.message_handler("test.topic.v1", _StubMessage, group_id="test-group")
        async def handler(
            _message: _StubMessage, _context: MessageContext
        ) -> None: ...  # handler body unused; testing absence of db config

        reg = next(iter(registry._handlers.values()))
        assert reg.db_session_config is None


# AutoKafkaClient._wrap_handler_with_db_session tests


class TestAutoKafkaClientWrapHandler:
    """Tests for AutoKafkaClient._wrap_handler_with_db_session."""

    def _make_client(self) -> AutoKafkaClient:
        return AutoKafkaClient(
            KafkaClientConfig(bootstrap_servers="localhost:29092"),
            is_testing=True,
        )

    def test_raises_when_no_factory_registered(self) -> None:
        """Raises KafkaClientError when handler uses @with_db_session but no factory set."""
        client = self._make_client()

        handler = AsyncMock()
        handler.__name__ = "handler"
        handler.__module__ = __name__

        registration = HandlerRegistration(
            topic="test.topic.v1",
            message_type=_StubMessage,
            handler_func=handler,
            group_id="test-group",
            db_session_config=DbSessionConfig(schema="test", auto_commit=True),
        )

        with pytest.raises(KafkaClientError, match="no db session factory was registered"):
            client._wrap_handler_with_db_session(registration)

    def test_returns_unchanged_registration_without_db_config(self) -> None:
        """Returns the same registration when no db_session_config."""
        client = self._make_client()

        handler = AsyncMock()
        handler.__name__ = "handler"
        handler.__module__ = __name__

        registration = HandlerRegistration(
            topic="test.topic.v1",
            message_type=_StubMessage,
            handler_func=handler,
            group_id="test-group",
        )

        result = client._wrap_handler_with_db_session(registration)
        assert result is registration

    @pytest.mark.asyncio
    @patch(
        "nohiki_kafka_client.client.auto_client.execute_with_db_session",
        new_callable=AsyncMock,
    )
    async def test_wrapped_handler_delegates_to_middleware(self, mock_execute: AsyncMock) -> None:
        """Wrapped handler delegates to execute_with_db_session when db config is set."""
        client = self._make_client()
        mock_factory = MagicMock()
        client.set_db_session_factory(mock_factory)

        handler = AsyncMock()
        handler.__name__ = "handler"
        handler.__module__ = __name__

        db_config = DbSessionConfig(schema="test", auto_commit=True)
        registration = HandlerRegistration(
            topic="test.topic.v1",
            message_type=_StubMessage,
            handler_func=handler,
            group_id="test-group",
            db_session_config=db_config,
        )

        wrapped_reg = client._wrap_handler_with_db_session(registration)
        context = _make_context()
        message = _StubMessage()

        await wrapped_reg.handler_func(message, context)

        mock_execute.assert_awaited_once_with(handler, message, context, db_config, mock_factory)
