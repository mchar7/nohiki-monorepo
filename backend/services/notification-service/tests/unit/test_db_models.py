"""Tests for notification database enum mappings."""

from __future__ import annotations

import pytest
from nohiki.common.v1 import NotificationChannel
from notification_service.db.models import NotificationChannelDB


@pytest.mark.parametrize(
    ("db_channel", "proto_channel"),
    [
        (NotificationChannelDB.UNSPECIFIED, NotificationChannel.UNSPECIFIED),
        (NotificationChannelDB.EMAIL, NotificationChannel.EMAIL),
        (NotificationChannelDB.SMS, NotificationChannel.SMS),
        (NotificationChannelDB.PUSH_WEB, NotificationChannel.PUSH_WEB),
    ],
)
def test_notification_channel_round_trip(
    db_channel: NotificationChannelDB,
    proto_channel: NotificationChannel,
) -> None:
    """Each canonical channel maps explicitly in both directions."""
    assert NotificationChannelDB.from_proto(proto_channel) is db_channel
    assert db_channel.to_proto() is proto_channel


def test_notification_channel_db_has_exact_canonical_members() -> None:
    """Persistence exposes exactly the canonical labels and string values."""
    assert {(member.name, member.value) for member in NotificationChannelDB} == {
        ("UNSPECIFIED", "UNSPECIFIED"),
        ("EMAIL", "EMAIL"),
        ("SMS", "SMS"),
        ("PUSH_WEB", "PUSH_WEB"),
    }


def test_notification_channel_db_rejects_unknown_proto_value() -> None:
    """Unknown protobuf values fail clearly instead of relying on enum names."""
    with pytest.raises(ValueError, match="Unsupported notification channel"):
        NotificationChannelDB.from_proto(NotificationChannel(99))
