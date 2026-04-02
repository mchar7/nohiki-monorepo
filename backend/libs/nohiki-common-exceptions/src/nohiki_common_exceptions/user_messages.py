"""User-facing error codes and messages.

These codes are returned to the frontend for i18n mapping.
The frontend has corresponding ErrorMessages constants.
"""

from __future__ import annotations

from enum import StrEnum


class UserFacingErrorCode(StrEnum):
    """Error codes returned to frontend."""

    # Auth
    INVALID_CREDENTIALS = "AUTH.INVALID_CREDENTIALS"
    SESSION_EXPIRED = "AUTH.SESSION_EXPIRED"
    UNAUTHORIZED = "AUTH.UNAUTHORIZED"
    EMAIL_IN_USE = "AUTH.EMAIL_IN_USE"

    # Profile
    PROFILE_NOT_FOUND = "PROFILE.NOT_FOUND"
    PROFILE_DUPLICATE_NAME = "PROFILE.DUPLICATE_NAME"
    PROFILE_MAX_REACHED = "PROFILE.MAX_PROFILES_REACHED"

    # Attachment
    ATTACHMENT_NOT_FOUND = "ATTACHMENT.NOT_FOUND"
    FILE_TOO_LARGE = "ATTACHMENT.FILE_TOO_LARGE"
    INVALID_FILE_TYPE = "ATTACHMENT.INVALID_TYPE"

    # Listing
    LISTING_NOT_FOUND = "LISTING.NOT_FOUND"

    # Correlation
    CORRELATION_NOT_FOUND = "CORRELATION.NOT_FOUND"

    # Document
    TEMPLATE_NOT_FOUND = "DOCUMENT.TEMPLATE_NOT_FOUND"
    GENERATION_FAILED = "DOCUMENT.GENERATION_FAILED"

    # Generic
    VALIDATION_ERROR = "VALIDATION.ERROR"
    SERVER_ERROR = "NETWORK.SERVER_ERROR"


DEFAULT_MESSAGES: dict[UserFacingErrorCode, str] = {
    UserFacingErrorCode.INVALID_CREDENTIALS: "Invalid email or password",
    UserFacingErrorCode.SESSION_EXPIRED: "Your session has expired",
    UserFacingErrorCode.UNAUTHORIZED: "Authentication required",
    UserFacingErrorCode.EMAIL_IN_USE: "Email already registered",
    UserFacingErrorCode.PROFILE_NOT_FOUND: "Profile not found",
    UserFacingErrorCode.PROFILE_DUPLICATE_NAME: "Profile name already exists",
    UserFacingErrorCode.PROFILE_MAX_REACHED: "Maximum profiles reached",
    UserFacingErrorCode.ATTACHMENT_NOT_FOUND: "Attachment not found",
    UserFacingErrorCode.FILE_TOO_LARGE: "File too large",
    UserFacingErrorCode.INVALID_FILE_TYPE: "Invalid file type",
    UserFacingErrorCode.LISTING_NOT_FOUND: "Job listing not found",
    UserFacingErrorCode.CORRELATION_NOT_FOUND: "Match not found",
    UserFacingErrorCode.TEMPLATE_NOT_FOUND: "Template not found",
    UserFacingErrorCode.GENERATION_FAILED: "Document generation failed",
    UserFacingErrorCode.VALIDATION_ERROR: "Validation error",
    UserFacingErrorCode.SERVER_ERROR: "Server error",
}


def get_default_message(code: UserFacingErrorCode) -> str:
    """Get default English message for error code."""
    return DEFAULT_MESSAGES.get(code, "An error occurred")
