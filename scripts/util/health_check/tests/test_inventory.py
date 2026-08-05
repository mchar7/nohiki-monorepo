"""Fail-closed tests for the in-cluster health inventory."""

from __future__ import annotations

import importlib
import json
import math
import pkgutil
from typing import cast
from urllib.parse import urlsplit

import pytest
from health_check.checks.infrastructure.platform_services import _KUBERNETES_ENDPOINTS
from health_check.cli.app import app
from health_check.core.base import HealthCheck
from health_check.core.inventory import (
    CheckSeverity,
    EndpointClass,
    InventorySpec,
    K3sDisposition,
    build_inventory,
)
from health_check.core.models import CheckCategory, CheckMetadata
from health_check.core.registry import CheckRegistry, _all_concrete_subclasses
from health_check.platform.kubernetes import KubernetesPlatform
from health_check.platform.models import PlatformTarget
from typer.testing import CliRunner


class _InventoryFixture:
    def __init__(
        self,
        check_id: str,
        *,
        platforms: frozenset[PlatformTarget] = frozenset({PlatformTarget.KUBERNETES}),
        depends_on: frozenset[str] = frozenset(),
        timeout_seconds: float = 5.0,
    ) -> None:
        self.metadata = CheckMetadata(
            check_id=check_id,
            name=check_id,
            category=CheckCategory.INFRASTRUCTURE,
            platforms=platforms,
            depends_on=depends_on,
            timeout_seconds=timeout_seconds,
            description="inventory fixture",
        )


def _inventory_check(
    check_id: str,
    *,
    platforms: frozenset[PlatformTarget] = frozenset({PlatformTarget.KUBERNETES}),
    depends_on: frozenset[str] = frozenset(),
    timeout_seconds: float = 5.0,
) -> HealthCheck:
    return cast(
        "HealthCheck",
        _InventoryFixture(
            check_id,
            platforms=platforms,
            depends_on=depends_on,
            timeout_seconds=timeout_seconds,
        ),
    )


def _registry() -> CheckRegistry:
    package = importlib.import_module("health_check.checks")
    for _, module_name, _ in pkgutil.walk_packages(
        list(package.__path__),
        prefix="health_check.checks.",
    ):
        importlib.import_module(module_name)
    registry = CheckRegistry()
    for check_type in _all_concrete_subclasses(HealthCheck):
        if check_type.__module__.startswith("health_check.checks."):
            registry.register(check_type())
    return registry


def test_real_registry_has_exactly_closed_k3s_partition() -> None:
    closure = _registry().inventory()

    assert closure.closed
    assert len(closure.registry_ids) == 41
    assert len(closure.applicable_ids | closure.adapted_ids) == 40
    assert closure.inapplicable_ids == frozenset({"cdc_end_to_end"})
    assert not closure.unknown_ids
    assert not closure.silent_skip_ids
    assert not closure.errors
    assert closure.registry_ids == (closure.applicable_ids | closure.adapted_ids | closure.inapplicable_ids)
    assert not (closure.applicable_ids & closure.adapted_ids)
    assert not (closure.applicable_ids & closure.inapplicable_ids)
    assert not (closure.adapted_ids & closure.inapplicable_ids)


def test_inventory_records_are_deterministic_and_metadata_complete() -> None:
    records = _registry().inventory().records

    assert [record.check_id for record in records] == sorted(record.check_id for record in records)
    assert {record.endpoint_class for record in records} <= set(EndpointClass)
    assert {record.severity for record in records} == {
        CheckSeverity.CRITICAL,
        CheckSeverity.WARNING,
    }
    assert all(record.evidence for record in records)
    assert all(item.strip() for record in records for item in record.evidence)
    assert all(math.isfinite(record.timeout_seconds) for record in records)
    assert all(record.timeout_seconds > 0 for record in records)


