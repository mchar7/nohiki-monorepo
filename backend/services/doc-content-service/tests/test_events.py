"""Tests for events package - Kafka event handlers for doc-content-service."""

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from nohiki.common.v1 import EventMetadata, RenderOutputFormat
from nohiki.doc.content.v1 import (
    ContentGenerationContext,
    ContentGenerationRequested,
    TriggerType,
)
from nohiki.doc.template.v1 import DocumentTemplateVersionSnapshot
from nohiki.job.correlation.v1 import CorrelationEvaluated
from nohiki.job.listing.v1 import ListingNotificationSnapshot, ListingSnapshot
from nohiki.user.pref.v1 import SearchPrefSnapshot
from nohiki_common_exceptions import ValidationError


def _create_timestamp() -> datetime:
    return datetime.now(tz=UTC)


def _create_metadata(correlation_id: str | None = None) -> EventMetadata:
    return EventMetadata(
        event_id=str(uuid4()),
        timestamp=_create_timestamp(),
        source_service="test-service",
        correlation_id=correlation_id or str(uuid4()),
    )


class TestStartEventConsumer:
    """Tests for start_event_consumer function."""

    def test_start_event_consumer_calls_kafka_client(self) -> None:
        from doc_content_service.events import start_event_consumer

        with patch("doc_content_service.events.kafka_client") as mock_kafka:
            start_event_consumer()
            mock_kafka.start_consumers.assert_called_once()


class TestDefaultAutoGenerationThreshold:
    """Tests for DEFAULT_AUTO_GENERATION_THRESHOLD constant."""

    def test_default_threshold_value(self) -> None:
        from doc_content_service.events.upstream_cdc import (
            DEFAULT_AUTO_GENERATION_THRESHOLD,
        )

        assert DEFAULT_AUTO_GENERATION_THRESHOLD == 80


class TestHandleContentGenerationRequested:
    """Tests for handle_content_generation_requested handler."""

    @pytest.mark.asyncio
    async def test_processes_valid_request(self) -> None:
        from doc_content_service.events.handlers import (
            handle_content_generation_requested,
        )

        request_id = str(uuid4())
        user_id = str(uuid4())
        listing_id = str(uuid4())
        template_version_id = str(uuid4())
        template_id = str(uuid4())
        job_correlation_id = str(uuid4())

        pref_snapshot = SearchPrefSnapshot(
            id=str(uuid4()),
            user_id=user_id,
            pref_name="Test Pref",
        )
        listing_snapshot = ListingSnapshot(
            id=listing_id,
            listing_url="https://example.com/job",
            title="Software Engineer",
            company_name="TechCorp",
            description="A great job",
        )
        template_version = DocumentTemplateVersionSnapshot(
            version_id=template_version_id,
            version="1.0.0",
            template_content="<html></html>",
            content_schema_json=json.dumps({"type": "object"}),
        )
        ctx = ContentGenerationContext(
            listing=listing_snapshot,
            template_version=template_version,
        )
        message = ContentGenerationRequested(
            metadata=_create_metadata("upstream-correlation-id"),
            request_id=request_id,
            trigger_type=TriggerType.MANUAL,
            context=ctx,
            pref_snapshot=pref_snapshot,
            output_format=RenderOutputFormat.PDF,
            template_id=template_id,
            template_name="Tailored resume",
            job_correlation_id=job_correlation_id,
        )
        msg_context = MagicMock()

        with patch("doc_content_service.events.handlers.process_content_generation") as mock_process:
            await handle_content_generation_requested(message, msg_context)

        mock_process.assert_awaited_once()
        await_args = mock_process.await_args
        assert await_args is not None
        params = await_args.kwargs["params"]
        assert str(params.request_id) == request_id
        assert str(params.user_id) == user_id
        assert params.context is ctx
        assert params.pref_snapshot is pref_snapshot
        assert params.correlation_id == "upstream-correlation-id"
        assert params.output_format is RenderOutputFormat.PDF
        assert params.template_id == template_id
        assert params.template_name == "Tailored resume"
        assert params.job_correlation_id == job_correlation_id

    @pytest.mark.parametrize(
        ("field_name", "invalid_value"),
        [
            pytest.param("trigger_type", TriggerType.UNSPECIFIED, id="unspecified-trigger"),
            pytest.param("trigger_type", TriggerType(999), id="undefined-trigger"),
            pytest.param(
                "output_format",
                RenderOutputFormat.UNSPECIFIED,
                id="unspecified-output",
            ),
            pytest.param("output_format", RenderOutputFormat(999), id="undefined-output"),
        ],
    )
    @pytest.mark.asyncio
    async def test_rejects_invalid_enums_before_content_generation(
        self,
        field_name: str,
        invalid_value: TriggerType | RenderOutputFormat,
    ) -> None:
        """Legacy/open enum values cannot cross the current command boundary."""
        from doc_content_service.events.handlers import (
            handle_content_generation_requested,
        )

        request_id = str(uuid4())
        user_id = str(uuid4())
        message = ContentGenerationRequested(
            metadata=_create_metadata(request_id),
            request_id=request_id,
            trigger_type=TriggerType.MANUAL,
            context=ContentGenerationContext(
                listing=ListingSnapshot(
                    id=str(uuid4()),
                    listing_url="https://example.com/job",
                    title="Software Engineer",
                    company_name="TechCorp",
                    description="A great job",
                ),
                template_version=DocumentTemplateVersionSnapshot(
                    version_id=str(uuid4()),
                    version="1.0.0",
                    template_content="<html></html>",
                    content_schema_json='{"type":"object"}',
                ),
            ),
            pref_snapshot=SearchPrefSnapshot(id=str(uuid4()), user_id=user_id, pref_name="Test Pref"),
            output_format=RenderOutputFormat.PDF,
            template_id=str(uuid4()),
            job_correlation_id=str(uuid4()),
        )
        setattr(message, field_name, invalid_value)

        with (
            patch("doc_content_service.events.handlers.process_content_generation") as process,
            pytest.raises(ValidationError, match=field_name),
        ):
            await handle_content_generation_requested(message, MagicMock())

        process.assert_not_awaited()


