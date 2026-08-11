"""Render contracts for the operational local Kafka Connect stack."""

import subprocess
from pathlib import Path

from _documents import Manifest, load_manifests, mapping_at, mapping_sequence_at, metadata_of, string_at

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_CHART = _REPOSITORY_ROOT / "infra" / "k8s" / "helm"
_IDENTITY = Path(__file__).parent / "fixtures" / "values.prod.identity.yaml"
_POSTGRES_CLASS = "io.debezium.connector.postgresql.PostgresConnector"
_EXPECTED_SOURCES = {
    "bff-service-outbox": ("bff_outbox_slot", "bff_outbox_pub", "bff_schema.outbox", "bff-service"),
    "doc-template-service-outbox": (
        "doc_template_outbox_slot",
        "doc_template_outbox_pub",
        "doc_template_schema.outbox",
        "doc-template-service",
    ),
    "job-correlation-evaluation-service-wal": (
        "job_correlation_wal_slot",
        "job_correlation_wal_pub",
        "job_correlation_schema.processed_events",
        "job-correlation-evaluation-service",
    ),
    "job-ingest-enrichment-service-outbox": (
        "job_ingest_enrichment_outbox_slot",
        "job_ingest_enrichment_outbox_pub",
        "job_ingest_enrichment_schema.outbox",
        "job-ingest-enrichment-service",
    ),
    "job-query-composition-service-outbox": (
        "job_query_composition_outbox_slot",
        "job_query_composition_outbox_pub",
        "job_query_schema.outbox",
        "job-query-composition-service",
    ),
    "job-storage-service-outbox": (
        "job_storage_outbox_slot",
        "job_storage_outbox_pub",
        "job_storage_schema.outbox",
        "job-storage-service",
    ),
    "notification-service-outbox": (
        "notification_outbox_slot",
        "notification_outbox_pub",
        "notification_schema.outbox",
        "notification-service",
    ),
    "skill-graph-service-outbox": (
        "skill_graph_outbox_slot",
        "skill_graph_outbox_pub",
        "skill_graph_schema.outbox",
        "skill-graph-service",
    ),
    "user-auth-service-outbox": (
        "user_auth_outbox_slot",
        "user_auth_outbox_pub",
        "user_auth_schema.outbox",
        "user-auth-service",
    ),
    "user-entitlement-service-outbox": (
        "user_entitlement_outbox_slot",
        "user_entitlement_outbox_pub",
        "user_entitlement_schema.outbox",
        "user-entitlement-service",
    ),
    "user-pref-service-outbox": (
        "user_pref_outbox_slot",
        "user_pref_outbox_pub",
        "user_pref_schema.outbox",
        "user-pref-service",
    ),
    "user-upload-service-outbox": (
        "user_upload_outbox_slot",
        "user_upload_outbox_pub",
        "user_upload_schema.outbox",
        "user-upload-service",
    ),
}
_EXPECTED_ROLE_MEMBERSHIPS = {
    "bff_debezium": "bff_svc",
    "doc_template_debezium": "doc_template_svc",
    "job_correlation_evaluation_debezium": "job_correlation_evaluation_svc",
    "job_ingest_enrichment_debezium": "job_ingest_enrichment_svc",
    "job_query_composition_debezium": "job_query_composition_svc",
    "job_storage_debezium": "job_storage_svc",
    "notification_debezium": "notification_svc",
    "skill_graph_debezium": "skill_graph_svc",
    "user_auth_debezium": "user_auth_svc",
    "user_entitlement_debezium": "user_entitlement_svc",
    "user_pref_debezium": "user_pref_svc",
    "user_upload_debezium": "user_upload_svc",
}


