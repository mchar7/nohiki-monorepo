"""Tests for normalization adapter implementations."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from skill_graph_service.services.normalization.ports import SkillSearchMatch
from skill_graph_service.services.normalization_adapters import (
    QdrantSemanticAdapter,
    SqlSkillReadAdapter,
)


class TestSqlSkillReadAdapter:
    """Tests for SqlSkillReadAdapter."""

    @pytest.fixture
    def mock_session(self) -> AsyncMock:
        """Provide a mock async session."""
        return AsyncMock()

    @pytest.fixture
    def adapter(self, mock_session: AsyncMock) -> SqlSkillReadAdapter:
        """Provide adapter instance with mocked session."""
        return SqlSkillReadAdapter(mock_session)

    @pytest.mark.asyncio
    async def test_find_exact_match_returns_skill(self, adapter: SqlSkillReadAdapter, mock_session: AsyncMock) -> None:
        """Should return skill when exact match found."""
        mock_skill = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_skill
        mock_session.execute.return_value = mock_result

        result = await adapter.find_exact_match("python")

        assert result is mock_skill
        mock_session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_find_exact_match_returns_none(self, adapter: SqlSkillReadAdapter, mock_session: AsyncMock) -> None:
        """Should return None when no exact match found."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        result = await adapter.find_exact_match("nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_find_alias_match_delegates_to_resolve_alias(
        self, adapter: SqlSkillReadAdapter, mock_session: AsyncMock
    ) -> None:
        """Should delegate to resolve_alias function."""
        from unittest.mock import patch

        mock_skill = MagicMock()
        with patch(
            "skill_graph_service.services.normalization_adapters.db_adapter.resolve_alias",
            new_callable=AsyncMock,
            return_value=mock_skill,
        ) as mock_resolve:
            result = await adapter.find_alias_match("py", context_hint="programming")

            mock_resolve.assert_called_once_with("py", mock_session, context_hint="programming")
            assert result is mock_skill

    @pytest.mark.asyncio
    async def test_load_jaccard_corpus_returns_candidates(
        self, adapter: SqlSkillReadAdapter, mock_session: AsyncMock
    ) -> None:
        """Should return list of (id, text) tuples."""
        skill_id = uuid4()
        mock_row = MagicMock()
        mock_row.id = skill_id
        mock_row.normalized_text = "python"

        mock_result = MagicMock()
        mock_result.fetchall.return_value = [mock_row]
        mock_session.execute.return_value = mock_result

        result = await adapter.load_jaccard_corpus(limit=100)

        assert len(result) == 1
        assert result[0] == (str(skill_id), "python")


class TestQdrantSemanticAdapter:
    """Tests for QdrantSemanticAdapter."""

    @pytest.fixture
    def mock_client(self) -> AsyncMock:
        """Provide a mock Qdrant client."""
        return AsyncMock()

    @pytest.fixture
    def adapter(self, mock_client: AsyncMock) -> QdrantSemanticAdapter:
        """Provide adapter instance with mocked client."""
        return QdrantSemanticAdapter(mock_client, "skills")

    @pytest.mark.asyncio
    async def test_search_dense_batch_returns_results(
        self, adapter: QdrantSemanticAdapter, mock_client: AsyncMock
    ) -> None:
        """Should convert raw Qdrant results to typed skill matches."""
        skill_id = str(uuid4())

        # Create mock HybridSearchResult with required payload fields
        raw_result = MagicMock()
        raw_result.id = f"{skill_id}_label"
        raw_result.score = 0.95
        raw_result.payload = {"skill_id": skill_id, "name": "Python", "description": "lang"}

        mock_client.search_dense_batch.return_value = [[raw_result]]

        queries = [[0.1, 0.2]]
        result = await adapter.search_dense_batch(queries, limit=10, score_threshold=0.8)

        # Verify result contains SkillSearchMatch objects
        assert len(result) == 1
        assert len(result[0]) == 1
        match = result[0][0]
        assert isinstance(match, SkillSearchMatch)
        assert match.skill_id == skill_id
        assert match.name == "Python"
        assert match.score == 0.95
        mock_client.search_dense_batch.assert_called_once()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "payload",
        [{"name": "Python"}, {"skill_id": "not-a-uuid", "name": "Python"}],
        ids=["missing", "malformed"],
    )
    async def test_search_dense_batch_invalid_skill_id_raises_error(
        self,
        adapter: QdrantSemanticAdapter,
        mock_client: AsyncMock,
        payload: dict[str, str],
    ) -> None:
        """Missing and malformed canonical IDs fail closed before matching."""
        from nohiki_common_exceptions import DataIntegrityError

        raw_result = MagicMock()
        raw_result.id = "some_point_id"
        raw_result.score = 0.95
        raw_result.payload = payload
        mock_client.search_dense_batch.return_value = [[raw_result]]

        with pytest.raises(DataIntegrityError, match="invalid 'skill_id'"):
            await adapter.search_dense_batch([[0.1, 0.2]], limit=10, score_threshold=0.8)

    @pytest.mark.asyncio
    async def test_retrieve_vectors_returns_dict(self, adapter: QdrantSemanticAdapter, mock_client: AsyncMock) -> None:
        """Should return vector dict from client."""
        mock_vectors = {"id1": [0.1, 0.2], "id2": [0.3, 0.4]}
        mock_client.retrieve_vectors.return_value = mock_vectors

        result = await adapter.retrieve_vectors(["id1", "id2"])

        assert result == mock_vectors
        mock_client.retrieve_vectors.assert_called_once_with(collection_name="skills", point_ids=["id1", "id2"])


class TestAdapterExports:
    """Tests for adapter module exports."""

    def test_adapters_exported_from_package(self) -> None:
        """Should export both adapters from package."""
        from skill_graph_service.services.normalization_adapters import (
            QdrantSemanticAdapter,
            SqlSkillReadAdapter,
        )

        assert SqlSkillReadAdapter is not None
        assert QdrantSemanticAdapter is not None


class TestPortsDataclasses:
    """Tests for ports module dataclasses."""

    def test_match_counts_creation(self) -> None:
        """Should create MatchCounts with all fields."""
        from skill_graph_service.services.normalization.ports import MatchCounts

        counts = MatchCounts(exact=1, alias=2, jaccard=3, semantic=4, uncertain=5, no_match=6)

        assert counts.exact == 1
        assert counts.alias == 2
        assert counts.jaccard == 3
        assert counts.semantic == 4
        assert counts.uncertain == 5
        assert counts.no_match == 6

    def test_match_counts_is_frozen(self) -> None:
        """Should be immutable."""
        from skill_graph_service.services.normalization.ports import MatchCounts

        assert MatchCounts.__dataclass_params__.frozen
