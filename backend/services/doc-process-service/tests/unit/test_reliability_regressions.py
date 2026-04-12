"""Behavior-grade regressions for document processing reliability boundaries."""

from __future__ import annotations

from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch
from zipfile import ZipFile, ZipInfo

import httpx
import pytest
from doc_process_service.cache.manager import CacheManager
from doc_process_service.core.config import DoclingSettings, Settings, VLMSettings
from doc_process_service.events.handlers import _process_document
from doc_process_service.events.types import ProcessingParams
from doc_process_service.models.domain import ProcessingOptions
from doc_process_service.providers.docling.client import DoclingClient
from doc_process_service.services.processing import ProcessingService
from fastapi import FastAPI
from nohiki.common.v1 import CommandHeader
from nohiki.doc.process.v1 import ProcessedDocumentSnapshot, ProcessingLevel
from nohiki_s3_client import S3ObjectTooLargeError


def _client(*, poll_interval: float = 0.1, max_poll_attempts: int = 3) -> DoclingClient:
    return DoclingClient.from_settings(
        DoclingSettings(
            base_url="http://docling.test",
            poll_interval_seconds=poll_interval,
            max_poll_attempts=max_poll_attempts,
        ),
        VLMSettings(enabled=False),
    )


def _http_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "http://docling.test/v1/convert/file/async")
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError(f"HTTP {status_code}", request=request, response=response)


@pytest.mark.asyncio
async def test_oversized_content_is_rejected_before_cache_or_provider_call() -> None:
    service = ProcessingService.__new__(ProcessingService)
    cache = MagicMock(spec=CacheManager)
    client = MagicMock(spec=DoclingClient)
    object.__setattr__(service, "_settings", Settings(docling=DoclingSettings(max_document_bytes=4)))
    object.__setattr__(service, "_cache", cache)
    object.__setattr__(service, "_client", client)

    result = await service.process("content-id", b"12345", ProcessingOptions())

    assert result.error == "Document exceeds the configured size limit"
    assert result.is_retryable is False
    cache.get_processed.assert_not_called()
    client.process.assert_not_called()


@pytest.mark.asyncio
async def test_oversized_s3_document_is_rejected_before_download_or_provider_call() -> None:
    from doc_process_service.events.handlers import settings

    params = ProcessingParams(
        command=CommandHeader(operation_id="operation", callback_topic="callback"),
        storage_key="uploads/oversized.pdf",
        content_id="content-id",
        processing_level=ProcessingLevel.TABLES,
        correlation_id="correlation",
    )
    s3 = MagicMock()
    s3.get_object = AsyncMock(
        side_effect=S3ObjectTooLargeError(
            params.storage_key,
            settings.docling.max_document_bytes,
            settings.docling.max_document_bytes + 1,
        )
    )
    service = MagicMock()
    service.process = AsyncMock()
    publish_failed = AsyncMock()
    metrics = MagicMock()

    with (
        patch("doc_process_service.events.handlers.get_s3_client", return_value=s3),
        patch("doc_process_service.events.handlers._get_processing_service", return_value=service),
        patch("doc_process_service.events.handlers.publish_processing_failed", publish_failed),
        patch("doc_process_service.events.handlers.DocProcessMetrics.get", return_value=metrics),
    ):
        await _process_document(params)

    s3.get_object.assert_awaited_once_with(
        params.storage_key,
        max_bytes=settings.docling.max_document_bytes,
    )
    service.process.assert_not_awaited()
    assert publish_failed.await_args is not None
    assert publish_failed.await_args.kwargs["error_code"] == "DOCUMENT_TOO_LARGE"
    assert publish_failed.await_args.kwargs["is_retryable"] is False


