"""Kafka event handlers for skill-graph-service.

Importing this module registers all Kafka handlers via decorator side effects.
"""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING, Final
from uuid import UUID

import sqlalchemy as sa

if TYPE_CHECKING:
    from nohiki_qdrant_client import QdrantVectorClient
from nohiki.common.v1 import CommandHeader, ErrorInfo
from nohiki.ml.v1 import (
    BatchEmbeddingCallback,
    BatchEmbeddingItem,
    EncodingMode,
    EntityType,
)
from nohiki.skill.v1 import (
    AliasLearned,
    RawSkillWithLevel,
    SkillGraphSeeded,
    SkillMentionCreated,
    SkillMentionSource,
    SkillNormalizationCallback,
    SkillNormalizationRequested,
    SkillProficiencyLevel,
    SkillProposed,
)
from nohiki.skill.v1 import (
    SkillNormalizationResult as SkillNormalizationResultProto,
)
from nohiki_common_exceptions import DataNotAvailableError, ValidationError
from nohiki_db_utils import check_and_mark_processed, create_event_metadata
from nohiki_embedding_client import BatchEmbeddingItemResult
from nohiki_kafka_client import CommandContext, MessageContext, Topics, callback_from_command
from nohiki_observability import get_logger

from skill_graph_service.core.config import get_manifest, get_qdrant_client, get_readiness_gate, get_settings
from skill_graph_service.core.embedding import (
    get_batch_embedding_publisher,
    get_normalization_embedding_publisher,
)
from skill_graph_service.core.kafka import kafka_client
from skill_graph_service.db.models import SCHEMA_NAME, SkillNode
from skill_graph_service.db.repositories import fetch_all_skills_for_embedding
from skill_graph_service.events.publishers import publish_skill_created, publish_skill_created_batch
from skill_graph_service.services.alias_service import AliasUpsertParams, upsert_alias
from skill_graph_service.services.bootstrap_publisher import publish_skill_created_events_for_bootstrap
from skill_graph_service.services.embedding_service import (
    EmbeddingVariant,
    build_occupation_vector_points,
    build_skill_batch_items,
    build_skill_vector_points,
    skill_variant_point_id,
)
from skill_graph_service.services.normalization import (
    BatchNormalizationResult,
    NormalizationEmbeddingState,
    assemble_batch_normalization_result,
    deserialize_deterministic_match_result,
    resolve_canonical_skill_ids,
    run_deterministic_matching,
    run_semantic_qdrant_search,
    serialize_skill_result,
)
from skill_graph_service.services.normalization_adapters import QdrantSemanticAdapter
from skill_graph_service.services.skill_governance import SkillProposalParams, process_skill_proposal

logger = get_logger(__name__)
settings = get_settings()

_ALIAS_DYNAMIC_SOURCE_VERSION: Final[str] = "dynamic"

# Batch request admission accepts 100 items; each skill expands to three variants,
# so 33 whole skills fit per request (99 items).
_BOOTSTRAP_BATCH_SIZE: Final[int] = 33


async def _claim_event_once(
    message: SkillMentionCreated | AliasLearned | SkillProposed | SkillGraphSeeded,
    context: MessageContext,
    handler_name: str,
) -> bool:
    """Atomically claim a state-changing event in the handler transaction."""
    event_id = message.metadata.event_id if message.metadata else ""
    if not isinstance(event_id, str) or not event_id:
        logger.warning("Event has no event_id; processing without deduplication", handler=handler_name)
        return True
    return await check_and_mark_processed(
        context.require_db_session(),
        SCHEMA_NAME,
        event_id,
        handler_name,
    )


