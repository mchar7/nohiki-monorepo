"""Repository layer for job-correlation-evaluation-service."""

from job_correlation_evaluation_service.repositories.correlation_repository import (
    CorrelationRepository,
)
from job_correlation_evaluation_service.repositories.feedback_repository import (
    FeedbackRepository,
    ListingFeedbackAggregate,
)
from job_correlation_evaluation_service.repositories.projection_repository import (
    ProfileProjectionRepository,
)

__all__ = [
    "CorrelationRepository",
    "FeedbackRepository",
    "ListingFeedbackAggregate",
    "ProfileProjectionRepository",
]
