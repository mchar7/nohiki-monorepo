"""Behavioral contracts for fail-closed local Secret source validation.

All inputs are generated under ``tmp_path``.  The suite never opens the repository's
Secret sources or decrypts/prints Secret data.
"""

from __future__ import annotations

import functools
import hashlib
import importlib.util
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

import pytest
import yaml
from _documents import (
    load_manifests,
    load_mapping,
    mapping_at,
    mapping_sequence_at,
    sequence_at,
    string_at,
)

ROOT = Path(__file__).resolve().parents[3]
VALIDATOR = ROOT / "scripts/infra/validate_local_secret_sources.py"
PROVISIONER = ROOT / "scripts/infra/provision_local_app_secrets.py"
RUNTIME_PROVISIONER = ROOT / "scripts/infra/provision_local_runtime_secrets.py"
TLS_PROVISIONER = ROOT / "scripts/infra/provision_local_tls_source.py"
LOCAL_SECRET_CONTRACT = ROOT / "scripts/infra/local_secret_contract.py"
HELM_README = ROOT / "infra/k8s/helm/README.md"
LOCAL_VALUES = ROOT / "infra/k8s/helm/values.local.yaml"
BASE_VALUES = ROOT / "infra/k8s/helm/values.yaml"
LOCAL_OBSERVABILITY = ROOT / "infra/k8s/observability/overlays/local"
REQUIRED_SOURCES = (
    "database/host",
    "database/port",
    "database/user",
    "database/password",
    "database/database",
    "email/api_key",
    "jsearch/api_key",
    "s3/access_key",
    "s3/secret_key",
)
OPTIONAL_SOURCES = (
    "redis/password",
    "oauth/github_client_id",
    "oauth/github_client_secret",
    "oauth/google_client_id",
    "oauth/google_client_secret",
)


@functools.cache
def _local_provider_credentials() -> frozenset[str]:
    spec = importlib.util.spec_from_file_location("test_local_secret_contract", LOCAL_SECRET_CONTRACT)
    assert spec is not None
    assert spec.loader is not None
    contract = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(contract)
    credentials = contract.enabled_provider_credentials(
        load_mapping(BASE_VALUES),
        load_mapping(LOCAL_VALUES),
    )
    assert credentials
    return frozenset(credentials)


def _runtime_keys() -> set[str]:
    return {f"{credential}_api_key" for credential in _local_provider_credentials()}


DATABASE_SERVICES = (
    "bff-service",
    "doc-template-service",
    "job-correlation-evaluation-service",
    "job-ingest-discovery-service",
    "job-ingest-enrichment-service",
    "job-ingest-schedule-service",
    "job-query-composition-service",
    "job-storage-service",
    "notification-service",
    "skill-graph-service",
    "user-auth-service",
    "user-entitlement-service",
    "user-pref-service",
    "user-upload-service",
)
DATABASE_KEYS = {
    "host",
    "port",
    "user",
    "username",
    "password",
    "database",
    "dbname",
    "dsn",
    "uri",
}
APPLICATION_SECRET_KEYS = {
    "nohiki-redis-credentials": {"password", "dsn"},
    "nohiki-jwt-keys": {"private_key"},
    "nohiki-email-api-keys": {"resend_api_key"},
    "nohiki-jsearch-api-keys": {"api_key"},
    "nohiki-s3-credentials": {"access_key", "secret_key"},
    "observability-storage-credentials": {
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_REGION",
    },
    "auth-listings-secret": {"secret"},
    "nohiki-rustfs-credentials": {
        "root-user",
        "root-password",
        "access-key",
        "secret-key",
    },
}
OAUTH_KEYS = {
    "github_client_id",
    "github_client_secret",
    "google_client_id",
    "google_client_secret",
}
_REJECTION_MARKER = "fixture-private-marker-7f93"


@dataclass(frozen=True)
class Sources:
    secrets: Path
    age_key: Path
    sops_config: Path
    encrypted_secret: Path
    runtime_kustomization: Path


@pytest.fixture
def secret_modules(monkeypatch: pytest.MonkeyPatch) -> tuple[ModuleType, ModuleType]:
    monkeypatch.syspath_prepend(str(PROVISIONER.parent))
    validator_spec = importlib.util.spec_from_file_location("validate_local_secret_sources", VALIDATOR)
    assert validator_spec is not None
    assert validator_spec.loader is not None
    validator = importlib.util.module_from_spec(validator_spec)
    monkeypatch.setitem(sys.modules, validator_spec.name, validator)
    validator_spec.loader.exec_module(validator)

    provisioner_spec = importlib.util.spec_from_file_location("provision_local_app_secrets", PROVISIONER)
    assert provisioner_spec is not None
    assert provisioner_spec.loader is not None
    provisioner = importlib.util.module_from_spec(provisioner_spec)
    monkeypatch.setitem(sys.modules, provisioner_spec.name, provisioner)
    provisioner_spec.loader.exec_module(provisioner)
    return validator, provisioner


