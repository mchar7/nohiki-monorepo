"""Tests for sample_data builder functions.

Tests build_listing_snapshot, build_search_pref_snapshot, and to_discovered_listing.
"""

from __future__ import annotations

from nohiki.common.v1 import (
    JobBoardSource,
    NotificationFrequency,
    PaymentFrequency,
    SeniorityLevel,
    WorkArrangement,
)
from nohiki.job.ingest.v1 import DiscoveredListing
from nohiki.job.listing.v1 import ListingSnapshot
from nohiki.ml.v1 import EmbeddingType
from nohiki.user.pref.v1 import SearchPrefSnapshot
from nohiki_test_utils.sample_data._common import (
    COLLECTION_VERSION,
    DEFAULT_AUTO_TAILOR_THRESHOLD,
    DEFAULT_MIN_FIT_SCORE_DISQUALIFY,
    SAMPLE_DATA_MODEL_ID,
    build_listing_snapshot,
    build_search_pref_snapshot,
    make_compensation_range,
    make_location,
    make_remote_location,
    to_discovered_listing,
)
from nohiki_test_utils.sample_data._ids import FIXED_TIMESTAMP
from nohiki_test_utils.sample_data._types import ListingPersonaSpec, PrefPersonaSpec


class TestBuildListingSnapshot:
    """Tests for build_listing_snapshot function."""

    def test_builds_complete_snapshot(self) -> None:
        """Build listing snapshot with all required fields."""
        spec = ListingPersonaSpec(
            entity_id="test-listing-id",
            listing_url="https://example.com/job",
            source=JobBoardSource.LINKEDIN,
            title="Software Engineer",
            company_name="Tech Corp",
            description="Build amazing software",
            location_raw="San Francisco, CA",
            location=make_location("San Francisco", "CA"),
            work_arrangement=WorkArrangement.HYBRID,
            seniority_level=SeniorityLevel.MID,
            required_skills=["Python", "FastAPI"],
            experience_years_min=3,
            experience_years_max=5,
            compensation=make_compensation_range(12000000, 18000000),
            version=1,
        )
        snapshot = build_listing_snapshot(spec)
        assert isinstance(snapshot, ListingSnapshot)
        assert snapshot.id == "test-listing-id"
        assert snapshot.title == "Software Engineer"
        assert snapshot.company_name == "Tech Corp"
        assert snapshot.work_arrangement == WorkArrangement.HYBRID
        assert len(snapshot.required_skills) == 2

    def test_snapshot_has_embeddings(self) -> None:
        """Snapshot includes all required embeddings."""
        spec = ListingPersonaSpec(
            entity_id="test-id",
            listing_url="https://example.com/job",
            source=JobBoardSource.INDEED,
            title="Test Job",
            company_name="Test Co",
            description="Test description",
            location_raw="NYC",
            location=make_location("New York", "NY"),
            work_arrangement=WorkArrangement.ON_SITE,
            seniority_level=SeniorityLevel.SENIOR,
            required_skills=["Skill1"],
            experience_years_min=5,
            experience_years_max=10,
            compensation=make_compensation_range(15000000, 20000000),
            version=1,
        )
        snapshot = build_listing_snapshot(spec)
        assert snapshot.skills_embedding is not None
        assert snapshot.skills_embedding.model_id == SAMPLE_DATA_MODEL_ID
        assert snapshot.title_embedding is not None
        assert snapshot.title_embedding.model_id == SAMPLE_DATA_MODEL_ID
        assert snapshot.retrieval_embeddings
        assert len(snapshot.retrieval_embeddings) == 1
        assert snapshot.retrieval_embeddings[0].embedding_type == EmbeddingType.MUVERA

    def test_snapshot_has_skill_requirements(self) -> None:
        """Snapshot includes generated skill requirements."""
        spec = ListingPersonaSpec(
            entity_id="test-id",
            listing_url="https://example.com/job",
            source=JobBoardSource.LINKEDIN,
            title="Test Job",
            company_name="Test Co",
            description="Test description",
            location_raw="Boston, MA",
            location=make_location("Boston", "MA"),
            work_arrangement=WorkArrangement.REMOTE,
            seniority_level=SeniorityLevel.STAFF,
            required_skills=["Python", "Kafka", "PostgreSQL"],
            experience_years_min=7,
            experience_years_max=12,
            compensation=make_compensation_range(18000000, 25000000),
            version=1,
        )
        snapshot = build_listing_snapshot(spec)
        assert len(snapshot.skill_requirements) == 3
        assert snapshot.skill_requirements[0].skill_name == "Python"
        assert snapshot.skill_requirements[1].skill_name == "Kafka"

    def test_snapshot_timestamps(self) -> None:
        """Snapshot uses FIXED_TIMESTAMP for all time fields."""
        spec = ListingPersonaSpec(
            entity_id="test-id",
            listing_url="https://example.com/job",
            source=JobBoardSource.INDEED,
            title="Test Job",
            company_name="Test Co",
            description="Test description",
            location_raw="Seattle, WA",
            location=make_location("Seattle", "WA"),
            work_arrangement=WorkArrangement.HYBRID,
            seniority_level=SeniorityLevel.ENTRY,
            required_skills=["JavaScript"],
            experience_years_min=0,
            experience_years_max=2,
            compensation=make_compensation_range(8000000, 12000000),
            version=1,
        )
        snapshot = build_listing_snapshot(spec)
        assert snapshot.posted_at == FIXED_TIMESTAMP
        assert snapshot.discovered_at == FIXED_TIMESTAMP
        assert snapshot.processed_at == FIXED_TIMESTAMP
        assert snapshot.created_at == FIXED_TIMESTAMP
        assert snapshot.updated_at == FIXED_TIMESTAMP

    def test_snapshot_collection_version(self) -> None:
        """Snapshot uses correct collection version."""
        spec = ListingPersonaSpec(
            entity_id="test-id",
            listing_url="https://example.com/job",
            source=JobBoardSource.LINKEDIN,
            title="Test Job",
            company_name="Test Co",
            description="Test description",
            location_raw="Austin, TX",
            location=make_location("Austin", "TX"),
            work_arrangement=WorkArrangement.ON_SITE,
            seniority_level=SeniorityLevel.MID,
            required_skills=["Go"],
            experience_years_min=3,
            experience_years_max=6,
            compensation=make_compensation_range(13000000, 17000000),
            version=1,
        )
        snapshot = build_listing_snapshot(spec)
        assert snapshot.collection_version == COLLECTION_VERSION


