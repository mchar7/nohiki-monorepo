"""Correlation service for CQRS operations - publishes feedback commands."""

from __future__ import annotations

from uuid import UUID

from nohiki.feedback.v1 import ScoreAdjustmentRequested, ScoreFeedbackRequested, ScoreFeedbackType
from nohiki.job.correlation.v1 import FeedbackRecorded, FeedbackType
from nohiki_db_utils import create_event_metadata
from nohiki_kafka_client import Topics
from nohiki_observability import get_logger
from uuid_utils.compat import uuid7

from bff_service.core.config import get_settings
from bff_service.core.kafka import kafka_client

logger = get_logger(__name__)
settings = get_settings()


class CorrelationService:
    """Service for correlation CQRS operations.

    Write operations publish command events to Kafka.
    """

    async def record_feedback_command(
        self,
        user_id: UUID,
        correlation_id: UUID,
        feedback_type: FeedbackType,
    ) -> str:
        """Publish feedback recorded command event.

        Args:
            user_id: User ID for authorization
            correlation_id: Correlation to record feedback for
            feedback_type: Protobuf FeedbackType enum

        Returns:
            request_id for async tracking

        """
        request_id = str(uuid7())

        event = FeedbackRecorded(
            metadata=create_event_metadata(settings.service_name, request_id),
            request_id=request_id,
            correlation_id=str(correlation_id),
            user_id=str(user_id),
            feedback_type=feedback_type,
        )

        await kafka_client.publish(
            Topics.JOB_CORRELATION_FEEDBACK_RECORDED,
            event,
            key=request_id,
        )

        logger.info(
            "Published feedback recorded command",
            user_id=str(user_id),
            correlation_id=str(correlation_id),
            feedback_type=feedback_type.name,
            request_id=request_id,
        )

        return request_id

    async def submit_score_feedback_command(
        self,
        user_id: UUID,
        correlation_id: UUID,
        feedback_type: ScoreFeedbackType,
    ) -> str:
        """Publish score feedback command event.

        Args:
            user_id: User ID for authorization
            correlation_id: Correlation to provide feedback for
            feedback_type: ScoreFeedbackType enum (GOOD, TOO_HIGH, TOO_LOW)

        Returns:
            request_id for async tracking

        """
        request_id = str(uuid7())

        event = ScoreFeedbackRequested(
            metadata=create_event_metadata(settings.service_name, request_id),
            request_id=request_id,
            correlation_id=str(correlation_id),
            user_id=str(user_id),
            feedback_type=feedback_type,
        )

        await kafka_client.publish(
            Topics.FEEDBACK_SCORE_FEEDBACK_REQUESTED,
            event,
            key=request_id,
        )

        logger.info(
            "Published score feedback command",
            user_id=str(user_id),
            correlation_id=str(correlation_id),
            feedback_type=feedback_type.name,
            request_id=request_id,
        )

        return request_id

    async def submit_score_adjustment_command(
        self,
        user_id: UUID,
        correlation_id: UUID,
        adjusted_score: float,
        reasoning: str,
    ) -> str:
        """Publish score adjustment command event.

        Args:
            user_id: User ID for authorization
            correlation_id: Correlation to adjust score for
            adjusted_score: User's corrected score (0.0-1.0)
            reasoning: User's explanation for the adjustment

        Returns:
            request_id for async tracking

        """
        request_id = str(uuid7())

        event = ScoreAdjustmentRequested(
            metadata=create_event_metadata(settings.service_name, request_id),
            request_id=request_id,
            correlation_id=str(correlation_id),
            user_id=str(user_id),
            original_score=0.0,  # Will be filled by the handler from DB
            adjusted_score=adjusted_score,
            reasoning=reasoning,
        )

        await kafka_client.publish(
            Topics.FEEDBACK_SCORE_ADJUSTMENT_REQUESTED,
            event,
            key=request_id,
        )

        logger.info(
            "Published score adjustment command",
            user_id=str(user_id),
            correlation_id=str(correlation_id),
            adjusted_score=adjusted_score,
            request_id=request_id,
        )

        return request_id
