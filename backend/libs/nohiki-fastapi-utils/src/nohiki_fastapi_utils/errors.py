"""error handling utilities for Nohiki services."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Self

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from nohiki_observability import get_logger
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = get_logger(__name__)


class ErrorField(BaseModel):
    """Field-specific validation error."""

    field: str
    message: str
    value: str | None = None


class ErrorResponse(BaseModel):
    """Standardized error response."""

    timestamp: datetime
    status: int
    error: str
    message: str
    path: str
    details: list[ErrorField] | None = None


class ErrorCode(StrEnum):
    """Standardized error codes across all services, mapping to HTTP status codes."""

    # Client errors (4xx)
    VALIDATION_ERROR = ("VALIDATION_ERROR", status.HTTP_422_UNPROCESSABLE_CONTENT)
    INVALID_REQUEST = ("INVALID_REQUEST", status.HTTP_400_BAD_REQUEST)
    UNAUTHORIZED = ("UNAUTHORIZED", status.HTTP_401_UNAUTHORIZED)
    FORBIDDEN = ("FORBIDDEN", status.HTTP_403_FORBIDDEN)
    NOT_FOUND = ("NOT_FOUND", status.HTTP_404_NOT_FOUND)
    CONFLICT = ("CONFLICT", status.HTTP_409_CONFLICT)
    UNPROCESSABLE_ENTITY = ("UNPROCESSABLE_ENTITY", status.HTTP_422_UNPROCESSABLE_CONTENT)
    TOO_MANY_REQUESTS = ("TOO_MANY_REQUESTS", status.HTTP_429_TOO_MANY_REQUESTS)

    # Server errors (5xx)
    INTERNAL_ERROR = ("INTERNAL_ERROR", status.HTTP_500_INTERNAL_SERVER_ERROR)
    DATABASE_ERROR = ("DATABASE_ERROR", status.HTTP_500_INTERNAL_SERVER_ERROR)
    NOT_IMPLEMENTED = ("NOT_IMPLEMENTED", status.HTTP_501_NOT_IMPLEMENTED)
    SERVICE_UNAVAILABLE = ("SERVICE_UNAVAILABLE", status.HTTP_503_SERVICE_UNAVAILABLE)
    GATEWAY_TIMEOUT = ("GATEWAY_TIMEOUT", status.HTTP_504_GATEWAY_TIMEOUT)

    status_code: int

    def __new__(cls, code: str, status_code: int) -> Self:
        """Create a new ErrorCode instance."""
        obj = str.__new__(cls, code)
        obj._value_ = code
        obj.status_code = status_code
        return obj

    @property
    def code(self) -> str:
        """Get the error code string."""
        return str(self._value_)


class NohikiError(Exception):
    """Base exception class for all Nohiki service errors."""

    def __init__(
        self,
        message: str,
        error_code: ErrorCode,
        status_code: int | None = None,
        details: list[ErrorField] | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Initialize a NohikiError instance."""
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.status_code = status_code or error_code.status_code
        self.details = details or []
        self.context = context or {}


