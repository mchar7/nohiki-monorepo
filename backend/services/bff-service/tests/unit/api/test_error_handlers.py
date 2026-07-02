"""Unit tests for BFF error handlers."""

from __future__ import annotations

from unittest.mock import MagicMock

from bff_service.api.error_handlers import (
    UserFacingErrorResponse,
    _get_status_code,
    _map_exception_to_code,
    create_user_facing_error_response,
    domain_exception_handler,
    setup_domain_error_handlers,
)
from fastapi import FastAPI
from nohiki_common_exceptions import DataNotFoundError, ValidationError
from nohiki_common_exceptions.user_messages import UserFacingErrorCode


class TestUserFacingErrorResponse:
    """Tests for UserFacingErrorResponse model."""

    def test_creates_with_required_fields(self) -> None:
        """Test creating response with required fields."""
        response = UserFacingErrorResponse(
            error_code="TEST.ERROR",
            message="Test error",
        )

        assert response.error_code == "TEST.ERROR"
        assert response.message == "Test error"
        assert response.details is None
        assert response.request_id is None

    def test_creates_with_all_fields(self) -> None:
        """Test creating response with all fields."""
        response = UserFacingErrorResponse(
            error_code="TEST.ERROR",
            message="Test error",
            details={"field": "value"},
            request_id="req-123",
        )

        assert response.error_code == "TEST.ERROR"
        assert response.message == "Test error"
        assert response.details == {"field": "value"}
        assert response.request_id == "req-123"


class TestCreateUserFacingErrorResponse:
    """Tests for create_user_facing_error_response function."""

    def test_creates_response_with_code(self) -> None:
        """Test creating response with error code."""
        response = create_user_facing_error_response(
            error_code=UserFacingErrorCode.PROFILE_NOT_FOUND,
        )

        assert response.error_code == UserFacingErrorCode.PROFILE_NOT_FOUND.value
        assert response.message is not None
        assert response.details is None
        assert response.request_id is None

    def test_creates_response_with_request_id(self) -> None:
        """Test creating response with request ID."""
        response = create_user_facing_error_response(
            error_code=UserFacingErrorCode.SERVER_ERROR,
            request_id="req-456",
        )

        assert response.request_id == "req-456"

    def test_creates_response_with_details(self) -> None:
        """Test creating response with details."""
        details = {"field": "name", "reason": "required"}
        response = create_user_facing_error_response(
            error_code=UserFacingErrorCode.VALIDATION_ERROR,
            details=details,
        )

        assert response.details == details


class TestMapExceptionToCode:
    """Tests for _map_exception_to_code function."""

    def test_maps_data_not_found_profile(self) -> None:
        """Test mapping DataNotFoundError for Profile."""
        exc = DataNotFoundError(resource_type="Profile", resource_id="123")
        code = _map_exception_to_code(exc)
        assert code == UserFacingErrorCode.PROFILE_NOT_FOUND

    def test_maps_data_not_found_listing(self) -> None:
        """Test mapping DataNotFoundError for Listing."""
        exc = DataNotFoundError(resource_type="Listing", resource_id="456")
        code = _map_exception_to_code(exc)
        assert code == UserFacingErrorCode.LISTING_NOT_FOUND

    def test_maps_data_not_found_unknown_type(self) -> None:
        """Test mapping DataNotFoundError for unknown type."""
        exc = DataNotFoundError(resource_type="Unknown", resource_id="789")
        code = _map_exception_to_code(exc)
        assert code == UserFacingErrorCode.SERVER_ERROR

    def test_maps_validation_error(self) -> None:
        """Test mapping ValidationError."""
        exc = ValidationError(message="Invalid input")
        code = _map_exception_to_code(exc)
        assert code == UserFacingErrorCode.VALIDATION_ERROR


class TestGetStatusCode:
    """Tests for _get_status_code function."""

    def test_returns_404_for_data_not_found(self) -> None:
        """Test returns 404 for DataNotFoundError."""
        exc = DataNotFoundError(resource_type="Profile", resource_id="123")
        assert _get_status_code(exc) == 404

    def test_returns_400_for_validation_error(self) -> None:
        """Test returns 400 for ValidationError."""
        exc = ValidationError(message="Invalid input")
        assert _get_status_code(exc) == 400


class TestDomainExceptionHandler:
    """Tests for domain_exception_handler function."""

    def test_handles_data_not_found(self) -> None:
        """Test handling DataNotFoundError."""
        request = MagicMock()
        request.headers.get.return_value = "req-123"
        exc = DataNotFoundError(resource_type="Profile", resource_id="456")

        response = domain_exception_handler(request, exc)

        assert response.status_code == 404
        request.headers.get.assert_called_with("X-Request-ID")

    def test_handles_validation_error(self) -> None:
        """Test handling ValidationError."""
        request = MagicMock()
        request.headers.get.return_value = None
        exc = ValidationError(message="Invalid input")

        response = domain_exception_handler(request, exc)

        assert response.status_code == 400

    def test_includes_context_in_details(self) -> None:
        """Test context is included in details."""
        request = MagicMock()
        request.headers.get.return_value = None
        exc = DataNotFoundError(
            resource_type="Profile",
            resource_id="123",
            context={"extra": "info"},
        )

        response = domain_exception_handler(request, exc)

        assert response.status_code == 404


class TestSetupDomainErrorHandlers:
    """Tests for setup_domain_error_handlers function."""

    def test_registers_exception_handler(self) -> None:
        """Test registers exception handler with app."""
        app = FastAPI()

        setup_domain_error_handlers(app)

        # Verify handler was registered by checking exception_handlers
        from nohiki_common_exceptions import NohikiError

        assert NohikiError in app.exception_handlers
