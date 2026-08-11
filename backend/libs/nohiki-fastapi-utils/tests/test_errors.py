"""Tests for error handling utilities."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, HTTPException, status
from fastapi.testclient import TestClient
from nohiki_fastapi_utils.errors import (
    ConflictError,
    DatabaseError,
    ErrorCode,
    ErrorField,
    ErrorResponse,
    ExternalServiceError,
    InternalError,
    NohikiError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    ValidationError,
    create_error_response,
    handle_generic_exception,
    handle_http_exception,
    handle_nohiki_error,
    handle_validation_error,
    require_field,
    setup_error_handlers,
    validate_positive_integer,
    validate_string_length,
)
from pydantic import ValidationError as PydanticValidationError


class TestErrorField:
    """Tests for ErrorField model."""

    def test_init_with_all_fields(self) -> None:
        """Test ErrorField with all fields."""
        field = ErrorField(field="name", message="Required", value="test")
        assert field.field == "name"
        assert field.message == "Required"
        assert field.value == "test"

    def test_init_without_value(self) -> None:
        """Test ErrorField without value."""
        field = ErrorField(field="email", message="Invalid format")
        assert field.field == "email"
        assert field.message == "Invalid format"
        assert field.value is None


class TestErrorResponse:
    """Tests for ErrorResponse model."""

    def test_init(self) -> None:
        """Test ErrorResponse initialization."""
        now = datetime.now(UTC)
        response = ErrorResponse(
            timestamp=now,
            status=400,
            error="VALIDATION_ERROR",
            message="Validation failed",
            path="/api/v1/users",
        )
        assert response.timestamp == now
        assert response.status == 400
        assert response.error == "VALIDATION_ERROR"
        assert response.message == "Validation failed"
        assert response.path == "/api/v1/users"
        assert response.details is None

    def test_init_with_details(self) -> None:
        """Test ErrorResponse with details."""
        details = [ErrorField(field="name", message="Required")]
        response = ErrorResponse(
            timestamp=datetime.now(UTC),
            status=422,
            error="VALIDATION_ERROR",
            message="Validation failed",
            path="/api/v1/users",
            details=details,
        )
        assert response.details is not None
        assert len(response.details) == 1


class TestErrorCode:
    """Tests for ErrorCode enum."""

    def test_validation_error_code(self) -> None:
        """Test VALIDATION_ERROR code."""
        assert ErrorCode.VALIDATION_ERROR.code == "VALIDATION_ERROR"
        assert ErrorCode.VALIDATION_ERROR.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_not_found_code(self) -> None:
        """Test NOT_FOUND code."""
        assert ErrorCode.NOT_FOUND.code == "NOT_FOUND"
        assert ErrorCode.NOT_FOUND.status_code == status.HTTP_404_NOT_FOUND

    def test_unauthorized_code(self) -> None:
        """Test UNAUTHORIZED code."""
        assert ErrorCode.UNAUTHORIZED.code == "UNAUTHORIZED"
        assert ErrorCode.UNAUTHORIZED.status_code == status.HTTP_401_UNAUTHORIZED

    def test_forbidden_code(self) -> None:
        """Test FORBIDDEN code."""
        assert ErrorCode.FORBIDDEN.code == "FORBIDDEN"
        assert ErrorCode.FORBIDDEN.status_code == status.HTTP_403_FORBIDDEN

    def test_conflict_code(self) -> None:
        """Test CONFLICT code."""
        assert ErrorCode.CONFLICT.code == "CONFLICT"
        assert ErrorCode.CONFLICT.status_code == status.HTTP_409_CONFLICT

    def test_internal_error_code(self) -> None:
        """Test INTERNAL_ERROR code."""
        assert ErrorCode.INTERNAL_ERROR.code == "INTERNAL_ERROR"
        assert ErrorCode.INTERNAL_ERROR.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

    def test_service_unavailable_code(self) -> None:
        """Test SERVICE_UNAVAILABLE code."""
        assert ErrorCode.SERVICE_UNAVAILABLE.code == "SERVICE_UNAVAILABLE"
        assert ErrorCode.SERVICE_UNAVAILABLE.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


class TestNohikiError:
    """Tests for NohikiError base exception."""

    def test_init_basic(self) -> None:
        """Test basic NohikiError initialization."""
        error = NohikiError("Test error", ErrorCode.INTERNAL_ERROR)
        assert error.message == "Test error"
        assert error.error_code == ErrorCode.INTERNAL_ERROR
        assert error.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert error.details == []
        assert error.context == {}

    def test_init_with_custom_status(self) -> None:
        """Test NohikiError with custom status code."""
        error = NohikiError("Test error", ErrorCode.INTERNAL_ERROR, status_code=502)
        assert error.status_code == 502

    def test_init_with_details(self) -> None:
        """Test NohikiError with details."""
        details = [ErrorField(field="test", message="Test message")]
        error = NohikiError("Test error", ErrorCode.VALIDATION_ERROR, details=details)
        assert error.details == details

    def test_init_with_context(self) -> None:
        """Test NohikiError with context."""
        context = {"user_id": "123"}
        error = NohikiError("Test error", ErrorCode.INTERNAL_ERROR, context=context)
        assert error.context == context


class TestValidationError:
    """Tests for ValidationError."""

    def test_default_message(self) -> None:
        """Test ValidationError with default message."""
        error = ValidationError()
        assert error.message == "Validation failed"
        assert error.error_code == ErrorCode.VALIDATION_ERROR

    def test_custom_message(self) -> None:
        """Test ValidationError with custom message."""
        error = ValidationError(message="Custom validation error")
        assert error.message == "Custom validation error"

    def test_with_details(self) -> None:
        """Test ValidationError with details."""
        details = [ErrorField(field="email", message="Invalid")]
        error = ValidationError(details=details)
        assert error.details == details


class TestNotFoundError:
    """Tests for NotFoundError."""

    def test_without_identifier(self) -> None:
        """Test NotFoundError without identifier."""
        error = NotFoundError("User")
        assert error.message == "User not found"
        assert error.error_code == ErrorCode.NOT_FOUND

    def test_with_identifier(self) -> None:
        """Test NotFoundError with identifier."""
        error = NotFoundError("User", "123")
        assert error.message == "User not found: 123"


class TestConflictError:
    """Tests for ConflictError."""

    def test_init(self) -> None:
        """Test ConflictError initialization."""
        error = ConflictError("User", "Email already exists")
        assert error.message == "User conflict: Email already exists"
        assert error.error_code == ErrorCode.CONFLICT


class TestPermissionDeniedError:
    """Tests for PermissionDeniedError."""

    def test_default_message(self) -> None:
        """Test PermissionDeniedError with default message."""
        error = PermissionDeniedError()
        assert error.message == "Permission denied"
        assert error.error_code == ErrorCode.FORBIDDEN

    def test_custom_message(self) -> None:
        """Test PermissionDeniedError with custom message."""
        error = PermissionDeniedError("You cannot access this resource")
        assert error.message == "You cannot access this resource"


class TestRateLimitError:
    """Tests for RateLimitError."""

    def test_default_message(self) -> None:
        """Test RateLimitError with default message."""
        error = RateLimitError()
        assert error.message == "Rate limit exceeded"
        assert error.error_code == ErrorCode.TOO_MANY_REQUESTS


class TestInternalError:
    """Tests for InternalError."""

    def test_default_message(self) -> None:
        """Test InternalError with default message."""
        error = InternalError()
        assert error.message == "Internal server error"
        assert error.error_code == ErrorCode.INTERNAL_ERROR


class TestDatabaseError:
    """Tests for DatabaseError."""

    def test_default_message(self) -> None:
        """Test DatabaseError with default message."""
        error = DatabaseError()
        assert error.message == "Database error"
        assert error.error_code == ErrorCode.INTERNAL_ERROR


class TestExternalServiceError:
    """Tests for ExternalServiceError."""

    def test_default_message(self) -> None:
        """Test ExternalServiceError with default message."""
        error = ExternalServiceError()
        assert error.message == "External service error"
        assert error.error_code == ErrorCode.SERVICE_UNAVAILABLE


class TestCreateErrorResponse:
    """Tests for create_error_response function."""

    def test_creates_response(self) -> None:
        """Test create_error_response creates proper response."""
        request = MagicMock()
        request.url.path = "/api/v1/test"

        response = create_error_response(
            request=request,
            status_code=400,
            error_code="INVALID_REQUEST",
            message="Bad request",
        )

        assert response.status == 400
        assert response.error == "INVALID_REQUEST"
        assert response.message == "Bad request"
        assert response.path == "/api/v1/test"
        assert response.details is None

    def test_creates_response_with_details(self) -> None:
        """Test create_error_response with details."""
        request = MagicMock()
        request.url.path = "/api/v1/test"
        details = [ErrorField(field="name", message="Required")]

        response = create_error_response(
            request=request,
            status_code=422,
            error_code="VALIDATION_ERROR",
            message="Validation failed",
            details=details,
        )

        assert response.details is not None
        assert len(response.details) == 1


class TestHandleValidationError:
    """Tests for handle_validation_error function."""

    def test_handles_pydantic_error(self) -> None:
        """Test handling Pydantic validation error."""
        from pydantic import BaseModel

        class TestModel(BaseModel):
            name: str
            age: int

        request = MagicMock()
        request.url.path = "/api/v1/test"

        try:
            TestModel(name=cast("str", 123), age=cast("int", "not_an_int"))
        except PydanticValidationError as exc:
            response = handle_validation_error(request, exc)
            assert response.status_code == 422
            body_bytes = response.body
            body = body_bytes.decode() if isinstance(body_bytes, bytes) else str(body_bytes)
            assert "VALIDATION_ERROR" in body


class TestHandleNohikiError:
    """Tests for handle_nohiki_error function."""

    def test_handles_nohiki_error(self) -> None:
        """Test handling NohikiError."""
        request = MagicMock()
        request.url.path = "/api/v1/test"

        error = NotFoundError("User", "123")
        response = handle_nohiki_error(request, error)

        assert response.status_code == 404
        body_bytes = response.body
        body = body_bytes.decode() if isinstance(body_bytes, bytes) else str(body_bytes)
        assert "NOT_FOUND" in body
        assert "User not found: 123" in body


class TestHandleHttpException:
    """Tests for handle_http_exception function."""

    def test_handles_404(self) -> None:
        """Test handling 404 HTTPException."""
        request = MagicMock()
        request.url.path = "/api/v1/test"

        exc = HTTPException(status_code=404, detail="Not found")
        response = handle_http_exception(request, exc)

        assert response.status_code == 404
        body_bytes = response.body
        body = body_bytes.decode() if isinstance(body_bytes, bytes) else str(body_bytes)
        assert "NOT_FOUND" in body

    @pytest.mark.parametrize(
        ("status_code", "error_code"),
        [(418, "INVALID_REQUEST"), (499, "INVALID_REQUEST"), (501, "INTERNAL_ERROR")],
    )
    def test_handles_unmapped_status(self, status_code: int, error_code: str) -> None:
        """Unmapped client errors are invalid requests; unmapped server errors stay internal."""
        request = MagicMock()
        request.url.path = "/api/v1/test"

        exc = HTTPException(status_code=status_code, detail="unmapped status")
        response = handle_http_exception(request, exc)

        assert response.status_code == status_code
        body_bytes = response.body
        body = body_bytes.decode() if isinstance(body_bytes, bytes) else str(body_bytes)
        assert error_code in body


class TestHandleGenericException:
    """Tests for handle_generic_exception function."""

    def test_handles_generic_exception(self) -> None:
        """Test handling generic exception."""
        request = MagicMock()
        request.url.path = "/api/v1/test"

        exc = RuntimeError("Something went wrong")
        response = handle_generic_exception(request, exc)

        assert response.status_code == 500
        body_bytes = response.body
        body = body_bytes.decode() if isinstance(body_bytes, bytes) else str(body_bytes)
        assert "INTERNAL_ERROR" in body
        assert "unexpected error" in body.lower()


class TestSetupErrorHandlers:
    """Tests for setup_error_handlers function."""

    def test_server_errors_are_redacted_with_stable_envelopes(self) -> None:
        """Every server-error source returns a stable envelope without its sensitive detail."""
        secret = "postgres://admin:super-secret@database"
        app = FastAPI()
        setup_error_handlers(app)

        @app.get("/server-error/{kind}")
        async def raise_server_error(kind: str) -> None:
            if kind == "typed":
                raise InternalError(secret)
            if kind == "http":
                raise HTTPException(status_code=503, detail=secret)
            raise RuntimeError(secret)

        cases = {
            "typed": (500, "INTERNAL_ERROR", "Internal server error"),
            "http": (503, "SERVICE_UNAVAILABLE", "Service unavailable"),
            "generic": (500, "INTERNAL_ERROR", "An unexpected error occurred"),
        }
        client = TestClient(app, raise_server_exceptions=False)

        for kind, (status_code, error_code, message) in cases.items():
            response = client.get(f"/server-error/{kind}")
            body = response.json()
            body.pop("timestamp")

            assert response.status_code == status_code
            assert body == {
                "status": status_code,
                "error": error_code,
                "message": message,
                "path": f"/server-error/{kind}",
                "details": None,
            }
            assert secret not in response.text

    def test_http_exception_headers_survive_standardization(self) -> None:
        """Authentication challenges and retry guidance survive error-envelope conversion."""
        app = FastAPI()
        setup_error_handlers(app)

        @app.get("/http-error/{kind}")
        async def raise_http_error(kind: str) -> None:
            if kind == "auth":
                raise HTTPException(
                    status_code=401,
                    detail="Authentication required",
                    headers={"WWW-Authenticate": "Bearer realm=nohiki"},
                )
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded",
                headers={"Retry-After": "17"},
            )

        cases = (
            ("auth", 401, "UNAUTHORIZED", "WWW-Authenticate", "Bearer realm=nohiki"),
            ("rate", 429, "TOO_MANY_REQUESTS", "Retry-After", "17"),
        )
        client = TestClient(app)

        for kind, status_code, error_code, header, value in cases:
            response = client.get(f"/http-error/{kind}")
            assert response.status_code == status_code
            assert response.json()["error"] == error_code
            assert response.headers[header] == value

    def test_unknown_route_uses_standard_not_found_envelope(self) -> None:
        """Starlette router misses use the same public error contract as application 404s."""
        app = FastAPI()
        setup_error_handlers(app)

        response = TestClient(app).get("/missing-route")
        body = response.json()
        body.pop("timestamp")

        assert response.status_code == 404
        assert body == {
            "status": 404,
            "error": "NOT_FOUND",
            "message": "Not Found",
            "path": "/missing-route",
            "details": None,
        }

    def test_request_validation_uses_standard_envelope_and_field_path(self) -> None:
        """FastAPI request validation identifies the rejected field in the shared envelope."""
        app = FastAPI()
        setup_error_handlers(app)

        @app.get("/items/{item_id}")
        async def get_item(item_id: int) -> dict[str, int]:
            return {"item_id": item_id}

        response = TestClient(app).get("/items/not-an-integer")
        body = response.json()
        details = body.pop("details")
        body.pop("timestamp")

        assert response.status_code == 422
        assert body == {
            "status": 422,
            "error": "VALIDATION_ERROR",
            "message": "Validation failed",
            "path": "/items/not-an-integer",
        }
        assert [detail["field"] for detail in details] == ["path -> item_id"]


class TestRequireField:
    """Tests for require_field function."""

    def test_returns_value_when_present(self) -> None:
        """Test require_field returns value when present."""
        result = require_field("test", "name")
        assert result == "test"

    def test_raises_for_none(self) -> None:
        """Test require_field raises for None."""
        with pytest.raises(ValidationError) as exc_info:
            require_field(None, "name")
        assert "name" in exc_info.value.message

    def test_raises_for_empty_string(self) -> None:
        """Test require_field raises for empty string."""
        with pytest.raises(ValidationError):
            require_field("", "name")

    def test_raises_for_whitespace_string(self) -> None:
        """Test require_field raises for whitespace-only string."""
        with pytest.raises(ValidationError):
            require_field("   ", "name")


class TestValidateStringLength:
    """Tests for validate_string_length function."""

    def test_returns_none_for_none(self) -> None:
        """Test validate_string_length returns None for None input."""
        result = validate_string_length(None, "name")
        assert result is None

    def test_returns_value_when_valid(self) -> None:
        """Test validate_string_length returns value when valid."""
        result = validate_string_length("test", "name", min_length=1, max_length=10)
        assert result == "test"

    def test_raises_for_too_short(self) -> None:
        """Test validate_string_length raises for too short string."""
        with pytest.raises(ValidationError) as exc_info:
            validate_string_length("ab", "name", min_length=3)
        assert "at least 3" in exc_info.value.message

    def test_raises_for_too_long(self) -> None:
        """Test validate_string_length raises for too long string."""
        long_string = "abcdefghijk"
        with pytest.raises(ValidationError) as exc_info:
            validate_string_length(long_string, "name", max_length=10)
        assert "at most 10" in exc_info.value.message


class TestValidatePositiveInteger:
    """Tests for validate_positive_integer function."""

    def test_returns_none_for_none(self) -> None:
        """Test validate_positive_integer returns None for None input."""
        result = validate_positive_integer(None, "count")
        assert result is None

    def test_returns_value_when_positive(self) -> None:
        """Test validate_positive_integer returns value when positive."""
        result = validate_positive_integer(5, "count")
        assert result == 5

    def test_raises_for_zero(self) -> None:
        """Test validate_positive_integer raises for zero."""
        with pytest.raises(ValidationError) as exc_info:
            validate_positive_integer(0, "count")
        assert "positive" in exc_info.value.message

    def test_raises_for_negative(self) -> None:
        """Test validate_positive_integer raises for negative."""
        with pytest.raises(ValidationError):
            validate_positive_integer(-1, "count")


class TestSetupErrorHandlersValidation:
    """Tests for setup_error_handlers PydanticValidationError handler."""

    def test_validation_error_handler_registered(self) -> None:
        """setup_error_handlers registers a PydanticValidationError handler."""
        from nohiki_fastapi_utils.errors import setup_error_handlers
        from pydantic import BaseModel as PydanticBaseModel

        class StrictInput(PydanticBaseModel):
            count: int

        app = FastAPI()
        setup_error_handlers(app)

        @app.post("/test")
        async def test_endpoint(data: StrictInput) -> dict[str, int]:
            return {"count": data.count}

        client = TestClient(app, raise_server_exceptions=False)
        response = client.post("/test", json={"count": "not_a_number"})
        assert response.status_code == 422
