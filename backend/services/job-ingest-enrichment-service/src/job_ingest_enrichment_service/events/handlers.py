"""Command handlers for job-ingest-enrichment-service.

Importing this module registers Kafka handlers via decorator side effects.
The callbacks module must also be imported to register callback handlers.
"""

from __future__ import annotations

from nohiki.job.listing.v1 import ListingAccepted
from nohiki_kafka_client import MessageContext, RateLimitConfig, Topics
from nohiki_observability import get_logger

from job_ingest_enrichment_service.core.config import get_settings
from job_ingest_enrichment_service.core.kafka import kafka_client
from job_ingest_enrichment_service.core.rate_limiting import LazyRateLimitMiddleware
from job_ingest_enrichment_service.services.processor_service import process_job_enrichment

logger = get_logger(__name__)
settings = get_settings()

# Create lazy-loading rate limit middleware for LLM calls
_rate_limit_middleware = (
    LazyRateLimitMiddleware(
        service_name=settings.service_name,
        redis_url=str(settings.redis.dsn),
        config=RateLimitConfig(
            key="llm:enrichment",
            requests_per_window=settings.rate_limit.requests_per_window,
            window_seconds=settings.rate_limit.window_seconds,
        ),
    )
    if settings.rate_limit.enabled
    else None
)


@kafka_client.with_resilience(
    max_retries=30,
    retry_backoff_ms=60000,
    max_backoff_ms=120000,
)
@kafka_client.message_handler(
    Topics.JOB_LISTING_ACCEPTED,
    ListingAccepted,
    group_id=settings.kafka.consumer_group,
    middleware=[_rate_limit_middleware] if _rate_limit_middleware else [],
    preserve_partition_order=False,
)
async def handle_listing_accepted(
    message: ListingAccepted,
    _context: MessageContext,
) -> None:
    """Handle accepted listings for enrichment."""
    metadata = message.metadata
    listing = message.listing

    if metadata is None:
        msg = "ListingAccepted.metadata is required"
        raise ValueError(msg)
    if listing is None:
        msg = "ListingAccepted.listing is required"
        raise ValueError(msg)
    if message.discovered_data is None:
        msg = "ListingAccepted.discovered_data is required"
        raise ValueError(msg)

    correlation_id = metadata.correlation_id
    if not correlation_id:
        msg = "ListingAccepted.metadata.correlation_id is required"
        raise ValueError(msg)

    logger.info(
        "Received listing accepted event",
        correlation_id=correlation_id,
        listing_url=listing.listing_url,
        source=listing.source,
    )

    result = await process_job_enrichment(
        discovered_data=message.discovered_data,
        listing_reference=listing,
        correlation_id=correlation_id,
    )

    if result:
        logger.info(
            "Job enrichment initiated",
            listing_url=listing.listing_url,
            title=result.get("title", ""),
            correlation_id=correlation_id,
        )
    else:
        logger.warning(
            "Job enrichment failed",
            listing_url=listing.listing_url,
            correlation_id=correlation_id,
        )


def start_event_consumer() -> None:
    """Start the Kafka event consumer."""
    logger.info("Starting event consumer", service=settings.service_name)
    kafka_client.start_consumers()
