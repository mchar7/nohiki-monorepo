"""Channel validation and recipient resolution for notifications."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, NoReturn

from nohiki.common.v1 import NotificationChannel
from nohiki_fastapi_utils.errors import ErrorCode, ErrorField, NohikiError

if TYPE_CHECKING:
    from uuid import UUID


@dataclass(frozen=True, slots=True)
class ValidatedChannels:
    """Result of notification channel validation."""

    valid: list[NotificationChannel]
    invalid: list[str]

    @property
    def has_invalid(self) -> bool:
        """Check if any invalid channels were found."""
        return len(self.invalid) > 0


def validate_channels(channel_strings: list[str]) -> ValidatedChannels:
    """Validate and parse notification channel strings.

    Args:
        channel_strings: List of channel name strings to validate.

    Returns:
        ValidatedChannels with valid NotificationChannel enums and invalid strings.

    """
    valid: list[NotificationChannel] = []
    invalid: list[str] = []

    for channel_str in channel_strings:
        try:
            channel = NotificationChannel[channel_str.upper()]
            valid.append(channel)
        except KeyError:
            invalid.append(channel_str)

    return ValidatedChannels(valid=valid, invalid=invalid)


def raise_invalid_channels_error(invalid_channels: list[str]) -> NoReturn:
    """Raise error for invalid notification channels.

    Args:
        invalid_channels: List of invalid channel strings.

    Raises:
        NohikiError: Always raised with INVALID_REQUEST code.

    """
    raise NohikiError(
        error_code=ErrorCode.INVALID_REQUEST,
        message="Invalid notification channels specified",
        details=[
            ErrorField(field="invalid_channels", message=", ".join(invalid_channels)),
            ErrorField(field="valid_channels", message=", ".join(m.name for m in NotificationChannel)),
        ],
    )


def raise_no_channels_error(user_id: UUID, role_id: UUID) -> NoReturn:
    """Raise error when no notification channels specified.

    Args:
        user_id: User ID for error context.
        role_id: Role ID for error context.

    Raises:
        NohikiError: Always raised with INVALID_REQUEST code.

    """
    raise NohikiError(
        error_code=ErrorCode.INVALID_REQUEST,
        message="No notification channels specified",
        details=[
            ErrorField(field="user_id", message=str(user_id)),
            ErrorField(field="role_id", message=str(role_id)),
        ],
    )


def resolve_recipient_for_channel(
    channel: NotificationChannel,
    user_email: str | None,
    user_id: UUID,
) -> str:
    """Resolve recipient address for a given notification channel.

    Args:
        channel: The notification channel to resolve recipient for.
        user_email: User's email address (required for EMAIL channel).
        user_id: User ID for error context.

    Returns:
        Resolved recipient address string.

    Raises:
        NohikiError: If recipient cannot be resolved for the channel.

    """
    if channel == NotificationChannel.EMAIL:
        if not user_email:
            raise NohikiError(
                error_code=ErrorCode.INVALID_REQUEST,
                message="No recipient available for channel",
                details=[
                    ErrorField(field="channel", message=str(channel.value)),
                    ErrorField(field="user_id", message=str(user_id)),
                ],
            )
        return user_email

    raise NohikiError(
        error_code=ErrorCode.NOT_IMPLEMENTED,
        message=f"Channel {channel.value} is not yet implemented",
        details=[ErrorField(field="channel", message=str(channel.value))],
    )
