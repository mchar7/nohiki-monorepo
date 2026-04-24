"""Tests for template_registry module.

This module tests the template registry that maps event types to notification
templates for domain-agnostic notification handling.
"""

from __future__ import annotations

import dataclasses

import pytest
from nohiki.doc.content.v1 import ContentGenerationCompleted
from nohiki.job.correlation.v1 import CorrelationEvaluated
from nohiki.job.listing.v1 import ListingNotificationSnapshot
from notification_service.services.template_registry import (
    EVENT_TYPE_CONTENT_GENERATION_COMPLETED,
    EVENT_TYPE_CORRELATION_EVALUATED,
    TEMPLATE_REGISTRY,
    TemplateConfig,
    _job_match_score_extractor,
    _no_score,
    extract_content_generation_context,
    extract_job_match_context,
    get_template_config,
)


class TestGetTemplateConfig:
    """Tests for get_template_config function."""

    def test_returns_none_for_unregistered_event_type(self) -> None:
        """Should return None for event types not in the registry."""
        result = get_template_config("unknown.event.type")
        assert result is None

    def test_returns_config_for_correlation_evaluated(self) -> None:
        """Should return TemplateConfig for CorrelationEvaluated event type."""
        result = get_template_config(EVENT_TYPE_CORRELATION_EVALUATED)

        assert result is not None
        assert isinstance(result, TemplateConfig)
        assert result.template_name == "job_match"
        assert result.subject_template == "New Job Match: {listing_title} at {company_name}"
        assert result.uses_threshold is True
        assert result.requires_completed_status is False

    def test_returns_config_for_content_generation_completed(self) -> None:
        """Should return TemplateConfig for ContentGenerationCompleted event type."""
        result = get_template_config(EVENT_TYPE_CONTENT_GENERATION_COMPLETED)

        assert result is not None
        assert isinstance(result, TemplateConfig)
        assert result.template_name == "content_generation_completed"
        assert result.subject_template == "Your Generated Document for {listing_title}"
        assert result.uses_threshold is False
        assert result.requires_completed_status is True


class TestExtractJobMatchContext:
    """Tests for extract_job_match_context function."""

    def test_extracts_all_fields_with_listing_snapshot(self) -> None:
        """Should extract all fields correctly when listing_snapshot is present."""
        listing_snapshot = ListingNotificationSnapshot(
            id="listing-123",
            title="Senior Python Developer",
            company_name="Acme Corp",
            listing_url="https://example.com/job/123",
        )
        event = CorrelationEvaluated(
            correlation_id="corr-456",
            fit_score=85,
            listing_snapshot=listing_snapshot,
        )

        context = extract_job_match_context(event)

        assert context["listing_title"] == "Senior Python Developer"
        assert context["company_name"] == "Acme Corp"
        assert context["listing_url"] == "https://example.com/job/123"
        assert context["fit_score"] == 85
        assert context["correlation_id"] == "corr-456"
        assert context["listing_id"] == "listing-123"

    def test_raises_error_when_listing_snapshot_is_missing(self) -> None:
        """Should raise ValueError when listing_snapshot is missing (fail-fast for ECST)."""
        event = CorrelationEvaluated(
            correlation_id="corr-789",
            fit_score=75,
        )

        with pytest.raises(ValueError, match="listing_snapshot is required"):
            extract_job_match_context(event)

    def test_handles_empty_company_name(self) -> None:
        """Should handle empty company_name in listing_snapshot."""
        listing_snapshot = ListingNotificationSnapshot(
            id="listing-empty",
            title="Developer Role",
            company_name="",
            listing_url="https://example.com/job/456",
        )
        event = CorrelationEvaluated(
            correlation_id="corr-empty",
            fit_score=60,
            listing_snapshot=listing_snapshot,
        )

        context = extract_job_match_context(event)

        assert context["listing_title"] == "Developer Role"
        assert context["company_name"] == ""
        assert context["listing_url"] == "https://example.com/job/456"


