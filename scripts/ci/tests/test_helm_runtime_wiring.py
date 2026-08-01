"""Regression coverage for the two verified Helm runtime blockers.

Blocker 1 -- database DSN wiring:
    Every DB-backed service Deployment must receive ``DATABASE__DSN`` (env-prefix
    aware) from its per-service credential Secret ``{svc}-db-credentials`` -- the
    same Secret the ``{svc}-db-migrate`` Job uses -- via ``secretKeyRef`` key
    ``dsn``. Workloads that are not DB-backed must never receive a ``DATABASE__DSN``.

Blocker 2 -- local S3 presign URL:
    The local S3 public URL must use an RFC 6761 ``.localhost`` name or a
    loopback IP address over HTTP. The application validator
    (``nohiki_s3_client.S3Settings.validate_public_url``) rejects arbitrary
    non-loopback HTTP hosts. Staging and production public URLs must never use
    insecure HTTP.

The DB-backed set is derived from the rendered migration Jobs rather than a
hardcoded list, so the tests stay correct as services are added or removed.
"""

from __future__ import annotations

import runpy
import subprocess
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlsplit

import yaml
from helm_test_utils import runtime_eso_args
from test_image_digest_gitops import _digest_values

_ROOT = Path(__file__).resolve().parents[3]
_CHART = _ROOT / "infra" / "k8s" / "helm"
_IDENTITY = Path(__file__).parent / "fixtures" / "values.prod.identity.yaml"
_NETWORK = Path(__file__).parent / "fixtures" / "values.prod.network.yaml"
_TOPICS = runpy.run_path(
    str(_ROOT / "backend" / "libs" / "nohiki-kafka-client" / "src" / "nohiki_kafka_client" / "topics.py")
)["Topics"]
_KAFKA_SCALER_TOPICS = {
    "nohiki-doc-content-service": {
        _TOPICS.DOC_CONTENT_GENERATION_REQUESTED,
        _TOPICS.JOB_CORRELATION_EVALUATED,
    },
    "nohiki-doc-process-service": {_TOPICS.DOC_PROCESS_PROCESSING_REQUESTED},
    "nohiki-doc-template-service": {
        _TOPICS.DOC_TEMPLATE_CREATE_REQUESTED,
        _TOPICS.DOC_TEMPLATE_DELETE_REQUESTED,
        _TOPICS.DOC_TEMPLATE_RENDER_REQUESTED,
        _TOPICS.DOC_TEMPLATE_VERSION_ADD_REQUESTED,
    },
    "nohiki-job-correlation-evaluation-service": {
        _TOPICS.FEEDBACK_SCORE_ADJUSTMENT_REQUESTED,
        _TOPICS.FEEDBACK_SCORE_FEEDBACK_REQUESTED,
        _TOPICS.JOB_CORRELATION_BACKFILL_LISTINGS,
        _TOPICS.JOB_CORRELATION_FEEDBACK_RECORDED,
        _TOPICS.JOB_CORRELATION_TRAINING_EXPORT_REQUESTED,
        _TOPICS.JOB_LISTING_CREATED,
        _TOPICS.JOB_LISTING_DELETED,
        _TOPICS.JOB_LISTING_UPDATED,
        _TOPICS.USER_PREF_CREATED,
        _TOPICS.USER_PREF_DELETED,
        _TOPICS.USER_PREF_UPDATED,
    },
    "nohiki-job-ingest-discovery-service": {_TOPICS.JOB_INGEST_DISCOVERY_REQUESTED},
    "nohiki-job-query-composition-service": {
        _TOPICS.USER_AUTH_ACCOUNT_DELETED,
        _TOPICS.USER_AUTH_ACTIVITY,
        _TOPICS.USER_ENTITLEMENT_CHANGED,
        _TOPICS.USER_PREF_CREATED,
        _TOPICS.USER_PREF_DELETED,
        _TOPICS.USER_PREF_UPDATED,
    },
    "nohiki-job-storage-service": {
        _TOPICS.JOB_INGEST_ENRICHMENT_COMPLETED,
        _TOPICS.JOB_INGEST_LISTING_DISCOVERED,
        _TOPICS.JOB_LISTING_BACKFILL_REQUESTED,
        _TOPICS.JOB_LISTING_SNAPSHOT_REFRESH_REQUESTED,
    },
    "nohiki-ml-compute-service": {_TOPICS.ML_INTERNAL_K8S_COMPUTE},
    "nohiki-ml-gateway-service": {
        _TOPICS.ML_BATCH_EMBEDDING_REQUESTED,
        _TOPICS.ML_EMBEDDING_REQUESTED,
        _TOPICS.ML_RERANK_REQUESTED,
    },
    "nohiki-skill-graph-service": {
        _TOPICS.SKILL_ALIAS_LEARNED,
        _TOPICS.SKILL_BATCH_EMBEDDING_CALLBACK,
        _TOPICS.SKILL_GRAPH_SEEDED,
        _TOPICS.SKILL_MENTION_CREATED,
        _TOPICS.SKILL_NORMALIZATION_EMBEDDING_CALLBACK,
        _TOPICS.SKILL_NORMALIZATION_REQUESTED,
        _TOPICS.SKILL_PROPOSED,
    },
    "nohiki-user-entitlement-service": {
        _TOPICS.USER_AUTH_ACCOUNT_DELETED,
        _TOPICS.USER_AUTH_ACCOUNT_UPDATED,
    },
    "nohiki-user-pref-service": {
        _TOPICS.USER_AUTH_ACCOUNT_DELETED,
        _TOPICS.USER_PREF_ATTACH_UPLOAD_REQUESTED,
        _TOPICS.USER_PREF_CREATE_REQUESTED,
        _TOPICS.USER_PREF_DELETE_REQUESTED,
        _TOPICS.USER_PREF_DETACH_UPLOAD_REQUESTED,
        _TOPICS.USER_PREF_EMBEDDING_CALLBACK,
        _TOPICS.USER_PREF_FEATURE_IMPORTANCE_UPDATE_REQUESTED,
        _TOPICS.USER_PREF_SETTINGS_UPDATE_REQUESTED,
        _TOPICS.USER_PREF_SKILL_CALLBACK,
        _TOPICS.USER_PREF_UPDATE_REQUESTED,
        _TOPICS.USER_UPLOAD_DELETED,
    },
    "nohiki-user-upload-service": {
        _TOPICS.USER_AUTH_ACCOUNT_DELETED,
        _TOPICS.USER_UPLOAD_CREATE_REQUESTED,
        _TOPICS.USER_UPLOAD_DELETE_REQUESTED,
    },
}
_WARM_KAFKA_SCALERS = {
    "nohiki-job-storage-service",
    "nohiki-ml-compute-service",
}
_LIFECYCLE_EXCLUSIONS = {
    "nohiki-job-ingest-enrichment-service",
    "nohiki-job-ingest-schedule-service",
    "nohiki-notification-service",
}


