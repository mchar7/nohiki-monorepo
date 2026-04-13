"""Listing scoring service."""

from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, Final

from nohiki.job.listing.v1 import ListingSnapshot
from nohiki.user.pref.v1 import SearchPrefSnapshot
from nohiki_common_exceptions import ExternalServiceError
from nohiki_observability import get_logger

if TYPE_CHECKING:
    from collections.abc import Mapping

    from job_correlation_evaluation_service.services.scoring.pipeline import (
        QueryEncoding,
        ScoringPipeline,
    )
    from job_correlation_evaluation_service.services.scoring.stages.deterministic_final import FactorAttribution

logger = get_logger(__name__)

type ScoreBreakdownValue = bool | float | int | str | None | dict[str, float]
type ScoreBreakdownDict = dict[str, ScoreBreakdownValue]


# Cap description length before lowercasing on the disqualification hot path:
# pathological HTML descriptions (>>8KB) otherwise dominate per-pair CPU when
# the same listing is scored against many profiles.
_JOB_TEXT_MAX_CHARS: Final[int] = 8192


def _get_cached_job_text(listing: ListingSnapshot) -> str:
    """Return lowercased ``title description company_name skills`` text for keyword scans.

    The same listing is scored against many profiles in a single backfill batch;
    rebuilding and lowercasing the (potentially multi-KB) description per pair
    is wasted CPU. Cache on the listing instance so the cost is paid once per
    listing per scoring run.
    """
    cached = getattr(listing, "_cached_job_text", None)
    if isinstance(cached, str):
        return cached
    text = f"{listing.title} {listing.description} {listing.company_name} {' '.join(listing.required_skills)}".lower()
    if len(text) > _JOB_TEXT_MAX_CHARS:
        text = text[:_JOB_TEXT_MAX_CHARS]
    # Slotted / proxy listing types may reject attribute injection; falling
    # back to recomputation is safe but rarely hit in practice.
    with contextlib.suppress(AttributeError, TypeError):
        object.__setattr__(listing, "_cached_job_text", text)
    return text


@lru_cache(maxsize=256)
def _compile_disallowed_pattern(keywords_tuple: tuple[str, ...]) -> re.Pattern[str]:
    """Compile and cache regex pattern for disallowed keyword detection.

    Uses single-pass regex instead of O(k*n) sequential substring checks.

    Args:
        keywords_tuple: Tuple of disallowed keywords.

    Returns:
        Compiled regex pattern for substring matching.

    """
    escaped = [re.escape(kw.lower()) for kw in keywords_tuple]
    return re.compile("|".join(escaped), re.IGNORECASE)


class MLScoringServiceError(ExternalServiceError):
    """Raised when ML scoring fails.

    Inherits ExternalServiceError because ML inference is treated as an
    external dependency: failures are typically transient (model load,
    pipeline IO, downstream gateway timeouts) and benefit from exponential
    backoff retry semantics.
    """

    def __init__(self, reason: str) -> None:
        """Initialize with failure reason."""
        self.reason = reason
        super().__init__(message=reason, service_name="ml-scoring", operation="score")


@dataclass(frozen=True, slots=True)
class MLScoringResult:
    """Result of ML-based scoring for a job-profile pair."""

    score: int
    is_disqualified: bool
    disqualification_reason: str | None
    feature_vector: tuple[float, ...] | None = None
    role_relevance_raw: float = 0.0
    ranking_index: float = 0.0
    factors: tuple[FactorAttribution, ...] = ()
    listing_id: str | None = None


