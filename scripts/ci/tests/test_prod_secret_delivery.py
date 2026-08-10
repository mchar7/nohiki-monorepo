import importlib.util
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml
from ci_checks.core.image_inventory import load_inventory

_ROOT = Path(__file__).resolve().parents[3]
_CHART = _ROOT / "infra/k8s/helm"
_IDENTITY = Path(__file__).parent / "fixtures" / "values.prod.identity.yaml"
_LOCAL_SECRET_CONTRACT = _ROOT / "scripts/infra/local_secret_contract.py"


def _digest_fixture(tmp_path: Path) -> Path:
    digests = {name: f"sha256:{index + 1:064x}" for index, name in enumerate(load_inventory().names)}
    path = tmp_path / "values.prod.digests.yaml"
    path.write_text(yaml.safe_dump({"global": {"imageDigests": digests}}), encoding="utf-8")
    return path


def _render(*values: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    command = ["helm", "template", "nohiki", str(_CHART), "--namespace", "nohiki-prod"]
    for value in values:
        command.extend(("--values", str(value)))
    return subprocess.run(command, cwd=_ROOT, capture_output=True, text=True, check=check)


def _documents(result: subprocess.CompletedProcess[str]) -> tuple[dict[str, Any], ...]:
    return tuple(document for document in yaml.safe_load_all(result.stdout) if isinstance(document, dict))


def _walk(value: object) -> Iterator[object]:
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _prod(tmp_path: Path) -> tuple[dict[str, Any], ...]:
    return _documents(
        _render(
            _CHART / "values.yaml",
            _CHART / "values.prod.yaml",
            _IDENTITY,
            _digest_fixture(tmp_path),
        )
    )


def _enabled_provider_credentials(values_name: str) -> tuple[str, ...]:
    spec = importlib.util.spec_from_file_location("test_prod_local_secret_contract", _LOCAL_SECRET_CONTRACT)
    assert spec is not None
    assert spec.loader is not None
    contract = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(contract)
    return contract.enabled_provider_credentials(_CHART / "values.yaml", _CHART / values_name)


def _provider_secret_names(values_name: str) -> frozenset[str]:
    credentials = _enabled_provider_credentials(values_name)
    return frozenset(f"nohiki-model-egress-{credential}" for credential in credentials)


def _model_egress_external_secret_names(values_name: str) -> frozenset[str]:
    values = yaml.safe_load((_CHART / "values.yaml").read_text(encoding="utf-8"))
    clients = {client["secretName"] for client in values["global"]["modelEgress"]["clients"]}
    return _provider_secret_names(values_name) | clients | {"nohiki-model-egress-tls", "nohiki-model-egress-ca"}


def test_production_uses_only_stable_external_secrets_apis(tmp_path: Path) -> None:
    documents = _prod(tmp_path)
    external_resources = [
        doc for doc in documents if doc.get("kind") in {"ExternalSecret", "SecretStore", "ClusterSecretStore"}
    ]
    assert external_resources
    assert {doc["apiVersion"] for doc in external_resources} == {"external-secrets.io/v1"}
    assert not any(value == "external-secrets.io/v1beta1" for document in documents for value in _walk(document))


def test_production_requires_complete_workload_identity(tmp_path: Path) -> None:
    digest = _digest_fixture(tmp_path)
    missing = _render(_CHART / "values.yaml", _CHART / "values.prod.yaml", digest, check=False)
    assert missing.returncode != 0
    for field in ("keyVaultUrl", "clientId", "tenantId"):
        overlay = yaml.safe_load(_IDENTITY.read_text(encoding="utf-8"))
        overlay["global"]["eso"]["azure"][field] = ""
        path = tmp_path / f"missing-{field}.yaml"
        path.write_text(yaml.safe_dump(overlay), encoding="utf-8")
        result = _render(
            _CHART / "values.yaml",
            _CHART / "values.prod.yaml",
            path,
            digest,
            check=False,
        )
        assert result.returncode != 0, field


def test_production_store_uses_only_referenced_azure_identity(tmp_path: Path) -> None:
    documents = _prod(tmp_path)
    service_account = next(
        doc
        for doc in documents
        if doc.get("kind") == "ServiceAccount" and doc["metadata"]["name"] == "external-secrets-sa"
    )
    assert service_account["metadata"]["namespace"] == "nohiki-prod"
    assert (
        service_account["metadata"]["annotations"]
        | {
            "azure.workload.identity/client-id": "11111111-1111-4111-8111-111111111111",
            "azure.workload.identity/tenant-id": "22222222-2222-4222-8222-222222222222",
        }
        == service_account["metadata"]["annotations"]
    )
    store = next(doc for doc in documents if doc.get("kind") == "ClusterSecretStore")
    assert store["metadata"]["name"] == "nohiki-secret-store"
    assert store["spec"] == {
        "provider": {
            "azurekv": {
                "authType": "WorkloadIdentity",
                "vaultUrl": "https://nohiki-prod-kv.vault.azure.net",
                "serviceAccountRef": {
                    "name": "external-secrets-sa",
                    "namespace": "nohiki-prod",
                },
            }
        }
    }
    assert "fake" not in store["spec"]["provider"]
    assert not any(doc.get("kind") == "SecretProviderClass" for doc in documents)
    assert not any(
        csi.get("driver") == "secrets-store.csi.k8s.io"
        for doc in documents
        for node in _walk(doc)
        if isinstance(node, dict)
        for csi in (node.get("csi"),)
        if isinstance(csi, dict)
    )
    assert not any("stringData" in doc for doc in documents)
    external_targets = {doc["spec"]["target"]["name"] for doc in documents if doc.get("kind") == "ExternalSecret"}
    assert not any(
        doc.get("kind") == "Secret" and doc.get("metadata", {}).get("name") in external_targets for doc in documents
    )


def test_external_secrets_own_exact_targets_and_keys(tmp_path: Path) -> None:
    documents = _prod(tmp_path)
    external = {doc["spec"]["target"]["name"]: doc for doc in documents if doc.get("kind") == "ExternalSecret"}
    provider_targets = {name: {"Authorization"} for name in _provider_secret_names("values.prod.yaml")}
    shared = {
        "nohiki-redis-credentials": {"dsn"},
        "nohiki-jwt-keys": {"private_key"},
        "nohiki-oauth-credentials": {
            "github_client_id",
            "github_client_secret",
            "google_client_id",
            "google_client_secret",
        },
        "nohiki-model-egress-tls": {"tls.crt", "tls.key"},
        "nohiki-model-egress-ca": {"ca.crt"},
        "nohiki-email-api-keys": {"resend_api_key"},
        "nohiki-jsearch-api-keys": {"api_key"},
        "nohiki-s3-credentials": {"access_key", "secret_key"},
        "qdrant-api-key": {"api-key"},
        "auth-listings-secret": {"secret"},
        "kafka-sasl-credentials": {"mechanism", "username", "password"},
    } | provider_targets
    client_targets = {
        "nohiki-model-egress-client-doc-content": "doc-content",
        "nohiki-model-egress-client-job-ingest-enrichment": "job-ingest-enrichment",
    }
    for name, keys in shared.items():
        assert {item["secretKey"] for item in external[name]["spec"]["data"]} == keys
    database_targets = {name for name in external if name.endswith("-db-credentials")}
    assert database_targets
    for name in database_targets:
        assert {item["secretKey"] for item in external[name]["spec"]["data"]} == {
            "host",
            "port",
            "user",
            "username",
            "password",
            "database",
            "dbname",
            "uri",
            "dsn",
        }
    assert set(external) == set(shared) | database_targets | set(client_targets)
    assert "observability-storage-credentials" not in external
    assert "nohiki-llm-api-keys" not in external
    assert "nohiki-model-egress-client" not in external
    for name, secret in external.items():
        assert secret["spec"]["target"]["creationPolicy"] == "Owner"
        if name in client_targets:
            assert "secretStoreRef" not in secret["spec"]
            assert secret["spec"]["refreshPolicy"] == "CreatedOnce"
            assert secret["spec"]["target"]["template"]["metadata"]["labels"] == {
                "nohiki.io/model-egress-route-responses": "true"
            }
            generator_ref = secret["spec"]["dataFrom"][0]["sourceRef"]["generatorRef"]
            assert generator_ref == {
                "apiVersion": "generators.external-secrets.io/v1alpha1",
                "kind": "Password",
                "name": name,
            }
            generator = next(
                document
                for document in documents
                if document.get("kind") == "Password" and document["metadata"]["name"] == name
            )
            assert generator["spec"]["secretKeys"] == [client_targets[name]]
        else:
            assert secret["spec"]["secretStoreRef"] == {
                "name": "nohiki-secret-store",
                "kind": "ClusterSecretStore",
            }


def test_every_application_secret_reference_is_provisioned(tmp_path: Path) -> None:
    documents = _prod(tmp_path)
    provided = {
        (doc["spec"]["target"]["name"], item["secretKey"])
        for doc in documents
        if doc.get("kind") == "ExternalSecret"
        for item in doc["spec"].get("data", [])
    }
    generators = {
        doc["metadata"]["name"]: set(doc["spec"]["secretKeys"]) for doc in documents if doc.get("kind") == "Password"
    }
    provided |= {
        (doc["spec"]["target"]["name"], key)
        for doc in documents
        if doc.get("kind") == "ExternalSecret"
        for source in doc["spec"].get("dataFrom", [])
        for generator_ref in (source.get("sourceRef", {}).get("generatorRef", {}),)
        for key in generators.get(generator_ref.get("name"), set())
    }
    refs: set[tuple[str, str]] = set()
    projected_names: set[str] = set()
    for doc in documents:
        for node in _walk(doc):
            if not isinstance(node, dict):
                continue
            secret_ref = node.get("secretKeyRef")
            if isinstance(secret_ref, dict):
                name = secret_ref.get("name")
                key = secret_ref.get("key")
                if isinstance(name, str) and isinstance(key, str):
                    refs.add((name, key))
            projected = node.get("projected")
            if isinstance(projected, dict):
                sources = projected.get("sources")
                if isinstance(sources, list):
                    for source in sources:
                        if isinstance(source, dict):
                            secret = source.get("secret")
                            if isinstance(secret, dict):
                                name = secret.get("name")
                                if isinstance(name, str):
                                    projected_names.add(name)
    assert refs
    assert refs <= provided
    assert projected_names <= {name for name, _ in provided}


def test_enabled_workloads_never_mount_runtime_or_provider_credentials(
    tmp_path: Path,
) -> None:
    documents = _prod(tmp_path)
    deployments = {
        document["metadata"]["name"]: document for document in documents if document.get("kind") == "Deployment"
    }
    assert "nohiki-skill-graph-service" in deployments
    forbidden = {
        "nohiki-llm-runtime",
        "nohiki-llm-api-keys",
    } | _provider_secret_names("values.prod.yaml")
    expected_inventory = {
        "nohiki-doc-content-service": {
            "nohiki-model-egress-client-doc-content",
            "nohiki-model-egress-ca",
        },
        "nohiki-job-ingest-enrichment-service": {
            "nohiki-model-egress-client-job-ingest-enrichment",
            "nohiki-model-egress-ca",
        },
    }
    actual_inventory: dict[str, set[str]] = {}
    for name, deployment in deployments.items():
        referenced: set[str] = set()
        for node in _walk(deployment["spec"]["template"]["spec"]):
            if not isinstance(node, dict):
                continue
            for field in ("secretKeyRef", "secretRef"):
                ref = node.get(field)
                if isinstance(ref, dict) and isinstance(ref_name := ref.get("name"), str):
                    referenced.add(ref_name)
            secret = node.get("secret")
            if isinstance(secret, dict):
                secret_name = secret.get("secretName", secret.get("name"))
                if isinstance(secret_name, str):
                    referenced.add(secret_name)
        assert not (referenced & forbidden), name
        gateway_refs = {secret for secret in referenced if secret.startswith("nohiki-model-egress")}
        if gateway_refs:
            actual_inventory[name] = gateway_refs
    assert actual_inventory == expected_inventory
    assert not (set(actual_inventory.get("nohiki-skill-graph-service", set())) & forbidden)


def test_redis_qdrant_database_and_keda_secret_semantics(tmp_path: Path) -> None:
    documents = _prod(tmp_path)
    dumped = yaml.safe_dump_all(documents)
    assert "nohiki-redis-credentials" in dumped
    assert "qdrant-api-key" in dumped
    keda = next(
        doc
        for doc in documents
        if doc.get("kind") == "TriggerAuthentication" and doc["metadata"]["name"] == "nohiki-kafka-auth"
    )
    parameters = {entry["parameter"]: (entry["name"], entry["key"]) for entry in keda["spec"]["secretTargetRef"]}
    assert parameters == {
        "sasl": ("kafka-sasl-credentials", "mechanism"),
        "username": ("kafka-sasl-credentials", "username"),
        "password": ("kafka-sasl-credentials", "password"),
    }


@pytest.mark.parametrize(
    ("values_name", "delivery"),
    [
        pytest.param("values.local.yaml", "sops", id="local"),
        pytest.param("values.staging.yaml", "external", id="staging"),
    ],
)
def test_secret_delivery_matches_environment_contract(values_name: str, delivery: str) -> None:
    extra = (_IDENTITY,) if delivery == "external" else ()
    result = _render(_CHART / "values.yaml", _CHART / values_name, *extra)
    documents = _documents(result)
    if delivery == "external":
        assert any(doc.get("kind") == "ExternalSecret" for doc in documents)
        assert not any(
            doc.get("kind") == "Secret" and doc.get("metadata", {}).get("name") == "nohiki-jwt-keys"
            for doc in documents
        )
    else:
        external = [doc for doc in documents if doc.get("kind") == "ExternalSecret"]
        external_targets = {doc["spec"]["target"]["name"] for doc in external}
        assert external_targets == _model_egress_external_secret_names("values.local.yaml")
        source_names = {item["remoteRef"]["key"] for doc in external for item in doc["spec"].get("data", [])}
        direct_secret_names = {doc["metadata"]["name"] for doc in documents if doc.get("kind") == "Secret"}
        assert direct_secret_names.isdisjoint(external_targets | source_names)
        assert not any(doc.get("kind") in {"SecretStore", "ClusterSecretStore"} for doc in documents)
