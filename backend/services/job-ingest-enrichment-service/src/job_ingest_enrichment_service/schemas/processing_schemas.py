"""Processing schemas for job processor service."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class LLMProcessingResponse:
    """Response from LLM processing."""

    structured_data: dict[str, Any]
    success: bool
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class JobReference:
    """Reference to a job for processing."""

    listing_url: str
    source: str
    raw_listing_id: str


@dataclass(frozen=True, slots=True)
class ProfileReference:
    """Reference to a user profile for processing."""

    user_id: str
    pref_id: str


@dataclass(slots=True)
class ProcessingContext:
    """Context for job processing operations."""

    correlation_id: str
    job_reference: JobReference
    profile_reference: ProfileReference
    retry_count: int = 0
    timeout_seconds: int = 120
