"""Callback handlers for embedding and skill normalization convergence in job enrichment."""

from __future__ import annotations

import asyncio
import base64
import json
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from inspect import isawaitable
from typing import Final
from uuid import UUID

from nohiki.common.v1 import (
    ErrorInfo,
    GeoCoordinates,
    ListingReference,
    OperationOutcome,
    ProcessingStatus,
)
from nohiki.job.ingest.v1 import DiscoveredListing, EnrichmentCompleted, StoredListing
from nohiki.ml.v1 import (
    EmbeddingCallback,
    EmbeddingResult,
    EmbeddingType,
    EmbeddingVector,
    EncodingMode,
    EntityType,
)
from nohiki.skill.v1 import (
    JobSkillRequirement,
    SkillClarificationNeeded,
    SkillNormalizationCallback,
    SkillNormalizationResult,
    SkillProficiencyLevel,
)
from nohiki_common_exceptions import ValidationError
from nohiki_db_utils import InvalidTransitionError, SagaRepository, SagaStatus, create_event_metadata
from nohiki_embedding_client import EmbeddingSpec
from nohiki_kafka_client import CommandContext, MessageContext, Topics
from nohiki_observability import get_logger
from sqlalchemy.ext.asyncio import AsyncSession

from job_ingest_enrichment_service.core.config import get_manifest, get_settings
from job_ingest_enrichment_service.core.embedding import get_embedding_publisher
from job_ingest_enrichment_service.core.kafka import kafka_client
from job_ingest_enrichment_service.db.models import EnrichmentEmbeddingSaga
from job_ingest_enrichment_service.events.publishers import (
    EnrichmentPublishContext,
    publish_enrichment_completed_outbox,
    publish_enrichment_failed_outbox,
)
from job_ingest_enrichment_service.services.enrichment_context import EnrichmentContext
from job_ingest_enrichment_service.services.proto_builders import EmbeddingBundle, build_stored_listing_from_context
from job_ingest_enrichment_service.services.skill_clarification import (
    ClarificationContext,
    SkillDecisionSchema,
    get_skill_clarification_service,
)

logger = get_logger(__name__)
settings = get_settings()

_saga_repo: SagaRepository[EnrichmentEmbeddingSaga] = SagaRepository(EnrichmentEmbeddingSaga)
_SAGA_TTL = timedelta(minutes=30)
_ATTR_TYPE = "embedding_type"
_LLM_CHAIN_EXTRACTION: Final[str] = "extraction"
_EMBEDDING_FIELDS: Final[dict[str, str]] = {
    "retrieval": "retrieval_embedding_b64",
    "title": "title_embedding_b64",
    "skills": "skills_embedding_b64",
}


class _DuplicateEmbeddingCallbackError(Exception):
    """Signal an idempotent redelivery while the saga row is locked."""


def _decode_first_embedding(b64: str | None) -> EmbeddingVector | None:
    """Decode a base64-encoded EmbeddingResult and return its first embedding, or None when empty."""
    if not b64:
        return None
    result = EmbeddingResult().parse(base64.b64decode(b64))
    return result.embeddings[0] if result.embeddings else None


async def _publish_enrichment_failed(ctx: EnrichmentContext, error: ErrorInfo) -> None:
    """Publish a terminal enrichment outcome so storage closes its ingest saga."""
    discovered = DiscoveredListing.from_json(ctx.discovered_json)
    event = EnrichmentCompleted(
        metadata=create_event_metadata(settings.service_name, ctx.correlation_id),
        listing=ListingReference(
            listing_id=ctx.listing_id or None,
            listing_url=ctx.listing_url,
            source=discovered.source,
            external_listing_id=discovered.external_id or None,
        ),
        stored_data=StoredListing(),
        result=OperationOutcome(status=ProcessingStatus.FAILED, error=error),
        listing_id=ctx.listing_id,
        collection_version=get_manifest().get_entity_version(EntityType.JOB),
    )
    await kafka_client.publish(Topics.JOB_INGEST_ENRICHMENT_COMPLETED, event)


