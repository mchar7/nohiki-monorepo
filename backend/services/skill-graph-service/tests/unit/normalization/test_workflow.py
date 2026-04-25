"""Unit tests for normalization workflow orchestration."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nohiki.ml.v1 import (
    DenseData,
    EmbeddingType,
    EmbeddingVector,
)
from nohiki.skill.v1 import MatchConfidence, SkillMatchType, SkillProficiencyLevel
from nohiki_db_utils.testing import create_mock_session
from skill_graph_service.db.models import SkillNode
from skill_graph_service.services.embedding_service import EmbeddingVariant, skill_variant_point_id
from skill_graph_service.services.normalization.models import (
    DeterministicMatchResult,
    SkillNormalizationResult,
)
from skill_graph_service.services.normalization.ports import SkillSearchMatch
from skill_graph_service.services.normalization.workflow import (
    assemble_batch_normalization_result,
    resolve_canonical_skill_ids,
    run_deterministic_matching,
    run_semantic_qdrant_search,
)


class TestRunDeterministicMatching:
    """Tests for run_deterministic_matching orchestration."""

    @pytest.fixture
    def mock_session_factory(self) -> MagicMock:
        """Create mock async session factory."""
        session = create_mock_session()
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=session)
        ctx.__aexit__ = AsyncMock(return_value=False)
        return MagicMock(return_value=ctx)

    @pytest.mark.asyncio
    async def test_empty_skills_returns_all_matched(self, mock_session_factory: MagicMock) -> None:
        result = await run_deterministic_matching([], mock_session_factory)

        assert result.all_matched is True
        assert result.skill_results == []
        assert result.unmatched == []

    @pytest.mark.asyncio
    async def test_whitespace_only_skills_filtered(self, mock_session_factory: MagicMock) -> None:
        result = await run_deterministic_matching(["   ", "\t", ""], mock_session_factory)

        assert result.all_matched is True
        assert result.skill_results == []

    @pytest.mark.asyncio
    async def test_short_skills_filtered(self, mock_session_factory: MagicMock) -> None:
        with (
            patch(
                "skill_graph_service.services.normalization.workflow._load_jaccard_candidates",
                AsyncMock(return_value=[]),
            ),
            patch(
                "skill_graph_service.services.normalization.workflow._deterministic_with_session",
                AsyncMock(return_value=None),
            ),
        ):
            result = await run_deterministic_matching(["a"], mock_session_factory)

        assert result.all_matched is True
        assert result.skill_results == []

    @pytest.mark.asyncio
    async def test_valid_skills_processed(self, mock_session_factory: MagicMock) -> None:
        skill = MagicMock(spec=SkillNode)
        skill.id = uuid.uuid4()
        skill.normalized_text = "python"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = skill
        mock_result.fetchall.return_value = []

        session = create_mock_session()
        session.execute = AsyncMock(return_value=mock_result)

        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=session)
        ctx.__aexit__ = AsyncMock(return_value=False)
        mock_session_factory.return_value = ctx

        with patch(
            "skill_graph_service.services.normalization.workflow._load_jaccard_candidates",
            AsyncMock(return_value=[]),
        ):
            result = await run_deterministic_matching(["Python"], mock_session_factory)

        assert len(result.skill_results) == 1


class TestRunSemanticQdrantSearch:
    """Tests for run_semantic_qdrant_search."""

    @pytest.mark.asyncio
    async def test_empty_unmatched_returns_empty(self) -> None:
        qdrant = AsyncMock()

        result = await run_semantic_qdrant_search([], [], qdrant)

        assert result == {}
        qdrant.search_dense_batch.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_valid_embeddings_returns_empty(self) -> None:
        qdrant = AsyncMock()
        unmatched = [(0, "python")]
        embedding_results: list = []

        result = await run_semantic_qdrant_search(unmatched, embedding_results, qdrant)

        assert result == {}

    @pytest.mark.asyncio
    async def test_successful_search_returns_results(self) -> None:
        qdrant = AsyncMock()
        skill_id = uuid.uuid4()

        search_match = SkillSearchMatch(
            point_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{skill_id}_label")),
            score=0.95,
            skill_id=str(skill_id),
            name="Python",
            description="",
        )

        qdrant.search_dense_batch = AsyncMock(return_value=[[search_match]])

        unmatched = [(0, "python")]

        embedding_item = MagicMock()
        embedding_item.item_attributes = {"position": "0"}
        dense_vec = EmbeddingVector(
            embedding_type=EmbeddingType.DENSE,
            dense=DenseData(values=[0.1] * 1024),
            collection_version="v1",
        )
        embedding_item.embeddings = [dense_vec]

        result = await run_semantic_qdrant_search(unmatched, [embedding_item], qdrant)

        assert 0 in result
        assert result[0].confidence == MatchConfidence.AUTO_MATCH

    @pytest.mark.asyncio
    async def test_qdrant_error_propagates_for_retry(self) -> None:
        """A transient Qdrant outage fails the callback so Kafka can retry it."""
        qdrant = AsyncMock()
        qdrant.search_dense_batch = AsyncMock(side_effect=OSError("Connection failed"))

        unmatched = [(0, "python")]
        embedding_item = MagicMock()
        embedding_item.item_attributes = {"position": "0"}
        embedding_item.embeddings = [
            EmbeddingVector(
                embedding_type=EmbeddingType.DENSE,
                dense=DenseData(values=[0.1] * 1024),
                collection_version="v1",
            )
        ]

        with pytest.raises(OSError, match="Connection failed"):
            await run_semantic_qdrant_search(unmatched, [embedding_item], qdrant)


class TestResolveCanonicalSkillIds:
    """Tests for the canonical picker-ID resolution path."""

    @pytest.mark.asyncio
    async def test_preserves_ids_names_requirements_and_aggregate_embedding(self) -> None:
        first, second = uuid.uuid4(), uuid.uuid4()
        first_node = MagicMock(id=first, display_name="Python", normalized_text="python")
        second_node = MagicMock(id=second, display_name="", normalized_text="data engineering")
        db_result = MagicMock()
        db_result.scalars.return_value.all.return_value = [second_node, first_node]
        session = create_mock_session()
        session.execute = AsyncMock(return_value=db_result)
        session_context = AsyncMock()
        session_context.__aenter__ = AsyncMock(return_value=session)
        session_context.__aexit__ = AsyncMock(return_value=False)
        session_factory = MagicMock(return_value=session_context)
        first_point = skill_variant_point_id(first, EmbeddingVariant.LABEL)
        second_point = skill_variant_point_id(second, EmbeddingVariant.LABEL)
        qdrant = AsyncMock()
        qdrant.retrieve_vectors = AsyncMock(return_value={first_point: [1.0, 0.0], second_point: [0.0, 1.0]})

        result = await resolve_canonical_skill_ids([str(first), str(second), str(first)], session_factory, "v1", qdrant)

        assert result is not None
        assert result.canonical_skill_ids == [str(first), str(second)]
        assert [detail.canonical_skill_name for detail in result.results] == ["Python", "data engineering"]
        assert [requirement.skill_id for requirement in result.skill_requirements] == [str(first), str(second)]
        assert result.aggregated_embedding is not None
        assert result.aggregated_embedding.dense is not None
        assert list(result.aggregated_embedding.dense.values) == pytest.approx([2**-0.5, 2**-0.5])
        qdrant.retrieve_vectors.assert_awaited_once()
        assert qdrant.retrieve_vectors.await_args is not None
        assert qdrant.retrieve_vectors.await_args.kwargs["point_ids"] == [first_point, second_point]

    @pytest.mark.asyncio
    async def test_missing_canonical_id_fails_closed(self) -> None:
        from nohiki_common_exceptions import ValidationError

        requested = uuid.uuid4()
        db_result = MagicMock()
        db_result.scalars.return_value.all.return_value = []
        session = create_mock_session()
        session.execute = AsyncMock(return_value=db_result)
        session_context = AsyncMock()
        session_context.__aenter__ = AsyncMock(return_value=session)
        session_context.__aexit__ = AsyncMock(return_value=False)
        qdrant = AsyncMock()

        with pytest.raises(ValidationError, match=str(requested)):
            await resolve_canonical_skill_ids([str(requested)], MagicMock(return_value=session_context), "v1", qdrant)

        qdrant.retrieve_vectors.assert_not_awaited()


class TestAssembleBatchNormalizationResult:
    """Tests for assemble_batch_normalization_result."""

    @pytest.mark.asyncio
    async def test_assembles_deterministic_only(self) -> None:
        skill_id = uuid.uuid4()
        det_result = DeterministicMatchResult(
            skill_results=[
                (
                    0,
                    "Python",
                    SkillNormalizationResult(
                        canonical_id=skill_id,
                        canonical_name="python",
                        match_type=SkillMatchType.EXACT,
                        confidence=MatchConfidence.CONFIDENT,
                        similarity_score=1.0,
                    ),
                )
            ],
            unmatched=[],
            all_matched=True,
        )

        qdrant = AsyncMock()
        label_point_id = skill_variant_point_id(skill_id, EmbeddingVariant.LABEL)
        qdrant.retrieve_vectors = AsyncMock(return_value={label_point_id: [0.5] * 1024})

        result = await assemble_batch_normalization_result(det_result, {}, "v1", qdrant)

        assert len(result.canonical_skill_ids) == 1
        assert result.canonical_skill_ids[0] == str(skill_id)
        assert result.requires_clarification is False
        # Regression guard: aggregation must call retrieve with UUID-formatted IDs (not "{uuid}_label").
        await_args = qdrant.retrieve_vectors.await_args
        assert await_args is not None
        called_with = await_args.kwargs["point_ids"]
        assert "_label" not in called_with[0]

    @pytest.mark.asyncio
    async def test_includes_semantic_results(self) -> None:
        skill_id = uuid.uuid4()
        det_result = DeterministicMatchResult(
            skill_results=[(0, "Python", None)],
            unmatched=[(0, "python")],
            all_matched=False,
        )

        semantic_results = {
            0: SkillNormalizationResult(
                canonical_id=skill_id,
                canonical_name="python",
                match_type=SkillMatchType.SEMANTIC,
                confidence=MatchConfidence.CONFIDENT,
                similarity_score=0.92,
            )
        }

        qdrant = AsyncMock()
        qdrant.retrieve_vectors = AsyncMock(
            return_value={skill_variant_point_id(skill_id, EmbeddingVariant.LABEL): [0.5] * 1024}
        )

        result = await assemble_batch_normalization_result(det_result, semantic_results, "v1", qdrant)

        assert len(result.canonical_skill_ids) == 1
        assert result.canonical_skill_ids[0] == str(skill_id)

    @pytest.mark.asyncio
    async def test_preserves_position_metadata_and_canonical_values_for_requirements(self) -> None:
        """Requirements retain input order, metadata, and canonical match details."""
        first, second = uuid.uuid4(), uuid.uuid4()
        first_match = SkillNormalizationResult(
            canonical_id=first,
            canonical_name="Canonical Python",
            match_type=SkillMatchType.EXACT,
            confidence=MatchConfidence.CONFIDENT,
            similarity_score=0.91,
        )
        semantic_match = SkillNormalizationResult(
            canonical_id=second,
            canonical_name="Canonical SQL",
            match_type=SkillMatchType.SEMANTIC,
            confidence=MatchConfidence.AUTO_MATCH,
            similarity_score=0.82,
        )
        duplicate_match = SkillNormalizationResult(
            canonical_id=first,
            canonical_name="Canonical Python",
            match_type=SkillMatchType.ALIAS,
            confidence=MatchConfidence.AUTO_MATCH,
            similarity_score=0.73,
        )
        det_result = DeterministicMatchResult(
            skill_results=[
                (0, "python", first_match),
                (1, "sql", None),
                (2, "python", duplicate_match),
            ],
            unmatched=[(1, "sql")],
            all_matched=False,
        )
        qdrant = AsyncMock()
        qdrant.retrieve_vectors = AsyncMock(
            return_value={
                skill_variant_point_id(first, EmbeddingVariant.LABEL): [1.0, 0.0],
                skill_variant_point_id(second, EmbeddingVariant.LABEL): [0.0, 1.0],
            }
        )

        result = await assemble_batch_normalization_result(
            det_result,
            {1: semantic_match},
            "v1",
            qdrant,
            raw_skill_metadata=[
                ("python", int(SkillProficiencyLevel.BEGINNER), True),
                ("sql", int(SkillProficiencyLevel.EXPERT), False),
            ],
        )

        assert [
            (
                requirement.skill_id,
                requirement.skill_name,
                requirement.proficiency_level,
                requirement.is_required,
                requirement.extraction_confidence,
            )
            for requirement in result.skill_requirements
        ] == [
            (str(first), "Canonical Python", SkillProficiencyLevel.BEGINNER, True, 0.91),
            (str(second), "Canonical SQL", SkillProficiencyLevel.EXPERT, False, 0.82),
            (str(first), "Canonical Python", SkillProficiencyLevel.UNSPECIFIED, False, 0.73),
        ]

    @pytest.mark.asyncio
    async def test_omitted_raw_metadata_uses_unspecified_requirement_defaults(self) -> None:
        """Requirements without raw metadata default to unspecified and optional."""
        skill_id = uuid.uuid4()
        det_result = DeterministicMatchResult(
            skill_results=[
                (
                    0,
                    "python",
                    SkillNormalizationResult(
                        canonical_id=skill_id,
                        canonical_name="Canonical Python",
                        match_type=SkillMatchType.EXACT,
                        confidence=MatchConfidence.CONFIDENT,
                        similarity_score=1.0,
                    ),
                )
            ],
            unmatched=[],
            all_matched=True,
        )
        qdrant = AsyncMock()
        qdrant.retrieve_vectors = AsyncMock(
            return_value={skill_variant_point_id(skill_id, EmbeddingVariant.LABEL): [1.0, 0.0]}
        )

        result = await assemble_batch_normalization_result(det_result, {}, "v1", qdrant)

        assert len(result.skill_requirements) == 1
        requirement = result.skill_requirements[0]
        assert requirement.skill_id == str(skill_id)
        assert requirement.skill_name == "Canonical Python"
        assert requirement.proficiency_level == SkillProficiencyLevel.UNSPECIFIED
        assert requirement.is_required is False
        assert requirement.extraction_confidence == 1.0

    @pytest.mark.asyncio
    async def test_uncertain_triggers_clarification(self) -> None:
        det_result = DeterministicMatchResult(
            skill_results=[(0, "Python", None)],
            unmatched=[(0, "python")],
            all_matched=False,
        )

        candidate = MagicMock()
        candidate.skill_id = str(uuid.uuid4())
        candidate.skill_name = "Python Programming"
        candidate.score = 0.75

        semantic_results = {
            0: SkillNormalizationResult(
                canonical_id=None,
                canonical_name=None,
                match_type=SkillMatchType.SEMANTIC,
                confidence=MatchConfidence.UNCERTAIN,
                similarity_score=0.75,
                candidates=[candidate],
            )
        }

        qdrant = AsyncMock()
        qdrant.retrieve_vectors = AsyncMock(return_value={})

        result = await assemble_batch_normalization_result(det_result, semantic_results, "v1", qdrant)

        assert result.requires_clarification is True
        assert len(result.clarifications) == 1
