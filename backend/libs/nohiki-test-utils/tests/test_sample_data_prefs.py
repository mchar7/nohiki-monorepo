"""Tests for sample_data.prefs module."""

from __future__ import annotations

from uuid import UUID

from nohiki.common.v1 import JobBoardSource, SeniorityLevel, WorkArrangement
from nohiki.user.pref.v1 import SearchPrefSnapshot
from nohiki_test_utils.sample_data.prefs import (
    BACKEND_ENGINEER_PREF,
    DATA_SCIENTIST_PREF,
    DEVOPS_ENGINEER_PREF,
    FRONTEND_DEVELOPER_PREF,
    FULLSTACK_DEVELOPER_PREF,
)

ALL_PREFS = [
    BACKEND_ENGINEER_PREF,
    DATA_SCIENTIST_PREF,
    DEVOPS_ENGINEER_PREF,
    FRONTEND_DEVELOPER_PREF,
    FULLSTACK_DEVELOPER_PREF,
]


class TestAllPrefsAreSearchPrefSnapshots:
    """Verify all prefs are valid SearchPrefSnapshot instances."""

    def test_all_are_search_pref_snapshots(self) -> None:
        """All exported prefs are SearchPrefSnapshot instances."""
        for pref in ALL_PREFS:
            assert isinstance(pref, SearchPrefSnapshot)


class TestPrefIds:
    """Tests for pref ID validity and uniqueness."""

    def test_all_have_valid_uuid_ids(self) -> None:
        """All prefs have valid UUID IDs."""
        for pref in ALL_PREFS:
            UUID(pref.id)

    def test_all_ids_unique(self) -> None:
        """All pref IDs are unique."""
        ids = [p.id for p in ALL_PREFS]
        assert len(ids) == len(set(ids))

    def test_all_have_valid_user_ids(self) -> None:
        """All prefs have valid user UUID IDs."""
        for pref in ALL_PREFS:
            UUID(pref.user_id)


class TestPrefRequiredFields:
    """Tests for required field presence."""

    def test_all_have_pref_names(self) -> None:
        """All prefs have non-empty preference names."""
        for pref in ALL_PREFS:
            assert pref.pref_name
            assert len(pref.pref_name) > 0

    def test_all_have_search_keywords(self) -> None:
        """All prefs have at least one search keyword."""
        for pref in ALL_PREFS:
            assert pref.search_keywords
            assert len(pref.search_keywords) >= 1

    def test_all_have_user_skills(self) -> None:
        """All prefs have at least one user skill."""
        for pref in ALL_PREFS:
            assert pref.user_skills
            assert len(pref.user_skills) >= 1

    def test_all_have_work_arrangements(self) -> None:
        """All prefs have at least one work arrangement."""
        for pref in ALL_PREFS:
            assert pref.work_arrangements
            assert len(pref.work_arrangements) >= 1

    def test_all_have_seniority_levels(self) -> None:
        """All prefs have at least one seniority level."""
        for pref in ALL_PREFS:
            assert pref.experience_preference is not None
            assert pref.experience_preference.seniority_levels
            assert len(pref.experience_preference.seniority_levels) >= 1


class TestPrefWorkArrangements:
    """Tests for work arrangement preferences."""

    def test_all_include_remote_or_hybrid(self) -> None:
        """All prefs include remote or hybrid work arrangements."""
        for pref in ALL_PREFS:
            arrangements = pref.work_arrangements
            assert WorkArrangement.REMOTE in arrangements or WorkArrangement.HYBRID in arrangements

    def test_all_have_remote_locations(self) -> None:
        """All prefs have remote location preferences."""
        for pref in ALL_PREFS:
            assert pref.remote_locations
            assert len(pref.remote_locations) >= 1


class TestPrefSalaryPreferences:
    """Tests for salary preference data."""

    def test_all_have_salary_preferences(self) -> None:
        """All prefs have salary preferences configured."""
        for pref in ALL_PREFS:
            assert pref.salary_preference is not None

    def test_min_salary_less_than_target(self) -> None:
        """Minimum salary is always less than target salary."""
        for pref in ALL_PREFS:
            sal_pref = pref.salary_preference
            assert sal_pref is not None
            assert sal_pref.min_salary is not None
            assert sal_pref.target_salary is not None
            assert sal_pref.min_salary.minor_units < sal_pref.target_salary.minor_units


