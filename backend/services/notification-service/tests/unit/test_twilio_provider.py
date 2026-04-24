"""Tests for Twilio SendGrid email provider."""

from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import status
from nohiki.common.v1 import NotificationChannel
from notification_service.core.providers import EmailConfig
from notification_service.db.models import Message
from notification_service.services.provider_clients.twilio_email_provider import TwilioSendGridProvider


@pytest.fixture
def email_config() -> EmailConfig:
    """Fixture for EmailConfig."""
    return EmailConfig(
        from_address="test@example.com",
        from_name="Test Sender",
        unsubscribe_domain="example.com",
    )


@pytest.fixture
def message() -> Message:
    """Fixture for a Message model."""
    msg = MagicMock(spec=Message)
    msg.id = "123e4567-e89b-12d3-a456-426614174000"
    msg.user_id = "123e4567-e89b-12d3-a456-426614174001"
    msg.recipient = "recipient@example.com"
    msg.subject = "Test Subject"
    msg.body = "<p>Test Body</p>"
    msg.provider_payload = {}
    return msg


class TestTwilioSendGridProvider:
    """Tests for TwilioSendGridProvider."""

    def test_init(self, email_config: EmailConfig) -> None:
        """Test initialization."""
        with patch.dict(os.environ, {"SENDGRID_API_KEY": "SG.123"}):
            provider = TwilioSendGridProvider(email_config)
            assert provider.channel == NotificationChannel.EMAIL
            assert provider.name == "twilio_sendgrid"
            assert provider.api_key == "SG.123"

    @pytest.mark.asyncio
    async def test_send_success(self, email_config: EmailConfig, message: Message) -> None:
        """Test successful send."""
        with patch.dict(os.environ, {"SENDGRID_API_KEY": "SG.123"}):
            provider = TwilioSendGridProvider(email_config)

            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = status.HTTP_202_ACCEPTED
            mock_response.headers = {"X-Message-Id": "msg_123"}

            mock_client = AsyncMock(spec=httpx.AsyncClient)
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.post.return_value = mock_response

            with patch("httpx.AsyncClient", return_value=mock_client):
                result = await provider.send(message)

                assert result.success is True
                assert result.provider_msg_id == "msg_123"
                mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_failure_response(self, email_config: EmailConfig, message: Message) -> None:
        """Test send with failure response."""
        with patch.dict(os.environ, {"SENDGRID_API_KEY": "SG.123"}):
            provider = TwilioSendGridProvider(email_config)

            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = status.HTTP_400_BAD_REQUEST
            mock_response.json.return_value = {"errors": [{"message": "Invalid request"}]}

            mock_client = AsyncMock(spec=httpx.AsyncClient)
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.post.return_value = mock_response

            with patch("httpx.AsyncClient", return_value=mock_client):
                result = await provider.send(message)

                assert result.success is False
                assert "Invalid request" in str(result.error)
                assert result.retryable is False

    @pytest.mark.asyncio
    async def test_rate_limit_response_exposes_retry_after(
        self,
        email_config: EmailConfig,
        message: Message,
    ) -> None:
        """SendGrid's Retry-After header reaches the delivery scheduler."""
        with patch.dict(os.environ, {"SENDGRID_API_KEY": "SG.123"}):
            provider = TwilioSendGridProvider(email_config)
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = status.HTTP_429_TOO_MANY_REQUESTS
            mock_response.headers = {"Retry-After": "120"}
            mock_response.json.return_value = {"errors": [{"message": "Rate limited"}]}
            mock_response.text = "Rate limited"
            mock_client = AsyncMock(spec=httpx.AsyncClient)
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.post.return_value = mock_response

            with patch("httpx.AsyncClient", return_value=mock_client):
                result = await provider.send(message)

        assert result.success is False
        assert result.retryable is True
        assert result.retry_after_seconds == 120

    @pytest.mark.asyncio
    async def test_send_http_status_error(self, email_config: EmailConfig, message: Message) -> None:
        """Test send with HTTPStatusError."""
        with patch.dict(os.environ, {"SENDGRID_API_KEY": "SG.123"}):
            provider = TwilioSendGridProvider(email_config)

            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
            mock_response.json.return_value = {"errors": [{"message": "Server error"}]}

            mock_client = AsyncMock(spec=httpx.AsyncClient)
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.post.side_effect = httpx.HTTPStatusError("Error", request=MagicMock(), response=mock_response)

            with patch("httpx.AsyncClient", return_value=mock_client):
                result = await provider.send(message)

                assert result.success is False
                assert "Server error" in str(result.error)
                assert result.retryable is True

    @pytest.mark.asyncio
    async def test_send_request_error(self, email_config: EmailConfig, message: Message) -> None:
        """Test send with RequestError."""
        with patch.dict(os.environ, {"SENDGRID_API_KEY": "SG.123"}):
            provider = TwilioSendGridProvider(email_config)

            mock_client = AsyncMock(spec=httpx.AsyncClient)
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.post.side_effect = httpx.RequestError("Connection failed")

            with patch("httpx.AsyncClient", return_value=mock_client):
                result = await provider.send(message)

                assert result.success is False
                assert "Connection failed" in str(result.error)
                assert result.retryable is True

    @pytest.mark.asyncio
    async def test_send_validation_error(self, email_config: EmailConfig) -> None:
        """Test send with ValueError (missing fields)."""
        with patch.dict(os.environ, {"SENDGRID_API_KEY": "SG.123"}):
            provider = TwilioSendGridProvider(email_config)

            # Create mock message with missing required field to trigger validation error
            invalid_message = MagicMock(spec=Message)
            invalid_message.recipient = ""
            invalid_message.subject = "Test"
            invalid_message.body = "<p>Test</p>"
            invalid_message.id = uuid.uuid4()
            invalid_message.user_id = uuid.uuid4()

            result = await provider.send(invalid_message)

            assert result.success is False
            assert "Validation error" in str(result.error)
            assert result.retryable is False

    @pytest.mark.asyncio
    async def test_send_unexpected_error(self, email_config: EmailConfig, message: Message) -> None:
        """Test send with unexpected exception."""
        with patch.dict(os.environ, {"SENDGRID_API_KEY": "SG.123"}):
            provider = TwilioSendGridProvider(email_config)

            mock_client = AsyncMock(spec=httpx.AsyncClient)
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.post.side_effect = Exception("Boom")

            with patch("httpx.AsyncClient", return_value=mock_client):
                result = await provider.send(message)

                assert result.success is False
                assert "Unexpected error" in str(result.error)
                assert result.retryable is True

    def test_create_mail_payload(self, email_config: EmailConfig, message: Message) -> None:
        """Test payload creation."""
        with patch.dict(os.environ, {"SENDGRID_API_KEY": "SG.123"}):
            provider = TwilioSendGridProvider(email_config)
            message.provider_payload = {"text_alt": "Plain text"}

            payload = provider._create_mail_payload(message)

            assert payload["personalizations"][0]["to"][0]["email"] == "recipient@example.com"
            assert payload["subject"] == "Test Subject"
            assert payload["content"][0]["value"] == "Plain text"
            assert payload["content"][0]["type"] == "text/plain"
            assert payload["content"][1]["value"] == "<p>Test Body</p>"
            assert payload["content"][1]["type"] == "text/html"
            assert "X-Message-ID" in payload["headers"]
            assert "X-Account-ID" in payload["headers"]

    @pytest.mark.asyncio
    async def test_validate_config_success(self, email_config: EmailConfig) -> None:
        """Test configuration validation success."""
        with patch.dict(os.environ, {"SENDGRID_API_KEY": "SG.123"}):
            provider = TwilioSendGridProvider(email_config)

            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = status.HTTP_200_OK
            mock_response.json.return_value = {"scopes": ["mail.send"]}

            mock_client = AsyncMock(spec=httpx.AsyncClient)
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.get.return_value = mock_response

            with patch("httpx.AsyncClient", return_value=mock_client):
                assert await provider.validate_config() is True

    @pytest.mark.asyncio
    async def test_validate_config_missing_key(self, email_config: EmailConfig) -> None:
        """Test configuration validation failure due to missing key."""
        with patch.dict(os.environ, {"SENDGRID_API_KEY": "SG.123"}):
            provider = TwilioSendGridProvider(email_config)

        provider.api_key = ""
        assert await provider.validate_config() is False

    @pytest.mark.asyncio
    async def test_validate_config_invalid_key_format(self, email_config: EmailConfig) -> None:
        """Test configuration validation failure due to invalid key format."""
        with patch.dict(os.environ, {"SENDGRID_API_KEY": "invalid"}):
            provider = TwilioSendGridProvider(email_config)
            assert await provider.validate_config() is False

    @pytest.mark.asyncio
    async def test_validate_config_missing_scope(self, email_config: EmailConfig) -> None:
        """Test configuration validation failure due to missing scope."""
        with patch.dict(os.environ, {"SENDGRID_API_KEY": "SG.123"}):
            provider = TwilioSendGridProvider(email_config)

            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = status.HTTP_200_OK
            mock_response.json.return_value = {"scopes": ["other.scope"]}

            mock_client = AsyncMock(spec=httpx.AsyncClient)
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.get.return_value = mock_response

            with patch("httpx.AsyncClient", return_value=mock_client):
                assert await provider.validate_config() is False

    @pytest.mark.asyncio
    async def test_validate_config_api_failure(self, email_config: EmailConfig) -> None:
        """Test configuration validation failure due to API error."""
        with patch.dict(os.environ, {"SENDGRID_API_KEY": "SG.123"}):
            provider = TwilioSendGridProvider(email_config)

            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = status.HTTP_403_FORBIDDEN

            mock_client = AsyncMock(spec=httpx.AsyncClient)
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.get.return_value = mock_response

            with patch("httpx.AsyncClient", return_value=mock_client):
                assert await provider.validate_config() is False

    @pytest.mark.asyncio
    async def test_validate_config_cached(self, email_config: EmailConfig) -> None:
        """Test cached validation result."""
        with patch.dict(os.environ, {"SENDGRID_API_KEY": "SG.123"}):
            provider = TwilioSendGridProvider(email_config)
            from datetime import UTC, datetime

            provider._last_validation_time = datetime.now(UTC)
            provider._validation_result = True

            assert await provider.validate_config() is True

    @pytest.mark.asyncio
    async def test_retry_logic_dns_error(self, email_config: EmailConfig) -> None:
        """Test retry logic for DNS errors."""
        with patch.dict(os.environ, {"SENDGRID_API_KEY": "SG.123"}):
            provider = TwilioSendGridProvider(email_config)

            mock_client = AsyncMock(spec=httpx.AsyncClient)
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.get.side_effect = httpx.ConnectError("No address associated with hostname")

            with (
                patch("httpx.AsyncClient", return_value=mock_client),
                patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
            ):
                assert await provider.validate_config() is False
                assert mock_sleep.call_count == 2