def _failure_publish_context(saga: EnrichmentEmbeddingSaga) -> EnrichmentPublishContext:
    """Reconstruct the event context persisted when the embedding saga started."""
    data = json.loads(saga.enrichment_data_json)
    enrichment_ctx = EnrichmentContext(**data["enrichment_ctx"])
    discovered = DiscoveredListing.from_json(enrichment_ctx.discovered_json)
    geocoded_coordinates: GeoCoordinates | None = None
    if enrichment_ctx.geocoded_lat is not None and enrichment_ctx.geocoded_lon is not None:
        geocoded_coordinates = GeoCoordinates(
            latitude=enrichment_ctx.geocoded_lat,
            longitude=enrichment_ctx.geocoded_lon,
        )
    return EnrichmentPublishContext(
        listing_ref=ListingReference(
            listing_id=enrichment_ctx.listing_id or None,
            listing_url=enrichment_ctx.listing_url,
            source=discovered.source,
            external_listing_id=discovered.external_id or None,
        ),
        stored_data=StoredListing(),
        listing_id=enrichment_ctx.listing_id,
        llm_model_id=saga.llm_model_id,
        collection_version=get_manifest().get_entity_version(EntityType.JOB),
        correlation_id=enrichment_ctx.correlation_id,
        geocoded_coordinates=geocoded_coordinates,
    )


def _decode_all_embeddings(b64: str | None) -> list[EmbeddingVector]:
    """Decode a base64-encoded EmbeddingResult and return all embeddings, or empty list."""
    if not b64:
        return []
    return list(EmbeddingResult().parse(base64.b64decode(b64)).embeddings)


@kafka_client.message_handler(
    Topics.JOB_INGEST_SKILL_CALLBACK,
    SkillNormalizationCallback,
    group_id=f"{settings.service_name}-skill-callback",
    preserve_partition_order=False,
)
@kafka_client.with_db_session(auto_commit=False)
async def handle_skill_normalization_callback(
    message: SkillNormalizationCallback,
    context: MessageContext,
) -> None:
    """Handle skill normalization callback: create embedding saga and fire requests."""
    operation_id = message.callback.operation_id if message.callback else "unknown"

    if message.error is not None:
        logger.error(
            "Skill normalization failed",
            operation_id=operation_id,
            error_code=message.error.error_code,
            error_message=message.error.error_message,
        )
        if message.callback and isinstance(message.callback.caller_context, bytes):
            await _publish_enrichment_failed(
                EnrichmentContext.from_bytes(message.callback.caller_context),
                message.error,
            )
        return

    if message.success is None:
        msg = "Skill normalization callback has no result"
        raise ValidationError(msg)

    result = message.success
    enrichment_ctx = EnrichmentContext.from_bytes(message.callback.caller_context)

    logger.info(
        "Skill normalization completed, initiating embedding saga",
        operation_id=operation_id,
        listing_url=enrichment_ctx.listing_url,
        skill_count=len(result.skill_requirements),
    )

    if result.requires_clarification and result.clarifications:
        await _handle_skill_clarification(
            context=context,
            clarifications=list(result.clarifications),
            enrichment_ctx=enrichment_ctx,
            confirmed_requirements=list(result.skill_requirements),
        )
        return

    skill_requirements = _get_skill_requirements(result, enrichment_ctx)
    await _create_embedding_saga_and_request(context, enrichment_ctx, skill_requirements)


async def _fail_embedding_saga(
    db: AsyncSession,
    saga_id: UUID,
    *,
    error: ErrorInfo,
    operation_id: str,
) -> None:
    """Fail a saga and enqueue its terminal outcome in the same transaction."""
    try:
        await _saga_repo.fail(db, saga_id, reason=error.error_message)
    except InvalidTransitionError:
        logger.info("Duplicate embedding failure ignored", saga_id=str(saga_id), operation_id=operation_id)
        await db.commit()
        return

    load_call = _saga_repo.load(db, saga_id)
    if not isawaitable(load_call):
        # Keeps mocked repository calls from changing callback behavior in unit tests.
        await db.commit()
        return
    saga = await load_call
    if saga is None:
        msg = f"Saga {saga_id} disappeared after failure transition"
        raise ValidationError(msg)
    await publish_enrichment_failed_outbox(db, _failure_publish_context(saga), error)
    await db.commit()


