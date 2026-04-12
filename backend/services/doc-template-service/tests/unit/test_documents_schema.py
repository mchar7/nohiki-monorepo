"""Tests for document-related Pydantic schemas."""

from uuid import UUID

import pytest
from doc_template_service.schemas.documents import (
    GenerateRequest,
    GenerateResponse,
    ValidationRequest,
    ValidationResponse,
)
from pydantic import ValidationError


class TestGenerateRequest:
    """Tests for GenerateRequest schema."""

    def test_valid_request_with_required_fields(self) -> None:
        """Test valid request with only required fields."""
        request = GenerateRequest(
            template_version_id=UUID("11111111-1111-1111-1111-111111111111"),
            data={"name": "Test"},
        )
        assert request.template_version_id == UUID("11111111-1111-1111-1111-111111111111")
        assert request.data == {"name": "Test"}
        assert request.output_format == "pdf"
        assert request.schema_id is None
        assert request.include_text_alternative is False

    def test_valid_request_with_all_fields(self) -> None:
        """Test valid request with all fields."""
        request = GenerateRequest(
            template_version_id=UUID("11111111-1111-1111-1111-111111111111"),
            data={"name": "Test", "items": [1, 2, 3]},
            output_format="html",
            schema_id=UUID("22222222-2222-2222-2222-222222222222"),
            include_text_alternative=True,
        )
        assert request.output_format == "html"
        assert request.schema_id == UUID("22222222-2222-2222-2222-222222222222")
        assert request.include_text_alternative is True

    def test_missing_required_template_version_id_raises_error(self) -> None:
        """Test that missing template_version_id raises validation error."""
        with pytest.raises(ValidationError) as exc_info:
            GenerateRequest(data={"name": "Test"})
        assert "template_version_id" in str(exc_info.value)

    def test_missing_required_data_raises_error(self) -> None:
        """Test that missing data raises validation error."""
        with pytest.raises(ValidationError) as exc_info:
            GenerateRequest(template_version_id=UUID("11111111-1111-1111-1111-111111111111"))
        assert "data" in str(exc_info.value)

    def test_empty_data_dict_is_valid(self) -> None:
        """Test that empty data dict is valid."""
        request = GenerateRequest(
            template_version_id=UUID("11111111-1111-1111-1111-111111111111"),
            data={},
        )
        assert request.data == {}


class TestGenerateResponse:
    """Tests for GenerateResponse schema."""

    def test_valid_response_with_required_fields(self) -> None:
        """Test valid response with required fields."""
        response = GenerateResponse(
            content=b"PDF content",
            template_version_id=UUID("11111111-1111-1111-1111-111111111111"),
            template_name="test-template",
            template_version="1.0.0",
        )
        assert response.content == b"PDF content"
        assert response.text_alt is None

    def test_valid_response_with_text_alternative(self) -> None:
        """Test valid response with text alternative."""
        response = GenerateResponse(
            content=b"PDF content",
            text_alt="Plain text version",
            template_version_id=UUID("11111111-1111-1111-1111-111111111111"),
            template_name="test-template",
            template_version="1.0.0",
        )
        assert response.text_alt == "Plain text version"

    def test_missing_content_raises_error(self) -> None:
        """Test that missing content raises validation error."""
        with pytest.raises(ValidationError) as exc_info:
            GenerateResponse(
                template_version_id=UUID("11111111-1111-1111-1111-111111111111"),
                template_name="test-template",
                template_version="1.0.0",
            )
        assert "content" in str(exc_info.value)


class TestValidationRequest:
    """Tests for ValidationRequest schema."""

    def test_valid_request_with_data_only(self) -> None:
        """Test valid request with only data."""
        request = ValidationRequest(data={"name": "Test"})
        assert request.data == {"name": "Test"}
        assert request.schema_id is None

    def test_valid_request_with_schema_id(self) -> None:
        """Test valid request with schema_id."""
        request = ValidationRequest(
            data={"name": "Test"},
            schema_id=UUID("11111111-1111-1111-1111-111111111111"),
        )
        assert request.schema_id == UUID("11111111-1111-1111-1111-111111111111")

    def test_missing_data_raises_error(self) -> None:
        """Test that missing data raises validation error."""
        with pytest.raises(ValidationError) as exc_info:
            ValidationRequest()
        assert "data" in str(exc_info.value)


class TestValidationResponse:
    """Tests for ValidationResponse schema."""

    def test_valid_response_success(self) -> None:
        """Test valid success response."""
        response = ValidationResponse(is_valid=True)
        assert response.is_valid is True
        assert response.errors == []
        assert response.warnings == []

    def test_valid_response_with_errors(self) -> None:
        """Test valid response with errors."""
        response = ValidationResponse(
            is_valid=False,
            errors=["Missing required field: name", "Invalid type for age"],
        )
        assert response.is_valid is False
        assert len(response.errors) == 2

    def test_valid_response_with_warnings(self) -> None:
        """Test valid response with warnings."""
        response = ValidationResponse(
            is_valid=True,
            warnings=["Field 'extra' is not in schema"],
        )
        assert response.is_valid is True
        assert len(response.warnings) == 1

    def test_missing_is_valid_raises_error(self) -> None:
        """Test that missing is_valid raises validation error."""
        with pytest.raises(ValidationError) as exc_info:
            ValidationResponse()
        assert "is_valid" in str(exc_info.value)
