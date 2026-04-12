"""Tests for extended JSON Schema validator."""

import pytest
from doc_template_service.core.validation._jsonschema_ext import (
    CUSTOM_KEYWORDS,
    RichValidator,
    get_cached_validator,
    get_validator,
    validate_data,
    x_error_message_validator,
    x_label_validator,
    x_order_validator,
    x_ui_type_validator,
)
from doc_template_service.schemas.models import ValidationIssue


class TestCustomKeywordValidators:
    """Tests for custom keyword no-op validators."""

    def test_x_label_validator_yields_nothing(self) -> None:
        """Test that x_label_validator is a no-op."""
        result = list(x_label_validator(None, "Label", None, {}))
        assert result == []

    def test_x_order_validator_yields_nothing(self) -> None:
        """Test that x_order_validator is a no-op."""
        result = list(x_order_validator(None, 1, None, {}))
        assert result == []

    def test_x_ui_type_validator_yields_nothing(self) -> None:
        """Test that x_ui_type_validator is a no-op."""
        result = list(x_ui_type_validator(None, "text", None, {}))
        assert result == []

    def test_x_error_message_validator_yields_nothing(self) -> None:
        """Test that x_error_message_validator is a no-op."""
        result = list(x_error_message_validator(None, "Error message", None, {}))
        assert result == []


class TestCustomKeywordsConstant:
    """Tests for CUSTOM_KEYWORDS constant."""

    def test_contains_all_custom_keywords(self) -> None:
        """Test that all custom keywords are defined."""
        assert "x-label" in CUSTOM_KEYWORDS
        assert "x-order" in CUSTOM_KEYWORDS
        assert "x-ui-type" in CUSTOM_KEYWORDS
        assert "x-errorMessage" in CUSTOM_KEYWORDS


class TestRichValidator:
    """Tests for RichValidator class."""

    def test_init_with_simple_schema(self) -> None:
        """Test initialization with a simple schema."""
        schema: dict[str, object] = {"type": "object"}
        validator = RichValidator(schema)
        assert validator.schema == schema

    def test_iter_errors_valid_data(self) -> None:
        """Test iter_errors with valid data."""
        schema: dict[str, object] = {"type": "object", "properties": {"name": {"type": "string"}}}
        validator = RichValidator(schema)
        errors = list(validator.iter_errors({"name": "test"}))
        assert errors == []

    def test_iter_errors_invalid_data(self) -> None:
        """Test iter_errors with invalid data."""
        schema: dict[str, object] = {"type": "object", "properties": {"name": {"type": "string"}}}
        validator = RichValidator(schema)
        errors = list(validator.iter_errors({"name": 123}))
        assert len(errors) == 1
        assert "type" in str(errors[0].validator)

    def test_validate_valid_data(self) -> None:
        """Test validate with valid data does not raise."""
        schema: dict[str, object] = {"type": "string"}
        validator = RichValidator(schema)
        validator.validate("test")  # Should not raise

    def test_validate_invalid_data_raises(self) -> None:
        """Test validate with invalid data raises ValidationError."""
        from jsonschema.exceptions import ValidationError

        schema: dict[str, object] = {"type": "string"}
        validator = RichValidator(schema)
        with pytest.raises(ValidationError):
            validator.validate(123)

    def test_is_valid_returns_true_for_valid_data(self) -> None:
        """Test is_valid returns True for valid data."""
        schema: dict[str, object] = {"type": "number"}
        validator = RichValidator(schema)
        assert validator.is_valid(42) is True

    def test_is_valid_returns_false_for_invalid_data(self) -> None:
        """Test is_valid returns False for invalid data."""
        schema: dict[str, object] = {"type": "number"}
        validator = RichValidator(schema)
        assert validator.is_valid("not a number") is False

    def test_iter_errors_with_paths_returns_paths(self) -> None:
        """Test iter_errors_with_paths returns errors with paths."""
        schema: dict[str, object] = {
            "type": "object",
            "properties": {"nested": {"type": "object", "properties": {"value": {"type": "number"}}}},
        }
        validator = RichValidator(schema)
        errors = validator.iter_errors_with_paths({"nested": {"value": "not a number"}})
        assert len(errors) == 1
        path, _error = errors[0]
        assert "nested" in path or "value" in path

    def test_iter_errors_with_paths_array_index(self) -> None:
        """Test iter_errors_with_paths handles array indices."""
        schema: dict[str, object] = {"type": "array", "items": {"type": "number"}}
        validator = RichValidator(schema)
        errors = validator.iter_errors_with_paths([1, 2, "three", 4])
        assert len(errors) == 1
        path, _error = errors[0]
        assert 2 in path  # Index of invalid item

    def test_create_validation_issues_returns_issues(self) -> None:
        """Test create_validation_issues returns ValidationIssue list."""
        schema: dict[str, object] = {
            "type": "object",
            "required": ["name"],
            "properties": {"name": {"type": "string"}},
        }
        validator = RichValidator(schema)
        issues = validator.create_validation_issues({})
        assert len(issues) == 1
        assert isinstance(issues[0], ValidationIssue)
        assert "required" in issues[0].keyword

    def test_create_validation_issues_empty_for_valid_data(self) -> None:
        """Test create_validation_issues returns empty list for valid data."""
        schema: dict[str, object] = {"type": "object"}
        validator = RichValidator(schema)
        issues = validator.create_validation_issues({})
        assert issues == []

    def test_custom_keywords_do_not_cause_errors(self) -> None:
        """Test that custom x- keywords don't cause validation errors."""
        schema: dict[str, object] = {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "x-label": "Full Name",
                    "x-order": 1,
                    "x-ui-type": "text",
                    "x-errorMessage": "Please enter your name",
                }
            },
        }
        validator = RichValidator(schema)
        assert validator.is_valid({"name": "John"}) is True
        issues = validator.create_validation_issues({"name": "John"})
        assert issues == []


