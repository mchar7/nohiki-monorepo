"""Focused tests for the authenticated tailored-document BFF command."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from bff_service.api.routers.documents import (
    GenerateDocumentRequest,
    GenerateTailoredDocumentRequest,
    generate_document,
    generate_tailored_document,
)
from fastapi import HTTPException
from nohiki.common.v1 import AccessScope, Location, RenderOutputFormat, SubscriptionTier, UploadReference
from nohiki.job.listing.v1 import ListingSnapshot
from nohiki.user.pref.v1 import SearchPrefSnapshot
from nohiki_db_utils.testing import create_mock_session
from nohiki_kafka_client import Topics
from pytest_mock import MockerFixture
from user_entitlement_service.core.tiers import TIER_CONFIGS


def _upload(user_id: uuid.UUID, storage_key: str, *, name: str) -> UploadReference:
    return UploadReference(
        id=str(uuid.uuid4()),
        user_id=str(user_id),
        name=name,
        content_type="application/pdf",
        file_size=123,
        content_hash=f"hash-{name}",
        storage_key=storage_key,
    )


def _enterprise_upload_limit() -> int:
    return TIER_CONFIGS[SubscriptionTier.ENTERPRISE].max_uploads_per_pref


def _snapshots(
    user_id: uuid.UUID, pref_id: uuid.UUID, listing_id: uuid.UUID
) -> tuple[SearchPrefSnapshot, ListingSnapshot]:
    example = _upload(user_id, "users/example.pdf", name="example")
    context = _upload(user_id, "users/context.pdf", name="context")
    pref = SearchPrefSnapshot(
        id=str(pref_id),
        user_id=str(user_id),
        pref_name="Platform roles",
        search_keywords=["python", "kafka"],
        disallowed_keywords=["intern"],
        physical_locations=[Location(city="Berlin")],
        open_to_relocation=True,
        auto_tailor_threshold=81,
        tailoring_schema_id=str(uuid.uuid4()),
        tailoring_preferences={"tone": "direct", "length": "two-pages"},
        is_active=True,
        example_uploads=[example],
        context_uploads=[context],
    )
    listing = ListingSnapshot(
        id=str(listing_id),
        listing_url="https://jobs.example/platform",
        title="Platform Engineer",
        company_name="Example Co",
        description="Own the event platform",
        location=Location(city="Berlin"),
        required_skills=["Python", "Kafka"],
        language="en",
        experience_years_min=4,
        experience_years_max=8,
        discovered_at=datetime(2026, 7, 1, tzinfo=UTC),
        version=7,
        raw_content_hash="listing-hash",
        collection_version="skills-v4",
    )
    return pref, listing


def _successful_rows(
    user_id: uuid.UUID,
) -> tuple[SimpleNamespace, SimpleNamespace, SimpleNamespace, SearchPrefSnapshot]:
    pref_id = uuid.uuid4()
    listing_id = uuid.uuid4()
    correlation_id = uuid.uuid4()
    pref, listing = _snapshots(user_id, pref_id, listing_id)
    duplicate = _upload(user_id, "users/context.pdf", name="duplicate-context")
    extra = _upload(user_id, "users/cover-letter.pdf", name="cover-letter")
    correlation = SimpleNamespace(
        id=correlation_id,
        user_id=user_id,
        pref_id=pref_id,
        listing_id=listing_id,
        pref_snapshot=pref.to_dict(),
        pref_uploads=[duplicate.to_dict(), extra.to_dict()],
    )
    listing_projection = SimpleNamespace(id=listing_id, snapshot=listing.to_dict())
    template = SimpleNamespace(
        id=uuid.uuid4(),
        version_id=uuid.uuid4(),
        version="3.2.1",
        name="Tailored Resume",
        template_content="<html>{{ summary }}</html>",
        content_schema={"type": "object", "required": ["summary"]},
        description="Resume layout",
        access_scope=AccessScope.PUBLIC,
        owner_id=None,
        is_active=True,
    )
    return correlation, listing_projection, template, pref


def _result(value: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


@pytest.mark.asyncio
async def test_tailored_command_carries_complete_ecst_and_one_request_uuid(
    mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id = uuid.uuid4()
    correlation, listing, template, pref = _successful_rows(user_id)
    db = create_mock_session()
    db.add = mocker.Mock()
    db.execute.side_effect = [_result(correlation), _result(listing), _result(template)]
    publish = AsyncMock()
    monkeypatch.setattr("bff_service.api.routers.documents.kafka_client.publish", publish)

    response = await generate_tailored_document(
        GenerateTailoredDocumentRequest(
            job_correlation_id=correlation.id,
            template_id=template.id,
            output_format="html",
        ),
        user_id,
        db,
    )

    status_row = db.add.call_args.args[0]
    publish.assert_awaited_once()
    assert publish.await_args is not None
    kwargs = publish.await_args.kwargs
    event = kwargs["message"]
    assert response.request_id == str(status_row.request_id) == kwargs["key"]
    assert event.request_id == response.request_id
    assert event.metadata.correlation_id == response.request_id
    assert event.job_correlation_id == str(correlation.id)
    assert event.template_id == str(template.id)
    assert event.template_name == template.name
    assert event.output_format == RenderOutputFormat.HTML
    assert event.pref_snapshot.to_dict() == pref.to_dict()
    assert event.context.listing.to_dict() == listing.snapshot
    assert event.context.template_version.version_id == str(template.version_id)
    assert event.context.template_version.version == template.version
    assert event.context.template_version.template_content == template.template_content
    assert event.context.template_version.content_schema_json == '{"type": "object", "required": ["summary"]}'
    assert [upload.storage_key for upload in event.context.example_uploads] == ["users/example.pdf"]
    assert [upload.storage_key for upload in event.context.context_uploads] == [
        "users/context.pdf",
        "users/cover-letter.pdf",
    ]
    assert event.context.user_preferences is not None
    assert event.context.user_preferences.to_dict() == {
        "tone": "direct",
        "length": "two-pages",
    }
    assert status_row.user_id == user_id
    assert status_row.job_correlation_id == correlation.id
    assert status_row.pref_id == correlation.pref_id
    assert status_row.listing_id == correlation.listing_id
    assert status_row.template_version_id == template.version_id
    assert status_row.output_format == "html"
    assert status_row.status == "pending"
    assert kwargs["topic"] == Topics.DOC_CONTENT_GENERATION_REQUESTED
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_tailored_command_missing_or_foreign_correlation_is_not_disclosed() -> None:
    user_id = uuid.uuid4()
    correlation_id = uuid.uuid4()
    db = create_mock_session()
    db.execute.return_value = _result(None)

    with pytest.raises(HTTPException) as exc_info:
        await generate_tailored_document(
            GenerateTailoredDocumentRequest(job_correlation_id=correlation_id, template_id=uuid.uuid4()),
            user_id,
            db,
        )

    assert exc_info.value.status_code == 404
    stmt = db.execute.await_args.args[0]
    sql = str(stmt.compile(compile_kwargs={"literal_binds": False}))
    assert "job_correlation_projections.user_id" in sql
    assert "job_correlation_projections.id" in sql
    db.add.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["listing", "pref", "listing_snapshot"])
async def test_tailored_command_rejects_absent_snapshots(missing: str) -> None:
    user_id = uuid.uuid4()
    correlation, listing, template, _pref = _successful_rows(user_id)
    if missing == "pref":
        correlation.pref_snapshot = None
    if missing == "listing_snapshot":
        listing.snapshot = None
    rows = [
        _result(correlation),
        _result(None if missing == "listing" else listing),
        _result(template),
    ]
    db = create_mock_session()
    db.execute.side_effect = rows

    with pytest.raises(HTTPException) as exc_info:
        await generate_tailored_document(
            GenerateTailoredDocumentRequest(job_correlation_id=correlation.id, template_id=template.id),
            user_id,
            db,
        )

    assert exc_info.value.status_code == 409
    db.add.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("malformed", [{"unknownField": object()}, "not-json"])
async def test_tailored_command_rejects_malformed_stored_snapshots(
    malformed: object,
) -> None:
    user_id = uuid.uuid4()
    correlation, listing, template, _pref = _successful_rows(user_id)
    correlation.pref_snapshot = malformed
    db = create_mock_session()
    db.execute.side_effect = [_result(correlation), _result(listing), _result(template)]

    with pytest.raises(HTTPException) as exc_info:
        await generate_tailored_document(
            GenerateTailoredDocumentRequest(job_correlation_id=correlation.id, template_id=template.id),
            user_id,
            db,
        )

    assert exc_info.value.status_code == 409
    db.add.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("conflict", ["pref_id", "pref_user", "listing_id", "inactive"])
async def test_tailored_command_rejects_stale_or_inactive_pref_snapshot(
    conflict: str,
) -> None:
    user_id = uuid.uuid4()
    correlation, listing, template, pref = _successful_rows(user_id)
    if conflict == "pref_id":
        pref.id = str(uuid.uuid4())
    elif conflict == "pref_user":
        pref.user_id = str(uuid.uuid4())
    elif conflict == "listing_id":
        listing.snapshot["id"] = str(uuid.uuid4())
    else:
        pref.is_active = False
    correlation.pref_snapshot = pref.to_dict()
    db = create_mock_session()
    db.execute.side_effect = [_result(correlation), _result(listing), _result(template)]

    with pytest.raises(HTTPException) as exc_info:
        await generate_tailored_document(
            GenerateTailoredDocumentRequest(job_correlation_id=correlation.id, template_id=template.id),
            user_id,
            db,
        )

    assert exc_info.value.status_code == 409
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_tailored_command_rejects_unowned_or_incomplete_template() -> None:
    user_id = uuid.uuid4()
    correlation, listing, template, _pref = _successful_rows(user_id)
    db = create_mock_session()
    db.execute.side_effect = [_result(correlation), _result(listing), _result(None)]

    with pytest.raises(HTTPException) as exc_info:
        await generate_tailored_document(
            GenerateTailoredDocumentRequest(job_correlation_id=correlation.id, template_id=template.id),
            user_id,
            db,
        )

    assert exc_info.value.status_code == 404
    template_stmt = db.execute.await_args_list[2].args[0]
    sql = str(template_stmt.compile(compile_kwargs={"literal_binds": False}))
    assert "template_projections.is_active" in sql
    assert "template_projections.access_scope" in sql
    assert "template_projections.owner_id" in sql

    template.version_id = None
    db = create_mock_session()
    db.execute.side_effect = [_result(correlation), _result(listing), _result(template)]
    with pytest.raises(HTTPException) as incomplete:
        await generate_tailored_document(
            GenerateTailoredDocumentRequest(job_correlation_id=correlation.id, template_id=template.id),
            user_id,
            db,
        )
    assert incomplete.value.status_code == 409


@pytest.mark.asyncio
async def test_tailored_command_rejects_foreign_or_empty_upload_references() -> None:
    user_id = uuid.uuid4()
    correlation, listing, template, _pref = _successful_rows(user_id)
    for bad_upload in (
        _upload(uuid.uuid4(), "users/foreign.pdf", name="foreign"),
        _upload(user_id, "", name="missing-key"),
    ):
        correlation.pref_uploads = [bad_upload.to_dict()]
        db = create_mock_session()
        db.execute.side_effect = [
            _result(correlation),
            _result(listing),
            _result(template),
        ]
        with pytest.raises(HTTPException) as exc_info:
            await generate_tailored_document(
                GenerateTailoredDocumentRequest(job_correlation_id=correlation.id, template_id=template.id),
                user_id,
                db,
            )
        assert exc_info.value.status_code == 409
        db.add.assert_not_called()


@pytest.mark.asyncio
async def test_tailored_command_accepts_enterprise_upload_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid.uuid4()
    correlation, listing, template, pref = _successful_rows(user_id)
    pref.example_uploads = [
        _upload(user_id, f"users/example-{index}.pdf", name=f"example-{index}")
        for index in range(_enterprise_upload_limit() - len(pref.context_uploads))
    ]
    correlation.pref_snapshot = pref.to_dict()
    correlation.pref_uploads = []
    db = create_mock_session()
    db.execute.side_effect = [_result(correlation), _result(listing), _result(template)]
    publish = AsyncMock()
    monkeypatch.setattr("bff_service.api.routers.documents.kafka_client.publish", publish)

    await generate_tailored_document(
        GenerateTailoredDocumentRequest(
            job_correlation_id=correlation.id,
            template_id=template.id,
        ),
        user_id,
        db,
    )

    db.add.assert_called_once()
    db.commit.assert_awaited_once()
    publish.assert_awaited_once()


@pytest.mark.asyncio
async def test_tailored_command_rejects_more_than_enterprise_upload_limit_before_side_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid.uuid4()
    correlation, listing, template, pref = _successful_rows(user_id)
    pref.example_uploads = [
        _upload(user_id, f"users/example-{index}.pdf", name=f"example-{index}")
        for index in range(_enterprise_upload_limit())
    ]
    correlation.pref_snapshot = pref.to_dict()
    correlation.pref_uploads = []
    db = create_mock_session()
    db.execute.side_effect = [_result(correlation), _result(listing), _result(template)]
    publish = AsyncMock()
    monkeypatch.setattr("bff_service.api.routers.documents.kafka_client.publish", publish)

    with pytest.raises(HTTPException) as exc_info:
        await generate_tailored_document(
            GenerateTailoredDocumentRequest(
                job_correlation_id=correlation.id,
                template_id=template.id,
            ),
            user_id,
            db,
        )

    assert exc_info.value.status_code == 409
    db.add.assert_not_called()
    db.commit.assert_not_awaited()
    publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_direct_render_route_still_publishes_direct_render_topic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid.uuid4()
    template_id = uuid.uuid4()
    template = SimpleNamespace(
        id=template_id,
        name="Direct",
        version="1.0.0",
        template_content="<html>{{ name }}</html>",
        content_schema=None,
    )
    db = create_mock_session()
    db.execute.return_value = _result(template)
    publish = AsyncMock()
    monkeypatch.setattr("bff_service.api.routers.documents.kafka_client.publish", publish)

    await generate_document(
        GenerateDocumentRequest(template_version_id=template_id, data={"name": "Ada"}),
        user_id,
        db,
    )

    assert publish.await_args is not None
    assert publish.await_args.kwargs["topic"] == Topics.DOC_TEMPLATE_RENDER_REQUESTED


def test_tailored_command_requires_authentication() -> None:
    from bff_service.api.deps.auth import get_current_user_id_from_cookie
    from bff_service.api.routers.documents import router
    from bff_service.core.db import get_async_db
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/documents")

    async def _reject_auth() -> None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    app.dependency_overrides[get_current_user_id_from_cookie] = _reject_auth
    app.dependency_overrides[get_async_db] = lambda: None
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/api/v1/documents/generate-tailored",
        json={
            "job_correlation_id": str(uuid.uuid4()),
            "template_id": str(uuid.uuid4()),
            "output_format": "pdf",
        },
    )

    assert response.status_code == 401
