"""Profile service for job target profile management."""

from __future__ import annotations

from datetime import UTC
from typing import TYPE_CHECKING
from uuid import UUID

from nohiki.common.v1 import (
    CommutePreferences,
    EntityTimestamps,
    ExperiencePreference,
    Location,
    SalaryPreference,
    SeniorityLevel,
    UploadReference,
    WorkArrangement,
)
from nohiki.ml.v1 import DenseData, EmbeddingType, EmbeddingVector
from nohiki.skill.v1 import UserSkillEntry
from nohiki.user.pref.v1 import (
    PrefCreateRequested,
    PrefUpdateRequested,
    SearchPrefSnapshot,
)
from nohiki_fastapi_utils.errors import NotFoundError
from nohiki_observability import get_logger
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.orm import selectinload

from user_pref_service.core.config import get_settings
from user_pref_service.core.embedding import (
    build_profile_embedding_text,
    profile_embedding_content_hash,
)
from user_pref_service.db.models import SearchPref, SearchPrefUpload
from user_pref_service.services.geo_integration import geocode_locations

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.sql.elements import ColumnElement

logger = get_logger(__name__)

_SEMANTIC_PROFILE_FIELDS = frozenset(
    {
        "pref_name",
        "search_keywords",
        "user_skills",
        "required_skills",
        "preferred_skills",
    }
)


def extract_canonical_skill_names(profile: SearchPref) -> list[str]:
    """Read normalized skill names from the profile's persisted JSONB state."""
    data = profile.user_skills_data
    if not isinstance(data, list):
        return []
    return [
        name for item in data if isinstance(item, dict) and isinstance(name := item.get("skill_name"), str) and name
    ]


def build_profile_embedding_text_from_profile(profile: SearchPref) -> str:
    """Build embedding text from the complete persisted profile row."""
    keywords = profile.search_keywords if isinstance(profile.search_keywords, list) else []
    return build_profile_embedding_text(profile.pref_name, keywords, extract_canonical_skill_names(profile))


def set_profile_semantic_hash(profile: SearchPref, embedding_text: str) -> str:
    """Persist the identity of the profile semantic text and return it."""
    content_hash = profile_embedding_content_hash(embedding_text)
    profile.semantic_content_hash = content_hash
    return content_hash


def _extract_locations(profile: SearchPref) -> tuple[list[Location], list[Location]]:
    """Extract physical and remote locations from profile."""
    physical_locs = [Location.from_dict(loc) for loc in (profile.physical_locations or [])]
    remote_locs = [Location.from_dict(loc) for loc in (profile.remote_locations or [])]
    return physical_locs, remote_locs


def _extract_skills_embedding(profile: SearchPref) -> EmbeddingVector | None:
    """Build EmbeddingVector for user skills dense embedding.

    Returns None when no aggregated embedding has been computed yet
    (e.g. new profile before skill normalization completes).
    """
    if not profile.user_skills_embedding:
        return None
    return EmbeddingVector(
        embedding_type=EmbeddingType.DENSE,
        dense=DenseData(values=list(profile.user_skills_embedding)),
        collection_version=profile.collection_version or "",
    )


def _extract_query_embedding(profile: SearchPref) -> EmbeddingVector:
    """Build EmbeddingVector for query dense embedding."""
    content_hash = profile.semantic_content_hash or profile_embedding_content_hash(
        build_profile_embedding_text_from_profile(profile)
    )
    return EmbeddingVector(
        embedding_type=EmbeddingType.DENSE,
        dense=DenseData(values=list(profile.query_embedding or [])),
        content_hash=content_hash,
        collection_version=profile.collection_version or "",
    )


def _extract_query_retrieval_embeddings(profile: SearchPref) -> list[EmbeddingVector]:
    """Build list of retrieval EmbeddingVectors from stored JSONB data."""
    if not profile.query_artifacts_data:
        return []
    return [EmbeddingVector.from_dict(d) for d in profile.query_artifacts_data]


