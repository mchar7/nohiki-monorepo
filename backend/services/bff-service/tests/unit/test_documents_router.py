"""Unit tests for documents router response models.

Tests the pure model logic without importing heavy dependencies.
"""

import asyncio
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from nohiki_db_utils.testing import create_mock_session
from nohiki_fastapi_utils import JWTClaims
from pydantic import BaseModel, Field
from pytest_mock import MockerFixture

# Inline model definitions to test without importing heavy deps


class GenerateDocumentRequest(BaseModel):
    """Request to generate a document."""

    template_version_id: str
    data: dict[str, object]
    output_format: str = Field(default="pdf", pattern="^(pdf|html|png)$")


class GenerateDocumentResponse(BaseModel):
    """Response for document generation initiation."""

    request_id: str
    status: str = "accepted"


class DocumentStatusResponse(BaseModel):
    """Response for document generation status."""

    request_id: str
    status: str
    download_url: str | None = None
    error: str | None = None
    template_name: str | None = None
    output_format: str = "pdf"
    created_at: datetime | None = None


class TestRequestModels:
    """Tests for request models."""

    def test_generate_document_request(self) -> None:
        """Test GenerateDocumentRequest model."""
        request = GenerateDocumentRequest(
            template_version_id="test-id",
            data={"name": "Test"},
            output_format="pdf",
        )
        assert request.template_version_id == "test-id"
        assert request.data == {"name": "Test"}
        assert request.output_format == "pdf"

    def test_generate_document_request_default_format(self) -> None:
        """Test default output format."""
        request = GenerateDocumentRequest(
            template_version_id="test-id",
            data={},
        )
        assert request.output_format == "pdf"


class TestResponseModels:
    """Tests for response models."""

    def test_generate_document_response(self) -> None:
        """Test GenerateDocumentResponse model."""
        response = GenerateDocumentResponse(request_id="test-request-id")
        assert response.request_id == "test-request-id"
        assert response.status == "accepted"

    def test_document_status_response_pending(self) -> None:
        """Test DocumentStatusResponse for pending status."""
        response = DocumentStatusResponse(
            request_id="test-id",
            status="pending",
        )
        assert response.request_id == "test-id"
        assert response.status == "pending"
        assert response.download_url is None
        assert response.error is None
        assert response.template_name is None
        assert response.output_format == "pdf"
        assert response.created_at is None

    def test_document_status_response_completed(self) -> None:
        """Test DocumentStatusResponse for completed status."""
        ts = datetime(2024, 1, 1, tzinfo=UTC)
        response = DocumentStatusResponse(
            request_id="test-id",
            status="completed",
            download_url="https://example.com/doc.pdf",
            template_name="My Resume",
            output_format="pdf",
            created_at=ts,
        )
        assert response.status == "completed"
        assert response.download_url == "https://example.com/doc.pdf"
        assert response.template_name == "My Resume"
        assert response.output_format == "pdf"
        assert response.created_at == ts

    def test_document_status_response_failed(self) -> None:
        """Test DocumentStatusResponse for failed status."""
        response = DocumentStatusResponse(
            request_id="test-id",
            status="failed",
            error="Render error",
        )
        assert response.status == "failed"
        assert response.error == "Render error"

    def test_document_status_response_template_name_optional(self) -> None:
        """Test that template_name defaults to None when template was deleted."""
        response = DocumentStatusResponse(request_id="id", status="completed")
        assert response.template_name is None

    def test_document_status_response_output_format_default(self) -> None:
        """Test output_format defaults to 'pdf'."""
        response = DocumentStatusResponse(request_id="id", status="pending")
        assert response.output_format == "pdf"

    def test_document_status_response_html_format(self) -> None:
        """Test non-pdf output_format is preserved."""
        response = DocumentStatusResponse(
            request_id="id",
            status="completed",
            output_format="html",
        )
        assert response.output_format == "html"

    def test_paginated_document_response(self) -> None:
        """Test PaginatedResponse with DocumentStatusResponse items."""
        from nohiki_fastapi_utils import PaginatedResponse, PaginationParams

        doc = DocumentStatusResponse(request_id="id1", status="completed")
        params = PaginationParams(page=1, page_size=20)
        response = PaginatedResponse[DocumentStatusResponse].create(
            items=[doc],
            total=1,
            params=params,
        )
        assert len(response.items) == 1
        assert response.total == 1
        assert response.has_next is False


# Router handler tests


