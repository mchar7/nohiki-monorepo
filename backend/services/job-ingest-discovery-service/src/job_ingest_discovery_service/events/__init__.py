"""Event handlers for job-ingest-discovery-service.

Importing this module registers all Kafka handlers via decorator side effects.
"""

from job_ingest_discovery_service.events.handlers import start_event_consumer

__all__ = ["start_event_consumer"]
