"""Tests for messaging constants and failure cause determination."""

from __future__ import annotations

import pytest
from nohiki.common.v1 import DeliveryFailureCause
from notification_service.services.messaging.constants import (
    FAILURE_CAUSE_PATTERNS,
    determine_failure_cause,
)


class TestDetermineFailureCause:
    """Tests for determine_failure_cause function."""

    def test_none_error_returns_unexpected(self) -> None:
        """None error message returns UNEXPECTED_ERROR."""
        assert determine_failure_cause(None) == DeliveryFailureCause.UNEXPECTED_ERROR

    def test_empty_string_returns_unexpected(self) -> None:
        """Empty error message returns UNEXPECTED_ERROR."""
        assert determine_failure_cause("") == DeliveryFailureCause.UNEXPECTED_ERROR

    @pytest.mark.parametrize(
        ("error_msg", "expected"),
        [
            ("provider not found", DeliveryFailureCause.PROVIDER_NOT_FOUND),
            ("Provider Not Found for channel", DeliveryFailureCause.PROVIDER_NOT_FOUND),
            ("rate limit exceeded", DeliveryFailureCause.RATE_LIMITED),
            ("Rate Limit hit", DeliveryFailureCause.RATE_LIMITED),
            ("template rendering failed", DeliveryFailureCause.TEMPLATE_ERROR),
            ("Template not found", DeliveryFailureCause.TEMPLATE_ERROR),
            ("network connection failed", DeliveryFailureCause.NETWORK_ERROR),
            ("connection refused", DeliveryFailureCause.NETWORK_ERROR),
            ("request timeout", DeliveryFailureCause.NETWORK_ERROR),
            ("auth token expired", DeliveryFailureCause.AUTHENTICATION_ERROR),
            ("invalid credential", DeliveryFailureCause.AUTHENTICATION_ERROR),
            ("token revoked", DeliveryFailureCause.AUTHENTICATION_ERROR),
        ],
    )
    def test_pattern_matching(self, error_msg: str, expected: DeliveryFailureCause) -> None:
        """Error messages are correctly mapped to failure causes."""
        assert determine_failure_cause(error_msg) == expected

    def test_invalid_email_recipient(self) -> None:
        """Invalid email in error returns INVALID_RECIPIENT."""
        assert determine_failure_cause("invalid email address") == DeliveryFailureCause.INVALID_RECIPIENT
        assert determine_failure_cause("invalid recipient format") == DeliveryFailureCause.INVALID_RECIPIENT

    def test_generic_error_returns_provider_error(self) -> None:
        """Unrecognized errors return PROVIDER_ERROR."""
        assert determine_failure_cause("some random error") == DeliveryFailureCause.PROVIDER_ERROR
        assert determine_failure_cause("unknown failure") == DeliveryFailureCause.PROVIDER_ERROR

    def test_case_insensitive_matching(self) -> None:
        """Pattern matching is case-insensitive."""
        assert determine_failure_cause("RATE LIMIT") == DeliveryFailureCause.RATE_LIMITED
        assert determine_failure_cause("Network Error") == DeliveryFailureCause.NETWORK_ERROR

    def test_failure_cause_patterns_is_immutable(self) -> None:
        """FAILURE_CAUSE_PATTERNS should be a Final constant."""
        assert len(FAILURE_CAUSE_PATTERNS) > 0
        assert all(isinstance(patterns, tuple) for patterns in FAILURE_CAUSE_PATTERNS)
