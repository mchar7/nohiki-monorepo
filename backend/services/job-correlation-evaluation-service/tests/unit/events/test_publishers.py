"""Unit tests for transactional WAL event publishers."""

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from job_correlation_evaluation_service.events.publishers import (
    _build_listing_notification_snapshot,
    _collect_pref_uploads,
    publish_correlation_evaluated,
)
from job_correlation_evaluation_service.services.match_types import (
    JobMatchResult,
    MatchContext,
)
from job_correlation_evaluation_service.services.scoring.stages.deterministic_final import (
    FactorAttribution,
)
from nohiki.common.v1 import UploadReference
from nohiki.job.correlation.v1 import CorrelationEvaluated
from nohiki.job.listing.v1 import ListingSnapshot
from nohiki.user.pref.v1 import SearchPrefSnapshot
from nohiki_db_utils.testing import create_mock_session
from nohiki_kafka_client import Topics


class TestBuildListingNotificationSnapshot:
    """Tests for _build_listing_notification_snapshot function."""

    def test_builds_snapshot_with_location(self) -> None:
        """Test building snapshot with location data."""
        job = MagicMock(spec=ListingSnapshot)
        job.id = "job-123"
        job.listing_url = "https://example.com/job"
        job.title = "Software Engineer"
        job.company_name = "Tech Corp"
        job.location = MagicMock()
        job.location.city = "San Francisco"
        job.location.state_province = "CA"
        job.posted_at = None

        snapshot = _build_listing_notification_snapshot(job)

        assert snapshot.id == "job-123"
        assert snapshot.listing_url == "https://example.com/job"
        assert snapshot.title == "Software Engineer"
        assert snapshot.company_name == "Tech Corp"
        assert snapshot.location is job.location

    def test_builds_snapshot_without_location(self) -> None:
        """Test building snapshot without location data."""
        job = MagicMock(spec=ListingSnapshot)
        job.id = "job-123"
        job.listing_url = "https://example.com/job"
        job.title = "Software Engineer"
        job.company_name = "Tech Corp"
        job.location = None
        job.posted_at = None

        snapshot = _build_listing_notification_snapshot(job)

        assert snapshot.location is None

    def test_builds_snapshot_with_partial_location(self) -> None:
        """Test building snapshot with only city."""
        job = MagicMock(spec=ListingSnapshot)
        job.id = "job-123"
        job.listing_url = "https://example.com/job"
        job.title = "Software Engineer"
        job.company_name = "Tech Corp"
        job.location = MagicMock()
        job.location.city = "Remote"
        job.location.state_province = None
        job.posted_at = None

        snapshot = _build_listing_notification_snapshot(job)

        assert snapshot.location is job.location
        assert snapshot.location.city == "Remote"

    def test_builds_snapshot_with_posted_at(self) -> None:
        """Test building snapshot with posted_at timestamp."""
        job = MagicMock(spec=ListingSnapshot)
        job.id = "job-123"
        job.listing_url = "https://example.com/job"
        job.title = "Software Engineer"
        job.company_name = "Tech Corp"
        job.location = None
        job.posted_at = datetime.now(UTC)

        snapshot = _build_listing_notification_snapshot(job)

        assert snapshot.posted_at == job.posted_at

    def test_handles_missing_title_and_company(self) -> None:
        """Test building snapshot with missing title and company."""
        job = MagicMock(spec=ListingSnapshot)
        job.id = "job-123"
        job.listing_url = "https://example.com/job"
        job.title = None
        job.company_name = None
        job.location = None
        job.posted_at = None

        snapshot = _build_listing_notification_snapshot(job)

        assert snapshot.title == "Untitled"
        assert snapshot.company_name == ""


class TestCollectPrefUploads:
    """Tests for _collect_pref_uploads function."""

    def test_collects_both_upload_types(self) -> None:
        """Test collecting both example and context uploads."""
        mock_example = MagicMock()
        mock_context = MagicMock()
        mock_profile = MagicMock()
        mock_profile.example_uploads = [mock_example]
        mock_profile.context_uploads = [mock_context]

        uploads = _collect_pref_uploads(mock_profile)

        assert len(uploads) == 2
        assert mock_example in uploads
        assert mock_context in uploads

    def test_returns_empty_when_no_uploads(self) -> None:
        """Test returns empty list when no uploads."""
        mock_profile = MagicMock()
        mock_profile.example_uploads = []
        mock_profile.context_uploads = []

        uploads = _collect_pref_uploads(mock_profile)

        assert uploads == []


def _published_event(db: AsyncMock) -> CorrelationEvaluated:
    """Decode the protobuf written to the transactional WAL seam."""
    assert db.execute.await_args is not None
    statement, params = db.execute.await_args.args
    assert "pg_logical_emit_message(true" in str(statement)
    assert isinstance(params, dict)
    return CorrelationEvaluated().parse(params["content"])


