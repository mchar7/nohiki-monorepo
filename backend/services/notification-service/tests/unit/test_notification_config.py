"""Tests for notification configuration extraction module.

Tests the extraction of notification configuration from SearchPrefSnapshot's
nested notification_config structure following the ECST pattern.
"""

from __future__ import annotations

import dataclasses

from nohiki.common.v1 import (
    EmailDestination,
    NotificationChannel,
    NotificationMethod,
    SearchPrefNotificationConfig,
    SmsDestination,
    WebPushDestination,
)
from nohiki.user.pref.v1 import SearchPrefSnapshot
from notification_service.services.notification_config import (
    ExtractedNotificationConfig,
    extract_email_from_notification_config,
    extract_notification_config,
)


class TestExtractEmailFromNotificationConfig:
    """Tests for extract_email_from_notification_config function."""

    def test_returns_none_when_config_is_none(self) -> None:
        """Should return None when config is None."""
        result = extract_email_from_notification_config(None)
        assert result is None

    def test_returns_none_when_methods_list_is_empty(self) -> None:
        """Should return None when methods list is empty."""
        config = SearchPrefNotificationConfig(
            threshold=80,
            methods=[],
        )
        result = extract_email_from_notification_config(config)
        assert result is None

    def test_returns_none_when_no_methods_are_enabled(self) -> None:
        """Should return None when no methods are enabled."""
        config = SearchPrefNotificationConfig(
            threshold=80,
            methods=[
                NotificationMethod(
                    enabled=False,
                    channel=NotificationChannel.EMAIL,
                    email=EmailDestination(email_address="test@example.com"),
                ),
            ],
        )
        result = extract_email_from_notification_config(config)
        assert result is None

    def test_returns_none_when_enabled_method_has_no_email_destination(self) -> None:
        """Should return None when enabled method has no email destination."""
        config = SearchPrefNotificationConfig(
            threshold=80,
            methods=[
                NotificationMethod(
                    enabled=True,
                    channel=NotificationChannel.SMS,
                    sms=SmsDestination(phone_number="+14155551234"),
                ),
            ],
        )
        result = extract_email_from_notification_config(config)
        assert result is None

    def test_returns_none_when_email_destination_has_empty_address(self) -> None:
        """Should return None when email destination has empty address."""
        config = SearchPrefNotificationConfig(
            threshold=80,
            methods=[
                NotificationMethod(
                    enabled=True,
                    channel=NotificationChannel.EMAIL,
                    email=EmailDestination(email_address=""),
                ),
            ],
        )
        result = extract_email_from_notification_config(config)
        assert result is None

    def test_returns_email_when_enabled_method_has_email_destination(self) -> None:
        """Should return email when enabled method has email destination."""
        expected_email = "user@example.com"
        config = SearchPrefNotificationConfig(
            threshold=80,
            methods=[
                NotificationMethod(
                    enabled=True,
                    channel=NotificationChannel.EMAIL,
                    email=EmailDestination(email_address=expected_email),
                ),
            ],
        )
        result = extract_email_from_notification_config(config)
        assert result == expected_email

    def test_returns_first_enabled_email_when_multiple_methods_exist(self) -> None:
        """Should return first enabled email when multiple methods exist."""
        first_email = "first@example.com"
        second_email = "second@example.com"
        config = SearchPrefNotificationConfig(
            threshold=80,
            methods=[
                NotificationMethod(
                    enabled=False,
                    channel=NotificationChannel.EMAIL,
                    email=EmailDestination(email_address="disabled@example.com"),
                ),
                NotificationMethod(
                    enabled=True,
                    channel=NotificationChannel.EMAIL,
                    email=EmailDestination(email_address=first_email),
                ),
                NotificationMethod(
                    enabled=True,
                    channel=NotificationChannel.EMAIL,
                    email=EmailDestination(email_address=second_email),
                ),
            ],
        )
        result = extract_email_from_notification_config(config)
        assert result == first_email

    def test_skips_non_email_methods_to_find_email(self) -> None:
        """Should skip non-email methods to find email destination."""
        expected_email = "found@example.com"
        config = SearchPrefNotificationConfig(
            threshold=80,
            methods=[
                NotificationMethod(
                    enabled=True,
                    channel=NotificationChannel.SMS,
                    sms=SmsDestination(phone_number="+14155551234"),
                ),
                NotificationMethod(
                    enabled=True,
                    channel=NotificationChannel.PUSH_WEB,
                    web_push=WebPushDestination(device_token="token123", device_name="Browser"),
                ),
                NotificationMethod(
                    enabled=True,
                    channel=NotificationChannel.EMAIL,
                    email=EmailDestination(email_address=expected_email),
                ),
            ],
        )
        result = extract_email_from_notification_config(config)
        assert result == expected_email

    def test_handles_email_with_display_name(self) -> None:
        """Should return email address even when display name is set."""
        expected_email = "user@example.com"
        config = SearchPrefNotificationConfig(
            threshold=80,
            methods=[
                NotificationMethod(
                    enabled=True,
                    channel=NotificationChannel.EMAIL,
                    email=EmailDestination(
                        email_address=expected_email,
                        display_name="John Doe",
                    ),
                ),
            ],
        )
        result = extract_email_from_notification_config(config)
        assert result == expected_email


