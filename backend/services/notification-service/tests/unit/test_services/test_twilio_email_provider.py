"""Tests for the Twilio SendGrid email provider with strict secrets handling."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator

import uuid

import httpx
import pytest
from notification_service.core.providers import EmailConfig, ProviderConfigError
from notification_service.db.models import Message, MessageStatus, NotificationChannelDB
from notification_service.services.provider_clients.twilio_email_provider import TwilioSendGridProvider


@pytest.fixture
def email_config() -> EmailConfig:
    """Create an email config for testing."""
    return EmailConfig(
        from_address="from@example.com",
        from_name="Test Sender",
        unsubscribe_domain="example.com",
    )


@pytest.fixture
def mock_secrets_dir(monkeypatch: pytest.MonkeyPatch) -> Generator[Path]:
    """Create a temporary directory for mock secrets and set env vars."""
    with tempfile.TemporaryDirectory() as temp_dir:
        secrets_dir = Path(temp_dir)

        # Set environment variable for the API key
        monkeypatch.setenv("SENDGRID_API_KEY", "test_api_key")

        yield secrets_dir


@pytest.fixture
async def provider_with_cleanup(
    email_config: EmailConfig,
) -> AsyncGenerator[TwilioSendGridProvider]:
    """Create a provider instance and clean up after test."""
    provider = TwilioSendGridProvider(email_config)
    try:
        yield provider
    finally:
        await provider.aclose()


@pytest.fixture
def mock_message() -> Message:
    """Create a mock message for testing."""
    return Message(
        id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        user_id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
        recipient="test@example.com",
        subject="Test Subject",
        body="<p>Test HTML body</p>",
        channel=NotificationChannelDB.EMAIL,
        status=MessageStatus.PENDING,
        provider_payload={"text_alt": "Test plain text body"},
    )


@pytest.fixture
def mock_http_response() -> MagicMock:
    """Create a mock HTTP response."""
    response = MagicMock(spec=httpx.Response)
    response.status_code = 202
    response.headers = {"X-Message-Id": "test-msg-id"}
    response.json.return_value = {}
    response.text = ""
    return response


@pytest.mark.asyncio
@pytest.mark.usefixtures("mock_secrets_dir")
async def test_provider_initialization(email_config: EmailConfig) -> None:
    """Test provider initialization."""
    provider = TwilioSendGridProvider(email_config)
    assert provider.api_key == "test_api_key"
    assert provider.config.from_address == "from@example.com"
    assert provider.config.from_name == "Test Sender"
    assert provider.base_url == "https://api.sendgrid.com/v3"
    await provider.aclose()


@pytest.mark.asyncio
async def test_provider_initialization_missing_secrets(
    email_config: EmailConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test provider initialization with missing secrets."""
    # Ensure the environment variable is not set
    monkeypatch.delenv("SENDGRID_API_KEY", raising=False)

    with pytest.raises(ProviderConfigError):
        TwilioSendGridProvider(email_config)


@pytest.mark.asyncio
@pytest.mark.usefixtures("mock_secrets_dir")
async def test_send_success(
    provider_with_cleanup: TwilioSendGridProvider,
    mock_message: Message,
    mock_http_response: MagicMock,
) -> None:
    """Successful send results in ProviderResult.success == True."""
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_http_response
        mock_client_class.return_value.__aenter__.return_value = mock_client

        provider = provider_with_cleanup
        result = await provider.send(mock_message)

        assert result.success is True
        assert result.provider_msg_id == "test-msg-id"
        assert result.error is None
        mock_client.post.assert_called_once_with("/mail/send", json=mock_client.post.call_args[1]["json"])


@pytest.mark.asyncio
@pytest.mark.usefixtures("mock_secrets_dir")
async def test_send_validation_error(mock_message: Message, email_config: EmailConfig) -> None:
    """Test message sending with validation error."""
    provider = TwilioSendGridProvider(email_config)

    # Create invalid message
    mock_message.recipient = ""

    result = await provider.send(mock_message)

    assert result.success is False
    assert result.error is not None
    assert "Validation error" in result.error
    assert result.retryable is False

    await provider.aclose()


