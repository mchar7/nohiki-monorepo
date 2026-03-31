"""Wire-contract tests for content generation output formats."""

from datetime import UTC, datetime

import pytest
from nohiki.common.v1 import EventMetadata, RenderOutputFormat
from nohiki.doc.content.v1 import (
    ContentGenerationContext,
    ContentGenerationRequested,
    TriggerType,
)
from nohiki.job.listing.v1 import ListingSnapshot
from nohiki.user.pref.v1 import SearchPrefSnapshot

_REQUEST_ID = "3a116497-3bd2-40e5-83e3-98eb492043f4"


def _request(output_format: RenderOutputFormat) -> ContentGenerationRequested:
    return ContentGenerationRequested(
        metadata=EventMetadata(
            event_id="4b11bad8-eaf7-4bf1-b762-a38791703521",
            timestamp=datetime(2026, 7, 13, 12, 30, tzinfo=UTC),
            source_service="bff-service",
            correlation_id="7aa20476-f60c-490b-94f3-18d8c9277c27",
            causation_id="4418b2d6-de2d-4b41-851c-c83fa6c76e51",
            version="v1",
            trace_id="f78b2378beef45d581659b636df06097",
        ),
        request_id=_REQUEST_ID,
        trigger_type=TriggerType.MANUAL,
        context=ContentGenerationContext(
            listing=ListingSnapshot(
                id="34fbe0bb-e02e-40ec-a3e9-6679e27bc1c1",
                listing_url="https://example.test/jobs/34fbe0bb",
                title="Platform Engineer",
                company_name="Example Co",
                description="Build reliable systems.",
                required_skills=["Python", "Kafka"],
                language="en",
            ),
        ),
        pref_snapshot=SearchPrefSnapshot(
            id="17300682-c8b2-431a-bd5e-7535f9d55e37",
            user_id="d5b7dc7c-082d-4a5a-b967-07941a5c1c39",
            pref_name="Platform roles",
            search_keywords=["platform", "distributed systems"],
            disallowed_keywords=["intern"],
        ),
        output_format=output_format,
        template_id="1bd9437c-8ab7-42e7-b28b-a114cbcd86e9",
        template_name="Platform application",
        job_correlation_id="a19c0ae4-d3ac-4a49-b31c-b7df27788c71",
    )


@pytest.mark.parametrize(
    "output_format",
    [output_format for output_format in RenderOutputFormat if output_format.value != 0],
    ids=lambda output_format: output_format.name.lower(),
)
def test_content_generation_requested_roundtrips_every_output_format(
    output_format: RenderOutputFormat,
) -> None:
    request = _request(output_format)

    restored = ContentGenerationRequested().parse(bytes(request))

    assert restored.output_format is output_format
    assert restored.request_id == _REQUEST_ID
    assert restored.trigger_type is TriggerType.MANUAL
    assert restored.metadata.event_id == request.metadata.event_id
    assert restored.metadata.correlation_id == request.metadata.correlation_id
    assert restored.context.listing.id == request.context.listing.id
    assert restored.context.listing.required_skills == ["Python", "Kafka"]
    assert restored.template_id == request.template_id
    assert restored.template_name == "Platform application"
    assert restored.job_correlation_id == request.job_correlation_id
    assert restored.pref_snapshot.id == request.pref_snapshot.id
    assert restored.pref_snapshot.search_keywords == ["platform", "distributed systems"]


def test_legacy_payload_without_output_format_decodes_without_corrupting_existing_fields() -> None:
    legacy_request = _request(RenderOutputFormat.UNSPECIFIED)
    legacy_payload = bytes(legacy_request)

    restored = ContentGenerationRequested().parse(legacy_payload)

    assert restored.output_format is RenderOutputFormat.UNSPECIFIED
    assert restored.request_id == _REQUEST_ID
    assert restored.trigger_type is TriggerType.MANUAL
    assert restored.metadata.event_id == legacy_request.metadata.event_id
    assert restored.metadata.correlation_id == legacy_request.metadata.correlation_id
    assert restored.context.listing.id == legacy_request.context.listing.id
    assert restored.context.listing.title == "Platform Engineer"
    assert restored.template_id == legacy_request.template_id
    assert restored.template_name == legacy_request.template_name
    assert restored.job_correlation_id == legacy_request.job_correlation_id
    assert restored.context.listing.required_skills == ["Python", "Kafka"]
    assert restored.pref_snapshot.id == legacy_request.pref_snapshot.id
    assert restored.pref_snapshot.pref_name == "Platform roles"
    assert restored.pref_snapshot.search_keywords == ["platform", "distributed systems"]