class ValidationError(NohikiError):
    """Exception for validation errors."""

    def __init__(
        self,
        message: str = "Validation failed",
        details: list[ErrorField] | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Initialize a ValidationError instance."""
        super().__init__(
            message=message,
            error_code=ErrorCode.VALIDATION_ERROR,
            details=details,
            context=context,
        )


class NotFoundError(NohikiError):
    """Exception for resource not found errors."""

    def __init__(
        self,
        resource: str,
        identifier: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Initialize a NotFoundError instance."""
        message = f"{resource} not found" if not identifier else f"{resource} not found: {identifier}"
        super().__init__(
            message=message,
            error_code=ErrorCode.NOT_FOUND,
            context=context,
        )


class ConflictError(NohikiError):
    """Exception for resource conflict errors."""

    def __init__(
        self,
        resource: str,
        reason: str,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Initialize a ConflictError instance."""
        message = f"{resource} conflict: {reason}"
        super().__init__(
            message=message,
            error_code=ErrorCode.CONFLICT,
            context=context,
        )


class PermissionDeniedError(NohikiError):
    """Exception for permission denied errors."""

    def __init__(
        self,
        message: str = "Permission denied",
        context: dict[str, Any] | None = None,
    ) -> None:
        """Initialize a PermissionDeniedError instance."""
        super().__init__(
            message=message,
            error_code=ErrorCode.FORBIDDEN,
            context=context,
        )


class RateLimitError(NohikiError):
    """Exception for rate limit exceeded errors."""

    def __init__(
        self,
        message: str = "Rate limit exceeded",
        context: dict[str, Any] | None = None,
    ) -> None:
        """Initialize a RateLimitError instance."""
        super().__init__(
            message=message,
            error_code=ErrorCode.TOO_MANY_REQUESTS,
            context=context,
        )


class InternalError(NohikiError):
    """Exception for internal server errors."""

    def __init__(
        self,
        message: str = "Internal server error",
        context: dict[str, Any] | None = None,
    ) -> None:
        """Initialize an InternalError instance."""
        super().__init__(
            message=message,
            error_code=ErrorCode.INTERNAL_ERROR,
            context=context,
        )


class DatabaseError(NohikiError):
    """Exception for database errors."""

    def __init__(
        self,
        message: str = "Database error",
        context: dict[str, Any] | None = None,
    ) -> None:
        """Initialize a DatabaseError instance."""
        super().__init__(
            message=message,
            error_code=ErrorCode.INTERNAL_ERROR,
            context=context,
        )


class ExternalServiceError(NohikiError):
    """Exception for external service errors."""

    def __init__(
        self,
        message: str = "External service error",
        context: dict[str, Any] | None = None,
    ) -> None:
        """Initialize an ExternalServiceError instance."""
        super().__init__(
            message=message,
            error_code=ErrorCode.SERVICE_UNAVAILABLE,
            context=context,
        )


def create_error_response(
    request: Request, status_code: int, error_code: str, message: str, details: list[ErrorField] | None = None
) -> ErrorResponse:
    """Create a standardized error response."""
    return ErrorResponse(
        timestamp=datetime.now(UTC),
        status=status_code,
        error=error_code,
        message=message,
        path=str(request.url.path),
        details=details,
    )


def handle_validation_error(
    request: Request,
    exc: PydanticValidationError | RequestValidationError,
) -> JSONResponse:
    """Handle request and Pydantic validation errors."""
    details = []
    for error in exc.errors():
        field_path = " -> ".join(str(loc) for loc in error["loc"])
        details.append(ErrorField(field=field_path, message=error["msg"]))

    error_response = create_error_response(
        request=request,
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        error_code=ErrorCode.VALIDATION_ERROR.code,
        message="Validation failed",
        details=details,
    )

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content=jsonable_encoder(error_response),
    )


def handle_nohiki_error(request: Request, exc: NohikiError) -> JSONResponse:
    """Handle custom Nohiki service errors without disclosing server internals."""
    is_server_error = exc.status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR
    if is_server_error:
        logger.error(
            "Service error",
            error_code=exc.error_code.code,
            status_code=exc.status_code,
            error=exc.message,
            context=exc.context,
        )

    error_response = create_error_response(
        request=request,
        status_code=exc.status_code,
        error_code=exc.error_code.code,
        message="Service unavailable"
        if exc.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        else "Internal server error"
        if is_server_error
        else exc.message,
        details=None if is_server_error else exc.details,
    )

    return JSONResponse(
        status_code=exc.status_code,
        content=jsonable_encoder(error_response),
    )


def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Handle FastAPI and Starlette HTTP exceptions."""
    # Map HTTP status codes to our error codes
    error_code_mapping = {
        status.HTTP_400_BAD_REQUEST: ErrorCode.INVALID_REQUEST,
        status.HTTP_401_UNAUTHORIZED: ErrorCode.UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN: ErrorCode.FORBIDDEN,
        status.HTTP_404_NOT_FOUND: ErrorCode.NOT_FOUND,
        status.HTTP_409_CONFLICT: ErrorCode.CONFLICT,
        status.HTTP_422_UNPROCESSABLE_CONTENT: ErrorCode.VALIDATION_ERROR,
        status.HTTP_429_TOO_MANY_REQUESTS: ErrorCode.TOO_MANY_REQUESTS,
        status.HTTP_500_INTERNAL_SERVER_ERROR: ErrorCode.INTERNAL_ERROR,
        status.HTTP_503_SERVICE_UNAVAILABLE: ErrorCode.SERVICE_UNAVAILABLE,
        status.HTTP_504_GATEWAY_TIMEOUT: ErrorCode.GATEWAY_TIMEOUT,
    }

    error_code = error_code_mapping.get(exc.status_code)
    if error_code is None:
        error_code = (
            ErrorCode.INVALID_REQUEST
            if status.HTTP_400_BAD_REQUEST <= exc.status_code < status.HTTP_500_INTERNAL_SERVER_ERROR
            else ErrorCode.INTERNAL_ERROR
        )

    is_server_error = exc.status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR
    if is_server_error:
        logger.error("HTTP server error", status_code=exc.status_code, detail=exc.detail)

    error_response = create_error_response(
        request=request,
        status_code=exc.status_code,
        error_code=error_code.code,
        message="Service unavailable"
        if exc.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        else "Internal server error"
        if is_server_error
        else str(exc.detail),
    )

    return JSONResponse(
        status_code=exc.status_code,
        content=jsonable_encoder(error_response),
        headers=exc.headers,
    )


def handle_generic_exception(request: Request, exc: Exception) -> JSONResponse:
    """Handle unexpected exceptions."""
    logger.exception("Unexpected error", error=str(exc))

    error_response = create_error_response(
        request=request,
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        error_code=ErrorCode.INTERNAL_ERROR.code,
        message="An unexpected error occurred",
    )

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=jsonable_encoder(error_response),
    )


def setup_error_handlers(app: FastAPI) -> None:
    """Set up global error handlers for the FastAPI application."""

    @app.exception_handler(RequestValidationError)
    async def request_validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return handle_validation_error(request, exc)

    @app.exception_handler(PydanticValidationError)
    async def validation_error_handler(request: Request, exc: PydanticValidationError) -> JSONResponse:
        return handle_validation_error(request, exc)

    @app.exception_handler(NohikiError)
    async def nohiki_error_handler(request: Request, exc: NohikiError) -> JSONResponse:
        return handle_nohiki_error(request, exc)

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return handle_http_exception(request, exc)

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        return handle_generic_exception(request, exc)


def require_field[T](value: T, field_name: str) -> T:
    """Enforce required fields with detailed error messages."""
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValidationError(
            message=f"Field '{field_name}' is required",
            details=[ErrorField(field=field_name, message="Field is required")],
        )
    return value


def validate_string_length(
    value: str | None,
    field_name: str,
    min_length: int | None = None,
    max_length: int | None = None,
) -> str | None:
    """Validate string length with detailed error messages."""
    if value is not None:
        if min_length is not None and len(value) < min_length:
            raise ValidationError(
                message=f"Field '{field_name}' must be at least {min_length} characters long",
                details=[
                    ErrorField(
                        field=field_name,
                        message=f"Must be at least {min_length} characters long",
                        value=value,
                    )
                ],
            )

        if max_length is not None and len(value) > max_length:
            raise ValidationError(
                message=f"Field '{field_name}' must be at most {max_length} characters long",
                details=[
                    ErrorField(
                        field=field_name,
                        message=f"Must be at most {max_length} characters long",
                        value=value,
                    )
                ],
            )
    return value


def validate_positive_integer(value: int | None, field_name: str) -> int | None:
    """Validate that an integer is positive."""
    if value is not None and value <= 0:
        raise ValidationError(
            message=f"Field '{field_name}' must be a positive integer",
            details=[
                ErrorField(
                    field=field_name,
                    message="Must be a positive integer",
                    value=str(value),
                )
            ],
        )
    return value