def _make_template_version_projection(**kwargs: object) -> SimpleNamespace:
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "family_id": uuid.uuid4(),
        "namespace": "default",
        "name": "Test Template",
        "version": "1.0.0",
        "template_content": "<html><body>Test</body></html>",
        "content_schema": None,
        "description": "Test description",
        "is_active": True,
    }
    defaults |= kwargs
    return SimpleNamespace(**defaults)


def _make_template_family_projection(**kwargs: object) -> SimpleNamespace:
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "name": "Test Template",
    }
    defaults |= kwargs
    return SimpleNamespace(**defaults)


def _make_document_status(**kwargs: object) -> SimpleNamespace:
    defaults: dict[str, object] = {
        "request_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "template_version_id": uuid.uuid4(),
        "output_format": "pdf",
        "status": "pending",
        "storage_key": None,
        "error_message": None,
        "created_at": datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC),
    }
    defaults |= kwargs
    return SimpleNamespace(**defaults)


def _principal(*, sub: str | None = None) -> JWTClaims:
    now = int(datetime.now(UTC).timestamp())
    return JWTClaims(
        sub=sub or str(uuid.uuid4()),
        iss="https://api.nohiki.com",
        aud="https://app.nohiki.com",
        exp=now + 3600,
        iat=now,
        jti=str(uuid.uuid4()),
        roles=["user"],
        permissions=[],
        tenant_id=None,
        session_family_id=None,
    )