async def _get_embedded_skill_ids(
    qdrant: QdrantVectorClient,
    collection_name: str,
) -> set[UUID]:
    """Query Qdrant for skill IDs with all required embedding variants.

    A skill is complete only when its deterministic label, description, and
    alternative-label points all exist. Qdrant is the source of truth for
    embedding status.

    Args:
        qdrant: QdrantVectorClient instance.
        collection_name: Qdrant collection name for skills.

    Returns:
        Set of skill UUIDs with all three embeddings in Qdrant.

    """
    point_ids_by_entity: dict[UUID, set[str]] = {}
    offset = None
    batch_size = 1000

    while True:
        records, next_offset = await qdrant.raw_client.scroll(
            collection_name=collection_name,
            limit=batch_size,
            offset=offset,
            with_payload=["entity_id"],
            with_vectors=False,
        )
        for record in records:
            if record.payload and (entity_id := record.payload.get("entity_id")):
                skill_id = UUID(entity_id)
                point_ids_by_entity.setdefault(skill_id, set()).add(str(record.id))

        if next_offset is None:
            break
        offset = next_offset

    return {
        skill_id
        for skill_id, point_ids in point_ids_by_entity.items()
        if all(skill_variant_point_id(skill_id, variant) in point_ids for variant in EmbeddingVariant)
    }


@kafka_client.message_handler(
    Topics.SKILL_BATCH_EMBEDDING_CALLBACK,
    BatchEmbeddingCallback,
    group_id="skill-graph-batch-embedding-callback-primary",
)
async def handle_batch_embedding_callback(
    message: BatchEmbeddingCallback,
    _context: MessageContext,
) -> None:
    """Receive batch embedding results for skills/occupations; upsert to Qdrant.

    Routes by entity_type to appropriate vector point builder and collection.
    Qdrant is the source of truth for embedding status. No DB update needed.
    """
    if (success_payload := message.success) is not None:
        results = [BatchEmbeddingItemResult.from_result_item(r) for r in success_payload.results]
        manifest = get_manifest()
        qdrant = get_qdrant_client()

        match message.entity_type:
            case EntityType.SKILL:
                collection_name = manifest.get_collection_name(EntityType.SKILL)
                points = build_skill_vector_points(results)
                entity_label = "skill"
            case EntityType.OCCUPATION:
                collection_name = manifest.get_collection_name(EntityType.OCCUPATION)
                points = build_occupation_vector_points(results)
                entity_label = "occupation"
            case _:
                msg = f"Unsupported entity type in batch embedding callback: {message.entity_type}"
                raise ValidationError(msg)

        upserted_batch = await qdrant.upsert_vector_points_batch(
            collection_name=collection_name,
            points=points,
        )

        logger.info(
            "Upserted batch embeddings",
            entity_type=entity_label,
            count=upserted_batch,
            unique_entities=len({r.entity_id for r in results}),
        )
    elif (error_payload := message.error) is not None:
        logger.error(
            "Batch embedding failed",
            entity_type=message.entity_type.name if message.entity_type else "unknown",
            error_code=error_payload.error_code,
            error_message=error_payload.error_message,
            retryable=error_payload.retryable,
        )
    else:
        msg = "Empty batch embedding callback result"
        raise ValidationError(msg)


