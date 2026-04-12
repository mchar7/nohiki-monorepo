"""Skill canonicalization metrics for job-correlation-evaluation-service.

Instruments the skill canonicalization pipeline with counters and histograms
for processed skills, cache hit rates, batch operations, and feature extraction.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from nohiki_observability.metrics.builders import DomainMetricsBase, MetricDefinition
from opentelemetry.metrics import Counter, Histogram


@dataclass(frozen=True, slots=True)
class BatchCanonicalizationResult:
    """Result metrics from a batch canonicalization operation."""

    batch_size: int
    duration_seconds: float
    matched_count: int
    new_skill_count: int
    needs_review_count: int
    failed_count: int


DEFINITIONS = [
    MetricDefinition(
        "nohiki_skill_canonicalization_processed_total",
        "Skills processed through canonicalization pipeline",
        "1",
        "counter",
    ),
    MetricDefinition(
        "nohiki_skill_canonicalization_cache_hits_total",
        "Cache hits during skill canonicalization",
        "1",
        "counter",
    ),
    MetricDefinition(
        "nohiki_skill_canonicalization_cache_misses_total",
        "Cache misses during skill canonicalization",
        "1",
        "counter",
    ),
    MetricDefinition(
        "nohiki_skill_canonicalization_duration_seconds",
        "Skill canonicalization latency",
        "s",
        "histogram",
    ),
    MetricDefinition(
        "nohiki_skill_canonicalization_errors_total",
        "Skill canonicalization errors",
        "1",
        "counter",
    ),
    MetricDefinition(
        "nohiki_feature_extraction_duration_seconds",
        "Feature extraction latency",
        "s",
        "histogram",
    ),
    MetricDefinition(
        "nohiki_skill_batch_canonicalization_total",
        "Batch canonicalization operations",
        "1",
        "counter",
    ),
    MetricDefinition(
        "nohiki_skill_batch_duration_seconds",
        "Batch canonicalization latency",
        "s",
        "histogram",
    ),
    MetricDefinition(
        "nohiki_skill_batch_matched_total",
        "Skills matched in batch canonicalization",
        "1",
        "counter",
    ),
    MetricDefinition(
        "nohiki_skill_batch_new_total",
        "New skills created in batch canonicalization",
        "1",
        "counter",
    ),
    MetricDefinition(
        "nohiki_skill_batch_review_total",
        "Skills needing review in batch canonicalization",
        "1",
        "counter",
    ),
    MetricDefinition(
        "nohiki_skill_batch_failed_total",
        "Failed skills in batch canonicalization",
        "1",
        "counter",
    ),
]


class SkillCanonicalizationMetrics(DomainMetricsBase):
    """Skill pipeline metrics for canonicalization and feature extraction."""

    def __init__(self) -> None:
        """Initialize skill canonicalization metrics."""
        super().__init__("nohiki.skill_canonicalization", DEFINITIONS)

    @property
    def skills_processed(self) -> Counter:
        """Counter for skills processed."""
        return self._get_counter("nohiki_skill_canonicalization_processed_total")

    @skills_processed.setter
    def skills_processed(self, value: object) -> None:
        """Set skills_processed counter (for testing)."""
        self._instruments["nohiki_skill_canonicalization_processed_total"] = value

    @property
    def cache_hits(self) -> Counter:
        """Counter for cache hits."""
        return self._get_counter("nohiki_skill_canonicalization_cache_hits_total")

    @cache_hits.setter
    def cache_hits(self, value: object) -> None:
        """Set cache_hits counter (for testing)."""
        self._instruments["nohiki_skill_canonicalization_cache_hits_total"] = value

    @property
    def cache_misses(self) -> Counter:
        """Counter for cache misses."""
        return self._get_counter("nohiki_skill_canonicalization_cache_misses_total")

    @cache_misses.setter
    def cache_misses(self, value: object) -> None:
        """Set cache_misses counter (for testing)."""
        self._instruments["nohiki_skill_canonicalization_cache_misses_total"] = value

    @property
    def latency(self) -> Histogram:
        """Histogram for skill canonicalization latency."""
        return self._get_histogram("nohiki_skill_canonicalization_duration_seconds")

    @latency.setter
    def latency(self, value: object) -> None:
        """Set latency histogram (for testing)."""
        self._instruments["nohiki_skill_canonicalization_duration_seconds"] = value

    @property
    def errors(self) -> Counter:
        """Counter for skill canonicalization errors."""
        return self._get_counter("nohiki_skill_canonicalization_errors_total")

    @errors.setter
    def errors(self, value: object) -> None:
        """Set errors counter (for testing)."""
        self._instruments["nohiki_skill_canonicalization_errors_total"] = value

    @property
    def feature_extraction_latency(self) -> Histogram:
        """Histogram for feature extraction latency."""
        return self._get_histogram("nohiki_feature_extraction_duration_seconds")

    @feature_extraction_latency.setter
    def feature_extraction_latency(self, value: object) -> None:
        """Set feature_extraction_latency histogram (for testing)."""
        self._instruments["nohiki_feature_extraction_duration_seconds"] = value

    def record_skill_processed(
        self,
        stage: str,
        duration_seconds: float,
        *,
        cache_hit: bool = False,
        success: bool = True,
    ) -> None:
        """Record a skill processing operation."""
        attrs = {"stage": stage, "status": "success" if success else "error"}

        self._get_counter("nohiki_skill_canonicalization_processed_total").add(1, attrs)
        self._get_histogram("nohiki_skill_canonicalization_duration_seconds").record(duration_seconds, attrs)

        if cache_hit:
            self._get_counter("nohiki_skill_canonicalization_cache_hits_total").add(1, attrs)
        else:
            self._get_counter("nohiki_skill_canonicalization_cache_misses_total").add(1, attrs)

        if not success:
            self._get_counter("nohiki_skill_canonicalization_errors_total").add(1, attrs)

    def record_feature_extraction(
        self,
        duration_seconds: float,
        *,
        success: bool = True,
    ) -> None:
        """Record a feature extraction operation."""
        attrs = {"status": "success" if success else "error"}
        self._get_histogram("nohiki_feature_extraction_duration_seconds").record(duration_seconds, attrs)

        if not success:
            self._get_counter("nohiki_skill_canonicalization_errors_total").add(1, {"operation": "feature_extraction"})

    def record_batch_canonicalization(self, result: BatchCanonicalizationResult) -> None:
        """Record batch canonicalization metrics."""
        self._get_counter("nohiki_skill_batch_canonicalization_total").add(1, {"batch_size": str(result.batch_size)})
        self._get_histogram("nohiki_skill_batch_duration_seconds").record(result.duration_seconds)
        self._get_counter("nohiki_skill_batch_matched_total").add(result.matched_count)
        self._get_counter("nohiki_skill_batch_new_total").add(result.new_skill_count)
        self._get_counter("nohiki_skill_batch_review_total").add(result.needs_review_count)
        self._get_counter("nohiki_skill_batch_failed_total").add(result.failed_count)


@lru_cache(maxsize=1)
def get_skill_canonicalization_metrics() -> SkillCanonicalizationMetrics:
    """Get singleton SkillCanonicalizationMetrics instance."""
    return SkillCanonicalizationMetrics()
