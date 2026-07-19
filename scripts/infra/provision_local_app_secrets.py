#!/usr/bin/env python3
"""Render local Secret inputs, encrypt them with SOPS, and atomically publish ciphertext."""

import argparse
import os
import secrets
import stat
import subprocess
import sys
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import cast
from urllib.parse import quote

import yaml
from validate_local_secret_sources import (
    _AGE_RECIPIENT,
    _APP_REQUIRED_SOURCES,
    LocalContractSnapshot,
    ValidationError,
    _expected_application_inventory,
    _load_local_contract,
    _load_mapping,
    _open_directory,
    _validate_encrypted_app_secrets,
    _validate_sources,
)

_ROOT = Path(__file__).resolve().parents[2]
_CHART = _ROOT / "infra/k8s/helm"
_DEFAULT_OUTPUT = _ROOT / "infra/k8s/gitops/secrets/local/nohiki-app-secrets.sops.yaml"
_DEFAULT_SOPS_CONFIG = _ROOT / ".sops.yaml"
_LOGICAL_PATH = "infra/k8s/gitops/secrets/local/nohiki-app-secrets.sops.yaml"
_SHARED_NAMES = {
    "nohiki-redis-credentials",
    "nohiki-jwt-keys",
    "nohiki-email-api-keys",
    "nohiki-jsearch-api-keys",
    "nohiki-s3-credentials",
    "observability-storage-credentials",
    "auth-listings-secret",
}
_DATABASE_KEYS = {
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
_SHARED_KEYS = {
    "nohiki-redis-credentials": {"password", "dsn"},
    "nohiki-jwt-keys": {"private_key"},
    "nohiki-oauth-credentials": {
        "github_client_id",
        "github_client_secret",
        "google_client_id",
        "google_client_secret",
    },
    "nohiki-email-api-keys": {"resend_api_key"},
    "nohiki-jsearch-api-keys": {"api_key"},
    "observability-storage-credentials": {
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_REGION",
    },
    "nohiki-s3-credentials": {"access_key", "secret_key"},
    "auth-listings-secret": {"secret"},
    "nohiki-rustfs-credentials": {
        "root-user",
        "root-password",
        "access-key",
        "secret-key",
    },
}


class ProvisionError(RuntimeError):
    """A safe application Secret provisioning failure."""


def _source(sources: dict[str, bytes], relative: str, *, optional: bool = False) -> str:
    raw = sources.get(relative)
    if raw is None:
        if optional:
            return ""
        message = f"validated source {relative} is missing"
        raise ProvisionError(message)
    try:
        return raw.decode("utf-8").removesuffix("\n")
    except UnicodeDecodeError as error:
        message = f"validated source {relative} is not UTF-8"
        raise ProvisionError(message) from error


def _run(command: list[str], *, cwd: Path = _ROOT, pass_fds: tuple[int, ...] = ()) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            pass_fds=pass_fds,
        )
    except FileNotFoundError as error:
        message = f"required command {command[0]!r} is unavailable"
        raise ProvisionError(message) from error
    if result.returncode != 0:
        message = f"{command[0]} failed while provisioning application Secrets"
        raise ProvisionError(message)
    return result


def _values(sources: dict[str, bytes], *, oauth_enabled: bool) -> dict[str, object]:
    oauth = {
        "githubClientId": _source(sources, "oauth/github_client_id", optional=True),
        "githubClientSecret": _source(sources, "oauth/github_client_secret", optional=True),
        "googleClientId": _source(sources, "oauth/google_client_id", optional=True),
        "googleClientSecret": _source(sources, "oauth/google_client_secret", optional=True),
    }
    if not oauth_enabled:
        oauth = dict.fromkeys(oauth, "")
    else:
        github = bool(oauth["githubClientId"]) and bool(oauth["githubClientSecret"])
        google = bool(oauth["googleClientId"]) and bool(oauth["googleClientSecret"])
        partial = bool(oauth["githubClientId"]) != bool(oauth["githubClientSecret"]) or bool(
            oauth["googleClientId"]
        ) != bool(oauth["googleClientSecret"])
        if partial or not (github or google):
            message = "OAuth is enabled without a complete provider credential pair"
            raise ProvisionError(message)
    return {
        "secretValues": {
            "database": {
                "host": _source(sources, "database/host"),
                "port": _source(sources, "database/port"),
                "user": _source(sources, "database/user"),
                "password": _source(sources, "database/password"),
                "name": _source(sources, "database/database"),
            },
            "redis": {"password": _source(sources, "redis/password", optional=True)},
            "jwt": {"privateKey": _source(sources, "jwt/private_key")},
            "oauth": oauth,
            "email": {"resendApiKey": _source(sources, "email/api_key")},
            "jsearch": {"apiKey": _source(sources, "jsearch/api_key")},
            "s3": {
                "accessKey": _source(sources, "s3/access_key"),
                "secretKey": _source(sources, "s3/secret_key"),
            },
            "authListings": {"secret": secrets.token_urlsafe(48)},
        }
    }


