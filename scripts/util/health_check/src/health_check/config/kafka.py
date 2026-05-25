"""Kafka-related configuration: topic derivation, error patterns, and indicators.

Topic names are derived at runtime from ``nohiki_kafka_client.Topics`` -- the
authoritative source -- rather than duplicated as constants. When a new topic
is added to the Topics class, the health checker automatically validates its
existence in Kafka without any manual sync.
"""

from __future__ import annotations

from typing import Final

from nohiki_kafka_client import Topics


def get_all_topic_names() -> frozenset[str]:
    """Derive the complete set of Kafka topic names from the canonical Topics class.

    Introspects every non-private attribute of ``Topics`` whose value is a
    ``str``, collecting all topic name strings. This approach ensures the health
    checker is always in sync with the authoritative topic registry.

    Returns:
        Frozenset of all topic name strings defined in ``Topics``.
    """
    return frozenset(
        value
        for attr_name in dir(Topics)
        if not attr_name.startswith("_") and isinstance(value := getattr(Topics, attr_name), str)
    )


KAFKA_ERROR_PATTERNS: Final[frozenset[str]] = frozenset(
    {
        "connection refused",
        "failed to resolve",
        "broker not available",
        "no brokers available",
        "consumererror",
        "consumer loop failed",
        "name or service not known",
        "heartbeat failed",
        "marking the coordinator dead",
        "coordinator is unavailable",
        "group coordinator is unavailable",
    }
)
"""Log substrings that indicate a Kafka connectivity or consumer error."""

KAFKA_TRANSIENT_ERROR_PATTERNS: Final[frozenset[str]] = frozenset(
    {
        "heartbeat failed",
        "marking the coordinator dead",
        "coordinator is unavailable",
        "group coordinator is unavailable",
    }
)
"""Subset of ``KAFKA_ERROR_PATTERNS`` that are transient and may self-resolve.

When a transient error appears alongside an active consumer group, the
event-flow check treats it as a warning rather than a hard failure.
"""

KAFKA_SUBSCRIPTION_INDICATORS: Final[frozenset[str]] = frozenset(
    {
        "subscribed to topics",
        "partitions assigned",
        "kafka is available",
    }
)
"""Log substrings confirming a service has successfully subscribed to Kafka."""

DB_ERROR_PATTERNS: Final[frozenset[str]] = frozenset(
    {
        "operationalerror",
        "could not connect to server",
        "connection to server",
        "fatal:",
    }
)
"""Log substrings indicating a database connectivity error in a service."""

DB_TYPE_MISMATCH_PATTERNS: Final[frozenset[str]] = frozenset(
    {
        "datatypemismatcherror",
        "column .* is of type .* but expression is of type",
        "invalid input syntax for type",
        "programmingerror",
    }
)
"""Log substrings indicating a database schema type mismatch."""

KAFKA_CONSUMER_GROUP_PREFIX_FILTER: Final[str] = "-service"
"""Consumer group names must contain this substring to be considered Nohiki groups."""

OUTBOX_CONNECTOR_NAMES: Final[tuple[str, ...]] = (
    # User domain
    "nohiki-outbox-user_auth",
    "nohiki-outbox-user_pref",
    "nohiki-outbox-user_upload",
    "nohiki-outbox-user_entitlement",
    # Job domain
    "nohiki-outbox-job_query",
    "nohiki-outbox-job_storage",
    "job-correlation-evaluation-service-wal",
    "nohiki-outbox-job_ingest_enrichment",
    # Doc domain
    "nohiki-outbox-doc_render",
    "nohiki-outbox-doc_schema",
    "nohiki-outbox-doc_template",
    # Skill domain
    "nohiki-outbox-skill_graph",
    # Notification
    "nohiki-outbox-notification",
)
"""Kafka Connect source connector names registered per service."""
