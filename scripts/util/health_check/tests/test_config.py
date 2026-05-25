"""Tests for configuration modules."""

from __future__ import annotations

from health_check.config.kafka import (
    DB_ERROR_PATTERNS,
    DB_TYPE_MISMATCH_PATTERNS,
    KAFKA_ERROR_PATTERNS,
    KAFKA_TRANSIENT_ERROR_PATTERNS,
    OUTBOX_CONNECTOR_NAMES,
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

    def test_connector_readiness_inventory_matches_delivery_modes(self) -> None:
        assert OUTBOX_CONNECTOR_NAMES == (
            "nohiki-outbox-user_auth",
            "nohiki-outbox-user_pref",
            "nohiki-outbox-user_upload",
            "nohiki-outbox-user_entitlement",
            "nohiki-outbox-job_query",
            "nohiki-outbox-job_storage",
            "job-correlation-evaluation-service-wal",
            "nohiki-outbox-job_ingest_enrichment",
            "nohiki-outbox-doc_render",
            "nohiki-outbox-doc_schema",
            "nohiki-outbox-doc_template",
            "nohiki-outbox-skill_graph",
            "nohiki-outbox-notification",
        )

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
