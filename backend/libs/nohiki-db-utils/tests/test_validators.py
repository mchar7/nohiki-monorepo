"""Tests for defensive SQL identifier validators."""

from __future__ import annotations

import pytest
from nohiki_db_utils._validators import validate_schema_name


class TestValidateSchemaName:
    """Tests for validate_schema_name."""

    @pytest.mark.parametrize(
        "schema",
        [
            "bff_schema",
            "user_pref_schema",
            "MySchema",
            "_private",
            "a",
            "A1",
            "schema_with_digits_123",
        ],
    )
    def test_accepts_valid_identifiers(self, schema: str) -> None:
        """Valid PostgreSQL-style identifiers are accepted."""
        validate_schema_name(schema)  # Should not raise

    @pytest.mark.parametrize(
        "schema",
        [
            "",
            "1schema",  # starts with digit
            "schema-name",  # hyphen
            "schema name",  # space
            "schema;DROP TABLE x;--",  # SQL injection attempt
            "schema.other",  # dot
            'schema"quoted"',  # quotes
            "\x00schema",  # null byte
            "schema\n",  # newline
            "a" * 64,  # too long (> 63 chars, PostgreSQL NAMEDATALEN limit)
        ],
    )
    def test_rejects_invalid_identifiers(self, schema: str) -> None:
        """Unsafe identifiers raise ValueError."""
        with pytest.raises(ValueError, match="schema name"):
            validate_schema_name(schema)

    def test_empty_message_mentions_non_empty(self) -> None:
        """Empty schema produces a clear error message."""
        with pytest.raises(ValueError, match="non-empty"):
            validate_schema_name("")