class TestBuildSearchPrefSnapshot:
    """Tests for build_search_pref_snapshot function."""

    def test_builds_complete_pref_snapshot(self) -> None:
        """Build preference snapshot with all required fields."""
        spec = PrefPersonaSpec(
            entity_id="pref-id",
            user_id="user-id",
            pref_name="Software Engineering Jobs",
            search_keywords=["python", "backend"],
            disallowed_keywords=["frontend"],
            physical_locations=[make_location("San Francisco", "CA")],
            remote_locations=[make_remote_location()],
            work_arrangements=[WorkArrangement.REMOTE, WorkArrangement.HYBRID],
            open_to_relocation=False,
            experience_years=5,
            seniority_levels=[SeniorityLevel.MID, SeniorityLevel.SENIOR],
            min_salary_minor_units=12000000,
            target_salary_minor_units=15000000,
            user_skill_names=["Python", "FastAPI", "PostgreSQL"],
        )
        snapshot = build_search_pref_snapshot(spec)
        assert isinstance(snapshot, SearchPrefSnapshot)
        assert snapshot.id == "pref-id"
        assert snapshot.user_id == "user-id"
        assert snapshot.pref_name == "Software Engineering Jobs"
        assert len(snapshot.search_keywords) == 2
        assert len(snapshot.user_skills) == 3

    def test_pref_snapshot_has_embeddings(self) -> None:
        """Preference snapshot includes all embeddings."""
        spec = PrefPersonaSpec(
            entity_id="pref-id",
            user_id="user-id",
            pref_name="Test Pref",
            search_keywords=["test"],
            disallowed_keywords=[],
            physical_locations=[],
            remote_locations=[make_remote_location()],
            work_arrangements=[WorkArrangement.REMOTE],
            open_to_relocation=True,
            experience_years=3,
            seniority_levels=[SeniorityLevel.MID],
            min_salary_minor_units=10000000,
            target_salary_minor_units=12000000,
            user_skill_names=["Skill1"],
        )
        snapshot = build_search_pref_snapshot(spec)
        assert snapshot.user_skills_embedding is not None
        assert snapshot.query_embedding is not None
        assert snapshot.query_retrieval_embeddings
        assert len(snapshot.query_retrieval_embeddings) == 1

    def test_pref_snapshot_feature_importance(self) -> None:
        """Preference snapshot has feature importance configured."""
        spec = PrefPersonaSpec(
            entity_id="pref-id",
            user_id="user-id",
            pref_name="Test Pref",
            search_keywords=["test"],
            disallowed_keywords=[],
            physical_locations=[],
            remote_locations=[make_remote_location()],
            work_arrangements=[WorkArrangement.REMOTE],
            open_to_relocation=False,
            experience_years=5,
            seniority_levels=[SeniorityLevel.SENIOR],
            min_salary_minor_units=15000000,
            target_salary_minor_units=18000000,
            user_skill_names=["Python"],
        )
        snapshot = build_search_pref_snapshot(spec)
        assert snapshot.feature_importance is not None
        assert snapshot.feature_importance.skill_match_importance is not None
        assert snapshot.feature_importance.location_importance is not None
        assert snapshot.feature_importance.skill_match_importance > 0
        assert snapshot.feature_importance.location_importance > 0

    def test_pref_snapshot_salary_preference(self) -> None:
        """Preference snapshot has salary preference configured."""
        spec = PrefPersonaSpec(
            entity_id="pref-id",
            user_id="user-id",
            pref_name="Test Pref",
            search_keywords=["test"],
            disallowed_keywords=[],
            physical_locations=[],
            remote_locations=[make_remote_location()],
            work_arrangements=[WorkArrangement.REMOTE],
            open_to_relocation=False,
            experience_years=5,
            seniority_levels=[SeniorityLevel.SENIOR],
            min_salary_minor_units=15000000,
            target_salary_minor_units=20000000,
            user_skill_names=["Python"],
        )
        snapshot = build_search_pref_snapshot(spec)
        assert snapshot.salary_preference is not None
        assert snapshot.salary_preference.min_salary is not None
        assert snapshot.salary_preference.target_salary is not None
        assert snapshot.salary_preference.min_salary.minor_units == 15000000
        assert snapshot.salary_preference.target_salary.minor_units == 20000000
        assert snapshot.salary_preference.preferred_frequency == PaymentFrequency.ANNUALLY

    def test_pref_snapshot_notification_config(self) -> None:
        """Preference snapshot has notification config."""
        spec = PrefPersonaSpec(
            entity_id="pref-id",
            user_id="user-id",
            pref_name="Test Pref",
            search_keywords=["test"],
            disallowed_keywords=[],
            physical_locations=[],
            remote_locations=[make_remote_location()],
            work_arrangements=[WorkArrangement.REMOTE],
            open_to_relocation=False,
            experience_years=3,
            seniority_levels=[SeniorityLevel.MID],
            min_salary_minor_units=10000000,
            target_salary_minor_units=12000000,
            user_skill_names=["Python"],
        )
        snapshot = build_search_pref_snapshot(spec)
        assert snapshot.notification_config is not None
        assert snapshot.notification_config.frequency == NotificationFrequency.DAILY

    def test_pref_snapshot_thresholds(self) -> None:
        """Preference snapshot has correct threshold values."""
        spec = PrefPersonaSpec(
            entity_id="pref-id",
            user_id="user-id",
            pref_name="Test Pref",
            search_keywords=["test"],
            disallowed_keywords=[],
            physical_locations=[],
            remote_locations=[make_remote_location()],
            work_arrangements=[WorkArrangement.REMOTE],
            open_to_relocation=False,
            experience_years=5,
            seniority_levels=[SeniorityLevel.SENIOR],
            min_salary_minor_units=15000000,
            target_salary_minor_units=18000000,
            user_skill_names=["Python"],
        )
        snapshot = build_search_pref_snapshot(spec)
        assert snapshot.min_fit_score_disqualify == DEFAULT_MIN_FIT_SCORE_DISQUALIFY
        assert snapshot.auto_tailor_threshold == DEFAULT_AUTO_TAILOR_THRESHOLD

    def test_pref_snapshot_scrape_sources(self) -> None:
        """Preference snapshot has scrape sources configured."""
        spec = PrefPersonaSpec(
            entity_id="pref-id",
            user_id="user-id",
            pref_name="Test Pref",
            search_keywords=["test"],
            disallowed_keywords=[],
            physical_locations=[],
            remote_locations=[make_remote_location()],
            work_arrangements=[WorkArrangement.REMOTE],
            open_to_relocation=False,
            experience_years=3,
            seniority_levels=[SeniorityLevel.MID],
            min_salary_minor_units=10000000,
            target_salary_minor_units=12000000,
            user_skill_names=["Python"],
        )
        snapshot = build_search_pref_snapshot(spec)
        assert JobBoardSource.LINKEDIN in snapshot.scrape_sources
        assert JobBoardSource.INDEED in snapshot.scrape_sources


