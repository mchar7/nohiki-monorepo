"""Connection-pool and timeout contract for the HTTP email providers.

Both providers must reuse one httpx client for every send, so a send costs no
TCP or TLS handshake and cannot exhaust ephemeral ports, and that client must
carry an explicit per-phase timeout so a hung provider releases the worker.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import ClassVar
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest
from nohiki.common.v1 import NotificationChannel
from notification_service.core.config import ProviderTimeoutSettings, get_settings
from notification_service.core.providers import (
    BaseProvider,
    EmailConfig,
    ProviderResult,
    aclose_all_providers,
    configure_email_provider,
    get_provider,
    register_provider,
)
from notification_service.db.models import Message
from notification_service.services.provider_clients.http_pool import build_pooled_client
from notification_service.services.provider_clients.resend_email_provider import ResendEmailProvider
from notification_service.services.provider_clients.twilio_email_provider import TwilioSendGridProvider


@dataclass(frozen=True, slots=True)
class _ProviderCase:
    """One provider under test, with the shape of an accepted response."""

    factory: Callable[[EmailConfig], BaseProvider]
    env_var: str
    api_key: str
    accepted_status: int
    accepted_json: dict[str, str]
    accepted_headers: dict[str, str]
    expected_msg_id: str


_CASES = {
    "resend": _ProviderCase(
        factory=ResendEmailProvider,
        env_var="RESEND_API_KEY",
        api_key="re_123",
        accepted_status=200,
        accepted_json={"id": "resend-msg-1"},
        accepted_headers={},
        expected_msg_id="resend-msg-1",
    ),
    "twilio_sendgrid": _ProviderCase(
        factory=TwilioSendGridProvider,
        env_var="SENDGRID_API_KEY",
        api_key="SG.123",
        accepted_status=202,
        accepted_json={},
        accepted_headers={"X-Message-Id": "sendgrid-msg-1"},
        expected_msg_id="sendgrid-msg-1",
    ),
}


@pytest.fixture
def email_config() -> EmailConfig:
    """Shared email config with no provider-specific key."""
    return EmailConfig(
        from_address="from@example.com",
        from_name="Test Sender",
        unsubscribe_domain="example.com",
    )


@pytest.fixture
def message() -> MagicMock:
    """Minimal sendable message."""
    msg = MagicMock(spec=Message)
    msg.id = uuid4()
    msg.user_id = uuid4()
    msg.external_layout_id = None
    msg.recipient = "to@example.com"
    msg.subject = "Subject"
    msg.body = "<p>Body</p>"
    msg.provider_payload = {}
    return msg


def _accepted_response(case: _ProviderCase) -> MagicMock:
    response = MagicMock(spec=httpx.Response)
    response.status_code = case.accepted_status
    response.json.return_value = case.accepted_json
    response.headers = case.accepted_headers
    response.text = ""
    return response


def _build_provider(case: _ProviderCase, email_config: EmailConfig) -> BaseProvider:
    with patch.dict(os.environ, {case.env_var: case.api_key}):
        return case.factory(email_config)


class TestProviderTimeoutSettings:
    """The timeout budget is explicit and per phase."""

    def test_maps_every_phase(self) -> None:
        """Each configured phase lands on the matching httpx timeout slot."""
        timeout = ProviderTimeoutSettings(
            connect_seconds=1.5,
            read_seconds=2.5,
            write_seconds=3.5,
            pool_seconds=4.5,
        ).to_httpx_timeout()

        assert timeout.connect == pytest.approx(1.5)
        assert timeout.read == pytest.approx(2.5)
        assert timeout.write == pytest.approx(3.5)
        assert timeout.pool == pytest.approx(4.5)

    def test_no_phase_is_unbounded(self) -> None:
        """Defaults leave no phase without a deadline."""
        timeout = ProviderTimeoutSettings().to_httpx_timeout()

        assert None not in (timeout.connect, timeout.read, timeout.write, timeout.pool)


class TestPooledClient:
    """`build_pooled_client` is the single source of the timeout budget."""

    @pytest.mark.asyncio
    async def test_client_carries_configured_timeout(self) -> None:
        """The constructed client's timeout matches the settings budget."""
        client = build_pooled_client(base_url="https://example.invalid", headers={})
        try:
            assert client.timeout == get_settings().email.timeout.to_httpx_timeout()
        finally:
            await client.aclose()


