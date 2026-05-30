"""Tests for tailor.display.console -- format helpers and constants."""

from __future__ import annotations

import pytest
from rich.console import Console
from tailor.display.console import (
    ICON_ARROW,
    ICON_BULLET,
    ICON_DOC,
    ICON_ERROR,
    ICON_FILE,
    ICON_GENERATE,
    ICON_INFO,
    ICON_RENDER,
    ICON_SPINNER,
    ICON_SUCCESS,
    ICON_TARGET,
    ICON_TEMPLATE,
    ICON_WARNING,
    STYLE_ACCENT,
    STYLE_DIM,
    STYLE_ERROR,
    STYLE_HIGHLIGHT,
    STYLE_INFO,
    STYLE_SUCCESS,
    STYLE_WARNING,
    console,
    format_cost,
    format_duration,
    format_size,
    format_tokens,
)


class TestFormatSize:
    """Tests for format_size byte formatter."""

    @pytest.mark.parametrize(
        ("size_bytes", "expected"),
        [
            (0, "0 B"),
            (1023, "1023 B"),
            (1024, "1.0 KB"),
            (1536, "1.5 KB"),
            (1_048_576, "1.0 MB"),
            (1_572_864, "1.5 MB"),
        ],
    )
    def test_format_size(self, size_bytes: int, expected: str) -> None:
        """format_size must produce human-readable byte strings for all size ranges."""
        assert format_size(size_bytes) == expected


class TestFormatDuration:
    """Tests for format_duration time formatter."""

    @pytest.mark.parametrize(
        ("seconds", "expected"),
        [
            (0.5, "500ms"),
            (0.001, "1ms"),
            (1.5, "1.5s"),
            (59.9, "59.9s"),
            (60.0, "1m 0s"),
            (90.0, "1m 30s"),
            (125.0, "2m 5s"),
        ],
    )
    def test_format_duration(self, seconds: float, expected: str) -> None:
        """format_duration must produce human-readable duration strings for all time ranges."""
        assert format_duration(seconds) == expected


class TestFormatTokens:
    """Tests for format_tokens token count formatter."""

    def test_zero_tokens(self) -> None:
        """format_tokens must format zero as '0'."""
        assert format_tokens(0) == "0"

    def test_thousand_tokens(self) -> None:
        """format_tokens must add thousands separator for 1000."""
        assert format_tokens(1000) == "1,000"

    def test_million_tokens(self) -> None:
        """format_tokens must add thousands separators for 1,000,000."""
        assert format_tokens(1_000_000) == "1,000,000"


class TestFormatCost:
    """Tests for format_cost USD formatter."""

    @pytest.mark.parametrize(
        ("usd", "expected"),
        [
            (0.0001, "~$0.0001"),
            (0.009, "~$0.0090"),
            (0.01, "~$0.01"),
            (1.5, "~$1.50"),
        ],
    )
    def test_format_cost(self, usd: float, expected: str) -> None:
        """format_cost must use 4 decimal places below $0.01 and 2 decimal places at or above."""
        assert format_cost(usd) == expected


class TestStyleConstants:
    """Tests verifying STYLE_* constants are non-empty strings."""

    @pytest.mark.parametrize(
        "value",
        [STYLE_SUCCESS, STYLE_ERROR, STYLE_WARNING, STYLE_INFO, STYLE_DIM, STYLE_HIGHLIGHT, STYLE_ACCENT],
    )
    def test_style_constant_is_nonempty_string(self, value: str) -> None:
        """Every STYLE_* constant must be a non-empty string."""
        assert isinstance(value, str)
        assert value


class TestIconConstants:
    """Tests verifying ICON_* constants are non-empty strings."""

    @pytest.mark.parametrize(
        "value",
        [
            ICON_SUCCESS,
            ICON_ERROR,
            ICON_WARNING,
            ICON_INFO,
            ICON_SPINNER,
            ICON_BULLET,
            ICON_ARROW,
            ICON_FILE,
            ICON_DOC,
            ICON_TEMPLATE,
            ICON_GENERATE,
            ICON_RENDER,
            ICON_TARGET,
        ],
    )
    def test_icon_constant_is_nonempty_string(self, value: str) -> None:
        """Every ICON_* constant must be a non-empty string."""
        assert isinstance(value, str)
        assert value


class TestConsoleInstance:
    """Tests for the shared console singleton."""

    def test_console_is_rich_console_instance(self) -> None:
        """The module-level console must be a rich Console instance."""
        assert isinstance(console, Console)
