"""Database schema and column expectations for health checks.

Schema names are constants because importing 18 service packages to read their
individual ``config.py`` settings is impractical. These values change only when
a new service is added, at which point all deployment artifacts (compose files,
Helm charts, migrations) must also be updated -- a conscious release event.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Final


@dataclass(frozen=True, slots=True)
class SchemaExpectation:
    """Expected PostgreSQL schema with its owning service and minimum migration.

    Attributes:
        service: Canonical service name that owns this schema.
        migration: Minimum Alembic revision that must be present.
    """

    service: str
    migration: str


CRITICAL_SCHEMAS: Final[MappingProxyType[str, SchemaExpectation]] = MappingProxyType(
    {
        # User domain
        "user_auth_schema": SchemaExpectation(service="user-auth-service", migration="001"),
        "user_pref_schema": SchemaExpectation(service="user-pref-service", migration="001"),
        "user_upload_schema": SchemaExpectation(service="user-upload-service", migration="001"),
        "user_entitlement_schema": SchemaExpectation(service="user-entitlement-service", migration="001"),
        # Job domain
        "job_storage_schema": SchemaExpectation(service="job-storage-service", migration="001"),
        "job_schedule_schema": SchemaExpectation(service="job-ingest-schedule-service", migration="001"),
        "job_query_schema": SchemaExpectation(service="job-query-composition-service", migration="001"),
        "job_correlation_schema": SchemaExpectation(service="job-correlation-evaluation-service", migration="001"),
        # Skill domain
        "skill_graph_schema": SchemaExpectation(service="skill-graph-service", migration="001"),
        # Doc domain
        "doc_template_schema": SchemaExpectation(service="doc-template-service", migration="001"),
        # Notification
        "notification_schema": SchemaExpectation(service="notification-service", migration="001"),
        # Job ingest
        "job_ingest_enrichment_schema": SchemaExpectation(service="job-ingest-enrichment-service", migration="001"),
        # BFF
        "bff_schema": SchemaExpectation(service="bff-service", migration="001"),
    }
)

CRITICAL_COLUMNS: Final[MappingProxyType[str, frozenset[str]]] = MappingProxyType(
    {
        "job_storage_schema.listings": frozenset(
            {
                "id",
                "listing_url",
                "job_board_source",
                "title",
                "company_name",
                "collection_version",
                "skills_embedding",
                "title_embedding",
                "canonical_skill_ids",
                "required_skills",
                "raw_content_hash",
                "dedup_hash",
                "search_vector",
                "status",
            }
        ),
        "user_pref_schema.search_prefs": frozenset(
            {
                "id",
                "user_id",
                "pref_name",
                "search_keywords",
                "collection_version",
            }
        ),
        "bff_schema.job_correlation_projections": frozenset(
            {
                "id",
                "user_id",
                "pref_id",
                "listing_id",
                "fit_score",
                "status",
                "score_breakdown",
                "listing_title",
                "listing_url",
            }
        ),
    }
)

OUTBOX_PUBLICATION_NAME_PREFIX: Final[str] = "nohiki"
"""All CDC publications are expected to have names starting with this prefix."""

REPLICATION_SLOT_NAME_PREFIX: Final[str] = "nohiki"
"""All CDC replication slots are expected to have names starting with this prefix."""

NOHIKI_DB_NAME: Final[str] = "nohiki_db"
"""Primary PostgreSQL database name."""

NOHIKI_DB_USER: Final[str] = "postgres"
"""PostgreSQL superuser for health check queries."""
