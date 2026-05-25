"""Health check: skill graph data is seeded in PostgreSQL and Qdrant."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from health_check.config.thresholds import (
    HTTP_CHECK_TIMEOUT_SECONDS,
    QDRANT_PORT,
    SKILL_GRAPH_MIN_EMBEDDING_COUNT,
    SKILL_GRAPH_MIN_SKILL_COUNT,
)
from health_check.config.vectors import load_skill_collection_name
from health_check.core.base import HealthCheck
from health_check.core.models import CheckCategory, CheckMetadata, CheckResult, CheckStatus
from health_check.platform.models import PlatformTarget

if TYPE_CHECKING:
    from health_check.platform.protocol import Platform

_METADATA: Final[CheckMetadata] = CheckMetadata(
    check_id="skill_graph_seeded",
    name="Skill Graph Seeded",
    category=CheckCategory.APPLICATION,
    platforms=frozenset({PlatformTarget.COMPOSE, PlatformTarget.KUBERNETES}),
    depends_on=frozenset({"postgres_connectivity"}),
    timeout_seconds=30.0,
    description="Verify skill graph data meets minimum row and embedding counts.",
)

_SKILL_NODE_QUERY: Final[str] = "SELECT COUNT(*) FROM skill_graph_schema.skill_node"
_QDRANT_BASE: Final[str] = f"http://localhost:{QDRANT_PORT}"
_HTTP_TIMEOUT: Final[int] = int(HTTP_CHECK_TIMEOUT_SECONDS)


@dataclass(frozen=True, slots=True)
class _SkillCounts:
    """Aggregated skill data counts from PostgreSQL and Qdrant."""

    postgres_count: int | None
    qdrant_count: int | None


async def _query_postgres_skill_count(platform: Platform) -> int | None:
    """Return the skill_node row count or None if the query fails.

    Args:
        platform: Active platform for psql execution.

    Returns:
        Row count as int, or ``None`` on query failure.
    """
    code, stdout, _ = await asyncio.to_thread(platform.exec_psql, _SKILL_NODE_QUERY)
    if code != 0:
        return None
    try:
        return int(stdout.strip())
    except ValueError:
        return None


async def _query_qdrant_skill_count(platform: Platform, collection: str) -> int | None:
    """Return the number of points in the Qdrant skills collection.

    Args:
        platform: Active platform for HTTP curl.
        collection: Qdrant collection name for skills.

    Returns:
        Point count as int, or ``None`` if the collection is unreachable.
    """
    code, stdout, _ = await asyncio.to_thread(
        platform.curl,
        f"{_QDRANT_BASE}/collections/{collection}",
        timeout=_HTTP_TIMEOUT,
    )
    if code != 0:
        return None
    try:
        data = json.loads(stdout)
        count = data.get("result", {}).get("points_count")
        return int(count) if count is not None else 0
    except json.JSONDecodeError, ValueError, TypeError, KeyError:
        return None


async def _collect_counts(platform: Platform, collection: str) -> _SkillCounts:
    """Collect skill counts from PostgreSQL and Qdrant concurrently.

    Args:
        platform: Active platform.
        collection: Qdrant collection name for skills.

    Returns:
        Aggregated counts from both storage backends.
    """
    async with asyncio.TaskGroup() as tg:
        pg_task = tg.create_task(_query_postgres_skill_count(platform))
        qdrant_task = tg.create_task(_query_qdrant_skill_count(platform, collection))
    return _SkillCounts(
        postgres_count=pg_task.result(),
        qdrant_count=qdrant_task.result(),
    )


class SkillGraphSeededCheck(HealthCheck):
    """Verify the skill graph meets minimum data requirements in PostgreSQL and Qdrant."""

    @property
    def metadata(self) -> CheckMetadata:
        """Return check metadata."""
        return _METADATA

    async def execute(self, platform: Platform) -> CheckResult:
        """Run the skill graph seeding check."""
        collection = load_skill_collection_name()
        counts = await _collect_counts(platform, collection)

        if counts.postgres_count is None:
            return self._make_result(
                CheckStatus.ERROR,
                "Cannot query skill_graph_schema.skill_node",
                remediation_hint=("Ensure skill-graph-service migrations have run: just migrate skill-graph-service"),
            )

        failures: list[str] = []
        details: list[str] = []

        pg_count: int = counts.postgres_count
        if pg_count < SKILL_GRAPH_MIN_SKILL_COUNT:
            failures.append(f"PostgreSQL: {pg_count:,} skill nodes (minimum {SKILL_GRAPH_MIN_SKILL_COUNT:,})")
        else:
            details.append(f"PostgreSQL: {pg_count:,} skill nodes")

        # Track point count as a typed int for the success-path summary.
        # Each branch assigns an int so ty can verify the type without casts.
        qdrant_point_count: int
        if counts.qdrant_count is None:
            failures.append(f"Qdrant collection '{collection}': unreachable")
            qdrant_point_count = 0
        elif counts.qdrant_count < SKILL_GRAPH_MIN_EMBEDDING_COUNT:
            failures.append(
                f"Qdrant '{collection}': {counts.qdrant_count:,} points (minimum {SKILL_GRAPH_MIN_EMBEDDING_COUNT:,})"
            )
            qdrant_point_count = counts.qdrant_count
        else:
            details.append(f"Qdrant '{collection}': {counts.qdrant_count:,} points")
            qdrant_point_count = counts.qdrant_count

        if failures:
            return self._make_result(
                CheckStatus.FAILED,
                f"{len(failures)} skill graph seeding issue(s)",
                details=tuple(failures),
                remediation_hint=(
                    "Kubernetes: Helm pre-install hook seeds automatically. "
                    "Local: uv run --package bootstrap-skill-graph-job bootstrap-skill-graph "
                    "(set DB_*, KAFKA_BOOTSTRAP_SERVERS, TABIYA_*_CSV env vars)"
                ),
            )

        return self._make_result(
            CheckStatus.PASSED,
            f"Skill graph seeded: {pg_count:,} nodes, {qdrant_point_count:,} embeddings",
            details=tuple(details),
        )