class TestPublishCorrelationEvaluated:
    """Tests for publish_correlation_evaluated function."""

    @pytest.fixture
    def mock_result(self) -> JobMatchResult:
        """Create a deterministic result with human-facing factor evidence."""
        return JobMatchResult(
            pref_id="pref-123",
            listing_id="listing-456",
            listing_url="https://example.com/job",
            score=80,
            feature_schema_version="test",
            role_relevance_raw=81.5,
            ranking_index=0.8,
            factors=(
                FactorAttribution("skills", 0.92, 75, 1.75),
                FactorAttribution("location", 0.25, 50, -3.25),
            ),
        )

    @pytest.fixture
    def mock_context(self) -> MatchContext:
        """Create mock match context."""
        mock_job = MagicMock(spec=ListingSnapshot)
        mock_job.id = "listing-456"
        mock_job.listing_url = "https://example.com/job"
        mock_job.title = "Software Engineer"
        mock_job.company_name = "Tech Corp"
        mock_job.location = None
        mock_job.posted_at = None

        mock_profile = SearchPrefSnapshot(
            id="pref-123",
            user_id="user-123",
            pref_name="Test profile",
        )

        return MatchContext(
            listing_id="listing-456",
            listing_url="https://example.com/job",
            job=mock_job,
            profile=mock_profile,
            correlation_id="test-correlation",
        )

    @pytest.mark.asyncio
    async def test_writes_event_to_transactional_wal(
        self,
        mock_result: JobMatchResult,
        mock_context: MatchContext,
    ) -> None:
        """Correlation payload and routing envelope share the database transaction."""
        db = create_mock_session()

        await publish_correlation_evaluated(db, mock_result, mock_context)

        db.execute.assert_awaited_once()
        assert db.execute.await_args is not None
        statement, params = db.execute.await_args.args
        assert "pg_logical_emit_message(true" in str(statement)
        assert isinstance(params, dict)
        prefix = json.loads(params["prefix"])
        assert prefix["topic"] == Topics.JOB_CORRELATION_EVALUATED
        assert prefix["aggregate_id"] == str(mock_result.correlation_id)
        assert prefix["aggregate_type"] == "correlation"
        assert CorrelationEvaluated().parse(params["content"]).fit_score == 80
        db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_wal_event_contains_correct_data(
        self,
        mock_result: JobMatchResult,
        mock_context: MatchContext,
    ) -> None:
        """The WAL protobuf preserves human-facing correlation evidence."""
        db = create_mock_session()

        await publish_correlation_evaluated(db, mock_result, mock_context)

        event = _published_event(db)
        assert event.fit_score == 80
        assert event.correlation_id == str(mock_result.correlation_id)
        assert dict(event.correlation_metadata) == {}
        assert event.fit_ranking_breakdown is not None
        assert event.fit_ranking_breakdown.method_version == "deterministic-fit-v1"
        factors = event.fit_ranking_breakdown.factors
        assert [factor.factor.name for factor in factors] == [
            "ROLE_RELEVANCE",
            "SKILLS",
            "LOCATION",
        ]
        assert [factor.compatibility_score for factor in factors] == [81.5, 92.0, 25.0]
        assert [factor.importance for factor in factors] == [100, 75, 50]
        assert [factor.contribution_points for factor in factors] == [81.5, 1.75, -3.25]
        assert event.fit_score == round(sum(factor.contribution_points for factor in factors))

    @pytest.mark.asyncio
    async def test_includes_listing_snapshot(
        self,
        mock_result: JobMatchResult,
        mock_context: MatchContext,
    ) -> None:
        """The WAL event includes its notification snapshot."""
        db = create_mock_session()

        await publish_correlation_evaluated(db, mock_result, mock_context)

        event = _published_event(db)
        assert event.listing_snapshot is not None
        assert event.listing_snapshot.title == "Software Engineer"
        assert event.listing_snapshot.company_name == "Tech Corp"

    @pytest.mark.asyncio
    async def test_includes_profile_uploads(
        self,
        mock_result: JobMatchResult,
    ) -> None:
        """The WAL event includes profile uploads."""
        mock_job = MagicMock(spec=ListingSnapshot)
        mock_job.id = "listing-456"
        mock_job.listing_url = "https://example.com/job"
        mock_job.title = "Software Engineer"
        mock_job.company_name = "Tech Corp"
        mock_job.location = None
        mock_job.posted_at = None

        upload = UploadReference(id="upload-123", name="resume.pdf")
        mock_profile = SearchPrefSnapshot(
            id="pref-123",
            user_id="user-123",
            pref_name="Test profile",
            example_uploads=[upload],
        )

        context = MatchContext(
            listing_id="listing-456",
            listing_url="https://example.com/job",
            job=mock_job,
            profile=mock_profile,
            correlation_id="test-correlation",
        )
        db = create_mock_session()

        await publish_correlation_evaluated(db, mock_result, context)

        event = _published_event(db)
        assert len(event.pref_uploads) == 1
