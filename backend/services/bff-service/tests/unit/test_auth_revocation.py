"""Focused tests for the durable BFF access-token revocation ledger."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from bff_service.services.auth_revocation import (
    JtiCollisionError,
    delete_expired_revocations,
    is_access_token_revoked,
    record_access_token_revocation,
    record_session_family_revocation,
    record_user_revocation_cutoff,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import ClauseElement


def _compiled(statement: ClauseElement) -> tuple[str, dict[str, object]]:
    compiled = statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": False})
    return str(compiled), compiled.params


@pytest.mark.asyncio
async def test_revocation_lookup_uses_jti_permanent_tombstone_and_active_family_cutoff() -> None:
    session = AsyncMock()
    session.scalar.return_value = True
    user_id = uuid4()
    family_id = str(uuid4())
    issued_at = datetime(2026, 7, 11, tzinfo=UTC)

    assert (
        await is_access_token_revoked(
            session, user_id=user_id, jti=str(uuid4()), issued_at=issued_at, session_family_id=family_id
        )
        is True
    )

    sql, params = _compiled(session.scalar.await_args.args[0])
    normalized = " ".join(sql.lower().split())
    assert "revoked_access_tokens.expires_at > now()" in normalized
    assert "user_revocation_cutoffs.is_permanent is true" in normalized
    assert "user_revocation_cutoffs.revoked_before >=" in normalized
    assert "user_revocation_cutoffs.expires_at > now()" in normalized
    assert "revoked_session_families.family_id =" in normalized
    assert "revoked_session_families.user_id =" in normalized
    assert "revoked_session_families.expires_at > now()" in normalized
    assert "revoked_session_families.revoked_before >=" in normalized
    assert user_id in params.values()
    assert issued_at in params.values()


@pytest.mark.asyncio
async def test_jti_upsert_is_idempotent_and_expiry_is_monotonic() -> None:
    session = AsyncMock()
    session.execute.return_value = MagicMock(rowcount=1)
    expires_at = datetime(2026, 7, 11, 12, tzinfo=UTC)

    await record_access_token_revocation(session, user_id=uuid4(), jti=str(uuid4()), expires_at=expires_at)

    sql, params = _compiled(session.execute.await_args.args[0])
    normalized = " ".join(sql.lower().split())
    assert "on conflict (jti) do update" in normalized
    assert "greatest(" in normalized
    assert "revoked_access_tokens.expires_at, excluded.expires_at)" in normalized
    assert "revoked_access_tokens.user_id = excluded.user_id" in normalized
    assert expires_at in params.values()


@pytest.mark.asyncio
async def test_cross_user_jti_collision_is_rejected() -> None:
    session = AsyncMock()
    session.execute.return_value = MagicMock(rowcount=0)

    with pytest.raises(JtiCollisionError):
        await record_access_token_revocation(
            session,
            user_id=uuid4(),
            jti=str(uuid4()),
            expires_at=datetime(2026, 7, 11, tzinfo=UTC),
        )


@pytest.mark.asyncio
async def test_cutoff_upsert_is_monotonic_and_permanent() -> None:
    session = AsyncMock()
    revoked_before = datetime(2026, 7, 11, 12, 34, 56, tzinfo=UTC)

    await record_user_revocation_cutoff(
        session,
        user_id=uuid4(),
        revoked_before=revoked_before,
        is_permanent=True,
    )

    sql, params = _compiled(session.execute.await_args.args[0])
    normalized = " ".join(sql.lower().split())
    assert "on conflict (user_id) do update" in normalized
    assert revoked_before in params.values()
    assert datetime.max.replace(tzinfo=UTC) in params.values()
    assert True in params.values()
    assert "user_revocation_cutoffs.expires_at, excluded.expires_at)" in normalized
    assert "user_revocation_cutoffs.is_permanent or excluded.is_permanent" in normalized
    assert "greatest(" in normalized
    assert "user_revocation_cutoffs.revoked_before, excluded.revoked_before)" in normalized


@pytest.mark.asyncio
async def test_family_upsert_is_idempotent_monotonic_and_user_isolated() -> None:
    session = AsyncMock()
    session.execute.return_value = MagicMock(rowcount=1)
    cutoff = datetime(2026, 7, 11, 12, tzinfo=UTC)
    expiry = cutoff + timedelta(minutes=10)

    await record_session_family_revocation(
        session, family_id=str(uuid4()), user_id=uuid4(), revoked_before=cutoff, expires_at=expiry
    )

    sql, _ = _compiled(session.execute.await_args.args[0])
    normalized = " ".join(sql.lower().split())
    assert "on conflict (family_id) do update" in normalized
    assert "revoked_session_families.user_id = excluded.user_id" in normalized
    assert "greatest(" in normalized
    assert "revoked_session_families.revoked_before, excluded.revoked_before)" in normalized
    assert "revoked_session_families.expires_at, excluded.expires_at)" in normalized


@pytest.mark.asyncio
async def test_cross_user_family_collision_and_malformed_family_are_rejected() -> None:
    session = AsyncMock()
    session.execute.return_value = MagicMock(rowcount=0)
    with pytest.raises(JtiCollisionError):
        await record_session_family_revocation(
            session,
            family_id=str(uuid4()),
            user_id=uuid4(),
            revoked_before=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
        )

    session.reset_mock()
    with pytest.raises(ValueError, match="badly formed hexadecimal UUID string"):
        await is_access_token_revoked(
            session,
            user_id=uuid4(),
            jti=str(uuid4()),
            issued_at=datetime.now(UTC),
            session_family_id="malformed",
        )
    session.scalar.assert_not_awaited()


@pytest.mark.asyncio
async def test_legacy_token_without_family_omits_family_predicate() -> None:
    session = AsyncMock()
    session.scalar.return_value = False
    await is_access_token_revoked(session, user_id=uuid4(), jti=str(uuid4()), issued_at=datetime.now(UTC))
    sql, _ = _compiled(session.scalar.await_args.args[0])
    assert "revoked_session_families" not in sql


@pytest.mark.asyncio
async def test_malformed_jti_is_rejected_before_database_access() -> None:
    session = AsyncMock()

    with pytest.raises(ValueError, match="badly formed hexadecimal UUID string"):
        await is_access_token_revoked(
            session,
            user_id=uuid4(),
            jti="not-a-uuid",
            issued_at=datetime(2026, 7, 11, tzinfo=UTC),
        )

    session.scalar.assert_not_awaited()


@pytest.mark.asyncio
async def test_cleanup_deletes_only_expired_nonpermanent_rows() -> None:
    session = AsyncMock()
    session.execute.side_effect = [MagicMock(rowcount=2), MagicMock(rowcount=3), MagicMock(rowcount=4)]

    assert await delete_expired_revocations(session) == 9
    token_sql, _ = _compiled(session.execute.await_args_list[0].args[0])
    family_sql, _ = _compiled(session.execute.await_args_list[1].args[0])
    cutoff_sql, _ = _compiled(session.execute.await_args_list[2].args[0])
    assert "DELETE FROM bff_schema.revoked_access_tokens" in token_sql
    assert "revoked_access_tokens.expires_at <= now()" in token_sql
    assert "DELETE FROM bff_schema.revoked_session_families" in family_sql
    assert "revoked_session_families.expires_at <= now()" in family_sql
    assert "DELETE FROM bff_schema.user_revocation_cutoffs" in cutoff_sql
    assert "user_revocation_cutoffs.is_permanent IS false" in cutoff_sql
    assert "user_revocation_cutoffs.expires_at <= now()" in cutoff_sql
