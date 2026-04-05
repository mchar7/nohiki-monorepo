"""PyLate PLAID index for batch ColBERT retrieval.

Batch scoring capabilities using PyLate's FastPLAID index,
which is optimized for offline batch processing scenarios like:
- Nightly re-scoring of all profiles against all jobs
- Batch similarity computation for recommendations
- Offline index building and maintenance

Benefits over online Qdrant search:
- 5x+ faster retrieval for batch scenarios
- Optimized for throughput over latency
- Local index without network overhead

Usage:
    config = PLAIDIndexConfig(
        index_folder="/data/plaid-indexes",
        index_name="jobs_v1",
    )

    # Build index from documents
    index = PLAIDIndex(config)
    index.build(document_ids, document_embeddings)

    # Batch retrieval
    retriever = PLAIDRetriever(index)
    results = retriever.retrieve_batch(query_embeddings, k=100)
"""

from __future__ import annotations

import dataclasses
import importlib
import math
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Protocol, cast

import numpy as np
from nohiki_observability import get_logger

from nohiki_ml_core._deps import get_minibatch_kmeans, require_pylate
from nohiki_ml_core.batch.metrics import get_plaid_metrics

logger = get_logger(__name__)

_MIN_DOCS_FOR_CLUSTER_METRICS: int = 50
"""Minimum corpus size for statistically meaningful cluster threshold computation."""

_MIN_TOKENS_FOR_KMEANS: int = 2
"""Minimum tokens required for k-means clustering (need at least 2 points)."""

_DEFAULT_CLUSTER_SAMPLE_SIZE: int = 8000
"""Default max tokens to sample for k-means cluster threshold computation."""

_DEFAULT_RANDOM_SEED: int = 42
"""Default random seed for reproducible cluster threshold computation."""


def _compute_k_from_tokens(total_tokens: int) -> int:
    """Compute number of k-means centroids using NextPlaid's heuristic.

    Formula from NextPlaid kmeans.rs:271:
        K = 2^floor(log2(16 * sqrt(total_tokens)))

    Args:
        total_tokens: Total number of token embeddings in the corpus.

    Returns:
        Number of centroids K, clamped to [1, total_tokens - 1].

    """
    if total_tokens < 1:
        return 1
    inner = 16.0 * math.sqrt(total_tokens)
    k = 2 ** math.floor(math.log2(inner))
    return max(1, min(k, total_tokens - 1))


class PLAIDIndexProtocol(Protocol):
    """Protocol for PyLate PLAID index."""

    def add_documents(
        self,
        *,
        documents_ids: list[str],
        documents_embeddings: list[list[list[float]]],
    ) -> None:
        """Add documents to the index."""


class ColBERTRetrieverProtocol(Protocol):
    """Protocol for PyLate ColBERT retriever."""

    def retrieve(
        self,
        *,
        queries_embeddings: list[list[list[float]]],
        k: int,
        subset: list[str] | None = None,
    ) -> list[list[dict[str, float | int | str]]]:
        """Retrieve top-k documents for each query embedding.

        Args:
            queries_embeddings: List of query token arrays.
            k: Number of results per query.
            subset: If provided, restricts IVF search to only these document IDs.
                Uses fast-plaid's native subset filtering applied uniformly across
                all queries.

        """


def _load_plaid_index_class(module: ModuleType) -> type[PLAIDIndexProtocol]:
    return cast(type[PLAIDIndexProtocol], module.PLAID)


def _load_colbert_retriever_class(module: ModuleType) -> type[ColBERTRetrieverProtocol]:
    return cast(type[ColBERTRetrieverProtocol], module.ColBERT)


@dataclass(frozen=True, slots=True)
class PLAIDIndexConfig:
    """Configuration for PLAID index.

    Attributes:
        index_folder: Directory containing PLAID indexes.
        index_name: Name of this specific index.
        override: If True, overwrite existing index on build.
        kmeans_niters: Number of k-means iterations during index build.
        nbits: Number of bits for residual quantization.
        n_ivf_probe: IVF cells probed per query. Default 8 is adequate for corpora
            under 50K docs. Increase to 16-32 at 100K+ to maintain recall.
        n_full_scores: Candidate pool size for exact MaxSim rescoring after IVF
            retrieval. Higher values improve recall at the cost of latency.
        max_points_per_centroid: Maximum token embeddings assigned to a single
            centroid during k-means. Caps cluster imbalance.

    """

    index_folder: str
    index_name: str
    override: bool = False
    kmeans_niters: int = 4
    nbits: int = 2
    n_ivf_probe: int = 8
    n_full_scores: int = 8192
    max_points_per_centroid: int = 256


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    """Single retrieval result from PLAID search."""

    document_id: str
    score: float


