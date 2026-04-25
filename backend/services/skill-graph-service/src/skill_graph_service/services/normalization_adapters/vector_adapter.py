"""Qdrant vector adapter for semantic search and embedding retrieval.

Implements SemanticSearchPort protocol using QdrantVectorClient.
"""

from __future__ import annotations

from uuid import UUID

from nohiki_common_exceptions import DataIntegrityError
from nohiki_qdrant_client import HybridSearchResult, QdrantVectorClient, SearchParams

from skill_graph_service.services.normalization.ports import SkillSearchMatch


class QdrantSemanticAdapter:
    """Adapter for semantic vector operations using Qdrant.

    Implements the SemanticSearchPort protocol for vector search and retrieval.
    """

    def __init__(self, client: QdrantVectorClient, collection_name: str) -> None:
        """Initialize with Qdrant client and collection name.

        Args:
            client: Qdrant vector client instance.
            collection_name: Name of the Qdrant collection for skills.

        """
        self._client = client
        self._collection_name = collection_name

    @staticmethod
    def _to_skill_match(result: HybridSearchResult) -> SkillSearchMatch:
        """Convert raw Qdrant result to typed skill match.

        Validates that required payload fields are present.

        Args:
            result: Raw Qdrant search result.

        Returns:
            Typed skill match with validated fields.

        Raises:
            DataIntegrityError: If required payload fields are missing.

        """
        payload = result.payload
        skill_id = payload.get("skill_id")
        try:
            canonical_id = str(UUID(str(skill_id)))
        except (TypeError, ValueError) as exc:
            raise DataIntegrityError(
                resource_type="SkillEmbedding",
                resource_ids=(str(result.id),),
                message=f"Qdrant point {result.id} has invalid 'skill_id' payload field",
            ) from exc
        return SkillSearchMatch(
            point_id=str(result.id),
            score=result.score,
            skill_id=canonical_id,
            name=str(payload.get("name", "")),
            description=str(payload.get("description", "")),
        )

    async def search_dense_batch(
        self,
        queries: list[list[float]],
        *,
        limit: int,
        score_threshold: float,
    ) -> list[list[SkillSearchMatch]]:
        """Search for similar skills using dense vectors.

        Args:
            queries: List of query vectors.
            limit: Maximum results per query.
            score_threshold: Minimum similarity score.

        Returns:
            List of typed skill matches per query.

        """
        params = SearchParams(
            collection_name=self._collection_name,
            limit=limit,
            score_threshold=score_threshold,
        )
        raw_results = await self._client.search_dense_batch(queries=queries, params=params)
        matches: list[list[SkillSearchMatch]] = []
        for batch in raw_results:
            unique_by_skill: dict[str, SkillSearchMatch] = {}
            for result in batch:
                match = self._to_skill_match(result)
                if match.skill_id not in unique_by_skill:
                    unique_by_skill[match.skill_id] = match
            matches.append(list(unique_by_skill.values()))
        return matches

    async def retrieve_vectors(
        self,
        point_ids: list[str],
    ) -> dict[str, list[float]]:
        """Retrieve existing vectors by point IDs.

        Args:
            point_ids: List of point IDs to retrieve.

        Returns:
            Dict mapping point ID to vector.

        """
        return await self._client.retrieve_vectors(
            collection_name=self._collection_name,
            point_ids=point_ids,
        )