class MLScoringService:
    """ML-based scoring service integrating the 4-stage pipeline.

    This service wraps the ScoringPipeline and provides a high-level
    interface for scoring job-profile pairs using the ML pipeline.

    Pipeline Stages:
        Stage 1: MUVERA ANN (Qdrant hybrid search)
        Stage 2: MaxSim Rerank (ColBERT late-interaction)
        Stage 3: LLM Rerank (optional, external)
        Stage 4: L2R Final (LightGBM)

    Usage:
        >>> service = MLScoringService(pipeline)
        >>> service.initialize()
        >>> result = service.score_with_inline_embeddings(job, profile, query_encoding)
        >>> print(f"Score: {result.score}, Confidence: {result.confidence}")

    """

    def __init__(self, pipeline: ScoringPipeline) -> None:
        """Initialize ML scoring service.

        Args:
            pipeline: ScoringPipeline instance (not yet initialized)

        """
        self._pipeline = pipeline
        self._initialized = False

    @property
    def is_initialized(self) -> bool:
        """Check if service is initialized."""
        return self._initialized

    def initialize(self) -> None:
        """Initialize service (load models).

        This must be called before any scoring operations.
        Typically called during application startup in the lifespan handler.
        """
        if self._initialized:
            logger.warning("MLScoringService already running")
            return

        logger.info("Starting MLScoringService")
        self._initialized = True
        logger.info("MLScoringService ready")

    def _check_disqualification(
        self,
        job: ListingSnapshot,
        profile: SearchPrefSnapshot,
    ) -> tuple[bool, str | None]:
        """Check if job should be disqualified based on profile criteria.

        Uses cached compiled regex for O(n) single-pass matching instead of
        O(k*n) sequential substring checks per keyword.

        Args:
            job: Job listing to check
            profile: Profile with disallowed keywords

        Returns:
            Tuple of (is_disqualified, reason)

        """
        if not profile.disallowed_keywords:
            return False, None

        keywords_tuple = tuple(profile.disallowed_keywords)
        pattern = _compile_disallowed_pattern(keywords_tuple)
        job_text = _get_cached_job_text(job)

        match = pattern.search(job_text)
        if match:
            return True, f"Contains disallowed keyword: {match.group()}"

        return False, None

    async def score_listings_batch(
        self,
        listings: Mapping[str, ListingSnapshot],
        profile: SearchPrefSnapshot,
        query_encoding: QueryEncoding,
    ) -> list[MLScoringResult]:
        """Score multiple listings against a profile with embedding similarity.

        Used for backfill: receives pre-computed query encoding, then
        runs L2R scoring via embedding similarity.

        Args:
            listings: Dict mapping entity_id to ListingSnapshot
            profile: User search preferences
            query_encoding: Pre-computed query encoding from EmbeddingCompleted event

        Returns:
            List of MLScoringResult for each listing

        Raises:
            MLScoringServiceError: If scoring fails

        """
        if not self._initialized:
            msg = "Service not initialized"
            raise MLScoringServiceError(msg)

        if not listings:
            return []

        scored_candidates = await self._pipeline.score_listings_by_ids(
            query_encoding=query_encoding,
            profile=profile,
            listings=listings,
        )

        return [
            MLScoringResult(
                score=candidate.final_score,
                is_disqualified=False,
                disqualification_reason=None,
                listing_id=candidate.entity_id,
                feature_vector=candidate.feature_vector,
                role_relevance_raw=(
                    candidate.role_relevance_raw
                    if candidate.role_relevance_raw is not None
                    else 100.0 * candidate.maxsim_score
                ),
                ranking_index=candidate.rank_index,
                factors=candidate.factor_attributions,
            )
            for candidate in scored_candidates
        ]

    def extract_query_encoding_from_snapshot(
        self,
        profile: SearchPrefSnapshot,
    ) -> QueryEncoding | None:
        """Extract QueryEncoding from ECST snapshot's query_artifacts.

        Args:
            profile: SearchPrefSnapshot with query_artifacts populated.

        Returns:
            QueryEncoding if artifacts are present, None otherwise.

        """
        if not self._initialized:
            return None
        return self._pipeline.extract_query_encoding_from_snapshot(profile)

    def score_with_inline_embeddings(
        self,
        listing: ListingSnapshot,
        profile: SearchPrefSnapshot,
        query_encoding: QueryEncoding,
    ) -> MLScoringResult:
        """Score a listing using inline embedding artifacts.

        Args:
            listing: Listing with embedding_artifacts populated
            profile: User search preferences
            query_encoding: Profile's query encoding

        Returns:
            MLScoringResult with real MaxSim score

        """
        if not self._initialized:
            msg = "Service not initialized"
            raise MLScoringServiceError(msg)

        disqualified, reason = self._check_disqualification(listing, profile)
        if disqualified:
            return MLScoringResult(
                score=0,
                is_disqualified=True,
                disqualification_reason=reason,
            )

        result = self._pipeline.score_with_inline_embeddings(
            listing=listing,
            profile=profile,
            query_encoding=query_encoding,
        )

        return MLScoringResult(
            score=result.final_score,
            is_disqualified=False,
            disqualification_reason=None,
            feature_vector=result.feature_vector,
            role_relevance_raw=(
                result.role_relevance_raw if result.role_relevance_raw is not None else 100.0 * result.maxsim_score
            ),
            ranking_index=result.rank_index,
            factors=result.factor_attributions,
        )

    async def close(self) -> None:
        """Close service resources."""
        if self._pipeline:
            await self._pipeline.close()
