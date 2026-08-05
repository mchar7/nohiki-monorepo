"""Tests for configuration modules."""

from __future__ import annotations

import importlib
import json
import re
import subprocess
from pathlib import Path

import pytest
import yaml
from health_check.config.kafka import (
    COMPOSE_CDC_CONNECTORS,
    DB_ERROR_PATTERNS,
    DB_TYPE_MISMATCH_PATTERNS,
    KAFKA_ERROR_PATTERNS,
    KAFKA_TRANSIENT_ERROR_PATTERNS,
    KUBERNETES_CDC_CONNECTORS,
    KUBERNETES_SINK_CONNECTOR_NAMES,
    CdcConnector,
    cdc_connectors_for,
    connector_names_for,
    get_all_topic_names,
)
from health_check.config.thresholds import (
    CDC_END_TO_END_TIMEOUT_SECONDS,
    CHECK_DEFAULT_TIMEOUT_SECONDS,
    CONSUMER_LAG_THRESHOLD,
    IMPORT_CHECK_TIMEOUT_SECONDS,
    KAFKA_GROUP_MEMBERSHIP_TIMEOUT_SECONDS,
    KAFKA_TOPICS_CMD_TIMEOUT_SECONDS,
    STALE_SERVICE_THRESHOLD_HOURS,
)
from health_check.platform.models import PlatformTarget

_REPO = Path(__file__).resolve().parents[4]
_CONNECT_ROOT = _REPO / "infra" / "k8s" / "kafka-connect"
_HELM_CHART = _REPO / "infra" / "k8s" / "helm"


