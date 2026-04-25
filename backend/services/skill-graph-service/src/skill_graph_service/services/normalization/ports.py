"""Port interfaces (protocols) for normalization infrastructure dependencies.

These protocols define the contracts that adapters must implement, enabling
dependency inversion and testability.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from skill_graph_service.db.models import SkillNode


type SkillCandidate = tuple[str, str]


@dataclass(frozen=True, slots=True)
class SkillSearchMatch:
    """Typed skill search result with validated payload fields.

    Constructed from raw Qdrant results at the adapter boundary.
    All payload fields are validated at construction time.
    """

    point_id: str
    score: float
    skill_id: str
    name: str
    description: str = ""


@dataclass(frozen=True, slots=True)
class MatchCounts:
    """Match type distribution for metrics."""

    exact: int
    alias: int
    jaccard: int
    semantic: int
    uncertain: int
    no_match: int


class SkillReadPort(Protocol):
    """Port for reading skill data from persistent storage."""

    async def find_exact_match(self, normalized: str) -> SkillNode | None:
        """Find skill by exact case-insensitive match on normalized_text."""
        ...

    async def find_alias_match(
        self,
        normalized: str,
        *,
        context_hint: str | None = None,
    ) -> SkillNode | None:
        """Find skill via alias table lookup with optional context disambiguation."""
        ...

    async def load_jaccard_corpus(self) -> list[SkillCandidate]:
        """Load skill corpus for Jaccard matching (id, normalized_text pairs)."""
        ...


class SemanticSearchPort(Protocol):
    """Port for semantic vector search operations."""

    async def search_dense_batch(
        self,
        queries: list[list[float]],
        *,
        limit: int,
        score_threshold: float,
    ) -> list[list[SkillSearchMatch]]:
        """Search for similar skills using dense vectors."""
        ...

    async def retrieve_vectors(
        self,
        point_ids: list[str],
    ) -> dict[str, list[float]]:
        """Retrieve existing vectors by point IDs."""
        ...


class MetricsPort(Protocol):
    """Port for recording normalization metrics."""

    def record_batch_duration(self, duration_seconds: float, batch_size: int) -> None:
        """Record batch normalization duration."""
        ...

    def record_match_counts(self, counts: MatchCounts) -> None:
        """Record match type distribution."""
        ...