@pytest.mark.parametrize("case_name", list(_CASES))
class TestProviderPooling:
    """Pooling contract, asserted identically for every HTTP provider."""

    @pytest.mark.asyncio
    async def test_client_is_built_once_and_reused_across_sends(
        self,
        case_name: str,
        email_config: EmailConfig,
        message: MagicMock,
    ) -> None:
        """Two sends share one client, so no second handshake is paid."""
        case = _CASES[case_name]
        provider = _build_provider(case, email_config)

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post.return_value = _accepted_response(case)

        with patch("httpx.AsyncClient", return_value=mock_client) as client_factory:
            first = await provider.send(message)
            second = await provider.send(message)

        assert first.success is True
        assert second.success is True
        assert first.provider_msg_id == case.expected_msg_id
        assert client_factory.call_count == 1, "a second client means the pool was not reused"
        assert mock_client.post.await_count == 2

    @pytest.mark.asyncio
    async def test_send_carries_the_explicit_timeout(
        self,
        case_name: str,
        email_config: EmailConfig,
        message: MagicMock,
    ) -> None:
        """The client the send runs on was built with the per-phase budget."""
        case = _CASES[case_name]
        provider = _build_provider(case, email_config)

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post.return_value = _accepted_response(case)

        with patch("httpx.AsyncClient", return_value=mock_client) as client_factory:
            await provider.send(message)

        assert client_factory.call_args.kwargs["timeout"] == get_settings().email.timeout.to_httpx_timeout()

    @pytest.mark.asyncio
    async def test_send_and_validate_share_one_client(
        self,
        case_name: str,
        email_config: EmailConfig,
        message: MagicMock,
    ) -> None:
        """Config validation reuses the send pool instead of opening its own."""
        case = _CASES[case_name]
        provider = _build_provider(case, email_config)

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post.return_value = _accepted_response(case)
        validation = MagicMock(spec=httpx.Response)
        validation.status_code = 200
        validation.json.return_value = {"scopes": ["mail.send"]}
        mock_client.get.return_value = validation

        with patch("httpx.AsyncClient", return_value=mock_client) as client_factory:
            await provider.send(message)
            await provider.validate_config()

        assert client_factory.call_count == 1

    @pytest.mark.asyncio
    async def test_aclose_releases_the_pool(
        self,
        case_name: str,
        email_config: EmailConfig,
        message: MagicMock,
    ) -> None:
        """`aclose` closes the live client and forgets it."""
        case = _CASES[case_name]
        provider = _build_provider(case, email_config)

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post.return_value = _accepted_response(case)

        with patch("httpx.AsyncClient", return_value=mock_client):
            await provider.send(message)
            await provider.aclose()

        mock_client.aclose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_aclose_without_a_send_is_a_noop(
        self,
        case_name: str,
        email_config: EmailConfig,
    ) -> None:
        """A provider that never sent holds nothing to close."""
        case = _CASES[case_name]
        provider = _build_provider(case, email_config)

        with patch("httpx.AsyncClient") as client_factory:
            await provider.aclose()

        client_factory.assert_not_called()


class _ClosableProvider(BaseProvider):
    """Provider recording whether it was asked to close."""

    channel = NotificationChannel.EMAIL
    name: ClassVar[str] = "closable"
    required_secrets: ClassVar[list[str]] = []
    closed: ClassVar[list[str]] = []

    async def send(self, message: Message) -> ProviderResult:
        _ = message
        return ProviderResult(success=True)

    async def validate_config(self) -> bool:
        return True

    async def aclose(self) -> None:
        _ClosableProvider.closed.append(self.name)


class _BrokenCloseProvider(_ClosableProvider):
    """Provider whose close always fails."""

    name: ClassVar[str] = "broken_close"

    async def aclose(self) -> None:
        msg = "close failed"
        raise RuntimeError(msg)


class TestAcloseAllProviders:
    """Shutdown must close every instantiated pool exactly once."""

    @pytest.mark.asyncio
    async def test_closes_every_instantiated_provider(self, email_config: EmailConfig) -> None:
        """Providers reachable from the registry are all closed."""
        _ClosableProvider.closed = []
        register_provider(NotificationChannel.EMAIL, _ClosableProvider)
        configure_email_provider(email_config, "closable")
        get_provider(NotificationChannel.EMAIL, "closable")

        await aclose_all_providers()

        assert _ClosableProvider.closed == ["closable"]

    @pytest.mark.asyncio
    async def test_one_failure_does_not_strand_the_others(self, email_config: EmailConfig) -> None:
        """A provider that raises on close never blocks its siblings."""
        _ClosableProvider.closed = []
        register_provider(NotificationChannel.EMAIL, _BrokenCloseProvider)
        register_provider(NotificationChannel.EMAIL, _ClosableProvider)
        configure_email_provider(email_config, "broken_close")
        get_provider(NotificationChannel.EMAIL, "broken_close")
        get_provider(NotificationChannel.EMAIL, "closable")

        await aclose_all_providers()

        assert _ClosableProvider.closed == ["closable"]
