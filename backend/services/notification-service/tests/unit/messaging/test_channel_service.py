"""Tests for channel validation and recipient resolution."""

from __future__ import annotations

from uuid import uuid4

import pytest
from nohiki.common.v1 import NotificationChannel
from nohiki_fastapi_utils.errors import ErrorCode, NohikiError
from notification_service.services.messaging.channel_service import (
    ValidatedChannels,
    raise_invalid_channels_error,
    raise_no_channels_error,
    resolve_recipient_for_channel,
    validate_channels,
)


class TestValidateChannels:
    """Tests for validate_channels function."""

    def test_valid_email_channel(self) -> None:
        """Valid 'email' channel is parsed correctly."""
        result = validate_channels(["email"])
        assert len(result.valid) == 1
        assert result.valid[0] == NotificationChannel.EMAIL
        assert result.invalid == []
        assert result.has_invalid is False

    def test_valid_uppercase_channel(self) -> None:
        """Channel names are case-insensitive."""
        result = validate_channels(["EMAIL"])
        assert len(result.valid) == 1
        assert result.valid[0] == NotificationChannel.EMAIL

    def test_invalid_channel(self) -> None:
        """Invalid channel is captured in invalid list."""
        result = validate_channels(["invalid_channel"])
        assert result.valid == []
        assert result.invalid == ["invalid_channel"]
        assert result.has_invalid is True

    def test_mixed_valid_and_invalid(self) -> None:
        """Mixed channels are correctly categorized."""
        result = validate_channels(["email", "invalid", "sms_not_supported"])
        assert len(result.valid) == 1
        assert result.valid[0] == NotificationChannel.EMAIL
        assert result.invalid == ["invalid", "sms_not_supported"]
        assert result.has_invalid is True

    def test_empty_list(self) -> None:
        """Empty list returns empty results."""
        result = validate_channels([])
        assert result.valid == []
        assert result.invalid == []
        assert result.has_invalid is False

    def test_multiple_valid_channels(self) -> None:
        """Multiple valid channels are all parsed."""
        result = validate_channels(["email", "EMAIL"])
        assert len(result.valid) == 2
        assert all(c == NotificationChannel.EMAIL for c in result.valid)


class TestValidatedChannelsDataclass:
    """Tests for ValidatedChannels dataclass."""

    def test_has_invalid_property(self) -> None:
        """has_invalid property correctly reflects invalid count."""
        valid_only = ValidatedChannels(valid=[NotificationChannel.EMAIL], invalid=[])
        assert valid_only.has_invalid is False

        with_invalid = ValidatedChannels(valid=[], invalid=["bad"])
        assert with_invalid.has_invalid is True


class TestResolveRecipientForChannel:
    """Tests for resolve_recipient_for_channel function."""

    def test_email_channel_with_email(self) -> None:
        """EMAIL channel with valid email returns the email."""
        result = resolve_recipient_for_channel(
            NotificationChannel.EMAIL,
            "test@example.com",
            uuid4(),
        )
        assert result == "test@example.com"

    def test_email_channel_no_email_raises(self) -> None:
        """EMAIL channel without email raises NohikiError."""
        with pytest.raises(NohikiError) as exc_info:
            resolve_recipient_for_channel(NotificationChannel.EMAIL, None, uuid4())
        assert exc_info.value.error_code == ErrorCode.INVALID_REQUEST
        assert "No recipient available" in exc_info.value.message

    def test_unsupported_channel_raises(self) -> None:
        """Unsupported channels raise NOT_IMPLEMENTED error."""
        with pytest.raises(NohikiError) as exc_info:
            resolve_recipient_for_channel(NotificationChannel.SMS, "123456789", uuid4())
        assert exc_info.value.error_code == ErrorCode.NOT_IMPLEMENTED


class TestErrorHelpers:
    """Tests for error helper functions."""

    def test_raise_invalid_channels_error(self) -> None:
        """raise_invalid_channels_error raises with correct details."""
        with pytest.raises(NohikiError) as exc_info:
            raise_invalid_channels_error(["bad1", "bad2"])
        assert exc_info.value.error_code == ErrorCode.INVALID_REQUEST
        assert "Invalid notification channels" in exc_info.value.message

    def test_raise_no_channels_error(self) -> None:
        """raise_no_channels_error raises with user context."""
        user_id = uuid4()
        role_id = uuid4()
        with pytest.raises(NohikiError) as exc_info:
            raise_no_channels_error(user_id, role_id)
        assert exc_info.value.error_code == ErrorCode.INVALID_REQUEST
        assert "No notification channels" in exc_info.value.message