@kafka_client.message_handler(
    Topics.SKILL_GRAPH_SEEDED,
    SkillGraphSeeded,
    group_id="skill-graph-bootstrap-seeded-primary",
)
@kafka_client.with_db_session()
async def handle_skill_graph_seeded(
    message: SkillGraphSeeded,
    context: MessageContext,
) -> None:
    """Publish SKILL_CREATED events and trigger batch embedding for seeded skills.

    Two responsibilities:
    1. Publish SKILL_CREATED events for all seeded skills (enables BFF projections)
    2. Request batch embeddings for skills not yet vectorized (enables Qdrant search)
    """
    if getattr(message, "metadata", None) is None:
        logger.warning(
            "Event has no event_id; processing without deduplication",
            handler="handle_skill_graph_seeded",
        )
    elif not await _claim_event_once(message, context, "handle_skill_graph_seeded"):
        return
    db = context.require_db_session()
    publisher = get_batch_embedding_publisher()

    logger.info(
        "SkillGraphSeeded received -- publishing events + initiating embeddings",
        source_version=message.source_version,
        skills_seeded=message.skills_seeded,
    )

    # --- STEP 1: Publish SKILL_CREATED events in the handler transaction ---
    # The processed-event claim must commit only after all outbox batches and
    # embedding commands finish; otherwise a crash would permanently skip work.
    result = await publish_skill_created_events_for_bootstrap(
        db,
        skill_created_publisher=publish_skill_created,
        skill_created_batch_publisher=publish_skill_created_batch,
        commit_batches=False,
    )

    logger.info(
        "Published SKILL_CREATED events for all seeded skills",
        total_published=result.total_published,
        batch_count=result.batch_count,
    )

    # --- STEP 2: Request batch embeddings for skills not yet in Qdrant ---
    all_skills = await fetch_all_skills_for_embedding(db)

    # Query Qdrant for existing embedded skill entity_ids (source of truth)
    manifest = get_manifest()
    collection_name = manifest.get_collection_name(EntityType.SKILL)
    qdrant = get_qdrant_client()
    existing_skill_ids = await _get_embedded_skill_ids(qdrant, collection_name)

    # Filter out already-embedded skills
    skills = [s for s in all_skills if s.id not in existing_skill_ids]
    total_batches = (len(skills) + _BOOTSTRAP_BATCH_SIZE - 1) // _BOOTSTRAP_BATCH_SIZE

    logger.info(
        "Embedding bootstrap started",
        total_skills_in_db=len(all_skills),
        already_embedded=len(existing_skill_ids),
        skills_to_embed=len(skills),
        total_batches=total_batches,
    )

    if not skills:
        logger.info("All skills already embedded in Qdrant, skipping embedding requests")
        return

    published_batches = 0
    for offset in range(0, len(skills), _BOOTSTRAP_BATCH_SIZE):
        items: list[BatchEmbeddingItem] = []
        for skill in skills[offset : offset + _BOOTSTRAP_BATCH_SIZE]:
            items.extend(
                build_skill_batch_items(
                    skill_id=skill.id,
                    preferred_label=skill.preferred_label,
                    description=skill.description,
                    alt_labels=skill.alt_labels,
                )
            )
        await publisher.request_batch_embedding(
            items=items,
            entity_type=EntityType.SKILL,
            encoding_mode=EncodingMode.DOCUMENT,
        )
        published_batches += 1

    logger.info(
        "Published all bootstrap batches -- awaiting async callbacks",
        batch_count=published_batches,
        total_skills=len(skills),
    )


@kafka_client.message_handler(
    Topics.SKILL_MENTION_CREATED,
    SkillMentionCreated,
    group_id=settings.kafka_consumer_group,
    preserve_partition_order=False,
)
@kafka_client.with_db_session()
async def handle_skill_mention_created(message: SkillMentionCreated, context: MessageContext) -> None:
    """Update occurrence counts for canonical skill."""
    if not message.match:
        logger.debug("SkillMentionCreated has no match, skipping count update")
        return

    if not message.mention:
        logger.debug("SkillMentionCreated has no mention, skipping count update")
        return

    canonical_id = message.match.canonical_id
    source_type = message.mention.source_type

    if not await _claim_event_once(message, context, "handle_skill_mention_created"):
        return

    db = context.require_db_session()
    stmt = (
        sa.update(SkillNode)
        .where(SkillNode.id == canonical_id)
        .values(
            mention_count=SkillNode.mention_count + 1,
            last_seen_at=sa.func.now(),
        )
    )

    match source_type:
        case SkillMentionSource.JOB:
            stmt = stmt.values(job_count=SkillNode.job_count + 1)
        case SkillMentionSource.PROFILE:
            stmt = stmt.values(profile_count=SkillNode.profile_count + 1)

    await db.execute(stmt)

    logger.debug(
        "Updated skill mention counts",
        skill_id=canonical_id,
        source_type=source_type.name if source_type else "unknown",
    )


def _build_normalization_success_callback(
    original_command: CommandHeader,
    batch_result: BatchNormalizationResult,
    collection_version: str,
    correlation_id: str | None,
) -> SkillNormalizationCallback:
    """Build a successful SkillNormalizationCallback from a completed batch result."""
    return SkillNormalizationCallback(
        metadata=create_event_metadata(settings.service_name, correlation_id),
        callback=callback_from_command(original_command),
        success=SkillNormalizationResultProto(
            canonical_skill_ids=batch_result.canonical_skill_ids,
            skills_embedding=batch_result.aggregated_embedding,
            results=batch_result.results,
            requires_clarification=batch_result.requires_clarification,
            clarifications=batch_result.clarifications,
            skill_requirements=batch_result.skill_requirements,
            collection_version=collection_version,
        ),
    )


