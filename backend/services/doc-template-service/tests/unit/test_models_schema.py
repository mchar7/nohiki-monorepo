"""Tests for core model schemas."""

import pytest
from doc_template_service.schemas.models import (
    ALLOWED_IMAGE_FORMATS,
    ALLOWED_OUTPUT_FORMATS,
    GenerateRequest,
    ImageOptions,
    ValidationIssue,
    ValidationReport,
)
from pydantic import ValidationError


class TestValidationIssue:
    """Tests for ValidationIssue model."""

    def test_valid_issue(self) -> None:
        """Test creating a valid validation issue."""
        issue = ValidationIssue(
            path="$.name",
            keyword="type",
            message="Expected string, got integer",
        )
        assert issue.path == "$.name"
        assert issue.keyword == "type"
        assert issue.message == "Expected string, got integer"

    def test_missing_path_raises_error(self) -> None:
        """Test that missing path raises validation error."""
        with pytest.raises(ValidationError) as exc_info:
            ValidationIssue(keyword="type", message="Error")
        assert "path" in str(exc_info.value)

    def test_missing_keyword_raises_error(self) -> None:
        """Test that missing keyword raises validation error."""
        with pytest.raises(ValidationError) as exc_info:
            ValidationIssue(path="$.name", message="Error")
        assert "keyword" in str(exc_info.value)

    def test_missing_message_raises_error(self) -> None:
        """Test that missing message raises validation error."""
        with pytest.raises(ValidationError) as exc_info:
            ValidationIssue(path="$.name", keyword="type")
        assert "message" in str(exc_info.value)


class TestValidationReport:
    """Tests for ValidationReport model."""

    def test_valid_report_success(self) -> None:
        """Test creating a valid success report."""
        report = ValidationReport(valid=True)
        assert report.valid is True
        assert report.issues == []
        assert report.summary is None

    def test_valid_report_with_issues(self) -> None:
        """Test creating a report with issues."""
        issues = [
            ValidationIssue(path="$.name", keyword="required", message="Field required"),
            ValidationIssue(path="$.age", keyword="type", message="Invalid type"),
        ]
        report = ValidationReport(valid=False, issues=issues)
        assert report.valid is False
        assert len(report.issues) == 2

    def test_valid_report_with_summary(self) -> None:
        """Test creating a report with summary."""
        report = ValidationReport(
            valid=False,
            issues=[],
            summary={"required": 2, "type": 1},
        )
        assert report.summary == {"required": 2, "type": 1}

    def test_missing_valid_raises_error(self) -> None:
        """Test that missing valid field raises validation error."""
        with pytest.raises(ValidationError) as exc_info:
            ValidationReport()
        assert "valid" in str(exc_info.value)


class TestImageOptions:
    """Tests for ImageOptions model."""

    def test_valid_png_options(self) -> None:
        """Test creating valid PNG options."""
        options = ImageOptions(format="png")
        assert options.format == "png"
        assert options.width == 800
        assert options.height == 600
        assert options.quality == 90

    def test_valid_jpeg_options(self) -> None:
        """Test creating valid JPEG options."""
        options = ImageOptions(format="jpeg", width=1920, height=1080, quality=85)
        assert options.format == "jpeg"
        assert options.width == 1920
        assert options.height == 1080
        assert options.quality == 85

    def test_valid_webp_options(self) -> None:
        """Test creating valid WebP options."""
        options = ImageOptions(format="webp", width=1024, height=768)
        assert options.format == "webp"

    def test_invalid_format_raises_error(self) -> None:
        """Test that invalid format raises validation error."""
        with pytest.raises(ValidationError) as exc_info:
            ImageOptions.model_validate({"format": "gif"})
        assert "Format must be one of" in str(exc_info.value)

    def test_width_below_minimum_raises_error(self) -> None:
        """Test that width below minimum raises validation error."""
        with pytest.raises(ValidationError) as exc_info:
            ImageOptions(format="png", width=0)
        assert "Dimensions must be between" in str(exc_info.value)

    def test_width_above_maximum_raises_error(self) -> None:
        """Test that width above maximum raises validation error."""
        with pytest.raises(ValidationError) as exc_info:
            ImageOptions(format="png", width=5000)
        assert "Dimensions must be between" in str(exc_info.value)

    def test_height_below_minimum_raises_error(self) -> None:
        """Test that height below minimum raises validation error."""
        with pytest.raises(ValidationError) as exc_info:
            ImageOptions(format="png", height=0)
        assert "Dimensions must be between" in str(exc_info.value)

    def test_height_above_maximum_raises_error(self) -> None:
        """Test that height above maximum raises validation error."""
        with pytest.raises(ValidationError) as exc_info:
            ImageOptions(format="png", height=5000)
        assert "Dimensions must be between" in str(exc_info.value)

    def test_quality_below_minimum_raises_error(self) -> None:
        """Test that quality below minimum raises validation error."""
        with pytest.raises(ValidationError) as exc_info:
            ImageOptions(format="png", quality=0)
        assert "Quality must be between" in str(exc_info.value)

    def test_quality_above_maximum_raises_error(self) -> None:
        """Test that quality above maximum raises validation error."""
        with pytest.raises(ValidationError) as exc_info:
            ImageOptions(format="png", quality=101)
        assert "Quality must be between" in str(exc_info.value)

    def test_boundary_values_are_valid(self) -> None:
        """Test that boundary values are valid."""
        options = ImageOptions(format="png", width=1, height=1, quality=1)
        assert options.width == 1
        assert options.height == 1
        assert options.quality == 1

        options = ImageOptions(format="png", width=4096, height=4096, quality=100)
        assert options.width == 4096
        assert options.height == 4096
        assert options.quality == 100


