"""Sparse vector encoder using sparse encoding via fastembed."""

import math
from dataclasses import dataclass
from typing import Protocol, cast

from nohiki_ml_manifest import SemanticRepresentationManifest
from nohiki_observability import get_logger

from nohiki_ml_core import _deps

_FASTEMBED_MODULE = "fastembed"


class _SupportsToList[T](Protocol):
    """Protocol for array-like objects with tolist support."""

    def tolist(self) -> list[T]:
        """Convert array-like content to a list."""


class SparseEmbedding(Protocol):
    """Protocol for fastembed sparse embedding output."""

    indices: _SupportsToList[int]
    values: _SupportsToList[float]


class SparseTextEmbedding(Protocol):
    """Protocol for fastembed SparseTextEmbedding."""

    def embed(self, texts: list[str]) -> list[SparseEmbedding]:
        """Generate sparse embeddings for a batch of texts."""


def _load_sparse_embedding_class(module: object, attr_name: str) -> type[SparseTextEmbedding]:
    return cast("type[SparseTextEmbedding]", getattr(module, attr_name))


logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class SparseVector:
    """Sparse vector representation."""

    indices: list[int]
    values: list[float]

    def __post_init__(self) -> None:
        """Reject malformed sparse geometry before scoring or persistence."""
        if len(self.indices) != len(self.values):
            msg = "Sparse indices and values must have equal lengths"
            raise ValueError(msg)
        if any(not isinstance(index, int) or isinstance(index, bool) or index < 0 for index in self.indices):
            msg = "Sparse indices must be non-negative integers"
            raise ValueError(msg)
        if len(set(self.indices)) != len(self.indices):
            msg = "Sparse indices must be unique"
            raise ValueError(msg)
        if not all(math.isfinite(value) for value in self.values):
            msg = "Sparse values must be finite"
            raise ValueError(msg)

    def dot_product(self, other: SparseVector) -> float:
        """Compute dot product with another sparse vector.

        Efficient O(n + m) algorithm using index intersection.

        Args:
            other: Another SparseVector to compute similarity with

        Returns:
            Dot product score (higher = more similar)

        """
        if not self.indices or not other.indices:
            return 0.0

        # Build index map for the smaller vector for efficiency
        if len(self.indices) <= len(other.indices):
            smaller_map = dict(zip(self.indices, self.values, strict=True))
            larger_indices, larger_values = other.indices, other.values
        else:
            smaller_map = dict(zip(other.indices, other.values, strict=True))
            larger_indices, larger_values = self.indices, self.values

        return sum(
            val * smaller_map[idx] for idx, val in zip(larger_indices, larger_values, strict=True) if idx in smaller_map
        )


class SparseEncoder:
    """Qdrant sparse vector encoder using fastembed.

    Uses learned sparse embeddings that significantly outperform BM25-style
    term frequency approaches.

    Note:
        Requires [inference] extra: uv pip install nohiki-ml-core[inference]
        This encoder always runs locally - no remote backend option.

    """

    def __init__(self, manifest: SemanticRepresentationManifest | None = None) -> None:
        """Initialize encoder with manifest.

        Args:
            manifest: Optional semantic representation configuration

        Raises:
            MissingLocalDependencyError: If fastembed is not installed

        """
        self.manifest = manifest
        self.model_id = manifest.sparse.model_id if manifest else "Qdrant/minicoil-v1"
        self.enabled = manifest.sparse.enabled if manifest else True
        self._model: SparseTextEmbedding | None = None

        # Validate fastembed is available upfront if encoding is enabled
        if self.enabled:
            _deps.require_fastembed("Sparse encoder", module_name=_FASTEMBED_MODULE)

        logger.info(
            "Sparse encoder initialized",
            enabled=self.enabled,
            model_id=self.model_id,
        )

    def _ensure_model(self) -> SparseTextEmbedding:
        """Lazy-load sparse model on first use.

        Returns:
            fastembed SparseTextEmbedding model instance

        Raises:
            RuntimeError: If model fails to load

        """
        if self._model is None:
            module = _deps.import_optional_module(
                _FASTEMBED_MODULE,
                _deps.LocalDependency.FASTEMBED,
                "Sparse encoder",
            )
            try:
                model_class = _load_sparse_embedding_class(module, "SparseTextEmbedding")
                self._model = model_class(model_name=self.model_id)
                logger.info("Sparse model loaded", model_id=self.model_id)
            except Exception as e:
                logger.exception("Failed to load sparse model")
                error_msg = f"Failed to load sparse model {self.model_id}: {e}"
                raise RuntimeError(error_msg) from e

        return self._model

    def encode(self, text: str) -> SparseVector:
        """Generate sparse vector from text using sparse encoding.

        Args:
            text: Text to encode

        Returns:
            SparseVector with indices and values

        """
        if not self.enabled:
            return SparseVector(indices=[], values=[])

        model = self._ensure_model()

        try:
            embeddings = list(model.embed([text]))
            if not embeddings:
                return SparseVector(indices=[], values=[])

            sparse_embedding = embeddings[0]
            indices = sparse_embedding.indices.tolist()
            values = sparse_embedding.values.tolist()

            logger.debug(
                "Sparse encoding completed",
                num_terms=len(indices),
            )
        except Exception:
            logger.exception("Sparse encoding failed", text_length=len(text))
            raise
        else:
            return SparseVector(indices=indices, values=values)

    @staticmethod
    def _validate_batch_count(actual: int, expected: int) -> None:
        if actual != expected:
            msg = f"Sparse encoder returned {actual} rows for {expected} texts"
            raise ValueError(msg)

    def encode_batch(self, texts: list[str]) -> list[SparseVector]:
        """Encode batch of texts using sparse encoding.

        Args:
            texts: List of texts to encode

        Returns:
            List of SparseVector instances

        """
        if not self.enabled:
            return [SparseVector(indices=[], values=[]) for _ in texts]

        if not texts:
            return []

        model = self._ensure_model()

        try:
            embeddings = list(model.embed(texts))
            self._validate_batch_count(len(embeddings), len(texts))

            results = []
            for sparse_embedding in embeddings:
                indices = sparse_embedding.indices.tolist()
                values = sparse_embedding.values.tolist()
                results.append(SparseVector(indices=indices, values=values))

            logger.debug(
                "Sparse batch encoding completed",
                num_texts=len(texts),
                total_terms=sum(len(r.indices) for r in results),
            )
        except Exception:
            logger.exception("Sparse batch encoding failed", num_texts=len(texts))
            raise
        else:
            return results

    def warm_up(self) -> None:
        """Pre-load the sparse model to avoid cold-start latency on first request."""
        if self.enabled:
            self._ensure_model()
            logger.info("Sparse model warmed up", model_id=self.model_id)
