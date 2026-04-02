"""Tests for data availability exceptions."""

import math

from nohiki_common_exceptions import (
    DataIntegrityError,
    DataNotAvailableError,
    DataNotFoundError,
    ErrorSeverity,
    RetryStrategy,
    StaleDataError,
)
from nohiki_common_exceptions.user_messages import UserFacingErrorCode, get_default_message


class TestDataNotAvailableError:
    """Tests for DataNotAvailableError."""

    def test_auto_generates_message(self) -> None:
        """Test message is auto-generated from resource details."""
        error = DataNotAvailableError(
            resource_type="Listing",
            resource_id="abc-123",
            source="cache",
        )

        assert str(error) == "Listing 'abc-123' unavailable from cache"

    def test_custom_message_preserved(self) -> None:
        """Test custom message overrides auto-generated one."""
        error = DataNotAvailableError(
            message="Custom unavailable message",
            resource_type="Listing",
            resource_id="abc-123",
            source="cache",
        )

        assert str(error) == "Custom unavailable message"

    def test_is_retryable(self) -> None:
        """Test DataNotAvailableError is retryable."""
        error = DataNotAvailableError(
            resource_type="Listing",
            resource_id="123",
            source="grpc",
        )

        assert error.is_retryable is True
        assert error.retry_strategy == RetryStrategy.RETRY_EXPONENTIAL

    def test_severity_is_high(self) -> None:
        """Test severity is HIGH for data unavailability."""
        error = DataNotAvailableError(
            resource_type="Profile",
            resource_id="456",
            source="database",
        )

        assert error.severity == ErrorSeverity.HIGH

    def test_context_includes_resource_details(self) -> None:
        """Test context contains resource type, id, and source."""
        error = DataNotAvailableError(
            resource_type="Account",
            resource_id="user-789",
            source="redis",
        )
        ctx = error.to_log_context()

        assert ctx["resource_type"] == "Account"
        assert ctx["resource_id"] == "user-789"
        assert ctx["source"] == "redis"


class TestDataNotFoundError:
    """Tests for DataNotFoundError."""

    def test_auto_generates_message(self) -> None:
        """Test message is auto-generated from resource details."""
        error = DataNotFoundError(
            resource_type="Listing",
            resource_id="nonexistent-123",
        )

        assert str(error) == "Listing 'nonexistent-123' not found"

    def test_custom_message_preserved(self) -> None:
        """Test custom message overrides auto-generated one."""
        error = DataNotFoundError(
            message="The job was deleted",
            resource_type="Listing",
            resource_id="deleted-123",
        )

        assert str(error) == "The job was deleted"

    def test_is_not_retryable(self) -> None:
        """Test DataNotFoundError is NOT retryable."""
        error = DataNotFoundError(
            resource_type="Listing",
            resource_id="123",
        )

        assert error.is_retryable is False
        assert error.retry_strategy == RetryStrategy.NO_RETRY

    def test_severity_is_medium(self) -> None:
        """Test severity is MEDIUM for not found errors."""
        error = DataNotFoundError(
            resource_type="Profile",
            resource_id="456",
        )

        assert error.severity == ErrorSeverity.MEDIUM

    def test_context_includes_resource_details(self) -> None:
        """Test context contains resource type and id."""
        error = DataNotFoundError(
            resource_type="Correlation",
            resource_id="correlation-xyz",
        )
        ctx = error.to_log_context()

        assert ctx["resource_type"] == "Correlation"
        assert ctx["resource_id"] == "correlation-xyz"
        assert "source" not in ctx  # Not applicable for not found