class TestPrefFeatureImportance:
    """Tests for feature importance configuration."""

    def test_all_have_feature_importance(self) -> None:
        """All prefs have feature importance configured."""
        for pref in ALL_PREFS:
            assert pref.feature_importance is not None

    def test_feature_importance_values_in_range(self) -> None:
        """Feature importance values are between 0 and 100."""
        for pref in ALL_PREFS:
            fi = pref.feature_importance
            assert fi is not None
            assert fi.skill_match_importance is not None
            assert fi.location_importance is not None
            assert fi.work_arrangement_importance is not None
            assert fi.experience_importance is not None
            assert fi.salary_importance is not None
            assert fi.recency_importance is not None
            assert 0 <= fi.skill_match_importance <= 100
            assert 0 <= fi.location_importance <= 100
            assert 0 <= fi.work_arrangement_importance <= 100
            assert 0 <= fi.experience_importance <= 100
            assert 0 <= fi.salary_importance <= 100
            assert 0 <= fi.recency_importance <= 100


class TestPrefNotificationConfig:
    """Tests for notification configuration."""

    def test_all_have_notification_config(self) -> None:
        """All prefs have notification config."""
        for pref in ALL_PREFS:
            assert pref.notification_config is not None

    def test_notification_threshold_in_range(self) -> None:
        """Notification thresholds are between 0 and 100."""
        for pref in ALL_PREFS:
            config = pref.notification_config
            assert config is not None
            assert 0 <= config.threshold <= 100


class TestPrefScrapeSourcesConfig:
    """Tests for scrape sources configuration."""

    def test_all_have_scrape_sources(self) -> None:
        """All prefs have scrape sources configured."""
        for pref in ALL_PREFS:
            assert pref.scrape_sources
            assert len(pref.scrape_sources) >= 1

    def test_scrape_sources_include_major_boards(self) -> None:
        """All prefs include LinkedIn or Indeed."""
        for pref in ALL_PREFS:
            sources = pref.scrape_sources
            assert JobBoardSource.LINKEDIN in sources or JobBoardSource.INDEED in sources


class TestPrefEmbeddings:
    """Tests for embedding data."""

    def test_all_have_user_skills_embedding(self) -> None:
        """All prefs have user skills embeddings."""
        for pref in ALL_PREFS:
            assert pref.user_skills_embedding is not None

    def test_all_have_query_embedding(self) -> None:
        """All prefs have query embeddings."""
        for pref in ALL_PREFS:
            assert pref.query_embedding is not None

    def test_all_have_query_retrieval_embeddings(self) -> None:
        """All prefs have query retrieval embeddings."""
        for pref in ALL_PREFS:
            assert pref.query_retrieval_embeddings
            assert len(pref.query_retrieval_embeddings) > 0


class TestSpecificPrefs:
    """Tests for specific preference personas."""

    def test_backend_engineer_pref_skills(self) -> None:
        """Backend engineer pref has appropriate skills."""
        skills = [s.skill_name for s in BACKEND_ENGINEER_PREF.user_skills]
        assert "Python" in skills
        assert "FastAPI" in skills
        assert "PostgreSQL" in skills

    def test_backend_engineer_pref_keywords(self) -> None:
        """Backend engineer pref has backend-focused keywords."""
        keywords = BACKEND_ENGINEER_PREF.search_keywords
        assert "python" in keywords
        assert "backend" in keywords

    def test_frontend_developer_pref_skills(self) -> None:
        """Frontend developer pref has appropriate skills."""
        skills = [s.skill_name for s in FRONTEND_DEVELOPER_PREF.user_skills]
        assert "React" in skills
        assert "TypeScript" in skills

    def test_data_scientist_pref_seniority(self) -> None:
        """Data scientist pref targets senior/staff levels."""
        exp_pref = DATA_SCIENTIST_PREF.experience_preference
        assert exp_pref is not None
        assert SeniorityLevel.SENIOR in exp_pref.seniority_levels
        assert SeniorityLevel.STAFF in exp_pref.seniority_levels

    def test_devops_engineer_pref_skills(self) -> None:
        """DevOps engineer pref has infrastructure skills."""
        skills = [s.skill_name for s in DEVOPS_ENGINEER_PREF.user_skills]
        assert "Kubernetes" in skills
        assert "Docker" in skills
        assert "Terraform" in skills

    def test_fullstack_developer_open_to_relocation(self) -> None:
        """Fullstack developer is open to relocation."""
        assert FULLSTACK_DEVELOPER_PREF.open_to_relocation is True
