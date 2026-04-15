"""Tests for JSearch exceptions."""

from __future__ import annotations

import pytest
from job_ingest_discovery_service.providers.jsearch.exceptions import (
    JSearchError,
    JSearchNotConfiguredError,
    JSearchRateLimitError,
)


class TestJSearchError:
    """Tests for base JSearchError."""

    def test_message_stored(self) -> None:
        """Test message is stored."""
        error = JSearchError("Test error message")
        assert error.message == "Test error message"
        assert str(error) == "Test error message"


class TestJSearchNotConfiguredError:
    """Tests for JSearchNotConfiguredError."""

    def test_default_message(self) -> None:
        """Test default error message."""
        error = JSearchNotConfiguredError()
        assert "jsearch" in error.message.lower()
        assert "not configured" in error.message.lower()


class TestJSearchRateLimitError:
    """Tests for JSearchRateLimitError."""

    def test_with_tier_name(self) -> None:
        """Test error with tier name."""
        error = JSearchRateLimitError(tier_name="monthly")
        assert error.tier_name == "monthly"
        assert "monthly" in str(error)

    def test_with_retry_after(self) -> None:
        """Test error with retry_after_seconds."""
        error = JSearchRateLimitError(tier_name="hourly", retry_after_seconds=3600.0)
        assert error.tier_name == "hourly"
        assert error.retry_after_seconds == pytest.approx(3600.0)

    def test_inherits_from_rate_limited_error(self) -> None:
        """Test inheritance from RateLimitedError."""
        from nohiki_common_exceptions import RateLimitedError

        error = JSearchRateLimitError(tier_name="monthly")
        assert isinstance(error, RateLimitedError)

    def test_is_retryable(self) -> None:
        """Test that error is marked as retryable."""
        error = JSearchRateLimitError(tier_name="hourly")
        assert error.is_retryable
