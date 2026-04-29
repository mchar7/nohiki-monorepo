"""Unit tests for user_pref_service.services.enrichment_completion module."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nohiki.ml.v1 import DenseData, EmbeddingType, EmbeddingVector
from nohiki.skill.v1 import JobSkillRequirement, SkillNormalizationResult, SkillProficiencyLevel, SkillProvenance
from nohiki_db_utils.testing import create_mock_session
from user_pref_service.core.embedding import profile_embedding_content_hash
from user_pref_service.services.enrichment_completion import (
    build_user_skills,
    job_requirement_to_user_skill,
    load_user_skills_from_profile,
    persist_query_enrichment,
    persist_skill_enrichment,
)


def _make_dense_vector(values: list[float], version: str = "v1") -> EmbeddingVector:
    """Build a DENSE EmbeddingVector for tests."""
    return EmbeddingVector(
        embedding_type=EmbeddingType.DENSE,
        dense=DenseData(values=values),
        collection_version=version,
    )


def _make_embedding_result(
    dense_values: list[float],
    *,
    collection_version: str = "v1",
    extra_vectors: list[EmbeddingVector] | None = None,
) -> MagicMock:
    """Build a mock EmbeddingResult with real EmbeddingVector objects."""
    dense_vec = _make_dense_vector(dense_values, collection_version)
    all_vectors = [dense_vec, *(extra_vectors or [])]
    result = MagicMock()
    result.embeddings = all_vectors
    result.collection_version = collection_version
    return result


def _make_normalization_result(
    skill_names: list[str],
    *,
    collection_version: str = "v1",
) -> SkillNormalizationResult:
    """Build a real SkillNormalizationResult with proper proto objects."""
    reqs = [
        JobSkillRequirement(
            skill_id=f"skill-{i}",
            skill_name=name,
            proficiency_level=SkillProficiencyLevel.INTERMEDIATE,
            extraction_confidence=0.9,
        )
        for i, name in enumerate(skill_names)
    ]
    skills_embedding = _make_dense_vector([0.1, 0.2, 0.3])
    return SkillNormalizationResult(
        canonical_skill_ids=[f"skill-{i}" for i in range(len(skill_names))],
        skill_requirements=reqs,
        skills_embedding=skills_embedding,
        collection_version=collection_version,
    )


class TestJobRequirementToUserSkill:
    """Tests for job_requirement_to_user_skill mapping function."""

    def test_maps_all_fields(self) -> None:
        """All JobSkillRequirement fields are correctly mapped."""
        req = JobSkillRequirement(
            skill_id="skill-123",
            skill_name="Python",
            proficiency_level=SkillProficiencyLevel.ADVANCED,
            extraction_confidence=0.95,
        )

        result = job_requirement_to_user_skill(req)

        assert result.skill_id == "skill-123"
        assert result.skill_name == "Python"
        assert result.proficiency == SkillProficiencyLevel.ADVANCED
        assert result.provenance == SkillProvenance.USER_DECLARED
        assert result.provenance_confidence == pytest.approx(0.95)

    def test_handles_empty_fields(self) -> None:
        """Handles JobSkillRequirement with empty/default fields."""
        req = JobSkillRequirement()

        result = job_requirement_to_user_skill(req)

        assert result.skill_id == ""
        assert result.skill_name == ""
        assert result.provenance == SkillProvenance.USER_DECLARED


class TestBuildUserSkills:
    """Tests for build_user_skills helper."""

    def test_builds_from_normalization_result(self) -> None:
        """Converts all skill_requirements to UserSkillEntry in a single pass."""
        norm_result = _make_normalization_result(["Python", "Go"])
        skills = build_user_skills(norm_result)

        assert len(skills) == 2
        assert skills[0].skill_name == "Python"
        assert skills[1].skill_name == "Go"

    def test_empty_requirements_returns_empty_list(self) -> None:
        """Returns empty list when normalization result has no skill requirements."""
        norm_result = SkillNormalizationResult()
        assert build_user_skills(norm_result) == []


class TestLoadUserSkillsFromProfile:
    """Tests for load_user_skills_from_profile."""

    def test_returns_empty_list_when_no_data(self) -> None:
        """Returns empty list when profile has no user_skills_data."""
        profile = MagicMock()
        profile.user_skills_data = None
        assert load_user_skills_from_profile(profile) == []

    def test_deserializes_stored_skill_dicts(self) -> None:
        """Deserializes UserSkillEntry dicts from profile.user_skills_data."""
        req = JobSkillRequirement(
            skill_id="s1",
            skill_name="Rust",
            proficiency_level=SkillProficiencyLevel.INTERMEDIATE,
        )
        entry = job_requirement_to_user_skill(req)
        profile = MagicMock()
        profile.user_skills_data = [entry.to_dict()]

        loaded = load_user_skills_from_profile(profile)

        assert len(loaded) == 1
        assert loaded[0].skill_name == "Rust"


class TestPersistSkillEnrichment:
    """Tests for persist_skill_enrichment service function."""

    @pytest.mark.asyncio
    async def test_persists_embedding_vector_skill_ids_and_user_skills_data(self) -> None:
        """Persists skills embedding vector, canonical skill IDs, and full UserSkillEntry data."""
        profile_id = uuid.uuid4()
        mock_profile = MagicMock()
        mock_db = create_mock_session()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

        norm_result = _make_normalization_result(["Python", "Go"])

        with patch(
            "user_pref_service.services.enrichment_completion.profile_service.get_profile_by_id",
            new_callable=AsyncMock,
            return_value=mock_profile,
        ):
            result = await persist_skill_enrichment(mock_db, profile_id, norm_result)

        assert mock_profile.user_skills_embedding == [0.1, 0.2, 0.3]
        assert mock_profile.collection_version == "v1"
        assert mock_profile.user_skill_ids == ["skill-0", "skill-1"]
        assert isinstance(mock_profile.user_skills_data, list)
        assert len(mock_profile.user_skills_data) == 2
        mock_db.flush.assert_awaited_once()
        mock_db.refresh.assert_awaited_once_with(mock_profile)
        assert result is mock_profile

    @pytest.mark.asyncio
    async def test_skips_embedding_when_no_dense_data(self) -> None:
        """Skips setting user_skills_embedding when skills_embedding has no dense arm."""
        profile_id = uuid.uuid4()
        mock_profile = MagicMock()
        mock_profile.user_skills_embedding = [0.5]
        mock_db = create_mock_session()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

        norm_result = SkillNormalizationResult(
            canonical_skill_ids=[],
            skill_requirements=[],
            skills_embedding=EmbeddingVector(embedding_type=EmbeddingType.DENSE),
            collection_version="v1",
        )

        with patch(
            "user_pref_service.services.enrichment_completion.profile_service.get_profile_by_id",
            new_callable=AsyncMock,
            return_value=mock_profile,
        ):
            await persist_skill_enrichment(mock_db, profile_id, norm_result)

        assert mock_profile.user_skills_embedding == [0.5]

    @pytest.mark.asyncio
    async def test_persists_empty_skills_when_no_requirements(self) -> None:
        """Persists empty user_skills_data and user_skill_ids for no-skill profiles."""
        profile_id = uuid.uuid4()
        mock_profile = MagicMock()
        mock_db = create_mock_session()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

        norm_result = SkillNormalizationResult(
            canonical_skill_ids=[],
            skill_requirements=[],
        )

        with patch(
            "user_pref_service.services.enrichment_completion.profile_service.get_profile_by_id",
            new_callable=AsyncMock,
            return_value=mock_profile,
        ):
            await persist_skill_enrichment(mock_db, profile_id, norm_result)

        assert mock_profile.user_skill_ids == []
        assert mock_profile.user_skills_data == []

    @pytest.mark.asyncio
    async def test_does_not_set_embedding_when_skills_embedding_is_none(self) -> None:
        """user_skills_embedding stays None when normalization returns no aggregated embedding."""
        profile_id = uuid.uuid4()
        mock_profile = MagicMock()
        mock_profile.user_skills_embedding = None
        mock_db = create_mock_session()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

        norm_result = SkillNormalizationResult(
            canonical_skill_ids=[],
            skill_requirements=[],
            # skills_embedding defaults to None (no canonical skills to aggregate)
        )

        with patch(
            "user_pref_service.services.enrichment_completion.profile_service.get_profile_by_id",
            new_callable=AsyncMock,
            return_value=mock_profile,
        ):
            await persist_skill_enrichment(mock_db, profile_id, norm_result)

        assert mock_profile.user_skills_embedding is None


class TestPersistQueryEnrichment:
    """Tests for persist_query_enrichment service function."""

    @pytest.mark.asyncio
    async def test_persists_dense_and_retrieval_vectors_in_single_pass(self) -> None:
        """Partitions in one pass: DENSE → query_embedding, non-DENSE → query_artifacts_data."""
        pref_id = uuid.uuid4()
        mock_profile = MagicMock()
        mock_db = create_mock_session()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

        muvera_vec = EmbeddingVector(
            embedding_type=EmbeddingType.MUVERA,
            dense=DenseData(values=[1.0] * 8192),
            collection_version="v1",
        )
        mock_result = _make_embedding_result(
            [0.4, 0.5, 0.6],
            collection_version="v2",
            extra_vectors=[muvera_vec],
        )

        with patch(
            "user_pref_service.services.enrichment_completion.profile_service.get_profile_by_id",
            new_callable=AsyncMock,
            return_value=mock_profile,
        ):
            result = await persist_query_enrichment(mock_db, pref_id, mock_result)

        assert mock_profile.query_embedding == [0.4, 0.5, 0.6]
        assert mock_profile.collection_version == "v2"
        assert mock_profile.query_artifacts_data == [muvera_vec.to_dict()]
        assert result is mock_profile

    @pytest.mark.asyncio
    async def test_skips_query_embedding_when_no_dense_vector(self) -> None:
        """Does not overwrite query_embedding when result has no DENSE vector."""
        pref_id = uuid.uuid4()
        mock_profile = MagicMock()
        mock_profile.query_embedding = [0.7, 0.8]
        mock_db = create_mock_session()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

        mock_result = MagicMock()
        mock_result.embeddings = []
        mock_result.collection_version = "v1"

        with patch(
            "user_pref_service.services.enrichment_completion.profile_service.get_profile_by_id",
            new_callable=AsyncMock,
            return_value=mock_profile,
        ):
            await persist_query_enrichment(mock_db, pref_id, mock_result)

        assert mock_profile.query_embedding == [0.7, 0.8]

    @pytest.mark.asyncio
    async def test_older_generation_cannot_overwrite_newer_query_embedding(self) -> None:
        """Expected-generation mismatch returns no profile and performs no write."""
        pref_id = uuid.uuid4()
        mock_profile = MagicMock(semantic_content_generation=2, query_embedding=[0.9])
        mock_db = create_mock_session()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()
        result = _make_embedding_result([0.1, 0.2])

        with patch(
            "user_pref_service.services.enrichment_completion.profile_service.get_profile_by_id_for_update",
            new_callable=AsyncMock,
            return_value=mock_profile,
        ) as get_profile:
            persisted = await persist_query_enrichment(mock_db, pref_id, result, expected_generation=1)

        assert persisted is None
        assert mock_profile.query_embedding == [0.9]
        mock_db.flush.assert_not_awaited()
        get_profile.assert_awaited_once_with(mock_db, pref_id)

    @pytest.mark.asyncio
    async def test_legacy_callback_hash_mismatch_returns_without_mutating_profile(self) -> None:
        """A legacy text hash is checked against persisted semantic fields before writing."""
        pref_id = uuid.uuid4()
        mock_profile = MagicMock(
            semantic_content_generation=0,
            semantic_content_hash=None,
            pref_name="Current Profile",
            search_keywords=["Python"],
            user_skills_data=None,
            query_embedding=[0.9],
        )
        mock_db = create_mock_session()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()
        result = _make_embedding_result([0.1, 0.2])

        with patch(
            "user_pref_service.services.enrichment_completion.profile_service.get_profile_by_id_for_update",
            new_callable=AsyncMock,
            return_value=mock_profile,
        ):
            persisted = await persist_query_enrichment(
                mock_db,
                pref_id,
                result,
                expected_hash=profile_embedding_content_hash("Old Profile Python"),
            )

        assert persisted is None
        assert mock_profile.query_embedding == [0.9]
        mock_db.flush.assert_not_awaited()
