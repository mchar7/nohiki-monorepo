"""Database package for job-ingest-schedule-service."""

from job_ingest_schedule_service.db.models import Base, IngestionSchedule

__all__ = ["Base", "IngestionSchedule"]