def _render(values_name: str, tmp_path: Path) -> tuple[dict, ...]:
    environment = values_name.removeprefix("values.").removesuffix(".yaml")
    command = [
        "helm",
        "template",
        "nohiki",
        str(_CHART),
        "--namespace",
        f"nohiki-{environment}",
        "--values",
        str(_CHART / values_name),
    ]
    if values_name == "values.prod.yaml":
        command.extend(
            (
                "--values",
                str(_IDENTITY),
                "--values",
                str(_NETWORK),
                "--values",
                str(_digest_values(tmp_path)),
            )
        )
    command.extend(runtime_eso_args(environment))
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    return tuple(document for document in yaml.safe_load_all(result.stdout) if isinstance(document, dict))


def _deployments(documents: tuple[dict, ...]) -> dict[str, dict]:
    return {document["metadata"]["name"]: document for document in documents if document.get("kind") == "Deployment"}


def _db_backed_services(documents: tuple[dict, ...]) -> set[str]:
    """Services with a ``{svc}-db-migrate`` Job -- the source of truth for DB-backed workloads."""
    return {
        document["metadata"]["name"].removesuffix("-db-migrate")
        for document in documents
        if document.get("kind") == "Job" and document["metadata"]["name"].endswith("-db-migrate")
    }


def _migration_secret(documents: tuple[dict, ...], svc: str) -> str:
    """Name of the Secret the migration Job reads its DSN from (matched by the Deployment)."""
    job = next(
        document
        for document in documents
        if document.get("kind") == "Job" and document["metadata"]["name"] == f"{svc}-db-migrate"
    )
    for container in job["spec"]["template"]["spec"]["containers"]:
        for entry in container.get("env", []):
            reference = entry.get("valueFrom", {}).get("secretKeyRef")
            if reference and entry["name"].startswith("DATABASE"):
                return reference["name"]
    message = f"{svc}-db-migrate Job has no DATABASE_URL secretKeyRef"
    raise AssertionError(message)


