"""SQL database adapter for skill reads, alias resolution, and Jaccard corpus loading.

Implements SkillReadPort protocol using SQLAlchemy async session.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func, select

from skill_graph_service.db.models import SkillNode
from skill_graph_service.services.alias_service import resolve_alias
from skill_graph_service.services.normalization.ports import SkillCandidate

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class SqlSkillReadAdapter:
    """Adapter for reading skill data from PostgreSQL.

    Implements the SkillReadPort protocol for database operations.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize with a database session.

        Args:
            session: SQLAlchemy async session for database operations.

        """
        self._session = session

    async def find_exact_match(self, normalized: str) -> SkillNode | None:
        """Find skill by exact case-insensitive match on normalized_text.

        Args:
            normalized: Lowercase normalized skill text.

        Returns:
            SkillNode if found, None otherwise.

        """
        stmt = select(SkillNode).where(func.lower(SkillNode.normalized_text) == normalized)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_alias_match(
        self,
        normalized: str,
        *,
        context_hint: str | None = None,
    ) -> SkillNode | None:
        """Find skill via alias table lookup with optional context disambiguation.

        Args:
            normalized: Lowercase normalized skill text.
            context_hint: Optional context for disambiguation.

        Returns:
            SkillNode if alias found, None otherwise.

        """
        return await resolve_alias(normalized, self._session, context_hint=context_hint)

    async def load_jaccard_corpus(self, *, limit: int) -> list[SkillCandidate]:
        """Load skill corpus for Jaccard matching.

        Args:
            limit: Maximum number of candidates to load.

        Returns:
            List of (skill_id, normalized_text) tuples.

        """
        stmt = select(SkillNode.id, SkillNode.normalized_text).limit(limit)
        result = await self._session.execute(stmt)
        return [(str(row.id), row.normalized_text) for row in result.fetchall()]