def test_paths_are_lazy_and_explicit_project_root_is_authoritative(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import nohiki_test_utils.paths as shared_paths
    from health_check.config import paths

    def reject_discovery() -> Path:
        pytest.fail("explicit PROJECT_ROOT must not invoke monorepo discovery")

    # This proves resolver behavior in an installed-image-shaped layout. It does not
    # prove the health Dockerfile's COPY or ENV because CI has no health-image executor.
    image_root = tmp_path / "app"
    manifest = image_root / "data" / "config" / "semantic_representation_manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text("{}\n", encoding="utf-8")

    with monkeypatch.context() as patch:
        patch.delenv("PROJECT_ROOT", raising=False)
        patch.setattr(shared_paths, "get_repo_root", reject_discovery)
        reloaded_paths = importlib.reload(paths)
        patch.setenv("PROJECT_ROOT", str(image_root))

        assert reloaded_paths.get_project_root() == image_root
        resolved_manifest = reloaded_paths.get_manifest_path()
        assert resolved_manifest == manifest
        assert resolved_manifest.read_text(encoding="utf-8") == "{}\n"

    importlib.reload(paths)


def _array_entries(script: str, variable: str) -> tuple[str, ...]:
    lines = script.splitlines()
    starts = [index for index, line in enumerate(lines) if line.strip() == f"{variable}=("]
    assert len(starts) == 1, f"{variable} must be defined exactly once"
    entries: list[str] = []
    for line in lines[starts[0] + 1 :]:
        stripped = line.strip()
        if stripped == ")":
            assert entries, f"{variable} must not be empty"
            return tuple(entries)
        if not stripped or stripped.startswith("#"):
            continue
        match = re.fullmatch(r'"([^"\\]+)"\s*(?:#.*)?', stripped)
        assert match is not None, f"unsupported {variable} entry: {stripped}"
        entries.append(match[1])
    pytest.fail(f"{variable} is not closed")


def _template_connector(
    template_name: str,
    name: str,
    replacements: dict[str, str],
) -> CdcConnector:
    document = json.loads((_CONNECT_ROOT / "connectors" / template_name).read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    config = document["config"]
    assert isinstance(config, dict)

    def rendered(key: str) -> str:
        value = config[key]
        assert isinstance(value, str)
        for marker, replacement in replacements.items():
            value = value.replace(marker, replacement)
        return value

    return CdcConnector(
        name=name,
        slot_name=rendered("slot.name"),
        publication_name=rendered("publication.name"),
        table_name=rendered("table.include.list"),
        connector_class=rendered("connector.class"),
    )


def _registered_connectors() -> tuple[CdcConnector, ...]:
    script = (_CONNECT_ROOT / "scripts" / "register-connectors.sh").read_text(encoding="utf-8")
    connectors: list[CdcConnector] = []
    for entry in _array_entries(script, "OUTBOX_CONNECTORS"):
        service_name, schema_name = entry.split(":")
        prefix = service_name.removesuffix("-service").replace("-", "_")
        connectors.append(
            _template_connector(
                "outbox-connector-template.json",
                f"{service_name}-outbox",
                {"DB_PREFIX": prefix, "SCHEMA_NAME": schema_name},
            )
        )
    for entry in _array_entries(script, "WAL_CONNECTORS"):
        service_name, schema_name, resource_prefix = entry.split(":")
        connectors.append(
            _template_connector(
                "wal-connector-template.json",
                f"{service_name}-wal",
                {"RESOURCE_PREFIX": resource_prefix, "SCHEMA_NAME": schema_name},
            )
        )
    return tuple(connectors)


def _helm_connectors() -> tuple[tuple[CdcConnector, ...], tuple[str, ...]]:
    result = subprocess.run(
        [
            "helm",
            "template",
            "nohiki",
            str(_HELM_CHART),
            "--namespace",
            "nohiki-local",
            "--values",
            str(_HELM_CHART / "values.local.yaml"),
            "--set",
            "kafkaConnect.enabled=true",
            "--show-only",
            "templates/strimzi-kafka-connectors.yaml",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    sources: list[CdcConnector] = []
    sinks: list[str] = []
    for document in yaml.safe_load_all(result.stdout):
        if not isinstance(document, dict) or document.get("kind") != "KafkaConnector":
            continue
        metadata = document["metadata"]
        spec = document["spec"]
        assert isinstance(metadata, dict)
        assert isinstance(spec, dict)
        name = metadata["name"]
        connector_class = spec["class"]
        config = spec["config"]
        assert isinstance(name, str)
        assert isinstance(connector_class, str)
        assert isinstance(config, dict)
        if connector_class != "io.debezium.connector.postgresql.PostgresConnector":
            sinks.append(name)
            continue
        slot_name = config["slot.name"]
        publication_name = config["publication.name"]
        table_name = config["table.include.list"]
        assert isinstance(slot_name, str)
        assert isinstance(publication_name, str)
        assert isinstance(table_name, str)
        sources.append(CdcConnector(name, slot_name, publication_name, table_name, connector_class))
    return tuple(sources), tuple(sinks)


class TestKafkaConfig:
    def test_get_all_topic_names_returns_frozenset(self) -> None:
        topics = get_all_topic_names()
        assert isinstance(topics, frozenset)

    def test_get_all_topic_names_not_empty(self) -> None:
        topics = get_all_topic_names()
        assert len(topics) > 0

    def test_all_topic_names_are_strings(self) -> None:
        for t in get_all_topic_names():
            assert isinstance(t, str)

    def test_transient_patterns_subset_of_error_patterns(self) -> None:
        assert KAFKA_TRANSIENT_ERROR_PATTERNS <= KAFKA_ERROR_PATTERNS

    def test_compose_inventory_matches_registration_templates(self) -> None:
        assert _registered_connectors() == COMPOSE_CDC_CONNECTORS
        assert cdc_connectors_for(PlatformTarget.COMPOSE) == COMPOSE_CDC_CONNECTORS
        assert connector_names_for(PlatformTarget.COMPOSE) == tuple(
            connector.name for connector in COMPOSE_CDC_CONNECTORS
        )
        assert not any(name.startswith("nohiki-outbox-") for name in connector_names_for(PlatformTarget.COMPOSE))

    def test_kubernetes_inventory_matches_rendered_helm_connectors(self) -> None:
        rendered_sources, rendered_sinks = _helm_connectors()
        assert sorted(rendered_sources, key=lambda item: item.name) == sorted(
            KUBERNETES_CDC_CONNECTORS, key=lambda item: item.name
        )
        assert rendered_sinks == KUBERNETES_SINK_CONNECTOR_NAMES
        assert frozenset(connector_names_for(PlatformTarget.KUBERNETES)) == frozenset(
            (*(connector.name for connector in rendered_sources), *rendered_sinks)
        )

    def test_registration_array_oracle_rejects_unsupported_lines(self) -> None:
        script = 'OUTBOX_CONNECTORS=(\n"valid:entry"\n$DYNAMIC\n)\n'
        with pytest.raises(AssertionError, match="unsupported OUTBOX_CONNECTORS entry"):
            _array_entries(script, "OUTBOX_CONNECTORS")

    def test_db_error_patterns_non_empty(self) -> None:
        assert len(DB_ERROR_PATTERNS) > 0

    def test_db_type_mismatch_patterns_non_empty(self) -> None:
        assert len(DB_TYPE_MISMATCH_PATTERNS) > 0


class TestThresholds:
    def test_stale_threshold_positive(self) -> None:
        assert STALE_SERVICE_THRESHOLD_HOURS > 0

    def test_consumer_lag_threshold_positive(self) -> None:
        assert CONSUMER_LAG_THRESHOLD > 0

    def test_default_timeout_positive(self) -> None:
        assert CHECK_DEFAULT_TIMEOUT_SECONDS > 0

    def test_cdc_timeout_positive(self) -> None:
        assert CDC_END_TO_END_TIMEOUT_SECONDS > 0

    def test_kafka_topics_timeout_positive(self) -> None:
        assert KAFKA_TOPICS_CMD_TIMEOUT_SECONDS > 0

    def test_import_check_timeout_positive(self) -> None:
        assert IMPORT_CHECK_TIMEOUT_SECONDS > 0

    def test_group_membership_timeout_positive(self) -> None:
        assert KAFKA_GROUP_MEMBERSHIP_TIMEOUT_SECONDS > 0


class TestDatabaseConfig:
    def test_critical_schemas_non_empty(self) -> None:
        from health_check.config.database import CRITICAL_SCHEMAS

        assert len(CRITICAL_SCHEMAS) > 0

    def test_all_schemas_have_service_and_migration(self) -> None:
        from health_check.config.database import CRITICAL_SCHEMAS

        for schema, exp in CRITICAL_SCHEMAS.items():
            assert isinstance(schema, str)
            assert isinstance(exp.service, str)
            assert isinstance(exp.migration, str)

    def test_critical_columns_non_empty(self) -> None:
        from health_check.config.database import CRITICAL_COLUMNS

        assert len(CRITICAL_COLUMNS) > 0

    def test_all_column_paths_have_schema_prefix(self) -> None:
        from health_check.config.database import CRITICAL_COLUMNS

        for path in CRITICAL_COLUMNS:
            assert "." in path, f"{path!r} must be schema.table format"


class TestServicesConfig:
    def test_infrastructure_services_non_empty(self) -> None:
        from health_check.config.services import INFRASTRUCTURE_SERVICES

        assert len(INFRASTRUCTURE_SERVICES) > 0

    def test_core_services_non_empty(self) -> None:
        from health_check.config.services import CORE_SERVICES

        assert len(CORE_SERVICES) > 0

    def test_kafka_consumer_services_subset_of_core(self) -> None:
        from health_check.config.services import CORE_SERVICES, KAFKA_CONSUMER_SERVICES

        core_set = set(CORE_SERVICES)
        for svc in KAFKA_CONSUMER_SERVICES:
            assert svc in core_set, f"{svc} must be in CORE_SERVICES"


class TestVectorsConfig:
    """Tests for config/vectors.py manifest-derived configuration."""

    def test_load_expected_dimensions_returns_dict(self) -> None:
        from health_check.config.vectors import load_expected_dimensions

        dims = load_expected_dimensions()
        assert isinstance(dims, dict)
        assert len(dims) > 0

    def test_load_expected_dimensions_keys_are_collection_names(self) -> None:
        from health_check.config.vectors import load_expected_dimensions

        dims = load_expected_dimensions()
        for key in dims:
            assert isinstance(key, str)
            assert len(key) > 0

    def test_load_expected_dimensions_values_map_names_to_ints(self) -> None:
        from health_check.config.vectors import load_expected_dimensions

        dims = load_expected_dimensions()
        for collection, vectors in dims.items():
            assert isinstance(vectors, dict), f"{collection} vectors should be a dict"
            for name, size in vectors.items():
                assert isinstance(name, str)
                assert isinstance(size, int)
                assert size > 0

    def test_load_expected_dimensions_covers_tracked_entities(self) -> None:
        from health_check.config.vectors import (
            _TRACKED_ENTITIES,
            load_expected_dimensions,
        )

        dims = load_expected_dimensions()
        assert len(dims) == len(_TRACKED_ENTITIES)

    def test_load_skill_collection_name_returns_string(self) -> None:
        from health_check.config.vectors import load_skill_collection_name

        name = load_skill_collection_name()
        assert isinstance(name, str)
        assert len(name) > 0

    def test_load_skill_collection_name_contains_skill(self) -> None:
        from health_check.config.vectors import load_skill_collection_name

        name = load_skill_collection_name()
        assert "skill" in name.lower()
