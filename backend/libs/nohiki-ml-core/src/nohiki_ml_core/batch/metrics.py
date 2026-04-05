"""OTel observability for PLAID index health.

OpenTelemetry metrics for tracking PLAID index codebook health,
particularly the staleness that occurs after add_documents() calls. FastPlaid's update()
does not recompute centroids, so new tokens that fall far from existing centroids degrade
IVF recall silently.

Since get_documents_embeddings() raises NotImplementedError on FastPlaid (embeddings are
stored in compressed/quantized form), the cluster threshold baseline must be established
from raw token arrays during build() before they are handed to PyLate for compression.

Metrics:
    nohiki_plaid_cluster_threshold: 75th percentile L2 residual norm at build time.
        Rising values after add_documents() indicate codebook staleness.
    nohiki_plaid_docs_since_rebuild_total: Documents added since last full build().
    nohiki_plaid_rebuilds_total: Total full index rebuilds (build() calls).
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

from opentelemetry import metrics

if TYPE_CHECKING:
    from nohiki_ml_core.batch.plaid_index import PLAIDIndex


class PLAIDIndexMetrics:
    """Observable metrics for PLAID index health.

    Uses OTel observable gauges with callbacks that read state from a registered
    PLAIDIndex instance. The counter (rebuilds_total) is synchronous.

    Attributes:
        rebuilds_total: Counter for full index rebuilds.

    """

    def __init__(self) -> None:
        """Initialize PLAID index metrics with OTel meter."""
        self._meter = metrics.get_meter("nohiki.plaid_index")
        self._index: PLAIDIndex | None = None

        self._meter.create_observable_gauge(
            "nohiki_plaid_cluster_threshold",
            callbacks=[self._observe_cluster_threshold],
            description=(
                "75th percentile L2 residual norm of token-to-centroid distance at "
                "PLAID build time. Rising values after add_documents() indicate "
                "codebook staleness and degraded IVF recall."
            ),
            unit="1",
        )

        self._meter.create_observable_gauge(
            "nohiki_plaid_docs_since_rebuild_total",
            callbacks=[self._observe_docs_since_rebuild],
            description=(
                "Documents added via add_documents() since the last full build(). "
                "fast-plaid update() does not recompute centroids."
            ),
            unit="1",
        )

        self.rebuilds_total = self._meter.create_counter(
            "nohiki_plaid_rebuilds_total",
            description="Full PLAID index rebuilds (build() calls that initialize a new corpus).",
            unit="1",
        )

    def register_index(self, index: PLAIDIndex) -> None:
        """Link metrics to a specific PLAIDIndex instance.

        Args:
            index: The PLAIDIndex instance to observe.

        """
        self._index = index

    def _observe_cluster_threshold(self, _options: metrics.CallbackOptions) -> list[metrics.Observation]:
        """Callback for cluster_threshold observable gauge."""
        if self._index is None or self._index.cluster_threshold_baseline is None:
            return []
        return [
            metrics.Observation(
                self._index.cluster_threshold_baseline,
                {"index_name": self._index.config.index_name},
            )
        ]

    def _observe_docs_since_rebuild(self, _options: metrics.CallbackOptions) -> list[metrics.Observation]:
        """Callback for docs_since_rebuild observable gauge."""
        if self._index is None:
            return []
        return [
            metrics.Observation(
                self._index.docs_since_rebuild,
                {"index_name": self._index.config.index_name},
            )
        ]


@lru_cache(maxsize=1)
def get_plaid_metrics() -> PLAIDIndexMetrics:
    """Return singleton PLAIDIndexMetrics instance.

    Returns:
        The shared PLAIDIndexMetrics instance.

    """
    return PLAIDIndexMetrics()