async def expire_stale_embedding_sagas(db: AsyncSession) -> int:
    """Expire stale sagas and enqueue one failed outcome per locked saga."""
    stale = await _saga_repo.find_stale(db, cutoff=datetime.now(UTC))
    for saga in stale:
        saga.transition_to(SagaStatus.EXPIRED)
        await publish_enrichment_failed_outbox(
            db,
            _failure_publish_context(saga),
            ErrorInfo(
                error_code="EMBEDDING_SAGA_EXPIRED",
                error_message="Embedding enrichment saga expired before all callbacks arrived",
                retryable=False,
            ),
        )
    if stale:
        await db.flush()
    return len(stale)


@kafka_client.message_handler(
    Topics.JOB_INGEST_ENRICHMENT_EMBEDDING_CALLBACK,
    EmbeddingCallback,
    group_id=f"{settings.service_name}-embedding-callback",
    preserve_partition_order=False,
)
@kafka_client.with_db_session(auto_commit=False)
async def handle_embedding_callback(
    message: EmbeddingCallback,
    context: MessageContext,
) -> None:
    """Handle embedding callback: record into saga and publish enrichment when converged."""
    if message.callback is None:
        msg = "Embedding callback metadata is required"
        raise ValidationError(msg)

    operation_id = message.callback.operation_id
    saga_payload = json.loads(message.callback.caller_context.decode("utf-8"))
    saga_id = UUID(saga_payload["saga_id"])
    embedding_type = (message.callback.attributes or {}).get(_ATTR_TYPE, "")
    embedding_field = _EMBEDDING_FIELDS.get(embedding_type)
    if embedding_field is None:
        msg = f"Unknown embedding type: {embedding_type!r}"
        raise ValidationError(msg)

    if message.error is not None:
        logger.error(
            "Embedding failed",
            operation_id=operation_id,
            embedding_type=embedding_type,
            error_code=message.error.error_code,
            error_message=message.error.error_message,
        )
        db = context.require_db_session()
        await _fail_embedding_saga(
            db,
            saga_id,
            error=message.error,
            operation_id=operation_id,
        )
        return

    if message.success is None:
        logger.error("Empty embedding callback", operation_id=operation_id)
        return

    embedding_b64 = base64.b64encode(bytes(message.success)).decode("ascii")

    def _update(saga: EnrichmentEmbeddingSaga) -> None:
        if getattr(saga, embedding_field) is not None:
            raise _DuplicateEmbeddingCallbackError
        setattr(saga, embedding_field, embedding_b64)

    db = context.require_db_session()
    try:
        saga, is_complete = await _saga_repo.record_callback(db, saga_id, update_fn=_update)
    except _DuplicateEmbeddingCallbackError:
        await db.commit()
        logger.info(
            "Duplicate embedding callback ignored",
            saga_id=str(saga_id),
            embedding_type=embedding_type,
            operation_id=operation_id,
        )
        return
    except InvalidTransitionError:
        await db.commit()
        logger.info(
            "Late embedding callback ignored for terminal saga",
            saga_id=str(saga_id),
            embedding_type=embedding_type,
            operation_id=operation_id,
        )
        return

    if not is_complete:
        await db.commit()
        return

    await _converge_and_publish(db, saga)


async def _converge_and_publish(db: AsyncSession, saga: EnrichmentEmbeddingSaga) -> None:
    """Build and publish EnrichmentCompleted via outbox once all embedding callbacks have arrived.

    Uses transactional outbox pattern to ensure atomicity between saga state
    transition and event publication.
    """
    data = json.loads(saga.enrichment_data_json)
    enrichment_ctx = EnrichmentContext(**data["enrichment_ctx"])
    skill_requirements = [JobSkillRequirement.from_dict(d) for d in data["skill_requirements"]]
    discovered = DiscoveredListing.from_json(enrichment_ctx.discovered_json)

    stored_listing = _build_stored_listing(
        ctx=enrichment_ctx,
        discovered=discovered,
        skill_requirements=skill_requirements,
        embeddings=(saga.retrieval_embedding_b64, saga.title_embedding_b64, saga.skills_embedding_b64),
    )

    listing_ref = ListingReference(
        listing_id=enrichment_ctx.listing_id or None,
        listing_url=enrichment_ctx.listing_url,
        source=discovered.source,
        external_listing_id=discovered.external_id or None,
    )

    geocoded_coords: GeoCoordinates | None = None
    if enrichment_ctx.geocoded_lat is not None and enrichment_ctx.geocoded_lon is not None:
        geocoded_coords = GeoCoordinates(
            latitude=enrichment_ctx.geocoded_lat,
            longitude=enrichment_ctx.geocoded_lon,
        )

    publish_ctx = EnrichmentPublishContext(
        listing_ref=listing_ref,
        stored_data=stored_listing,
        listing_id=enrichment_ctx.listing_id,
        llm_model_id=saga.llm_model_id,
        collection_version=saga.collection_version,
        correlation_id=enrichment_ctx.correlation_id,
        geocoded_coordinates=geocoded_coords,
    )

    saga.transition_to(SagaStatus.COMPLETED)

    await publish_enrichment_completed_outbox(db, publish_ctx)

    await db.commit()

    logger.info(
        "Enrichment saga completed",
        saga_id=str(saga.id),
        listing_id=enrichment_ctx.listing_id,
        correlation_id=enrichment_ctx.correlation_id,
    )