def _render(values_path: Path, contract: LocalContractSnapshot) -> list[dict[str, object]]:
    base_snapshot = values_path.with_name("base-values.yaml")
    local_snapshot = values_path.with_name("local-values.yaml")
    base_snapshot.write_text(yaml.safe_dump(contract.base_values, sort_keys=False), encoding="utf-8")
    local_snapshot.write_text(yaml.safe_dump(contract.local_values, sort_keys=False), encoding="utf-8")
    base_snapshot.chmod(0o600)
    local_snapshot.chmod(0o600)
    result = _run(
        [
            "helm",
            "template",
            "nohiki",
            str(_CHART),
            "--namespace",
            "nohiki",
            "--values",
            str(base_snapshot),
            "--values",
            str(local_snapshot),
            "--values",
            str(values_path),
            "--set",
            "global.secrets.inlineSecretsEnabled=true",
            "--show-only",
            "templates/secrets.yaml",
        ]
    )
    documents = [
        cast(dict[str, object], document)
        for document in yaml.safe_load_all(result.stdout)
        if isinstance(document, dict) and document.get("kind") == "Secret"
    ]
    selected: list[dict[str, object]] = []
    for document in documents:
        metadata = document.get("metadata")
        name = metadata.get("name") if isinstance(metadata, dict) else None
        if not isinstance(name, str):
            continue
        is_database = name.endswith(("-db-credentials", "-debezium-credentials"))
        if name not in _SHARED_NAMES and name != "nohiki-oauth-credentials" and not is_database:
            continue
        data = document.get("stringData")
        if not isinstance(data, dict):
            message = f"rendered Secret {name} has no stringData"
            raise ProvisionError(message)
        document.pop("metadata")
        document["metadata"] = (
            {
                "name": name,
                "namespace": "nohiki",
                "labels": {"cnpg.io/reload": "true"},
            }
            if is_database
            else {"name": name, "namespace": "nohiki"}
        )
        if is_database:
            username = data.get("user")
            host = data.get("host")
            port = data.get("port")
            database = data.get("database")
            if not all(isinstance(value, str) and value for value in (username, host, port, database)):
                message = f"rendered database Secret {name} is incomplete"
                raise ProvisionError(message)
            password = secrets.token_urlsafe(36)
            authority = f"{quote(username, safe='')}:{quote(password, safe='')}@{host}:{port}/{database}"
            data.update(
                {
                    "username": username,
                    "password": password,
                    "dbname": database,
                    "dsn": f"postgresql://{authority}?sslmode=disable",
                    "uri": f"postgresql://{authority}",
                }
            )
        if name == "nohiki-oauth-credentials" and not any(data.values()):
            continue
        selected.append(document)

    redis = next(
        document
        for document in selected
        if document["metadata"] == {"name": "nohiki-redis-credentials", "namespace": "nohiki"}
    )
    redis_data = redis.get("stringData")
    if not isinstance(redis_data, dict):
        message = "rendered Redis Secret is malformed"
        raise ProvisionError(message)
    # Valkey is auth-disabled locally; retain the exact consumer key without putting
    # a credential into the in-cluster DSN. A non-empty unused value remains SOPS-encrypted.
    if not redis_data.get("password"):
        redis_data["password"] = secrets.token_urlsafe(32)
    s3 = next(
        document
        for document in selected
        if document["metadata"] == {"name": "nohiki-s3-credentials", "namespace": "nohiki"}
    )
    s3_data = s3.get("stringData")
    if not isinstance(s3_data, dict):
        message = "rendered S3 Secret is malformed"
        raise ProvisionError(message)
    selected.append(
        {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": "nohiki-rustfs-credentials", "namespace": "nohiki"},
            "type": "Opaque",
            "stringData": {
                "root-user": s3_data["access_key"],
                "root-password": s3_data["secret_key"],
                "access-key": s3_data["access_key"],
                "secret-key": s3_data["secret_key"],
            },
        }
    )
    return selected