def test_every_adaptation_and_inapplicability_has_precise_evidence() -> None:
    records = _registry().inventory().records

    adapted = [record for record in records if record.k3s_disposition is K3sDisposition.ADAPTED]
    inapplicable = [record for record in records if record.k3s_disposition is K3sDisposition.INAPPLICABLE]
    expected_adaptations = {
        "alembic_migrations": "expected-head manifest and CNPG primary query",
        "consumer_lag": "Strimzi bootstrap Service DNS",
        "service_dependencies": "digest-pinned service-image init-container evidence",
        "core_services": "cluster Service DNS and EndpointSlice discovery",
        "debezium_connectors": "Strimzi KafkaConnector status",
        "infra_services": "Kubernetes workload discovery replaces Compose container state",
        "job_vector_population": "Qdrant Service DNS",
        "kafka_broker": "Strimzi bootstrap Service DNS",
        "kafka_consumers": "Strimzi bootstrap Service DNS",
        "kafka_event_flow": "Strimzi resources and Connect Service DNS",
        "kafka_topics": "Strimzi bootstrap Service DNS",
        "model_readiness": "ML compute Service DNS",
        "observability_stack": ("in-cluster observability Service DNS; Phoenix is intentionally disabled on k3s"),
        "outbox_processing": "CNPG and Strimzi resource queries",
        "platform_services": "cluster Service DNS replaces host-published ports",
        "postgres_connectivity": "CNPG primary service discovery",
        "profile_vector_population": "Qdrant Service DNS",
        "qdrant_dimensions": "Qdrant Service DNS",
        "redis_health": "cluster Service DNS",
        "runtime_artifacts": "read-only validation through each consuming application pod",
        "stale_services": "pod status and Kafka consumer metadata",
    }
    expected_reasons = {
        "cdc_end_to_end": "mutates application data; the verification Job is strictly non-mutating",
    }
    assert {record.check_id: record.k3s_adaptation for record in adapted} == expected_adaptations
    assert {record.check_id: record.k3s_reason for record in inapplicable} == expected_reasons
    for record in adapted:
        assert record.k3s_reason is None
        assert record.evidence
    for record in inapplicable:
        assert record.k3s_adaptation is None
        assert record.evidence


def test_k3s_runnable_checks_are_exactly_applicable_and_adapted() -> None:
    registry = _registry()
    closure = registry.inventory()

    assert {check.metadata.check_id for check in registry.get_k3s_checks()} == (
        closure.applicable_ids | closure.adapted_ids
    )
    assert "cdc_end_to_end" in closure.inapplicable_ids
    assert "cdc_end_to_end" not in {check.metadata.check_id for check in registry.get_k3s_checks()}
    assert "service_dependencies" in closure.adapted_ids
    assert not ({check.metadata.check_id for check in registry.get_k3s_checks()} & closure.inapplicable_ids)


def test_registry_rejects_requested_unknown_ids() -> None:
    registry = _registry()

    with pytest.raises(ValueError, match="does_not_exist"):
        registry.get_checks(check_ids=frozenset({"does_not_exist"}))


def test_inventory_rejects_unknown_registry_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from health_check.core import inventory

    monkeypatch.setattr(inventory, "INVENTORY_SPECS", {})
    closure = build_inventory([_inventory_check("unclassified")])

    assert closure.unknown_ids == frozenset({"unclassified"})
    assert not closure.closed


def test_inventory_rejects_silent_k3s_skip(monkeypatch: pytest.MonkeyPatch) -> None:
    from health_check.core import inventory

    monkeypatch.setattr(
        inventory,
        "INVENTORY_SPECS",
        {
            "compose_only": InventorySpec(
                EndpointClass.HTTP,
                K3sDisposition.APPLICABLE,
                CheckSeverity.CRITICAL,
                ("HTTP readiness response",),
            )
        },
    )
    closure = build_inventory(
        [
            _inventory_check(
                "compose_only",
                platforms=frozenset({PlatformTarget.COMPOSE}),
            )
        ]
    )

    assert closure.silent_skip_ids == frozenset({"compose_only"})
    assert not closure.closed


def test_inventory_rejects_unknown_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    from health_check.core import inventory

    monkeypatch.setattr(
        inventory,
        "INVENTORY_SPECS",
        {
            "dependent": InventorySpec(
                EndpointClass.DATABASE,
                K3sDisposition.APPLICABLE,
                CheckSeverity.CRITICAL,
                ("database query result",),
            )
        },
    )
    closure = build_inventory([_inventory_check("dependent", depends_on=frozenset({"missing"}))])

    assert closure.errors == ("dependent: unknown dependencies ['missing']",)
    assert not closure.closed