def _render(*args: str) -> list[Manifest]:
    result = subprocess.run(
        ["helm", "template", "nohiki", str(_CHART), "--namespace", "nohiki", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return load_manifests(result.stdout)


def test_local_render_emits_the_canonical_connect_stack() -> None:
    documents = _render(
        "--values",
        str(_CHART / "values.local.yaml"),
        "--show-only",
        "templates/strimzi-kafka-connect.yaml",
        "--show-only",
        "templates/strimzi-kafka-connectors.yaml",
        "--show-only",
        "templates/cnpg-cluster.yaml",
    )
    connect = next(document for document in documents if document["kind"] == "KafkaConnect")
    connect_spec = mapping_at(connect, "spec")
    assert connect_spec["image"] == "localhost:5000/kafka-connect:dev"
    connect_config = mapping_at(connect_spec, "config")
    assert connect_config["config.providers"] == "directory"
    assert (
        connect_config["config.providers.directory.class"]
        == "org.apache.kafka.common.config.provider.DirectoryConfigProvider"
    )
    assert connect_config["config.providers.directory.param.allowed.paths"] == "/mnt/secrets"
    assert "config.providers.file.class" not in connect_config

    connectors = {
        metadata_of(document)["name"]: document for document in documents if document["kind"] == "KafkaConnector"
    }
    assert set(connectors) == {*_EXPECTED_SOURCES, "qdrant-embedding-sink"}
    for name, (slot, publication, table, service) in _EXPECTED_SOURCES.items():
        spec = mapping_at(connectors[name], "spec")
        config = mapping_at(spec, "config")
        assert spec["class"] == _POSTGRES_CLASS
        assert config["slot.name"] == slot
        assert config["publication.name"] == publication
        assert config["publication.autocreate.mode"] == "filtered"
        assert config["table.include.list"] == table
        assert config["database.user"] == f"${{directory:/mnt/secrets/{service}-debezium:username}}"
        assert config["database.password"] == f"${{directory:/mnt/secrets/{service}-debezium:password}}"

    qdrant = mapping_at(connectors["qdrant-embedding-sink"], "spec")
    assert qdrant["class"] == "io.qdrant.kafka.QdrantSinkConnector"
    assert mapping_at(qdrant, "config")["topics"] == "ml.fct.embedding-completed-json.v1"
    assert "qdrant.api.key" not in mapping_at(qdrant, "config")

    pod_template = mapping_at(connect_spec, "template", "pod")
    mounted_secrets = {
        string_at(mapping_at(volume, "secret"), "secretName") for volume in mapping_sequence_at(pod_template, "volumes")
    }
    assert mounted_secrets == {f"{service}-debezium-credentials" for *_, service in _EXPECTED_SOURCES.values()}
    assert "qdrant-credentials" not in mounted_secrets

    cluster = next(document for document in documents if document["kind"] == "Cluster")
    roles = {
        string_at(role, "name"): role for role in mapping_sequence_at(mapping_at(cluster, "spec"), "managed", "roles")
    }
    memberships = {name: role["inRoles"] for name, role in roles.items() if name.endswith("_debezium")}
    assert memberships == {name: [app_role] for name, app_role in _EXPECTED_ROLE_MEMBERSHIPS.items()}
    assert all(roles[name]["replication"] is True for name in _EXPECTED_ROLE_MEMBERSHIPS)


def test_secret_backed_qdrant_connector_uses_directory_provider() -> None:
    documents = _render(
        "--values",
        str(_CHART / "values.local.yaml"),
        "--set",
        "kafkaConnect.qdrant.apiKeyFromSecret=true",
        "--show-only",
        "templates/strimzi-kafka-connectors.yaml",
    )
    qdrant = next(document for document in documents if metadata_of(document)["name"] == "qdrant-embedding-sink")

    assert mapping_at(qdrant, "spec", "config")["qdrant.api.key"] == ("${directory:/mnt/secrets/qdrant:api-key}")


def test_non_local_render_keeps_connect_disabled() -> None:
    documents = _render(
        "--namespace",
        "nohiki-dev",
        "--values",
        str(_CHART / "values.dev.yaml"),
        "--values",
        str(_IDENTITY),
    )
    assert not any(document["kind"] in {"KafkaConnect", "KafkaConnector"} for document in documents)
