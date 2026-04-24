"""Unit tests for the manage.py script."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from notification_service.manage import main


def test_main_unknown_command() -> None:
    """Test main function with unknown command."""
    with (
        patch("sys.argv", ["manage.py", "unknown"]),
        patch("notification_service.manage.logger") as mock_logger,
        patch("notification_service.manage.sys.exit", side_effect=RuntimeError("sys.exit called")),
    ):
        with pytest.raises(RuntimeError, match=r"sys\.exit called"):
            main()

        # structlog-style logging uses keyword arguments
        mock_logger.error.assert_called_once_with("Unknown command", command="unknown")


def test_main_no_args() -> None:
    """Test main function with no arguments."""
    with (
        patch("sys.argv", ["manage.py"]),
        patch("notification_service.manage.logger") as mock_logger,
        patch("notification_service.manage.sys.exit", side_effect=RuntimeError("sys.exit called")),
    ):
        with pytest.raises(RuntimeError, match=r"sys\.exit called"):
            main()

        mock_logger.info.assert_any_call("Usage: python manage.py <command>")
        mock_logger.info.assert_any_call("Available commands:")
