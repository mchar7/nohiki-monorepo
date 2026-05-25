"""Service list constants used across health checks."""

from __future__ import annotations

from types import MappingProxyType
from typing import Final

INFRASTRUCTURE_SERVICES: Final[frozenset[str]] = frozenset(
    {
        "postgres",
        "redis",
        "kafka",
        "traefik",
    }
)

CORE_SERVICES: Final[frozenset[str]] = frozenset(
    {
        "user-auth-service",
        "user-pref-service",
        "user-upload-service",
        "user-entitlement-service",
        "bff-service",
        "doc-template-service",
        "doc-content-service",
        "doc-process-service",
        "job-query-composition-service",
        "job-ingest-schedule-service",
        "job-ingest-discovery-service",
        "job-ingest-enrichment-service",
        "job-storage-service",
        "job-correlation-evaluation-service",
        "notification-service",
        "ml-gateway-service",
        "ml-compute-service",
        "skill-graph-service",
    }
)

KAFKA_CONSUMER_SERVICES: Final[frozenset[str]] = frozenset(
    {
        "bff-service",
        "job-correlation-evaluation-service",
        "ml-gateway-service",
        "ml-compute-service",
        "job-storage-service",
        "notification-service",
        "job-ingest-enrichment-service",
        "job-ingest-discovery-service",
        "job-query-composition-service",
        "doc-template-service",
        "doc-content-service",
        "doc-process-service",
        "skill-graph-service",
        "user-pref-service",
        "user-upload-service",
        "user-entitlement-service",
    }
)

KAFKA_CONSUMER_GROUPS: Final[MappingProxyType[str, tuple[str, ...]]] = MappingProxyType(
    {
        "bff-service": ("bff-service-consumer-projections",),
        "job-ingest-discovery-service": ("job-ingest-discovery-service-consumer",),
        "job-ingest-enrichment-service": (
            "job-ingest-enrichment-service-consumer",
            "job-ingest-enrichment-service-skill-callback",
        ),
        "job-query-composition-service": ("job-query-composition-service-consumer",),
        "doc-template-service": ("doc-template-service-consumer-commands",),
        "doc-content-service": ("doc-content-service-consumer",),
        "doc-process-service": ("doc-process-service-consumer",),
        "job-storage-service": ("job-storage-service-consumer",),
        "job-correlation-evaluation-service": (
            "job-correlation-evaluation-service-consumer",
            "job-correlation-evaluation-service-consumer-projection",
        ),
        "notification-service": ("notification-service-consumer",),
        "ml-gateway-service": ("ml-gateway-service-consumer",),
        "ml-compute-service": ("ml-compute-service-consumer",),
        "skill-graph-service": ("skill-graph-service-consumer",),
        "user-pref-service": ("user-pref-service-consumer",),
        "user-upload-service": ("user-upload-service-consumer",),
        "user-entitlement-service": ("user-entitlement-service-consumer",),
    }
)

CRITICAL_CONSUMER_GROUPS_LAG: Final[tuple[str, ...]] = (
    "bff-service-consumer-projections",
    "job-storage-service-consumer",
    "job-ingest-enrichment-service-skill-callback",
    "job-correlation-evaluation-service-consumer",
    "job-correlation-evaluation-service-consumer-projection",
)

REQUIRED_SYSTEM_TEMPLATES: Final[frozenset[tuple[str, str]]] = frozenset(
    {
        ("resume", "resume"),
        ("cover_letter", "cover_letter"),
        ("messaging-service", "job_notification"),
    }
)

OBSERVABILITY_CONTAINER_NAMES: Final[frozenset[str]] = frozenset(
    {
        "nohiki-obs-prometheus",
        "nohiki-obs-grafana",
        "nohiki-obs-tempo",
        "nohiki-obs-mimir",
        "nohiki-obs-loki",
        "nohiki-obs-otel-collector",
        "nohiki-obs-pyroscope",
        "nohiki-obs-phoenix",
    }
)

GRAFANA_EXPECTED_DATASOURCES: Final[tuple[str, ...]] = (
    "Prometheus",
    "Loki",
    "Tempo",
    "Mimir",
    "Pyroscope",
)

GRAFANA_EXPECTED_DASHBOARD_UIDS: Final[tuple[str, ...]] = (
    "nohiki-overview",
    "nohiki-services",
    "nohiki-database",
    "nohiki-infrastructure",
    "nohiki-llm",
    "nohiki-providers",
    "nohiki-skill-canonicalization",
)
