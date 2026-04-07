"""Tests for structured log processors."""

from __future__ import annotations

from unittest.mock import MagicMock

from nohiki_observability.processors import redact_sensitive_data


def test_redacts_sensitive_keys_recursively() -> None:
    """Sensitive values nested in mappings and sequences never reach structured output."""
    event = {
        "event": "login failed",
        "request": {
            "credentials": {"password": "nested-secret", "username": "alice"},
            "attempts": [{"Authorization": "Bearer hidden", "result": "denied"}],
            "metadata": ({"api-key": "hidden-key", "region": "eu-west"},),
        },
    }

    result = redact_sensitive_data(MagicMock(), "info", event)

    assert result == {
        "event": "login failed",
        "request": {
            "credentials": "[REDACTED]",
            "attempts": [{"Authorization": "[REDACTED]", "result": "denied"}],
            "metadata": ({"api-key": "[REDACTED]", "region": "eu-west"},),
        },
    }