def _expected_names(contract: LocalContractSnapshot) -> set[str]:
    return set(_expected_application_inventory(contract))


def _verify_plain_inventory(documents: list[dict[str, object]], contract: LocalContractSnapshot) -> None:
    inventory: dict[str, set[str]] = {}
    for document in documents:
        metadata = document.get("metadata")
        data = document.get("stringData")
        if not isinstance(metadata, dict) or not isinstance(data, dict):
            message = "rendered Secret inventory is malformed"
            raise ProvisionError(message)
        name = metadata.get("name")
        if not isinstance(name, str):
            message = "rendered Secret name is malformed"
            raise ProvisionError(message)
        is_database = name.endswith(("-db-credentials", "-debezium-credentials"))
        expected_metadata = (
            {"name": name, "namespace": "nohiki", "labels": {"cnpg.io/reload": "true"}}
            if is_database
            else {"name": name, "namespace": "nohiki"}
        )
        if metadata != expected_metadata:
            message = f"rendered Secret {name} has invalid metadata"
            raise ProvisionError(message)
        inventory[name] = set(data)
    if set(inventory) != _expected_names(contract):
        message = "rendered Secret name inventory is incomplete"
        raise ProvisionError(message)
    for name, keys in inventory.items():
        expected = _DATABASE_KEYS if name.endswith(("-db-credentials", "-debezium-credentials")) else _SHARED_KEYS[name]
        if keys != expected:
            message = f"rendered Secret {name} has an invalid key inventory"
            raise ProvisionError(message)


def _validate_policy(sops_config: Path) -> str:
    try:
        config = _load_mapping(sops_config, "SOPS policy")
    except ValidationError as error:
        message = "SOPS policy is invalid"
        raise ProvisionError(message) from error
    rules = config.get("creation_rules")
    if not isinstance(rules, list) or len(rules) != 1 or not isinstance(rules[0], dict):
        message = "SOPS policy must contain exactly one creation rule"
        raise ProvisionError(message)
    rule = rules[0]
    recipient = rule.get("age")
    if (
        set(rule) != {"path_regex", "encrypted_regex", "age"}
        or rule.get("path_regex") != r"infra/k8s/gitops/secrets/local/.*\.sops\.yaml$"
        or rule.get("encrypted_regex") != "^(data|stringData)$"
        or not isinstance(recipient, str)
        or _AGE_RECIPIENT.fullmatch(recipient) is None
    ):
        message = "SOPS policy does not contain the required local Age recipient"
        raise ProvisionError(message)
    return recipient


