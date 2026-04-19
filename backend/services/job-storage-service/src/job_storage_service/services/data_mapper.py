"""Maps typed proto messages to database model fields.

Only post-enrichment proto (StoredListing) is mapped here; pre-enrichment
discovered data is held in ListingIngestSaga and never written to listings.

Proto fields are validated by protovalidate at the Kafka deserialization boundary.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nohiki.job.ingest.v1 import StoredListing


def compute_dedup_hash(title: str, company_name: str, posted_at: datetime | None) -> str:
    """Compute cross-source deduplication hash.

    Hash of normalized: lowercase(title) + lowercase(company_name) + date(posted_at)
    This catches the same job across different sources (LinkedIn, Indeed, etc.)
    """
    normalized_title = title.lower().strip()
    normalized_company = company_name.lower().strip()
    posted_date = posted_at.date().isoformat() if posted_at else "unknown"

    content = f"{normalized_title}|{normalized_company}|{posted_date}"
    return hashlib.sha256(content.encode()).hexdigest()


class JobDataMapper:
    """Maps StoredListing proto to database fields for the canonical listings table."""

    def from_stored(
        self,
        stored: StoredListing,
        correlation_id: str,
        collection_version: str,
    ) -> dict[str, Any]:
        """Map StoredListing proto to database fields for enriched storage.

        Args:
            stored: Typed proto from EnrichmentCompleted event.
            correlation_id: Correlation ID for tracing.
            collection_version: Qdrant collection version (e.g., 'v1') from manifest.

        Returns:
            Dict of database column values for Listing model insert/update.

        """
        now = datetime.now(UTC)

        # ExperienceRequirement uses optional ExperienceYearsBound for min/max
        exp = stored.experience
        min_exp_bound = getattr(exp, "min_years", None) if exp else None
        max_exp_bound = getattr(exp, "max_years", None) if exp else None
        min_exp = min_exp_bound.years if min_exp_bound else None
        max_exp = max_exp_bound.years if max_exp_bound else None

        title = stored.title
        company_name = stored.company_name or ""
        posted_at = stored.posted_timestamp

        return {
            "title": title,
            "company_name": company_name,
            "description": stored.description,
            "location": stored.location.to_dict() if stored.location else None,
            "work_arrangement": stored.work_arrangement,
            "employment_term": stored.employment_term,
            "seniority_level": stored.seniority_level,
            "language": stored.language,
            "required_skills": [sr.skill_name for sr in stored.skill_requirements if sr.skill_name],
            "canonical_skill_ids": [sr.skill_id for sr in stored.skill_requirements],
            "min_experience_years": min_exp,
            "max_experience_years": max_exp,
            "compensation": stored.compensation.to_dict() if stored.compensation else None,
            "company_logo_url": stored.company_logo_url or None,
            "skills_embedding": list(stored.skills_embedding.dense.values)
            if stored.skills_embedding and stored.skills_embedding.dense
            else [],
            "title_embedding": list(stored.title_embedding.dense.values)
            if stored.title_embedding and stored.title_embedding.dense
            else [],
            "collection_version": collection_version,
            "raw_content_hash": stored.content_hash,
            "dedup_hash": compute_dedup_hash(title, company_name, posted_at),
            "discovered_at": stored.discovered_timestamp,
            "posted_at": posted_at,
            "processed_at": now,
            "processing_correlation_id": correlation_id,
            "updated_at": now,
        }
