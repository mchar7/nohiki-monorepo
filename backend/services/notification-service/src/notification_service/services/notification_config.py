"""Notification configuration extraction from ECST pref_snapshot.

Utilities to extract notification configuration
from SearchPrefSnapshot's nested notification_config structure.
"""

from __future__ import annotations

from dataclasses import dataclass

from nohiki.common.v1 import SearchPrefNotificationConfig
from nohiki.user.pref.v1 import SearchPrefSnapshot


@dataclass(frozen=True, slots=True)
class ExtractedNotificationConfig:
    """Extracted notification configuration from pref_snapshot.

    Attributes:
        user_id: The user ID from the pref_snapshot
        pref_id: The preference ID from the pref_snapshot
        threshold: Notification threshold (0-100)
        email_address: First enabled email destination, or None

    """

    user_id: str
    pref_id: str
    threshold: int
    email_address: str | None


def extract_email_from_notification_config(
    config: SearchPrefNotificationConfig | None,
) -> str | None:
    """Extract first enabled email address from notification config.

    Navigates the nested structure:
    notification_config.methods[].email.email_address

    Args:
        config: The SearchPrefNotificationConfig from pref_snapshot

    Returns:
        The email address if found and enabled, None otherwise

    """
    if config is None:
        return None

    for method in config.methods:
        if method.enabled and method.email is not None and method.email.email_address:
            return method.email.email_address

    return None


def extract_notification_config(
    pref_snapshot: SearchPrefSnapshot | None,
) -> ExtractedNotificationConfig | None:
    """Extract notification configuration from SearchPrefSnapshot.

    Args:
        pref_snapshot: The preference snapshot from an ECST event

    Returns:
        ExtractedNotificationConfig if extraction successful, None otherwise

    """
    if pref_snapshot is None:
        return None

    config = pref_snapshot.notification_config
    if config is None:
        return None

    email_address = extract_email_from_notification_config(config)

    return ExtractedNotificationConfig(
        user_id=pref_snapshot.user_id,
        pref_id=pref_snapshot.id,
        threshold=config.threshold,
        email_address=email_address,
    )