class TestExtractContentGenerationContext:
    """Tests for extract_content_generation_context function."""

    def test_extracts_all_fields_with_listing_snapshot(self) -> None:
        """Should extract all fields correctly when listing_snapshot is present."""
        listing_snapshot = ListingNotificationSnapshot(
            id="listing-content-123",
            title="Backend Engineer",
            company_name="TechCo",
            listing_url="https://example.com/job/content",
        )
        event = ContentGenerationCompleted(
            request_id="req-111",
            listing_id="listing-content-123",
            listing_snapshot=listing_snapshot,
        )

        context = extract_content_generation_context(event)

        assert context["listing_title"] == "Backend Engineer"
        assert context["company_name"] == "TechCo"
        assert context["request_id"] == "req-111"
        assert context["listing_id"] == "listing-content-123"

    def test_handles_missing_listing_snapshot(self) -> None:
        """Should return None for missing fields when listing_snapshot is missing."""
        event = ContentGenerationCompleted(
            request_id="req-222",
            listing_id="listing-content-456",
        )

        context = extract_content_generation_context(event)

        # For content generation, listing_snapshot is optional - returns None for missing fields
        assert context["listing_title"] is None
        assert context["company_name"] is None
        assert context["request_id"] == "req-222"
        assert context["listing_id"] == "listing-content-456"

    def test_handles_empty_fields_in_listing_snapshot(self) -> None:
        """Should return empty fields when listing_snapshot has empty fields."""
        listing_snapshot = ListingNotificationSnapshot(
            id="listing-content-456",
            title="",
            company_name="",
        )
        event = ContentGenerationCompleted(
            request_id="req-222",
            listing_id="listing-content-456",
            listing_snapshot=listing_snapshot,
        )

        context = extract_content_generation_context(event)

        # For content generation with empty snapshot fields
        assert context["listing_title"] == ""
        assert context["company_name"] == ""
        assert context["request_id"] == "req-222"
        assert context["listing_id"] == "listing-content-456"

    def test_handles_empty_company_name(self) -> None:
        """Should handle empty company_name in listing_snapshot."""
        listing_snapshot = ListingNotificationSnapshot(
            id="listing-no-company",
            title="Full Stack Developer",
            company_name="",
            listing_url="https://example.com/job/nocompany",
        )
        event = ContentGenerationCompleted(
            request_id="req-333",
            listing_id="listing-no-company",
            listing_snapshot=listing_snapshot,
        )

        context = extract_content_generation_context(event)

        assert context["listing_title"] == "Full Stack Developer"
        assert context["company_name"] == ""


class TestScoreExtractors:
    """Tests for score extractor functions."""

    def test_job_match_score_extractor_returns_fit_score(self) -> None:
        """Should return the fit_score from CorrelationEvaluated event."""
        event = CorrelationEvaluated(
            correlation_id="corr-score-test",
            fit_score=92,
        )

        result = _job_match_score_extractor(event)

        assert result == 92

    def test_job_match_score_extractor_returns_zero_fit_score(self) -> None:
        """Should return zero fit_score when event has zero score."""
        event = CorrelationEvaluated(
            correlation_id="corr-zero-score",
            fit_score=0,
        )

        result = _job_match_score_extractor(event)

        assert result == 0

    def test_no_score_returns_none(self) -> None:
        """Should return None for any event."""
        event = ContentGenerationCompleted(
            request_id="req-no-score",
            listing_id="listing-no-score",
        )

        result = _no_score(event)

        assert result is None

    def test_no_score_with_content_generation_event(self) -> None:
        """Should return None for ContentGenerationCompleted event."""
        listing_snapshot = ListingNotificationSnapshot(
            id="listing-no-score-content",
            title="Engineer",
            company_name="Company",
            listing_url="https://example.com",
        )
        event = ContentGenerationCompleted(
            request_id="req-no-score",
            listing_id="listing-no-score-content",
            listing_snapshot=listing_snapshot,
        )

        result = _no_score(event)

        assert result is None


