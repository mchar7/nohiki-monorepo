"""Event handlers for bff-service.

Importing this module registers all Kafka handlers via decorator side effects.

Handler packages:
- projections/: Domain-specific projection handlers (accounts, profiles, listings, etc.)
"""

from nohiki_observability import get_logger

from bff_service.core.config import get_settings
from bff_service.core.kafka import kafka_client
from bff_service.events.projections import (
    doc_content,
    doc_template,
    job_correlation,
    job_listing,
    skill,
    user_auth,
    user_pref,
    user_upload,
)

__all__ = [
    "doc_content",
    "doc_template",
    "job_correlation",
    "job_listing",
    "skill",
    "start_event_consumer",
    "user_auth",
    "user_pref",
    "user_upload",
]

logger = get_logger(__name__)
settings = get_settings()


def start_event_consumer() -> None:
    """Start the Kafka event consumer."""
    logger.info("Starting event consumer", service=settings.service_name)
    kafka_client.start_consumers()