def build_profile_snapshot(
    profile: SearchPref,
    *,
    user_skills: list[UserSkillEntry] | None = None,
) -> SearchPrefSnapshot:
    """Build a SearchPrefSnapshot protobuf for ECST events.

    Embedding data is read directly from the profile row (persisted
    by enrichment handlers before this function is called).

    Args:
        profile: SearchPref database model.
        user_skills: Rich user skill entries from normalization.

    """
    example_uploads, context_uploads = _get_upload_references(profile.attachments)
    physical_locs, remote_locs = _extract_locations(profile)

    return SearchPrefSnapshot(
        id=str(profile.id),
        user_id=str(profile.user_id),
        pref_name=profile.pref_name,
        search_keywords=list(profile.search_keywords or []),
        disallowed_keywords=list(profile.disallowed_keywords or []),
        physical_locations=physical_locs,
        remote_locations=remote_locs,
        work_arrangements=list(profile.work_arrangements or []),
        open_to_relocation=profile.open_to_relocation,
        commute_preferences=(
            CommutePreferences.from_dict(profile.commute_preferences) if profile.commute_preferences else None
        ),
        experience_preference=_build_experience_preference(profile),
        salary_preference=_build_salary_preference(profile),
        excluded_scrape_sources=list(profile.excluded_scrape_sources or []),
        min_fit_score_disqualify=profile.min_fit_score_disqualify,
        auto_tailor_threshold=profile.auto_tailor_threshold,
        tailoring_schema_id=str(profile.tailoring_schema_id) if profile.tailoring_schema_id else None,
        tailoring_preferences=dict(profile.tailoring_preferences) if profile.tailoring_preferences else {},
        is_active=profile.is_active,
        example_uploads=example_uploads,
        context_uploads=context_uploads,
        timestamps=_build_timestamps(profile),
        user_skills=(
            user_skills
            if user_skills is not None
            else [UserSkillEntry.from_dict(data) for data in (profile.user_skills_data or [])]
        ),
        user_skills_embedding=_extract_skills_embedding(profile),
        query_embedding=_extract_query_embedding(profile),
        query_retrieval_embeddings=_extract_query_retrieval_embeddings(profile),
        semantic_content_generation=profile.semantic_content_generation,
        semantic_content_hash=profile.semantic_content_hash or "",
        collection_version=profile.collection_version or "",
    )


def _get_upload_references(
    attachments: list[SearchPrefUpload],
) -> tuple[list[UploadReference], list[UploadReference]]:
    """Build UploadReference messages from profile attachments."""
    example_uploads: list[UploadReference] = []
    context_uploads: list[UploadReference] = []

    for att in attachments:
        ref = UploadReference(id=str(att.upload_id), storage_key=str(att.upload_id))
        if att.upload_type == "example":
            example_uploads.append(ref)
        else:
            context_uploads.append(ref)

    return example_uploads, context_uploads


def _build_experience_preference(profile: SearchPref) -> ExperiencePreference | None:
    """Build ExperiencePreference from profile data."""
    has_experience = profile.experience_years is not None
    has_seniority = bool(profile.seniority_levels)

    if not has_experience and not has_seniority:
        return None

    return ExperiencePreference(
        experience_years=profile.experience_years,
        seniority_levels=[SeniorityLevel(s) for s in (profile.seniority_levels or [])],
    )


def _build_salary_preference(profile: SearchPref) -> SalaryPreference | None:
    """Build SalaryPreference from profile's JSONB salary_preference field.

    JSONB is stored directly from betterproto to_dict(), so from_dict() handles it.
    """
    if not profile.salary_preference:
        return None
    return SalaryPreference.from_dict(profile.salary_preference)


def _build_timestamps(profile: SearchPref) -> EntityTimestamps:
    """Build EntityTimestamps message from profile."""
    created = profile.created_at
    updated = profile.updated_at

    if created is None or updated is None:
        msg = "profile created_at and updated_at must be set"
        raise ValueError(msg)

    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=UTC)

    return EntityTimestamps(created_at=created, updated_at=updated)