class TestToDiscoveredListing:
    """Tests for to_discovered_listing function."""

    def test_converts_snapshot_to_discovered_listing(self) -> None:
        """Convert listing snapshot to discovered listing format."""
        spec = ListingPersonaSpec(
            entity_id="listing-id",
            listing_url="https://example.com/job",
            source=JobBoardSource.LINKEDIN,
            title="Software Engineer",
            company_name="Tech Corp",
            description="Build software",
            location_raw="San Francisco, CA",
            location=make_location("San Francisco", "CA"),
            work_arrangement=WorkArrangement.HYBRID,
            seniority_level=SeniorityLevel.MID,
            required_skills=["Python"],
            experience_years_min=3,
            experience_years_max=5,
            compensation=make_compensation_range(12000000, 18000000),
            version=1,
        )
        snapshot = build_listing_snapshot(spec)
        discovered = to_discovered_listing(snapshot)
        assert isinstance(discovered, DiscoveredListing)
        assert discovered.listing_url == snapshot.listing_url
        assert discovered.source == snapshot.source
        assert discovered.title == snapshot.title
        assert discovered.company_name == snapshot.company_name

    def test_discovered_listing_uses_snapshot_id_as_external_id(self) -> None:
        """Discovered listing uses snapshot ID as external_id by default."""
        spec = ListingPersonaSpec(
            entity_id="listing-id",
            listing_url="https://example.com/job",
            source=JobBoardSource.INDEED,
            title="Test Job",
            company_name="Test Co",
            description="Test description",
            location_raw="NYC",
            location=make_location("New York", "NY"),
            work_arrangement=WorkArrangement.ON_SITE,
            seniority_level=SeniorityLevel.SENIOR,
            required_skills=["Skill1"],
            experience_years_min=5,
            experience_years_max=10,
            compensation=make_compensation_range(15000000, 20000000),
            version=1,
        )
        snapshot = build_listing_snapshot(spec)
        discovered = to_discovered_listing(snapshot)
        assert discovered.external_id == snapshot.id

    def test_discovered_listing_custom_external_id(self) -> None:
        """Discovered listing respects custom external_id."""
        spec = ListingPersonaSpec(
            entity_id="listing-id",
            listing_url="https://example.com/job",
            source=JobBoardSource.LINKEDIN,
            title="Test Job",
            company_name="Test Co",
            description="Test description",
            location_raw="Boston, MA",
            location=make_location("Boston", "MA"),
            work_arrangement=WorkArrangement.REMOTE,
            seniority_level=SeniorityLevel.STAFF,
            required_skills=["Python"],
            experience_years_min=7,
            experience_years_max=12,
            compensation=make_compensation_range(18000000, 25000000),
            version=1,
        )
        snapshot = build_listing_snapshot(spec)
        discovered = to_discovered_listing(snapshot, external_id="custom-external-id")
        assert discovered.external_id == "custom-external-id"

    def test_discovered_listing_has_raw_skills(self) -> None:
        """Discovered listing includes raw skills list."""
        spec = ListingPersonaSpec(
            entity_id="listing-id",
            listing_url="https://example.com/job",
            source=JobBoardSource.INDEED,
            title="Test Job",
            company_name="Test Co",
            description="Test description",
            location_raw="Seattle, WA",
            location=make_location("Seattle", "WA"),
            work_arrangement=WorkArrangement.HYBRID,
            seniority_level=SeniorityLevel.ENTRY,
            required_skills=["JavaScript", "React", "TypeScript"],
            experience_years_min=0,
            experience_years_max=2,
            compensation=make_compensation_range(8000000, 12000000),
            version=1,
        )
        snapshot = build_listing_snapshot(spec)
        discovered = to_discovered_listing(snapshot)
        assert len(discovered.raw_skills) == 3
        assert "JavaScript" in discovered.raw_skills
        assert "React" in discovered.raw_skills

    def test_discovered_listing_timestamps(self) -> None:
        """Discovered listing has correct timestamps."""
        spec = ListingPersonaSpec(
            entity_id="listing-id",
            listing_url="https://example.com/job",
            source=JobBoardSource.LINKEDIN,
            title="Test Job",
            company_name="Test Co",
            description="Test description",
            location_raw="Austin, TX",
            location=make_location("Austin", "TX"),
            work_arrangement=WorkArrangement.ON_SITE,
            seniority_level=SeniorityLevel.MID,
            required_skills=["Go"],
            experience_years_min=3,
            experience_years_max=6,
            compensation=make_compensation_range(13000000, 17000000),
            version=1,
        )
        snapshot = build_listing_snapshot(spec)
        discovered = to_discovered_listing(snapshot)
        assert discovered.discovered_timestamp == snapshot.discovered_at
        assert discovered.posted_timestamp == snapshot.posted_at
