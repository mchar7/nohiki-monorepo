"""Unit tests for alias service."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from skill_graph_service.db.models import SkillAlias, SkillNode


class TestResolveAlias:
    """Tests for resolve_alias function."""

    @pytest.mark.asyncio
    async def test_returns_none_when_no_alias_found(
        self,
        mock_db_session: AsyncMock,
    ) -> None:
        """Test that None is returned when no alias exists."""
        from skill_graph_service.services.alias_service import resolve_alias

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute.return_value = mock_result

        result = await resolve_alias("unknown-skill", mock_db_session)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_skill_node_when_alias_found(
        self,
        mock_db_session: AsyncMock,
    ) -> None:
        """Test that SkillNode is returned when alias exists."""
        from skill_graph_service.services.alias_service import resolve_alias

        skill_id = uuid.uuid4()
        mock_skill = MagicMock(spec=SkillNode)
        mock_skill.id = skill_id
        mock_skill.normalized_text = "python"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_skill
        mock_db_session.execute.return_value = mock_result

        result = await resolve_alias("py", mock_db_session)
        assert result is not None
        assert result.id == skill_id

    @pytest.mark.asyncio
    async def test_uses_context_hint_when_provided(
        self,
        mock_db_session: AsyncMock,
    ) -> None:
        """Test that context_hint is used in query."""
        from skill_graph_service.services.alias_service import resolve_alias

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute.return_value = mock_result

        await resolve_alias("ml", mock_db_session, context_hint="data science")

        assert mock_db_session.execute.called


class TestUpsertAlias:
    """Tests for upsert_alias function."""

    @pytest.mark.asyncio
    async def test_creates_new_alias(
        self,
        mock_db_session: AsyncMock,
    ) -> None:
        """Test creating a new alias."""
        from skill_graph_service.services.alias_service import AliasUpsertParams, upsert_alias

        skill_id = uuid.uuid4()
        mock_alias = MagicMock(spec=SkillAlias)
        mock_alias.alias_text = "py"
        mock_alias.canonical_skill_id = skill_id
        mock_alias.usage_count = 1

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_alias
        mock_db_session.execute.return_value = mock_result

        result = await upsert_alias(
            db=mock_db_session,
            params=AliasUpsertParams(
                alias_text="py",
                canonical_skill_id=skill_id,
                source="llm_extraction",
                source_version="dynamic",
            ),
        )

        assert result.alias_text == "py"
        assert mock_db_session.commit.called

    @pytest.mark.asyncio
    async def test_conflicting_canonical_mapping_fails_without_commit(
        self,
        mock_db_session: AsyncMock,
    ) -> None:
        """A losing upsert race cannot silently remap an alias to another skill."""
        from nohiki_common_exceptions import DataIntegrityError
        from skill_graph_service.services.alias_service import AliasUpsertParams, upsert_alias

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute.return_value = mock_result

        with pytest.raises(DataIntegrityError, match="different canonical skill"):
            await upsert_alias(
                db=mock_db_session,
                params=AliasUpsertParams(
                    alias_text="py",
                    canonical_skill_id=uuid.uuid4(),
                    source="llm_extraction",
                    source_version="dynamic",
                ),
            )

        mock_db_session.commit.assert_not_awaited()


class TestIncrementAliasUsage:
    """Tests for increment_alias_usage function."""

    @pytest.mark.asyncio
    async def test_returns_true_when_updated(
        self,
        mock_db_session: AsyncMock,
    ) -> None:
        """Test that True is returned when alias is updated."""
        from skill_graph_service.services.alias_service import increment_alias_usage

        mock_result = MagicMock()
        mock_result.rowcount = 1
        mock_db_session.execute.return_value = mock_result

        result = await increment_alias_usage("py", mock_db_session)
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_not_found(
        self,
        mock_db_session: AsyncMock,
    ) -> None:
        """Test that False is returned when alias doesn't exist."""
        from skill_graph_service.services.alias_service import increment_alias_usage

        mock_result = MagicMock()
        mock_result.rowcount = 0
        mock_db_session.execute.return_value = mock_result

        result = await increment_alias_usage("nonexistent", mock_db_session)
        assert result is False
