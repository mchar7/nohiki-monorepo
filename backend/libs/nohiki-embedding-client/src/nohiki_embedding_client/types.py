"""Type definitions for embedding client."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from nohiki.ml.v1 import BatchEmbeddingResultItem, EmbeddingType, EmbeddingVector, EncodingMode

if TYPE_CHECKING:
    from nohiki.ml.v1 import (
        EmbeddingCallback,
        EntityType,
    )
    from nohiki.ml.v1 import (
        EmbeddingResult as ProtoEmbeddingResult,
    )

SHA256_HEX_LENGTH = 64


def _validate_content_hash(value: str, field_name: str) -> None:
    """Require canonical SHA-256 text at every callback decode boundary."""
    valid = len(value) == SHA256_HEX_LENGTH and all(char in "0123456789abcdef" for char in value)
    if not valid:
        msg = f"{field_name} must be a lowercase SHA-256 hex digest"
        raise ValueError(msg)


def _validate_embeddings(embeddings: list[EmbeddingVector]) -> None:
    """Reject malformed callback vectors before they reach storage or scoring."""
    seen_types: set[EmbeddingType] = set()
    for embedding in embeddings:
        if embedding.embedding_type in seen_types:
            msg = f"Duplicate embedding type {embedding.embedding_type.name}"
            raise ValueError(msg)
        seen_types.add(embedding.embedding_type)
        _validate_content_hash(embedding.content_hash, "Embedding content_hash")

        match embedding.embedding_type:
            case EmbeddingType.DENSE | EmbeddingType.MUVERA:
                values = embedding.dense.values if embedding.dense is not None else []
                valid = bool(values) and all(math.isfinite(value) for value in values)
            case EmbeddingType.SPARSE:
                sparse = embedding.sparse
                valid = (
                    sparse is not None
                    and bool(sparse.values)
                    and len(sparse.indices) == len(sparse.values)
                    and len(set(sparse.indices)) == len(sparse.indices)
                    and all(math.isfinite(value) for value in sparse.values)
                )
            case EmbeddingType.COLBERT:
                multi = embedding.multi_vector
                valid = (
                    multi is not None
                    and multi.num_tokens > 0
                    and multi.token_dim > 0
                    and len(multi.values) == multi.num_tokens * multi.token_dim
                    and all(math.isfinite(value) for value in multi.values)
                )
            case _:
                valid = False
        if not valid:
            msg = f"Malformed {embedding.embedding_type.name} embedding vector"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class EmbeddingSpec:
    """Specification for what and how to embed.

    Bundles the embedding-specific parameters (types, mode, indexing)
    into a single typed container, keeping method signatures
    under 5 positional args.

    Attributes:
        requested_types: Which embedding geometries to compute.
        encoding_mode: DOCUMENT (AVG aggregation) or QUERY (SUM aggregation).
        publish_to_index: Whether to publish vectors to Qdrant via Kafka sink.

    """

    requested_types: list[EmbeddingType] = field(default_factory=list)
    encoding_mode: EncodingMode = EncodingMode.DOCUMENT
    publish_to_index: bool = False


@dataclass(frozen=True, slots=True)
class EmbeddingResult:
    """Result from an embedding request containing all computed embeddings.

    Attributes:
        embeddings: All computed embedding vectors.
        entity_id: Entity identifier that was embedded.
        entity_type: Type of entity (JOB, PROFILE, SKILL).
        collection_version: Qdrant collection version.
        content_hash: SHA-256 hash of the embedded content.
        encoding_mode: DOCUMENT or QUERY encoding mode used.

    """

    embeddings: list[EmbeddingVector]
    entity_id: str
    entity_type: EntityType
    collection_version: str
    content_hash: str
    encoding_mode: EncodingMode

    @classmethod
    def from_callback(cls, message: EmbeddingCallback) -> EmbeddingResult:
        """Create result from an EmbeddingCallback success message.

        Args:
            message: The EmbeddingCallback response with success payload.

        Returns:
            EmbeddingResult populated from the callback's success branch.

        Raises:
            ValueError: If the callback contains an error instead of success.

        """
        success: ProtoEmbeddingResult | None = message.success
        if success is None:
            msg = f"EmbeddingCallback {message.callback.operation_id} is not a success"
            raise ValueError(msg)
        embeddings = list(success.embeddings)
        requested_types = list(success.requested_types)
        if not embeddings:
            msg = "Successful embedding callback must contain at least one embedding"
            raise ValueError(msg)
        if len(set(requested_types)) != len(requested_types):
            msg = "Embedding result requested_types must be unique"
            raise ValueError(msg)
        returned_types = {embedding.embedding_type for embedding in embeddings}
        if returned_types != set(requested_types):
            msg = (
                f"Embedding result types {sorted(item.name for item in returned_types)} do not match "
                f"requested types {sorted(item.name for item in requested_types)}"
            )
            raise ValueError(msg)
        _validate_embeddings(embeddings)
        _validate_content_hash(success.content_hash, "Embedding result content_hash")
        return cls(
            embeddings=embeddings,
            entity_id=message.entity_id,
            entity_type=message.entity_type,
            collection_version=success.collection_version,
            content_hash=success.content_hash,
            encoding_mode=success.encoding_mode,
        )

    def get_by_type(self, embedding_type: EmbeddingType) -> EmbeddingVector | None:
        """Find the first EmbeddingVector matching the given type.

        Args:
            embedding_type: The embedding type to search for.

        Returns:
            Matching EmbeddingVector or None if not found.

        """
        return next((emb for emb in self.embeddings if emb.embedding_type == embedding_type), None)

    def get_dense(self) -> EmbeddingVector | None:
        """Get the DENSE embedding vector, if present."""
        return self.get_by_type(EmbeddingType.DENSE)

    def get_muvera(self) -> EmbeddingVector | None:
        """Get the MUVERA embedding vector, if present."""
        return self.get_by_type(EmbeddingType.MUVERA)

    def get_sparse(self) -> EmbeddingVector | None:
        """Get the SPARSE embedding vector, if present."""
        return self.get_by_type(EmbeddingType.SPARSE)

    def get_colbert(self) -> EmbeddingVector | None:
        """Get the COLBERT embedding vector, if present."""
        return self.get_by_type(EmbeddingType.COLBERT)


@dataclass(frozen=True, slots=True)
class BatchEmbeddingItemResult:
    """Result for a single item within a batch embedding response.

    Returned as elements of the list from batch embedding callback handlers.
    Mirrors EmbeddingResult but scoped to one item: entity_type and
    encoding_mode are batch-wide and carried on the parent response.

    Attributes:
        point_id: Qdrant point identifier echoed from the request item.
        entity_id: Canonical entity UUID echoed from the request item.
        embeddings: Computed embedding vectors for this item.
        content_hash: SHA-256 hex of the embedded text (64 chars).
        item_attributes: Key-value attributes echoed from the request item.

    """

    point_id: str
    entity_id: str
    embeddings: list[EmbeddingVector]
    content_hash: str
    item_attributes: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_result_item(cls, item: BatchEmbeddingResultItem) -> BatchEmbeddingItemResult:
        """Create from a BatchEmbeddingResultItem proto message.

        Args:
            item: The proto result item from a BatchEmbeddingCallback message.

        Returns:
            BatchEmbeddingItemResult populated from the proto item.

        """
        embeddings = list(item.embeddings)
        _validate_embeddings(embeddings)
        _validate_content_hash(item.content_hash, "Batch embedding item content_hash")
        return cls(
            point_id=item.point_id,
            entity_id=item.entity_id,
            embeddings=embeddings,
            content_hash=item.content_hash,
            item_attributes=dict(item.item_attributes) if item.item_attributes else {},
        )

    def get_by_type(self, embedding_type: EmbeddingType) -> EmbeddingVector | None:
        """Find the first EmbeddingVector matching the given type.

        Args:
            embedding_type: The embedding type to search for.

        Returns:
            Matching EmbeddingVector or None if not found.

        """
        return next((emb for emb in self.embeddings if emb.embedding_type == embedding_type), None)

    def get_dense(self) -> EmbeddingVector | None:
        """Get the DENSE embedding vector, if present."""
        return self.get_by_type(EmbeddingType.DENSE)