async def create_profile(
    db: AsyncSession,
    user_id: UUID,
    cmd: PrefCreateRequested,
) -> SearchPref:
    """Create a new job target profile from a command message."""
    settings = get_settings()
    physical_locs = list(cmd.physical_locations)
    if settings.geocoding_enabled and physical_locs:
        physical_locs = await geocode_locations(physical_locs)

    profile = SearchPref(
        user_id=user_id,
        pref_name=cmd.pref_name,
        search_keywords=list(cmd.search_keywords),
        disallowed_keywords=list(cmd.disallowed_keywords),
        physical_locations=[loc.to_dict() for loc in physical_locs],
        remote_locations=[Location(country=c).to_dict() for c in cmd.remote_locations],
        work_arrangements=[WorkArrangement(w) for w in cmd.work_arrangements],
        open_to_relocation=cmd.open_to_relocation,
        commute_preferences=cmd.commute_preferences.to_dict() if cmd.commute_preferences else None,
        notification_config=cmd.notification_config.to_dict() if cmd.notification_config else None,
        experience_years=cmd.experience_preference.experience_years if cmd.experience_preference else None,
        seniority_levels=[SeniorityLevel(s) for s in cmd.experience_preference.seniority_levels]
        if cmd.experience_preference
        else [],
        salary_preference=cmd.salary_preference.to_dict() if cmd.salary_preference else None,
        auto_tailor_threshold=cmd.auto_tailor_threshold,
        tailoring_schema_id=UUID(cmd.tailoring_schema_id) if cmd.tailoring_schema_id else None,
        tailoring_preferences=dict(cmd.tailoring_preferences) if cmd.tailoring_preferences else None,
        is_active=cmd.is_active,
        request_id=UUID(cmd.request_id),
        semantic_content_generation=1,
    )
    db.add(profile)
    await db.flush()

    created_profile = await get_profile_by_id(db, profile.id)
    logger.info("Created profile", pref_id=str(created_profile.id), user_id=str(user_id))
    return created_profile