def _dsn_reference(deployment: dict) -> tuple[str, str] | None:
    """Return ``(secret_name, key)`` for the ``*DATABASE__DSN`` env, or ``None`` when absent."""
    for container in deployment["spec"]["template"]["spec"]["containers"]:
        for entry in container.get("env", []):
            if entry["name"].endswith("DATABASE__DSN"):
                reference = entry.get("valueFrom", {}).get("secretKeyRef")
                assert reference is not None, (
                    f"{deployment['metadata']['name']} {entry['name']} must come from a Secret, not an inline value"
                )
                return reference["name"], reference["key"]
    return None


def _s3_public_urls(documents: tuple[dict, ...]) -> dict[str, str]:
    """Map Deployment name -> its ``*S3__PUBLIC_URL`` env value (inline values only)."""
    urls: dict[str, str] = {}
    for name, deployment in _deployments(documents).items():
        for container in deployment["spec"]["template"]["spec"]["containers"]:
            for entry in container.get("env", []):
                if entry["name"].endswith("S3__PUBLIC_URL") and "value" in entry:
                    urls[name] = entry["value"]
    return urls


def _is_accepted_public_url(value: str, *, allow_http_loopback: bool) -> bool:
    """Mirror ``nohiki_s3_client.S3Settings.validate_public_url`` (kept in sync with the app)."""
    if any(character.isspace() for character in value) or any(delimiter in value for delimiter in "?#\\"):
        return False
    parsed = urlsplit(value)
    if not parsed.hostname or parsed.username or parsed.password:
        return False
    if parsed.scheme == "https":
        return True
    if parsed.scheme != "http" or not allow_http_loopback:
        return False
    host = parsed.hostname.strip("[]").rstrip(".")
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        loopback = ip_address(host).is_loopback
    except ValueError:
        loopback = False
    return loopback


def test_local_db_backed_deployments_receive_dsn_from_credential_secret(
    tmp_path: Path,
) -> None:
    documents = _render("values.local.yaml", tmp_path)
    db_services = _db_backed_services(documents)
    assert db_services, "expected the local render to contain DB-backed services"
    deployments = _deployments(documents)

    for svc in sorted(db_services):
        deployment = deployments.get(f"nohiki-{svc}")
        assert deployment is not None, f"missing Deployment nohiki-{svc} for DB-backed service"
        reference = _dsn_reference(deployment)
        assert reference is not None, f"nohiki-{svc} must receive DATABASE__DSN from its credential Secret"
        secret_name, key = reference
        assert secret_name == f"{svc}-db-credentials"
        # Same Secret the migration Job connects with, so the deployment reaches the migrated schema.
        assert secret_name == _migration_secret(documents, svc)
        assert key == "dsn"


def test_local_non_db_workloads_never_receive_dsn(tmp_path: Path) -> None:
    documents = _render("values.local.yaml", tmp_path)
    db_services = _db_backed_services(documents)
    deployments = _deployments(documents)

    # Sentinel: a known non-DB first-party service must render and stay DSN-free,
    # so this test cannot pass vacuously on a broken render.
    assert "nohiki-ml-gateway-service" in deployments
    assert "ml-gateway-service" not in db_services

    for name, deployment in deployments.items():
        if name.removeprefix("nohiki-") in db_services:
            continue
        assert _dsn_reference(deployment) is None, f"non-DB workload {name} must not receive DATABASE__DSN"


