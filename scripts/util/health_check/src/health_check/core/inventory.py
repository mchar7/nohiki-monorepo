"""Fail-closed deployment metadata and external acceptance-evidence inventory."""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from health_check.platform.models import PlatformTarget

if TYPE_CHECKING:
    from collections.abc import Mapping

    from health_check.core.base import HealthCheck


CDC_END_TO_END_CAPABILITY: Final[str] = "cdc_end_to_end"
CDC_ACCEPTANCE_EVIDENCE_DEFAULT: Final[Path] = Path(".artifacts/k8s-local/live-cdc.json")
EVIDENCE_REQUIRED_IDS: Final[frozenset[str]] = frozenset({CDC_END_TO_END_CAPABILITY})


class EndpointClass(StrEnum):
    """External system class used by a check, without an endpoint value."""

    NONE = "none"
    HTTP = "http"
    DATABASE = "database"
    KAFKA = "kafka"
    VALKEY = "valkey"
    S3 = "s3"
    QDRANT = "qdrant"
    KUBERNETES = "kubernetes"


class CheckSeverity(StrEnum):
    """Operational severity of a failed check."""

    CRITICAL = "critical"
    WARNING = "warning"


class K3sDisposition(StrEnum):
    """How a registered check participates in the in-cluster k3s suite."""

    APPLICABLE = "applicable"
    ADAPTED = "adapted"
    INAPPLICABLE = "inapplicable"


@dataclass(frozen=True, slots=True)
class InventorySpec:
    """Value-free inventory fields that cannot safely be inferred from code."""

    endpoint_class: EndpointClass
    disposition: K3sDisposition
    severity: CheckSeverity
    evidence: tuple[str, ...]
    adaptation: str | None = None
    reason: str | None = None

    def validate(self, check_id: str) -> tuple[str, ...]:
        """Return deterministic validation errors for this specification."""
        errors: list[str] = []
        if not self.evidence or any(not item.strip() for item in self.evidence):
            errors.append(f"{check_id}: evidence must be non-empty")
        if self.disposition is K3sDisposition.ADAPTED and not self.adaptation:
            errors.append(f"{check_id}: adapted check requires an adaptation")
        if self.disposition is K3sDisposition.INAPPLICABLE and not self.reason:
            errors.append(f"{check_id}: inapplicable check requires a reason")
        if self.disposition is not K3sDisposition.ADAPTED and self.adaptation is not None:
            errors.append(f"{check_id}: only adapted checks may define an adaptation")
        if self.disposition is not K3sDisposition.INAPPLICABLE and self.reason is not None:
            errors.append(f"{check_id}: only inapplicable checks may define a reason")
        return tuple(errors)


@dataclass(frozen=True, slots=True)
class InventoryRecord:
    """Generated registry metadata for one concrete check."""

    check_id: str
    dependencies: frozenset[str]
    endpoint_class: EndpointClass
    platforms: frozenset[PlatformTarget]
    k3s_disposition: K3sDisposition
    k3s_adaptation: str | None
    k3s_reason: str | None
    severity: CheckSeverity
    timeout_seconds: float
    evidence: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class InventoryClosure:
    """Closure proof for a discovered registry and its required external evidence."""

    records: tuple[InventoryRecord, ...]
    registry_ids: frozenset[str]
    applicable_ids: frozenset[str]
    adapted_ids: frozenset[str]
    inapplicable_ids: frozenset[str]
    unknown_ids: frozenset[str]
    silent_skip_ids: frozenset[str]
    errors: tuple[str, ...]
    evidence_required_ids: frozenset[str]
    unexercised_ids: frozenset[str]
    evidence_errors: tuple[str, ...]

    @property
    def structurally_closed(self) -> bool:
        """Whether every registered check is classified exactly once."""
        classified = self.applicable_ids | self.adapted_ids | self.inapplicable_ids
        return (
            not self.errors
            and not self.unknown_ids
            and not self.silent_skip_ids
            and classified == self.registry_ids
            and not (self.applicable_ids & self.adapted_ids)
            and not (self.applicable_ids & self.inapplicable_ids)
            and not (self.adapted_ids & self.inapplicable_ids)
        )

    @property
    def closed(self) -> bool:
        """Whether structural classification and required acceptance evidence are complete."""
        return (
            self.structurally_closed
            and not self.evidence_errors
            and not self.unexercised_ids
            and self.unexercised_ids <= self.evidence_required_ids
        )