async def get_profile_by_id(db: AsyncSession, pref_id: UUID) -> SearchPref:
    """Get profile by ID with attachments loaded."""
    result = await db.execute(
        select(SearchPref)
        .where(SearchPref.id == pref_id)
        .options(selectinload(SearchPref.attachments))
        .execution_options(populate_existing=True)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise NotFoundError(resource="Profile", identifier=str(pref_id))
    return profile


async def get_profile_by_id_optional(db: AsyncSession, pref_id: UUID) -> SearchPref | None:
    """Get profile by ID, returning None if not found (for idempotent operations)."""
    result = await db.execute(
        select(SearchPref).where(SearchPref.id == pref_id).options(selectinload(SearchPref.attachments))
    )
    return result.scalar_one_or_none()


async def get_profile_by_id_for_update(db: AsyncSession, pref_id: UUID) -> SearchPref:
    """Load a profile while holding its row lock for callback compare-and-set."""
    result = await db.execute(
        select(SearchPref)
        .where(SearchPref.id == pref_id)
        .options(selectinload(SearchPref.attachments))
        .with_for_update()
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise NotFoundError(resource="Profile", identifier=str(pref_id))
    return profile


async def get_profiles_by_ids(db: AsyncSession, pref_ids: set[UUID]) -> list[SearchPref]:
    """Get multiple profiles by IDs in a single batch query.

    Args:
        db: Async database session.
        pref_ids: Profile IDs to fetch.

    Returns:
        Profiles with attachments eagerly loaded.

    """
    if not pref_ids:
        return []

    result = await db.execute(
        select(SearchPref)
        .where(SearchPref.id.in_(pref_ids))
        .options(selectinload(SearchPref.attachments))
        .execution_options(populate_existing=True)
    )
    return list(result.scalars().unique().all())


async def get_profile_by_request_id(db: AsyncSession, request_id: UUID) -> SearchPref | None:
    """Get profile by request_id for idempotency checking."""
    result = await db.execute(
        select(SearchPref).where(SearchPref.request_id == request_id).options(selectinload(SearchPref.attachments))
    )
    return result.scalar_one_or_none()


async def list_user_profiles(db: AsyncSession, user_id: UUID, *, active_only: bool = False) -> list[SearchPref]:
    """List all profiles for a user."""
    query = select(SearchPref).where(SearchPref.user_id == user_id).options(selectinload(SearchPref.attachments))
    if active_only:
        query = query.where(SearchPref.is_active.is_(True))
    query = query.order_by(SearchPref.created_at.desc())

    result = await db.execute(query)
    return list(result.scalars().all())


def _apply_profile_updates(profile: SearchPref, cmd: PrefUpdateRequested) -> None:
    """Apply updates from command to profile model."""
    updated_fields = set(cmd.updated_fields)
    skill_fields = {"user_skills", "required_skills", "preferred_skills"}
    if updated_fields & skill_fields:
        skill_ids = list(
            dict.fromkeys(
                str(UUID(skill_id))
                for skill_id in (
                    *cmd.user_skills,
                    *cmd.required_skills,
                    *cmd.preferred_skills,
                )
            )
        )
        profile.user_skill_ids = skill_ids
        profile.user_skills_data = [UserSkillEntry(skill_id=skill_id).to_dict() for skill_id in skill_ids]

    if "experience_preference" in updated_fields:
        experience = cmd.experience_preference
        profile.experience_years = experience.experience_years if experience else None
        profile.seniority_levels = (
            [SeniorityLevel(level) for level in experience.seniority_levels] if experience else []
        )

    field_handlers: dict[str, tuple[str, object]] = {
        "pref_name": ("pref_name", cmd.pref_name or None),
        "search_keywords": ("search_keywords", list(cmd.search_keywords)),
        "disallowed_keywords": ("disallowed_keywords", list(cmd.disallowed_keywords)),
        "physical_locations": (
            "physical_locations",
            [loc.to_dict() for loc in cmd.physical_locations],
        ),
        "remote_locations": (
            "remote_locations",
            [Location(country=c).to_dict() for c in cmd.remote_locations],
        ),
        "work_arrangements": (
            "work_arrangements",
            [WorkArrangement(w) for w in cmd.work_arrangements],
        ),
        "open_to_relocation": ("open_to_relocation", cmd.open_to_relocation),
        "commute_preferences": (
            "commute_preferences",
            cmd.commute_preferences.to_dict() if cmd.commute_preferences else None,
        ),
        "salary_preference": (
            "salary_preference",
            cmd.salary_preference.to_dict() if cmd.salary_preference else None,
        ),
        "auto_tailor_threshold": ("auto_tailor_threshold", cmd.auto_tailor_threshold),
        "tailoring_schema_id": (
            "tailoring_schema_id",
            UUID(cmd.tailoring_schema_id) if cmd.tailoring_schema_id else None,
        ),
        "tailoring_preferences": (
            "tailoring_preferences",
            dict(cmd.tailoring_preferences) if cmd.tailoring_preferences else None,
        ),
        "is_active": ("is_active", cmd.is_active),
        "notification_config": (
            "notification_config",
            cmd.notification_config.to_dict() if cmd.notification_config else None,
        ),
    }

    for field_name, (attr_name, value) in field_handlers.items():
        if field_name in updated_fields:
            setattr(profile, attr_name, value)
    if updated_fields & _SEMANTIC_PROFILE_FIELDS:
        current_generation = profile.semantic_content_generation
        profile.semantic_content_generation = (current_generation if isinstance(current_generation, int) else 0) + 1


async def update_profile(db: AsyncSession, pref_id: UUID, cmd: PrefUpdateRequested) -> SearchPref:
    """Update profile fields from an update command.

    Geocodes physical locations when they are part of the update.

    Args:
        db: Async database session.
        pref_id: ID of the profile to update.
        cmd: Update command with changed fields.

    Returns:
        Updated SearchPref with attachments loaded.

    """
    profile = await get_profile_by_id(db, pref_id)
    _apply_profile_updates(profile, cmd)

    settings = get_settings()
    if "physical_locations" in set(cmd.updated_fields) and settings.geocoding_enabled:
        raw_locs = [Location.from_dict(d) for d in (profile.physical_locations or [])]
        if raw_locs:
            geocoded = await geocode_locations(raw_locs)
            profile.physical_locations = [loc.to_dict() for loc in geocoded]

    await db.flush()
    return await get_profile_by_id(db, pref_id)


async def delete_profile(db: AsyncSession, pref_id: UUID) -> SearchPref:
    """Delete a profile and its attachment associations."""
    profile = await get_profile_by_id(db, pref_id)
    user_id = profile.user_id

    await db.delete(profile)
    await db.flush()

    logger.info("Deleted profile", pref_id=str(pref_id), user_id=str(user_id))
    return profile


async def get_profile_ids_for_user(db: AsyncSession, user_id: UUID) -> list[UUID]:
    """Return canonical profile IDs before an account-level bulk deletion."""
    result = await db.execute(select(SearchPref.id).where(SearchPref.user_id == user_id))
    return list(result.scalars().all())


async def delete_user_profiles(db: AsyncSession, user_id: UUID) -> int:
    """Delete all profiles for a user.

    Uses bulk DELETE for O(1) database round-trip instead of O(N) individual deletes.
    """
    result = await db.execute(delete(SearchPref).where(SearchPref.user_id == user_id))
    count: int = getattr(result, "rowcount", 0) or 0
    await db.flush()

    if count > 0:
        logger.info("Deleted all profiles for user", user_id=str(user_id), count=count)
    return count


async def _advance_profile_revisions(db: AsyncSession, predicate: ColumnElement[bool]) -> None:
    """Advance matching authoritative snapshot revisions monotonically."""
    await db.execute(
        update(SearchPref)
        .where(predicate)
        .values(
            updated_at=func.greatest(
                func.clock_timestamp(),
                SearchPref.updated_at + text("interval '1 microsecond'"),
            )
        )
    )


async def associate_attachment(
    db: AsyncSession,
    pref_id: UUID,
    upload_id: UUID,
    upload_type: str,
) -> SearchPrefUpload:
    """Associate an attachment with a profile."""
    await get_profile_by_id(db, pref_id)

    result = await db.execute(
        select(SearchPrefUpload).where(
            SearchPrefUpload.pref_id == pref_id,
            SearchPrefUpload.upload_id == upload_id,
        )
    )
    if association := result.scalar_one_or_none():
        if association.upload_type == upload_type:
            return association

        await db.execute(
            update(SearchPrefUpload)
            .where(
                SearchPrefUpload.pref_id == pref_id,
                SearchPrefUpload.upload_id == upload_id,
            )
            .values(upload_type=upload_type)
        )
        await _advance_profile_revisions(db, SearchPref.id == pref_id)
        await db.flush()
        refreshed = await db.execute(
            select(SearchPrefUpload)
            .where(
                SearchPrefUpload.pref_id == pref_id,
                SearchPrefUpload.upload_id == upload_id,
            )
            .execution_options(populate_existing=True)
        )
        return refreshed.scalar_one()

    association = SearchPrefUpload(pref_id=pref_id, upload_id=upload_id, upload_type=upload_type)
    db.add(association)
    await db.flush()
    await _advance_profile_revisions(db, SearchPref.id == pref_id)

    logger.info(
        "Associated attachment with profile",
        pref_id=str(pref_id),
        upload_id=str(upload_id),
    )
    return association


async def disassociate_attachment(db: AsyncSession, pref_id: UUID, upload_id: UUID) -> None:
    """Remove attachment association from profile."""
    result = await db.execute(
        delete(SearchPrefUpload).where(SearchPrefUpload.pref_id == pref_id, SearchPrefUpload.upload_id == upload_id)
    )
    deleted_count = getattr(result, "rowcount", 0) or 0
    if deleted_count == 0:
        raise NotFoundError(resource="SearchPrefUpload", identifier=f"{pref_id}/{upload_id}")

    await _advance_profile_revisions(db, SearchPref.id == pref_id)
    await db.flush()
    logger.info(
        "Disassociated attachment from profile",
        pref_id=str(pref_id),
        upload_id=str(upload_id),
    )


async def remove_attachment_from_all_profiles(db: AsyncSession, upload_id: UUID) -> int:
    """Remove attachment from all profile associations."""
    affected_pref_ids = select(SearchPrefUpload.pref_id).where(SearchPrefUpload.upload_id == upload_id)
    await _advance_profile_revisions(db, SearchPref.id.in_(affected_pref_ids))
    result = await db.execute(delete(SearchPrefUpload).where(SearchPrefUpload.upload_id == upload_id))
    count: int = getattr(result, "rowcount", 0) or 0
    await db.flush()

    if count > 0:
        logger.info("Removed attachment from profiles", upload_id=str(upload_id), count=count)
    return count


async def get_profiles_with_attachment(db: AsyncSession, upload_id: UUID) -> list[SearchPref]:
    """Get all profiles that reference a given upload.

    Used before bulk-deleting junction rows so the caller can publish
    PrefUpdated events for each affected profile (ECST compliance).

    Args:
        db: Async database session.
        upload_id: The upload ID to search for.

    Returns:
        List of SearchPref models with attachments eagerly loaded.

    """
    result = await db.execute(
        select(SearchPref)
        .join(SearchPrefUpload, SearchPref.id == SearchPrefUpload.pref_id)
        .where(SearchPrefUpload.upload_id == upload_id)
        .options(selectinload(SearchPref.attachments))
    )
    return list(result.scalars().unique().all())
