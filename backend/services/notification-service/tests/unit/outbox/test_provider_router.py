"""Unit tests for :class:`ProviderRouter` dispatch and breaker logic.

Each test drives the router with synthesised providers (subclasses of
:class:`BaseProvider`) and the real :class:`CircuitBreaker`, so the
state-machine wiring is exercised end-to-end rather than mocked.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import ClassVar
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from nohiki.common.v1 import NotificationChannel
from nohiki_redis_utils import CircuitBreakerConfig
from notification_service.core.providers import (
    BaseProvider,
    EmailConfig,
    ProviderResult,
    clear_provider_registry,
    configure_email_provider,
    register_provider,
)
from notification_service.db.models import Message, NotificationChannelDB
from notification_service.services.outbox.provider_router import (
    ProviderRouter,
    SendVerdict,
)


class _StubProvider(BaseProvider):
    """Base for scripted test providers; subclasses override ``send`` behaviour."""

    channel = NotificationChannel.EMAIL
    required_secrets: ClassVar[list[str]] = []

    async def validate_config(self) -> bool:
        return True


def _make_message(provider_name: str | None = None) -> MagicMock:
    """Spec'd Message mock with the minimum fields the router reads."""
    msg = MagicMock(spec=Message)
    msg.id = uuid4()
    msg.channel = NotificationChannelDB.EMAIL
    msg.provider_name = provider_name
    return msg


def _email_config() -> EmailConfig:
    return EmailConfig(
        from_address="noreply@example.com",
        from_name="Test",
        unsubscribe_domain="example.com",
    )


def _breaker_config(**overrides: object) -> CircuitBreakerConfig:
    """Fast-tripping breaker config for tests."""
    defaults: dict[str, object] = {
        "failure_threshold": 2,
        "success_threshold": 1,
        "timeout_seconds": 0.05,
        "half_open_max_calls": 1,
    }
    defaults.update(overrides)
    return CircuitBreakerConfig(**defaults)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _reset_registry() -> Generator[None]:
    """Provider registry is module-global; reset before and after each test."""
    clear_provider_registry()
    yield
    clear_provider_registry()


class TestSendOutcomes:
    """Five canonical scenarios + the provider-not-found edge."""

    @pytest.mark.asyncio
    async def test_primary_delivers(self) -> None:
        """Primary returns success: outcome is DELIVERED, no fallback consulted."""

        class _Primary(_StubProvider):
            name: ClassVar[str] = "primary"
            calls: ClassVar[int] = 0

            async def send(self, message: Message) -> ProviderResult:
                _Primary.calls += 1
                return ProviderResult(success=True, provider_msg_id="ok-1")

        class _Fallback(_StubProvider):
            name: ClassVar[str] = "fallback"
            calls: ClassVar[int] = 0

            async def send(self, message: Message) -> ProviderResult:
                _Fallback.calls += 1
                return ProviderResult(success=True, provider_msg_id="ok-2")

        register_provider(NotificationChannel.EMAIL, _Primary)
        register_provider(NotificationChannel.EMAIL, _Fallback)
        configure_email_provider(_email_config(), "primary")

        router = ProviderRouter(cb_config=_breaker_config())
        outcome = await router.send(_make_message())

        assert outcome.verdict is SendVerdict.DELIVERED
        assert outcome.provider is not None
        assert outcome.provider.name == "primary"
        assert _Fallback.calls == 0

    @pytest.mark.asyncio
    async def test_primary_fails_non_circuit(self) -> None:
        """Single retryable failure: breaker stays CLOSED, returns FAILED."""

        class _Primary(_StubProvider):
            name: ClassVar[str] = "primary"

            async def send(self, message: Message) -> ProviderResult:
                return ProviderResult(success=False, error="500", retryable=True)

        register_provider(NotificationChannel.EMAIL, _Primary)
        configure_email_provider(_email_config(), "primary")

        router = ProviderRouter(cb_config=_breaker_config(failure_threshold=5))
        outcome = await router.send(_make_message())

        assert outcome.verdict is SendVerdict.FAILED
        assert outcome.provider is not None
        assert outcome.result is not None
        assert outcome.result.retryable is True

    @pytest.mark.asyncio
    async def test_primary_circuit_open_falls_back(self) -> None:
        """After primary trips, the next call routes to the fallback."""

        class _Primary(_StubProvider):
            name: ClassVar[str] = "primary"

            async def send(self, message: Message) -> ProviderResult:
                return ProviderResult(success=False, error="500", retryable=True)

        class _Fallback(_StubProvider):
            name: ClassVar[str] = "fallback"

            async def send(self, message: Message) -> ProviderResult:
                return ProviderResult(success=True, provider_msg_id="from-fallback")

        register_provider(NotificationChannel.EMAIL, _Primary)
        register_provider(NotificationChannel.EMAIL, _Fallback)
        configure_email_provider(_email_config(), "primary")

        router = ProviderRouter(cb_config=_breaker_config(failure_threshold=2))

        # Two failures trip the breaker; the third call must route to the fallback.
        await router.send(_make_message())
        await router.send(_make_message())
        outcome = await router.send(_make_message())

        assert outcome.verdict is SendVerdict.DELIVERED
        assert outcome.provider is not None
        assert outcome.provider.name == "fallback"

    @pytest.mark.asyncio
    async def test_all_circuits_open(self) -> None:
        """Every breaker open => ALL_CIRCUITS_OPEN, no provider in outcome."""

        class _Primary(_StubProvider):
            name: ClassVar[str] = "primary"

            async def send(self, message: Message) -> ProviderResult:
                return ProviderResult(success=False, error="500", retryable=True)

        class _Fallback(_StubProvider):
            name: ClassVar[str] = "fallback"

            async def send(self, message: Message) -> ProviderResult:
                return ProviderResult(success=False, error="500", retryable=True)

        register_provider(NotificationChannel.EMAIL, _Primary)
        register_provider(NotificationChannel.EMAIL, _Fallback)
        configure_email_provider(_email_config(), "primary")

        router = ProviderRouter(cb_config=_breaker_config(failure_threshold=2))

        # Trip both breakers (two failures each via primary then fallback).
        for _ in range(4):
            await router.send(_make_message())

        outcome = await router.send(_make_message())

        assert outcome.verdict is SendVerdict.ALL_CIRCUITS_OPEN
        assert outcome.provider is None
        assert outcome.result is None

    @pytest.mark.asyncio
    async def test_provider_not_found_returns_failed(self) -> None:
        """Unknown ``provider_name`` surfaces as a non-retryable FAILED outcome."""

        class _Primary(_StubProvider):
            name: ClassVar[str] = "primary"

            async def send(self, message: Message) -> ProviderResult:
                return ProviderResult(success=True)

        register_provider(NotificationChannel.EMAIL, _Primary)
        configure_email_provider(_email_config(), "primary")

        router = ProviderRouter(cb_config=_breaker_config())
        outcome = await router.send(_make_message(provider_name="does-not-exist"))

        assert outcome.verdict is SendVerdict.FAILED
        assert outcome.provider is None
        assert outcome.result is not None
        assert outcome.result.retryable is False
        assert "Provider not found" in (outcome.result.error or "")

    @pytest.mark.asyncio
    async def test_provider_raises_converts_to_retryable_failed(self) -> None:
        """A provider that raises is converted into FAILED+retryable, not propagated."""

        class _Primary(_StubProvider):
            name: ClassVar[str] = "primary"

            async def send(self, message: Message) -> ProviderResult:
                err = "network down"
                raise ConnectionError(err)

        register_provider(NotificationChannel.EMAIL, _Primary)
        configure_email_provider(_email_config(), "primary")

        router = ProviderRouter(cb_config=_breaker_config(failure_threshold=10))
        outcome = await router.send(_make_message())

        assert outcome.verdict is SendVerdict.FAILED
        assert outcome.provider is not None
        assert outcome.result is not None
        assert outcome.result.retryable is True
        assert "network down" in (outcome.result.error or "")


