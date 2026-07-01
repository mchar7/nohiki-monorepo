"""Standardized error handling for BFF API with user-facing error codes.

All errors return consistent JSON format:
{
    "error_code": "PROFILE.NOT_FOUND",
    "message": "Profile not found",
    "details": {...},
    "request_id": "abc-123"
}
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Request
from fastapi.responses import JSONResponse
from nohiki_common_exceptions import (
    DataNotFoundError,
)
from nohiki_common_exceptions import (
    NohikiError as DomainError,
)
from nohiki_common_exceptions import (
    ValidationError as DomainValidationError,
)
from nohiki_common_exceptions.user_messages import (
    DEFAULT_MESSAGES,
    UserFacingErrorCode,
)
from pydantic import BaseModel

if TYPE_CHECKING:
    from fastapi import FastAPI


class UserFacingErrorResponse(BaseModel):
    """Standardized error response format for frontend consumption."""

    error_code: str
    message: str
    details: dict | None = None
    request_id: str | None = None


def create_user_facing_error_response(
    error_code: UserFacingErrorCode,
    request_id: str | None = None,
    details: dict | None = None,
) -> UserFacingErrorResponse:
    """Create standardized error response with user-facing code."""
    return UserFacingErrorResponse(
        error_code=error_code.value,
        message=DEFAULT_MESSAGES.get(error_code, "An error occurred"),
        details=details,
        request_id=request_id,
    )


def domain_exception_handler(
    request: Request,
    exc: BaseException,
) -> JSONResponse:
    """Handle domain NohikiError exceptions with user-facing messages."""
    if not isinstance(exc, DomainError):
        msg = f"Unexpected exception type: {type(exc).__name__}"
        raise TypeError(msg)

    error_code = _map_exception_to_code(exc)
    request_id = request.headers.get("X-Request-ID")

    response = create_user_facing_error_response(
        error_code=error_code,
        request_id=request_id,
        details=exc.context or None,
    )

    status_code = _get_status_code(exc)

    return JSONResponse(
        status_code=status_code,
        content=response.model_dump(exclude_none=True),
    )


_RESOURCE_TYPE_TO_ERROR_CODE: dict[str, UserFacingErrorCode] = {
    "Profile": UserFacingErrorCode.PROFILE_NOT_FOUND,
    "Listing": UserFacingErrorCode.LISTING_NOT_FOUND,
    "Correlation": UserFacingErrorCode.CORRELATION_NOT_FOUND,
    "Attachment": UserFacingErrorCode.ATTACHMENT_NOT_FOUND,
    "Template": UserFacingErrorCode.TEMPLATE_NOT_FOUND,
}


def _map_exception_to_code(exc: DomainError) -> UserFacingErrorCode:
    """Map internal exception to user-facing error code."""
    if isinstance(exc, DataNotFoundError):
        return _RESOURCE_TYPE_TO_ERROR_CODE.get(exc.resource_type, UserFacingErrorCode.SERVER_ERROR)
    if isinstance(exc, DomainValidationError):
        return UserFacingErrorCode.VALIDATION_ERROR
    return UserFacingErrorCode.SERVER_ERROR


def _get_status_code(exc: DomainError) -> int:
    """Map exception to HTTP status code."""
    if isinstance(exc, DataNotFoundError):
        return 404
    if isinstance(exc, DomainValidationError):
        return 400
    return 500


def setup_domain_error_handlers(app: FastAPI) -> None:
    """Register domain exception handlers with FastAPI app.

    This adds handlers for nohiki_common_exceptions errors, which are
    separate from the nohiki_fastapi_utils error handlers.
    """
    app.add_exception_handler(DomainError, domain_exception_handler)
