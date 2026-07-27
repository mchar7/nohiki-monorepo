"""Read-only Kubernetes delivery, routing, operator, and image contract checks."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Final

import psycopg
import redis
from aiokafka import AIOKafkaConsumer

from health_check.config.kafka import get_all_topic_names
from health_check.core.base import HealthCheck
from health_check.core.models import (
    CheckCategory,
    CheckMetadata,
    CheckResult,
    CheckStatus,
)
from health_check.platform.kubernetes import _run_kubectl
from health_check.platform.models import PlatformTarget
from health_check.platform.protocol import Platform

_METADATA: Final = CheckMetadata(
    check_id="k8s_platform_contracts",
    name="Kubernetes Platform Contracts",
    category=CheckCategory.KUBERNETES,
    platforms=frozenset({PlatformTarget.KUBERNETES}),
    depends_on=frozenset({"k8s_pending_pods", "observability_stack"}),
    timeout_seconds=60.0,
    description="Verify routing, network policy, operators, Flux releases, immutable images, and tick delivery.",
)

_REQUIRED_QUERIES: Final[tuple[tuple[str, str, str], ...]] = (
    ("Gateway", "nohiki", "gateways.gateway.networking.k8s.io"),
    ("HTTPRoute", "nohiki", "httproutes.gateway.networking.k8s.io"),
    ("NetworkPolicy", "nohiki", "networkpolicies.networking.k8s.io"),
    ("Strimzi Kafka", "nohiki", "kafkas.kafka.strimzi.io"),
    ("CNPG cluster", "nohiki", "clusters.postgresql.cnpg.io"),
    ("OpenTelemetry collector", "nohiki", "opentelemetrycollectors.opentelemetry.io"),
    ("Grafana", "nohiki", "grafanas.grafana.integreatly.org"),
    ("Flux Kustomization", "flux-system", "kustomizations.kustomize.toolkit.fluxcd.io"),
    ("Flux HelmRelease", "flux-system", "helmreleases.helm.toolkit.fluxcd.io"),
    ("schedule tick", "nohiki", "cronjobs.batch"),
)


def _items(namespace: str, resource: str) -> tuple[list[dict[str, object]], str | None]:
    code, stdout, stderr = _run_kubectl(["get", resource, "-o", "json"], namespace=namespace)
    if code != 0:
        return [], stderr.strip() or f"kubectl get {resource} failed"
    try:
        document = json.loads(stdout)
    except json.JSONDecodeError as exc:
        return [], f"invalid {resource} JSON: {exc}"
    items = document.get("items") if isinstance(document, dict) else None
    if not isinstance(items, list):
        return [], f"{resource} response has no item list"
    return [item for item in items if isinstance(item, dict)], None


def _container_images(item: dict[str, object]) -> tuple[str, ...]:
    spec = item.get("spec")
    if not isinstance(spec, dict):
        return ()
    template = spec.get("template")
    if isinstance(template, dict):
        pod_spec = template.get("spec")
    else:
        job_template = spec.get("jobTemplate")
        nested = job_template.get("spec") if isinstance(job_template, dict) else None
        pod_template = nested.get("template") if isinstance(nested, dict) else None
        pod_spec = pod_template.get("spec") if isinstance(pod_template, dict) else None
    if not isinstance(pod_spec, dict):
        return ()
    init_containers = pod_spec.get("initContainers")
    containers = pod_spec.get("containers")
    candidates = (
        *(init_containers if isinstance(init_containers, list) else []),
        *(containers if isinstance(containers, list) else []),
    )
    return tuple(
        image
        for container in candidates
        if isinstance(container, dict) and isinstance((image := container.get("image")), str)
    )


def _database_contract() -> str | None:
    """Verify PostgreSQL, schemas, publication, and replication slots read-only."""
    try:
        with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as connection:
            connection.execute("SET default_transaction_read_only = on")
            row = connection.execute(
                "SELECT "
                "(SELECT count(*) FROM information_schema.schemata WHERE schema_name NOT LIKE 'pg_%'), "
                "(SELECT count(*) FROM pg_publication), "
                "(SELECT count(*) FROM pg_replication_slots WHERE slot_type = 'logical')"
            ).fetchone()
            if row is None:
                return "PostgreSQL contract query returned no row"
            schema_count, publication_count, slot_count = row
    except (KeyError, psycopg.Error) as exc:
        return f"PostgreSQL contract failed: {exc}"
    if not schema_count or not publication_count or not slot_count:
        return (
            "PostgreSQL contract incomplete: "
            f"schemas={schema_count}, publications={publication_count}, logical_slots={slot_count}"
        )
    return None


def _valkey_contract() -> str | None:
    """Verify Valkey responds and is not loading its dataset."""
    try:
        client = redis.Redis.from_url(os.getenv("VALKEY_URL", "redis://valkey:6379"), socket_timeout=5)
        if not client.ping() or client.info("persistence").get("loading"):
            return "Valkey is unavailable or loading its dataset"
    except redis.RedisError as exc:
        return f"Valkey contract failed: {exc}"
    return None


async def _kafka_contract() -> str | None:
    """Verify broker metadata and every canonical retry/DLQ/topic name."""
    consumer = AIOKafkaConsumer(bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "nohiki-kafka-bootstrap:9092"))
    try:
        await consumer.start()
        existing = await consumer.topics()
    except (OSError, RuntimeError) as exc:
        return f"Kafka metadata failed: {exc}"
    finally:
        await consumer.stop()
    missing = get_all_topic_names() - existing
    if missing:
        return f"Kafka topics missing: {sorted(missing)}"
    if not any("retry" in topic for topic in existing) or not any("dlq" in topic for topic in existing):
        return "Kafka retry/DLQ topics are missing"
    return None


class KubernetesPlatformContractsCheck(HealthCheck):
    """Verify the in-cluster platform contract without mutating resources."""

    @property
    def metadata(self) -> CheckMetadata:
        """Return static metadata for the Kubernetes platform contract check."""
        return _METADATA

    async def execute(self, _platform: Platform, /) -> CheckResult:
        """Verify the Kubernetes platform contracts.

        Args:
            _platform: Platform adapter required by the health-check contract; unused here.

        Returns:
            The aggregate platform contract result.
        """
        failures: list[str] = []
        evidence: list[str] = []
        async with asyncio.TaskGroup() as tg:
            database_task = tg.create_task(asyncio.to_thread(_database_contract))
            valkey_task = tg.create_task(asyncio.to_thread(_valkey_contract))
        database_failure, valkey_failure = database_task.result(), valkey_task.result()
        kafka_failure = await _kafka_contract()
        failures.extend(failure for failure in (database_failure, valkey_failure, kafka_failure) if failure)
        evidence.extend(
            (
                "PostgreSQL schemas/publication/slots",
                "Valkey PING/loading",
                "Kafka canonical/retry/DLQ topics",
            )
        )
        for label, namespace, resource in _REQUIRED_QUERIES:
            items, error = await asyncio.to_thread(_items, namespace, resource)
            if error:
                failures.append(f"{label}: {error}")
            elif not items:
                failures.append(f"{label}: no resources found")
            elif label == "schedule tick" and not any(
                "schedule-tick" in str(item.get("metadata", {})) for item in items
            ):
                failures.append("schedule tick: publisher CronJob not found")
            else:
                evidence.append(f"{label}: {len(items)} resource(s)")

        for resource in (
            "deployments.apps",
            "statefulsets.apps",
            "daemonsets.apps",
            "jobs.batch",
            "cronjobs.batch",
        ):
            items, error = await asyncio.to_thread(_items, os.getenv("K8S_NAMESPACE", "nohiki"), resource)
            if error:
                failures.append(f"image inventory: {error}")
                continue
            failures.extend(
                f"mutable first-party image: {image}"
                for item in items
                for image in _container_images(item)
                if image.startswith("localhost:5000/") and "@sha256:" not in image
            )

        if failures:
            return self._make_result(
                CheckStatus.FAILED,
                f"{len(failures)} Kubernetes platform contract issue(s)",
                details=tuple(failures),
                remediation_hint="Inspect Flux, operator, route, policy, and image status without restarting workloads",
            )
        return self._make_result(
            CheckStatus.PASSED,
            "Kubernetes platform contracts verified",
            details=tuple(evidence),
        )
