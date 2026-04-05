"""ML Encoding Pipeline - orchestrates full encoding flow.

All embeddings are returned inline. Qdrant is the canonical store
via Kafka Sink Connector - NO S3/Redis storage.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np
from nohiki_ml_manifest import SemanticRepresentationManifest
from nohiki_observability import get_logger

from nohiki_ml_core.encoders.colbert import ColBERTEncoder
from nohiki_ml_core.encoders.dense import DenseEncoder
from nohiki_ml_core.encoders.muvera import MUVERAEncoder
from nohiki_ml_core.encoders.sparse import SparseEncoder, SparseVector

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class EncodingResult:
    """Result of encoding a document - all embeddings inline."""

    colbert_tokens: np.ndarray
    muvera_fde: np.ndarray
    sparse_vector: SparseVector
    content_hash: str


@dataclass(frozen=True, slots=True)
class DenseEncodingResult:
    """Result of dense-only encoding (geometry derived from manifest)."""

    dense_embedding: np.ndarray
    content_hash: str


@dataclass(frozen=True, slots=True)
class DenseBatchEncodingResult:
    """Result of batched dense encoding: all items encoded in one inference pass."""

    dense_embeddings: np.ndarray
    content_hashes: list[str]


class MLEncodingPipeline:
    """Orchestrates full encoding pipeline.

    Used by ml-compute-service and Modal functions.

    All embeddings are returned inline - Qdrant is the canonical store
    via Kafka Sink Connector. NO S3/Redis storage.
    """

    def __init__(self, manifest: SemanticRepresentationManifest) -> None:
        """Initialize encoding pipeline.

        Args:
            manifest: Semantic representation configuration

        """
        self.manifest = manifest

        # Initialize encoders
        self.colbert = ColBERTEncoder(manifest)
        self.muvera = MUVERAEncoder(manifest)
        self.sparse = SparseEncoder(manifest)
        self.dense = DenseEncoder(manifest)

        logger.info(
            "ML encoding pipeline initialized",
            jobs_version=manifest.collections.jobs.version,
            profiles_version=manifest.collections.profiles.version,
            skills_version=manifest.collections.skills.version,
        )

    def encode_document(self, text: str, entity_id: str) -> EncodingResult:
        """Complete document encoding pipeline.

        Steps:
        1. Generate ColBERT tokens
        2. Generate MUVERA FDE from tokens
        3. Generate sparse vector

        All embeddings returned inline - Qdrant stores via Kafka sink.

        Args:
            text: Document text to encode
            entity_id: Entity ID for logging

        Returns:
            EncodingResult with all artifacts inline

        """
        content_hash = self._compute_content_hash(text)

        # 1. ColBERT encoding
        logger.debug("Encoding ColBERT tokens", entity_id=entity_id)
        colbert_tokens = self.colbert.encode_document(text)

        # 2. MUVERA FDE
        logger.debug("Encoding MUVERA FDE", entity_id=entity_id)
        muvera_fde = self.muvera.encode(colbert_tokens, is_query=False)

        # 3. Sparse vector
        logger.debug("Encoding sparse vector", entity_id=entity_id)
        sparse_vector = self.sparse.encode(text)

        logger.info(
            "Document encoding completed",
            entity_id=entity_id,
            num_tokens=colbert_tokens.shape[0],
            muvera_dim=muvera_fde.shape[0],
            sparse_terms=len(sparse_vector.indices),
            content_hash=content_hash,
        )

        return EncodingResult(
            colbert_tokens=colbert_tokens,
            muvera_fde=muvera_fde,
            sparse_vector=sparse_vector,
            content_hash=content_hash,
        )

    def encode_query(self, text: str) -> EncodingResult:
        """Query encoding using asymmetric ColBERT + SUM-aggregated MUVERA.

        Args:
            text: Query text to encode

        Returns:
            EncodingResult with all artifacts inline

        """
        content_hash = self._compute_content_hash(text)

        # ColBERT query encoding (asymmetric)
        logger.debug("Encoding query ColBERT tokens")
        colbert_tokens = self.colbert.encode_query(text)

        # MUVERA FDE with SUM aggregation
        logger.debug("Encoding query MUVERA FDE")
        muvera_fde = self.muvera.encode(colbert_tokens, is_query=True)

        # Sparse vector
        logger.debug("Encoding query sparse vector")
        sparse_vector = self.sparse.encode(text)

        logger.info(
            "Query encoding completed",
            num_tokens=colbert_tokens.shape[0],
            muvera_dim=muvera_fde.shape[0],
            sparse_terms=len(sparse_vector.indices),
        )

        return EncodingResult(
            colbert_tokens=colbert_tokens,
            muvera_fde=muvera_fde,
            sparse_vector=sparse_vector,
            content_hash=content_hash,
        )

    def encode_dense(self, text: str, entity_id: str) -> DenseEncodingResult:
        """Encode data into a single dense vector embedding.

        Args:
            text: Text to encode (skill name, job title, etc.)
            entity_id: Entity ID for logging

        Returns:
            DenseEncodingResult with dense embedding

        """
        content_hash = self._compute_content_hash(text)

        logger.debug("Encoding dense embedding", entity_id=entity_id)
        dense_embedding = self.dense.encode(text)

        logger.info(
            "Dense encoding completed",
            entity_id=entity_id,
            dense_dim=dense_embedding.shape[0],
            content_hash=content_hash,
        )

        return DenseEncodingResult(
            dense_embedding=dense_embedding,
            content_hash=content_hash,
        )

    def encode_dense_batch(
        self,
        texts: list[str],
        entity_ids: list[str],
        batch_size: int = 32,
    ) -> DenseBatchEncodingResult:
        """Encode multiple texts in one model forward pass.

        Delegates to DenseEncoder.encode_batch which passes the full list
        to the configured backend (DIRECT, ONNX, TEI) for native batching,
        avoiding N sequential model invocations.

        Args:
            texts: Input texts to encode, parallel to entity_ids.
            entity_ids: Corresponding entity IDs (parallel list, for logging).
            batch_size: Inference batch size forwarded to the encoder.

        Returns:
            DenseBatchEncodingResult with shape ``(n, dim)`` dense embeddings
            and per-item SHA-256 content hashes, in input order.

        Raises:
            ValueError: If texts and entity_ids have different lengths or texts is empty.

        """
        if len(texts) != len(entity_ids):
            msg = f"texts ({len(texts)}) and entity_ids ({len(entity_ids)}) must have equal length"
            raise ValueError(msg)
        if not texts:
            msg = "texts must be non-empty"
            raise ValueError(msg)

        content_hashes = [self._compute_content_hash(t) for t in texts]

        logger.debug(
            "Batch dense encoding started",
            n_texts=len(texts),
            entity_ids_sample=entity_ids[:3],
        )
        dense_embeddings = self.dense.encode_batch(texts, batch_size=batch_size)
        logger.info(
            "Batch dense encoding completed",
            n_texts=len(texts),
            dense_dim=dense_embeddings.shape[-1],
        )

        return DenseBatchEncodingResult(
            dense_embeddings=dense_embeddings,
            content_hashes=content_hashes,
        )

    def _compute_content_hash(self, text: str) -> str:
        """Compute SHA-256 hash of normalized content."""
        normalized = text.strip().lower()
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