@pytest.mark.asyncio
async def test_stream_document_events_forwards_request_cursor_and_releases_slot(
    mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    from bff_service.api.routers.documents import stream_document_events
    from bff_service.sse.bridge import SSEBridge
    from bff_service.sse.stream import SSEStreamContext
    from sse_starlette.sse import EventSourceResponse

    request_id = uuid.uuid4()
    user_id = uuid.uuid4()
    verified_claims = _principal(sub=str(user_id))
    principal = _principal(sub=str(user_id))
    order: list[str] = []
    db = create_mock_session()
    ownership = mocker.MagicMock()
    ownership.scalar_one_or_none.return_value = request_id
    db.execute.return_value = ownership
    context = mocker.MagicMock()

    async def _enter() -> object:
        order.append("session-enter")
        return db

    async def _exit(*_args: object) -> None:
        order.append("session-exit")

    context.__aenter__ = mocker.AsyncMock(side_effect=_enter)
    context.__aexit__ = mocker.AsyncMock(side_effect=_exit)
    session_factory = mocker.MagicMock(return_value=context)
    bridge = mocker.MagicMock(spec=SSEBridge)
    lease = mocker.sentinel.lease

    async def _acquire(*_args: object, **_kwargs: object) -> object:
        order.append("slot-acquire")
        return lease

    bridge.acquire_stream_slot.side_effect = _acquire
    shutdown = asyncio.Event()
    settings = mocker.MagicMock()
    settings.database = mocker.sentinel.database
    settings.sse.heartbeat_interval_seconds = 10
    settings.sse.max_stream_duration_seconds = 600
    settings.sse.max_concurrent_streams_per_user = 3
    monkeypatch.setattr("bff_service.api.routers.documents.get_settings", lambda: settings)
    get_factory = mocker.patch(
        "bff_service.api.routers.documents.get_async_sessionmaker",
        return_value=session_factory,
    )
    monkeypatch.setattr("bff_service.api.routers.documents.get_sse_bridge", lambda: bridge)
    monkeypatch.setattr("bff_service.api.routers.documents.get_shutdown_event", lambda: shutdown)

    async def _authorize(claims: JWTClaims, session: object) -> JWTClaims:
        order.append("authorize")
        assert claims is verified_claims
        assert session is db
        return principal

    authorize = mocker.patch(
        "bff_service.api.routers.documents.get_current_user_claims",
        side_effect=_authorize,
    )

    async def _fake_gen() -> AsyncGenerator[str]:
        yield "test"

    body = _fake_gen()

    def _construct(**_kwargs: object) -> AsyncGenerator[str]:
        order.append("generator")
        return body

    construct = mocker.patch(
        "bff_service.api.routers.documents.sse_event_generator",
        side_effect=_construct,
    )

    result = await stream_document_events(request_id, verified_claims, "41-0")

    assert isinstance(result, EventSourceResponse)
    assert result.body_iterator is body
    assert result.media_type == "text/event-stream"
    assert result.ping_interval == 10
    assert result.ping_message_factory is not None
    assert result.ping_message_factory().encode() == b": ping\r\n\r\n"
    assert order == [
        "session-enter",
        "authorize",
        "session-exit",
        "slot-acquire",
        "generator",
    ]
    get_factory.assert_called_once_with(settings.database)
    authorize.assert_awaited_once_with(verified_claims, db)
    bridge.acquire_stream_slot.assert_awaited_once_with(
        user_id,
        limit=3,
        ttl_seconds=610,
    )
    construct.assert_called_once_with(
        user_id=user_id,
        principal=principal,
        context=SSEStreamContext(
            session_factory=session_factory,
            bridge=bridge,
            settings=settings.sse,
            shutdown_event=shutdown,
        ),
        request_id=request_id,
        last_event_id="41-0",
    )
    bridge.release_stream_slot.assert_not_awaited()
    assert result.background is not None
    await result.background()
    bridge.release_stream_slot.assert_awaited_once_with(lease)


@pytest.mark.asyncio
async def test_stream_document_events_rejects_exhausted_slot_without_generator(
    mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    from bff_service.api.routers.documents import stream_document_events
    from bff_service.sse.bridge import SSEBridge

    request_id = uuid.uuid4()
    user_id = uuid.uuid4()
    principal = _principal(sub=str(user_id))
    db = create_mock_session()
    ownership = mocker.MagicMock()
    ownership.scalar_one_or_none.return_value = request_id
    db.execute.return_value = ownership
    context = mocker.MagicMock()
    context.__aenter__ = mocker.AsyncMock(return_value=db)
    context.__aexit__ = mocker.AsyncMock(return_value=None)
    session_factory = mocker.MagicMock(return_value=context)
    bridge = mocker.MagicMock(spec=SSEBridge)
    bridge.acquire_stream_slot.return_value = None
    settings = mocker.MagicMock()
    settings.database = mocker.sentinel.database
    settings.sse.heartbeat_interval_seconds = 15
    settings.sse.max_stream_duration_seconds = 300
    settings.sse.max_concurrent_streams_per_user = 2
    monkeypatch.setattr("bff_service.api.routers.documents.get_settings", lambda: settings)
    monkeypatch.setattr(
        "bff_service.api.routers.documents.get_async_sessionmaker",
        mocker.MagicMock(return_value=session_factory),
    )
    monkeypatch.setattr("bff_service.api.routers.documents.get_sse_bridge", lambda: bridge)
    monkeypatch.setattr("bff_service.api.routers.documents.get_shutdown_event", asyncio.Event)
    mocker.patch(
        "bff_service.api.routers.documents.get_current_user_claims",
        new=mocker.AsyncMock(return_value=principal),
    )
    construct = mocker.patch("bff_service.api.routers.documents.sse_event_generator")

    with pytest.raises(HTTPException) as exc_info:
        await stream_document_events(request_id, principal)

    assert exc_info.value.status_code == 429
    assert exc_info.value.detail == "Too many concurrent document event streams"
    bridge.acquire_stream_slot.assert_awaited_once_with(
        user_id,
        limit=2,
        ttl_seconds=315,
    )
    construct.assert_not_called()
    bridge.release_stream_slot.assert_not_awaited()


def test_stream_document_events_unauthenticated_returns_401() -> None:
    from bff_service.api.routers.documents import (
        document_events_router,
        get_verified_user_claims,
    )
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(document_events_router, prefix="/documents")

    async def _reject_auth() -> None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    app.dependency_overrides[get_verified_user_claims] = _reject_auth
    request_id = uuid.uuid4()

    response = TestClient(app, raise_server_exceptions=False).get(f"/documents/{request_id}/events")

    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated"}


@pytest.mark.asyncio
async def test_generate_document_publishes_event_and_creates_status(
    mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    from bff_service.api.routers.documents import (
        GenerateDocumentRequest,
        generate_document,
    )

    user_id = uuid.uuid4()
    template_version_id = uuid.uuid4()
    family_id = uuid.uuid4()

    mock_db = create_mock_session()
    mock_db.add = mocker.Mock()
    mock_kafka = mocker.AsyncMock()
    mock_kafka_client = mocker.MagicMock()
    mock_kafka_client.publish = mock_kafka
    monkeypatch.setattr("bff_service.api.routers.documents.kafka_client", mock_kafka_client)

    template_version = _make_template_version_projection(id=template_version_id, family_id=family_id)
    family = _make_template_family_projection(id=family_id, name="Resume Template")

    version_result = mocker.MagicMock()
    version_result.scalar_one_or_none.return_value = template_version
    family_result = mocker.MagicMock()
    family_result.scalar_one_or_none.return_value = family
    mock_db.execute.side_effect = [version_result, family_result]

    data = GenerateDocumentRequest(
        template_version_id=template_version_id,
        data={"name": "John Doe"},
        output_format="pdf",
    )

    result = await generate_document(data, user_id, mock_db)

    assert result.status == "accepted"
    assert result.request_id is not None
    mock_db.add.assert_called_once()
    mock_db.commit.assert_awaited_once()
    mock_kafka.assert_awaited_once()


@pytest.mark.asyncio
async def test_generate_document_raises_404_when_template_not_found(
    mocker: MockerFixture,
) -> None:
    from bff_service.api.routers.documents import (
        GenerateDocumentRequest,
        generate_document,
    )

    user_id = uuid.uuid4()
    template_version_id = uuid.uuid4()
    mock_db = create_mock_session()

    mock_result = mocker.MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = mock_result

    data = GenerateDocumentRequest(
        template_version_id=template_version_id,
        data={},
        output_format="pdf",
    )

    with pytest.raises(HTTPException) as exc_info:
        await generate_document(data, user_id, mock_db)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_get_document_status_returns_status(mocker: MockerFixture) -> None:
    """Test that get_document_status returns all fields including template_name."""
    from bff_service.api.routers.documents import get_document_status

    user_id = uuid.uuid4()
    request_id = uuid.uuid4()
    mock_db = create_mock_session()

    ts = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)
    doc_status = _make_document_status(
        request_id=request_id,
        user_id=user_id,
        status="completed",
        storage_key="s3://bucket/doc.pdf",
        output_format="pdf",
        created_at=ts,
    )
    # JOIN result: (DocumentGenerationStatus, template_name)
    mock_result = mocker.MagicMock()
    mock_result.one_or_none.return_value = (doc_status, "My Resume Template")
    mock_db.execute.return_value = mock_result

    result = await get_document_status(request_id, user_id, mock_db)

    assert result.request_id == str(request_id)
    assert result.status == "completed"
    assert result.download_url == "s3://bucket/doc.pdf"
    assert result.template_name == "My Resume Template"
    assert result.output_format == "pdf"
    assert result.created_at == ts


@pytest.mark.asyncio
async def test_get_document_status_template_name_none_when_template_deleted(
    mocker: MockerFixture,
) -> None:
    """Test that template_name is None when the template was deleted from projections."""
    from bff_service.api.routers.documents import get_document_status

    user_id = uuid.uuid4()
    request_id = uuid.uuid4()
    mock_db = create_mock_session()

    doc_status = _make_document_status(request_id=request_id, user_id=user_id, status="completed")
    # Outer join returns None for template_name when template row is absent
    mock_result = mocker.MagicMock()
    mock_result.one_or_none.return_value = (doc_status, None)
    mock_db.execute.return_value = mock_result

    result = await get_document_status(request_id, user_id, mock_db)

    assert result.template_name is None
    assert result.output_format == "pdf"


@pytest.mark.asyncio
async def test_get_document_status_raises_404_when_not_found(
    mocker: MockerFixture,
) -> None:
    from bff_service.api.routers.documents import get_document_status

    user_id = uuid.uuid4()
    request_id = uuid.uuid4()
    mock_db = create_mock_session()

    mock_result = mocker.MagicMock()
    mock_result.one_or_none.return_value = None
    mock_db.execute.return_value = mock_result

    with pytest.raises(HTTPException) as exc_info:
        await get_document_status(request_id, user_id, mock_db)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_list_documents_returns_user_documents(mocker: MockerFixture) -> None:
    """Test that list_documents returns documents with template names batch-resolved."""
    from bff_service.api.routers.documents import list_documents
    from nohiki_fastapi_utils import PaginationParams

    user_id = uuid.uuid4()
    mock_db = create_mock_session()
    pagination = PaginationParams(page=1, page_size=20)

    tpl_version_id1 = uuid.uuid4()
    tpl_version_id2 = uuid.uuid4()
    doc1 = _make_document_status(status="completed", template_version_id=tpl_version_id1)
    doc2 = _make_document_status(status="pending", template_version_id=tpl_version_id2)

    count_result = mocker.MagicMock()
    count_result.scalar.return_value = 2

    def _make_scalar_all(items: list[object]) -> SimpleNamespace:
        result = SimpleNamespace()
        result.all = lambda: items
        return result

    page_result = mocker.MagicMock()
    page_result.scalars.return_value = _make_scalar_all([doc1, doc2])

    # Third execute: batch template name lookup
    tpl_name_result = mocker.MagicMock()
    tpl_name_result.all.return_value = [
        (tpl_version_id1, "Resume Template"),
        (tpl_version_id2, "Cover Letter"),
    ]

    mock_db.execute.side_effect = [count_result, page_result, tpl_name_result]

    result = await list_documents(user_id, mock_db, pagination)

    assert result.total == 2
    assert len(result.items) == 2
    # Template names are resolved via the batch query
    assert result.items[0].template_name == "Resume Template"
    assert result.items[1].template_name == "Cover Letter"
    # output_format and created_at are propagated
    assert result.items[0].output_format == "pdf"
    assert result.items[0].created_at is not None


@pytest.mark.asyncio
async def test_list_documents_template_name_none_when_no_templates(
    mocker: MockerFixture,
) -> None:
    """Test that template_name is None when template_ids set is empty (no documents)."""
    from bff_service.api.routers.documents import list_documents
    from nohiki_fastapi_utils import PaginationParams

    user_id = uuid.uuid4()
    mock_db = create_mock_session()
    pagination = PaginationParams(page=1, page_size=20)

    count_result = mocker.MagicMock()
    count_result.scalar.return_value = 0

    def _make_scalar_all(items: list[object]) -> SimpleNamespace:
        result = SimpleNamespace()
        result.all = lambda: items
        return result

    page_result = mocker.MagicMock()
    page_result.scalars.return_value = _make_scalar_all([])

    # Only two execute calls when paginated.items is empty (no batch query)
    mock_db.execute.side_effect = [count_result, page_result]

    result = await list_documents(user_id, mock_db, pagination)

    assert result.total == 0
    assert result.items == []
    # Only count + page queries; no template batch query when items is empty
    assert mock_db.execute.call_count == 2


def test_output_format_to_proto_converts_pdf() -> None:
    from bff_service.api.routers.documents import _output_format_to_proto
    from nohiki.common.v1 import RenderOutputFormat

    result = _output_format_to_proto("pdf")
    assert result == RenderOutputFormat.PDF


def test_output_format_to_proto_converts_png() -> None:
    from bff_service.api.routers.documents import _output_format_to_proto
    from nohiki.common.v1 import RenderOutputFormat

    result = _output_format_to_proto("png")
    assert result == RenderOutputFormat.IMAGE


def test_output_format_to_proto_converts_html() -> None:
    from bff_service.api.routers.documents import _output_format_to_proto
    from nohiki.common.v1 import RenderOutputFormat

    result = _output_format_to_proto("html")
    assert result == RenderOutputFormat.HTML


def test_content_schema_uses_declared_draft_7_semantics() -> None:
    from bff_service.api.routers.documents import _validate_content_schema

    schema: dict[str, object] = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "dependentRequired": {"credit_card": ["billing_address"]},
    }

    _validate_content_schema({"credit_card": "1234"}, schema)


def test_validate_data_field_accepts_valid_input() -> None:
    from bff_service.api.routers.documents import _validate_data_field

    data: dict[str, object] = {"name": "John", "flag": True, "count": 42}
    assert _validate_data_field(data) is data


def test_validate_data_field_rejects_too_many_pairs() -> None:
    from bff_service.api.routers.documents import _validate_data_field
    from fastapi import HTTPException

    too_many: dict[str, object] = {str(i): i for i in range(101)}
    with pytest.raises(HTTPException) as exc_info:
        _validate_data_field(too_many)
    assert exc_info.value.status_code == 422


def test_validate_data_field_rejects_long_key() -> None:
    from bff_service.api.routers.documents import _validate_data_field
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        _validate_data_field({"x" * 65: "value"})
    assert exc_info.value.status_code == 422


def test_validate_data_field_rejects_large_value() -> None:
    from bff_service.api.routers.documents import _validate_data_field
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        _validate_data_field({"key": "x" * 50001})
    assert exc_info.value.status_code == 422


def test_struct_from_dict_preserves_bool() -> None:
    """Regression: str(True) returns 'True' (capital T) which breaks json.loads()."""
    from nohiki_proto_google.protobuf import Struct

    struct = Struct.from_dict({"enabled": True})
    result = struct.to_dict()
    assert result["enabled"] is True