def provision(secrets_dir: Path, output: Path, sops_config: Path) -> None:
    """Validate sources, render exact consumers, SOPS-encrypt, and atomically publish."""
    try:
        contract = _load_local_contract()
    except ValidationError as error:
        raise ProvisionError(str(error)) from error
    recipient = _validate_policy(sops_config)
    try:
        validated_sources = _validate_sources(
            secrets_dir,
            required_sources=_APP_REQUIRED_SOURCES,
            contract=contract,
        )
    except ValidationError as error:
        raise ProvisionError(str(error)) from error
    if ".." in output.parts or output.name != _DEFAULT_OUTPUT.name:
        validated_sources.close()
        message = "output must name the intended local application Secret manifest"
        raise ProvisionError(message)
    try:
        parent_descriptor = _open_directory(output.parent, "output parent")
    except ValidationError as error:
        validated_sources.close()
        raise ProvisionError(str(error)) from error
    try:
        try:
            existing = os.stat(output.name, dir_fd=parent_descriptor, follow_symlinks=False)
        except FileNotFoundError:
            existing = None
        if existing is not None and not stat.S_ISREG(existing.st_mode):
            message = "output must not be a symlink or non-regular file"
            raise ProvisionError(message)
        old_umask = os.umask(0o077)
        encrypted_temporary: str | None = None
        try:
            with tempfile.TemporaryDirectory(prefix="nohiki-local-app-secrets-") as name:
                directory = Path(name)
                directory.chmod(0o700)
                values_path = directory / "values.yaml"
                values_path.write_text(
                    yaml.safe_dump(
                        _values(validated_sources, oauth_enabled=contract.oauth_enabled),
                        sort_keys=False,
                    ),
                    encoding="utf-8",
                )
                values_path.chmod(0o600)
                documents = _render(values_path, contract)
                _verify_plain_inventory(documents, contract)
                try:
                    validated_sources.revalidate()
                except ValidationError as error:
                    message = "Secret sources changed before ciphertext generation"
                    raise ProvisionError(message) from error
                plaintext = directory / "secrets.yaml"
                plaintext.write_text(yaml.safe_dump_all(documents, sort_keys=False), encoding="utf-8")
                plaintext.chmod(0o600)
                encrypted_temporary = f".{output.name}.{secrets.token_hex(16)}"
                descriptor = os.open(
                    encrypted_temporary,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                    0o600,
                    dir_fd=parent_descriptor,
                )
                os.close(descriptor)
                inheritable = True
                os.set_inheritable(parent_descriptor, inheritable)
                encrypted_path = Path(f"/proc/self/fd/{parent_descriptor}/{encrypted_temporary}")
                _run(
                    [
                        "sops",
                        "--config",
                        str(sops_config),
                        "--age",
                        recipient,
                        "encrypt",
                        "--filename-override",
                        _LOGICAL_PATH,
                        "--output",
                        str(encrypted_path),
                        str(plaintext),
                    ],
                    pass_fds=(parent_descriptor,),
                )
                encrypted_descriptor = os.open(
                    encrypted_temporary,
                    os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                    dir_fd=parent_descriptor,
                )
                try:
                    with os.fdopen(encrypted_descriptor, "rb", closefd=False) as manifest:
                        encrypted_bytes = manifest.read()
                    os.fsync(encrypted_descriptor)
                finally:
                    os.close(encrypted_descriptor)
                validation_copy = directory / "encrypted.yaml"
                validation_copy.write_bytes(encrypted_bytes)
                validation_copy.chmod(0o600)
                try:
                    _validate_encrypted_app_secrets(validation_copy, recipient, contract)
                except ValidationError as error:
                    message = "SOPS output failed encrypted inventory validation"
                    raise ProvisionError(message) from error
                try:
                    validated_sources.revalidate()
                except ValidationError as error:
                    message = "Secret sources changed before ciphertext publication"
                    raise ProvisionError(message) from error
                try:
                    current_output = os.stat(output.name, dir_fd=parent_descriptor, follow_symlinks=False)
                except FileNotFoundError:
                    current_output = None
                if current_output is not None and not stat.S_ISREG(current_output.st_mode):
                    message = "output changed to a symlink or non-regular file"
                    raise ProvisionError(message)
                os.replace(
                    encrypted_temporary,
                    output.name,
                    src_dir_fd=parent_descriptor,
                    dst_dir_fd=parent_descriptor,
                )
                encrypted_temporary = None
                os.fsync(parent_descriptor)
        finally:
            os.umask(old_umask)
            if encrypted_temporary is not None:
                with suppress(FileNotFoundError):
                    os.unlink(encrypted_temporary, dir_fd=parent_descriptor)
    finally:
        os.close(parent_descriptor)
        validated_sources.close()


def main() -> int:
    """Provision encrypted application Secrets from validated local sources."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--secrets-dir",
        "--source-dir",
        dest="secrets_dir",
        type=Path,
        required=True,
    )
    parser.add_argument("--output", type=Path, default=_DEFAULT_OUTPUT)
    parser.add_argument("--sops-config", type=Path, default=_DEFAULT_SOPS_CONFIG)
    args = parser.parse_args()
    try:
        provision(args.secrets_dir, args.output, args.sops_config)
    except ProvisionError as error:
        sys.stderr.write(f"Application Secret provisioning failed: {error}\n")
        return 1
    sys.stdout.write("Encrypted application Secret inventory provisioned; no plaintext material remains\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