class TestExtractNotificationConfig:
    """Tests for extract_notification_config function."""

    def test_returns_none_when_pref_snapshot_is_none(self) -> None:
        """Should return None when pref_snapshot is None."""
        result = extract_notification_config(None)
        assert result is None

    def test_returns_none_when_notification_config_is_none(self) -> None:
        """Should return None when notification_config is None."""
        pref_snapshot = SearchPrefSnapshot(
            id="pref-123",
            user_id="user-456",
            pref_name="My Job Search",
            notification_config=None,
        )
        result = extract_notification_config(pref_snapshot)
        assert result is None

    def test_returns_extracted_config_with_all_fields(self) -> None:
        """Should return ExtractedNotificationConfig with all fields correctly extracted."""
        expected_user_id = "user-789"
        expected_pref_id = "pref-abc"
        expected_threshold = 75
        expected_email = "notifications@example.com"

        pref_snapshot = SearchPrefSnapshot(
            id=expected_pref_id,
            user_id=expected_user_id,
            pref_name="Engineering Jobs",
            notification_config=SearchPrefNotificationConfig(
                threshold=expected_threshold,
                methods=[
                    NotificationMethod(
                        enabled=True,
                        channel=NotificationChannel.EMAIL,
                        email=EmailDestination(email_address=expected_email),
                    ),
                ],
            ),
        )
        result = extract_notification_config(pref_snapshot)

        assert result is not None
        assert result.user_id == expected_user_id
        assert result.pref_id == expected_pref_id
        assert result.threshold == expected_threshold
        assert result.email_address == expected_email

    def test_returns_config_with_none_email_when_no_email_destination(self) -> None:
        """Should return config with None email when no email destination exists."""
        pref_snapshot = SearchPrefSnapshot(
            id="pref-123",
            user_id="user-456",
            pref_name="My Job Search",
            notification_config=SearchPrefNotificationConfig(
                threshold=50,
                methods=[
                    NotificationMethod(
                        enabled=True,
                        channel=NotificationChannel.SMS,
                        sms=SmsDestination(phone_number="+14155551234"),
                    ),
                ],
            ),
        )
        result = extract_notification_config(pref_snapshot)

        assert result is not None
        assert result.email_address is None
        assert result.threshold == 50

    def test_extracts_zero_threshold(self) -> None:
        """Should correctly extract zero threshold value."""
        pref_snapshot = SearchPrefSnapshot(
            id="pref-123",
            user_id="user-456",
            pref_name="My Job Search",
            notification_config=SearchPrefNotificationConfig(
                threshold=0,
                methods=[],
            ),
        )
        result = extract_notification_config(pref_snapshot)

        assert result is not None
        assert result.threshold == 0

    def test_extracts_max_threshold(self) -> None:
        """Should correctly extract maximum threshold value (100)."""
        pref_snapshot = SearchPrefSnapshot(
            id="pref-123",
            user_id="user-456",
            pref_name="My Job Search",
            notification_config=SearchPrefNotificationConfig(
                threshold=100,
                methods=[],
            ),
        )
        result = extract_notification_config(pref_snapshot)

        assert result is not None
        assert result.threshold == 100


class TestExtractedNotificationConfigDataclass:
    """Tests for ExtractedNotificationConfig dataclass."""

    def test_is_frozen_dataclass(self) -> None:
        """Should be a frozen dataclass."""
        assert dataclasses.is_dataclass(ExtractedNotificationConfig)
        params = getattr(ExtractedNotificationConfig, "__dataclass_params__", None)
        assert params is not None
        assert params.frozen is True

    def test_has_slots(self) -> None:
        """Should use slots for memory efficiency."""
        assert dataclasses.is_dataclass(ExtractedNotificationConfig)
        params = getattr(ExtractedNotificationConfig, "__dataclass_params__", None)
        assert params is not None
        assert params.slots is True

    def test_equality(self) -> None:
        """Should support equality comparison."""
        config1 = ExtractedNotificationConfig(
            user_id="user-123",
            pref_id="pref-456",
            threshold=80,
            email_address="test@example.com",
        )
        config2 = ExtractedNotificationConfig(
            user_id="user-123",
            pref_id="pref-456",
            threshold=80,
            email_address="test@example.com",
        )
        config3 = ExtractedNotificationConfig(
            user_id="user-different",
            pref_id="pref-456",
            threshold=80,
            email_address="test@example.com",
        )

        assert config1 == config2
        assert config1 != config3

    def test_can_have_none_email(self) -> None:
        """Should allow None for email_address."""
        config = ExtractedNotificationConfig(
            user_id="user-123",
            pref_id="pref-456",
            threshold=80,
            email_address=None,
        )
        assert config.email_address is None
