"""Constants for messaging service."""

from __future__ import annotations

from typing import Final

from nohiki.common.v1 import DeliveryFailureCause

# Message status text used when template rendering is in progress
MSG_TEMPLATE_RENDERING: Final[str] = "Template rendering in progress..."
MSG_NO_RECIPIENT: Final[str] = "No recipient available for channel"

# Error messages
MESSAGE_NOT_FOUND: Final[str] = "Message not found"
DATABASE_INTEGRITY_ERROR: Final[str] = "Database integrity error during update"
INVALID_MESSAGE_STATUS: Final[str] = "Cannot cancel message with status"
DATABASE_ERROR_MESSAGE_UPDATE: Final[str] = "Database error during message update"
FAILED_TO_RETRIEVE_MESSAGE: Final[str] = "Failed to retrieve message"
DATABASE_ERROR_MESSAGE_CREATION: Final[str] = "Database error during message creation"
FAILED_TO_CANCEL_MESSAGE: Final[str] = "Failed to cancel message"
FAILED_TO_RETRIEVE_MESSAGE_STATS: Final[str] = "Failed to retrieve message statistics"
TEMPLATE_NOT_FOUND_ERROR: Final[str] = "Template not found in namespace with visibility"

# Pattern mapping for error message to protobuf DeliveryFailureCause
FAILURE_CAUSE_PATTERNS: Final[list[tuple[list[str], DeliveryFailureCause]]] = [
    (["provider not found"], DeliveryFailureCause.PROVIDER_NOT_FOUND),
    (["rate limit"], DeliveryFailureCause.RATE_LIMITED),
    (["template"], DeliveryFailureCause.TEMPLATE_ERROR),
    (["network", "connection", "timeout"], DeliveryFailureCause.NETWORK_ERROR),
    (["auth", "token", "credential"], DeliveryFailureCause.AUTHENTICATION_ERROR),
]


def determine_failure_cause(error_message: str | None) -> DeliveryFailureCause:
    """Determine the protobuf failure cause based on error message.

    Args:
        error_message: Error message string to analyze.

    Returns:
        Appropriate DeliveryFailureCause enum value.

    """
    if not error_message:
        return DeliveryFailureCause.UNEXPECTED_ERROR

    error_lower = error_message.lower()

    for patterns, cause in FAILURE_CAUSE_PATTERNS:
        if any(pattern in error_lower for pattern in patterns):
            return cause

    if "invalid" in error_lower and ("email" in error_lower or "recipient" in error_lower):
        return DeliveryFailureCause.INVALID_RECIPIENT

    return DeliveryFailureCause.PROVIDER_ERROR