async def _publish_normalization_validation_error(
    message: SkillNormalizationRequested,
    error_message: str,
) -> None:
    correlation_id = message.metadata.correlation_id if message.metadata else None
    callback = SkillNormalizationCallback(
        metadata=create_event_metadata(settings.service_name, correlation_id),
        callback=callback_from_command(message.command),
        error=ErrorInfo(
            error_code="INVALID_SKILL_NORMALIZATION_REQUEST",
            error_message=error_message,
            retryable=False,
        ),
    )
    await kafka_client.publish(topic=message.command.callback_topic, message=callback)


@kafka_client.message_handler(
    Topics.SKILL_NORMALIZATION_REQUESTED,
    SkillNormalizationRequested,
    group_id=f"{settings.service_name}-normalization",
    preserve_partition_order=False,
)
@kafka_client.with_db_session()
async def handle_skill_normalization_requested(
    message: SkillNormalizationRequested,
    context: MessageContext,
) -> None:
    """Normalise skills using deterministic matching first, with semantic fallback.

    Runs exact, alias, and Jaccard matching concurrently across all input skills.
    When every skill matches deterministically the callback is published
    immediately. When any skill remains unmatched, embeddings are requested
    for those skills and the callback is deferred until the result arrives.

    Raises:
        DataNotAvailableError: When the skill graph is not yet ready (Qdrant
            has no embeddings). Triggers exponential backoff retry so the
            message is re-processed once seeding completes.
    """
    raw_skill_items = list(message.raw_skills_with_levels)
    if raw_skill_items:
        raw_skills = [item.raw_skill for item in raw_skill_items]
        if message.raw_skills and list(message.raw_skills) != raw_skills:
            await _publish_normalization_validation_error(
                message,
                "raw_skills and raw_skills_with_levels must contain the same ordered names",
            )
            return
    else:
        raw_skills = list(message.raw_skills)
        raw_skill_items = [
            RawSkillWithLevel(
                raw_skill=raw,
                proficiency_level=SkillProficiencyLevel.UNSPECIFIED,
                is_required=False,
            )
            for raw in raw_skills
        ]

    raw_mode = bool(raw_skills)
    canonical_mode = bool(message.canonical_skill_ids)
    if raw_mode == canonical_mode:
        await _publish_normalization_validation_error(
            message,
            "Exactly one non-empty skill input mode is required",
        )
        return
    raw_skill_metadata = [(item.raw_skill, int(item.proficiency_level), item.is_required) for item in raw_skill_items]

    gate = get_readiness_gate()
    if not gate.is_ready:
        raise DataNotAvailableError(
            resource_type="SkillEmbeddingCollection",
            resource_id="skills",
            source="SkillEmbeddingReadinessGate",
        )

    manifest = get_manifest()
    collection_version = manifest.get_entity_version(EntityType.SKILL)
    correlation_id = message.metadata.correlation_id if message.metadata else None

    if canonical_mode:
        try:
            batch_result = await resolve_canonical_skill_ids(
                list(message.canonical_skill_ids),
                context.require_session_factory(),
                collection_version,
                get_qdrant_client(),
            )
        except (ValueError, ValidationError) as exc:
            await _publish_normalization_validation_error(message, str(exc))
            return
        callback = _build_normalization_success_callback(
            original_command=message.command,
            batch_result=batch_result,
            collection_version=collection_version,
            correlation_id=correlation_id,
        )
        await kafka_client.publish(topic=message.command.callback_topic, message=callback)
        return

    industry_hint: str | None = None
    if message.job_context and message.job_context.industry:
        industry_hint = message.job_context.industry.strip().lower()
    det_result = await run_deterministic_matching(
        raw_skills=raw_skills,
        session_factory=context.require_session_factory(),
        context_hint=industry_hint,
    )

    if det_result.all_matched:
        batch_result = await assemble_batch_normalization_result(
            deterministic_result=det_result,
            semantic_results={},
            collection_version=collection_version,
            qdrant=get_qdrant_client(),
            raw_skill_metadata=raw_skill_metadata,
        )
        callback = _build_normalization_success_callback(
            original_command=message.command,
            batch_result=batch_result,
            collection_version=collection_version,
            correlation_id=correlation_id,
        )
        await kafka_client.publish(topic=message.command.callback_topic, message=callback)
        logger.info(
            "Skill normalisation complete -- all skills matched deterministically",
            operation_id=message.command.operation_id,
            input_count=len(raw_skills),
            confident_count=len(batch_result.canonical_skill_ids),
        )
        return

    state = NormalizationEmbeddingState(
        requester_operation_id=message.command.operation_id,
        requester_callback_topic=message.command.callback_topic,
        requester_caller_context_b64=base64.b64encode(message.command.caller_context).decode("ascii"),
        requester_attributes=dict(message.command.attributes) if message.command.attributes else {},
        raw_skills=raw_skills,
        matched_results_by_pos={
            str(pos): serialize_skill_result(match) for pos, _, match in det_result.skill_results if match is not None
        },
        unmatched_skill_pairs=[[pos, norm] for pos, norm in det_result.unmatched],
        collection_version=collection_version,
        industry_hint=industry_hint,
        raw_skill_metadata=raw_skill_metadata,
    )
    items = [
        BatchEmbeddingItem(
            point_id=f"norm-{pos}",
            entity_id=f"norm-{pos}",
            text=norm,
            item_attributes={"position": str(pos)},
        )
        for pos, norm in det_result.unmatched
    ]
    operation_id = await get_normalization_embedding_publisher().request_batch_embedding(
        items=items,
        entity_type=EntityType.SKILL,
        encoding_mode=EncodingMode.QUERY,
        context=CommandContext(caller_context=state.to_bytes()),
    )
    logger.info(
        "Skill normalisation deferred -- awaiting embedding callback for unmatched skills",
        operation_id=operation_id,
        input_count=len(raw_skills),
        matched_count=len(det_result.skill_results) - len(det_result.unmatched),
        unmatched_count=len(det_result.unmatched),
    )


