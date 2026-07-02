"""Tests for terminal document projection and durable SSE publication."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import bff_service.events.projections.doc_template as _doc_template_mod
import pytest
from bff_service.events.projections.doc_template import handle_render_completed
from bff_service.sse.events import DocumentStatusPayload
from nohiki_db_utils.testing import create_mock_session
from nohiki_kafka_client import MessageContext


def _context(session: AsyncMock) -> MessageContext:
    return MessageContext(
        topic="doc.template.render-completed",
        partition=0,
        offset=0,
        timestamp=0,
        headers={},
        key=None,
        db_session=session,
    )


def _event(
    request_id: uuid.UUID,
    *,
    completed: bool = True,
    storage_key: str = "renders/incoming.pdf",
    file_size: int = 1024,
    content_hash: str = "incoming-hash",
    error_message: str | None = None,
) -> MagicMock:
    from nohiki.common.v1 import ProcessingStatus

    result = MagicMock()
    result.status = ProcessingStatus.COMPLETED if completed else ProcessingStatus.FAILED
    result.error = SimpleNamespace(error_message=error_message) if error_message is not None else None
    event = MagicMock()
    event.metadata = SimpleNamespace(correlation_id=str(request_id))
    event.result = result
    event.storage_key = storage_key
    event.file_size = file_size
    event.content_hash = content_hash
    return event


def _canonical_row(
    request_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    status: str = "completed",
    storage_key: str | None = "renders/canonical.pdf",
    error_message: str | None = None,
    file_size: int | None = 2048,
    content_hash: str | None = "canonical-hash",
) -> SimpleNamespace:
    return SimpleNamespace(
        request_id=request_id,
        user_id=user_id,
        status=status,
        storage_key=storage_key,
        error_message=error_message,
        file_size=file_size,
        content_hash=content_hash,
    )


def _session_for_deliveries(
    canonical_rows: list[SimpleNamespace | None],
) -> AsyncMock:
    results: list[MagicMock] = []
    for canonical in canonical_rows:
        update_result = MagicMock()
        canonical_result = MagicMock()
        canonical_result.scalar_one_or_none.return_value = canonical
        results.extend((update_result, canonical_result))
    session = create_mock_session()
    session.execute = AsyncMock(side_effect=results)
    return session


def _published_payload(bridge: AsyncMock, call_index: int = -1) -> DocumentStatusPayload:
    payload = bridge.publish.await_args_list[call_index].args[1]
    assert isinstance(payload, DocumentStatusPayload)
    return payload


@pytest.mark.asyncio
async def test_terminal_publish_failure_propagates_after_database_commit() -> None:
    request_id = uuid.uuid4()
    canonical = _canonical_row(request_id, uuid.uuid4())
    session = _session_for_deliveries([canonical])
    bridge = AsyncMock()
    failure = RuntimeError("Redis stream unavailable")

    async def _fail_publish(_user_id: uuid.UUID, _payload: DocumentStatusPayload) -> str:
        session.commit.assert_awaited_once()
        raise failure

    bridge.publish.side_effect = _fail_publish
    with (
        patch.object(_doc_template_mod, "get_sse_bridge", return_value=bridge),
        pytest.raises(RuntimeError) as exc_info,
    ):
        await handle_render_completed(_event(request_id), _context(session))

    assert exc_info.value is failure
    session.commit.assert_awaited_once()
    bridge.publish.assert_awaited_once()


@pytest.mark.asyncio
async def test_kafka_retry_reloads_and_republishes_canonical_terminal_row() -> None:
    request_id = uuid.uuid4()
    canonical = _canonical_row(request_id, uuid.uuid4())
    session = _session_for_deliveries([canonical, canonical])
    bridge = AsyncMock()
    first_failure = RuntimeError("Redis stream unavailable")
    bridge.publish.side_effect = [first_failure, "1710000000000-0"]
    event = _event(request_id)

    with patch.object(_doc_template_mod, "get_sse_bridge", return_value=bridge):
        with pytest.raises(RuntimeError) as exc_info:
            await handle_render_completed(event, _context(session))
        await handle_render_completed(event, _context(session))

    assert exc_info.value is first_failure
    assert session.commit.await_count == 2
    assert session.execute.await_count == 4
    assert bridge.publish.await_count == 2
    assert bridge.publish.await_args_list[0].args == bridge.publish.await_args_list[1].args
    payload = _published_payload(bridge)
    assert payload.request_id == str(canonical.request_id)
    assert payload.status == canonical.status
    assert payload.storage_key == canonical.storage_key
    assert payload.file_size == canonical.file_size
    assert payload.content_hash == canonical.content_hash


@pytest.mark.asyncio
async def test_conflicting_terminal_duplicate_publishes_only_canonical_persisted_state() -> None:
    request_id = uuid.uuid4()
    user_id = uuid.uuid4()
    canonical = _canonical_row(
        request_id,
        user_id,
        status="completed",
        storage_key="renders/original.pdf",
        file_size=4096,
        content_hash="original-hash",
    )
    session = _session_for_deliveries([canonical])
    bridge = AsyncMock()
    conflicting = _event(
        request_id,
        completed=False,
        storage_key="renders/conflicting.pdf",
        file_size=1,
        content_hash="conflicting-hash",
        error_message="conflicting failure",
    )

    with patch.object(_doc_template_mod, "get_sse_bridge", return_value=bridge):
        await handle_render_completed(conflicting, _context(session))

    bridge.publish.assert_awaited_once()
    assert bridge.publish.await_args.args[0] == user_id
    payload = _published_payload(bridge)
    assert payload == DocumentStatusPayload(
        type="document_status",
        request_id=str(request_id),
        status="completed",
        storage_key="renders/original.pdf",
        error_message=None,
        file_size=4096,
        content_hash="original-hash",
    )
    update_statement = session.execute.await_args_list[0].args[0]
    assert "STATUS NOT IN" in str(update_statement.compile()).upper()


@pytest.mark.asyncio
async def test_successful_duplicate_is_idempotent_and_republishes_same_canonical_state() -> None:
    request_id = uuid.uuid4()
    canonical = _canonical_row(
        request_id,
        uuid.uuid4(),
        status="failed",
        storage_key=None,
        error_message="canonical failure",
        file_size=None,
        content_hash=None,
    )
    session = _session_for_deliveries([canonical, canonical])
    bridge = AsyncMock()
    event = _event(request_id, completed=False, error_message="incoming failure")

    with patch.object(_doc_template_mod, "get_sse_bridge", return_value=bridge):
        await handle_render_completed(event, _context(session))
        await handle_render_completed(event, _context(session))

    assert session.commit.await_count == 2
    assert bridge.publish.await_count == 2
    assert bridge.publish.await_args_list[0].args == bridge.publish.await_args_list[1].args
    assert _published_payload(bridge) == DocumentStatusPayload(
        type="document_status",
        request_id=str(request_id),
        status="failed",
        storage_key=None,
        error_message="canonical failure",
        file_size=None,
        content_hash=None,
    )


@pytest.mark.asyncio
async def test_missing_or_nonterminal_canonical_row_does_not_publish() -> None:
    request_id = uuid.uuid4()
    session = _session_for_deliveries([None])
    bridge = AsyncMock()

    with patch.object(_doc_template_mod, "get_sse_bridge", return_value=bridge):
        await handle_render_completed(_event(request_id), _context(session))

    session.commit.assert_awaited_once()
    bridge.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_correlation_id_skips_database_and_publish() -> None:
    session = create_mock_session()
    event = MagicMock()
    event.metadata = None
    bridge = AsyncMock()

    with patch.object(_doc_template_mod, "get_sse_bridge", return_value=bridge):
        await handle_render_completed(event, _context(session))

    session.execute.assert_not_awaited()
    session.commit.assert_not_awaited()
    bridge.publish.assert_not_awaited()
