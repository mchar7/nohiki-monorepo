"""Tests for validation exceptions."""

from nohiki_common_exceptions import (
    ErrorSeverity,
    RetryStrategy,
    SchemaVersionMismatchError,
    ValidationError,
)


class TestValidationError:
    """Tests for ValidationError."""

    def test_auto_generates_message(self) -> None:
        """Test message is auto-generated from field details."""
        error = ValidationError(
            field_name="email",
            invalid_value="not-an-email",
            constraint="must be a valid email address",
        )

        assert str(error) == "Validation failed for 'email': must be a valid email address"

    def test_custom_message_preserved(self) -> None:
        """Test custom message overrides auto-generated one."""
        error = ValidationError(
            message="Email format is invalid",
            field_name="email",
            invalid_value="bad",
            constraint="format",
        )

        assert str(error) == "Email format is invalid"

    def test_is_not_retryable(self) -> None:
        """Test ValidationError is NOT retryable."""
        error = ValidationError(
            field_name="age",
            invalid_value=-5,
            constraint="must be positive",
        )

        assert error.is_retryable is False
        assert error.retry_strategy == RetryStrategy.NO_RETRY

    def test_severity_is_low(self) -> None:
        """Test severity is LOW for validation errors."""
        error = ValidationError(
            field_name="field",
            invalid_value="value",
            constraint="rule",
        )

        assert error.severity == ErrorSeverity.LOW

    def test_truncates_long_invalid_values(self) -> None:
        """Test invalid values over 100 chars are truncated."""
        long_value = "x" * 200
        error = ValidationError(
            field_name="data",
            invalid_value=long_value,
            constraint="too long",
        )
        ctx = error.to_log_context()

        # Should be truncated to 100 chars + "..."
        assert len(ctx["invalid_value"]) == 103
        assert ctx["invalid_value"].endswith("...")
        assert ctx["invalid_value"].startswith("x" * 100)

    def test_short_values_not_truncated(self) -> None:
        """Test values under 100 chars are preserved."""
        short_value = "short string"
        error = ValidationError(
            field_name="name",
            invalid_value=short_value,
            constraint="constraint",
        )
        ctx = error.to_log_context()

        assert ctx["invalid_value"] == "short string"

    def test_context_includes_validation_details(self) -> None:
        """Test context contains field name and constraint."""
        error = ValidationError(
            field_name="password",
            invalid_value="123",
            constraint="minimum 8 characters",
        )
        ctx = error.to_log_context()

        assert ctx["field_name"] == "password"
        assert ctx["constraint"] == "minimum 8 characters"
        assert ctx["invalid_value"] == "123"

    def test_handles_none_invalid_value(self) -> None:
        """Test None as invalid_value is handled."""
        error = ValidationError(
            field_name="required_field",
            invalid_value=None,
            constraint="is required",
        )
        ctx = error.to_log_context()

        assert ctx["invalid_value"] == "None"


class TestSchemaVersionMismatchError:
    """Tests for SchemaVersionMismatchError."""

    def test_auto_generates_message(self) -> None:
        """Test message is auto-generated from version details."""
        error = SchemaVersionMismatchError(
            expected_version="v2",
            actual_version="v1",
        )

        assert "expected v2" in str(error)
        assert "got v1" in str(error)

    def test_custom_message_preserved(self) -> None:
        """Test custom message overrides auto-generated one."""
        error = SchemaVersionMismatchError(
            message="Incompatible protobuf version",
            expected_version="v2",
            actual_version="v1",
        )

        assert str(error) == "Incompatible protobuf version"

    def test_is_not_retryable(self) -> None:
        """Test SchemaVersionMismatchError is NOT retryable."""
        error = SchemaVersionMismatchError(
            expected_version="v3",
            actual_version="v1",
        )

        assert error.is_retryable is False
        assert error.retry_strategy == RetryStrategy.NO_RETRY

    def test_severity_is_high(self) -> None:
        """Test severity is HIGH for schema mismatches."""
        error = SchemaVersionMismatchError(
            expected_version="v2",
            actual_version="v1",
        )

        assert error.severity == ErrorSeverity.HIGH

    def test_context_includes_version_details(self) -> None:
        """Test context contains expected and actual versions."""
        error = SchemaVersionMismatchError(
            expected_version="2.0.0",
            actual_version="1.5.0",
        )
        ctx = error.to_log_context()

        assert ctx["expected_version"] == "2.0.0"
        assert ctx["actual_version"] == "1.5.0"