_A = K3sDisposition.APPLICABLE
_D = K3sDisposition.ADAPTED
_I = K3sDisposition.INAPPLICABLE
_C = CheckSeverity.CRITICAL
_W = CheckSeverity.WARNING

# This mapping is deliberately exhaustive. Discovery validates both directions so a
# newly added or deleted check cannot become an implicit runtime skip.
INVENTORY_SPECS: Final[Mapping[str, InventorySpec]] = MappingProxyType(
    {
        "infra_services": InventorySpec(
            EndpointClass.KUBERNETES,
            _D,
            _C,
            ("pod readiness and workload state",),
            adaptation="Kubernetes workload discovery replaces Compose container state",
        ),
        "platform_services": InventorySpec(
            EndpointClass.HTTP,
            _D,
            _C,
            ("service readiness endpoints",),
            adaptation="cluster Service DNS replaces host-published ports",
        ),
        "kafka_broker": InventorySpec(
            EndpointClass.KAFKA,
            _D,
            _C,
            ("broker metadata request",),
            adaptation="Strimzi bootstrap Service DNS",
        ),
        "postgres_connectivity": InventorySpec(
            EndpointClass.DATABASE,
            _D,
            _C,
            ("PostgreSQL readiness query",),
            adaptation="CNPG primary service discovery",
        ),
        "redis_health": InventorySpec(
            EndpointClass.VALKEY,
            _D,
            _C,
            ("Valkey PING and loading state",),
            adaptation="cluster Service DNS",
        ),
        "database_schemas": InventorySpec(EndpointClass.DATABASE, _A, _C, ("required schema catalog rows",)),
        "schema_columns": InventorySpec(EndpointClass.DATABASE, _A, _C, ("required column catalog rows",)),
        "alembic_migrations": InventorySpec(
            EndpointClass.DATABASE,
            _D,
            _C,
            ("exact expected and observed Alembic heads",),
            adaptation="expected-head manifest and CNPG primary query",
        ),
        "kafka_topics": InventorySpec(
            EndpointClass.KAFKA,
            _D,
            _C,
            ("canonical topic metadata",),
            adaptation="Strimzi bootstrap Service DNS",
        ),
        "kafka_consumers": InventorySpec(
            EndpointClass.KAFKA,
            _D,
            _C,
            ("consumer group membership",),
            adaptation="Strimzi bootstrap Service DNS",
        ),
        "consumer_lag": InventorySpec(
            EndpointClass.KAFKA,
            _D,
            _C,
            ("critical consumer group lag",),
            adaptation="Strimzi bootstrap Service DNS",
        ),
        "kafka_event_flow": InventorySpec(
            EndpointClass.HTTP,
            _D,
            _C,
            ("KafkaConnect and KafkaConnector status",),
            adaptation="Strimzi resources and Connect Service DNS",
        ),
        "debezium_connectors": InventorySpec(
            EndpointClass.HTTP,
            _D,
            _C,
            ("exact canonical inventory plus connector and task RUNNING status",),
            adaptation="Strimzi KafkaConnector status",
        ),
        "outbox_processing": InventorySpec(
            EndpointClass.DATABASE,
            _D,
            _C,
            ("retry, DLQ, outbox, and replication state",),
            adaptation="CNPG and Strimzi resource queries",
        ),
        "publication": InventorySpec(EndpointClass.DATABASE, _A, _C, ("publication table membership",)),
        "replication_slot": InventorySpec(EndpointClass.DATABASE, _A, _C, ("logical replication slot state",)),
        "core_services": InventorySpec(
            EndpointClass.HTTP,
            _D,
            _C,
            ("application readiness and metrics probes",),
            adaptation="cluster Service DNS and EndpointSlice discovery",
        ),
        "runtime_artifacts": InventorySpec(
            EndpointClass.KUBERNETES,
            _D,
            _C,
            ("semantic manifest readability and JSON root validity in six consuming runtimes",),
            adaptation="read-only validation through each consuming application pod",
        ),
        "service_dependencies": InventorySpec(
            EndpointClass.KUBERNETES,
            _D,
            _C,
            ("digest-pinned service-image module evidence",),
            adaptation="digest-pinned service-image init-container evidence",
        ),
        "stale_services": InventorySpec(
            EndpointClass.KAFKA,
            _D,
            _W,
            ("restart state and consumer heartbeats",),
            adaptation="pod status and Kafka consumer metadata",
        ),
        "skill_graph_seeded": InventorySpec(EndpointClass.DATABASE, _A, _C, ("skill and embedding row counts",)),
        "template_projections": InventorySpec(EndpointClass.DATABASE, _A, _C, ("required template projection rows",)),
        "qdrant_dimensions": InventorySpec(
            EndpointClass.QDRANT,
            _D,
            _C,
            ("collection vector dimensions",),
            adaptation="Qdrant Service DNS",
        ),
        "model_readiness": InventorySpec(
            EndpointClass.HTTP,
            _D,
            _C,
            ("ML compute readiness gate",),
            adaptation="ML compute Service DNS",
        ),
        "llm_workload_readiness": InventorySpec(
            EndpointClass.KUBERNETES,
            _A,
            _C,
            ("bounded workload readiness and redacted provider startup failure classification",),
        ),
        "pipeline_progress": InventorySpec(
            EndpointClass.DATABASE,
            _A,
            _C,
            ("read-only durable ingest saga aggregate progress",),
        ),
        "schedule_tick_continuity": InventorySpec(
            EndpointClass.DATABASE,
            _A,
            _C,
            ("active, due, and last-run schedule aggregates",),
        ),
        "replication_capacity": InventorySpec(
            EndpointClass.DATABASE,
            _A,
            _C,
            ("replication slot and WAL sender headroom",),
        ),
        "job_vector_population": InventorySpec(
            EndpointClass.QDRANT,
            _D,
            _C,
            ("embedded job and Qdrant point aggregates",),
            adaptation="Qdrant Service DNS",
        ),
        "profile_vector_population": InventorySpec(
            EndpointClass.QDRANT,
            _D,
            _C,
            ("embedded profile and Qdrant point aggregates",),
            adaptation="Qdrant Service DNS",
        ),
        "correlation_viability": InventorySpec(
            EndpointClass.DATABASE,
            _A,
            _C,
            ("eligible input and correlation output aggregates",),
        ),
        "k8s_deployment_rollout": InventorySpec(
            EndpointClass.KUBERNETES,
            _A,
            _C,
            (
                "nohiki.health/deployment-rollout/v1 ownership evidence",
                "Deployment, ReplicaSet, and pod rollout convergence",
                "declared and runtime immutable image digest consistency",
            ),
        ),
        "k8s_excessive_restarts": InventorySpec(EndpointClass.KUBERNETES, _A, _W, ("pod restart counts",)),
        "k8s_oom_killed": InventorySpec(EndpointClass.KUBERNETES, _A, _C, ("container termination reasons",)),
        "k8s_pending_pods": InventorySpec(EndpointClass.KUBERNETES, _A, _C, ("pod scheduling conditions",)),
        "k8s_platform_contracts": InventorySpec(
            EndpointClass.KUBERNETES,
            _A,
            _C,
            (
                "Gateway and HTTPRoute acceptance",
                "network policies",
                "operator and Flux release readiness",
                "immutable first-party image digests",
                "schedule tick workload",
            ),
        ),
        "k8s_flux_convergence": InventorySpec(
            EndpointClass.KUBERNETES,
            _A,
            _C,
            ("Flux Ready, Stalled, suspension, and observed generation state",),
        ),
        "k8s_gateway_api_readiness": InventorySpec(
            EndpointClass.KUBERNETES,
            _A,
            _C,
            ("Gateway acceptance/programming and HTTPRoute parent reference resolution",),
        ),
        "k8s_image_pull_failures": InventorySpec(
            EndpointClass.KUBERNETES,
            _A,
            _C,
            ("redacted image pull failure reasons across all pod container classes",),
        ),
        "observability_stack": InventorySpec(
            EndpointClass.HTTP,
            _D,
            _C,
            (
                "datasources and dashboards",
                "representative metric, log, and trace queries",
                "collector pipeline and scrape targets",
                "Phoenix disabled",
            ),
            adaptation="in-cluster observability Service DNS; Phoenix is intentionally disabled on k3s",
        ),
    }
)