def test_local_s3_public_url_is_accepted_loopback_http(tmp_path: Path) -> None:
    documents = _render("values.local.yaml", tmp_path)
    assert "nohiki-bff-service" in _deployments(documents)
    value = _s3_public_urls(documents).get("nohiki-bff-service")
    assert value == "http://s3.nohiki.localhost:8080"
    assert _is_accepted_public_url(value, allow_http_loopback=True), (
        f"{value!r} must be an accepted RFC localhost HTTP public URL"
    )
    assert not _is_accepted_public_url(
        "http://storage.example.com:8080",
        allow_http_loopback=True,
    )


def test_staging_and_production_s3_public_urls_are_not_insecure_http(
    tmp_path: Path,
) -> None:
    prod = _render("values.prod.yaml", tmp_path)
    # Production must publish an HTTPS presign endpoint (concrete anchor for this guardrail).
    assert _s3_public_urls(prod).get("nohiki-bff-service") == "https://nohikiprod.blob.core.windows.net"

    for values_name in ("values.staging.yaml", "values.prod.yaml"):
        documents = prod if values_name == "values.prod.yaml" else _render(values_name, tmp_path)
        for name, value in _s3_public_urls(documents).items():
            assert value.startswith("https://"), f"{name} S3 public URL must use HTTPS in {values_name}, got {value!r}"


def test_kafka_scalers_are_presence_partition_and_topic_aware(tmp_path: Path) -> None:
    for values_name, expected_maximum in (
        ("values.local.yaml", 1),
        ("values.dev.yaml", 3),
        ("values.staging.yaml", 3),
        ("values.prod.yaml", 3),
    ):
        documents = _render(values_name, tmp_path)
        scalers = {
            document["metadata"]["name"]: document for document in documents if document.get("kind") == "ScaledObject"
        }
        assert set(scalers) == set(_KAFKA_SCALER_TOPICS), values_name
        assert not set(scalers) & _LIFECYCLE_EXCLUSIONS

        for name, expected_topics in _KAFKA_SCALER_TOPICS.items():
            spec = scalers[name]["spec"]
            triggers = [trigger for trigger in spec["triggers"] if trigger["type"] == "kafka"]
            assert all("topic" in trigger["metadata"] for trigger in triggers), (values_name, name)
            assert {trigger["metadata"]["topic"] for trigger in triggers} == expected_topics
            assert spec["minReplicaCount"] == (1 if name in _WARM_KAFKA_SCALERS else 0), (values_name, name)
            assert spec["maxReplicaCount"] == expected_maximum
            if name in _WARM_KAFKA_SCALERS:
                assert "idleReplicaCount" not in spec
            else:
                assert spec["idleReplicaCount"] == 0


def test_kafka_scaler_auth_follows_global_kafka_security(tmp_path: Path) -> None:
    for values_name in ("values.local.yaml", "values.dev.yaml", "values.staging.yaml"):
        documents = _render(values_name, tmp_path)
        triggers = [
            trigger
            for document in documents
            if document.get("kind") == "ScaledObject"
            for trigger in document["spec"]["triggers"]
            if trigger["type"] == "kafka"
        ]
        assert triggers
        assert all("authenticationRef" not in trigger for trigger in triggers)
        assert all("tls" not in trigger["metadata"] for trigger in triggers)

    production = _render("values.prod.yaml", tmp_path)
    triggers = [
        trigger
        for document in production
        if document.get("kind") == "ScaledObject"
        for trigger in document["spec"]["triggers"]
        if trigger["type"] == "kafka"
    ]
    assert triggers
    assert all(trigger["authenticationRef"] == {"name": "nohiki-kafka-auth"} for trigger in triggers)
    assert all(trigger["metadata"]["tls"] == "enable" for trigger in triggers)
