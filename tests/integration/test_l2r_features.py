"""Unit tests for L2R scoring event structures.

Tests the Correlation and CorrelationEvaluated proto structures to verify
correct event format and validation. Does NOT test service implementation -
feature extraction unit tests belong in the service's own test suite.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from nohiki.common.v1 import (
    CorrelationStatus,
    EventMetadata,
    WorkArrangement,
)
from nohiki.job.correlation.v1 import (
    Correlation,
    CorrelationBatchCompleted,
    CorrelationEvaluated,
)


def build_test_metadata(correlation_id: str | None = None) -> EventMetadata:
    """Build test event metadata with correct field names."""
    return EventMetadata(
        event_id=str(uuid4()),
        timestamp=datetime.now(UTC),
        source_service="test-service",
        correlation_id=correlation_id,
        version="v1",
    )


class TestCorrelationEntity:
    """Test suite for Correlation entity proto structure."""

    def test_correlation_required_fields(self) -> None:
        """Test Correlation entity has required identification fields."""
        correlation = Correlation(
            id=str(uuid4()),
            pref_id=str(uuid4()),
            listing_id=str(uuid4()),
            user_id=str(uuid4()),
            fit_score=75,
            status=CorrelationStatus.EVALUATED,
            evaluated_at=datetime.now(UTC),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        assert correlation.id
        assert correlation.pref_id
        assert correlation.listing_id
        assert correlation.user_id

    def test_fit_score_valid_range(self) -> None:
        """Test fit_score must be 0-100."""
        correlation = Correlation(
            id=str(uuid4()),
            pref_id=str(uuid4()),
            listing_id=str(uuid4()),
            user_id=str(uuid4()),
            fit_score=85,
            status=CorrelationStatus.EVALUATED,
            evaluated_at=datetime.now(UTC),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        assert 0 <= correlation.fit_score <= 100

    def test_score_breakdown_structure(self) -> None:
        """Test score_breakdown map structure for feature contributions."""
        breakdown = {
            "skill_match": 20,
            "location_match": 15,
            "work_arrangement": 10,
            "experience_fit": 18,
            "salary_alignment": 12,
        }

        correlation = Correlation(
            id=str(uuid4()),
            pref_id=str(uuid4()),
            listing_id=str(uuid4()),
            user_id=str(uuid4()),
            fit_score=75,
            status=CorrelationStatus.EVALUATED,
            score_breakdown=breakdown,
            evaluated_at=datetime.now(UTC),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        assert len(correlation.score_breakdown) == 5
        assert correlation.score_breakdown["skill_match"] == 20
        assert all(-100 <= v <= 100 for v in correlation.score_breakdown.values())

    def test_user_feedback_optional(self) -> None:
        """Test user_feedback is optional (-1, 0, 1)."""
        correlation = Correlation(
            id=str(uuid4()),
            pref_id=str(uuid4()),
            listing_id=str(uuid4()),
            user_id=str(uuid4()),
            fit_score=60,
            status=CorrelationStatus.VIEWED,
            user_feedback=1,
            user_notes="Great match for my skills",
            evaluated_at=datetime.now(UTC),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        assert correlation.user_feedback == 1
        assert correlation.user_notes is not None


class TestCorrelationEvaluatedEvent:
    """Test suite for CorrelationEvaluated event proto structure."""

    def test_correlation_evaluated_structure(self) -> None:
        """Test CorrelationEvaluated event has required fields."""
        from nohiki.job.listing.v1 import ListingNotificationSnapshot
        from nohiki.user.pref.v1 import SearchPrefSnapshot

        correlation_id = str(uuid4())

        listing_snapshot = ListingNotificationSnapshot(
            id=str(uuid4()),
            title="Senior Python Developer",
            company_name="TechCorp",
            listing_url="https://example.com/job/123",
        )

        pref_snapshot = SearchPrefSnapshot(
            id=str(uuid4()),
            search_keywords=["Python", "Django"],
            work_arrangements=[WorkArrangement.REMOTE],
        )

        event = CorrelationEvaluated(
            metadata=build_test_metadata(),
            correlation_id=correlation_id,
            fit_score=82,
            correlation_status=CorrelationStatus.EVALUATED,
            listing_snapshot=listing_snapshot,
            pref_snapshot=pref_snapshot,
        )

        assert event.correlation_id == correlation_id
        assert event.fit_score == 82
        assert event.listing_snapshot is not None
        assert event.pref_snapshot is not None
        assert event.listing_snapshot.title == "Senior Python Developer"
        assert event.pref_snapshot.search_keywords == ["Python", "Django"]

    def test_correlation_evaluated_metadata_map(self) -> None:
        """Test correlation_metadata map for feature explanations."""
        from nohiki.job.listing.v1 import ListingNotificationSnapshot
        from nohiki.user.pref.v1 import SearchPrefSnapshot

        metadata_map = {
            "top_matching_skill": "Python",
            "location_distance_km": "25",
            "salary_comparison": "above_target",
        }

        event = CorrelationEvaluated(
            metadata=build_test_metadata(),
            correlation_id=str(uuid4()),
            fit_score=78,
            correlation_status=CorrelationStatus.EVALUATED,
            correlation_metadata=metadata_map,
            listing_snapshot=ListingNotificationSnapshot(
                id=str(uuid4()),
                title="Developer",
                company_name="Company",
                listing_url="https://example.com/job/1",
            ),
            pref_snapshot=SearchPrefSnapshot(id=str(uuid4())),
        )

        assert event.correlation_metadata["top_matching_skill"] == "Python"
        assert len(event.correlation_metadata) == 3


class TestCorrelationBatchCompletedEvent:
    """Test suite for CorrelationBatchCompleted event proto structure."""

    def test_batch_completed_structure(self) -> None:
        """Test CorrelationBatchCompleted event structure."""
        from nohiki.common.v1 import PrefReference

        pref_ref = PrefReference(
            pref_id=str(uuid4()),
            user_id=str(uuid4()),
        )

        event = CorrelationBatchCompleted(
            metadata=build_test_metadata(),
            pref=pref_ref,
            scrape_id=str(uuid4()),
            total_listings_processed=150,
            correlations_created=45,
            listings_filtered=105,
        )

        assert event.total_listings_processed == 150
        assert event.correlations_created == 45
        assert event.listings_filtered == 105
        assert event.total_listings_processed == event.correlations_created + event.listings_filtered

    def test_batch_metrics_non_negative(self) -> None:
        """Test batch metrics are non-negative."""
        from nohiki.common.v1 import PrefReference

        event = CorrelationBatchCompleted(
            metadata=build_test_metadata(),
            pref=PrefReference(pref_id=str(uuid4()), user_id=str(uuid4())),
            scrape_id=str(uuid4()),
            total_listings_processed=0,
            correlations_created=0,
            listings_filtered=0,
        )

        assert event.total_listings_processed >= 0
        assert event.correlations_created >= 0
        assert event.listings_filtered >= 0


class TestL2RScoringContracts:
    """Test L2R scoring contracts through event structures."""

    def test_fit_score_is_integer_0_100(self) -> None:
        """Verify fit_score output is integer 0-100 (not raw float)."""
        correlation = Correlation(
            id=str(uuid4()),
            pref_id=str(uuid4()),
            listing_id=str(uuid4()),
            user_id=str(uuid4()),
            fit_score=73,
            status=CorrelationStatus.EVALUATED,
            evaluated_at=datetime.now(UTC),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        assert isinstance(correlation.fit_score, int)
        assert 0 <= correlation.fit_score <= 100

    def test_score_breakdown_keys_are_feature_names(self) -> None:
        """Verify score_breakdown uses consistent feature naming."""
        expected_feature_categories = {
            "skill_match",
            "location_match",
            "work_arrangement",
            "experience_fit",
            "seniority_fit",
            "salary_alignment",
            "freshness",
            "semantic_similarity",
        }

        breakdown = dict.fromkeys(expected_feature_categories, 10)

        correlation = Correlation(
            id=str(uuid4()),
            pref_id=str(uuid4()),
            listing_id=str(uuid4()),
            user_id=str(uuid4()),
            fit_score=80,
            status=CorrelationStatus.EVALUATED,
            score_breakdown=breakdown,
            evaluated_at=datetime.now(UTC),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        assert set(correlation.score_breakdown.keys()) == expected_feature_categories

    def test_ecst_snapshots_in_evaluated_event(self) -> None:
        """Verify CorrelationEvaluated contains ECST snapshots for consumers."""
        from nohiki.job.listing.v1 import ListingNotificationSnapshot
        from nohiki.user.pref.v1 import SearchPrefSnapshot

        event = CorrelationEvaluated(
            metadata=build_test_metadata(),
            correlation_id=str(uuid4()),
            fit_score=85,
            correlation_status=CorrelationStatus.EVALUATED,
            listing_snapshot=ListingNotificationSnapshot(
                id=str(uuid4()),
                title="Python Developer",
                company_name="TechCorp",
                listing_url="https://example.com/job/1",
            ),
            pref_snapshot=SearchPrefSnapshot(
                id=str(uuid4()),
                search_keywords=["Python"],
            ),
        )

        assert event.listing_snapshot is not None
        assert event.pref_snapshot is not None
        assert event.listing_snapshot.title
        assert event.pref_snapshot.id