@pytest.fixture
def runtime_provisioner_module(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.syspath_prepend(str(PROVISIONER.parent))
    validator_spec = importlib.util.spec_from_file_location("validate_local_secret_sources", VALIDATOR)
    assert validator_spec is not None
    assert validator_spec.loader is not None
    validator = importlib.util.module_from_spec(validator_spec)
    monkeypatch.setitem(sys.modules, validator_spec.name, validator)
    validator_spec.loader.exec_module(validator)
    app_spec = importlib.util.spec_from_file_location("provision_local_app_secrets", PROVISIONER)
    assert app_spec is not None
    assert app_spec.loader is not None
    app = importlib.util.module_from_spec(app_spec)
    monkeypatch.setitem(sys.modules, app_spec.name, app)
    app_spec.loader.exec_module(app)

    runtime_spec = importlib.util.spec_from_file_location("provision_local_runtime_secrets", RUNTIME_PROVISIONER)
    assert runtime_spec is not None
    assert runtime_spec.loader is not None
    runtime = importlib.util.module_from_spec(runtime_spec)
    monkeypatch.setitem(sys.modules, runtime_spec.name, runtime)
    runtime_spec.loader.exec_module(runtime)
    return runtime


@pytest.fixture
def tls_provisioner_module(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.syspath_prepend(str(PROVISIONER.parent))
    tls_spec = importlib.util.spec_from_file_location("provision_local_tls_source", TLS_PROVISIONER)
    assert tls_spec is not None
    assert tls_spec.loader is not None
    tls = importlib.util.module_from_spec(tls_spec)
    monkeypatch.setitem(sys.modules, tls_spec.name, tls)
    tls_spec.loader.exec_module(tls)
    return tls


def _private_write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    path.write_text(value, encoding="utf-8")
    path.chmod(0o600)


@pytest.fixture(scope="session")
def provisioned_sources_template(tmp_path_factory: pytest.TempPathFactory) -> Sources:
    tmp_path = tmp_path_factory.mktemp("local-secret-sources")
    secrets = tmp_path / "secrets"
    values: dict[str, str] = {
        relative: f"{_REJECTION_MARKER}-{relative.replace('/', '-')}" for relative in REQUIRED_SOURCES
    }
    for credential in _local_provider_credentials():
        values[f"llm/provider/api_keys/{credential}"] = f"sk-{credential}-{_REJECTION_MARKER}"
    values["database/port"] = "5432"
    for relative, value in values.items():
        _private_write(secrets / relative, value)

    jwt_key = secrets / "jwt/private_key"
    jwt_key.parent.mkdir(parents=True)
    subprocess.run(
        [
            "openssl",
            "genpkey",
            "-algorithm",
            "RSA",
            "-pkeyopt",
            "rsa_keygen_bits:2048",
            "-out",
            str(jwt_key),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    jwt_key.chmod(0o600)

    age_key = tmp_path / "age.agekey"
    subprocess.run(["age-keygen", "-o", str(age_key)], check=True, capture_output=True, text=True)
    age_key.chmod(0o600)
    recipient = subprocess.run(
        ["age-keygen", "-y", str(age_key)], check=True, capture_output=True, text=True
    ).stdout.strip()

    sops_config = tmp_path / ".sops.yaml"
    sops_config.write_text(
        yaml.safe_dump(
            {
                "creation_rules": [
                    {
                        "path_regex": r"infra/k8s/gitops/secrets/local/.*\.sops\.yaml$",
                        "encrypted_regex": "^(data|stringData)$",
                        "age": recipient,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    plaintext = tmp_path / "provider.yaml"
    plaintext.write_text(
        yaml.safe_dump(
            {
                "apiVersion": "v1",
                "kind": "Secret",
                "metadata": {"name": "nohiki-llm-runtime", "namespace": "nohiki"},
                "type": "Opaque",
                "data": dict.fromkeys(sorted(_runtime_keys()), "c3ludGhldGlj"),
            }
        ),
        encoding="utf-8",
    )
    encrypted_secret = tmp_path / "nohiki-llm-runtime.sops.yaml"
    encryption = subprocess.run(
        [
            "sops",
            "--config",
            str(sops_config),
            "encrypt",
            "--age",
            recipient,
            "--encrypted-regex",
            "^(data|stringData)$",
            "--filename-override",
            "infra/k8s/gitops/secrets/local/nohiki-llm-runtime.sops.yaml",
            str(plaintext),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert encryption.returncode == 0, encryption.stderr
    encrypted = encryption.stdout
    encrypted_secret.write_text(encrypted, encoding="utf-8")
    plaintext.unlink()
    tls_plaintext = tmp_path / "tls-source.yaml"
    tls_plaintext.write_text(
        yaml.safe_dump(
            {
                "apiVersion": "v1",
                "kind": "Secret",
                "metadata": {
                    "name": "nohiki-model-egress-tls-source",
                    "namespace": "nohiki",
                },
                "type": "kubernetes.io/tls",
                "stringData": {
                    "tls.crt": "fixture-certificate",
                    "tls.key": "fixture-private-key",
                    "ca.crt": "fixture-ca-certificate",
                },
            }
        ),
        encoding="utf-8",
    )
    tls_encryption = subprocess.run(
        [
            "sops",
            "--config",
            str(sops_config),
            "encrypt",
            "--age",
            recipient,
            "--encrypted-regex",
            "^(data|stringData)$",
            "--filename-override",
            "infra/k8s/gitops/secrets/local/nohiki-model-egress-tls-source.sops.yaml",
            str(tls_plaintext),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert tls_encryption.returncode == 0, tls_encryption.stderr
    encrypted_secret.with_name("nohiki-model-egress-tls-source.sops.yaml").write_text(
        tls_encryption.stdout,
        encoding="utf-8",
    )
    tls_plaintext.unlink()

    cluster_dir = tmp_path / "clusters/local"
    cluster_dir.mkdir(parents=True)
    runtime_kustomization = cluster_dir / "runtime-secrets.yaml"
    runtime_kustomization.write_text(
        yaml.safe_dump(
            {
                "apiVersion": "kustomize.toolkit.fluxcd.io/v1",
                "kind": "Kustomization",
                "metadata": {"name": "runtime-secrets", "namespace": "flux-system"},
                "spec": {
                    "path": "./infra/k8s/gitops/secrets/local",
                    "wait": True,
                    "dependsOn": [{"name": "infrastructure"}],
                    "decryption": {
                        "provider": "sops",
                        "secretRef": {"name": "flux-sops"},
                    },
                    "sourceRef": {"kind": "GitRepository", "name": "flux-system"},
                    "prune": True,
                    "interval": "10m",
                    "timeout": "2m",
                    "retryInterval": "1m",
                    "healthChecks": [
                        {
                            "apiVersion": "v1",
                            "kind": "Secret",
                            "name": "nohiki-llm-runtime",
                            "namespace": "nohiki",
                        },
                        {
                            "apiVersion": "v1",
                            "kind": "Secret",
                            "name": "nohiki-model-egress-tls-source",
                            "namespace": "nohiki",
                        },
                        {
                            "apiVersion": "external-secrets.io/v1",
                            "kind": "SecretStore",
                            "name": "nohiki-local-secret-store",
                            "namespace": "nohiki",
                        },
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    (cluster_dir / "platform.yaml").write_text(
        yaml.safe_dump(
            {
                "apiVersion": "kustomize.toolkit.fluxcd.io/v1",
                "kind": "Kustomization",
                "metadata": {"name": "platform", "namespace": "flux-system"},
                "spec": {"dependsOn": [{"name": "runtime-secrets"}]},
            }
        ),
        encoding="utf-8",
    )
    secrets.chmod(0o700)
    for directory in (path for path in secrets.rglob("*") if path.is_dir()):
        directory.chmod(0o700)
    fixture = Sources(secrets, age_key, sops_config, encrypted_secret, runtime_kustomization)
    app_secret = encrypted_secret.with_name("nohiki-app-secrets.sops.yaml")
    provisioned = _provision(fixture, app_secret)
    assert provisioned.returncode == 0, provisioned.stderr
    return fixture


@pytest.fixture
def sources(tmp_path: Path, provisioned_sources_template: Sources) -> Sources:
    template_root = provisioned_sources_template.secrets.parent
    shutil.copytree(template_root, tmp_path, dirs_exist_ok=True)
    return Sources(
        secrets=tmp_path / provisioned_sources_template.secrets.relative_to(template_root),
        age_key=tmp_path / provisioned_sources_template.age_key.relative_to(template_root),
        sops_config=tmp_path / provisioned_sources_template.sops_config.relative_to(template_root),
        encrypted_secret=tmp_path / provisioned_sources_template.encrypted_secret.relative_to(template_root),
        runtime_kustomization=tmp_path / provisioned_sources_template.runtime_kustomization.relative_to(template_root),
    )


def _validate(sources: Sources) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(VALIDATOR),
            "--secrets-dir",
            str(sources.secrets),
            "--age-key-file",
            str(sources.age_key),
            "--sops-config",
            str(sources.sops_config),
            "--encrypted-secret",
            str(sources.encrypted_secret),
            "--encrypted-app-secrets",
            str(sources.encrypted_secret.with_name("nohiki-app-secrets.sops.yaml")),
            "--runtime-kustomization",
            str(sources.runtime_kustomization),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=os.environ | {"PATH": os.environ["PATH"]},
        check=False,
    )


def _provision(sources: Sources, output: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(PROVISIONER),
            "--secrets-dir",
            str(sources.secrets),
            "--output",
            str(output),
            "--sops-config",
            str(sources.sops_config),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _encrypted_inventory(path: Path) -> dict[str, set[str]]:
    documents = tuple(load_manifests(path.read_text(encoding="utf-8")))
    inventory = {document["metadata"]["name"]: set(document["stringData"]) for document in documents}
    assert len(inventory) == len(documents)
    assert all(
        (isinstance(value, str) and value.startswith("ENC[AES256_GCM,"))
        or (
            value == ""
            and (
                (document["metadata"]["name"] == "nohiki-redis-credentials" and key == "password")
                or (document["metadata"]["name"] == "nohiki-oauth-credentials" and key in OAUTH_KEYS)
            )
        )
        for document in documents
        for key, value in document["stringData"].items()
    )
    return inventory


def _runtime_encrypted_keys(path: Path) -> set[str]:
    document = load_mapping(path)
    assert document["metadata"] == {
        "name": "nohiki-llm-runtime",
        "namespace": "nohiki",
    }
    data = mapping_at(document, "data")
    assert all(isinstance(value, str) and value.startswith("ENC[AES256_GCM,") for value in data.values())
    return set(data)


def _assert_rejected_without_disclosure(
    result: subprocess.CompletedProcess[str],
) -> None:
    assert result.returncode != 0
    assert _REJECTION_MARKER not in result.stdout
    assert _REJECTION_MARKER not in result.stderr


def _install_path_swap(
    monkeypatch: pytest.MonkeyPatch,
    module: ModuleType,
    target: Path,
    replacement: Path,
) -> None:
    swapped = False

    def maybe_swap(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        dir_fd: int | None = None,
    ) -> None:
        nonlocal swapped
        if swapped:
            return
        candidate = Path(os.fsdecode(path))
        if not candidate.is_absolute() and dir_fd is not None:
            candidate = Path(f"/proc/self/fd/{dir_fd}").readlink() / candidate
        if candidate.absolute() != target.absolute():
            return
        target.unlink()
        target.symlink_to(replacement)
        swapped = True

    original_read_bytes = Path.read_bytes
    original_read_text = Path.read_text
    original_open = module.os.open

    def read_bytes(path: Path) -> bytes:
        maybe_swap(path)
        return original_read_bytes(path)

    def read_text(
        path: Path,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> str:
        maybe_swap(path)
        return original_read_text(path, encoding=encoding, errors=errors, newline=newline)

    def secure_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        maybe_swap(path, dir_fd)
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    monkeypatch.setattr(Path, "read_text", read_text)
    monkeypatch.setattr(module.os, "open", secure_open)


def test_valid_required_sources_pass_without_disclosing_values(
    sources: Sources,
) -> None:
    result = _validate(sources)
    assert result.returncode == 0, result.stderr
    assert _REJECTION_MARKER not in result.stdout
    assert _REJECTION_MARKER not in result.stderr


@pytest.mark.parametrize("state", ["missing", "empty", "symlink", "permissive"])
def test_unsafe_required_source_is_rejected(sources: Sources, tmp_path: Path, state: str) -> None:
    target = sources.secrets / "database/password"
    if state == "missing":
        target.unlink()
    elif state == "empty":
        target.write_text("", encoding="utf-8")
    elif state == "symlink":
        target.unlink()
        outside = tmp_path / "outside-secret"
        _private_write(outside, f"{_REJECTION_MARKER}-outside\n")
        target.symlink_to(outside)
    else:
        target.chmod(0o640)
    _assert_rejected_without_disclosure(_validate(sources))


@pytest.mark.parametrize("value", ["CHANGE_ME", "changeme", "replace-me", "example-secret"])
def test_placeholder_required_source_is_rejected(sources: Sources, value: str) -> None:
    _private_write(sources.secrets / "email/api_key", value + "\n")
    _assert_rejected_without_disclosure(_validate(sources))


def test_malformed_jwt_private_key_is_rejected(sources: Sources) -> None:
    _private_write(sources.secrets / "jwt/private_key", "not a private key\n")
    _assert_rejected_without_disclosure(_validate(sources))


@pytest.mark.parametrize("provider", sorted(_local_provider_credentials()))
def test_malformed_provider_source_is_rejected(sources: Sources, provider: str) -> None:
    _private_write(sources.secrets / f"llm/provider/api_keys/{provider}", "short\n")
    _assert_rejected_without_disclosure(_validate(sources))


def test_disabled_anthropic_source_is_rejected_as_dead_configuration(
    sources: Sources,
) -> None:
    assert "anthropic" not in _local_provider_credentials()
    _private_write(
        sources.secrets / "llm/provider/api_keys/anthropic",
        f"sk-anthropic-{_REJECTION_MARKER}",
    )
    _assert_rejected_without_disclosure(_validate(sources))


def test_runtime_source_and_key_tuples_follow_the_enabled_provider_snapshot(
    secret_modules: tuple[ModuleType, ModuleType],
) -> None:
    validator, _ = secret_modules
    snapshot_type = validator.LocalContractSnapshot
    snapshot = snapshot_type({}, {}, ("openrouter", "anthropic"), oauth_enabled=False)

    assert validator._runtime_required_sources(snapshot) == (
        "llm/provider/api_keys/openrouter",
        "llm/provider/api_keys/anthropic",
    )
    assert validator._runtime_keys(snapshot) == {
        "openrouter_api_key",
        "anthropic_api_key",
    }


@pytest.mark.parametrize("age_value", ["", "AGE-SECRET-KEY-1NOTVALID", "synthetic-age-placeholder"])
def test_empty_or_malformed_age_identity_is_rejected(sources: Sources, age_value: str) -> None:
    _private_write(sources.age_key, age_value)
    _assert_rejected_without_disclosure(_validate(sources))


@pytest.mark.parametrize("state", ["missing", "empty"])
def test_optional_oauth_and_redis_sources_may_be_absent_or_empty(sources: Sources, state: str) -> None:
    for relative in OPTIONAL_SOURCES:
        path = sources.secrets / relative
        if state == "empty":
            _private_write(path, "")
    result = _validate(sources)
    assert result.returncode == 0, result.stderr
    assert _REJECTION_MARKER not in result.stdout + result.stderr


@pytest.mark.parametrize("relative", OPTIONAL_SOURCES)
def test_present_optional_source_must_still_be_private(sources: Sources, relative: str) -> None:
    path = sources.secrets / relative
    _private_write(path, "synthetic-optional\n")
    path.chmod(0o644)
    _assert_rejected_without_disclosure(_validate(sources))


def test_encrypted_secret_name_namespace_and_key_shape_are_enforced(
    sources: Sources,
) -> None:
    original = sources.encrypted_secret.read_text(encoding="utf-8")
    for mutation in ("identity", "keys"):
        document = load_mapping(sources.encrypted_secret)
        if mutation == "identity":
            mapping_at(document, "metadata")["name"] = "wrong-name"
        else:
            mapping_at(document, "data").pop(next(iter(_runtime_keys())))
        sources.encrypted_secret.write_text(yaml.safe_dump(document), encoding="utf-8")
        _assert_rejected_without_disclosure(_validate(sources))
        sources.encrypted_secret.write_text(original, encoding="utf-8")


def test_encrypted_tls_secret_name_and_key_shape_are_enforced(sources: Sources) -> None:
    path = sources.encrypted_secret.with_name("nohiki-model-egress-tls-source.sops.yaml")
    original = path.read_text(encoding="utf-8")
    for mutation in ("identity", "keys"):
        document = load_mapping(path)
        if mutation == "identity":
            mapping_at(document, "metadata")["name"] = "wrong-name"
        else:
            mapping_at(document, "stringData").pop("ca.crt")
        path.write_text(yaml.safe_dump(document), encoding="utf-8")
        _assert_rejected_without_disclosure(_validate(sources))
        path.write_text(original, encoding="utf-8")


def test_plaintext_provider_manifest_is_rejected(sources: Sources) -> None:
    sources.encrypted_secret.write_text(
        yaml.safe_dump(
            {
                "apiVersion": "v1",
                "kind": "Secret",
                "metadata": {"name": "nohiki-llm-runtime", "namespace": "nohiki"},
                "type": "Opaque",
                "data": dict.fromkeys(_runtime_keys(), "cGxhaW50ZXh0"),
            }
        ),
        encoding="utf-8",
    )
    _assert_rejected_without_disclosure(_validate(sources))


def test_validation_is_read_only_even_when_rejected(sources: Sources, tmp_path: Path) -> None:
    _private_write(sources.secrets / "database/password", "CHANGE_ME\n")
    before = {path: (path.read_bytes(), path.stat().st_mode) for path in tmp_path.rglob("*") if path.is_file()}
    result = _validate(sources)
    _assert_rejected_without_disclosure(result)
    after = {path: (path.read_bytes(), path.stat().st_mode) for path in tmp_path.rglob("*") if path.is_file()}
    assert after == before
    assert not tuple(tmp_path.rglob("*generated-values*"))


def test_provisioner_writes_exact_encrypted_application_inventory(sources: Sources, tmp_path: Path) -> None:
    output_dir = tmp_path / "published"
    output_dir.mkdir()
    output = output_dir / "nohiki-app-secrets.sops.yaml"
    result = _provision(sources, output)
    assert result.returncode == 0, result.stderr
    assert output.stat().st_mode & 0o777 == 0o600
    inventory = _encrypted_inventory(output)
    expected = dict(APPLICATION_SECRET_KEYS)
    for service in DATABASE_SERVICES:
        expected[f"{service}-db-credentials"] = DATABASE_KEYS
        expected[f"{service}-debezium-credentials"] = DATABASE_KEYS
    assert inventory == expected
    documents = tuple(load_manifests(output.read_text(encoding="utf-8")))
    database_names = {
        f"{service}-{suffix}" for service in DATABASE_SERVICES for suffix in ("db-credentials", "debezium-credentials")
    }
    assert len(DATABASE_SERVICES) == 14
    assert len(database_names) == 28
    database_documents = {
        document["metadata"]["name"]: document
        for document in documents
        if document["metadata"]["name"] in database_names
    }
    assert set(database_documents) == database_names
    for document in database_documents.values():
        assert document["metadata"]["labels"] == {"cnpg.io/reload": "true"}
    ciphertext = output.read_text(encoding="utf-8")
    assert _REJECTION_MARKER not in ciphertext
    assert "PRIVATE KEY-----" not in ciphertext
    assert tuple(output_dir.iterdir()) == (output,)
    assert not tuple(tmp_path.rglob("*generated-values*"))


def test_disabled_local_oauth_rejects_dead_sources(sources: Sources, tmp_path: Path) -> None:
    _private_write(sources.secrets / "oauth/github_client_id", "fixture-github-client-id")
    _private_write(sources.secrets / "oauth/github_client_secret", "fixture-github-secret")
    output = tmp_path / "nohiki-app-secrets.sops.yaml"
    before = (output.read_bytes(), output.stat().st_mode)

    result = _provision(sources, output)

    _assert_rejected_without_disclosure(result)
    assert (output.read_bytes(), output.stat().st_mode) == before


@pytest.mark.parametrize("relative", [None, *OPTIONAL_SOURCES[1:]])
def test_enabled_local_oauth_rejects_empty_or_partial_provider_pairs(
    sources: Sources,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    secret_modules: tuple[ModuleType, ModuleType],
    relative: str | None,
) -> None:
    validator, provisioner = secret_modules
    original = validator._load_local_contract()
    enabled = type(original)(
        original.base_values,
        original.local_values,
        original.provider_credentials,
        oauth_enabled=True,
    )
    monkeypatch.setattr(provisioner, "_load_local_contract", lambda: enabled)
    if relative is not None:
        _private_write(
            sources.secrets / relative,
            f"fixture-{relative.replace('/', '-')}",
        )
    output_dir = tmp_path / "partial-oauth-output"
    output_dir.mkdir()
    output = output_dir / "nohiki-app-secrets.sops.yaml"

    with pytest.raises(provisioner.ProvisionError):
        provisioner.provision(sources.secrets, output, sources.sops_config)

    assert not tuple(output_dir.iterdir())


def test_enabled_local_oauth_emits_the_exact_rendered_consumer_keys(
    sources: Sources,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    secret_modules: tuple[ModuleType, ModuleType],
) -> None:
    validator, provisioner = secret_modules
    original_contract = validator._load_local_contract()
    enabled = type(original_contract)(
        original_contract.base_values,
        original_contract.local_values,
        original_contract.provider_credentials,
        oauth_enabled=True,
    )
    monkeypatch.setattr(provisioner, "_load_local_contract", lambda: enabled)
    _private_write(sources.secrets / "oauth/google_client_id", "fixture-google-client-id")
    _private_write(sources.secrets / "oauth/google_client_secret", "fixture-google-secret")
    output_dir = tmp_path / "enabled-oauth-output"
    output_dir.mkdir()
    output = output_dir / "nohiki-app-secrets.sops.yaml"

    provisioner.provision(sources.secrets, output, sources.sops_config)

    assert _encrypted_inventory(output)["nohiki-oauth-credentials"] == OAUTH_KEYS
    recipient = validator._validate_age_key(sources.age_key)
    assert validator._validate_encrypted_app_secrets(output, recipient, enabled) == set(_encrypted_inventory(output))
    original = tuple(load_manifests(output.read_text(encoding="utf-8")))
    oauth = next(document for document in original if document["metadata"]["name"] == "nohiki-oauth-credentials")
    assert oauth["stringData"]["github_client_id"] == ""
    assert oauth["stringData"]["github_client_secret"] == ""
    for mutation in ("partial-empty-pair", "partial-encrypted-pair", "all-empty"):
        documents = list(load_manifests(output.read_text(encoding="utf-8")))
        oauth = next(document for document in documents if document["metadata"]["name"] == "nohiki-oauth-credentials")
        data = oauth["stringData"]
        if mutation == "partial-empty-pair":
            data["google_client_secret"] = ""
        elif mutation == "partial-encrypted-pair":
            data["github_client_id"] = data["google_client_id"]
        else:
            data.update(dict.fromkeys(OAUTH_KEYS, ""))
        output.write_text(yaml.safe_dump_all(documents), encoding="utf-8")
        with pytest.raises(validator.ValidationError):
            validator._validate_encrypted_app_secrets(output, recipient, enabled)
        output.write_text(yaml.safe_dump_all(original), encoding="utf-8")


def test_provisioning_failure_preserves_previous_ciphertext_without_partial_files(
    sources: Sources, tmp_path: Path
) -> None:
    output_dir = tmp_path / "published"
    output_dir.mkdir()
    output = output_dir / "nohiki-app-secrets.sops.yaml"
    output.write_text("prior-ciphertext\n", encoding="utf-8")
    output.chmod(0o600)
    (sources.secrets / "database/password").unlink()

    result = _provision(sources, output)
    _assert_rejected_without_disclosure(result)
    assert output.read_text(encoding="utf-8") == "prior-ciphertext\n"
    assert tuple(output_dir.iterdir()) == (output,)


def test_source_path_swap_after_validation_is_rejected(
    sources: Sources,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    secret_modules: tuple[ModuleType, ModuleType],
) -> None:
    validator, _ = secret_modules
    target = sources.secrets / "database/password"
    replacement = tmp_path / "replacement-source"
    replacement.write_bytes(target.read_bytes())
    replacement.chmod(0o600)
    _install_path_swap(monkeypatch, validator, target, replacement)

    with pytest.raises(validator.ValidationError):
        validator._validate_sources(sources.secrets)


@pytest.mark.parametrize("replacement_mode", [0o700, 0o770])
def test_source_root_replacement_after_initial_check_is_rejected(
    sources: Sources,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    secret_modules: tuple[ModuleType, ModuleType],
    replacement_mode: int,
) -> None:
    validator, _ = secret_modules
    replacement = tmp_path / "replacement-secrets"
    shutil.copytree(sources.secrets, replacement)
    replacement.chmod(replacement_mode)
    displaced = tmp_path / "displaced-secrets"
    original_fstat = validator.os.fstat
    swapped = False

    def stat_then_swap(descriptor: int) -> os.stat_result:
        nonlocal swapped
        metadata = original_fstat(descriptor)
        descriptor_target = Path(f"/proc/self/fd/{descriptor}").resolve()
        if descriptor_target == sources.secrets and not swapped:
            swapped = True
            sources.secrets.rename(displaced)
            replacement.rename(sources.secrets)
        return metadata

    monkeypatch.setattr(validator.os, "fstat", stat_then_swap)

    validated = validator._validate_sources(sources.secrets)
    try:
        with pytest.raises(validator.ValidationError):
            validated.revalidate()
    finally:
        validated.close()


def test_forbidden_provider_creation_after_absence_check_is_rejected(
    sources: Sources,
    monkeypatch: pytest.MonkeyPatch,
    secret_modules: tuple[ModuleType, ModuleType],
) -> None:
    validator, _ = secret_modules
    forbidden = sources.secrets / "llm/provider/api_keys/anthropic"
    assert not forbidden.exists()
    original_stat = validator.os.stat
    created = False

    def create_after_absence(
        path: str | int | bytes | os.PathLike[str] | os.PathLike[bytes],
        *args: object,
        **kwargs: object,
    ) -> os.stat_result:
        nonlocal created
        try:
            return original_stat(path, *args, **kwargs)
        except FileNotFoundError:
            if path == "anthropic" and not created:
                created = True
                _private_write(forbidden, f"sk-anthropic-{_REJECTION_MARKER}")
            raise

    monkeypatch.setattr(validator.os, "stat", create_after_absence)

    validated = validator._validate_sources(sources.secrets)
    try:
        with pytest.raises(validator.ValidationError):
            validated.revalidate()
    finally:
        validated.close()


def _validate_artifact(
    validator: ModuleType,
    sources: Sources,
    target: Path,
    artifact: str,
) -> None:
    if artifact == "application":
        recipient = validator._validate_age_key(sources.age_key)
        validator._validate_encrypted_app_secrets(
            target,
            recipient,
            validator._load_local_contract(),
        )
    else:
        validator._validate_sops_and_secret(
            sources.sops_config,
            sources.encrypted_secret,
            validator._load_local_contract(),
        )


@pytest.mark.parametrize("artifact", ["policy", "provider", "application"])
def test_policy_and_manifest_path_swaps_are_rejected(
    sources: Sources,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    secret_modules: tuple[ModuleType, ModuleType],
    artifact: str,
) -> None:
    validator, _ = secret_modules
    target = {
        "policy": sources.sops_config,
        "provider": sources.encrypted_secret,
        "application": sources.encrypted_secret.with_name("nohiki-app-secrets.sops.yaml"),
    }[artifact]
    replacement = tmp_path / f"replacement-{artifact}.yaml"
    replacement.write_bytes(target.read_bytes())
    replacement.chmod(0o600)
    _install_path_swap(monkeypatch, validator, target, replacement)

    with pytest.raises(validator.ValidationError):
        _validate_artifact(validator, sources, target, artifact)


@pytest.mark.parametrize("artifact", ["policy", "provider", "application"])
def test_policy_and_manifest_symlink_substitution_is_rejected(
    sources: Sources,
    tmp_path: Path,
    secret_modules: tuple[ModuleType, ModuleType],
    artifact: str,
) -> None:
    validator, _ = secret_modules
    target = {
        "policy": sources.sops_config,
        "provider": sources.encrypted_secret,
        "application": sources.encrypted_secret.with_name("nohiki-app-secrets.sops.yaml"),
    }[artifact]
    replacement = tmp_path / f"symlink-target-{artifact}.yaml"
    replacement.write_bytes(target.read_bytes())
    replacement.chmod(0o600)
    target.unlink()
    target.symlink_to(replacement)

    with pytest.raises(validator.ValidationError):
        _validate_artifact(validator, sources, target, artifact)


def test_helm_contract_snapshot_uses_validated_bytes_after_path_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    secret_modules: tuple[ModuleType, ModuleType],
) -> None:
    validator, _ = secret_modules
    helm = tmp_path / "infra/k8s/helm"
    helm.mkdir(parents=True)
    base = helm / "values.yaml"
    local = helm / "values.local.yaml"
    base.write_bytes(BASE_VALUES.read_bytes())
    local.write_bytes(LOCAL_VALUES.read_bytes())
    monkeypatch.setattr(validator, "_ROOT", tmp_path)
    original_read = validator._read_regular_file

    def read_then_replace(path: Path, label: str) -> tuple[bytes, os.stat_result]:
        validated = original_read(path, label)
        if path == base:
            replacement = helm / "replacement.yaml"
            replacement.write_text("invalid: [", encoding="utf-8")
            replacement.replace(path)
        return validated

    monkeypatch.setattr(validator, "_read_regular_file", read_then_replace)
    snapshot = validator._load_local_contract()

    assert snapshot.provider_credentials == tuple(sorted(_local_provider_credentials()))
    assert base.read_text(encoding="utf-8") == "invalid: ["


def test_app_inventory_uses_captured_values_after_live_chart_replacement(
    sources: Sources,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    secret_modules: tuple[ModuleType, ModuleType],
) -> None:
    validator, provisioner = secret_modules
    contract = validator._load_local_contract()
    validated = validator._validate_sources(sources.secrets, contract=contract)
    chart = tmp_path / "helm"
    shutil.copytree(BASE_VALUES.parent, chart)
    monkeypatch.setattr(provisioner, "_CHART", chart)
    values_path = tmp_path / "secret-values.yaml"
    values_path.write_text(
        yaml.safe_dump(
            provisioner._values(validated, oauth_enabled=contract.oauth_enabled),
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    for name in ("values.yaml", "values.local.yaml"):
        replacement = chart / f"replacement-{name}"
        replacement.write_text("global: {}\n", encoding="utf-8")
        replacement.replace(chart / name)

    documents = provisioner._render(values_path, contract)

    provisioner._verify_plain_inventory(documents, contract)
    assert {document["metadata"]["name"] for document in documents} == provisioner._expected_names(contract)


@pytest.mark.parametrize("mutation", ["content", "permissions", "size"])
def test_descriptor_read_rejects_file_mutation_before_eof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    secret_modules: tuple[ModuleType, ModuleType],
    mutation: str,
) -> None:
    validator, _ = secret_modules
    path = tmp_path / "mutable-source"
    path.write_bytes(b"A" * 131_072)
    path.chmod(0o600)
    original_read = validator.os.read
    mutated = False

    def mutate_after_first_chunk(descriptor: int, size: int) -> bytes:
        nonlocal mutated
        chunk = original_read(descriptor, size)
        if chunk and not mutated:
            mutated = True
            if mutation == "content":
                path.write_bytes(b"B" * 131_072)
            elif mutation == "permissions":
                path.chmod(0o640)
            else:
                with path.open("ab") as stream:
                    stream.write(b"B")
        return chunk

    monkeypatch.setattr(validator.os, "read", mutate_after_first_chunk)

    with pytest.raises(validator.ValidationError):
        validator._read_regular_file(path, "synthetic source")


def test_descriptor_read_rejects_a_source_over_one_mebibyte(
    tmp_path: Path,
    secret_modules: tuple[ModuleType, ModuleType],
) -> None:
    validator, _ = secret_modules
    path = tmp_path / "oversized-source"
    path.write_bytes(b"A" * (1024 * 1024 + 1))
    path.chmod(0o600)

    with pytest.raises(validator.ValidationError):
        validator._read_regular_file(path, "synthetic source")


def test_helm_contract_loader_rejects_a_symlinked_trust_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    secret_modules: tuple[ModuleType, ModuleType],
) -> None:
    validator, _ = secret_modules
    actual = tmp_path / "actual-helm"
    actual.mkdir()
    (actual / "values.yaml").write_bytes(BASE_VALUES.read_bytes())
    (actual / "values.local.yaml").write_bytes(LOCAL_VALUES.read_bytes())
    k8s = tmp_path / "infra/k8s"
    k8s.mkdir(parents=True)
    (k8s / "helm").symlink_to(actual, target_is_directory=True)
    monkeypatch.setattr(validator, "_ROOT", tmp_path)

    with pytest.raises(validator.ValidationError):
        validator._load_local_contract()


def test_provisioner_rejects_source_mutation_before_publish_and_preserves_output(
    sources: Sources,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    secret_modules: tuple[ModuleType, ModuleType],
) -> None:
    _, provisioner = secret_modules
    target = sources.secrets / "database/password"
    original_validate = provisioner._validate_sources
    original_run = provisioner._run
    invoked_programs: list[str] = []

    def capture_run(
        command: list[str],
        *,
        cwd: Path = ROOT,
        pass_fds: tuple[int, ...] = (),
    ) -> subprocess.CompletedProcess[str]:
        invoked_programs.append(command[0])
        return original_run(command, cwd=cwd, pass_fds=pass_fds)

    def validate_then_replace(path: Path, **kwargs: object) -> object:
        validated = original_validate(path, **kwargs)
        _private_write(target, "different-safe-synthetic-password\n")
        return validated

    monkeypatch.setattr(provisioner, "_validate_sources", validate_then_replace)
    monkeypatch.setattr(provisioner, "_run", capture_run)
    output = tmp_path / "nohiki-app-secrets.sops.yaml"
    output.write_text("prior-ciphertext\n", encoding="utf-8")
    output.chmod(0o600)
    before = (output.read_bytes(), output.stat().st_mode)

    with pytest.raises(provisioner.ProvisionError):
        provisioner.provision(sources.secrets, output, sources.sops_config)

    assert (output.read_bytes(), output.stat().st_mode) == before
    assert "sops" not in invoked_programs
    assert tuple(tmp_path.glob(".nohiki-app-secrets.sops.yaml.*")) == ()


def test_provisioner_rejects_a_symlinked_output_parent(sources: Sources, tmp_path: Path) -> None:
    actual_parent = tmp_path / "actual-output"
    actual_parent.mkdir()
    linked_parent = tmp_path / "linked-output"
    linked_parent.symlink_to(actual_parent, target_is_directory=True)

    result = _provision(sources, linked_parent / "nohiki-app-secrets.sops.yaml")

    _assert_rejected_without_disclosure(result)
    assert not tuple(actual_parent.iterdir())


def test_provisioner_rejects_output_path_parent_traversal(sources: Sources, tmp_path: Path) -> None:
    declared_parent = tmp_path / "declared-output"
    declared_parent.mkdir()
    escaped = tmp_path / "nohiki-app-secrets.sops.yaml"

    escaped.unlink()
    result = _provision(sources, declared_parent / ".." / escaped.name)

    _assert_rejected_without_disclosure(result)
    assert not escaped.exists()


@pytest.mark.parametrize(
    "corruption",
    ["missing-sops", "wrong-recipient", "extra-recipient", "pgp", "plaintext"],
)
def test_provisioner_rejects_untrusted_sops_output_before_publish(
    sources: Sources,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    secret_modules: tuple[ModuleType, ModuleType],
    corruption: str,
) -> None:
    _, provisioner = secret_modules
    original_run = provisioner._run

    def corrupt_sops_output(
        command: list[str],
        *,
        cwd: Path = ROOT,
        pass_fds: tuple[int, ...] = (),
    ) -> subprocess.CompletedProcess[str]:
        result = original_run(command, cwd=cwd, pass_fds=pass_fds)
        if command[0] != "sops":
            return result
        output = Path(command[command.index("--output") + 1])
        documents = [dict(document) for document in load_manifests(output.read_text(encoding="utf-8"))]
        if corruption == "missing-sops":
            for document in documents:
                document.pop("sops")
        elif corruption == "wrong-recipient":
            for document in documents:
                mapping_sequence_at(mapping_at(document, "sops"), "age")[0]["recipient"] = "age1" + "q" * 58
        elif corruption == "extra-recipient":
            for document in documents:
                age = mapping_sequence_at(mapping_at(document, "sops"), "age")
                age.append(dict(age[0]))
        elif corruption == "pgp":
            for document in documents:
                mapping_at(document, "sops")["pgp"] = [{"fp": "synthetic-recipient"}]
        else:
            data = mapping_at(documents[0], "stringData")
            data[next(iter(data))] = "safe-plaintext-marker"
        output.write_text(yaml.safe_dump_all(documents, sort_keys=False), encoding="utf-8")
        return result

    monkeypatch.setattr(provisioner, "_run", corrupt_sops_output)
    output = tmp_path / "nohiki-app-secrets.sops.yaml"
    output.write_text("prior-ciphertext\n", encoding="utf-8")
    output.chmod(0o600)

    with pytest.raises(provisioner.ProvisionError):
        provisioner.provision(sources.secrets, output, sources.sops_config)

    assert output.read_text(encoding="utf-8") == "prior-ciphertext\n"
    assert tuple(tmp_path.glob(".nohiki-app-secrets.sops.yaml.*")) == ()


def test_provisioner_requires_a_complete_age_recipient(
    sources: Sources,
    tmp_path: Path,
    secret_modules: tuple[ModuleType, ModuleType],
) -> None:
    _, provisioner = secret_modules
    config = load_mapping(sources.sops_config)
    mapping_sequence_at(config, "creation_rules")[0]["age"] = "age1short"
    malformed = tmp_path / "malformed-sops.yaml"
    malformed.write_text(yaml.safe_dump(config), encoding="utf-8")

    with pytest.raises(provisioner.ProvisionError):
        provisioner._validate_policy(malformed)


def test_readme_has_only_portable_explicit_secret_authoring_commands() -> None:
    readme = HELM_README.read_text(encoding="utf-8")
    assert "/home/" not in readme
    assert "values.secrets.yaml" not in readme
    assert "generated-values" not in readme
    source_argument = '--source-dir "$NOHIKI_LOCAL_SECRETS_DIR"'
    assert readme.count(source_argument) == 2
    assert "${NOHIKI_LOCAL_SECRETS_DIR:?" in readme
    assert "NOHIKI_LOCAL_SECRETS_DIR must be absolute" in readme
    for script, output in (
        (
            "provision_local_app_secrets.py",
            "infra/k8s/gitops/secrets/local/nohiki-app-secrets.sops.yaml",
        ),
        (
            "provision_local_runtime_secrets.py",
            "infra/k8s/gitops/secrets/local/nohiki-llm-runtime.sops.yaml",
        ),
        (
            "provision_local_tls_source.py",
            "infra/k8s/gitops/secrets/local/nohiki-model-egress-tls-source.sops.yaml",
        ),
    ):
        assert f"uv run python scripts/infra/{script}" in readme
        assert f"--output {output}" in readme


@pytest.mark.parametrize("provisioner", [PROVISIONER, RUNTIME_PROVISIONER])
def test_missing_explicit_source_directory_changes_no_output(tmp_path: Path, provisioner: Path) -> None:
    output = tmp_path / (
        "nohiki-app-secrets.sops.yaml" if provisioner == PROVISIONER else "nohiki-llm-runtime.sops.yaml"
    )
    output.write_text("prior-ciphertext\n", encoding="utf-8")
    output.chmod(0o600)

    result = subprocess.run(
        [
            sys.executable,
            str(provisioner),
            "--output",
            str(output),
            "--sops-config",
            str(tmp_path / "unused-sops.yaml"),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert output.read_text(encoding="utf-8") == "prior-ciphertext\n"
    assert tuple(tmp_path.iterdir()) == (output,)


def test_observability_storage_is_derived_from_the_same_validated_s3_bytes(
    sources: Sources,
    tmp_path: Path,
    secret_modules: tuple[ModuleType, ModuleType],
) -> None:
    _, provisioner = secret_modules
    contract = provisioner._load_local_contract()
    validated = provisioner._validate_sources(
        sources.secrets,
        required_sources=provisioner._APP_REQUIRED_SOURCES,
        contract=contract,
    )
    values_path = tmp_path / "synthetic-values.yaml"
    values_path.write_text(
        yaml.safe_dump(
            provisioner._values(validated, oauth_enabled=contract.oauth_enabled),
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    documents = provisioner._render(values_path, contract)
    by_name = {document["metadata"]["name"]: document for document in documents}
    app = by_name["nohiki-s3-credentials"]["stringData"]
    rustfs = by_name["nohiki-rustfs-credentials"]["stringData"]
    observability = by_name["observability-storage-credentials"]["stringData"]
    access_digests = {
        hashlib.sha256(value.encode()).digest()
        for value in (
            app["access_key"],
            rustfs["root-user"],
            rustfs["access-key"],
            observability["AWS_ACCESS_KEY_ID"],
        )
    }
    secret_digests = {
        hashlib.sha256(value.encode()).digest()
        for value in (
            app["secret_key"],
            rustfs["root-password"],
            rustfs["secret-key"],
            observability["AWS_SECRET_ACCESS_KEY"],
        )
    }

    assert len(access_digests) == 1
    assert len(secret_digests) == 1
    assert set(observability) == APPLICATION_SECRET_KEYS["observability-storage-credentials"]
    assert observability["AWS_REGION"] == "local"


@pytest.mark.parametrize(
    "mutation",
    [
        "extra-top-level",
        "wrong-api-version",
        "wrong-kind",
        "extra-metadata",
        "extra-spec",
        "extra-decryption",
        "extra-source-ref",
        "extra-dependency",
        "wrong-interval",
        *(
            f"missing-spec-{key}"
            for key in (
                "path",
                "wait",
                "dependsOn",
                "decryption",
                "sourceRef",
                "prune",
                "interval",
                "timeout",
                "retryInterval",
                "healthChecks",
            )
        ),
    ],
)
def test_runtime_flux_kustomization_rejects_schema_drift(
    sources: Sources,
    secret_modules: tuple[ModuleType, ModuleType],
    mutation: str,
) -> None:
    validator, _ = secret_modules
    document = load_mapping(sources.runtime_kustomization)
    if mutation == "extra-top-level":
        document["unexpected"] = True
    elif mutation == "wrong-api-version":
        document["apiVersion"] = "kustomize.toolkit.fluxcd.io/v1beta2"
    elif mutation == "wrong-kind":
        document["kind"] = "Secret"
    elif mutation == "extra-metadata":
        mapping_at(document, "metadata")["labels"] = {"unexpected": "true"}
    elif mutation == "extra-spec":
        mapping_at(document, "spec")["force"] = True
    elif mutation == "extra-decryption":
        mapping_at(document, "spec", "decryption")["unexpected"] = True
    elif mutation == "extra-source-ref":
        mapping_at(document, "spec", "sourceRef")["namespace"] = "flux-system"
    elif mutation == "wrong-interval":
        mapping_at(document, "spec")["interval"] = "9m"
    elif mutation.startswith("missing-spec-"):
        mapping_at(document, "spec").pop(mutation.removeprefix("missing-spec-"))
    else:
        mapping_sequence_at(mapping_at(document, "spec"), "dependsOn")[0]["namespace"] = "flux-system"
    sources.runtime_kustomization.write_text(yaml.safe_dump(document), encoding="utf-8")

    with pytest.raises(validator.ValidationError):
        validator._validate_flux(sources.runtime_kustomization)


@pytest.mark.parametrize(
    "mutation",
    [
        "extra-top-level",
        "wrong-api-version",
        "wrong-kind",
        "extra-metadata",
        "extra-resource",
        "missing-resource",
    ],
)
def test_local_secret_kustomization_rejects_schema_or_inventory_drift(
    tmp_path: Path,
    secret_modules: tuple[ModuleType, ModuleType],
    mutation: str,
) -> None:
    validator, _ = secret_modules
    source = ROOT / "infra/k8s/gitops/secrets/local/kustomization.yaml"
    document = load_mapping(source)
    if mutation == "extra-top-level":
        document["unexpected"] = True
    elif mutation == "wrong-api-version":
        document["apiVersion"] = "kustomize.config.k8s.io/v1beta2"
    elif mutation == "wrong-kind":
        document["kind"] = "Secret"
    elif mutation == "extra-metadata":
        document["metadata"] = {"name": "unexpected"}
    elif mutation == "extra-resource":
        sequence_at(document, "resources").append("unexpected.yaml")
    else:
        sequence_at(document, "resources").pop()
    path = tmp_path / "kustomization.yaml"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")

    with pytest.raises(validator.ValidationError):
        validator._validate_local_kustomization(path)


def test_local_observability_uses_one_sops_owner_and_no_fake_eso() -> None:
    result = subprocess.run(
        ["kustomize", "build", str(LOCAL_OBSERVABILITY)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    documents = tuple(load_manifests(result.stdout))
    external_targets = {
        mapping_at(dict(document), "spec", "target").get("name")
        for document in documents
        if document.get("kind") == "ExternalSecret"
    }
    assert "observability-storage-credentials" not in external_targets
    assert "grafana-admin-credentials" not in external_targets
    assert not any(document.get("kind") == "ClusterSecretStore" for document in documents)
    rendered = yaml.safe_dump_all(documents)
    for stale in (
        "minioadmin",
        "minioadmin123",
        "rustfs_admin",
        "rustfs_secret",
        "grafana-admin-credentials",
    ):
        assert stale not in rendered


def test_local_object_store_consumers_use_the_single_storage_secret() -> None:
    base = load_mapping(BASE_VALUES)
    local = load_mapping(LOCAL_VALUES)
    reference = [{"secretRef": {"name": "observability-storage-credentials"}}]
    assert mapping_at(base, "mimir-distributed", "global")["extraEnvFrom"] == reference
    assert mapping_at(base, "tempo-distributed", "global")["extraEnvFrom"] == reference
    assert mapping_at(local, "loki", "write")["extraEnvFrom"] == reference
    assert mapping_at(local, "loki", "read")["extraEnvFrom"] == reference
    assert mapping_at(local, "loki", "backend")["extraEnvFrom"] == reference
    assert mapping_at(local, "pyroscope", "pyroscope")["extraEnvFrom"] == reference
    grafana_patch = (LOCAL_OBSERVABILITY / "kustomization.yaml").read_text(encoding="utf-8")
    assert 'enabled: "true"' in grafana_patch
    assert "org_role: Viewer" in grafana_patch


@pytest.mark.parametrize("forbidden", ["extra-age", "pgp", "kms", "gcp_kms", "azure_kv", "hc_vault"])
def test_sops_policy_rejects_every_noncanonical_recipient_configuration(
    sources: Sources,
    tmp_path: Path,
    secret_modules: tuple[ModuleType, ModuleType],
    forbidden: str,
) -> None:
    validator, provisioner = secret_modules
    config = load_mapping(sources.sops_config)
    rule = mapping_sequence_at(config, "creation_rules")[0]
    if forbidden == "extra-age":
        rule["age"] = [rule["age"], rule["age"]]
    else:
        rule[forbidden] = [{"synthetic": "recipient"}]
    policy = tmp_path / f"forbidden-{forbidden}.sops.yaml"
    policy.write_text(yaml.safe_dump(config), encoding="utf-8")

    with pytest.raises(provisioner.ProvisionError):
        provisioner._validate_policy(policy)
    with pytest.raises(validator.ValidationError):
        validator._validate_sops_and_secret(
            policy,
            sources.encrypted_secret,
            validator._load_local_contract(),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("age-enc", ""),
        ("age-enc", "not-an-age-envelope"),
        ("lastmodified", None),
        ("lastmodified", "14 July 2026"),
        ("version", None),
        ("version", "not-semver"),
    ],
)
def test_runtime_manifest_rejects_noncanonical_sops_envelope_metadata(
    sources: Sources,
    secret_modules: tuple[ModuleType, ModuleType],
    field: str,
    value: str | None,
) -> None:
    validator, _ = secret_modules
    document = load_mapping(sources.encrypted_secret)
    sops = mapping_at(document, "sops")
    if field == "age-enc":
        mapping_sequence_at(sops, "age")[0]["enc"] = value
    elif value is None:
        sops.pop(field)
    else:
        sops[field] = value
    sources.encrypted_secret.write_text(yaml.safe_dump(document), encoding="utf-8")

    with pytest.raises(validator.ValidationError):
        validator._validate_sops_and_secret(
            sources.sops_config,
            sources.encrypted_secret,
            validator._load_local_contract(),
        )


@pytest.mark.parametrize("forbidden", ["extra-age", "pgp", "kms", "gcp_kms", "azure_kv", "hc_vault"])
def test_tracked_runtime_manifest_rejects_extra_recipient_backends(sources: Sources, forbidden: str) -> None:
    document = load_mapping(sources.encrypted_secret)
    sops = mapping_at(document, "sops")
    if forbidden == "extra-age":
        age = mapping_sequence_at(sops, "age")
        age.append(dict(age[0]))
    else:
        sops[forbidden] = [{"synthetic": "recipient"}]
    sources.encrypted_secret.write_text(yaml.safe_dump(document), encoding="utf-8")

    _assert_rejected_without_disclosure(_validate(sources))


def test_runtime_provisioner_publishes_exact_enabled_provider_inventory(
    sources: Sources,
    tmp_path: Path,
    runtime_provisioner_module: ModuleType,
) -> None:
    output_dir = tmp_path / "runtime-output"
    output_dir.mkdir()
    output = output_dir / "nohiki-llm-runtime.sops.yaml"

    runtime_provisioner_module.provision(sources.secrets, output, sources.sops_config)

    assert _runtime_encrypted_keys(output) == _runtime_keys()
    assert output.stat().st_mode & 0o777 == 0o600
    assert tuple(output_dir.iterdir()) == (output,)
    assert not tuple(tmp_path.rglob("*generated-values*"))
    recipient = runtime_provisioner_module._validate_sops_and_secret(
        sources.sops_config,
        output,
        runtime_provisioner_module._load_local_contract(),
    )
    assert recipient == runtime_provisioner_module._validate_policy(sources.sops_config)


@pytest.mark.parametrize("mutation", ["missing", "dead-anthropic", "extra"])
def test_runtime_provisioner_rejects_nonexact_generated_key_inventory(
    sources: Sources,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    runtime_provisioner_module: ModuleType,
    mutation: str,
) -> None:
    original_run = runtime_provisioner_module._run

    def mutate_output(
        command: list[str],
        *,
        cwd: Path = ROOT,
        pass_fds: tuple[int, ...] = (),
    ) -> subprocess.CompletedProcess[str]:
        result = original_run(command, cwd=cwd, pass_fds=pass_fds)
        if command[0] != "sops":
            return result
        output = Path(command[command.index("--output") + 1])
        document = load_mapping(output)
        key = next(iter(_runtime_keys()))
        if mutation == "missing":
            data = mapping_at(document, "data")
            data.pop(key)
        elif mutation == "dead-anthropic":
            data = mapping_at(document, "data")
            data["anthropic_api_key"] = data[key]
        else:
            data = mapping_at(document, "data")
            data["unexpected"] = data[key]
        output.write_text(yaml.safe_dump(document), encoding="utf-8")
        return result

    monkeypatch.setattr(runtime_provisioner_module, "_run", mutate_output)
    output_dir = tmp_path / "invalid-runtime-output"
    output_dir.mkdir()
    output = output_dir / "nohiki-llm-runtime.sops.yaml"

    with pytest.raises(runtime_provisioner_module.ProvisionError):
        runtime_provisioner_module.provision(sources.secrets, output, sources.sops_config)

    assert not tuple(output_dir.iterdir())


def test_validator_accepts_the_three_generated_sops_artifacts(
    sources: Sources,
    runtime_provisioner_module: ModuleType,
) -> None:
    runtime_provisioner_module.provision(sources.secrets, sources.encrypted_secret, sources.sops_config)

    result = _validate(sources)

    assert result.returncode == 0, result.stderr
    assert _REJECTION_MARKER not in result.stdout + result.stderr


def test_application_ciphertext_has_exact_cnpg_reload_metadata(
    sources: Sources, secret_modules: tuple[ModuleType, ModuleType]
) -> None:
    validator, _ = secret_modules
    path = sources.encrypted_secret.with_name("nohiki-app-secrets.sops.yaml")
    documents = tuple(load_manifests(path.read_text(encoding="utf-8")))
    database_count = 0
    for document in documents:
        name = document["metadata"]["name"]
        metadata = document["metadata"]
        if name.endswith(("-db-credentials", "-debezium-credentials")):
            database_count += 1
            assert metadata == {
                "name": name,
                "namespace": "nohiki",
                "labels": {"cnpg.io/reload": "true"},
            }
        else:
            assert metadata == {"name": name, "namespace": "nohiki"}
    assert database_count == 28
    recipient = validator._validate_age_key(sources.age_key)
    assert len(
        validator._validate_encrypted_app_secrets(
            sources.encrypted_secret.with_name("nohiki-app-secrets.sops.yaml"),
            recipient,
            validator._load_local_contract(),
        )
    ) == len(documents)


@pytest.mark.parametrize("mutation", ["missing", "wrong", "extra"])
def test_validator_rejects_cnpg_reload_metadata_drift(
    sources: Sources,
    secret_modules: tuple[ModuleType, ModuleType],
    mutation: str,
) -> None:
    validator, _ = secret_modules
    path = sources.encrypted_secret.with_name("nohiki-app-secrets.sops.yaml")
    documents = [dict(document) for document in load_manifests(path.read_text(encoding="utf-8"))]
    database = next(
        document for document in documents if string_at(document, "metadata", "name").endswith("-db-credentials")
    )
    metadata = mapping_at(database, "metadata")
    if mutation == "missing":
        metadata.pop("labels")
    elif mutation == "wrong":
        mapping_at(metadata, "labels")["cnpg.io/reload"] = "false"
    else:
        mapping_at(metadata, "labels")["unexpected"] = "value"
    path.write_text(yaml.safe_dump_all(documents), encoding="utf-8")
    recipient = validator._validate_age_key(sources.age_key)

    with pytest.raises(validator.ValidationError):
        validator._validate_encrypted_app_secrets(
            path,
            recipient,
            validator._load_local_contract(),
        )


@pytest.mark.parametrize("provisioner_name", ["application", "runtime", "tls"])
def test_final_output_parent_swap_cannot_redirect_publication(
    sources: Sources,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    secret_modules: tuple[ModuleType, ModuleType],
    runtime_provisioner_module: ModuleType,
    tls_provisioner_module: ModuleType,
    provisioner_name: str,
) -> None:
    _, application = secret_modules
    module = {
        "application": application,
        "runtime": runtime_provisioner_module,
        "tls": tls_provisioner_module,
    }[provisioner_name]
    filename = {
        "application": "nohiki-app-secrets.sops.yaml",
        "runtime": "nohiki-llm-runtime.sops.yaml",
        "tls": "nohiki-model-egress-tls-source.sops.yaml",
    }[provisioner_name]
    parent = tmp_path / f"{provisioner_name}-publication"
    parent.mkdir()
    opened_parent = tmp_path / f"{provisioner_name}-opened-parent"
    original_replace = module.os.replace
    swapped = False

    def swap_parent_then_replace(
        source: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        destination: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        **kwargs: object,
    ) -> None:
        nonlocal swapped
        if not swapped:
            parent.rename(opened_parent)
            parent.mkdir()
            swapped = True
        original_replace(source, destination, **kwargs)

    monkeypatch.setattr(module.os, "replace", swap_parent_then_replace)
    output = parent / filename
    if provisioner_name in {"application", "runtime"}:
        module.provision(sources.secrets, output, sources.sops_config)
    else:
        module.provision(output)

    assert swapped
    assert not (parent / filename).exists()
    assert (opened_parent / filename).is_file()
    assert not tuple(parent.glob(f".{filename}.*"))
    assert not tuple(opened_parent.glob(f".{filename}.*"))
