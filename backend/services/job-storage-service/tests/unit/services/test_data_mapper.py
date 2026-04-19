"""Unit tests for data_mapper.py module."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from job_storage_service.services.data_mapper import JobDataMapper, compute_dedup_hash


class TestComputeDedupHash:
    """Tests for compute_dedup_hash function."""

    def test_computes_hash_with_posted_at(self) -> None:
        """Test computing hash with valid posted_at date."""
        posted_at = datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC)

        result = compute_dedup_hash("Senior Python Developer", "Acme Corp", posted_at)

        assert isinstance(result, str)
        assert len(result) == 64  # SHA256 hex length

    def test_computes_hash_without_posted_at(self) -> None:
        """Test computing hash when posted_at is None."""
        result = compute_dedup_hash("Software Engineer", "Tech Inc", None)

        assert isinstance(result, str)
        assert len(result) == 64

    def test_normalizes_title_and_company(self) -> None:
        """Test hash is case-insensitive and strips whitespace."""
        posted_at = datetime(2025, 1, 15, tzinfo=UTC)

        hash1 = compute_dedup_hash("Senior Developer", "Acme Corp", posted_at)
        hash2 = compute_dedup_hash("  SENIOR DEVELOPER  ", "  ACME CORP  ", posted_at)

        assert hash1 == hash2

    def test_different_inputs_produce_different_hashes(self) -> None:
        """Test different inputs produce different hashes."""
        posted_at = datetime(2025, 1, 15, tzinfo=UTC)

        hash1 = compute_dedup_hash("Developer", "Acme", posted_at)
        hash2 = compute_dedup_hash("Engineer", "Acme", posted_at)

        assert hash1 != hash2


class TestJobDataMapper:
    """Tests for JobDataMapper class (post-enrichment mapping only)."""

    @pytest.fixture
    def mapper(self) -> JobDataMapper:
        """Create a JobDataMapper instance."""
        return JobDataMapper()

    def test_from_stored_maps_enriched_fields(self, mapper: JobDataMapper) -> None:
        """Test mapping StoredListing with enriched fields."""
        stored = MagicMock()
        stored.title = "Senior Python Developer"
        stored.company_name = "Tech Corp"
        stored.description = "Full job description"
        stored.work_arrangement = "REMOTE"
        stored.employment_term = "FULL_TIME"
        stored.seniority_level = "SENIOR"
        stored.language = "en"
        stored.content_hash = "xyz789"
        stored.posted_timestamp = datetime(2025, 1, 10, tzinfo=UTC)
        stored.discovered_timestamp = datetime(2025, 1, 15, tzinfo=UTC)

        stored.location = MagicMock()
        stored.location.to_dict.return_value = {"city": "NYC", "country": "USA"}

        stored.compensation = MagicMock()
        stored.compensation.to_dict.return_value = {"min": 100000, "max": 150000}

        skill1 = MagicMock()
        skill1.skill_name = "Python"
        skill1.skill_id = "skill-id-1"
        skill2 = MagicMock()
        skill2.skill_name = "React"
        skill2.skill_id = "skill-id-2"
        stored.skill_requirements = [skill1, skill2]

        stored.experience = MagicMock()
        stored.experience.min_years = MagicMock()
        stored.experience.min_years.years = 3
        stored.experience.max_years = MagicMock()
        stored.experience.max_years.years = 5

        stored.skills_embedding = MagicMock()
        stored.skills_embedding.dense = MagicMock()
        stored.skills_embedding.dense.values = [0.1, 0.2, 0.3]
        stored.title_embedding = MagicMock()
        stored.title_embedding.dense = MagicMock()
        stored.title_embedding.dense.values = [0.4, 0.5, 0.6]

        result = mapper.from_stored(stored, correlation_id="corr-789", collection_version="v1")

        assert result["title"] == "Senior Python Developer"
        assert result["company_name"] == "Tech Corp"
        assert result["work_arrangement"] == "REMOTE"
        assert result["employment_term"] == "FULL_TIME"
        assert result["seniority_level"] == "SENIOR"
        assert result["location"] == {"city": "NYC", "country": "USA"}
        assert result["compensation"] == {"min": 100000, "max": 150000}
        assert result["required_skills"] == ["Python", "React"]
        assert result["canonical_skill_ids"] == ["skill-id-1", "skill-id-2"]
        assert result["min_experience_years"] == 3
        assert result["max_experience_years"] == 5
        assert result["skills_embedding"] == [0.1, 0.2, 0.3]
        assert result["title_embedding"] == [0.4, 0.5, 0.6]
        assert result["collection_version"] == "v1"
        assert result["processing_correlation_id"] == "corr-789"
        assert result["language"] == "en"

    def test_from_stored_handles_none_optional_fields(self, mapper: JobDataMapper) -> None:
        """Test mapping StoredListing with None optional fields (non-embedding)."""
        stored = MagicMock()
        stored.title = "Developer"
        stored.company_name = None
        stored.description = None
        stored.work_arrangement = None
        stored.employment_term = None
        stored.seniority_level = None
        stored.language = "fr-CA"
        stored.content_hash = "abc"
        stored.posted_timestamp = None
        stored.discovered_timestamp = datetime(2025, 1, 15, tzinfo=UTC)
        stored.location = None
        stored.compensation = None
        stored.skill_requirements = []
        stored.experience = None
        stored.skills_embedding = MagicMock()
        stored.skills_embedding.dense = MagicMock(values=[0.1, 0.2])
        stored.title_embedding = MagicMock()
        stored.title_embedding.dense = MagicMock(values=[0.3, 0.4])

        result = mapper.from_stored(stored, correlation_id="corr", collection_version="v1")

        assert result["company_name"] == ""
        assert result["description"] is None
        assert result["location"] is None
        assert result["compensation"] is None
        assert result["required_skills"] == []
        assert result["min_experience_years"] is None
        assert result["max_experience_years"] is None
        assert result["skills_embedding"] == [0.1, 0.2]
        assert result["title_embedding"] == [0.3, 0.4]
        assert result["language"] == "fr-CA"


class TestLanguageInFromStored:
    """Table-driven tests verifying language flows correctly through from_stored."""

    @pytest.fixture
    def mapper(self) -> JobDataMapper:
        """Create a JobDataMapper instance."""
        return JobDataMapper()

    def _make_stored_mock(self, language: str) -> MagicMock:
        """Build minimal StoredListing mock with specified language."""
        stored = MagicMock()
        stored.title = "Engineer"
        stored.company_name = "Corp"
        stored.description = None
        stored.work_arrangement = "HYBRID"
        stored.employment_term = "FULL_TIME"
        stored.seniority_level = "MID"
        stored.language = language
        stored.content_hash = "hash"
        stored.posted_timestamp = None
        stored.discovered_timestamp = datetime(2025, 1, 15, tzinfo=UTC)
        stored.location = None
        stored.compensation = None
        stored.skill_requirements = []
        stored.experience = None
        stored.skills_embedding = MagicMock()
        stored.skills_embedding.dense = MagicMock(values=[0.1])
        stored.title_embedding = MagicMock()
        stored.title_embedding.dense = MagicMock(values=[0.2])
        return stored

    @pytest.mark.parametrize("language", ["en", "fr", "de", "fr-CA", "zh-CN", "pt-BR"])
    def test_bcp47_tags_pass_through(self, mapper: JobDataMapper, language: str) -> None:
        """BCP 47 language tags are stored verbatim from the proto."""
        result = mapper.from_stored(self._make_stored_mock(language), correlation_id="corr", collection_version="v1")
        assert result["language"] == language
