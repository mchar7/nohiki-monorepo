"""Kafka event handlers for feedback collection (ML_T11)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from nohiki.common.v1 import CallbackHeader
from nohiki.feedback.v1 import ScoreAdjustmentRequested, ScoreFeedbackRequested
from nohiki.job.correlation.v1 import (
    FeedbackRecorded,
    TrainingExportCallback,
    TrainingExportRequested,
    TrainingExportResult,
    TrainingSample,
)
from nohiki_db_utils import create_event_metadata
from nohiki_kafka_client import MessageContext, Topics
from nohiki_observability import get_logger

from job_correlation_evaluation_service.core.config import get_settings
from job_correlation_evaluation_service.core.kafka import kafka_client
from job_correlation_evaluation_service.repositories.correlation_repository import (
    CorrelationNotFoundError,
    CorrelationRepository,
)
from job_correlation_evaluation_service.repositories.feedback_repository import (
    FeedbackRepository,
    ManualAdjustmentCreate,
)
from job_correlation_evaluation_service.services.feedback_service import (
    CorrelationFeedbackService,
    TrainingExportSample,
)

logger = get_logger(__name__)

settings = get_settings()
feedback_group_id = f"{settings.kafka_consumer_group}-feedback"
export_group_id = f"{settings.kafka_consumer_group}-export"
score_feedback_group_id = f"{settings.kafka_consumer_group}-score-feedback"


def _parse_date(date_str: str | None, field_name: str) -> datetime | None:
    """Parse an optional ISO date string, logging warnings on invalid format."""
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str)
    except ValueError:
        logger.warning("Invalid date format", field_name=field_name, value=date_str)
        return None


def _build_training_sample(sample_data: TrainingExportSample) -> TrainingSample:
    """Build the callback message from a canonical training row."""
    return TrainingSample(
        correlation_id=sample_data["correlation_id"],
        label=sample_data["label"],
        features=sample_data["features"],
        query_id=sample_data["query_id"],
    )


@kafka_client.message_handler(
    Topics.JOB_CORRELATION_FEEDBACK_RECORDED,
    FeedbackRecorded,
    group_id=feedback_group_id,
)
@kafka_client.with_db_session()
async def handle_feedback_recorded(
    message: FeedbackRecorded,
    context: MessageContext,
) -> None:
    """Handle user feedback command from BFF.

    Updates correlation flags based on feedback type.
    """
    request_id = message.request_id
    correlation_id = message.correlation_id
    user_id = message.user_id
    feedback_type = message.feedback_type

    logger.info(
        "Processing feedback command",
        request_id=request_id,
        correlation_id=correlation_id,
        user_id=user_id,
        feedback_type=feedback_type.name,
    )

    db = context.require_db_session()
    repository = CorrelationRepository(db)
    service = CorrelationFeedbackService(repository)

    try:
        correlation = await service.record_feedback(
            correlation_id=UUID(correlation_id),
            feedback_type=feedback_type,
            user_id=UUID(user_id),
        )

        logger.info(
            "Feedback recorded",
            request_id=request_id,
            correlation_id=str(correlation.id),
            user_id=str(correlation.user_id),
        )

    except CorrelationNotFoundError:
        logger.warning(
            "Correlation not found for feedback",
            request_id=request_id,
            correlation_id=correlation_id,
        )


@kafka_client.message_handler(
    Topics.JOB_CORRELATION_TRAINING_EXPORT_REQUESTED,
    TrainingExportRequested,
    group_id=export_group_id,
)
@kafka_client.with_db_session()
async def handle_training_export_requested(
    message: TrainingExportRequested,
    context: MessageContext,
) -> None:
    """Handle training data export request.

    Queries correlations with feedback signals and publishes training samples.
    """
    operation_id = message.command.operation_id
    callback_topic = message.command.callback_topic
    limit = message.limit if message.limit > 0 else 10000

    metadata = message.metadata
    correlation_id = metadata.correlation_id if metadata and metadata.correlation_id else operation_id

    logger.info(
        "Processing training export request",
        operation_id=operation_id,
        limit=limit,
        callback_topic=callback_topic,
    )

    min_date = _parse_date(message.min_date, "min_date")
    max_date = _parse_date(message.max_date, "max_date")

    db = context.require_db_session()
    repository = CorrelationRepository(db)
    service = CorrelationFeedbackService(repository)
    samples_data = await service.export_training_data(
        min_date=min_date,
        max_date=max_date,
        limit=limit,
    )

    training_samples = [_build_training_sample(s) for s in samples_data]

    export_event = TrainingExportCallback(
        metadata=create_event_metadata(settings.service_name, correlation_id),
        callback=CallbackHeader(
            operation_id=operation_id,
            caller_context=message.command.caller_context,
            attributes=dict(message.command.attributes) if message.command.attributes else {},
        ),
        success=TrainingExportResult(
            total_samples=len(training_samples),
            samples=training_samples,
        ),
    )

    await kafka_client.publish(callback_topic, export_event, key=operation_id)

    logger.info(
        "Training data exported",
        operation_id=operation_id,
        sample_count=len(training_samples),
        callback_topic=callback_topic,
    )


@kafka_client.message_handler(
    Topics.FEEDBACK_SCORE_FEEDBACK_REQUESTED,
    ScoreFeedbackRequested,
    group_id=score_feedback_group_id,
)
@kafka_client.with_db_session()
async def handle_score_feedback_requested(
    message: ScoreFeedbackRequested,
    context: MessageContext,
) -> None:
    """Handle asymmetric score feedback command from BFF.

    Creates feedback record indicating whether a correlation score
    is accurate (GOOD), too high (TOO_HIGH), or too low (TOO_LOW).
    """
    request_id = message.request_id
    correlation_id = message.correlation_id
    user_id = message.user_id
    feedback_type = message.feedback_type

    logger.info(
        "Processing score feedback command",
        request_id=request_id,
        correlation_id=correlation_id,
        user_id=user_id,
        feedback_type=feedback_type.name,
    )

    db = context.require_db_session()
    feedback_repo = FeedbackRepository(db)
    correlation_repo = CorrelationRepository(db)
    correlation_uuid = UUID(correlation_id)
    user_uuid = UUID(user_id)
    correlation = await correlation_repo.get_by_id(correlation_uuid, user_uuid)
    if correlation is None:
        logger.warning(
            "Correlation not found for score feedback",
            request_id=request_id,
            correlation_id=correlation_id,
            user_id=user_id,
        )
        return

    feedback = await feedback_repo.create_asymmetric_feedback(
        correlation_id=UUID(correlation_id),
        user_id=UUID(user_id),
        feedback_type=feedback_type,
        request_id=request_id,
    )

    logger.info(
        "Score feedback recorded",
        request_id=request_id,
        feedback_id=str(feedback.id),
        correlation_id=correlation_id,
        user_id=user_id,
        feedback_type=feedback_type.name,
    )


@kafka_client.message_handler(
    Topics.FEEDBACK_SCORE_ADJUSTMENT_REQUESTED,
    ScoreAdjustmentRequested,
    group_id=score_feedback_group_id,
)
@kafka_client.with_db_session()
async def handle_score_adjustment_requested(
    message: ScoreAdjustmentRequested,
    context: MessageContext,
) -> None:
    """Handle manual score adjustment command from BFF.

    Creates adjustment record with user-provided score and reasoning.
    The original_score is fetched from the correlation record.
    """
    request_id = message.request_id
    correlation_id = message.correlation_id
    user_id = message.user_id
    adjusted_score = message.adjusted_score
    reasoning = message.reasoning

    logger.info(
        "Processing score adjustment command",
        request_id=request_id,
        correlation_id=correlation_id,
        user_id=user_id,
        adjusted_score=adjusted_score,
    )

    db = context.require_db_session()
    correlation_repo = CorrelationRepository(db)
    feedback_repo = FeedbackRepository(db)

    correlation = await correlation_repo.get_by_id(UUID(correlation_id), UUID(user_id))
    if correlation is None:
        logger.warning(
            "Correlation not found for score adjustment",
            request_id=request_id,
            correlation_id=correlation_id,
        )
        return

    original_score = float(correlation.correlation_score) / 100.0 if correlation.correlation_score is not None else 0.0

    adjustment = await feedback_repo.create_manual_adjustment(
        UUID(correlation_id),
        UUID(user_id),
        ManualAdjustmentCreate(
            original_score=original_score,
            adjusted_score=adjusted_score,
            reasoning=reasoning,
            request_id=request_id,
        ),
    )

    logger.info(
        "Score adjustment recorded",
        request_id=request_id,
        adjustment_id=str(adjustment.id),
        correlation_id=correlation_id,
        user_id=user_id,
        original_score=original_score,
        adjusted_score=adjusted_score,
    )