@pytest.mark.asyncio
@pytest.mark.usefixtures("mock_secrets_dir")
async def test_send_http_error(mock_message: Message, email_config: EmailConfig) -> None:
    """Test message sending with HTTP error."""
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_error_response = MagicMock(spec=httpx.Response)
        mock_error_response.status_code = 400
        mock_error_response.json.return_value = {"errors": [{"message": "Bad request", "field": "content"}]}
        mock_error_response.text = "Bad request"

        mock_client.post.side_effect = httpx.HTTPStatusError(
            message="Bad request", request=MagicMock(), response=mock_error_response
        )
        mock_client_class.return_value.__aenter__.return_value = mock_client

        provider = TwilioSendGridProvider(email_config)
        result = await provider.send(mock_message)

        assert result.success is False
        assert result.error is not None
        assert "SendGrid HTTP error 400" in result.error
        assert result.retryable is False

        await provider.aclose()


@pytest.mark.asyncio
@pytest.mark.usefixtures("mock_secrets_dir")
async def test_send_network_error(mock_message: Message, email_config: EmailConfig) -> None:
    """Test handling of network errors during send."""
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.ConnectError("Network issue")
        mock_client_class.return_value.__aenter__.return_value = mock_client

        provider = TwilioSendGridProvider(email_config)
        result = await provider.send(mock_message)

        assert result.success is False
        assert result.error is not None
        assert "Network error" in result.error
        assert result.retryable is True

        await provider.aclose()


@pytest.mark.asyncio
@pytest.mark.usefixtures("mock_secrets_dir")
async def test_create_mail_payload(mock_message: Message, email_config: EmailConfig) -> None:
    """Test mail payload creation."""
    provider = TwilioSendGridProvider(email_config)

    payload = provider._create_mail_payload(mock_message)

    assert payload["personalizations"][0]["to"][0]["email"] == "test@example.com"
    assert payload["from"]["email"] == "from@example.com"
    assert payload["from"]["name"] == "Test Sender"
    assert payload["subject"] == "Test Subject"
    assert len(payload["content"]) == 2  # HTML and plain text
    assert payload["content"][0]["type"] == "text/plain"
    assert payload["content"][1]["type"] == "text/html"
    assert payload["headers"]["X-Message-ID"] == "00000000-0000-0000-0000-000000000001"
    assert payload["headers"]["X-Account-ID"] == "00000000-0000-0000-0000-000000000002"

    await provider.aclose()


@pytest.mark.asyncio
@pytest.mark.usefixtures("mock_secrets_dir")
async def test_validate_config_success(email_config: EmailConfig) -> None:
    """Test successful configuration validation."""
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"scopes": ["mail.send"]}
        mock_client.get.return_value = mock_response
        mock_client_class.return_value.__aenter__.return_value = mock_client

        provider = TwilioSendGridProvider(email_config)
        is_valid = await provider.validate_config()

        assert is_valid is True
        await provider.aclose()


@pytest.mark.asyncio
@pytest.mark.usefixtures("mock_secrets_dir")
async def test_validate_config_missing_scopes(email_config: EmailConfig) -> None:
    """Test configuration validation with missing scopes."""
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"scopes": ["mail.read"]}  # Missing mail.send
        mock_client.get.return_value = mock_response
        mock_client_class.return_value.__aenter__.return_value = mock_client

        provider = TwilioSendGridProvider(email_config)
        is_valid = await provider.validate_config()

        assert is_valid is False
        await provider.aclose()


@pytest.mark.asyncio
@pytest.mark.usefixtures("mock_secrets_dir")
async def test_parse_error_response(email_config: EmailConfig) -> None:
    """Test error response parsing."""
    provider = TwilioSendGridProvider(email_config)

    # Test with structured error response
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.json.return_value = {
        "errors": [{"message": "Invalid email", "field": "to"}, {"message": "Missing subject", "field": "subject"}]
    }

    error_msg = provider._parse_error_response(mock_response)
    assert "to: Invalid email" in error_msg
    assert "subject: Missing subject" in error_msg

    await provider.aclose()


@pytest.mark.asyncio
@pytest.mark.usefixtures("mock_secrets_dir")
async def test_is_retryable_error(email_config: EmailConfig) -> None:
    """Test retryable error detection."""
    provider = TwilioSendGridProvider(email_config)

    # Server errors should be retryable
    assert provider._is_retryable_error(500) is True
    assert provider._is_retryable_error(502) is True
    assert provider._is_retryable_error(503) is True

    # Rate limiting should be retryable
    assert provider._is_retryable_error(429) is True

    # Invalid credentials are permanent until configuration changes.
    assert provider._is_retryable_error(401) is False

    # Client errors should not be retryable
    assert provider._is_retryable_error(400) is False
    assert provider._is_retryable_error(404) is False

    await provider.aclose()