@pytest.mark.asyncio
async def test_corrupt_cache_entry_falls_through_to_next_valid_processing_level() -> None:
    redis = MagicMock()
    valid_snapshot = ProcessedDocumentSnapshot(
        content_id="cached-id",
        content_hash="hash",
        level=ProcessingLevel.IMAGES,
        markdown="# recovered",
    )
    redis.get_bytes = AsyncMock(
        side_effect=[
            b"not valid snapshot json",
            valid_snapshot.to_json().encode(),
        ]
    )
    manager = CacheManager(redis, raw_ttl=60, processed_ttl=60)

    result = await manager.get_processed("hash", ProcessingOptions(extract_tables=True))

    assert result == valid_snapshot
    assert redis.get_bytes.await_count == 2


@pytest.mark.parametrize(
    ("failure", "retryable"),
    [
        pytest.param(_http_error(429), True, id="rate-limit"),
        pytest.param(_http_error(503), True, id="provider-5xx"),
        pytest.param(httpx.RequestError("connection reset"), True, id="transport"),
        pytest.param(_http_error(400), False, id="invalid-request"),
        pytest.param(ValueError("malformed result"), False, id="invalid-result"),
    ],
)
def test_provider_failure_classification_distinguishes_transient_from_terminal(
    failure: Exception,
    *,
    retryable: bool,
) -> None:
    client = _client()

    with (
        patch.object(DoclingClient, "is_available", return_value=True),
        patch.object(DoclingClient, "_process_document", side_effect=failure),
    ):
        result = client.process(b"%PDF", "content-id", ProcessingOptions())

    assert result.error == "Document processing failed"
    assert result.is_retryable is retryable


def test_failed_readiness_probe_is_not_cached_and_can_recover() -> None:
    client = _client()

    with patch("httpx.Client.get") as get:
        get.side_effect = [
            MagicMock(status_code=503),
            MagicMock(status_code=200),
        ]
        assert client.is_available() is False
        assert client.is_available() is True

    assert get.call_count == 2


def test_polling_stops_at_monotonic_deadline_even_before_attempt_limit() -> None:
    client = _client(poll_interval=0.1, max_poll_attempts=3)

    with (
        patch.object(DoclingClient, "_poll_once", return_value=None) as poll_once,
        patch("doc_process_service.providers.docling.client.time.monotonic", side_effect=[0.0, 0.0, 0.31]),
        patch("doc_process_service.providers.docling.client.time.sleep"),
        pytest.raises(TimeoutError, match="Timeout waiting"),
    ):
        client._poll_for_result(httpx.Client(), "task-id")

    poll_once.assert_called_once()


def test_docx_zip_signature_routes_upload_as_docx() -> None:
    archive = BytesIO()
    with ZipFile(archive, "w") as docx:
        entry = ZipInfo("word/document.xml", date_time=(2026, 1, 1, 0, 0, 0))
        docx.writestr(entry, "<w:document />")

    assert (
        _client()._detect_mime_type(archive.getvalue())
        == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )


@pytest.mark.parametrize("failing_resource", ["consumers", "kafka", "cache"])
@pytest.mark.asyncio
async def test_shutdown_closes_later_resources_when_an_earlier_cleanup_fails(failing_resource: str) -> None:
    from doc_process_service.main import lifespan

    kafka = MagicMock()
    kafka.stop_consumers = AsyncMock()
    kafka.close = AsyncMock()
    cache_close = AsyncMock()
    observability = MagicMock()

    failures = {
        "consumers": kafka.stop_consumers,
        "kafka": kafka.close,
        "cache": cache_close,
    }
    failures[failing_resource].side_effect = RuntimeError(f"{failing_resource} cleanup failed")

    with (
        patch("doc_process_service.main.ensure_kafka_ready", new=AsyncMock()),
        patch("doc_process_service.main.start_event_consumer"),
        patch("doc_process_service.main.kafka_client", kafka),
        patch("doc_process_service.main.CacheFactory.close_all", cache_close),
        patch("doc_process_service.main.obs", observability),
        pytest.raises(RuntimeError, match=f"{failing_resource} cleanup failed"),
    ):
        async with lifespan(FastAPI()):
            pass

    kafka.stop_consumers.assert_awaited_once()
    kafka.close.assert_awaited_once()
    cache_close.assert_awaited_once()
    observability.shutdown.assert_called_once()
