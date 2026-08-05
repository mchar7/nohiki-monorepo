"""Kafka-related configuration: topic derivation, error patterns, and indicators.

Topic names are derived at runtime from ``nohiki_kafka_client.Topics`` -- the
authoritative source -- rather than duplicated as constants. When a new topic
is added to the Topics class, the health checker automatically validates its
existence in Kafka without any manual sync.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal

from nohiki_kafka_client import Topics

if TYPE_CHECKING:
    from health_check.platform.models import PlatformTarget


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


@dataclass(frozen=True)
class CdcConnector:
    """Kafka Connect source identity and its PostgreSQL resources."""

    name: str
    slot_name: str
    publication_name: str
    table_name: str
    connector_class: str = "io.debezium.connector.postgresql.PostgresConnector"


COMPOSE_CDC_CONNECTORS: Final[tuple[CdcConnector, ...]] = (
    CdcConnector(
        "user-auth-service-outbox", "user_auth_outbox_slot", "user_auth_outbox_pub", "user_auth_schema.outbox"
    ),
    CdcConnector(
        "user-pref-service-outbox", "user_pref_outbox_slot", "user_pref_outbox_pub", "user_pref_schema.outbox"
    ),
    CdcConnector(
        "user-upload-service-outbox",
        "user_upload_outbox_slot",
        "user_upload_outbox_pub",
        "user_upload_schema.outbox",
    ),
    CdcConnector(
        "user-entitlement-service-outbox",
        "user_entitlement_outbox_slot",
        "user_entitlement_outbox_pub",
        "user_entitlement_schema.outbox",
    ),
    CdcConnector(
        "job-query-composition-service-outbox",
        "job_query_composition_outbox_slot",
        "job_query_composition_outbox_pub",
        "job_query_schema.outbox",
    ),
    CdcConnector(
        "job-ingest-enrichment-service-outbox",
        "job_ingest_enrichment_outbox_slot",
        "job_ingest_enrichment_outbox_pub",
        "job_ingest_enrichment_schema.outbox",
    ),
    CdcConnector(
        "job-storage-service-outbox",
        "job_storage_outbox_slot",
        "job_storage_outbox_pub",
        "job_storage_schema.outbox",
    ),
    CdcConnector(
        "doc-template-service-outbox",
        "doc_template_outbox_slot",
        "doc_template_outbox_pub",
        "doc_template_schema.outbox",
    ),
    CdcConnector(
        "skill-graph-service-outbox",
        "skill_graph_outbox_slot",
        "skill_graph_outbox_pub",
        "skill_graph_schema.outbox",
    ),
    CdcConnector("bff-service-outbox", "bff_outbox_slot", "bff_outbox_pub", "bff_schema.outbox"),
    CdcConnector(
        "notification-service-outbox",
        "notification_outbox_slot",
        "notification_outbox_pub",
        "notification_schema.outbox",
    ),
    CdcConnector(
        "job-correlation-evaluation-service-wal",
        "job_correlation_wal_slot",
        "job_correlation_wal_pub",
        "job_correlation_schema.processed_events",
    ),
)
"""Compose CDC sources registered by the image startup script."""

KUBERNETES_CDC_CONNECTORS: Final[tuple[CdcConnector, ...]] = COMPOSE_CDC_CONNECTORS
"""Kubernetes CDC sources rendered by the Helm chart."""


KUBERNETES_SINK_CONNECTOR_NAMES: Final[tuple[str, ...]] = ("qdrant-embedding-sink",)
"""Kubernetes sink connectors rendered when the chart's Kafka Connect stack is enabled."""

SUPERSEDED_COMPOSE_CONNECTOR_NAMES: Final[frozenset[str]] = frozenset(
    {
        "nohiki-outbox-user_auth",
        "nohiki-outbox-user_pref",
        "nohiki-outbox-user_upload",
        "nohiki-outbox-user_entitlement",
        "nohiki-outbox-job_query",
        "nohiki-outbox-job_storage",
        "nohiki-outbox-job_correlation",
        "nohiki-outbox-job_ingest_enrichment",
        "nohiki-outbox-doc_render",
        "nohiki-outbox-doc_schema",
        "nohiki-outbox-doc_template",
        "nohiki-outbox-skill_graph",
        "nohiki-outbox-notification",
    }
)
"""Exact connector identities handled by the bounded Compose reconciliation recipe."""


def superseded_compose_resource_names(
    resource_kind: Literal["connector", "publication", "slot"],
) -> frozenset[str]:
    """Return the exact superseded resource identities the Compose recipe can remove."""
    if resource_kind == "connector":
        return SUPERSEDED_COMPOSE_CONNECTOR_NAMES
    suffixes = (name.removeprefix("nohiki-outbox-") for name in SUPERSEDED_COMPOSE_CONNECTOR_NAMES)
    if resource_kind == "publication":
        return frozenset(f"nohiki_outbox_pub_{suffix}" for suffix in suffixes)
    return frozenset(f"nohiki_outbox_slot_{suffix}" for suffix in suffixes)


def compose_reconciliation_covers(
    resource_kind: Literal["connector", "publication", "slot"],
    unexpected: list[str],
) -> bool:
    """Return whether every unexpected identity is inside the recipe's bounded inventory."""
    return bool(unexpected) and frozenset(unexpected).issubset(superseded_compose_resource_names(resource_kind))


def cdc_connectors_for(target: PlatformTarget) -> tuple[CdcConnector, ...]:
    """Return the exact CDC resource inventory for a deployment target."""
    if target.value == "compose":
        return COMPOSE_CDC_CONNECTORS
    return KUBERNETES_CDC_CONNECTORS


def connector_names_for(target: PlatformTarget) -> tuple[str, ...]:
    """Return every Kafka Connect identity expected for a deployment target."""
    names = tuple(connector.name for connector in cdc_connectors_for(target))
    if target.value == "kubernetes":
        return (*names, *KUBERNETES_SINK_CONNECTOR_NAMES)
    return names
