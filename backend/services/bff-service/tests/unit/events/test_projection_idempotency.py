"""Idempotency tests for BFF projection handlers.

Each test calls a handler twice with the same message and asserts:

1. No exception is raised on the duplicate call.
2. ``session.execute`` is called for each invocation.
3. The compiled PostgreSQL statement contains an ``ON CONFLICT`` clause
   (or ``DELETE``/``UPDATE`` for non-upsert handlers), which is what
   actually makes the handler idempotent at the database level.

Using the real PostgreSQL dialect compiler proves the ``insert(...)``
statements emit the expected upsert SQL without needing a live database.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from bff_service.events.projections.job_correlation import handle_correlation_evaluated
from bff_service.events.projections.job_listing import handle_listing_created
from bff_service.events.projections.skill import handle_skill_created
from bff_service.events.projections.user_auth import handle_account_updated
from bff_service.events.projections.user_pref import (
    handle_profile_created,
    handle_profile_updated,
    handle_user_pref_settings_created,
    handle_user_pref_settings_updated,
)
from bff_service.events.projections.user_upload import handle_attachment_created
from bff_service.services.auth_revocation import (
    record_access_token_revocation,
    record_user_revocation_cutoff,
)
from nohiki.common.v1 import Location
from nohiki_kafka_client import MessageContext
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import ClauseElement

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# Stubs for protobuf types
Account = MagicMock
AccountUpdated = MagicMock
PrefCreated = MagicMock
PrefUpdated = MagicMock
SearchPrefSnapshot = MagicMock
UserPrefSettings = MagicMock
UserPrefSettingsCreated = MagicMock
UserPrefSettingsUpdated = MagicMock
UploadCreated = MagicMock
ListingCreated = MagicMock
ListingSnapshot = MagicMock
CorrelationEvaluated = MagicMock
CanonicalSkill = MagicMock
SkillCreated = MagicMock


class _StatementCapture:
    """Mock session that records the compiled SQL of each executed statement.

    Compiling against the real PostgreSQL dialect lets the tests assert on
    ``ON CONFLICT`` clauses without standing up a database: the dialect's
    SQL generation is the actual idempotency contract.
    """

    def __init__(self) -> None:
        self.statements: list[str] = []
        self.parameters: list[dict[str, object]] = []
        self.execute = AsyncMock(side_effect=self._execute)
        self.scalar = AsyncMock(return_value=False)

    async def _execute(self, stmt: ClauseElement, *_args: object, **_kwargs: object) -> MagicMock:
        compiled = stmt.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": False},
        )
        self.statements.append(str(compiled))
        self.parameters.append(dict(compiled.params))
        return MagicMock()


def _capture_session() -> _StatementCapture:
    """Return a statement-capturing fake session for MessageContext injection."""
    return _StatementCapture()


def _ctx(topic: str = "test.topic.v1", *, db_session: _StatementCapture | None = None) -> MessageContext:
    """Build a MessageContext with optional injected db_session."""
    session = cast("AsyncSession | None", db_session)
    return MessageContext(topic=topic, partition=0, offset=0, timestamp=0, headers={}, key=None, db_session=session)


def _assert_has_upsert(statements: list[str]) -> None:
    """At least one captured statement must be an ON CONFLICT upsert."""
    assert any("ON CONFLICT" in s and "DO UPDATE SET" in s for s in statements), (
        f"Expected at least one ON CONFLICT ... DO UPDATE SET; got: {statements}"
    )


def _assert_has_idempotent_write(statements: list[str]) -> None:
    """At least one captured statement must be an upsert or DO NOTHING insert."""
    assert any("ON CONFLICT" in s and ("DO UPDATE SET" in s or "DO NOTHING" in s) for s in statements), (
        f"Expected at least one idempotent ON CONFLICT statement; got: {statements}"
    )


def _make_account_event() -> MagicMock:
    user_id = uuid.uuid4()
    now = datetime.now(UTC)
    account = Account()
    account.id = str(user_id)
    account.email = "idempotent@example.com"
    account.display_name = "Test"
    account.first_name = "Test"
    account.last_name = "User"
    account.is_active = True
    account.email_verified = True
    account.created_at = now
    account.updated_at = now

    event = AccountUpdated()
    event.user_id = str(user_id)
    event.account_snapshot = account
    return event


def _make_profile_created_event() -> MagicMock:
    pref_id = uuid.uuid4()
    user_id = uuid.uuid4()
    snapshot = SearchPrefSnapshot()
    snapshot.id = str(pref_id)
    snapshot.user_id = str(user_id)
    snapshot.pref_name = "My Profile"
    snapshot.search_keywords = ["python", "backend"]
    snapshot.disallowed_keywords = []
    snapshot.work_arrangements = []
    snapshot.notification_threshold = 70
    snapshot.auto_tailor_threshold = None
    snapshot.open_to_relocation = False
    snapshot.commute_preferences = None
    snapshot.user_skills = []
    snapshot.tailoring_schema_id = str(uuid.uuid4())
    snapshot.feature_importance = SimpleNamespace(
        skill_match_importance=10,
        location_importance=20,
        work_arrangement_importance=30,
        experience_importance=40,
        salary_importance=50,
        recency_importance=60,
    )
    snapshot.salary_preference = None
    snapshot.experience_preference = None
    snapshot.is_active = False

    event = PrefCreated()
    event.pref_snapshot = snapshot
    return event


def _make_listing_event() -> MagicMock:
    listing_id = uuid.uuid4()
    snapshot = ListingSnapshot()
    snapshot.id = str(listing_id)
    snapshot.title = "Software Engineer"
    snapshot.company_name = "Acme Corp"
    snapshot.listing_url = "https://example.com/job/1"
    snapshot.location = Location(city="San Francisco", state_province="CA")
    snapshot.description = "A job"
    snapshot.work_arrangement = SimpleNamespace(name="REMOTE")
    snapshot.seniority_level = SimpleNamespace(name="MID")
    snapshot.employment_type = SimpleNamespace(name="FULL_TIME")
    snapshot.source = SimpleNamespace(name="LINKEDIN")
    snapshot.version = 1
    snapshot.compensation = None
    snapshot.required_skills = []
    snapshot.preferred_skills = []
    snapshot.required_experience_years = None
    snapshot.education_level = None
    snapshot.posted_at = datetime.now(UTC)
    snapshot.expires_at = None
    snapshot.is_active = True

    listing_ref = MagicMock()
    listing_ref.id = str(listing_id)

    event = ListingCreated()
    event.listing_snapshot = snapshot
    event.listing = listing_ref
    return event


def _make_correlation_event() -> MagicMock:
    correlation_id = uuid.uuid4()
    pref_id = uuid.uuid4()
    listing_id = uuid.uuid4()
    user_id = uuid.uuid4()

    pref_snapshot = MagicMock()
    pref_snapshot.id = str(pref_id)
    pref_snapshot.user_id = str(user_id)

    listing_snapshot = MagicMock()
    listing_snapshot.id = str(listing_id)
    listing_snapshot.title = "Engineer"
    listing_snapshot.company_name = "Corp"
    listing_snapshot.listing_url = "https://example.com"
    listing_snapshot.location = Location(city="New York", state_province="NY")

    event = CorrelationEvaluated()
    event.correlation_id = str(correlation_id)
    event.pref_snapshot = pref_snapshot
    event.listing_snapshot = listing_snapshot
    event.fit_score = 0.85
    event.correlation_status = SimpleNamespace(name="EVALUATED")
    event.correlation_metadata = {"score": "0.85"}
    return event


def _make_skill_event() -> MagicMock:
    skill_id = uuid.uuid4()
    snapshot = CanonicalSkill()
    snapshot.id = str(skill_id)
    snapshot.canonical_id = "python-001"
    snapshot.normalized_text = "python"
    snapshot.display_name = "Python"
    snapshot.description = "Programming language"
    snapshot.category = "Programming"
    snapshot.subcategory = "Languages"
    snapshot.skill_type = "HARD"
    snapshot.source = SimpleNamespace(name="TABIYA")
    snapshot.mention_count = 100
    snapshot.job_count = 50
    snapshot.profile_count = 25

    event = SkillCreated()
    event.skill_snapshot = snapshot
    return event


def _make_settings_event(cls: type) -> MagicMock:
    user_id = uuid.uuid4()
    settings = UserPrefSettings()
    settings.user_id = str(user_id)
    settings.default_feature_importance = None
    settings.preferred_timezone = "America/New_York"
    settings.preferred_locale = "en-US"

    event = cls()
    event.settings = settings
    return event


def _make_attachment_event() -> MagicMock:
    upload_id = uuid.uuid4()
    user_id = uuid.uuid4()

    event = UploadCreated()
    event.upload_id = str(upload_id)
    event.user_id = str(user_id)
    event.upload_snapshot = MagicMock()
    event.upload_snapshot.id = str(upload_id)
    event.upload_snapshot.user_id = str(user_id)
    event.upload_snapshot.filename = "resume.pdf"
    event.upload_snapshot.content_type = "application/pdf"
    event.upload_snapshot.file_size = 1024
    event.upload_snapshot.storage_key = "uploads/resume.pdf"
    event.upload_snapshot.upload_type = SimpleNamespace(name="RESUME")
    event.upload_snapshot.created_at = datetime.now(UTC)
    return event


@pytest.mark.asyncio
async def test_account_updated_idempotent() -> None:
    """AccountUpdated upsert emits ON CONFLICT DO UPDATE on every replay."""
    event = _make_account_event()
    session = _capture_session()
    ctx = _ctx("user.auth.account-updated.v1", db_session=session)

    await handle_account_updated(event, ctx)
    await handle_account_updated(event, ctx)

    assert session.execute.await_count >= 2
    _assert_has_upsert(session.statements)


@pytest.mark.asyncio
async def test_profile_created_replay_refreshes_extended_profile_fields() -> None:
    """A repeated create snapshot refreshes schema, weighting, and lifecycle fields."""
    event = _make_profile_created_event()
    session = _capture_session()
    ctx = _ctx("user.pref.created.v1", db_session=session)

    await handle_profile_created(event, ctx)
    await handle_profile_created(event, ctx)

    assert session.execute.await_count >= 2
    _assert_has_upsert(session.statements)
    set_clause = session.statements[0].partition("DO UPDATE SET")[2]
    assert all(f"{field} =" in set_clause for field in ("tailoring_schema_id", "feature_importance", "is_active"))
    assert {
        "skill_match_importance": 10,
        "location_importance": 20,
        "work_arrangement_importance": 30,
        "experience_importance": 40,
        "salary_importance": 50,
        "recency_importance": 60,
    } in session.parameters[0].values()


@pytest.mark.asyncio
async def test_profile_updated_refreshes_extended_profile_fields() -> None:
    """Updated snapshots persist schema, six-part weighting, and active state on conflict."""
    event = _make_profile_created_event()
    event.__class__ = PrefUpdated
    session = _capture_session()
    ctx = _ctx("user.pref.updated.v1", db_session=session)

    await handle_profile_updated(event, ctx)
    await handle_profile_updated(event, ctx)

    assert session.execute.await_count >= 2
    _assert_has_upsert(session.statements)
    set_clause = session.statements[0].partition("DO UPDATE SET")[2]
    assert all(f"{field} =" in set_clause for field in ("tailoring_schema_id", "feature_importance", "is_active"))
    assert {
        "skill_match_importance": 10,
        "location_importance": 20,
        "work_arrangement_importance": 30,
        "experience_importance": 40,
        "salary_importance": 50,
        "recency_importance": 60,
    } in session.parameters[0].values()


@pytest.mark.asyncio
async def test_listing_created_idempotent() -> None:
    """ListingCreated upsert is guarded by version predicate to reject stale snapshots."""
    event = _make_listing_event()
    session = _capture_session()
    ctx = _ctx("job.listing.created.v1", db_session=session)

    await handle_listing_created(event, ctx)
    await handle_listing_created(event, ctx)

    assert session.execute.await_count >= 2
    _assert_has_upsert(session.statements)
    # Out-of-order delivery guard: the WHERE clause prevents an older snapshot
    # from regressing version on disk.
    assert any("WHERE" in s and "version" in s for s in session.statements), (
        f"Expected ON CONFLICT ... WHERE version <= ... guard; got: {session.statements}"
    )


@pytest.mark.asyncio
async def test_correlation_replay_refreshes_identity_and_listing_snapshot() -> None:
    """A correlation conflict refreshes ownership and every user-visible listing field."""
    event = _make_correlation_event()
    session = _capture_session()
    ctx = _ctx("job.correlation.evaluated.v1", db_session=session)

    await handle_correlation_evaluated(event, ctx)
    await handle_correlation_evaluated(event, ctx)

    assert session.execute.await_count >= 2
    _assert_has_upsert(session.statements)
    set_clause = session.statements[0].partition("DO UPDATE SET")[2]
    assert all(
        f"{field} =" in set_clause
        for field in (
            "id",
            "user_id",
            "listing_title",
            "listing_company",
            "listing_url",
            "listing_location",
        )
    )


@pytest.mark.asyncio
async def test_skill_created_idempotent() -> None:
    """SkillCreated handler emits an idempotent ON CONFLICT statement."""
    event = _make_skill_event()
    session = _capture_session()
    ctx = _ctx("skill.fct.skill-created.v1", db_session=session)

    await handle_skill_created(event, ctx)
    await handle_skill_created(event, ctx)

    assert session.execute.await_count >= 2
    _assert_has_idempotent_write(session.statements)


@pytest.mark.asyncio
async def test_settings_created_idempotent() -> None:
    """UserPrefSettingsCreated handler emits ON CONFLICT DO NOTHING."""
    event = _make_settings_event(UserPrefSettingsCreated)
    session = _capture_session()
    ctx = _ctx("user.pref.settings-created.v1", db_session=session)

    await handle_user_pref_settings_created(event, ctx)
    await handle_user_pref_settings_created(event, ctx)

    assert session.execute.await_count >= 2
    _assert_has_idempotent_write(session.statements)


@pytest.mark.asyncio
async def test_settings_updated_idempotent() -> None:
    """UserPrefSettingsUpdated handler emits ON CONFLICT DO UPDATE."""
    event = _make_settings_event(UserPrefSettingsUpdated)
    session = _capture_session()
    ctx = _ctx("user.pref.settings-updated.v1", db_session=session)

    await handle_user_pref_settings_updated(event, ctx)
    await handle_user_pref_settings_updated(event, ctx)

    assert session.execute.await_count >= 2
    _assert_has_upsert(session.statements)


@pytest.mark.asyncio
async def test_attachment_created_idempotent() -> None:
    """UploadCreated handler emits ON CONFLICT DO NOTHING for safe replay."""
    event = _make_attachment_event()
    session = _capture_session()
    ctx = _ctx("user.upload.created.v1", db_session=session)

    await handle_attachment_created(event, ctx)
    await handle_attachment_created(event, ctx)

    assert session.execute.await_count >= 2
    _assert_has_idempotent_write(session.statements)


@pytest.mark.asyncio
async def test_listing_created_does_not_regress_version() -> None:
    """A stale snapshot (lower version) must not overwrite a newer projection.

    The handler relies on PostgreSQL's ``ON CONFLICT ... WHERE excluded.version
    >= existing.version`` predicate to discard out-of-order events. We can't
    exercise the real predicate without a database, so we verify the compiled
    SQL preserves the version guard for both an older and newer snapshot.
    """
    older = _make_listing_event()
    older.listing_snapshot.version = 3
    newer = _make_listing_event()
    newer.listing_snapshot.id = older.listing_snapshot.id
    newer.listing.id = older.listing.id
    newer.listing_snapshot.version = 5

    session = _capture_session()
    ctx = _ctx("job.listing.created.v1", db_session=session)

    await handle_listing_created(newer, ctx)
    await handle_listing_created(older, ctx)

    assert session.execute.await_count == 2
    for stmt in session.statements:
        assert "ON CONFLICT" in stmt
        assert "WHERE" in stmt
        assert "version" in stmt


@pytest.mark.asyncio
async def test_access_token_revocation_duplicate_uses_conflict_update() -> None:
    """Duplicate JTI delivery remains an idempotent write with exact event expiry."""
    session = _capture_session()
    user_id = uuid.uuid4()
    jti = uuid.uuid4()
    expires_at = datetime.now(UTC) + timedelta(minutes=5)

    await record_access_token_revocation(
        cast("AsyncSession", session), user_id=user_id, jti=str(jti), expires_at=expires_at
    )
    await record_access_token_revocation(
        cast("AsyncSession", session), user_id=user_id, jti=str(jti), expires_at=expires_at
    )

    assert len(session.statements) == 2
    assert all("ON CONFLICT (jti) DO UPDATE" in statement for statement in session.statements)
    assert all({jti, user_id, expires_at} <= set(parameters.values()) for parameters in session.parameters)


@pytest.mark.asyncio
@pytest.mark.parametrize("delta", [timedelta(minutes=-1), timedelta(minutes=1)])
async def test_account_cutoff_replay_is_monotonic_and_cannot_downgrade_permanence(delta: timedelta) -> None:
    session = _capture_session()
    first = datetime.now(UTC)
    replayed = first + delta
    user_id = uuid.uuid4()

    await record_user_revocation_cutoff(
        cast("AsyncSession", session),
        user_id=user_id,
        revoked_before=first,
        is_permanent=True,
    )
    await record_user_revocation_cutoff(
        cast("AsyncSession", session),
        user_id=user_id,
        revoked_before=replayed,
        is_permanent=False,
    )

    assert len(session.statements) == 2
    assert all("ON CONFLICT (user_id) DO UPDATE" in statement for statement in session.statements)
    assert all("greatest(" in statement.lower() for statement in session.statements)
    assert all("is_permanent OR excluded.is_permanent" in statement for statement in session.statements)
    assert {user_id, first, True} <= set(session.parameters[0].values())
    assert {user_id, replayed, False} <= set(session.parameters[1].values())


@pytest.mark.asyncio
async def test_access_token_revocation_rejects_malformed_jti_before_db() -> None:
    """Malformed token identifiers never reach PostgreSQL."""
    session = _capture_session()

    with pytest.raises(ValueError, match="badly formed hexadecimal UUID string"):
        await record_access_token_revocation(
            cast("AsyncSession", session),
            user_id=uuid.uuid4(),
            jti="not-a-uuid",
            expires_at=datetime.now(UTC),
        )

    session.execute.assert_not_awaited()
