"""Event handlers for job-ingest-enrichment-service.

Importing this module registers all Kafka handlers via decorator side effects.
Both command handlers AND callback handlers must be imported for the saga to work.
"""

from job_ingest_enrichment_service.events import callbacks
from job_ingest_enrichment_service.events.handlers import start_event_consumer

__all__ = ["callbacks", "start_event_consumer"]
