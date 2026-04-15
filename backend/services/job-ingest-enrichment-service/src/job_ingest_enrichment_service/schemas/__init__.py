"""Schemas for job-ingest-enrichment-service."""

from job_ingest_enrichment_service.schemas.compensation import (
    CompensationBoundEstimate,
    CompensationEstimate,
)
from job_ingest_enrichment_service.schemas.experience import (
    ExperienceExtraction,
    ExperienceYearsBound,
)
from job_ingest_enrichment_service.schemas.extraction import JobExtractionSchema
from job_ingest_enrichment_service.schemas.location import LocationExtraction
from job_ingest_enrichment_service.schemas.processing_schemas import (
    JobReference,
    LLMProcessingResponse,
    ProcessingContext,
    ProfileReference,
)
from job_ingest_enrichment_service.schemas.skills import ExtractedSkill

__all__ = [
    "CompensationBoundEstimate",
    "CompensationEstimate",
    "ExperienceExtraction",
    "ExperienceYearsBound",
    "ExtractedSkill",
    "JobExtractionSchema",
    "JobReference",
    "LLMProcessingResponse",
    "LocationExtraction",
    "ProcessingContext",
    "ProfileReference",
]