class TestTemplateConfigProperties:
    """Tests for TemplateConfig dataclass properties."""

    def test_job_match_config_properties(self) -> None:
        """Job match config should use threshold, not require completed status."""
        config = TEMPLATE_REGISTRY[EVENT_TYPE_CORRELATION_EVALUATED]

        assert config.uses_threshold is True
        assert config.requires_completed_status is False
        assert config.template_name == "job_match"
        assert callable(config.context_extractor)
        assert callable(config.score_extractor)

    def test_content_generation_config_properties(self) -> None:
        """Content generation config should not use threshold, require completed status."""
        config = TEMPLATE_REGISTRY[EVENT_TYPE_CONTENT_GENERATION_COMPLETED]

        assert config.uses_threshold is False
        assert config.requires_completed_status is True
        assert config.template_name == "content_generation_completed"
        assert callable(config.context_extractor)
        assert callable(config.score_extractor)

    def test_template_config_is_frozen_dataclass(self) -> None:
        """TemplateConfig should be a frozen dataclass."""
        assert dataclasses.is_dataclass(TemplateConfig)
        params = getattr(TemplateConfig, "__dataclass_params__", None)
        assert params is not None
        assert params.frozen is True

    def test_registry_contains_expected_entries(self) -> None:
        """Registry should contain exactly the expected event types."""
        expected_keys = {
            EVENT_TYPE_CORRELATION_EVALUATED,
            EVENT_TYPE_CONTENT_GENERATION_COMPLETED,
        }

        assert set(TEMPLATE_REGISTRY.keys()) == expected_keys


class TestSubjectTemplateFormatting:
    """Tests for subject template formatting with context."""

    def test_job_match_subject_formatting(self) -> None:
        """Subject template should format correctly with job match context."""
        config = TEMPLATE_REGISTRY[EVENT_TYPE_CORRELATION_EVALUATED]
        listing_snapshot = ListingNotificationSnapshot(
            id="fmt-listing",
            title="ML Engineer",
            company_name="DataCo",
            listing_url="https://example.com",
        )
        event = CorrelationEvaluated(
            correlation_id="fmt-corr",
            fit_score=88,
            listing_snapshot=listing_snapshot,
        )

        context = config.context_extractor(event)
        subject = config.subject_template.format(**context)

        assert subject == "New Job Match: ML Engineer at DataCo"

    def test_content_generation_subject_formatting(self) -> None:
        """Subject template should format correctly with content generation context."""
        config = TEMPLATE_REGISTRY[EVENT_TYPE_CONTENT_GENERATION_COMPLETED]
        listing_snapshot = ListingNotificationSnapshot(
            id="fmt-content-listing",
            title="DevOps Engineer",
            company_name="CloudCo",
            listing_url="https://example.com",
        )
        event = ContentGenerationCompleted(
            request_id="fmt-content-req",
            listing_id="fmt-content-listing",
            listing_snapshot=listing_snapshot,
        )

        context = config.context_extractor(event)
        subject = config.subject_template.format(**context)

        assert subject == "Your Generated Document for DevOps Engineer"

    def test_job_match_subject_with_missing_snapshot_raises_error(self) -> None:
        """Should raise ValueError when listing_snapshot is missing (fail-fast for ECST)."""
        config = TEMPLATE_REGISTRY[EVENT_TYPE_CORRELATION_EVALUATED]
        event = CorrelationEvaluated(
            correlation_id="default-corr",
            fit_score=50,
        )

        with pytest.raises(ValueError, match="listing_snapshot is required"):
            config.context_extractor(event)


class TestEventTypeConstants:
    """Tests for event type constant values."""

    def test_correlation_evaluated_constant(self) -> None:
        """Correlation evaluated constant should have correct value."""
        assert EVENT_TYPE_CORRELATION_EVALUATED == "nohiki.job.correlation.v1.CorrelationEvaluated"

    def test_content_generation_completed_constant(self) -> None:
        """Content generation completed constant should have correct value."""
        assert EVENT_TYPE_CONTENT_GENERATION_COMPLETED == "nohiki.doc.content.v1.ContentGenerationCompleted"