class TestBreakerIsolation:
    """Breakers are per-provider; one provider's failures don't gate another."""

    @pytest.mark.asyncio
    async def test_failure_on_one_does_not_open_the_other(self) -> None:
        """Primary fails twice, fallback still receives traffic normally."""

        class _Primary(_StubProvider):
            name: ClassVar[str] = "primary"

            async def send(self, message: Message) -> ProviderResult:
                return ProviderResult(success=False, error="500", retryable=True)

        class _Fallback(_StubProvider):
            name: ClassVar[str] = "fallback"
            calls: ClassVar[int] = 0

            async def send(self, message: Message) -> ProviderResult:
                _Fallback.calls += 1
                return ProviderResult(success=True, provider_msg_id="fb")

        register_provider(NotificationChannel.EMAIL, _Primary)
        register_provider(NotificationChannel.EMAIL, _Fallback)
        configure_email_provider(_email_config(), "primary")

        router = ProviderRouter(cb_config=_breaker_config(failure_threshold=2, timeout_seconds=60.0))

        # Two failures on primary trip its breaker; subsequent sends must
        # consistently route to the fallback without re-opening its breaker.
        for _ in range(5):
            outcome = await router.send(_make_message())

        assert outcome.verdict is SendVerdict.DELIVERED
        assert outcome.provider is not None
        assert outcome.provider.name == "fallback"
        # Fallback was reached on the three calls after primary tripped.
        assert _Fallback.calls == 3


class TestNonRetryableFailures:
    """Non-retryable rejections do not count against the breaker."""

    @pytest.mark.asyncio
    async def test_non_retryable_failure_does_not_trip_breaker(self) -> None:
        """Five 400-style rejections don't open the breaker; primary stays in service."""

        class _Primary(_StubProvider):
            name: ClassVar[str] = "primary"
            calls: ClassVar[int] = 0

            async def send(self, message: Message) -> ProviderResult:
                _Primary.calls += 1
                return ProviderResult(success=False, error="invalid recipient", retryable=False)

        register_provider(NotificationChannel.EMAIL, _Primary)
        configure_email_provider(_email_config(), "primary")

        router = ProviderRouter(cb_config=_breaker_config(failure_threshold=2))
        for _ in range(5):
            outcome = await router.send(_make_message())

        assert outcome.verdict is SendVerdict.FAILED
        assert outcome.provider is not None
        assert outcome.provider.name == "primary"
        assert _Primary.calls == 5
