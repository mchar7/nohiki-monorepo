"""Tests for handler-level idempotency via processed_events."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import UUID

import pytest
from nohiki_db_utils.idempotency import check_and_mark_processed
from nohiki_db_utils.testing import create_mock_session


class TestCheckAndMarkProcessed:
    """Tests for check_and_mark_processed function."""

    @pytest.mark.asyncio
    async def test_new_event_returns_true(self) -> None:
        """New event inserts successfully and returns True."""
        mock_session = create_mock_session()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (UUID("12345678-1234-5678-1234-567812345678"),)
        mock_session.execute.return_value = mock_result

        result = await check_and_mark_processed(
            db=mock_session,
            schema="test_schema",
            event_id="12345678-1234-5678-1234-567812345678",
            handler_name="handle_listing_created",
        )

        assert result is True
        mock_session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_duplicate_event_returns_false(self) -> None:
        """Duplicate event (ON CONFLICT DO NOTHING) returns False."""
        mock_session = create_mock_session()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_session.execute.return_value = mock_result

        result = await check_and_mark_processed(
            db=mock_session,
            schema="test_schema",
            event_id="12345678-1234-5678-1234-567812345678",
            handler_name="handle_listing_created",
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_sql_contains_schema(self) -> None:
        """Generated SQL references the correct schema."""
        mock_session = create_mock_session()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (UUID("12345678-1234-5678-1234-567812345678"),)
        mock_session.execute.return_value = mock_result

        await check_and_mark_processed(
            db=mock_session,
            schema="my_service_schema",
            event_id="12345678-1234-5678-1234-567812345678",
            handler_name="handle_something",
        )

        call_args = mock_session.execute.call_args
        sql_text = str(call_args[0][0])
        assert "my_service_schema.processed_events" in sql_text

    @pytest.mark.asyncio
    async def test_sql_contains_on_conflict(self) -> None:
        """Generated SQL uses ON CONFLICT DO NOTHING for atomicity."""
        mock_session = create_mock_session()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (UUID("12345678-1234-5678-1234-567812345678"),)
        mock_session.execute.return_value = mock_result

        await check_and_mark_processed(
            db=mock_session,
            schema="test_schema",
            event_id="12345678-1234-5678-1234-567812345678",
            handler_name="handle_something",
        )

        call_args = mock_session.execute.call_args
        sql_text = str(call_args[0][0])
        assert "ON CONFLICT" in sql_text
        assert "DO NOTHING" in sql_text
        assert "RETURNING" in sql_text

    @pytest.mark.asyncio
    async def test_passes_correct_parameters(self) -> None:
        """Correct event_id and handler_name are passed to SQL."""
        mock_session = create_mock_session()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (UUID("87654321-4321-8765-4321-876543218765"),)
        mock_session.execute.return_value = mock_result

        await check_and_mark_processed(
            db=mock_session,
            schema="test_schema",
            event_id="87654321-4321-8765-4321-876543218765",
            handler_name="handle_job_created",
        )

        call_args = mock_session.execute.call_args
        stmt = call_args[0][0]
        compiled = stmt.compile()
        assert compiled.params["event_id"] == UUID("87654321-4321-8765-4321-876543218765")
        assert compiled.params["handler_name"] == "handle_job_created"
        assert "processed_at" in compiled.params

    @pytest.mark.asyncio
    async def test_event_id_uses_postgresql_uuid_bind_type(self) -> None:
        """Valid UUID strings are parsed and bound as PostgreSQL UUIDs."""
        mock_session = create_mock_session()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (UUID("12345678-1234-5678-1234-567812345678"),)
        mock_session.execute.return_value = mock_result

        await check_and_mark_processed(
            db=mock_session,
            schema="test_schema",
            event_id="12345678-1234-5678-1234-567812345678",
            handler_name="handle_something",
        )

        stmt = mock_session.execute.call_args.args[0]
        event_id_bind = stmt.compile().binds["event_id"]
        assert event_id_bind.type.python_type is UUID
        assert event_id_bind.value == UUID("12345678-1234-5678-1234-567812345678")

    @pytest.mark.asyncio
    async def test_malformed_event_id_fails_before_database_execution(self) -> None:
        """Malformed event IDs are rejected without issuing SQL."""
        mock_session = create_mock_session()

        with pytest.raises(ValueError, match="badly formed hexadecimal UUID string"):
            await check_and_mark_processed(
                db=mock_session,
                schema="test_schema",
                event_id="not-a-uuid",
                handler_name="handle_something",
            )

        mock_session.execute.assert_not_called()