@pytest.mark.parametrize("timeout_seconds", [0.0, -1.0, math.inf, math.nan])
def test_inventory_rejects_non_positive_or_non_finite_timeout(
    monkeypatch: pytest.MonkeyPatch,
    timeout_seconds: float,
) -> None:
    from health_check.core import inventory

    monkeypatch.setattr(
        inventory,
        "INVENTORY_SPECS",
        {
            "timed": InventorySpec(
                EndpointClass.NONE,
                K3sDisposition.APPLICABLE,
                CheckSeverity.CRITICAL,
                ("deterministic evidence",),
            )
        },
    )
    closure = build_inventory([_inventory_check("timed", timeout_seconds=timeout_seconds)])

    assert not closure.closed
    assert any("timeout" in error for error in closure.errors)


def test_inventory_covers_every_health_category() -> None:
    registry = _registry()
    runnable_ids = registry.inventory().applicable_ids | registry.inventory().adapted_ids
    categories = {check.metadata.category for check in registry.all_checks if check.metadata.check_id in runnable_ids}

    assert categories == set(CheckCategory)


def test_migration_and_readiness_evidence_are_separate() -> None:
    records = {record.check_id: record for record in _registry().inventory().records}

    migration = records["alembic_migrations"]
    assert migration.k3s_disposition is K3sDisposition.ADAPTED
    assert any("expected" in item.lower() and "head" in item.lower() for item in migration.evidence)
    assert not any("readiness" in item.lower() for item in migration.evidence)
    assert "alembic_migrations" not in records["core_services"].dependencies


def test_observability_inventory_requires_signals_and_phoenix_disposition() -> None:
    record = next(record for record in _registry().inventory().records if record.check_id == "observability_stack")
    evidence = " ".join(record.evidence).lower()
    disposition = " ".join(part for part in (record.k3s_adaptation, record.k3s_reason) if part is not None).lower()

    assert record.k3s_disposition is K3sDisposition.ADAPTED
    assert "metric" in evidence
    assert "log" in evidence
    assert "trace" in evidence
    assert "scrape" in evidence or "target" in evidence
    assert "datasource" in evidence
    assert "dashboard" in evidence
    assert "phoenix" in evidence
    assert "phoenix" in disposition
    assert "disabled" in disposition


def test_kubernetes_adaptations_use_cluster_service_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("E2E_BASE_URL", raising=False)
    monkeypatch.delenv("KAFKA_BOOTSTRAP_SERVERS", raising=False)
    monkeypatch.setenv("K8S_LOCAL_MODE", "false")
    platform = KubernetesPlatform(namespace="nohiki")
    endpoint_hosts = {urlsplit(endpoint.url).hostname for endpoint in _KUBERNETES_ENDPOINTS}

    assert endpoint_hosts == {
        "rustfs",
        "qdrant",
        "gotenberg",
        "docling",
        "nohiki-connect-api",
    }
    assert urlsplit(platform.api_base_url).hostname == "bff-service"
    assert platform.kafka_bootstrap_server == "nohiki-kafka-bootstrap:9092"
    assert all(host not in {None, "localhost", "127.0.0.1"} for host in endpoint_hosts)
    assert "localhost" not in platform.api_base_url
    assert "localhost" not in platform.kafka_bootstrap_server


def test_inventory_cli_emits_closed_machine_readable_evidence() -> None:
    result = CliRunner().invoke(app, ["inventory", "--target", "k8s", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["target"] == "kubernetes"
    assert payload["closed"] is True
    assert payload["unknown_ids"] == []
    assert payload["silent_skip_ids"] == []
    assert payload["errors"] == []
    assert [record["id"] for record in payload["records"]] == sorted(payload["registry_ids"])
    assert all(record["evidence"] for record in payload["records"])


def test_inventory_cli_rejects_unknown_target() -> None:
    result = CliRunner().invoke(app, ["inventory", "--target", "compose", "--json"])

    assert result.exit_code != 0
    assert "inventory target must be k8s" in result.output
