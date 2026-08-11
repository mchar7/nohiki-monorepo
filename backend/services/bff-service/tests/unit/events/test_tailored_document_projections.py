"""Projection and lifecycle tests for tailored document generation."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bff_service.events.projections.doc_content import (
    handle_content_generation_completed,
    handle_content_generation_failed,
)
from bff_service.events.projections.doc_template import (
    handle_render_completed,
    handle_template_created,
)
from bff_service.events.projections.job_correlation import handle_correlation_evaluated
from bff_service.events.projections.job_listing import handle_listing_created
from bff_service.sse.events import DocumentStatusPayload
from nohiki.common.v1 import AccessScope, Location, ProcessingStatus, UploadReference
from nohiki.doc.template.v1 import TemplateAudience
from nohiki.job.listing.v1 import ListingSnapshot
from nohiki.user.pref.v1 import SearchPrefSnapshot
from nohiki_db_utils.testing import create_mock_session
from nohiki_kafka_client import MessageContext
from sqlalchemy.dialects import postgresql


def _context(session: AsyncMock) -> MessageContext:
    return MessageContext(
        topic="test.topic.v1",
        partition=0,
        offset=0,
        timestamp=0,
        headers={},
        key=None,
        db_session=session,
    )


def _compile_params(session: AsyncMock) -> tuple[str, dict[str, object]]:
    statement = session.execute.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": False})
    return str(compiled), compiled.params


def _render_session(*canonical_rows: SimpleNamespace) -> AsyncMock:
    results: list[MagicMock] = []
    for canonical in canonical_rows:
        update_result = MagicMock()
        canonical_result = MagicMock()
        canonical_result.scalar_one_or_none.return_value = canonical
        results.extend((update_result, canonical_result))
    session = create_mock_session()
    session.execute = AsyncMock(side_effect=results)
    return session


def _upload(user_id: uuid.UUID, storage_key: str) -> UploadReference:
    return UploadReference(
        id=str(uuid.uuid4()),
        user_id=str(user_id),
        name="resume.pdf",
        content_type="application/pdf",
        file_size=42,
        content_hash="sha256",
        storage_key=storage_key,
    )


@pytest.mark.asyncio
async def test_listing_projection_persists_full_snapshot_json() -> None:
    listing_id = uuid.uuid4()
    snapshot = ListingSnapshot(
        id=str(listing_id),
        listing_url="https://example.test/job",
        title="Staff Engineer",
        company_name="Example",
        description="Full description",
        location=Location(city="Amsterdam"),
        required_skills=["Python", "Kafka"],
        language="en",
        discovered_at=datetime(2026, 7, 1, tzinfo=UTC),
        version=4,
        raw_content_hash="hash",
        collection_version="skills-v3",
    )
    event = MagicMock()
    event.listing_snapshot = snapshot
    event.listing = SimpleNamespace(id=str(listing_id))
    session = create_mock_session()

    await handle_listing_created(event, _context(session))

    sql, params = _compile_params(session)
    assert params["snapshot"] == snapshot.to_dict()
    assert "snapshot =" in sql
    assert snapshot.to_dict() in params.values()


@pytest.mark.asyncio
async def test_correlation_projection_persists_pref_snapshot_and_pref_uploads() -> None:
    correlation_id = uuid.uuid4()
    user_id = uuid.uuid4()
    pref_id = uuid.uuid4()
    listing_id = uuid.uuid4()
    pref = SearchPrefSnapshot(
        id=str(pref_id),
        user_id=str(user_id),
        pref_name="Backend",
        search_keywords=["python"],
        tailoring_preferences={"tone": "brief"},
        is_active=True,
    )
    upload = _upload(user_id, "users/resume.pdf")
    event = MagicMock()
    event.correlation_id = str(correlation_id)
    event.pref_snapshot = pref
    event.pref_uploads = [upload]
    event.listing_snapshot = SimpleNamespace(
        id=str(listing_id),
        title="Engineer",
        company_name="Example",
        listing_url="https://example.test/job",
        location=Location(city="Paris"),
    )
    event.fit_score = 88
    event.correlation_status = SimpleNamespace(name="EVALUATED")
    event.correlation_metadata = {"source": "matcher"}
    session = create_mock_session()

    await handle_correlation_evaluated(event, _context(session))

    sql, params = _compile_params(session)
    assert params["pref_snapshot"] == pref.to_dict()
    assert params["pref_uploads"] == [upload.to_dict()]
    assert "pref_snapshot =" in sql
    assert "pref_uploads =" in sql
    assert pref.to_dict() in params.values()
    assert [upload.to_dict()] in params.values()


@pytest.mark.asyncio
async def test_template_projection_persists_actual_version_uuid() -> None:
    template_id = uuid.uuid4()
    version_id = uuid.uuid4()
    version = SimpleNamespace(
        version_id=str(version_id),
        version="2.0.0",
        template_content="<html>{{ summary }}</html>",
        content_schema_json='{"type":"object"}',
    )
    event = MagicMock()
    event.template_id = str(template_id)
    event.template_snapshot = SimpleNamespace(
        namespace="default",
        name="resume",
        description="Resume",
        display_name="Resume",
        audience=TemplateAudience.DOCUMENT,
        access_scope=AccessScope.UNSPECIFIED,
        owner_id="",
        version_snapshot=version,
    )
    session = create_mock_session()

    await handle_template_created(event, _context(session))

    sql, params = _compile_params(session)
    assert params["version_id"] == version_id
    assert "version_id =" in sql
    assert version_id in params.values()


def _content_event(request_id: uuid.UUID, *, failed: bool = False) -> MagicMock:
    event = MagicMock()
    event.request_id = str(request_id)
    event.metadata = SimpleNamespace(correlation_id=str(request_id))
    if failed:
        event.result = SimpleNamespace(error=SimpleNamespace(error_message="LLM schema mismatch"))
    return event


@pytest.mark.asyncio
async def test_content_completed_transitions_pending_to_in_progress_and_is_idempotent() -> None:
    request_id = uuid.uuid4()
    user_id = uuid.uuid4()
    result = MagicMock()
    result.scalar_one_or_none.side_effect = [user_id, None]
    session = create_mock_session()
    session.execute.return_value = result
    bridge = AsyncMock()

    with patch("bff_service.events.projections.doc_content.get_sse_bridge", return_value=bridge):
        await handle_content_generation_completed(_content_event(request_id), _context(session))
        await handle_content_generation_completed(_content_event(request_id), _context(session))

    statement = session.execute.await_args_list[0].args[0]
    sql = str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": False}))
    assert "document_generation_status.status =" in sql
    assert "document_generation_status.job_correlation_id IS NOT NULL" in sql
    params = statement.compile(dialect=postgresql.dialect()).params
    assert "pending" in params.values()
    assert "in_progress" in params.values()
    assert bridge.publish.await_count == 1
    assert bridge.publish.await_args.args[0] == user_id
    payload = bridge.publish.await_args.args[1]
    assert payload.request_id == str(request_id)
    assert payload.status == "in_progress"
    assert session.commit.await_count == 2


@pytest.mark.asyncio
async def test_content_failed_is_terminal_user_isolated_and_duplicate_safe() -> None:
    request_id = uuid.uuid4()
    owner_id = uuid.uuid4()
    other_user_id = uuid.uuid4()
    result = MagicMock()
    result.scalar_one_or_none.side_effect = [owner_id, None]
    session = create_mock_session()
    session.execute.return_value = result
    bridge = AsyncMock()
    event = _content_event(request_id, failed=True)

    with patch("bff_service.events.projections.doc_content.get_sse_bridge", return_value=bridge):
        await handle_content_generation_failed(event, _context(session))
        await handle_content_generation_failed(event, _context(session))

    statement = session.execute.await_args_list[0].args[0]
    sql = str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": False}))
    params = statement.compile(dialect=postgresql.dialect()).params
    assert "document_generation_status.status IN" in sql
    assert "failed" in params.values()
    assert "LLM schema mismatch" in params.values()
    bridge.publish.assert_awaited_once()
    assert bridge.publish.await_args.args[0] == owner_id
    assert bridge.publish.await_args.args[0] != other_user_id
    payload = bridge.publish.await_args.args[1]
    assert payload.status == "failed"
    assert payload.error_message == "LLM schema mismatch"


@pytest.mark.asyncio
async def test_content_callback_with_mismatched_correlation_is_ignored() -> None:
    request_id = uuid.uuid4()
    event = _content_event(request_id)
    event.metadata.correlation_id = str(uuid.uuid4())
    session = create_mock_session()

    await handle_content_generation_completed(event, _context(session))

    session.execute.assert_not_awaited()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_late_render_callback_cannot_overwrite_terminal_failure_and_republishes_canonical_sse() -> None:
    request_id = uuid.uuid4()
    owner_id = uuid.uuid4()
    canonical = SimpleNamespace(
        request_id=request_id,
        user_id=owner_id,
        status="failed",
        storage_key=None,
        error_message="Canonical render failure",
        file_size=None,
        content_hash=None,
    )
    session = _render_session(canonical)
    event = MagicMock()
    event.metadata = SimpleNamespace(correlation_id=str(request_id))
    event.result = SimpleNamespace(status=ProcessingStatus.COMPLETED, error=None)
    event.storage_key = "renders/incoming.pdf"
    event.file_size = 100
    event.content_hash = "incoming-hash"
    bridge = AsyncMock()

    with patch(
        "bff_service.events.projections.doc_template.get_sse_bridge",
        return_value=bridge,
    ):
        await handle_render_completed(event, _context(session))

    assert session.execute.await_count == 2
    update_statement = session.execute.await_args_list[0].args[0]
    update_sql = str(update_statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": False}))
    assert "document_generation_status.status NOT IN" in update_sql
    update_params = update_statement.compile(dialect=postgresql.dialect()).params
    assert "completed" in update_params.values()
    assert "renders/incoming.pdf" in update_params.values()

    canonical_statement = session.execute.await_args_list[1].args[0]
    canonical_sql = str(canonical_statement.compile(dialect=postgresql.dialect()))
    assert canonical_sql.lstrip().startswith("SELECT")
    assert "document_generation_status.status IN" in canonical_sql
    session.commit.assert_awaited_once()
    bridge.publish.assert_awaited_once()
    assert bridge.publish.await_args.args[0] == owner_id
    assert bridge.publish.await_args.args[1] == DocumentStatusPayload(
        type="document_status",
        request_id=str(request_id),
        status="failed",
        storage_key=None,
        error_message="Canonical render failure",
        file_size=None,
        content_hash=None,
    )


@pytest.mark.asyncio
async def test_render_completed_remains_terminal_and_republishes_canonical_state_to_owner() -> None:
    request_id = uuid.uuid4()
    owner_id = uuid.uuid4()
    canonical = SimpleNamespace(
        request_id=request_id,
        user_id=owner_id,
        status="completed",
        storage_key="renders/canonical.pdf",
        error_message=None,
        file_size=2048,
        content_hash="canonical-hash",
    )
    session = _render_session(canonical, canonical)
    event = MagicMock()
    event.metadata = SimpleNamespace(correlation_id=str(request_id))
    event.result = SimpleNamespace(status=ProcessingStatus.COMPLETED, error=None)
    event.storage_key = "renders/incoming.pdf"
    event.file_size = 100
    event.content_hash = "incoming-hash"
    bridge = AsyncMock()

    with patch(
        "bff_service.events.projections.doc_template.get_sse_bridge",
        return_value=bridge,
    ):
        await handle_render_completed(event, _context(session))
        await handle_render_completed(event, _context(session))

    assert session.execute.await_count == 4
    assert session.commit.await_count == 2
    for call_index in (0, 2):
        update_statement = session.execute.await_args_list[call_index].args[0]
        update_sql = str(update_statement.compile(dialect=postgresql.dialect()))
        assert "document_generation_status.status NOT IN" in update_sql
    for call_index in (1, 3):
        canonical_statement = session.execute.await_args_list[call_index].args[0]
        canonical_sql = str(canonical_statement.compile(dialect=postgresql.dialect()))
        assert canonical_sql.lstrip().startswith("SELECT")
        assert "document_generation_status.status IN" in canonical_sql

    assert bridge.publish.await_count == 2
    assert bridge.publish.await_args_list[0].args == bridge.publish.await_args_list[1].args
    assert bridge.publish.await_args.args[0] == owner_id
    assert bridge.publish.await_args.args[1] == DocumentStatusPayload(
        type="document_status",
        request_id=str(request_id),
        status="completed",
        storage_key="renders/canonical.pdf",
        error_message=None,
        file_size=2048,
        content_hash="canonical-hash",
    )


@pytest.mark.asyncio
async def test_render_failure_remains_terminal_and_publishes_canonical_failure_to_owner() -> None:
    request_id = uuid.uuid4()
    owner_id = uuid.uuid4()
    canonical = SimpleNamespace(
        request_id=request_id,
        user_id=owner_id,
        status="failed",
        storage_key=None,
        error_message="Canonical renderer failure",
        file_size=None,
        content_hash=None,
    )
    session = _render_session(canonical)
    event = MagicMock()
    event.metadata = SimpleNamespace(correlation_id=str(request_id))
    event.result = SimpleNamespace(
        status=ProcessingStatus.FAILED,
        error=SimpleNamespace(error_message="Incoming render failure"),
    )
    event.storage_key = ""
    event.file_size = 0
    event.content_hash = ""
    bridge = AsyncMock()

    with patch(
        "bff_service.events.projections.doc_template.get_sse_bridge",
        return_value=bridge,
    ):
        await handle_render_completed(event, _context(session))

    assert session.execute.await_count == 2
    update_statement = session.execute.await_args_list[0].args[0]
    update_sql = str(update_statement.compile(dialect=postgresql.dialect()))
    assert "document_generation_status.status NOT IN" in update_sql
    update_params = update_statement.compile(dialect=postgresql.dialect()).params
    assert "failed" in update_params.values()
    assert "Incoming render failure" in update_params.values()

    canonical_statement = session.execute.await_args_list[1].args[0]
    canonical_sql = str(canonical_statement.compile(dialect=postgresql.dialect()))
    assert canonical_sql.lstrip().startswith("SELECT")
    assert "document_generation_status.status IN" in canonical_sql
    session.commit.assert_awaited_once()
    bridge.publish.assert_awaited_once()
    assert bridge.publish.await_args.args[0] == owner_id
    assert bridge.publish.await_args.args[1] == DocumentStatusPayload(
        type="document_status",
        request_id=str(request_id),
        status="failed",
        storage_key=None,
        error_message="Canonical renderer failure",
        file_size=None,
        content_hash=None,
    )