def _cdc_acceptance_evidence_error() -> str | None:
    """Return why the external CDC acceptance proof is unusable, if anything."""
    evidence_path = Path(os.getenv("CDC_ACCEPTANCE_EVIDENCE") or CDC_ACCEPTANCE_EVIDENCE_DEFAULT)
    try:
        document = json.loads(evidence_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return f"{CDC_END_TO_END_CAPABILITY}: evidence file is absent: {evidence_path}"
    except OSError, UnicodeError, json.JSONDecodeError:
        return f"{CDC_END_TO_END_CAPABILITY}: evidence file is unreadable or malformed: {evidence_path}"

    from health_check.acceptance.live_cluster_cdc import evidence_is_valid

    if not evidence_is_valid(document):
        return (
            f"{CDC_END_TO_END_CAPABILITY}: evidence did not pass status, restart-identity, "
            "offset-continuity, projection, and cleanup validation"
        )
    return None


def build_inventory(checks: list[HealthCheck]) -> InventoryClosure:
    """Generate and validate inventory closure for discovered checks."""
    by_id = {check.metadata.check_id: check for check in checks}
    registry_ids = frozenset(by_id)
    spec_ids = frozenset(INVENTORY_SPECS)
    errors: list[str] = []
    records: list[InventoryRecord] = []
    silent: set[str] = set()

    for check_id in sorted(registry_ids & spec_ids):
        check = by_id[check_id]
        spec = INVENTORY_SPECS[check_id]
        errors.extend(spec.validate(check_id))
        missing_dependencies = check.metadata.depends_on - registry_ids
        if missing_dependencies:
            errors.append(f"{check_id}: unknown dependencies {sorted(missing_dependencies)}")
        if not math.isfinite(check.metadata.timeout_seconds) or check.metadata.timeout_seconds <= 0:
            errors.append(f"{check_id}: timeout must be finite and positive")
        if (
            spec.disposition is not K3sDisposition.INAPPLICABLE
            and PlatformTarget.KUBERNETES not in check.metadata.platforms
        ):
            silent.add(check_id)
        records.append(
            InventoryRecord(
                check_id=check_id,
                dependencies=check.metadata.depends_on,
                endpoint_class=spec.endpoint_class,
                platforms=check.metadata.platforms,
                k3s_disposition=spec.disposition,
                k3s_adaptation=spec.adaptation,
                k3s_reason=spec.reason,
                severity=spec.severity,
                timeout_seconds=check.metadata.timeout_seconds,
                evidence=spec.evidence,
            )
        )

    applicable = frozenset(r.check_id for r in records if r.k3s_disposition is _A)
    adapted = frozenset(r.check_id for r in records if r.k3s_disposition is _D)
    inapplicable = frozenset(r.check_id for r in records if r.k3s_disposition is _I)
    evidence_error = _cdc_acceptance_evidence_error()
    return InventoryClosure(
        records=tuple(records),
        registry_ids=registry_ids,
        applicable_ids=applicable,
        adapted_ids=adapted,
        inapplicable_ids=inapplicable,
        unknown_ids=registry_ids ^ spec_ids,
        silent_skip_ids=frozenset(silent),
        errors=tuple(errors),
        evidence_required_ids=EVIDENCE_REQUIRED_IDS,
        unexercised_ids=EVIDENCE_REQUIRED_IDS if evidence_error else frozenset(),
        evidence_errors=(evidence_error,) if evidence_error else (),
    )