@dataclass(slots=True)
class PLAIDIndex:
    """PLAID index wrapper for batch ColBERT retrieval.

    Provides a clean interface over PyLate's PLAID index with:
    - Lazy loading of pylate dependencies
    - Index persistence and reloading
    - Batch document indexing
    - Codebook health metrics for monitoring IVF recall degradation
    """

    config: PLAIDIndexConfig
    _index: PLAIDIndexProtocol | None = field(default=None, init=False, repr=False)
    _total_docs: int = field(default=0, init=False, repr=False)
    _docs_since_rebuild: int = field(default=0, init=False, repr=False)
    _cluster_threshold_baseline: float | None = field(default=None, init=False, repr=False)

    @property
    def total_docs(self) -> int:
        """Total documents in the index."""
        return self._total_docs

    @property
    def docs_since_rebuild(self) -> int:
        """Documents added since last full build."""
        return self._docs_since_rebuild

    @property
    def cluster_threshold_baseline(self) -> float | None:
        """75th percentile L2 residual norm at build time, or None if not computed."""
        return self._cluster_threshold_baseline

    def _update_state_after_build(self, num_documents: int) -> None:
        """Reset state tracking fields after a full build."""
        self._total_docs = num_documents
        self._docs_since_rebuild = 0
        self._cluster_threshold_baseline = None

    def _emit_build_metrics(self, document_embeddings: list[np.ndarray]) -> None:
        """Compute cluster threshold and emit metrics if corpus is large enough."""
        if self._total_docs < _MIN_DOCS_FOR_CLUSTER_METRICS:
            logger.debug(
                "PLAID cluster metrics skipped (corpus too small)",
                num_documents=self._total_docs,
                min_required=_MIN_DOCS_FOR_CLUSTER_METRICS,
            )
            return

        threshold = self.compute_cluster_threshold(document_embeddings)
        self._cluster_threshold_baseline = threshold

        metrics = get_plaid_metrics()
        metrics.register_index(self)
        metrics.rebuilds_total.add(1, {"index_name": self.config.index_name})

        logger.info(
            "PLAID cluster health baseline recorded",
            cluster_threshold=threshold,
            index_name=self.config.index_name,
        )

    def ensure_index(self) -> PLAIDIndexProtocol:
        """Lazy-load PLAID index on first use.

        Raises:
            MissingLocalDependencyError: If pylate is not installed

        """
        if self._index is None:
            require_pylate("PLAID index")

            indexes_module = importlib.import_module("pylate.indexes")
            index_class = _load_plaid_index_class(indexes_module)
            self._index = index_class(
                index_folder=self.config.index_folder,
                index_name=self.config.index_name,
                override=self.config.override,
                kmeans_niters=self.config.kmeans_niters,
                nbits=self.config.nbits,
                n_ivf_probe=self.config.n_ivf_probe,
                n_full_scores=self.config.n_full_scores,
                max_points_per_centroid=self.config.max_points_per_centroid,
            )

            logger.info(
                "PLAID index initialized",
                index_folder=self.config.index_folder,
                index_name=self.config.index_name,
                override=self.config.override,
            )

        return self._index

    def build(
        self,
        document_ids: list[str],
        document_embeddings: list[np.ndarray],
    ) -> None:
        """Build index from document embeddings.

        Args:
            document_ids: List of document identifiers
            document_embeddings: List of ColBERT token arrays,
                each of shape (num_tokens, token_dim)

        Raises:
            ValueError: If document_ids and embeddings have different lengths

        """
        if len(document_ids) != len(document_embeddings):
            msg = f"Mismatched lengths: {len(document_ids)} document_ids vs {len(document_embeddings)} embeddings"
            raise ValueError(msg)

        index = self.ensure_index()

        embeddings_list = [emb.tolist() for emb in document_embeddings]

        try:
            index.add_documents(
                documents_ids=document_ids,
                documents_embeddings=embeddings_list,
            )

            self._update_state_after_build(len(document_ids))
            self._emit_build_metrics(document_embeddings)

            logger.info(
                "PLAID index built",
                num_documents=len(document_ids),
                index_name=self.config.index_name,
            )
        except Exception:
            logger.exception(
                "Failed to build PLAID index",
                num_documents=len(document_ids),
            )
            raise

    def add_documents(
        self,
        document_ids: list[str],
        document_embeddings: list[np.ndarray],
    ) -> None:
        """Add documents to existing index (incremental update).

        Args:
            document_ids: List of document identifiers
            document_embeddings: List of ColBERT token arrays

        """
        if len(document_ids) != len(document_embeddings):
            msg = f"Mismatched lengths: {len(document_ids)} document_ids vs {len(document_embeddings)} embeddings"
            raise ValueError(msg)

        index = self.ensure_index()

        embeddings_list = [emb.tolist() for emb in document_embeddings]

        try:
            index.add_documents(
                documents_ids=document_ids,
                documents_embeddings=embeddings_list,
            )

            self._total_docs += len(document_ids)
            self._docs_since_rebuild += len(document_ids)

            # Register with metrics in case this index was loaded from disk rather
            # than built in this process: build() handles registration for new indexes.
            metrics = get_plaid_metrics()
            metrics.register_index(self)

            logger.warning(
                "PLAID incremental update: centroids not recomputed",
                docs_since_rebuild=self._docs_since_rebuild,
                total_docs=self._total_docs,
                index_name=self.config.index_name,
            )

            logger.debug(
                "Documents added to PLAID index",
                num_documents=len(document_ids),
            )
        except Exception:
            logger.exception(
                "Failed to add documents to PLAID index",
                num_documents=len(document_ids),
            )
            raise

    @property
    def index_path(self) -> Path:
        """Get the path to the index folder."""
        return Path(self.config.index_folder) / self.config.index_name

    def exists(self) -> bool:
        """Check if index exists on disk."""
        return self.index_path.exists()

    @classmethod
    def load(cls, config: PLAIDIndexConfig) -> PLAIDIndex:
        """Load existing index from disk.

        Args:
            config: Index configuration (must have override=False)

        Returns:
            Loaded PLAIDIndex instance

        Raises:
            FileNotFoundError: If index doesn't exist

        """
        load_config = dataclasses.replace(config, override=False)

        index = cls(config=load_config)

        if not index.exists():
            msg = f"Index not found at {index.index_path}"
            raise FileNotFoundError(msg)

        index.ensure_index()

        logger.info(
            "PLAID index loaded from disk",
            index_path=str(index.index_path),
        )

        return index

    @staticmethod
    def compute_cluster_threshold(
        token_arrays: list[np.ndarray],
        sample_size: int = _DEFAULT_CLUSTER_SAMPLE_SIZE,
        seed: int = _DEFAULT_RANDOM_SEED,
    ) -> float:
        """Compute 75th percentile L2 residual norm for cluster health baseline.

        Must be called before tokens are passed to PyLate since FastPlaid's
        get_documents_embeddings() raises NotImplementedError post-build.
        Aligns with NextPlaid's cluster_threshold.npy semantics.

        Args:
            token_arrays: List of ColBERT token arrays, each shape (n_tokens, dim).
            sample_size: Max tokens to sample for k-means. Defaults to 8000.
            seed: Random seed for reproducibility.

        Returns:
            75th percentile of L2 norms of token-to-centroid residuals.

        Raises:
            MissingLocalDependencyError: If scikit-learn is not installed.

        """
        minibatch_kmeans_cls = get_minibatch_kmeans("PLAID cluster threshold computation")

        all_tokens: np.ndarray = np.vstack(token_arrays).astype(np.float32)
        total_tokens = len(all_tokens)

        if total_tokens < _MIN_TOKENS_FOR_KMEANS:
            return 0.0

        rng = np.random.default_rng(seed)
        if total_tokens > sample_size:
            idx = rng.choice(total_tokens, sample_size, replace=False)
            all_tokens = all_tokens[idx]

        # K is derived from the full corpus size so it approximates the production
        # PLAID index's centroid granularity, making the threshold comparable across builds.
        # Clamp to the actual sample size when sampling was applied: KMeans requires
        # n_samples >= n_clusters.
        k = min(_compute_k_from_tokens(total_tokens), max(1, len(all_tokens) - 1))
        km = minibatch_kmeans_cls(n_clusters=k, n_init=1, random_state=seed)
        km.fit(all_tokens)

        nearest_centroids = km.cluster_centers_[km.labels_]
        residuals = all_tokens - nearest_centroids
        norms = np.linalg.norm(residuals, axis=1)

        return float(np.percentile(norms, 75))