def _get_skill_requirements(
    result: SkillNormalizationResult,
    enrichment_ctx: EnrichmentContext | None = None,
) -> list[JobSkillRequirement]:
    """Extract skill requirements from normalization result, falling back to raw skills.

    When skill-graph returns ``results`` without ``skill_requirements``, the raw
    detail records carry no is_required signal. We look up each raw skill's
    required-ness from the original extraction (carried in ``enrichment_ctx``)
    rather than fabricating ``is_required=True``. Skills not found in the map
    fall back to ``False`` (more conservative than ``True``).
    """
    skill_requirements = list(result.skill_requirements)
    if skill_requirements or not result.results:
        return skill_requirements

    required_lookup = enrichment_ctx.raw_skill_required_map if enrichment_ctx else {}

    return [
        JobSkillRequirement(
            skill_name=r.raw_skill,
            proficiency_level=SkillProficiencyLevel.UNSPECIFIED,
            is_required=required_lookup.get(r.raw_skill.lower(), False),
        )
        for r in result.results
        if r.raw_skill
    ]


_EnrichmentB64 = tuple[str | None, str | None, str | None]


def _convert_decisions_to_requirements(
    decisions: list[SkillDecisionSchema],
) -> list[JobSkillRequirement]:
    """Convert LLM clarification decisions to JobSkillRequirement objects.

    Handles MATCH, EXPAND, and NEW_SKILL decisions. NEW_SKILL decisions
    create requirements with the proposed canonical name (skill will be
    added to graph via SkillProposed event).
    """
    requirements: list[JobSkillRequirement] = []

    for decision in decisions:
        match decision.decision:
            case "MATCH":
                if decision.matched_canonical_id:
                    requirements.append(
                        JobSkillRequirement(
                            skill_id=decision.matched_canonical_id,
                            skill_name=decision.matched_canonical_name or decision.raw_skill,
                            proficiency_level=SkillProficiencyLevel(decision.matched_requirement_level),
                            is_required=decision.matched_is_required,
                        )
                    )
            case "EXPAND":
                requirements.extend(
                    JobSkillRequirement(
                        skill_id=expanded.canonical_skill_id,
                        skill_name=expanded.canonical_skill_name,
                        proficiency_level=SkillProficiencyLevel(expanded.requirement_level),
                        is_required=expanded.is_required,
                    )
                    for expanded in decision.expanded_skills
                )
            case "NEW_SKILL":
                if decision.proposed_skill:
                    requirements.append(
                        JobSkillRequirement(
                            skill_id="",
                            skill_name=decision.proposed_skill.display_name,
                            proficiency_level=SkillProficiencyLevel(decision.proposed_requirement_level),
                            is_required=decision.proposed_is_required,
                        )
                    )

    return requirements


def _build_stored_listing(
    ctx: EnrichmentContext,
    discovered: DiscoveredListing,
    skill_requirements: list[JobSkillRequirement],
    embeddings: _EnrichmentB64,
) -> StoredListing:
    """Build StoredListing from enrichment context and embeddings.

    Args:
        ctx: Enrichment context with listing metadata.
        discovered: Original discovered listing data.
        skill_requirements: Normalized skill requirements.
        embeddings: Tuple of (retrieval_b64, title_b64, skills_b64) embeddings.

    Returns:
        Complete StoredListing proto ready for publication.

    """
    retrieval_b64, title_b64, skills_b64 = embeddings
    retrieval_embeddings = _decode_all_embeddings(retrieval_b64)
    title_embedding = _decode_first_embedding(title_b64) or EmbeddingVector()
    skills_embedding = _decode_first_embedding(skills_b64) or EmbeddingVector()

    return build_stored_listing_from_context(
        ctx=ctx,
        discovered_data=discovered,
        skill_requirements=skill_requirements,
        embeddings=EmbeddingBundle(
            skills=skills_embedding,
            title=title_embedding,
            retrieval=retrieval_embeddings,
        ),
    )