class TestGenerateRequest:
    """Tests for GenerateRequest model."""

    def test_valid_request_minimal(self) -> None:
        """Test creating a minimal valid request."""
        request = GenerateRequest(
            template="<html>{{ name }}</html>",
            data={"name": "Test"},
        )
        assert request.template == "<html>{{ name }}</html>"
        assert request.data == {"name": "Test"}
        assert request.output_format == "pdf"
        assert request.schema_id is None
        assert request.schema_version is None
        assert request.image_options is None

    def test_valid_request_with_all_fields(self) -> None:
        """Test creating a request with all fields."""
        image_options = ImageOptions(format="png", width=1920, height=1080)
        request = GenerateRequest(
            template="<html>{{ name }}</html>",
            data={"name": "Test"},
            output_format="png",
            schema_id="test-schema",
            schema_version=1,
            image_options=image_options,
        )
        assert request.output_format == "png"
        assert request.schema_id == "test-schema"
        assert request.schema_version == 1
        assert request.image_options is not None

    def test_all_output_formats_are_valid(self) -> None:
        """Test that all allowed output formats are valid."""
        for fmt in ALLOWED_OUTPUT_FORMATS:
            request = GenerateRequest.model_validate(
                {
                    "template": "<html></html>",
                    "data": {},
                    "output_format": fmt,
                }
            )
            assert request.output_format == fmt

    def test_invalid_output_format_raises_error(self) -> None:
        """Test that invalid output format raises validation error."""
        with pytest.raises(ValidationError) as exc_info:
            GenerateRequest.model_validate(
                {
                    "template": "<html></html>",
                    "data": {},
                    "output_format": "txt",
                }
            )
        assert "Output format must be one of" in str(exc_info.value)

    def test_missing_template_raises_error(self) -> None:
        """Test that missing template raises validation error."""
        with pytest.raises(ValidationError) as exc_info:
            GenerateRequest(data={"name": "Test"})
        assert "template" in str(exc_info.value)

    def test_missing_data_raises_error(self) -> None:
        """Test that missing data raises validation error."""
        with pytest.raises(ValidationError) as exc_info:
            GenerateRequest(template="<html></html>")
        assert "data" in str(exc_info.value)

    def test_complex_data_structure(self) -> None:
        """Test request with complex data structure."""
        data: dict[str, object] = {
            "user": {
                "name": "John",
                "address": {
                    "city": "NYC",
                    "zip": "10001",
                },
            },
            "items": [
                {"id": 1, "name": "Item 1"},
                {"id": 2, "name": "Item 2"},
            ],
        }
        request = GenerateRequest(
            template="<html>{{ user.name }}</html>",
            data=data,
        )
        assert request.data == data


class TestConstants:
    """Tests for module-level constants."""

    def test_allowed_image_formats(self) -> None:
        """Test ALLOWED_IMAGE_FORMATS constant."""
        assert "png" in ALLOWED_IMAGE_FORMATS
        assert "jpeg" in ALLOWED_IMAGE_FORMATS
        assert "webp" in ALLOWED_IMAGE_FORMATS
        assert len(ALLOWED_IMAGE_FORMATS) == 3

    def test_allowed_output_formats(self) -> None:
        """Test ALLOWED_OUTPUT_FORMATS constant."""
        assert "pdf" in ALLOWED_OUTPUT_FORMATS
        assert "html" in ALLOWED_OUTPUT_FORMATS
        assert "png" in ALLOWED_OUTPUT_FORMATS
        assert "jpeg" in ALLOWED_OUTPUT_FORMATS
        assert "webp" in ALLOWED_OUTPUT_FORMATS
        assert len(ALLOWED_OUTPUT_FORMATS) == 5