class TestStaleDataError:
    """Tests for StaleDataError."""

    def test_auto_generates_message_with_age(self) -> None:
        """Test message includes age information."""
        error = StaleDataError(
            resource_type="JobSnapshot",
            resource_id="snap-123",
            data_age_seconds=3600.5,
            max_age_seconds=1800.0,
        )

        assert "JobSnapshot 'snap-123' is stale" in str(error)
        assert "3600.5s" in str(error)
        assert "1800.0s" in str(error)

    def test_is_retryable_with_immediate_strategy(self) -> None:
        """Test StaleDataError uses RETRY_IMMEDIATE strategy."""
        error = StaleDataError(
            resource_type="Cache",
            resource_id="cache-key",
            data_age_seconds=100.0,
            max_age_seconds=60.0,
        )

        assert error.is_retryable is True
        assert error.retry_strategy == RetryStrategy.RETRY_IMMEDIATE

    def test_severity_is_medium(self) -> None:
        """Test severity is MEDIUM for stale data."""
        error = StaleDataError(
            resource_type="Data",
            resource_id="123",
            data_age_seconds=10.0,
            max_age_seconds=5.0,
        )

        assert error.severity == ErrorSeverity.MEDIUM

    def test_context_includes_age_information(self) -> None:
        """Test context contains age details."""
        error = StaleDataError(
            resource_type="Profile",
            resource_id="prof-456",
            data_age_seconds=120.5,
            max_age_seconds=60.0,
        )
        ctx = error.to_log_context()

        assert ctx["resource_type"] == "Profile"
        assert ctx["resource_id"] == "prof-456"
        assert math.isclose(ctx["data_age_seconds"], 120.5)
        assert math.isclose(ctx["max_age_seconds"], 60.0)


class TestDataIntegrityError:
    """Tests for DataIntegrityError."""

    def test_auto_generates_message(self) -> None:
        """Auto-generates message from resource type and IDs."""
        error = DataIntegrityError(
            resource_type="Embedding",
            resource_ids=("skill-1", "skill-2"),
        )

        assert "Embedding integrity violation" in str(error)
        assert "skill-1" in str(error)
        assert "skill-2" in str(error)

    def test_custom_message_preserved(self) -> None:
        """Custom message overrides auto-generated one."""
        error = DataIntegrityError(
            message="Custom integrity message",
            resource_type="Embedding",
            resource_ids=("skill-1",),
        )

        assert str(error) == "Custom integrity message"

    def test_is_not_retryable(self) -> None:
        """DataIntegrityError is NOT retryable."""
        error = DataIntegrityError(
            resource_type="Projection",
            resource_ids=("proj-1",),
        )

        assert error.is_retryable is False
        assert error.retry_strategy == RetryStrategy.NO_RETRY

    def test_severity_is_critical(self) -> None:
        """Severity is CRITICAL for integrity violations."""
        error = DataIntegrityError(
            resource_type="FK",
            resource_ids=("ref-1",),
        )

        assert error.severity == ErrorSeverity.CRITICAL

    def test_overflow_suffix_for_many_ids(self) -> None:
        """Message includes overflow count when many IDs provided."""
        ids = tuple(f"id-{i}" for i in range(20))
        error = DataIntegrityError(
            resource_type="Record",
            resource_ids=ids,
        )

        assert "more)" in str(error)

    def test_context_includes_resource_details(self) -> None:
        """Context contains resource type and IDs."""
        error = DataIntegrityError(
            resource_type="Skill",
            resource_ids=("s-1", "s-2"),
        )
        ctx = error.to_log_context()

        assert ctx["resource_type"] == "Skill"
        assert ctx["resource_ids"] == ["s-1", "s-2"]


class TestGetDefaultMessage:
    """Tests for get_default_message function."""

    def test_known_error_code(self) -> None:
        """Returns correct message for known error code."""
        result = get_default_message(UserFacingErrorCode.SERVER_ERROR)
        assert result == "Server error"

    def test_fallback_when_code_not_in_messages(self) -> None:
        """Returns fallback message when code is missing from DEFAULT_MESSAGES."""
        from unittest.mock import patch

        from nohiki_common_exceptions import user_messages

        trimmed = {k: v for k, v in user_messages.DEFAULT_MESSAGES.items() if k != UserFacingErrorCode.SERVER_ERROR}
        with patch.object(user_messages, "DEFAULT_MESSAGES", trimmed):
            result = get_default_message(UserFacingErrorCode.SERVER_ERROR)

        assert result == "An error occurred"