@dataclass(slots=True)
class PLAIDRetriever:
    """Batch retriever using PLAID index.

    Provides efficient batch retrieval for offline scoring scenarios.
    """

    index: PLAIDIndex
    _retriever: ColBERTRetrieverProtocol | None = field(default=None, init=False, repr=False)

    def _ensure_retriever(self) -> ColBERTRetrieverProtocol:
        """Lazy-load retriever on first use.

        Raises:
            MissingLocalDependencyError: If pylate is not installed

        """
        if self._retriever is not None:
            return self._retriever

        require_pylate("PLAID retriever")

        plaid_index = self.index.ensure_index()
        retrieve_module = importlib.import_module("pylate.retrieve")
        retriever_class = _load_colbert_retriever_class(retrieve_module)
        self._retriever = retriever_class(index=plaid_index)

        logger.info("PLAID retriever ready")

        return self._retriever

    def retrieve(
        self,
        query_embeddings: np.ndarray,
        k: int = 100,
        subset: list[str] | None = None,
    ) -> list[RetrievalResult]:
        """Retrieve top-k documents for a single query.

        Args:
            query_embeddings: Query ColBERT tokens of shape (num_tokens, token_dim)
            k: Number of results to return
            subset: If provided, restricts IVF search to only these document IDs.
                Uses fast-plaid's native subset filtering.

        Returns:
            List of RetrievalResult sorted by score descending

        """
        results = self.retrieve_batch([query_embeddings], k=k, subset=subset)
        return results[0] if results else []

    def retrieve_batch(
        self,
        queries_embeddings: list[np.ndarray],
        k: int = 100,
        subset: list[str] | None = None,
    ) -> list[list[RetrievalResult]]:
        """Retrieve top-k documents for multiple queries (batch).

        This is the primary method for batch scoring scenarios.

        Args:
            queries_embeddings: List of query ColBERT token arrays,
                each of shape (num_tokens, token_dim)
            k: Number of results per query
            subset: If provided, restricts IVF search to only these document IDs.
                Uses fast-plaid's native subset filtering applied uniformly across
                all queries.

        Returns:
            List of result lists, one per query

        """
        if not queries_embeddings:
            return []

        retriever = self._ensure_retriever()

        embeddings_list = [emb.tolist() for emb in queries_embeddings]

        try:
            raw_results = retriever.retrieve(
                queries_embeddings=embeddings_list,
                k=k,
                subset=subset,
            )

            results: list[list[RetrievalResult]] = []
            for query_results in raw_results:
                parsed = [
                    RetrievalResult(
                        document_id=str(r["id"]),
                        score=float(r["score"]),
                    )
                    for r in query_results
                ]
                results.append(parsed)

            logger.debug(
                "Batch retrieval completed",
                num_queries=len(queries_embeddings),
                k=k,
                total_results=sum(len(r) for r in results),
            )
        except Exception:
            logger.exception(
                "Batch retrieval failed",
                num_queries=len(queries_embeddings),
                k=k,
            )
            raise
        else:
            return results

    def score_pairs(
        self,
        query_embeddings: list[np.ndarray],
        document_ids: list[str],
    ) -> list[list[tuple[str, float]]]:
        """Score specific query-document pairs.

        Passes document_ids as the IVF subset so only those cells are probed,
        computing exact MaxSim scores for exactly the requested documents.
        Eliminates the 10x over-fetch heuristic.

        Args:
            query_embeddings: List of query ColBERT token arrays
            document_ids: List of document IDs to score against each query

        Returns:
            List of (document_id, score) tuples for each query. The subset
            parameter guarantees only the requested documents are returned;
            the post-filter is a safety guard against any future API changes.

        """
        document_id_set = frozenset(document_ids)

        all_results = self.retrieve_batch(query_embeddings, k=len(document_ids), subset=document_ids)

        filtered_results: list[list[tuple[str, float]]] = []
        for query_results in all_results:
            filtered = [(r.document_id, r.score) for r in query_results if r.document_id in document_id_set]
            filtered_results.append(filtered)

        return filtered_results
