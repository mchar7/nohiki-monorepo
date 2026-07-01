"""Correlations API routes - feedback recording via CQRS."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from nohiki.feedback.v1 import ScoreFeedbackType
from nohiki.job.correlation.v1 import FeedbackType
from nohiki_domain_utils import BetterprotoEnumAdapter
from nohiki_observability import get_logger
from pydantic import BaseModel, ConfigDict, Field

from bff_service.api.deps.auth import get_current_user_id_from_cookie
from bff_service.api.schemas import CommandAcceptedResponse
from bff_service.services.correlation_service import CorrelationService

logger = get_logger(__name__)

router = APIRouter()


# Request/Response Schemas


class RecordFeedbackRequest(BaseModel):
    """Request to record user feedback on a correlation."""

    feedback_type: Annotated[FeedbackType, BetterprotoEnumAdapter(exclude_unspecified=True)]


class ScoreFeedbackRequest(BaseModel):
    """Request to submit asymmetric score feedback on a correlation."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    feedback_type: Annotated[ScoreFeedbackType, BetterprotoEnumAdapter(exclude_unspecified=True)] = Field(
        description="Feedback type: GOOD (accurate), TOO_HIGH (overstated), TOO_LOW (understated)",
    )


class ScoreAdjustmentRequest(BaseModel):
    """Request to submit a manual score adjustment with reasoning."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    adjusted_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Corrected score value (0.0 = irrelevant, 1.0 = perfect match)",
        examples=[0.35, 0.72, 0.85],
    )
    reasoning: str = Field(
        min_length=10,
        max_length=1000,
        description="Brief explanation for the adjustment",
        examples=["Skills don't match the listed requirements", "Location is actually acceptable"],
    )


# Dependencies


def get_correlation_service() -> CorrelationService:
    """Get correlation service instance."""
    return CorrelationService()


# Routes


@router.post(
    "/{correlation_id}/feedback",
    response_model=CommandAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def record_feedback(
    correlation_id: UUID,
    data: RecordFeedbackRequest,
    user_id: Annotated[UUID, Depends(get_current_user_id_from_cookie)],
    service: Annotated[CorrelationService, Depends(get_correlation_service)],
) -> CommandAcceptedResponse:
    """Record user feedback on a correlation.

    Feedback types:
    - **viewed**: User viewed the job listing
    - **saved**: User saved the job for later
    - **applied**: User applied to the job (strongest positive signal)
    - **dismissed**: User dismissed the job (negative signal)
    - **liked**: User explicitly liked the match
    - **disliked**: User explicitly disliked the match

    Returns 202 Accepted with request_id for async completion tracking.
    """
    request_id = await service.record_feedback_command(
        user_id=user_id,
        correlation_id=correlation_id,
        feedback_type=data.feedback_type,
    )
    return CommandAcceptedResponse(request_id=request_id)


@router.post(
    "/{correlation_id}/score-feedback",
    response_model=CommandAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_score_feedback(
    correlation_id: UUID,
    data: ScoreFeedbackRequest,
    user_id: Annotated[UUID, Depends(get_current_user_id_from_cookie)],
    service: Annotated[CorrelationService, Depends(get_correlation_service)],
) -> CommandAcceptedResponse:
    """Submit asymmetric score feedback on a correlation.

    Feedback types:
    - **GOOD**: Score accurately reflects match quality
    - **TOO_HIGH**: Score overstates the match (should be lower)
    - **TOO_LOW**: Score understates the match (should be higher)

    This feedback is used to improve the L2R model and identify low-quality listings.

    Returns 202 Accepted with request_id for async completion tracking.
    """
    request_id = await service.submit_score_feedback_command(
        user_id=user_id,
        correlation_id=correlation_id,
        feedback_type=data.feedback_type,
    )
    return CommandAcceptedResponse(request_id=request_id)


@router.post(
    "/{correlation_id}/adjust-score",
    response_model=CommandAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_score_adjustment(
    correlation_id: UUID,
    data: ScoreAdjustmentRequest,
    user_id: Annotated[UUID, Depends(get_current_user_id_from_cookie)],
    service: Annotated[CorrelationService, Depends(get_correlation_service)],
) -> CommandAcceptedResponse:
    """Submit a manual score adjustment with reasoning.

    Provides richer signal than asymmetric feedback by specifying the exact
    score the user believes is correct along with their reasoning.

    Score range: 0.0 (completely irrelevant) to 1.0 (perfect match)

    Returns 202 Accepted with request_id for async completion tracking.
    """
    request_id = await service.submit_score_adjustment_command(
        user_id=user_id,
        correlation_id=correlation_id,
        adjusted_score=data.adjusted_score,
        reasoning=data.reasoning,
    )
    return CommandAcceptedResponse(request_id=request_id)
