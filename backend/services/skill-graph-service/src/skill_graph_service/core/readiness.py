"""Skill embedding readiness gate for health checks."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import TYPE_CHECKING

from nohiki_observability import get_logger

if TYPE_CHECKING:
    from nohiki_qdrant_client import QdrantVectorClient

logger = get_logger(__name__)


class SkillEmbeddingReadinessGate:
    """Readiness gate that opens once Qdrant has at least one skill embedding.

    Polls Qdrant on a background task. The /readyz endpoint returns 503
    until ``is_ready`` becomes True, allowing Docker/K8s to hold traffic
    until the skill collection is populated.

    Usage:
        gate = SkillEmbeddingReadinessGate(qdrant_client, collection_name)
        gate.start()
        # ... app runs ...
        await gate.stop()

    Attributes:
        _qdrant: Qdrant client used for point count queries.
        _collection_name: Skill embedding collection to poll.
        _poll_interval: Seconds between Qdrant polls.
        _min_point_count: Minimum points required to be considered ready.
        _is_ready: Set to True once the count threshold is reached.
        _is_failed: Set to True if polling encounters a permanent failure.
        _task: Background asyncio polling task.

    """

    def __init__(
        self,
        qdrant_client: QdrantVectorClient,
        collection_name: str,
        poll_interval_seconds: float = 5.0,
        min_point_count: int = 1,
    ) -> None:
        """Initialize the readiness gate.

        Args:
            qdrant_client: Qdrant vector client for count queries.
            collection_name: Name of the skill embedding collection to check.
            poll_interval_seconds: Seconds between Qdrant count polls. Default 5.
            min_point_count: Minimum number of points to consider ready. Default 1.

        """
        self._qdrant = qdrant_client
        self._collection_name = collection_name
        self._poll_interval = poll_interval_seconds
        self._min_point_count = min_point_count
        self._is_ready = False
        self._is_failed = False
        self._task: asyncio.Task[None] | None = None

    @property
    def is_ready(self) -> bool:
        """Return True once Qdrant has at least min_point_count skill embeddings."""
        return self._is_ready

    @property
    def is_failed(self) -> bool:
        """Return True if the readiness poll task was cancelled unexpectedly."""
        return self._is_failed

    def start(self) -> None:
        """Spawn the background polling task.

        Must be called from within a running asyncio event loop (e.g. FastAPI lifespan).

        """
        self._task = asyncio.create_task(self._poll_loop(), name="skill-readiness-gate")
        logger.info(
            "Readiness gate started",
            collection=self._collection_name,
            min_point_count=self._min_point_count,
        )

    async def stop(self) -> None:
        """Cancel the background polling task and wait for it to finish.

        Safe to call even if the gate is already ready or was never started.

        """
        if self._task is not None and not self._task.done():
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            logger.debug("Readiness gate stopped", collection=self._collection_name)

    async def _poll_loop(self) -> None:
        """Poll Qdrant count until the threshold is reached."""
        while not self._is_ready:
            try:
                count = await self._qdrant.count_points(self._collection_name)
                if count >= self._min_point_count:
                    self._is_ready = True
                    logger.info(
                        "Readiness gate opened -- skill embeddings available",
                        collection=self._collection_name,
                        point_count=count,
                    )
                    return
                logger.debug(
                    "Readiness gate polling -- awaiting embeddings",
                    collection=self._collection_name,
                    current_count=count,
                    min_required=self._min_point_count,
                )
            except Exception:  # noqa: BLE001  # poll loop must survive any transient Qdrant error
                logger.debug(
                    "Readiness gate poll failed -- will retry",
                    collection=self._collection_name,
                    exc_info=True,
                )
            await asyncio.sleep(self._poll_interval)