@kafka_client.message_handler(
    Topics.SKILL_NORMALIZATION_EMBEDDING_CALLBACK,
    BatchEmbeddingCallback,
    group_id="skill-normalization-embedding-primary",
)
@kafka_client.with_db_session()
async def handle_normalization_embedding_callback(
    message: BatchEmbeddingCallback,
    _context: MessageContext,
) -> None:
    """Complete skill normalisation using vector similarity search on received embeddings.

    Reconstructs normalisation context from caller_context, searches Qdrant for
    the closest canonical skills, assembles the final result, and publishes the
    callback to the original requester. On embedding failure, propagates the
    error rather than silently dropping it.
    """
    if not message.callback:
        msg = "Missing callback header in normalization embedding callback"
        raise ValidationError(msg)

    state = NormalizationEmbeddingState.from_bytes(message.callback.caller_context)
    original_command = CommandHeader(
        operation_id=state.requester_operation_id,
        callback_topic=state.requester_callback_topic,
        caller_context=base64.b64decode(state.requester_caller_context_b64),
        attributes=state.requester_attributes,
    )
    correlation_id = message.metadata.correlation_id if message.metadata else None

    if (success_payload := message.success) is not None:
        det_match = deserialize_deterministic_match_result(state)
        qdrant = get_qdrant_client()
        manifest = get_manifest()
        qdrant_adapter = QdrantSemanticAdapter(
            qdrant,
            manifest.get_collection_name(EntityType.SKILL),
        )
        semantic_results = await run_semantic_qdrant_search(
            unmatched=det_match.unmatched,
            embedding_results=list(success_payload.results),
            qdrant=qdrant_adapter,
        )
        batch_result = await assemble_batch_normalization_result(
            deterministic_result=det_match,
            semantic_results=semantic_results,
            collection_version=state.collection_version,
            qdrant=get_qdrant_client(),
            raw_skill_metadata=state.raw_skill_metadata,
        )
        callback = _build_normalization_success_callback(
            original_command=original_command,
            batch_result=batch_result,
            collection_version=state.collection_version,
            correlation_id=correlation_id,
        )
        await kafka_client.publish(topic=state.requester_callback_topic, message=callback)
        logger.info(
            "Skill normalisation complete with semantic fallback",
            operation_id=message.callback.operation_id if message.callback else None,
            input_count=len(state.raw_skills),
            confident_count=len(batch_result.canonical_skill_ids),
            requires_clarification=batch_result.requires_clarification,
        )
    elif (error_payload := message.error) is not None:
        error_callback = SkillNormalizationCallback(
            metadata=create_event_metadata(settings.service_name, correlation_id),
            callback=callback_from_command(original_command),
            error=ErrorInfo(
                error_code="EMBEDDING_FAILED",
                error_message=error_payload.error_message,
                retryable=error_payload.retryable,
            ),
        )
        await kafka_client.publish(topic=state.requester_callback_topic, message=error_callback)
        logger.error(
            "Skill normalisation failed -- propagating embedding error to original requester",
            operation_id=message.callback.operation_id if message.callback else None,
            error_code=error_payload.error_code,
            error_message=error_payload.error_message,
        )
    else:
        msg = "Empty normalization embedding callback result"
        raise ValidationError(msg)