async def _publish_enrichment_completed(
    ctx: EnrichmentContext,
    discovered: DiscoveredListing,
    skill_requirements: list[JobSkillRequirement],
    embeddings: _EnrichmentB64,
) -> None:
    """Build StoredListing from converged embeddings and publish EnrichmentCompleted directly.

    Used for the no-saga path where no DB state needs atomicity with the event.
    """
    stored_listing = _build_stored_listing(ctx, discovered, skill_requirements, embeddings)

    listing_ref = ListingReference(
        listing_id=ctx.listing_id or None,
        listing_url=ctx.listing_url,
        source=discovered.source,
        external_listing_id=discovered.external_id or None,
    )
    geocoded_coords: GeoCoordinates | None = None
    if ctx.geocoded_lat is not None and ctx.geocoded_lon is not None:
        geocoded_coords = GeoCoordinates(latitude=ctx.geocoded_lat, longitude=ctx.geocoded_lon)

    event = EnrichmentCompleted(
        metadata=create_event_metadata(settings.service_name, ctx.correlation_id),
        listing=listing_ref,
        stored_data=stored_listing,
        result=OperationOutcome(status=ProcessingStatus.COMPLETED),
        listing_id=ctx.listing_id,
        llm_model_id=settings.llm.chains.get(_LLM_CHAIN_EXTRACTION, settings.llm.provider).models[0].model,
        collection_version=get_manifest().get_entity_version(EntityType.JOB),
        geocoded_coordinates=geocoded_coords,
    )

    await kafka_client.publish(Topics.JOB_INGEST_ENRICHMENT_COMPLETED, event)