class TestGetCachedValidator:
    """Tests for get_cached_validator function."""

    @pytest.mark.asyncio
    async def test_returns_validator(self) -> None:
        """Test that function returns a RichValidator."""
        schema_str = '{"type": "object"}'
        validator = await get_cached_validator(schema_str)
        assert isinstance(validator, RichValidator)

    @pytest.mark.asyncio
    async def test_caches_validator(self) -> None:
        """Test that same schema returns cached validator."""
        schema_str = '{"type": "string"}'
        validator1 = await get_cached_validator(schema_str)
        validator2 = await get_cached_validator(schema_str)
        assert validator1 is validator2


class TestGetValidator:
    """Tests for get_validator function."""

    def test_returns_validator_from_dict(self) -> None:
        """Test that function returns validator from dict schema."""
        schema: dict[str, object] = {"type": "array"}
        validator = get_validator(schema)
        assert isinstance(validator, RichValidator)

    def test_caches_equivalent_schemas(self) -> None:
        """Test that equivalent schemas return same cached validator."""
        schema1: dict[str, object] = {"type": "object", "properties": {"a": {"type": "string"}}}
        schema2: dict[str, object] = {"properties": {"a": {"type": "string"}}, "type": "object"}
        validator1 = get_validator(schema1)
        validator2 = get_validator(schema2)
        # Same schema (sorted keys), should be same cached instance
        assert validator1 is validator2


class TestValidateData:
    """Tests for validate_data function."""

    def test_returns_empty_for_valid_data(self) -> None:
        """Test that valid data returns empty issues list."""
        schema: dict[str, object] = {"type": "object"}
        issues = validate_data(schema, {})
        assert issues == []

    def test_returns_issues_for_invalid_data(self) -> None:
        """Test that invalid data returns issues list."""
        schema: dict[str, object] = {"type": "string"}
        issues = validate_data(schema, 123)
        assert len(issues) == 1
        assert isinstance(issues[0], ValidationIssue)

    def test_validates_required_fields(self) -> None:
        """Test validation of required fields."""
        schema: dict[str, object] = {
            "type": "object",
            "required": ["email", "name"],
            "properties": {"email": {"type": "string"}, "name": {"type": "string"}},
        }
        issues = validate_data(schema, {"email": "test@example.com"})
        assert len(issues) == 1
        assert "required" in issues[0].keyword
