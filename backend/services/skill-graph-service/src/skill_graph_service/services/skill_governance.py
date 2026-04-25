"""Skill governance service for new skill proposals and approval."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final
from uuid import UUID

from nohiki.ml.v1 import EntityType
from nohiki_observability import get_logger
from nohiki_qdrant_client import QdrantVectorClient, SearchParams
from sqlalchemy import select, update
from uuid_utils.compat import uuid7

from skill_graph_service.core.config import get_manifest, get_settings
from skill_graph_service.db.models import (
    SKILL_DEFAULT_CONFIDENCE,
    SKILL_REVIEW_STATUS_APPROVED,
    SKILL_REVIEW_STATUS_PENDING,
    ProposedSkill,
    SkillAlias,
    SkillNode,
)
from skill_graph_service.seeding.normalizer import normalize_skill_text

settings = get_settings()

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from skill_graph_service.events.publishers import SkillCreatedPublisher

logger = get_logger(__name__)

DUPLICATE_THRESHOLD: Final[float] = 0.85
AUTO_APPROVE_THRESHOLD: Final[int] = 5

_MAX_PROPOSAL_ALIASES: Final[int] = 5
_ALIAS_SOURCE_PROPOSAL: Final[str] = "proposal_approved"
_ALIAS_SOURCE_VERSION_PROPOSAL: Final[str] = "nohiki-proposal"
_ALIAS_CONFIDENCE_PROPOSAL: Final[float] = 0.8


@dataclass(frozen=True, slots=True)
class SkillProposalParams:
    """Parameters for skill proposal processing."""

    canonical_name: str
    display_name: str
    suggested_aliases: list[str] | None = None
    category: str | None = None
    description: str | None = None
    reuse_level: str | None = None
    source_job_id: str | None = None
    proposed_by: str = "llm_extraction"
    embedding: list[float] | None = None


async def check_near_duplicates(
    embedding: list[float],
    qdrant: QdrantVectorClient,
    *,
    threshold: float = DUPLICATE_THRESHOLD,
    limit: int = 3,
) -> list[tuple[str, str, float]]:
    """Check for near-duplicate skills using semantic search.

    Args:
        embedding: Pre-computed embedding for the proposed skill
        qdrant: Qdrant client
        threshold: Similarity threshold for duplicates
        limit: Maximum number of duplicates to return

    Returns:
        List of (skill_id, skill_name, similarity) tuples

    """
    matches = await qdrant.search_dense(
        query_vector=embedding,
        params=SearchParams(
            collection_name=get_manifest().get_collection_name(EntityType.SKILL),
            limit=limit,
            score_threshold=threshold,
        ),
    )

    return [(str(m.id), str(m.payload.get("name", "")), m.score) for m in matches]


async def process_skill_proposal(
    db: AsyncSession,
    qdrant: QdrantVectorClient,
    params: SkillProposalParams,
    *,
    skill_created_publisher: SkillCreatedPublisher,
) -> tuple[str, str, UUID | None]:
    """Process a new skill proposal.

    Checks for near-duplicates and either:
    1. Rejects if too similar to existing skill
    2. Reinforces existing proposal if already proposed
    3. Creates new proposal if unique

    Args:
        db: Database session.
        qdrant: Qdrant client for duplicate detection.
        params: Skill proposal parameters.
        skill_created_publisher: Injected publisher for SKILL_CREATED events.

    Returns:
        Tuple of (status, message, skill_id) where status is one of:
        - ``"rejected_duplicate"``: skill_id is None
        - ``"proposal_reinforced"``: skill_id is None
        - ``"auto_approved"``: skill_id is the UUID of the created SkillNode
        - ``"pending_review"``: skill_id is None

    """
    normalized = normalize_skill_text(params.canonical_name)

    if params.embedding:
        duplicates = await check_near_duplicates(params.embedding, qdrant)
        if duplicates:
            logger.warning(
                "Skill proposal rejected as duplicate",
                proposed=normalized,
                similar_to=duplicates[0][1],
                similarity=duplicates[0][2],
            )
            return ("rejected_duplicate", f"Too similar to: {duplicates[0][1]}", None)

    existing = await db.execute(
        select(ProposedSkill).where(ProposedSkill.canonical_name == normalized).with_for_update()
    )

    if proposal := existing.scalar_one_or_none():
        return await _reinforce_existing_proposal(
            proposal=proposal,
            source_job_id=params.source_job_id,
            db=db,
            normalized=normalized,
            skill_created_publisher=skill_created_publisher,
        )

    return await _create_new_proposal(db, normalized, params)


async def _reinforce_existing_proposal(
    proposal: ProposedSkill,
    source_job_id: str | None,
    db: AsyncSession,
    normalized: str,
    *,
    skill_created_publisher: SkillCreatedPublisher,
) -> tuple[str, str, UUID | None]:
    """Reinforce an existing skill proposal with additional evidence."""
    new_job_ids_set = set(proposal.source_job_ids)
    if source_job_id:
        new_job_ids_set.add(source_job_id)
    new_job_ids = list(new_job_ids_set)

    new_count = proposal.proposal_count + 1

    stmt = (
        update(ProposedSkill)
        .where(ProposedSkill.id == proposal.id)
        .values(
            proposal_count=new_count,
            source_job_ids=new_job_ids,
            updated_at=datetime.now(UTC),
        )
    )
    await db.execute(stmt)

    if new_count >= AUTO_APPROVE_THRESHOLD:
        skill_id = await _approve_proposal(
            proposal.id,
            db,
            reviewed_by="auto_threshold",
            skill_created_publisher=skill_created_publisher,
        )
        return ("auto_approved", f"Skill created with ID: {skill_id}", skill_id)

    logger.info(
        "Skill proposal reinforced",
        canonical_name=normalized,
        proposal_count=new_count,
    )
    return ("proposal_reinforced", f"Proposal count: {new_count}", None)


async def _create_new_proposal(
    db: AsyncSession,
    normalized: str,
    params: SkillProposalParams,
) -> tuple[str, str, UUID | None]:
    """Create a new skill proposal."""
    new_proposal = ProposedSkill(
        canonical_name=normalized,
        display_name=params.display_name,
        suggested_aliases=params.suggested_aliases or [],
        category=params.category,
        description=params.description,
        reuse_level=params.reuse_level,
        source_job_ids=[params.source_job_id] if params.source_job_id else [],
        proposed_by=params.proposed_by,
        status=SKILL_REVIEW_STATUS_PENDING,
    )
    db.add(new_proposal)

    logger.info("New skill proposal created", canonical_name=normalized)
    return ("pending_review", "Proposal created, pending review", None)


async def _approve_proposal(
    proposal_id: UUID,
    db: AsyncSession,
    *,
    reviewed_by: str,
    skill_created_publisher: SkillCreatedPublisher,
) -> UUID:
    """Approve a skill proposal and create the canonical skill.

    Args:
        proposal_id: ID of the proposal to approve.
        db: Database session.
        reviewed_by: Who approved (user or "auto_threshold").
        skill_created_publisher: Injected publisher for SKILL_CREATED events.

    Returns:
        UUID of the created SkillNode.

    """
    stmt = select(ProposedSkill).where(ProposedSkill.id == proposal_id)
    result = await db.execute(stmt)
    proposal = result.scalar_one()

    skill_id = uuid7()

    skill = SkillNode(
        id=skill_id,
        normalized_text=proposal.canonical_name,
        display_name=proposal.display_name,
        reuse_level=proposal.reuse_level,
        category=proposal.category,
        description=proposal.description,
        confidence_score=SKILL_DEFAULT_CONFIDENCE,
        review_status=SKILL_REVIEW_STATUS_APPROVED,
    )
    db.add(skill)

    aliases_to_add = proposal.suggested_aliases[:_MAX_PROPOSAL_ALIASES] if proposal.suggested_aliases else []
    for alias_text in aliases_to_add:
        alias = SkillAlias(
            alias_text=alias_text.lower(),
            canonical_skill_id=skill_id,
            source=_ALIAS_SOURCE_PROPOSAL,
            source_version=_ALIAS_SOURCE_VERSION_PROPOSAL,
            confidence=_ALIAS_CONFIDENCE_PROPOSAL,
        )
        db.add(alias)

    stmt = (
        update(ProposedSkill)
        .where(ProposedSkill.id == proposal_id)
        .values(
            status=SKILL_REVIEW_STATUS_APPROVED,
            reviewed_at=datetime.now(UTC),
            reviewed_by=reviewed_by,
            approved_skill_id=skill_id,
        )
    )
    await db.execute(stmt)

    # Write SKILL_CREATED to outbox (same transaction = atomic)
    await skill_created_publisher(db, skill, provenance=None)

    logger.info(
        "Skill proposal approved",
        proposal_id=str(proposal_id),
        skill_id=str(skill_id),
        reviewed_by=reviewed_by,
    )

    return skill_id