async def _create_embedding_saga_and_request(
    context: MessageContext,
    enrichment_ctx: EnrichmentContext,
    skill_requirements: list[JobSkillRequirement],
) -> None:
    """Create embedding saga and request embeddings for retrieval, title, and skills.

    This is the common path for both normal skill normalization and post-clarification.
    Creates the saga record, then requests up to 3 embeddings which trigger callbacks
    that complete the saga and publish the enrichment completed event.

    Skills embedding is computed via ml-compute DENSE encoding rather than relying
    on skill-graph aggregation, which depends on Qdrant population timing and
    produces zero vectors when no canonical matches are found. Title embedding is
    also DENSE-encoded for future occupation-based similarity features.
    """
    skill_names = [sr.skill_name for sr in skill_requirements if sr.skill_name]
    max_text_chars = settings.processing.max_embedding_text_chars
    skills_text = " ".join(skill_names)[:max_text_chars]
    discovered = DiscoveredListing.from_json(enrichment_ctx.discovered_json)
    retrieval_text = "\n\n".join(
        p
        for p in [
            enrichment_ctx.cleaned_title,
            enrichment_ctx.cleaned_company,
            discovered.description or "",
            skills_text,
        ]
        if p
    )[:max_text_chars]
    has_retrieval = bool(retrieval_text.strip())
    has_title = bool(enrichment_ctx.cleaned_title and enrichment_ctx.cleaned_title.strip())
    has_skills = bool(skills_text.strip())
    expected = sum([has_retrieval, has_title, has_skills])

    if expected == 0:
        await _publish_enrichment_completed(enrichment_ctx, discovered, skill_requirements, (None, None, None))
        return

    db = context.require_db_session()
    saga = EnrichmentEmbeddingSaga(
        listing_id=enrichment_ctx.listing_id,
        llm_model_id=settings.llm.chains.get(_LLM_CHAIN_EXTRACTION, settings.llm.provider).models[0].model,
        collection_version=get_manifest().get_entity_version(EntityType.JOB),
        enrichment_data_json=json.dumps(
            {
                "enrichment_ctx": asdict(enrichment_ctx),
                "skill_requirements": [sr.to_dict() for sr in skill_requirements],
            }
        ),
        expected_callbacks=expected,
        expires_at=datetime.now(UTC) + _SAGA_TTL,
    )
    saga = await _saga_repo.create(db, saga)
    await db.commit()

    saga_ctx = json.dumps({"saga_id": str(saga.id)}).encode("utf-8")
    publisher = get_embedding_publisher()

    # The saga row is committed above so concurrent callbacks observe it, but
    # if any embedding request fails inside the TaskGroup the row is left
    # PENDING and would block convergence forever. Mark it FAILED before
    # propagating the exception.
    try:
        async with asyncio.TaskGroup() as tg:
            if has_retrieval:
                tg.create_task(
                    publisher.request_embedding(
                        text=retrieval_text,
                        entity_id=enrichment_ctx.listing_id,
                        entity_type=EntityType.JOB,
                        spec=EmbeddingSpec(
                            requested_types=[EmbeddingType.MUVERA, EmbeddingType.SPARSE, EmbeddingType.COLBERT],
                            encoding_mode=EncodingMode.DOCUMENT,
                            publish_to_index=False,
                        ),
                        context=CommandContext(caller_context=saga_ctx, attributes={_ATTR_TYPE: "retrieval"}),
                    )
                )
            if has_title:
                tg.create_task(
                    publisher.request_embedding(
                        text=enrichment_ctx.cleaned_title[:max_text_chars],
                        entity_id=enrichment_ctx.listing_id,
                        entity_type=EntityType.JOB,
                        spec=EmbeddingSpec(
                            requested_types=[EmbeddingType.DENSE],
                            encoding_mode=EncodingMode.DOCUMENT,
                            publish_to_index=False,
                        ),
                        context=CommandContext(caller_context=saga_ctx, attributes={_ATTR_TYPE: "title"}),
                    )
                )
            if has_skills:
                tg.create_task(
                    publisher.request_embedding(
                        text=skills_text,
                        entity_id=enrichment_ctx.listing_id,
                        entity_type=EntityType.JOB,
                        spec=EmbeddingSpec(
                            requested_types=[EmbeddingType.DENSE],
                            encoding_mode=EncodingMode.DOCUMENT,
                            publish_to_index=False,
                        ),
                        context=CommandContext(caller_context=saga_ctx, attributes={_ATTR_TYPE: "skills"}),
                    )
                )
    except Exception as exc:
        await _saga_repo.fail(db, saga.id, reason=f"embedding request failed: {exc}")
        await db.commit()
        raise

    logger.info("Embedding saga created", saga_id=str(saga.id), listing_id=enrichment_ctx.listing_id)


async def _handle_skill_clarification(
    context: MessageContext,
    clarifications: list[SkillClarificationNeeded],
    enrichment_ctx: EnrichmentContext,
    confirmed_requirements: list[JobSkillRequirement],
) -> None:
    """Handle skill clarification via LLM and create embedding saga.

    Instead of re-requesting normalization (which creates an infinite loop),
    this converts LLM decisions directly to JobSkillRequirement objects and
    proceeds to create the embedding saga for retrieval, title, and skills embeddings.
    """
    clarification_service = get_skill_clarification_service()

    confirmed_skills: list[str] = []
    accepted_ids: set[str] = set()
    for req in confirmed_requirements:
        if req.skill_name:
            confirmed_skills.append(req.skill_name)
        if req.skill_id:
            accepted_ids.add(req.skill_id)

    discovered = DiscoveredListing.from_json(enrichment_ctx.discovered_json)
    clarification_context = ClarificationContext(
        job_title=enrichment_ctx.cleaned_title,
        job_id=enrichment_ctx.listing_id,
        confirmed_skills=confirmed_skills,
        already_accepted_skill_ids=accepted_ids,
        description_excerpt=discovered.description[:500] if discovered.description else "",
    )

    decisions = await clarification_service.clarify_skills(clarifications, clarification_context)

    clarified_requirements = _convert_decisions_to_requirements(decisions)
    all_requirements = list(confirmed_requirements) + clarified_requirements

    await clarification_service.publish_outcomes(decisions, enrichment_ctx.listing_id, enrichment_ctx.correlation_id)

    await _create_embedding_saga_and_request(context, enrichment_ctx, all_requirements)

    logger.info(
        "Skill clarification completed, embedding saga created",
        listing_id=enrichment_ctx.listing_id,
        clarification_count=len(clarifications),
        decision_count=len(decisions),
        total_skills=len(all_requirements),
    )