class TestHandleJobMatched:
    """Tests for handle_job_matched handler."""

    @pytest.mark.asyncio
    async def test_logs_high_scoring_match(self) -> None:
        from doc_content_service.events.upstream_cdc import handle_job_matched

        pref_snapshot = SearchPrefSnapshot(
            id=str(uuid4()),
            user_id=str(uuid4()),
            pref_name="My Profile",
            auto_tailor_threshold=80,
        )
        listing_snapshot = ListingNotificationSnapshot(
            id=str(uuid4()),
            listing_url="https://example.com/job",
            title="Software Engineer",
            company_name="Test Corp",
        )
        message = CorrelationEvaluated(
            metadata=_create_metadata(),
            correlation_id=str(uuid4()),
            fit_score=90,
            pref_snapshot=pref_snapshot,
            listing_snapshot=listing_snapshot,
        )
        context = MagicMock()

        await handle_job_matched(message, context)

    @pytest.mark.asyncio
    async def test_uses_default_threshold_when_not_set(self) -> None:
        from doc_content_service.events.upstream_cdc import (
            DEFAULT_AUTO_GENERATION_THRESHOLD,
            handle_job_matched,
        )

        pref_snapshot = SearchPrefSnapshot(
            id=str(uuid4()),
            user_id=str(uuid4()),
            pref_name="My Profile",
            auto_tailor_threshold=0,
        )
        listing_snapshot = ListingNotificationSnapshot(
            id=str(uuid4()),
            listing_url="https://example.com/job",
            title="Software Engineer",
            company_name="Test Corp",
        )
        message = CorrelationEvaluated(
            metadata=_create_metadata(),
            correlation_id=str(uuid4()),
            fit_score=DEFAULT_AUTO_GENERATION_THRESHOLD + 5,
            pref_snapshot=pref_snapshot,
            listing_snapshot=listing_snapshot,
        )
        context = MagicMock()

        await handle_job_matched(message, context)
