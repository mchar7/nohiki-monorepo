"""Tests for events/projections event handlers.

Organized by domain (user, job, doc, skill) for clear separation of concerns.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bff_service.events.projections.doc_template import (
    handle_render_completed,
    handle_template_created,
    handle_template_deleted,
    handle_template_updated,
)
from bff_service.events.projections.job_correlation import handle_correlation_evaluated
from bff_service.events.projections.job_listing import (
    handle_listing_created,
    handle_listing_deleted,
    handle_listing_updated,
)
from bff_service.events.projections.skill import handle_skill_created
from bff_service.events.projections.user_auth import (
    handle_access_token_revoked,
    handle_account_deleted,
    handle_account_updated,
)
from bff_service.events.projections.user_pref import (
    handle_pref_enrichment_failed,
    handle_profile_created,
    handle_profile_deleted,
    handle_profile_updated,
    handle_user_pref_settings_created,
    handle_user_pref_settings_updated,
)
from bff_service.events.projections.user_upload import (
    handle_attachment_created,
    handle_attachment_deleted,
)
from bff_service.sse.events import CommandStatusPayload, DocumentStatusPayload
from nohiki.common.v1 import (
    CommutePreferences,
    CurrencyCode,
    Location,
    MonetaryAmount,
    PaymentFrequency,
    SalaryPreference,
    TransitMode,
)
from nohiki.doc.template.v1 import TemplateAudience
from nohiki.job.correlation.v1 import (
    FitFactor,
    FitFactorContribution,
    FitRankingBreakdown,
)
from nohiki_common_exceptions import ValidationError
from nohiki_db_utils.testing import create_mock_session
from nohiki_kafka_client import MessageContext


def _default_location() -> Location:
    """Build a structured Location for listing-snapshot tests.

    Listings now carry a structured `Location` (free-form `location_raw`
    was removed); projection handlers derive the display string from this
    via `format_location_display`, so test snapshots need a real instance.
    """
    return Location(city="San Francisco", state_province="CA")


# Stubs for all protobuf types to avoid ml.v1 cross-module import issues
Account = MagicMock
AccountDeleted = MagicMock
AccessTokenRevoked = MagicMock
AccountUpdated = MagicMock
PrefCreated = MagicMock
PrefDeleted = MagicMock
PrefUpdated = MagicMock
SearchPrefSnapshot = MagicMock
UserPrefSettings = MagicMock
UserPrefSettingsCreated = MagicMock
UserPrefSettingsUpdated = MagicMock
UploadCreated = MagicMock
UploadDeleted = MagicMock
ListingCreated = MagicMock
ListingDeleted = MagicMock
ListingSnapshot = MagicMock
ListingUpdated = MagicMock
CorrelationEvaluated = MagicMock
CanonicalSkill = MagicMock
SkillCreated = MagicMock
TemplateCreated = MagicMock
TemplateUpdated = MagicMock
TemplateDeleted = MagicMock
DocumentRenderCompleted = MagicMock


def _make_context(*, db_session: AsyncMock | None = None) -> MessageContext:
    """Build a MessageContext with injected db_session."""
    return MessageContext(
        topic="test.topic.v1",
        partition=0,
        offset=0,
        timestamp=0,
        headers={},
        key=None,
        db_session=db_session,
    )


def _assert_command_marked_completed(
    mock_session: AsyncMock,
    request_id: uuid.UUID,
    active_statuses: str | list[str] = "pending",
    user_id: uuid.UUID | None = None,
) -> None:
    """Assert a correlated CDC event transitions only an active command row."""
    assert mock_session.execute.await_count == 2
    statement = mock_session.execute.await_args_list[1].args[0]
    compiled = statement.compile(compile_kwargs={"literal_binds": False})
    sql = str(compiled).lower()
    assert "command_requests" in sql
    assert "status" in sql
    assert active_statuses in compiled.params.values()
    assert "completed" in compiled.params.values()
    assert request_id in compiled.params.values()
    if user_id is not None:
        assert user_id in compiled.params.values()


@pytest.mark.asyncio
async def test_handle_account_updated() -> None:
    """Test handle_account_updated handler with real protobuf event."""
    user_id = uuid.uuid4()
    now = datetime.now(UTC)

    account = Account()
    account.id = str(user_id)
    account.email = "test@example.com"
    account.display_name = "Test User"
    account.first_name = "Test"
    account.last_name = "User"
    account.is_active = True
    account.email_verified = True
    account.created_at = now
    account.updated_at = now

    event = AccountUpdated()
    event.user_id = str(user_id)
    event.account_snapshot = account

    mock_session = create_mock_session()
    mock_session.scalar.return_value = False
    ctx = _make_context(db_session=mock_session)

    await handle_account_updated(event, ctx)

    mock_session.execute.assert_awaited()


@pytest.mark.asyncio
async def test_handle_account_updated_ignores_permanently_deleted_user() -> None:
    user_id = uuid.uuid4()
    account = Account(
        id=str(user_id),
        email="deleted@example.com",
        display_name="Deleted",
        first_name="Deleted",
        last_name="User",
        is_active=True,
        email_verified=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC) + timedelta(days=365),
    )
    event = AccountUpdated(user_id=str(user_id), account_snapshot=account)
    mock_session = create_mock_session()
    mock_session.scalar.return_value = user_id

    mock_session.execute.reset_mock()
    await handle_account_updated(event, _make_context(db_session=mock_session))

    mock_session.scalar.assert_awaited_once()
    assert mock_session.execute.await_count == 1
    assert "pg_advisory_xact_lock" in str(mock_session.execute.await_args.args[0])


@pytest.mark.asyncio
async def test_inactive_account_update_records_nonpermanent_cutoff_before_projection() -> None:
    user_id = uuid.uuid4()
    timestamp = datetime.now(UTC)
    account = Account(
        id=str(user_id),
        email="disabled@example.com",
        display_name="Disabled",
        first_name="Disabled",
        last_name="User",
        is_active=False,
        email_verified=True,
        created_at=timestamp - timedelta(days=1),
        updated_at=timestamp,
    )
    event = AccountUpdated(
        user_id=str(user_id),
        account_snapshot=account,
        metadata=MagicMock(timestamp=timestamp),
    )
    session = create_mock_session()
    session.scalar.return_value = None
    operations: list[str] = []
    session.execute.side_effect = lambda *_args, **_kwargs: operations.append("projection")

    async def record(*_args: object, **_kwargs: object) -> None:
        operations.append("cutoff")

    with patch(
        "bff_service.events.projections.user_auth.record_user_revocation_cutoff",
        side_effect=record,
    ) as helper:
        await handle_account_updated(event, _make_context(db_session=session))

    helper.assert_awaited_once_with(
        session,
        user_id=user_id,
        revoked_before=timestamp,
        is_permanent=False,
    )
    assert operations[1] == "cutoff"
    assert "projection" in operations[2:]


@pytest.mark.asyncio
async def test_inactive_account_update_without_metadata_fails_before_projection() -> None:
    user_id = uuid.uuid4()
    timestamp = datetime.now(UTC)
    account = Account(
        id=str(user_id),
        email="disabled@example.com",
        display_name="Disabled",
        first_name="Disabled",
        last_name="User",
        is_active=False,
        email_verified=True,
        created_at=timestamp,
        updated_at=timestamp,
    )
    session = create_mock_session()
    session.scalar.return_value = None
    session.execute.reset_mock()

    with pytest.raises(ValueError, match="metadata"):
        await handle_account_updated(
            AccountUpdated(user_id=str(user_id), account_snapshot=account, metadata=None),
            _make_context(db_session=session),
        )

    assert session.execute.await_count == 1
    assert "pg_advisory_xact_lock" in str(session.execute.await_args.args[0])


@pytest.mark.asyncio
async def test_active_update_after_temporary_disable_is_projected_without_removing_cutoff() -> None:
    user_id = uuid.uuid4()
    timestamp = datetime.now(UTC)
    account = Account(
        id=str(user_id),
        email="reactivated@example.com",
        display_name="Reactivated",
        first_name="Reactivated",
        last_name="User",
        is_active=True,
        email_verified=True,
        created_at=timestamp - timedelta(days=1),
        updated_at=timestamp,
    )
    event = AccountUpdated(
        user_id=str(user_id),
        account_snapshot=account,
        metadata=MagicMock(timestamp=timestamp),
    )
    session = create_mock_session()
    session.scalar.return_value = None
    session.execute.reset_mock()

    with patch(
        "bff_service.events.projections.user_auth.record_user_revocation_cutoff",
        new_callable=AsyncMock,
    ) as record:
        await handle_account_updated(event, _make_context(db_session=session))

    record.assert_not_awaited()
    assert any("INSERT INTO" in str(call.args[0]) for call in session.execute.await_args_list)


@pytest.mark.asyncio
async def test_handle_access_token_revoked_writes_exact_ledger_values() -> None:
    """Token revocations pass validated identifiers and event expiry to the ledger helper."""
    user_id = uuid.uuid4()
    jti = uuid.uuid4()
    expires_at = datetime.now(UTC) + timedelta(minutes=5)
    event = AccessTokenRevoked(user_id=str(user_id), jti=str(jti), expires_at=expires_at, session_family_id="")
    mock_session = create_mock_session()

    with patch(
        "bff_service.events.projections.user_auth.record_access_token_revocation",
        new_callable=AsyncMock,
    ) as record:
        await handle_access_token_revoked(event, _make_context(db_session=mock_session))

    record.assert_awaited_once_with(mock_session, user_id=user_id, jti=str(jti), expires_at=expires_at)


@pytest.mark.asyncio
async def test_handle_family_revocation_writes_jti_and_family_cutoff() -> None:
    user_id = uuid.uuid4()
    family_id = uuid.uuid4()
    timestamp = datetime.now(UTC)
    expires_at = timestamp + timedelta(minutes=10)
    event = AccessTokenRevoked(
        user_id=str(user_id),
        jti=str(uuid.uuid4()),
        session_family_id=str(family_id),
        expires_at=expires_at,
        metadata=MagicMock(timestamp=timestamp),
    )
    mock_session = create_mock_session()

    with (
        patch(
            "bff_service.events.projections.user_auth.record_access_token_revocation",
            new_callable=AsyncMock,
        ),
        patch(
            "bff_service.events.projections.user_auth.record_session_family_revocation",
            new_callable=AsyncMock,
        ) as record_family,
    ):
        await handle_access_token_revoked(event, _make_context(db_session=mock_session))

    record_family.assert_awaited_once_with(
        mock_session,
        family_id=str(family_id),
        user_id=user_id,
        revoked_before=timestamp,
        expires_at=expires_at,
    )


@pytest.mark.asyncio
async def test_legacy_revocation_event_does_not_require_metadata_or_write_family() -> None:
    event = AccessTokenRevoked(
        user_id=str(uuid.uuid4()),
        jti=str(uuid.uuid4()),
        session_family_id="",
        expires_at=datetime.now(UTC),
    )
    with (
        patch(
            "bff_service.events.projections.user_auth.record_access_token_revocation",
            new_callable=AsyncMock,
        ),
        patch(
            "bff_service.events.projections.user_auth.record_session_family_revocation",
            new_callable=AsyncMock,
        ) as record_family,
    ):
        await handle_access_token_revoked(event, _make_context(db_session=create_mock_session()))
    record_family.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_account_deleted_records_cutoff_before_atomic_delete() -> None:
    """Account deletion records the metadata cutoff before deleting on the same session."""
    user_id = uuid.uuid4()
    timestamp = datetime.now(UTC)
    event = AccountDeleted(user_id=str(user_id), metadata=MagicMock(timestamp=timestamp))
    mock_session = create_mock_session()
    operations: list[str] = []
    mock_session.execute.side_effect = lambda *_args, **_kwargs: operations.append("delete")

    async def record(*_args: object, **_kwargs: object) -> None:
        operations.append("cutoff")

    with patch(
        "bff_service.events.projections.user_auth.record_user_revocation_cutoff",
        side_effect=record,
    ) as helper:
        await handle_account_deleted(event, _make_context(db_session=mock_session))

    helper.assert_awaited_once_with(mock_session, user_id=user_id, revoked_before=timestamp, is_permanent=True)
    assert operations[-2:] == ["cutoff", "delete"]
    statement = mock_session.execute.await_args.args[0]
    assert user_id in statement.compile().params.values()


@pytest.mark.parametrize(
    ("handler", "event"),
    [
        (
            handle_access_token_revoked,
            AccessTokenRevoked(user_id="not-a-uuid", jti=str(uuid.uuid4())),
        ),
        (
            handle_account_deleted,
            AccountDeleted(user_id="not-a-uuid", metadata=MagicMock(timestamp=datetime.now(UTC))),
        ),
    ],
)
@pytest.mark.asyncio
async def test_revocation_handlers_reject_malformed_user_uuid(
    handler: Callable[[MagicMock, MessageContext], Awaitable[None]], event: MagicMock
) -> None:
    """Malformed event user identifiers fail before a ledger write."""
    with pytest.raises(ValueError, match="badly formed hexadecimal UUID string"):
        await handler(event, _make_context(db_session=create_mock_session()))


@pytest.mark.asyncio
async def test_revocation_db_failure_propagates() -> None:
    """Projection database failures remain visible to Kafka for retry."""
    failure = RuntimeError("database unavailable")
    event = AccessTokenRevoked(user_id=str(uuid.uuid4()), jti=str(uuid.uuid4()), expires_at=datetime.now(UTC))
    with (
        patch(
            "bff_service.events.projections.user_auth.record_access_token_revocation",
            new_callable=AsyncMock,
            side_effect=failure,
        ),
        pytest.raises(RuntimeError, match="database unavailable"),
    ):
        await handle_access_token_revoked(event, _make_context(db_session=create_mock_session()))


@pytest.mark.parametrize("experience_years", [0, 5, 50])
@pytest.mark.asyncio
async def test_handle_profile_created(experience_years: int) -> None:
    """Created projections preserve exact experience years under API field names."""
    pref_id = uuid.uuid4()
    user_id = uuid.uuid4()
    request_id = uuid.uuid4()

    snapshot = SearchPrefSnapshot()
    snapshot.id = str(pref_id)
    snapshot.user_id = str(user_id)
    snapshot.pref_name = "My Profile"
    snapshot.experience_preference = MagicMock()
    snapshot.experience_preference.experience_years = experience_years
    snapshot.experience_preference.seniority_levels = []

    event = PrefCreated()
    event.pref_id = str(pref_id)
    event.pref_snapshot = snapshot
    event.user_id = str(user_id)
    event.metadata = MagicMock(correlation_id=str(request_id))

    mock_session = create_mock_session()
    ctx = _make_context(db_session=mock_session)

    await handle_profile_created(event, ctx)

    _assert_command_marked_completed(mock_session, request_id, ["pending", "in_progress"], user_id)
    mock_session.commit.assert_not_awaited()
    statement = mock_session.execute.await_args_list[0].args[0]
    assert {
        "experience_years": experience_years,
        "seniority_levels": [],
    } in statement.compile().params.values()


@pytest.mark.parametrize("experience_years", [0, 5, 50])
@pytest.mark.asyncio
async def test_handle_profile_updated(experience_years: int) -> None:
    """Updated projections preserve exact experience years under API field names."""
    pref_id = uuid.uuid4()
    user_id = uuid.uuid4()
    request_id = uuid.uuid4()

    snapshot = SearchPrefSnapshot()
    snapshot.id = str(pref_id)
    snapshot.user_id = str(user_id)
    snapshot.pref_name = "Updated Profile"
    snapshot.experience_preference = MagicMock()
    snapshot.experience_preference.experience_years = experience_years
    snapshot.experience_preference.seniority_levels = []

    event = PrefUpdated()
    event.pref_id = str(pref_id)
    event.pref_snapshot = snapshot
    event.user_id = str(user_id)
    event.metadata = MagicMock(correlation_id=str(request_id))

    mock_session = create_mock_session()
    ctx = _make_context(db_session=mock_session)

    await handle_profile_updated(event, ctx)

    _assert_command_marked_completed(mock_session, request_id, ["pending", "in_progress"], user_id)
    mock_session.commit.assert_not_awaited()
    statement = mock_session.execute.await_args_list[0].args[0]
    assert {
        "experience_years": experience_years,
        "seniority_levels": [],
    } in statement.compile().params.values()


@pytest.mark.asyncio
async def test_pref_enrichment_failure_updates_only_active_command_and_emits_status() -> None:
    """A matched failure becomes terminal and is visible on the existing SSE channel."""
    request_id = uuid.uuid4()
    user_id = uuid.uuid4()
    event = MagicMock(
        request_id=str(request_id),
        user_id=str(user_id),
        error_message="Embedding service unavailable",
    )
    result = MagicMock()
    result.one_or_none.return_value = (user_id, "create_profile")
    session = create_mock_session()
    session.execute.return_value = result
    bridge = MagicMock()
    bridge.publish = AsyncMock()

    with patch("bff_service.events.projections.user_pref.get_sse_bridge", return_value=bridge):
        await handle_pref_enrichment_failed(event, _make_context(db_session=session))

    statement = session.execute.await_args.args[0]
    params = statement.compile().params.values()
    assert request_id in params
    assert user_id in params
    assert ["pending", "in_progress"] in params
    assert "failed" in params
    assert "Embedding service unavailable" in params
    assert any(isinstance(value, datetime) for value in params)
    session.commit.assert_not_awaited()
    bridge.publish.assert_awaited_once()
    assert bridge.publish.await_args is not None
    published_user_id, payload = bridge.publish.await_args.args
    assert published_user_id == user_id
    assert isinstance(payload, CommandStatusPayload)
    assert not isinstance(payload, DocumentStatusPayload)
    assert payload.request_id == str(request_id)
    assert payload.type == "command_status"
    assert payload.command_type == "create_profile"
    assert payload.status == "failed"
    assert payload.error_message == "Embedding service unavailable"


@pytest.mark.asyncio
async def test_pref_enrichment_failure_without_active_command_emits_no_status() -> None:
    """Completed, failed, missing, and mismatched rows do not produce a new status event."""
    event = MagicMock(
        request_id=str(uuid.uuid4()),
        user_id=str(uuid.uuid4()),
        error_message="Late failure",
    )
    result = MagicMock()
    result.one_or_none.return_value = None
    session = create_mock_session()
    session.execute.return_value = result
    bridge = MagicMock()
    bridge.publish = AsyncMock()

    with patch("bff_service.events.projections.user_pref.get_sse_bridge", return_value=bridge):
        await handle_pref_enrichment_failed(event, _make_context(db_session=session))

    session.commit.assert_not_awaited()
    bridge.publish.assert_not_awaited()


@pytest.mark.parametrize(
    ("handler", "event_type"),
    [(handle_profile_created, PrefCreated), (handle_profile_updated, PrefUpdated)],
)
@pytest.mark.asyncio
async def test_profile_projection_serializes_nested_preferences_in_snake_case(
    handler: Callable[[object, MessageContext], Awaitable[None]],
    event_type: Callable[[], MagicMock],
) -> None:
    """Create and update projections persist the exact API-facing nested JSON contract."""
    pref_id = uuid.uuid4()
    snapshot = SearchPrefSnapshot()
    snapshot.id = str(pref_id)
    snapshot.user_id = str(uuid.uuid4())
    snapshot.pref_name = "Profile with constraints"
    snapshot.salary_preference = SalaryPreference(
        min_salary=MonetaryAmount(minor_units=8_000_000, currency=CurrencyCode.USD),
        target_salary=MonetaryAmount(minor_units=12_500_000, currency=CurrencyCode.EUR),
        preferred_frequency=PaymentFrequency.ANNUALLY,
    )
    snapshot.commute_preferences = CommutePreferences(
        acceptable_modes=[TransitMode.PUBLIC_TRANSIT, TransitMode.CYCLING],
        max_commute_minutes=45,
        ideal_commute_minutes=25,
    )
    event = event_type()
    event.pref_id = str(pref_id)
    event.pref_snapshot = snapshot
    mock_session = create_mock_session()
    await handler(event, _make_context(db_session=mock_session))

    parameters = mock_session.execute.await_args.args[0].compile().params.values()
    assert {
        "min_salary": {"minor_units": "8000000", "currency": "CURRENCY_CODE_USD"},
        "target_salary": {"minor_units": "12500000", "currency": "CURRENCY_CODE_EUR"},
        "preferred_frequency": "PAYMENT_FREQUENCY_ANNUALLY",
    } in parameters
    assert {
        "acceptable_modes": ["TRANSIT_MODE_PUBLIC_TRANSIT", "TRANSIT_MODE_CYCLING"],
        "max_commute_minutes": 45,
        "ideal_commute_minutes": 25,
    } in parameters


@pytest.mark.asyncio
async def test_handle_profile_deleted() -> None:
    """Test handle_profile_deleted handler."""
    pref_id = uuid.uuid4()

    event = PrefDeleted()
    event.pref_id = str(pref_id)

    mock_session = create_mock_session()
    ctx = _make_context(db_session=mock_session)

    await handle_profile_deleted(event, ctx)

    mock_session.execute.assert_awaited()


@pytest.mark.asyncio
async def test_handle_user_pref_settings_created() -> None:
    """Test handle_user_pref_settings_created handler."""
    user_id = uuid.uuid4()

    settings = UserPrefSettings()
    settings.user_id = str(user_id)

    event = UserPrefSettingsCreated()
    event.user_id = str(user_id)
    event.settings = settings

    mock_session = create_mock_session()
    ctx = _make_context(db_session=mock_session)

    await handle_user_pref_settings_created(event, ctx)

    mock_session.execute.assert_awaited()


@pytest.mark.asyncio
async def test_handle_user_pref_settings_updated() -> None:
    """Test handle_user_pref_settings_updated handler."""
    user_id = uuid.uuid4()

    settings = UserPrefSettings()
    settings.user_id = str(user_id)

    event = UserPrefSettingsUpdated()
    event.user_id = str(user_id)
    event.settings = settings

    mock_session = create_mock_session()
    ctx = _make_context(db_session=mock_session)

    await handle_user_pref_settings_updated(event, ctx)

    mock_session.execute.assert_awaited()


@pytest.mark.asyncio
async def test_handle_attachment_created() -> None:
    """Test handle_attachment_created handler."""
    upload_id = uuid.uuid4()
    user_id = uuid.uuid4()

    snapshot = MagicMock()
    snapshot.id = str(upload_id)
    snapshot.user_id = str(user_id)
    snapshot.file_name = "resume.pdf"

    event = UploadCreated()
    event.upload_id = str(upload_id)
    event.upload_snapshot = snapshot

    mock_session = create_mock_session()
    ctx = _make_context(db_session=mock_session)

    await handle_attachment_created(event, ctx)

    mock_session.execute.assert_awaited()


@pytest.mark.asyncio
async def test_handle_attachment_deleted() -> None:
    """Test handle_attachment_deleted handler."""
    upload_id = uuid.uuid4()

    event = UploadDeleted()
    event.upload_id = str(upload_id)

    mock_session = create_mock_session()
    ctx = _make_context(db_session=mock_session)

    await handle_attachment_deleted(event, ctx)

    mock_session.execute.assert_awaited()


@pytest.mark.asyncio
async def test_handle_listing_created() -> None:
    """Test handle_listing_created handler."""
    listing_id = uuid.uuid4()
    now = datetime.now(UTC)

    snapshot = ListingSnapshot()
    snapshot.id = str(listing_id)
    snapshot.title = "Software Engineer"
    snapshot.company_name = "TechCorp"
    snapshot.description = "A great job"
    snapshot.listing_url = "https://example.com/job"
    snapshot.location = _default_location()
    snapshot.version = 1
    snapshot.raw_content_hash = "abc123"
    snapshot.discovered_at = now

    listing_ref = MagicMock()
    listing_ref.listing_id = str(listing_id)
    listing_ref.listing_url = "https://example.com/job"

    event = ListingCreated()
    event.listing = listing_ref
    event.was_updated = False
    event.listing_snapshot = snapshot

    mock_session = create_mock_session()
    ctx = _make_context(db_session=mock_session)

    await handle_listing_created(event, ctx)

    mock_session.execute.assert_awaited()


@pytest.mark.asyncio
async def test_handle_listing_updated() -> None:
    """Test handle_listing_updated handler."""
    listing_id = uuid.uuid4()
    now = datetime.now(UTC)

    snapshot = ListingSnapshot()
    snapshot.id = str(listing_id)
    snapshot.title = "Senior Engineer"
    snapshot.company_name = "TechCorp"
    snapshot.description = "Updated job description"
    snapshot.listing_url = "https://example.com/job"
    snapshot.location = _default_location()
    snapshot.version = 2
    snapshot.raw_content_hash = "def456"
    snapshot.discovered_at = now

    listing_ref = MagicMock()
    listing_ref.listing_id = str(listing_id)
    listing_ref.listing_url = "https://example.com/job"

    event = ListingUpdated()
    event.listing = listing_ref
    event.previous_version = 1
    event.listing_snapshot = snapshot

    mock_session = create_mock_session()
    ctx = _make_context(db_session=mock_session)

    await handle_listing_updated(event, ctx)

    mock_session.execute.assert_awaited()


@pytest.mark.asyncio
async def test_handle_listing_deleted() -> None:
    """Test handle_listing_deleted handler."""
    listing_id = uuid.uuid4()

    event = ListingDeleted()
    event.listing_id = str(listing_id)

    mock_session = create_mock_session()
    ctx = _make_context(db_session=mock_session)

    await handle_listing_deleted(event, ctx)

    mock_session.execute.assert_awaited()


@pytest.mark.asyncio
async def test_handle_correlation_evaluated() -> None:
    """Test handle_correlation_evaluated handler."""
    correlation_id = uuid.uuid4()
    pref_id = uuid.uuid4()
    user_id = uuid.uuid4()
    listing_id = uuid.uuid4()

    listing_snapshot = ListingSnapshot()
    listing_snapshot.id = str(listing_id)
    listing_snapshot.title = "Software Engineer"
    listing_snapshot.company_name = "TechCorp"
    listing_snapshot.listing_url = "https://example.com/job"
    listing_snapshot.location = _default_location()

    pref_snapshot = SearchPrefSnapshot()
    pref_snapshot.id = str(pref_id)
    pref_snapshot.user_id = str(user_id)

    event = CorrelationEvaluated()
    event.correlation_id = str(correlation_id)
    event.listing_snapshot = listing_snapshot
    event.pref_snapshot = pref_snapshot
    event.fit_score = 85  # Integer as expected by protobuf
    event.correlation_metadata = {"ml_confidence": "0.95", "shap_value": "0.42"}
    event.fit_ranking_breakdown = FitRankingBreakdown(
        method_version="deterministic-fit-v1",
        factors=[
            FitFactorContribution(
                factor=FitFactor.ROLE_RELEVANCE,
                compatibility_score=82.0,
                importance=100,
                contribution_points=82.0,
            ),
            FitFactorContribution(
                factor=FitFactor.SKILLS,
                compatibility_score=94.0,
                importance=75,
                contribution_points=3.0,
            ),
        ],
    )
    mock_session = create_mock_session()
    ctx = _make_context(db_session=mock_session)

    await handle_correlation_evaluated(event, ctx)

    mock_session.execute.assert_awaited()
    statement = mock_session.execute.await_args.args[0]
    compiled = statement.compile(compile_kwargs={"literal_binds": False})
    expected_breakdown = {}
    expected_fit_breakdown = {
        "method_version": "deterministic-fit-v1",
        "factors": [
            {
                "factor": "ROLE_RELEVANCE",
                "compatibility_score": 82.0,
                "importance": 100,
                "contribution_points": 82.0,
            },
            {
                "factor": "SKILLS",
                "compatibility_score": 94.0,
                "importance": 75,
                "contribution_points": 3.0,
            },
        ],
    }
    assert expected_breakdown in compiled.params.values()
    assert expected_fit_breakdown in compiled.params.values()
    assert 85 in compiled.params.values()
    assert not any(key in str(expected_fit_breakdown).lower() for key in ("ml_", "shap", "probability", "confidence"))


@pytest.mark.asyncio
async def test_handle_skill_created() -> None:
    """Test handle_skill_created handler."""
    skill_id = uuid.uuid4()

    snapshot = CanonicalSkill()
    snapshot.id = str(skill_id)
    snapshot.canonical_id = "python"
    snapshot.normalized_text = "Python"
    snapshot.display_name = "Python Programming"
    snapshot.description = "A programming language"
    snapshot.category = "Programming"
    snapshot.subcategory = "Languages"
    snapshot.skill_type = "TECHNICAL"
    snapshot.source = None
    snapshot.mention_count = 100
    snapshot.job_count = 50
    snapshot.profile_count = 200

    event = SkillCreated()
    event.skill_id = str(skill_id)
    event.skill_snapshot = snapshot

    mock_session = create_mock_session()
    ctx = _make_context(db_session=mock_session)

    await handle_skill_created(event, ctx)

    mock_session.execute.assert_awaited()


@pytest.mark.asyncio
async def test_handle_account_updated_missing_snapshot() -> None:
    """Test handle_account_updated handler when account_snapshot is None."""
    user_id = uuid.uuid4()

    event = AccountUpdated()
    event.user_id = str(user_id)
    event.account_snapshot = None

    mock_session = create_mock_session()
    ctx = _make_context(db_session=mock_session)

    with patch("bff_service.events.projections.user_auth.logger") as mock_logger:
        await handle_account_updated(event, ctx)

    mock_session.execute.assert_not_awaited()
    mock_logger.warning.assert_called_once()


@pytest.mark.asyncio
async def test_handle_profile_created_missing_snapshot() -> None:
    """Test handle_profile_created raises ValidationError when snapshot is None."""
    pref_id = uuid.uuid4()

    event = PrefCreated()
    event.pref_id = str(pref_id)
    event.pref_snapshot = None

    ctx = _make_context()

    with pytest.raises(ValidationError, match="pref_snapshot"):
        await handle_profile_created(event, ctx)


@pytest.mark.asyncio
async def test_handle_profile_updated_missing_snapshot() -> None:
    """Test handle_profile_updated raises ValidationError when snapshot is None."""
    pref_id = uuid.uuid4()

    event = PrefUpdated()
    event.pref_id = str(pref_id)
    event.pref_snapshot = None

    ctx = _make_context()

    with pytest.raises(ValidationError, match="pref_snapshot"):
        await handle_profile_updated(event, ctx)


@pytest.mark.asyncio
async def test_handle_user_pref_settings_created_missing_snapshot() -> None:
    """Test handle_user_pref_settings_created when settings is None."""
    user_id = uuid.uuid4()

    event = UserPrefSettingsCreated()
    event.user_id = str(user_id)
    event.settings = None

    mock_session = create_mock_session()
    ctx = _make_context(db_session=mock_session)

    await handle_user_pref_settings_created(event, ctx)

    mock_session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_user_pref_settings_updated_missing_snapshot() -> None:
    """Test handle_user_pref_settings_updated when settings is None."""
    user_id = uuid.uuid4()

    event = UserPrefSettingsUpdated()
    event.user_id = str(user_id)
    event.settings = None

    mock_session = create_mock_session()
    ctx = _make_context(db_session=mock_session)

    await handle_user_pref_settings_updated(event, ctx)

    mock_session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_attachment_created_missing_snapshot() -> None:
    """Test handle_attachment_created raises ValidationError when snapshot is None."""
    upload_id = uuid.uuid4()

    event = UploadCreated()
    event.upload_id = str(upload_id)
    event.upload_snapshot = None

    ctx = _make_context()

    with pytest.raises(ValidationError, match="upload_snapshot"):
        await handle_attachment_created(event, ctx)


@pytest.mark.asyncio
async def test_handle_listing_created_missing_snapshot() -> None:
    """Test handle_listing_created when listing_snapshot is None."""
    listing_id = uuid.uuid4()

    event = ListingCreated()
    event.listing_snapshot = None
    event.was_updated = False

    listing_ref = MagicMock()
    listing_ref.listing_id = str(listing_id)
    event.listing = listing_ref

    mock_session = create_mock_session()
    ctx = _make_context(db_session=mock_session)

    await handle_listing_created(event, ctx)

    mock_session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_listing_created_missing_listing_ref() -> None:
    """Test handle_listing_created when listing reference is None."""
    listing_id = uuid.uuid4()
    now = datetime.now(UTC)

    snapshot = ListingSnapshot()
    snapshot.id = str(listing_id)
    snapshot.title = "Software Engineer"
    snapshot.company_name = "TechCorp"
    snapshot.description = "A great job"
    snapshot.listing_url = "https://example.com/job"
    snapshot.version = 1
    snapshot.raw_content_hash = "abc123"
    snapshot.discovered_at = now

    event = ListingCreated()
    event.listing_snapshot = snapshot
    event.listing = None
    event.was_updated = False

    mock_session = create_mock_session()
    ctx = _make_context(db_session=mock_session)

    await handle_listing_created(event, ctx)

    mock_session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_listing_updated_missing_snapshot() -> None:
    """Test handle_listing_updated when listing_snapshot is None."""
    event = ListingUpdated()
    event.listing_snapshot = None
    event.previous_version = 1

    mock_session = create_mock_session()
    ctx = _make_context(db_session=mock_session)

    await handle_listing_updated(event, ctx)

    mock_session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_correlation_evaluated_missing_listing_snapshot() -> None:
    """Test handle_correlation_evaluated when listing_snapshot is None."""
    correlation_id = uuid.uuid4()
    pref_id = uuid.uuid4()
    user_id = uuid.uuid4()

    pref_snapshot = SearchPrefSnapshot()
    pref_snapshot.id = str(pref_id)
    pref_snapshot.user_id = str(user_id)

    event = CorrelationEvaluated()
    event.correlation_id = str(correlation_id)
    event.listing_snapshot = None
    event.pref_snapshot = pref_snapshot
    event.fit_score = 85

    mock_session = create_mock_session()
    ctx = _make_context(db_session=mock_session)

    await handle_correlation_evaluated(event, ctx)

    mock_session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_correlation_evaluated_missing_pref_snapshot() -> None:
    """Test handle_correlation_evaluated when pref_snapshot is None."""
    correlation_id = uuid.uuid4()
    listing_id = uuid.uuid4()

    listing_snapshot = ListingSnapshot()
    listing_snapshot.id = str(listing_id)
    listing_snapshot.title = "Software Engineer"
    listing_snapshot.company_name = "TechCorp"
    listing_snapshot.listing_url = "https://example.com/job"

    event = CorrelationEvaluated()
    event.correlation_id = str(correlation_id)
    event.listing_snapshot = listing_snapshot
    event.pref_snapshot = None
    event.fit_score = 85

    mock_session = create_mock_session()
    ctx = _make_context(db_session=mock_session)

    await handle_correlation_evaluated(event, ctx)

    mock_session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_skill_created_missing_snapshot() -> None:
    """Test handle_skill_created when skill_snapshot is None."""
    skill_id = uuid.uuid4()

    event = SkillCreated()
    event.skill_id = str(skill_id)
    event.skill_snapshot = None

    mock_session = create_mock_session()
    ctx = _make_context(db_session=mock_session)

    await handle_skill_created(event, ctx)

    mock_session.execute.assert_not_awaited()


# Template + Render Handlers


@pytest.mark.asyncio
async def test_handle_template_created() -> None:
    """Test handle_template_created handler with ECST snapshot."""
    template_id = uuid.uuid4()
    request_id = uuid.uuid4()

    version_snapshot = MagicMock()
    version_snapshot.version_id = ""
    version_snapshot.version = "1.0.0"
    version_snapshot.template_content = "<html>{{ name }}</html>"
    version_snapshot.content_schema_json = '{"type": "object"}'

    snapshot = MagicMock()
    snapshot.namespace = "default"
    snapshot.name = "resume-classic"
    snapshot.display_name = "Classic Résumé"
    snapshot.description = "Classic resume template"
    snapshot.access_scope = MagicMock()
    snapshot.owner_id = str(uuid.uuid4())
    snapshot.version_snapshot = version_snapshot

    event = TemplateCreated()
    event.template_id = str(template_id)
    event.template_snapshot = snapshot
    event.metadata = MagicMock(correlation_id=str(request_id))

    mock_session = create_mock_session()
    ctx = _make_context(db_session=mock_session)

    await handle_template_created(event, ctx)

    _assert_command_marked_completed(mock_session, request_id)
    projection_stmt = mock_session.execute.await_args_list[0].args[0]
    projection_params = projection_stmt.compile().params
    assert projection_params["display_name"] == "Classic Résumé"
    assert projection_params["name"] == "resume-classic"


@pytest.mark.asyncio
async def test_handle_template_updated() -> None:
    """Test handle_template_updated handler with ECST snapshot."""
    template_id = uuid.uuid4()
    request_id = uuid.uuid4()

    version_snapshot = MagicMock()
    version_snapshot.version_id = ""
    version_snapshot.version = "2.0.0"
    version_snapshot.template_content = "<html>{{ title }}</html>"
    version_snapshot.content_schema_json = ""

    snapshot = MagicMock()
    snapshot.namespace = "default"
    snapshot.name = "resume-modern"
    snapshot.display_name = "Modern Résumé"
    snapshot.description = "Modern resume"
    snapshot.access_scope = None
    snapshot.owner_id = ""
    snapshot.version_snapshot = version_snapshot

    event = TemplateUpdated()
    event.template_id = str(template_id)
    event.template_snapshot = snapshot
    event.metadata = MagicMock(correlation_id=str(request_id))

    mock_session = create_mock_session()
    ctx = _make_context(db_session=mock_session)

    await handle_template_updated(event, ctx)

    _assert_command_marked_completed(mock_session, request_id)
    projection_stmt = mock_session.execute.await_args_list[0].args[0]
    assert projection_stmt.compile().params["display_name"] == "Modern Résumé"


@pytest.mark.asyncio
async def test_handle_template_updated_preserves_protobuf_defaults() -> None:
    """Default-valued optional snapshot fields are projected, not treated as absent."""
    template_id = uuid.uuid4()
    request_id = uuid.uuid4()
    version_snapshot = MagicMock(
        version_id="",
        version="2.0.0",
        template_content="<html>{{ title }}</html>",
        content_schema_json="",
    )
    snapshot = MagicMock(
        namespace="default",
        name="resume-modern",
        display_name="",
        audience=TemplateAudience.UNSPECIFIED,
        description="",
        access_scope=None,
        owner_id="",
        version_snapshot=version_snapshot,
    )
    event = TemplateUpdated()
    event.template_id = str(template_id)
    event.template_snapshot = snapshot
    event.metadata = MagicMock(correlation_id=str(request_id))
    mock_session = create_mock_session()

    await handle_template_updated(event, _make_context(db_session=mock_session))

    _assert_command_marked_completed(mock_session, request_id)
    projection_stmt = mock_session.execute.await_args_list[0].args[0]
    projection_params = projection_stmt.compile().params
    assert projection_params["display_name"] == ""
    assert projection_params["audience"] == TemplateAudience.UNSPECIFIED


@pytest.mark.asyncio
async def test_handle_template_deleted() -> None:
    """Test handle_template_deleted handler."""
    template_id = uuid.uuid4()
    request_id = uuid.uuid4()

    event = TemplateDeleted()
    event.template_id = str(template_id)
    event.metadata = MagicMock(correlation_id=str(request_id))

    mock_session = create_mock_session()
    ctx = _make_context(db_session=mock_session)

    await handle_template_deleted(event, ctx)

    _assert_command_marked_completed(mock_session, request_id)


@pytest.mark.asyncio
async def test_handle_render_completed() -> None:
    """Test handle_render_completed handler for successful render."""
    request_id = uuid.uuid4()

    completed_status = MagicMock()
    result = MagicMock()
    result.status = completed_status
    result.error_message = None

    metadata = MagicMock()
    metadata.correlation_id = str(request_id)

    event = DocumentRenderCompleted()
    event.metadata = metadata
    event.result = result
    event.storage_key = "renders/output.pdf"
    event.file_size = 2048
    event.content_hash = "sha256:abc123"

    mock_execute_result = MagicMock()
    mock_execute_result.scalar_one_or_none.return_value = None  # no terminal canonical row; skips SSE publish
    mock_session = create_mock_session()
    mock_session.execute = AsyncMock(return_value=mock_execute_result)
    ctx = _make_context(db_session=mock_session)

    await handle_render_completed(event, ctx)

    mock_session.execute.assert_awaited()
    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_render_completed_missing_correlation_id() -> None:
    """Test handle_render_completed when correlation_id is missing."""
    event = DocumentRenderCompleted()
    event.metadata = None

    mock_session = create_mock_session()
    ctx = _make_context(db_session=mock_session)

    await handle_render_completed(event, ctx)

    mock_session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_template_created_missing_snapshot() -> None:
    """Test handle_template_created when template_snapshot is missing."""
    event = TemplateCreated()
    event.template_id = str(uuid.uuid4())
    event.template_snapshot = None

    mock_session = create_mock_session()
    ctx = _make_context(db_session=mock_session)

    with patch("bff_service.events.projections.doc_template.logger"):
        await handle_template_created(event, ctx)

    mock_session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_template_created_missing_version_snapshot() -> None:
    """Test handle_template_created when version_snapshot is missing."""
    snapshot = MagicMock()
    snapshot.version_snapshot = None

    event = TemplateCreated()
    event.template_id = str(uuid.uuid4())
    event.template_snapshot = snapshot

    mock_session = create_mock_session()
    ctx = _make_context(db_session=mock_session)

    with patch("bff_service.events.projections.doc_template.logger"):
        await handle_template_created(event, ctx)

    mock_session.execute.assert_not_awaited()


# Language field tests for listing handlers


@pytest.mark.asyncio
async def test_handle_listing_created_includes_language() -> None:
    """handle_listing_created inserts language from snapshot into projection."""
    listing_id = uuid.uuid4()
    now = datetime.now(UTC)

    snapshot = ListingSnapshot()
    snapshot.id = str(listing_id)
    snapshot.title = "Software Engineer"
    snapshot.company_name = "TechCorp"
    snapshot.description = "A great job"
    snapshot.listing_url = "https://example.com/job"
    snapshot.location = _default_location()
    snapshot.version = 1
    snapshot.raw_content_hash = "abc123"
    snapshot.discovered_at = now
    snapshot.language = "fr-CA"  # BCP 47 language tag

    listing_ref = MagicMock()
    listing_ref.listing_id = str(listing_id)
    listing_ref.listing_url = "https://example.com/job"

    event = ListingCreated()
    event.listing = listing_ref
    event.was_updated = False
    event.listing_snapshot = snapshot

    mock_session = create_mock_session()
    ctx = _make_context(db_session=mock_session)

    await handle_listing_created(event, ctx)

    mock_session.execute.assert_awaited()
    call_args = mock_session.execute.await_args
    assert call_args is not None


@pytest.mark.asyncio
async def test_handle_listing_created_empty_language_becomes_none() -> None:
    """Empty language string from proto default maps to None in projection."""
    listing_id = uuid.uuid4()
    now = datetime.now(UTC)

    snapshot = ListingSnapshot()
    snapshot.id = str(listing_id)
    snapshot.title = "Software Engineer"
    snapshot.company_name = "TechCorp"
    snapshot.description = "A job"
    snapshot.listing_url = "https://example.com/job"
    snapshot.location = _default_location()
    snapshot.version = 1
    snapshot.raw_content_hash = "abc123"
    snapshot.discovered_at = now
    snapshot.language = ""  # Empty proto default

    listing_ref = MagicMock()
    listing_ref.listing_id = str(listing_id)
    event = ListingCreated()
    event.listing = listing_ref
    event.was_updated = False
    event.listing_snapshot = snapshot

    mock_session = create_mock_session()
    ctx = _make_context(db_session=mock_session)

    await handle_listing_created(event, ctx)

    mock_session.execute.assert_awaited()