@kafka_client.message_handler(
    Topics.SKILL_ALIAS_LEARNED,
    AliasLearned,
    group_id=f"{settings.service_name}-alias",
    preserve_partition_order=False,
)
@kafka_client.with_db_session()
async def handle_alias_learned(message: AliasLearned, context: MessageContext) -> None:
    """Handle AliasLearned event - upsert alias to database."""
    if not await _claim_event_once(message, context, "handle_alias_learned"):
        return
    params = AliasUpsertParams(
        alias_text=message.alias_text,
        canonical_skill_id=UUID(message.canonical_skill_id),
        source=message.source,
        source_version=_ALIAS_DYNAMIC_SOURCE_VERSION,
        context_hint=message.context_hint or None,
        confidence=message.confidence,
        source_job_id=UUID(message.source_job_id) if message.source_job_id else None,
    )
    await upsert_alias(context.require_db_session(), params)

    logger.info(
        "Processed AliasLearned",
        alias=message.alias_text,
        canonical_id=message.canonical_skill_id,
    )


@kafka_client.message_handler(
    Topics.SKILL_PROPOSED,
    SkillProposed,
    group_id=f"{settings.service_name}-proposed",
    preserve_partition_order=False,
)
@kafka_client.with_db_session()
async def handle_skill_proposed(message: SkillProposed, context: MessageContext) -> None:
    """Handle SkillProposed event: process proposal then embed newly created skills."""
    if not await _claim_event_once(message, context, "handle_skill_proposed"):
        return
    qdrant = get_qdrant_client()

    params = SkillProposalParams(
        canonical_name=message.proposal.canonical_name,
        display_name=message.proposal.display_name,
        suggested_aliases=list(message.proposal.suggested_aliases),
        category=message.proposal.category or None,
        description=message.proposal.description or None,
        reuse_level=message.proposal.reuse_level or None,
        source_job_id=message.source_job_id or None,
        proposed_by=message.source,
        embedding=list(message.embedding.dense.values) if message.embedding and message.embedding.dense else None,
    )
    status, msg, skill_id = await process_skill_proposal(
        context.require_db_session(),
        qdrant,
        params,
        skill_created_publisher=publish_skill_created,
    )

    logger.info(
        "Processed SkillProposed",
        canonical_name=message.proposal.canonical_name,
        status=status,
        message=msg,
    )

    if status == "auto_approved" and skill_id is not None:
        manifest = get_manifest()
        collection_version = manifest.get_entity_version(EntityType.SKILL)
        items = build_skill_batch_items(
            skill_id=skill_id,
            preferred_label=message.proposal.display_name or message.proposal.canonical_name,
            description=message.proposal.description or None,
            alt_labels=list(message.proposal.suggested_aliases),
        )
        operation_id = await get_batch_embedding_publisher().request_batch_embedding(
            items=items,
            entity_type=EntityType.SKILL,
            encoding_mode=EncodingMode.DOCUMENT,
        )
        logger.info(
            "Published triple embedding for auto-approved skill",
            skill_id=str(skill_id),
            canonical_name=message.proposal.canonical_name,
            collection_version=collection_version,
            operation_id=operation_id,
        )


def start_event_consumer() -> None:
    """Start the Kafka event consumer."""
    logger.info("Starting event consumer", service=settings.service_name)
    kafka_client.start_consumers()
