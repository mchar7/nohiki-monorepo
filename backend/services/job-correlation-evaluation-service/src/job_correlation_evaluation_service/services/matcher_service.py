"""Service for matching jobs to user preferences using ECST and PostgreSQL projections."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from nohiki_common_exceptions import DataNotAvailableError
from nohiki_observability import get_logger

from job_correlation_evaluation_service.db.models import Correlation
from job_correlation_evaluation_service.events.publishers import (
    publish_correlation_evaluated,
)
from job_correlation_evaluation_service.repositories import ProfileProjectionRepository
from job_correlation_evaluation_service.repositories.match_record_repository import (
    MatchRecordRepository,
)
from job_correlation_evaluation_service.services.match_types import (
    JobMatchResult,
    MatchContext,
)
from job_correlation_evaluation_service.services.scoring.constants import (
    FEATURE_SCHEMA_VERSION,
)
from job_correlation_evaluation_service.services.scoring_service import MLScoringResult

if TYPE_CHECKING:
    from collections.abc import Mapping

    from nohiki.job.listing.v1 import ListingSnapshot
    from nohiki.user.pref.v1 import SearchPrefSnapshot
    from sqlalchemy.ext.asyncio import AsyncSession

    from job_correlation_evaluation_service.services.scoring_service import (
        MLScoringService,
    )

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class _PersistContext:
    """Bundle of per-job fields used during the persist+publish phase."""

    job: ListingSnapshot
    job_id_str: str
    correlation_id: str


class JobMatcherService:
    """Service for matching jobs to user preferences.

    Orchestrates the job matching workflow using ECST pattern.
    Delegates to specialized components for scoring, persistence, and publishing.
    """

    def __init__(self, ml_scoring_service: MLScoringService | None = None) -> None:
        """Initialize the matcher service.

        Args:
            ml_scoring_service: ML scoring service for advanced scoring.
                If None, pipeline will return zero scores.

        """
        self._ml_service = ml_scoring_service

    @staticmethod
    def _is_listing_enriched(listing: ListingSnapshot) -> bool:
        """Check if a listing has sufficient enrichment data for ML scoring.

        Gates scoring on the presence of skills_embedding: the authoritative
        signal that LLM extraction and dense embedding computation completed.
        title_embedding is no longer used as an L2R feature (superseded by
        ISCO occupation matching), so its absence does not block scoring.

        skill_requirements (canonical objects from skill-graph-service) may be
        empty: canonicalization is an independent async saga. The scoring
        pipeline handles missing skill features gracefully via NaN propagation
        in the LightGBM feature vector.

        Args:
            listing: Job listing snapshot to validate.

        Returns:
            True if the listing has embedding data for ML scoring.

        """
        return listing.skills_embedding is not None

    async def match_job_to_profiles(
        self,
        db: AsyncSession,
        job: ListingSnapshot,
        correlation_id: str,
        *,
        force_rescore: bool = False,
    ) -> int:
        """Match a job against all active user profiles.

        Scores all eligible profiles synchronously (ML inference, no IO), then
        batch-inserts all matches in a single DB transaction, then publishes
        all match events concurrently.

        Args:
            db: Database session.
            job: Job listing snapshot from ECST event.
            correlation_id: Trace correlation ID.
            force_rescore: If True, score ALL active profiles and upsert
                existing correlations (used by ListingUpdated to refresh
                pre-enrichment scores). If False, skip profiles that already
                have a correlation for this listing (default for ListingCreated).

        Returns:
            Number of successful matches created or updated.

        Raises:
            ValueError: If correlation_id is empty.

        """
        if not correlation_id.strip():
            msg = "correlation_id cannot be empty"
            raise ValueError(msg)

        active_profiles = await ProfileProjectionRepository(db).get_active_profiles()
        if not active_profiles:
            return 0

        repo = MatchRecordRepository(db)
        job_id_str = str(job.id)

        target_profiles = await self._select_target_profiles(
            repo,
            active_profiles,
            job_id_str,
            force_rescore=force_rescore,
        )
        if not target_profiles:
            return 0

        if not self._is_listing_enriched(job):
            logger.warning(
                "Skipping unenriched listing: missing skills_embedding",
                listing_id=job_id_str,
            )
            return 0

        if not self._is_ml_service_ready():
            logger.error("ML service not ready - cannot score listings", listing_id=job_id_str)
            return 0

        scored: list[tuple[SearchPrefSnapshot, JobMatchResult]] = [
            (profile, result)
            for profile in target_profiles
            if (result := self._score_single(job, job_id_str, profile)) is not None
        ]

        if not scored:
            return 0

        persist_ctx = _PersistContext(job=job, job_id_str=job_id_str, correlation_id=correlation_id)
        match_count = await self._persist_scored_matches(
            db,
            repo,
            scored,
            persist_ctx,
            force_rescore=force_rescore,
        )

        logger.info(
            "Listing matching completed",
            listing_id=job_id_str,
            total_profiles=len(active_profiles),
            target_profiles=len(target_profiles),
            successful_matches=match_count,
            correlation_id=correlation_id,
            force_rescore=force_rescore,
        )

        return match_count

    @staticmethod
    async def _select_target_profiles(
        repo: MatchRecordRepository,
        active_profiles: list[SearchPrefSnapshot],
        job_id_str: str,
        *,
        force_rescore: bool,
    ) -> list[SearchPrefSnapshot]:
        """Pick which profiles to score for this job.

        Re-scoring (ListingUpdated after enrichment) targets every active
        profile so pre-enrichment correlations get refreshed. The default
        path skips profiles that already have a correlation for this listing.
        """
        if force_rescore:
            return list(active_profiles)
        all_pref_ids = [profile.id for profile in active_profiles]
        existing_pref_ids = await repo.get_existing_pref_ids(job_id_str, all_pref_ids)
        return [p for p in active_profiles if p.id not in existing_pref_ids]

    @staticmethod
    async def _persist_scored_matches(
        db: AsyncSession,
        repo: MatchRecordRepository,
        scored: list[tuple[SearchPrefSnapshot, JobMatchResult]],
        ctx_proto: _PersistContext,
        *,
        force_rescore: bool,
    ) -> int:
        """Atomically persist matches and emit one event per durable write."""
        persisted: list[tuple[SearchPrefSnapshot, JobMatchResult]] = []
        for profile, result in scored:
            user_id = uuid.UUID(str(profile.user_id))
            if force_rescore:
                correlation_id, status = await repo.upsert_match_no_commit(result, user_id)
                persisted.append(
                    (
                        profile,
                        replace(result, correlation_id=correlation_id, status=status),
                    )
                )
            elif await repo.record_match_no_commit(result, user_id):
                persisted.append((profile, result))

        for profile, result in persisted:
            ctx = MatchContext(
                ctx_proto.job_id_str,
                ctx_proto.job.listing_url,
                ctx_proto.job,
                profile,
                ctx_proto.correlation_id,
            )
            await publish_correlation_evaluated(db, result, ctx)

        await db.commit()
        return len(persisted)

    def _score_single(
        self,
        job: ListingSnapshot,
        job_id_str: str,
        profile: SearchPrefSnapshot,
    ) -> JobMatchResult | None:
        """Score a single job-profile pair using inline embeddings.

        Job embeddings come from ListingSnapshot.embedding_artifacts (REQUIRED).
        Profile query encoding is extracted from ECST snapshot.

        Args:
            job: Job listing snapshot with embedding_artifacts.
            job_id_str: String representation of job ID.
            profile: User search preferences.

        Returns:
            JobMatchResult if scoring succeeded, None if profile embeddings unavailable.

        Raises:
            RuntimeError: If ML service is not initialized.
            ValueError: If job missing retrieval_embeddings (proto validation should prevent).

        """
        ml_service = self._ml_service
        if ml_service is None:
            msg = "ML service not initialized"
            raise RuntimeError(msg)

        query_encoding = ml_service.extract_query_encoding_from_snapshot(profile)
        if query_encoding is None:
            logger.error(
                "Profile missing query_retrieval_embeddings in ECST snapshot",
                pref_id=profile.id,
            )
            return None

        ml_result = ml_service.score_with_inline_embeddings(
            listing=job,
            profile=profile,
            query_encoding=query_encoding,
        )

        if ml_result.is_disqualified:
            return None

        return self._build_match_result_from_ml(profile, job_id_str, job.listing_url, ml_result)

    def _build_match_result_from_ml(
        self,
        profile: SearchPrefSnapshot,
        listing_id: str,
        listing_url: str,
        ml_result: MLScoringResult,
    ) -> JobMatchResult:
        """Build JobMatchResult from ML scoring result.

        Args:
            profile: User profile.
            listing_id: Job listing ID.
            listing_url: Job listing URL.
            ml_result: ML scoring result.

        Returns:
            Constructed JobMatchResult.

        """
        return JobMatchResult(
            pref_id=profile.id,
            listing_id=listing_id,
            listing_url=listing_url,
            score=ml_result.score,
            feature_vector=ml_result.feature_vector,
            feature_schema_version=FEATURE_SCHEMA_VERSION,
            role_relevance_raw=ml_result.role_relevance_raw,
            ranking_index=ml_result.ranking_index,
            factors=ml_result.factors,
        )

    async def match_listings_to_profile(
        self,
        db: AsyncSession,
        listings: list[ListingSnapshot],
        profile: SearchPrefSnapshot,
        correlation_id: str,
        *,
        force_rescore: bool = False,
    ) -> int:
        """Match a listing batch against one profile, optionally rescoring all rows."""
        if not listings:
            return 0

        repo = MatchRecordRepository(db)
        listings_by_id = await self._prepare_backfill_listings(
            repo,
            listings,
            profile,
            force_rescore=force_rescore,
        )
        if not listings_by_id:
            return 0

        scorable_listings, zero_ids = await self._partition_backfill_listings(
            repo,
            listings_by_id,
            profile,
            force_rescore=force_rescore,
        )
        results = await self._score_listings_batch(scorable_listings, profile) if scorable_listings else []
        if force_rescore:
            scored_ids = {result.listing_id for result in results}
            results.extend(
                self._build_non_actionable_result(profile, listing_id, listings_by_id[listing_id].listing_url)
                for listing_id in zero_ids
            )
            results.extend(
                self._build_non_actionable_result(profile, listing_id, listing.listing_url)
                for listing_id, listing in scorable_listings.items()
                if listing_id not in scored_ids
            )
        elif not results:
            return 0
        user_id = uuid.UUID(str(profile.user_id))
        if force_rescore:
            persisted_matches = await repo.upsert_matches_with_listing_ids_no_commit(results, user_id)
        else:
            await repo.record_matches_batch_no_commit(results, user_id)
            inserted_listing_ids = repo.last_inserted_listing_ids
            persisted_matches = {
                result.listing_id: (result.correlation_id, result.status)
                for result in results
                if result.listing_id in inserted_listing_ids
            }

        for result in results:
            persisted = persisted_matches.get(result.listing_id)
            if persisted is None:
                continue
            listing = listings_by_id[result.listing_id]
            event_result = replace(result, correlation_id=persisted[0], status=persisted[1])
            await publish_correlation_evaluated(
                db,
                event_result,
                MatchContext(
                    result.listing_id,
                    result.listing_url,
                    listing,
                    profile,
                    correlation_id,
                ),
            )

        await db.commit()
        return len(persisted_matches)

    @staticmethod
    async def _prepare_backfill_listings(
        repo: MatchRecordRepository,
        listings: list[ListingSnapshot],
        profile: SearchPrefSnapshot,
        *,
        force_rescore: bool,
    ) -> dict[str, ListingSnapshot]:
        """Select callback listings, skipping existing rows only on create."""
        listings_by_id: dict[str, ListingSnapshot] = {str(listing.id): listing for listing in listings}
        if not force_rescore:
            existing_ids = await repo.get_existing_listing_ids(profile.id, list(listings_by_id))
            listings_by_id = {
                listing_id: listing for listing_id, listing in listings_by_id.items() if listing_id not in existing_ids
            }
        if not listings_by_id:
            return {}

        unenriched = {
            listing_id
            for listing_id, listing in listings_by_id.items()
            if not JobMatcherService._is_listing_enriched(listing)
        }
        if unenriched and not force_rescore:
            logger.warning(
                "Filtering unenriched listings from backfill batch",
                unenriched_count=len(unenriched),
                total_count=len(listings_by_id),
                pref_id=profile.id,
            )
            listings_by_id = {
                listing_id: listing for listing_id, listing in listings_by_id.items() if listing_id not in unenriched
            }
        return listings_by_id

    @staticmethod
    async def _partition_backfill_listings(
        repo: MatchRecordRepository,
        listings_by_id: dict[str, ListingSnapshot],
        profile: SearchPrefSnapshot,
        *,
        force_rescore: bool,
    ) -> tuple[dict[str, ListingSnapshot], set[str]]:
        """Separate scorable listings from existing unenriched rows to invalidate."""
        if not force_rescore:
            return listings_by_id, set()
        unenriched_ids = {
            listing_id
            for listing_id, listing in listings_by_id.items()
            if not JobMatcherService._is_listing_enriched(listing)
        }
        if not unenriched_ids:
            return listings_by_id, set()
        existing_ids = await repo.get_existing_listing_ids(profile.id, list(unenriched_ids))
        scorable = {
            listing_id: listing for listing_id, listing in listings_by_id.items() if listing_id not in unenriched_ids
        }
        return scorable, unenriched_ids & existing_ids

    @staticmethod
    def _build_non_actionable_result(
        profile: SearchPrefSnapshot,
        listing_id: str,
        listing_url: str,
    ) -> JobMatchResult:
        """Represent a valid listing omitted by scoring as an explicit zero match."""
        return JobMatchResult(
            pref_id=profile.id,
            listing_id=listing_id,
            listing_url=listing_url,
            score=0,
            feature_schema_version=FEATURE_SCHEMA_VERSION,
            role_relevance_raw=0.0,
            ranking_index=0.0,
            factors=(),
        )

    async def _score_listings_batch(
        self,
        listings_by_id: Mapping[str, ListingSnapshot],
        profile: SearchPrefSnapshot,
    ) -> list[JobMatchResult]:
        """Score listings using ML pipeline with embedding similarity.

        Args:
            listings_by_id: Dict mapping entity_id to ListingSnapshot
            profile: User search preferences

        Returns:
            List of JobMatchResult with ML scores

        Raises:
            RuntimeError: If ML service is not initialized (startup error)
            DataNotAvailableError: If embeddings are missing (should not happen with ECST)

        """
        ml_service = self._ml_service
        if ml_service is None or not ml_service.is_initialized:
            msg = "ML service not initialized - cannot score listings"
            raise RuntimeError(msg)

        query_encoding = ml_service.extract_query_encoding_from_snapshot(profile)

        if query_encoding is None:
            raise DataNotAvailableError(
                resource_type="ProfileQueryEncoding",
                resource_id=profile.id,
            )

        ml_results = await ml_service.score_listings_batch(
            listings=listings_by_id,
            profile=profile,
            query_encoding=query_encoding,
        )
        return self._convert_ml_results(ml_results, listings_by_id, profile)

    def _is_ml_service_ready(self) -> bool:
        """Check if ML service is available and initialized."""
        return self._ml_service is not None and self._ml_service.is_initialized

    def _convert_ml_results(
        self,
        ml_results: list[MLScoringResult],
        listings_by_id: Mapping[str, ListingSnapshot],
        profile: SearchPrefSnapshot,
    ) -> list[JobMatchResult]:
        return [
            self._build_match_result(ml_result, ml_result.listing_id, listings_by_id, profile)
            for ml_result in ml_results
            if not ml_result.is_disqualified
            and ml_result.listing_id is not None
            and ml_result.listing_id in listings_by_id
        ]

    def _build_match_result(
        self,
        ml_result: MLScoringResult,
        listing_id: str,
        listings_by_id: Mapping[str, ListingSnapshot],
        profile: SearchPrefSnapshot,
    ) -> JobMatchResult:
        """Build a single JobMatchResult from ML scoring result."""
        return JobMatchResult(
            pref_id=profile.id,
            listing_id=listing_id,
            listing_url=listings_by_id[listing_id].listing_url,
            score=ml_result.score,
            feature_vector=ml_result.feature_vector,
            feature_schema_version=FEATURE_SCHEMA_VERSION,
            role_relevance_raw=ml_result.role_relevance_raw,
            ranking_index=ml_result.ranking_index,
            factors=ml_result.factors,
        )

    async def get_actionable_matches(
        self,
        db: AsyncSession,
        pref_id: str,
        limit: int = 50,
    ) -> list[Correlation]:
        """Get actionable matches for a preference.

        Delegates to repository for data access.

        Args:
            db: Database session.
            pref_id: User preference ID.
            limit: Maximum matches to return.

        Returns:
            List of correlation records.

        """
        repo = MatchRecordRepository(db)
        return await repo.get_actionable_matches(pref_id, limit)

    async def dismiss_matches_for_deleted_job(
        self,
        db: AsyncSession,
        listing_id: uuid.UUID,
    ) -> int:
        """Dismiss all matches for a deleted job.

        Delegates to repository for data access.

        Args:
            db: Database session.
            listing_id: UUID of the deleted listing.

        Returns:
            Number of matches dismissed.

        """
        repo = MatchRecordRepository(db)
        return await repo.dismiss_for_deleted_listing(listing_id)
