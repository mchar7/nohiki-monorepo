#!/usr/bin/env python3
"""Validate local Secret sources and Flux SOPS ownership without mutation."""

import argparse
import base64
import binascii
import os
import re
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import yaml
from local_secret_contract import (
    LocalSecretContractError,
    enabled_provider_credentials,
    local_oauth_enabled,
)

_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_SOPS = _ROOT / ".sops.yaml"
_DEFAULT_ENCRYPTED_SECRET = _ROOT / "infra/k8s/gitops/secrets/local/nohiki-llm-runtime.sops.yaml"
_DEFAULT_ENCRYPTED_APP_SECRETS = _ROOT / "infra/k8s/gitops/secrets/local/nohiki-app-secrets.sops.yaml"
_DEFAULT_RUNTIME_KUSTOMIZATION = _ROOT / "infra/k8s/gitops/clusters/local/runtime-secrets.yaml"

_APP_REQUIRED_SOURCES = (
    "database/host",
    "database/port",
    "database/user",
    "database/password",
    "database/database",
    "jwt/private_key",
    "email/api_key",
    "jsearch/api_key",
    "s3/access_key",
    "s3/secret_key",
)
_OPTIONAL_SOURCES = (
    "redis/password",
    "oauth/github_client_id",
    "oauth/github_client_secret",
    "oauth/google_client_id",
    "oauth/google_client_secret",
)
_PROVIDER_SOURCES = {
    "anthropic": "llm/provider/api_keys/anthropic",
    "openai": "llm/provider/api_keys/openai",
    "openrouter": "llm/provider/api_keys/openrouter",
}
_DATABASE_SERVICES = (
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
_APPLICATION_KEYS = {
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
_OAUTH_KEYS = {
    "github_client_id",
    "github_client_secret",
    "google_client_id",
    "google_client_secret",
}
_PLACEHOLDER = re.compile(
    r"(?:placeholder|change[-_ ]?me|replace[-_ ]?me|example|dummy|synthetic|test[-_ ]?secret)",
    re.IGNORECASE,
)
_SOPS_VALUE = re.compile(r"ENC\[AES256_GCM,data:[^,]+,iv:[^,]+,tag:[^,]+,type:(?:str|bytes)\]\Z")
_AGE_IDENTITY = re.compile(r"AGE-" + r"SECRET-KEY-1[023456789ACDEFGHJKLMNPQRSTUVWXYZ]{58}\Z")
_AGE_RECIPIENT = re.compile(r"age1[023456789acdefghjklmnpqrstuvwxyz]{58}\Z")
_AGE_ENVELOPE = re.compile(
    r"\A-----BEGIN AGE ENCRYPTED FILE-----\n"
    r"(?:[A-Za-z0-9+/=]{1,76}\n)+"
    r"-----END AGE ENCRYPTED FILE-----\n\Z"
)
_SOPS_VERSION = re.compile(r"[1-9][0-9]*\.[0-9]+\.[0-9]+\Z")
_MAX_FILE_BYTES = 1024 * 1024


class ValidationError(ValueError):
    """A safe validation failure that never contains Secret contents."""


@dataclass(frozen=True)
class LocalContractSnapshot:
    """Descriptor-bound Helm inputs and their derived local consumer contract."""

    base_values: dict[str, object]
    local_values: dict[str, object]
    provider_credentials: tuple[str, ...]
    oauth_enabled: bool


def _fail(label: str, reason: str) -> None:
    message = f"{label}: {reason}"
    raise ValidationError(message)


def _load_local_contract() -> LocalContractSnapshot:
    base = _load_mapping(_ROOT / "infra/k8s/helm/values.yaml", "base Helm values")
    local = _load_mapping(_ROOT / "infra/k8s/helm/values.local.yaml", "local Helm values")
    try:
        providers = enabled_provider_credentials(base, local)
        oauth_enabled = local_oauth_enabled(local)
    except LocalSecretContractError as error:
        _fail("local Helm values", str(error))
    return LocalContractSnapshot(base, local, providers, oauth_enabled)


def _runtime_required_sources(contract: LocalContractSnapshot) -> tuple[str, ...]:
    return tuple(_PROVIDER_SOURCES[name] for name in contract.provider_credentials)


def _runtime_keys(contract: LocalContractSnapshot) -> set[str]:
    return {f"{name}_api_key" for name in contract.provider_credentials}


def _open_directory(path: Path, label: str) -> int:
    absolute = path.absolute()
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for component in absolute.parts[1:]:
            next_descriptor = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=descriptor,
            )
            os.close(descriptor)
            descriptor = next_descriptor
    except FileNotFoundError, NotADirectoryError:
        os.close(descriptor)
        _fail(label, "missing or has a non-directory path component")
    except OSError as error:
        os.close(descriptor)
        message = f"{label}: cannot be opened without following symlinks"
        raise ValidationError(message) from error
    return descriptor


def _read_regular_file(path: Path, label: str) -> tuple[bytes, os.stat_result]:
    parent_descriptor = _open_directory(path.parent, label)
    try:
        try:
            directory_entry = os.stat(path.name, dir_fd=parent_descriptor, follow_symlinks=False)
            descriptor = os.open(
                path.name,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=parent_descriptor,
            )
        except FileNotFoundError:
            _fail(label, "missing")
        except OSError as error:
            message = f"{label}: cannot be opened without following symlinks"
            raise ValidationError(message) from error
        try:
            before = os.fstat(descriptor)
            if (directory_entry.st_dev, directory_entry.st_ino) != (
                before.st_dev,
                before.st_ino,
            ):
                _fail(label, "changed while being opened")
            if not stat.S_ISREG(before.st_mode):
                _fail(label, "must be a regular file")
            chunks: list[bytes] = []
            remaining = _MAX_FILE_BYTES + 1
            while remaining:
                chunk = os.read(descriptor, min(65536, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            raw = b"".join(chunks)
            if len(raw) > _MAX_FILE_BYTES:
                _fail(label, "exceeds the maximum supported size")
            after = os.fstat(descriptor)
            before_identity = (
                before.st_dev,
                before.st_ino,
                before.st_uid,
                stat.S_IMODE(before.st_mode),
                before.st_size,
                before.st_ctime_ns,
                before.st_mtime_ns,
            )
            after_identity = (
                after.st_dev,
                after.st_ino,
                after.st_uid,
                stat.S_IMODE(after.st_mode),
                after.st_size,
                after.st_ctime_ns,
                after.st_mtime_ns,
            )
            if before_identity != after_identity or len(raw) != after.st_size:
                _fail(label, "changed while being read")
            return raw, after
        finally:
            os.close(descriptor)
    finally:
        os.close(parent_descriptor)


def _metadata_identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_uid,
        stat.S_IMODE(metadata.st_mode),
        metadata.st_size,
        metadata.st_ctime_ns,
        metadata.st_mtime_ns,
    )


def _directory_entries(descriptor: int) -> frozenset[str]:
    """Return names from an already validated directory descriptor."""
    with os.scandir(descriptor) as entries:
        return frozenset(entry.name for entry in entries)


class ValidatedSources(dict[str, bytes]):
    """Validated bytes bound to retained source directory descriptors."""

    def __init__(
        self,
        root_descriptor: int,
        root_parent_descriptor: int,
        root_name: str,
        root_identity: tuple[int, ...],
    ) -> None:
        """Retain source descriptors and their validation snapshots."""
        super().__init__()
        self.root_descriptor = root_descriptor
        self.root_parent_descriptor = root_parent_descriptor
        self.root_name = root_name
        self.root_identity = root_identity
        self.directories: dict[str, tuple[int, tuple[int, ...], frozenset[str]]] = {}
        self.files: list[tuple[int, str, tuple[int, ...], str]] = []
        self.closed = False

    def add_directory(self, relative: str, descriptor: int, label: str) -> None:
        """Retain a validated directory descriptor and inventory snapshot."""
        metadata = os.fstat(descriptor)
        if metadata.st_uid != os.geteuid():
            _fail(label, "must be owned by the current user")
        if stat.S_IMODE(metadata.st_mode) & 0o077:
            _fail(label, "must not grant group or other permissions")
        self.directories[relative] = (
            descriptor,
            _metadata_identity(metadata),
            _directory_entries(descriptor),
        )

    def add_file(self, parent_descriptor: int, name: str, metadata: os.stat_result, label: str) -> None:
        """Retain a validated source-file identity."""
        self.files.append((parent_descriptor, name, _metadata_identity(metadata), label))

    def revalidate(self) -> None:
        """Revalidate every retained directory and source-file identity."""
        try:
            current_root = os.stat(
                self.root_name,
                dir_fd=self.root_parent_descriptor,
                follow_symlinks=False,
            )
        except OSError as error:
            message = "secrets directory: changed after validation"
            raise ValidationError(message) from error
        if _metadata_identity(current_root) != self.root_identity:
            _fail("secrets directory", "changed after validation")
        for descriptor, identity, entries in self.directories.values():
            if _metadata_identity(os.fstat(descriptor)) != identity or _directory_entries(descriptor) != entries:
                _fail("secrets directory", "changed after source validation")
        for parent_descriptor, name, identity, label in self.files:
            try:
                metadata = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
            except OSError as error:
                message = f"{label}: changed after validation"
                raise ValidationError(message) from error
            if _metadata_identity(metadata) != identity or not stat.S_ISREG(metadata.st_mode):
                _fail(label, "changed after validation")

    def close(self) -> None:
        """Close all retained descriptors exactly once."""
        if self.closed:
            return
        self.closed = True
        descriptors = {descriptor for descriptor, _, _ in self.directories.values()}
        for descriptor in reversed(tuple(descriptors)):
            os.close(descriptor)
        if self.root_descriptor not in descriptors:
            os.close(self.root_descriptor)
        os.close(self.root_parent_descriptor)
        self.directories.clear()


def _open_source_parent(sources: ValidatedSources, relative: str, *, optional: bool) -> tuple[int, str] | None:
    components = Path(relative).parts
    descriptor = sources.root_descriptor
    key_parts: list[str] = []
    for component in components[:-1]:
        key_parts.append(component)
        key = "/".join(key_parts)
        cached = sources.directories.get(key)
        if cached is not None:
            descriptor = cached[0]
            continue
        try:
            child = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=descriptor,
            )
        except FileNotFoundError:
            if optional:
                return None
            _fail(relative, "missing")
        except OSError as error:
            message = f"{relative}: cannot be opened without following symlinks"
            raise ValidationError(message) from error
        try:
            sources.add_directory(key, child, key)
        except BaseException:
            os.close(child)
            raise
        descriptor = child
    return descriptor, components[-1]


def _read_source_file(parent_descriptor: int, name: str, label: str) -> tuple[bytes, os.stat_result]:
    try:
        directory_entry = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
        descriptor = os.open(
            name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=parent_descriptor,
        )
    except FileNotFoundError:
        _fail(label, "missing")
    except OSError as error:
        message = f"{label}: cannot be opened without following symlinks"
        raise ValidationError(message) from error
    try:
        before = os.fstat(descriptor)
        if (directory_entry.st_dev, directory_entry.st_ino) != (
            before.st_dev,
            before.st_ino,
        ) or not stat.S_ISREG(before.st_mode):
            _fail(label, "changed while being opened or is not a regular file")
        chunks: list[bytes] = []
        remaining = _MAX_FILE_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if len(raw) > _MAX_FILE_BYTES:
            _fail(label, "exceeds the maximum supported size")
        after = os.fstat(descriptor)
        if _metadata_identity(before) != _metadata_identity(after) or len(raw) != after.st_size:
            _fail(label, "changed while being read")
        return raw, after
    finally:
        os.close(descriptor)


def _validate_private_source_file(
    parent_descriptor: int, name: str, label: str, *, allow_empty: bool
) -> tuple[bytes, os.stat_result]:
    raw, metadata = _read_source_file(parent_descriptor, name, label)
    if metadata.st_uid != os.geteuid():
        _fail(label, "must be owned by the current user")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        _fail(label, "must not grant group or other permissions")
    if not raw and not allow_empty:
        _fail(label, "must not be empty")
    return raw, metadata


def _validate_private_file(path: Path, label: str, *, allow_empty: bool = False) -> bytes:
    raw, metadata = _read_regular_file(path, label)
    if metadata.st_uid != os.geteuid():
        _fail(label, "must be owned by the current user")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        _fail(label, "must not grant group or other permissions")
    if not raw and not allow_empty:
        _fail(label, "must not be empty")
    return raw


def _validate_secret_directory(path: Path, label: str) -> None:
    descriptor = _open_directory(path, label)
    try:
        metadata = os.fstat(descriptor)
        if metadata.st_uid != os.geteuid():
            _fail(label, "must be owned by the current user")
        if stat.S_IMODE(metadata.st_mode) & 0o077:
            _fail(label, "must not grant group or other permissions")
    finally:
        os.close(descriptor)


def _validate_scalar(raw: bytes, label: str, *, allow_empty: bool = False) -> str:
    if b"\x00" in raw or b"\r" in raw or b"\n" in raw.removesuffix(b"\n"):
        _fail(label, "must be a single-line value")
    raw = raw.removesuffix(b"\n")
    try:
        value = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        message = f"{label}: must be UTF-8 text"
        raise ValidationError(message) from error
    if value != value.strip():
        _fail(label, "must not have surrounding whitespace")
    if not value and not allow_empty:
        _fail(label, "must not be empty")
    if value and _PLACEHOLDER.search(value):
        _fail(label, "contains a placeholder value")
    return value


def _validate_jwt(raw: bytes) -> None:
    label = "jwt/private_key"
    normalized = raw.replace(b"\r\n", b"\n")
    header = re.match(rb"-----BEGIN (?P<kind>(?:RSA |EC |OPENSSH )?)PRIVATE KEY-----\n", normalized)
    if header is None:
        _fail(label, "must be an unencrypted PEM private key")
    header = cast(re.Match[bytes], header)
    kind = header.group("kind")
    pattern = re.compile(
        rb"-----BEGIN " + re.escape(kind) + rb"PRIVATE KEY-----\n"
        rb"(?P<body>[A-Za-z0-9+/=\n]+)"
        rb"-----END " + re.escape(kind) + rb"PRIVATE KEY-----\n?\Z"
    )
    match = pattern.fullmatch(normalized)
    if match is None:
        _fail(label, "must be a complete PEM private key")
    match = cast(re.Match[bytes], match)
    try:
        decoded = base64.b64decode(b"".join(match.group("body").splitlines()), validate=True)
    except binascii.Error as error:
        message = f"{label}: contains malformed PEM encoding"
        raise ValidationError(message) from error
    if kind != b"OPENSSH " and (len(decoded) < 64 or not decoded.startswith(b"0")):
        _fail(label, "contains malformed private-key data")
    if kind == b"OPENSSH " and not decoded.startswith(b"openssh-key-v1\x00"):
        _fail(label, "contains malformed OpenSSH private-key data")


def _validate_provider(value: str, provider: str) -> None:
    label = f"llm/provider/api_keys/{provider}"
    if len(value) < 16 or any(character.isspace() for character in value):
        _fail(label, f"must be a structurally valid {provider} credential")


def _load_mapping(path: Path, label: str) -> dict[str, object]:
    try:
        raw, _ = _read_regular_file(path, label)
        loaded = yaml.safe_load(raw.decode("utf-8"))
    except (UnicodeError, yaml.YAMLError) as error:
        message = f"{label}: cannot be parsed as YAML"
        raise ValidationError(message) from error
    if not isinstance(loaded, dict) or not all(isinstance(key, str) for key in loaded):
        _fail(label, "must contain one YAML mapping")
    return cast(dict[str, object], loaded)


def _load_documents(path: Path, label: str) -> tuple[dict[str, object], ...]:
    try:
        raw, _ = _read_regular_file(path, label)
        loaded = tuple(yaml.safe_load_all(raw.decode("utf-8")))
    except (UnicodeError, yaml.YAMLError) as error:
        message = f"{label}: cannot be parsed as YAML"
        raise ValidationError(message) from error
    if not loaded or not all(
        isinstance(document, dict) and all(isinstance(key, str) for key in document) for document in loaded
    ):
        _fail(label, "must contain only YAML mappings")
    return cast(tuple[dict[str, object], ...], loaded)


def _validate_age_key(path: Path) -> str:
    raw = _validate_private_file(path, "SOPS_AGE_KEY_FILE")
    try:
        lines = raw.decode("ascii").splitlines()
    except UnicodeDecodeError as error:
        message = "SOPS_AGE_KEY_FILE: must be ASCII text"
        raise ValidationError(message) from error
    identities = [line for line in lines if line and not line.startswith("#")]
    if len(identities) != 1 or _AGE_IDENTITY.fullmatch(identities[0]) is None:
        _fail("SOPS_AGE_KEY_FILE", "must contain exactly one valid Age identity")
    try:
        with tempfile.TemporaryDirectory(prefix="nohiki-age-validate-") as name:
            directory = Path(name)
            directory.chmod(0o700)
            bound_identity = directory / "age.agekey"
            bound_identity.write_bytes(raw)
            bound_identity.chmod(0o600)
            result = subprocess.run(
                ["age-keygen", "-y", str(bound_identity)],
                capture_output=True,
                text=True,
                check=False,
            )
    except FileNotFoundError as error:
        message = "SOPS_AGE_KEY_FILE: age-keygen is required for recipient validation"
        raise ValidationError(message) from error
    recipient = result.stdout.strip()
    if result.returncode != 0 or _AGE_RECIPIENT.fullmatch(recipient) is None:
        _fail("SOPS_AGE_KEY_FILE", "cannot derive a valid Age recipient")
    return recipient


def _validate_sources(
    secrets_dir: Path,
    *,
    required_sources: tuple[str, ...] | None = None,
    optional_sources: tuple[str, ...] = _OPTIONAL_SOURCES,
    contract: LocalContractSnapshot | None = None,
) -> ValidatedSources:
    if contract is None:
        contract = _load_local_contract()
    if required_sources is None:
        required_sources = _APP_REQUIRED_SOURCES + _runtime_required_sources(contract)
    if not secrets_dir.is_absolute():
        _fail("secrets directory", "must be an absolute external path")
    root_parent_descriptor = _open_directory(secrets_dir.parent, "secrets directory parent")
    root_descriptor: int | None = None
    try:
        root_entry = os.stat(
            secrets_dir.name,
            dir_fd=root_parent_descriptor,
            follow_symlinks=False,
        )
        root_descriptor = os.open(
            secrets_dir.name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=root_parent_descriptor,
        )
        root_metadata = os.fstat(root_descriptor)
        if (root_entry.st_dev, root_entry.st_ino) != (
            root_metadata.st_dev,
            root_metadata.st_ino,
        ):
            _fail("secrets directory", "changed while being opened")
    except BaseException:
        if root_descriptor is not None:
            os.close(root_descriptor)
        os.close(root_parent_descriptor)
        raise
    validated = ValidatedSources(
        root_descriptor,
        root_parent_descriptor,
        secrets_dir.name,
        _metadata_identity(root_metadata),
    )
    try:
        validated.add_directory("", root_descriptor, "secrets directory")
        if any(source.startswith("llm/provider/") for source in required_sources):
            enabled_sources = set(_runtime_required_sources(contract))
            for relative in set(_PROVIDER_SOURCES.values()) - enabled_sources:
                parent = _open_source_parent(validated, relative, optional=True)
                if parent is None:
                    continue
                parent_descriptor, name = parent
                try:
                    os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
                except FileNotFoundError:
                    continue
                _fail(relative, "is not consumed by an enabled local provider")
        for relative in (*required_sources, *optional_sources):
            optional = relative in optional_sources
            parent = _open_source_parent(validated, relative, optional=optional)
            if parent is None:
                continue
            parent_descriptor, name = parent
            if optional:
                try:
                    os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
                except FileNotFoundError:
                    continue
            raw, metadata = _validate_private_source_file(
                parent_descriptor,
                name,
                relative,
                allow_empty=optional,
            )
            validated[relative] = raw
            validated.add_file(parent_descriptor, name, metadata, relative)
            if relative == "jwt/private_key":
                _validate_jwt(raw)
                continue
            value = _validate_scalar(raw, relative, allow_empty=optional)
            if relative == "database/port":
                try:
                    port = int(value)
                except ValueError as error:
                    message = "database/port: must be a decimal TCP port"
                    raise ValidationError(message) from error
                if not 1 <= port <= 65535:
                    _fail("database/port", "must be between 1 and 65535")
            if relative.startswith("llm/provider/api_keys/"):
                _validate_provider(value, Path(relative).name)
        if any(relative.startswith("oauth/") for relative in optional_sources):
            oauth_pairs = (
                ("oauth/github_client_id", "oauth/github_client_secret"),
                ("oauth/google_client_id", "oauth/google_client_secret"),
            )
            complete_pairs = 0
            for client_id, client_secret in oauth_pairs:
                has_id = bool(validated.get(client_id))
                has_secret = bool(validated.get(client_secret))
                if has_id != has_secret:
                    _fail(
                        "OAuth sources",
                        "must contain complete provider credential pairs",
                    )
                complete_pairs += int(has_id and has_secret)
            if contract.oauth_enabled and complete_pairs == 0:
                _fail("OAuth sources", "must contain at least one complete provider pair")
            if not contract.oauth_enabled and complete_pairs:
                _fail("OAuth sources", "are not consumed while local OAuth is disabled")
    except BaseException:
        validated.close()
        raise
    else:
        return validated


def _validate_sops_metadata(sops: object, recipient: str, label: str) -> None:
    if not isinstance(sops, dict) or set(sops) != {
        "age",
        "lastmodified",
        "mac",
        "encrypted_regex",
        "version",
    }:
        _fail(label, "has unexpected or incomplete SOPS metadata")
    sops_mapping = cast(dict[str, object], sops)
    age = sops_mapping.get("age")
    mac = sops_mapping.get("mac")
    lastmodified = sops_mapping.get("lastmodified")
    version = sops_mapping.get("version")
    if sops_mapping.get("encrypted_regex") != "^(data|stringData)$" or not isinstance(age, list) or len(age) != 1:
        _fail(label, "has incomplete or unauthorized SOPS metadata")
    age_entries = cast(list[object], age)
    age_entry = age_entries[0]
    if not isinstance(age_entry, dict) or set(age_entry) != {"recipient", "enc"}:
        _fail(label, "has incomplete or unauthorized SOPS metadata")
    age_mapping = cast(dict[str, object], age_entry)
    envelope = age_mapping.get("enc")
    if (
        age_mapping.get("recipient") != recipient
        or _AGE_RECIPIENT.fullmatch(recipient) is None
        or not isinstance(envelope, str)
        or _AGE_ENVELOPE.fullmatch(envelope) is None
        or not isinstance(mac, str)
        or _SOPS_VALUE.fullmatch(mac) is None
        or not isinstance(lastmodified, str)
        or not isinstance(version, str)
        or _SOPS_VERSION.fullmatch(version) is None
    ):
        _fail(label, "has incomplete or unauthorized SOPS metadata")
    lastmodified = cast(str, lastmodified)
    try:
        modified = datetime.strptime(lastmodified, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError as error:
        message = f"{label}: has malformed SOPS lastmodified metadata"
        raise ValidationError(message) from error
    if modified.strftime("%Y-%m-%dT%H:%M:%SZ") != lastmodified:
        _fail(label, "has noncanonical SOPS lastmodified metadata")


def _validate_sops_and_secret(sops_path: Path, secret_path: Path, contract: LocalContractSnapshot) -> str:
    config = _load_mapping(sops_path, ".sops.yaml")
    rules = config.get("creation_rules")
    if not isinstance(rules, list) or len(rules) != 1:
        _fail(".sops.yaml", "must contain exactly one creation rule")
    creation_rules = cast(list[object], rules)
    rule = creation_rules[0]
    if not isinstance(rule, dict):
        _fail(".sops.yaml", "must contain exactly one creation rule")
    rule_mapping = cast(dict[object, object], rule)
    if set(rule_mapping) != {"path_regex", "encrypted_regex", "age"}:
        _fail(".sops.yaml", "local SOPS rule is incomplete or malformed")
    typed_rule = cast(dict[str, object], rule_mapping)
    recipient = typed_rule.get("age")
    if (
        typed_rule.get("path_regex") != r"infra/k8s/gitops/secrets/local/.*\.sops\.yaml$"
        or typed_rule.get("encrypted_regex") != "^(data|stringData)$"
        or not isinstance(recipient, str)
        or _AGE_RECIPIENT.fullmatch(recipient) is None
    ):
        _fail(".sops.yaml", "local SOPS rule is incomplete or malformed")
    recipient = cast(str, recipient)

    secret = _load_mapping(secret_path, "encrypted provider Secret")
    if set(secret) != {"apiVersion", "kind", "metadata", "type", "data", "sops"}:
        _fail("encrypted provider Secret", "has unexpected or missing top-level fields")
    if secret.get("apiVersion") != "v1" or secret.get("kind") != "Secret":
        _fail("encrypted provider Secret", "must be a core/v1 Secret")
    if secret.get("metadata") != {"name": "nohiki-llm-runtime", "namespace": "nohiki"}:
        _fail("encrypted provider Secret", "has the wrong name or namespace")
    if secret.get("type") != "Opaque":
        _fail("encrypted provider Secret", "must have type Opaque")
    data = secret.get("data")
    if not isinstance(data, dict) or set(data) != _runtime_keys(contract):
        _fail(
            "encrypted provider Secret",
            "does not contain the exact required key inventory",
        )
    data_mapping = cast(dict[str, object], data)
    if not all(isinstance(value, str) and _SOPS_VALUE.fullmatch(value) for value in data_mapping.values()):
        _fail("encrypted provider Secret", "contains plaintext or malformed ciphertext")
    _validate_sops_metadata(secret.get("sops"), recipient, "encrypted provider Secret")
    return recipient


def _expected_application_inventory(
    contract: LocalContractSnapshot,
) -> dict[str, set[str]]:
    base = contract.base_values
    local = contract.local_values
    expected = dict(_APPLICATION_KEYS)
    database_consumers: set[str] = set()
    for name, settings in base.items():
        if not isinstance(name, str) or not isinstance(settings, dict):
            continue
        local_settings = local.get(name, {})
        if not isinstance(local_settings, dict):
            local_settings = {}
        database = settings.get("database")
        enabled = local_settings.get("enabled", settings.get("enabled", False))
        if enabled is True and isinstance(database, dict) and database.get("enabled") is True:
            database_consumers.add(name)
            expected[f"{name}-db-credentials"] = _DATABASE_KEYS
            expected[f"{name}-debezium-credentials"] = _DATABASE_KEYS
    if database_consumers != set(_DATABASE_SERVICES):
        _fail("local Helm values", "do not enable the exact 14 database consumers")

    global_local = local.get("global")
    if not isinstance(global_local, dict):
        _fail("local Helm values", "have no global contract")
    global_values = cast(dict[object, object], global_local)
    if global_values.get("database") != {"host": "nohiki-pg-rw", "port": 5432}:
        _fail("local Helm values", "do not use the CloudNativePG in-cluster endpoint")
    if global_values.get("redis") != {"host": "nohiki-valkey-primary", "port": 6379}:
        _fail("local Helm values", "do not use the in-cluster Valkey endpoint")
    kafka = global_values.get("kafka")
    if (
        not isinstance(kafka, dict)
        or kafka.get("bootstrapServers") != "nohiki-kafka-kafka-bootstrap:9092"
        or kafka.get("security") != {"protocol": "PLAINTEXT"}
    ):
        _fail("local Helm values", "must use Kafka PLAINTEXT without a SASL Secret")
    qdrant = global_values.get("qdrant")
    if not isinstance(qdrant, dict) or any("secret" in str(key).lower() for key in qdrant):
        _fail(
            "local Helm values",
            "must not reference a Qdrant Secret when auth is disabled",
        )
    rustfs = local.get("rustfs")
    rustfs_secret = rustfs.get("secret") if isinstance(rustfs, dict) else None
    if not isinstance(rustfs_secret, dict) or rustfs_secret.get("existingSecret") != "nohiki-rustfs-credentials":
        _fail("local Helm values", "must delegate RustFS Secret ownership to Flux")
    if contract.oauth_enabled:
        expected["nohiki-oauth-credentials"] = _OAUTH_KEYS
    return expected


def _validate_encrypted_app_secrets(secret_path: Path, recipient: str, contract: LocalContractSnapshot) -> set[str]:
    label = "encrypted application Secret inventory"
    documents = _load_documents(secret_path, label)
    expected = _expected_application_inventory(contract)
    inventory: dict[str, set[str]] = {}
    for document in documents:
        if set(document) != {
            "apiVersion",
            "kind",
            "metadata",
            "type",
            "stringData",
            "sops",
        }:
            _fail(label, "has unexpected or missing top-level fields")
        metadata = document.get("metadata")
        name = metadata.get("name") if isinstance(metadata, dict) else None
        is_database = isinstance(name, str) and name.endswith(("-db-credentials", "-debezium-credentials"))
        expected_type = "kubernetes.io/basic-auth" if is_database else "Opaque"
        expected_metadata = (
            {
                "name": name,
                "namespace": "nohiki",
                "labels": {"cnpg.io/reload": "true"},
            }
            if is_database
            else {"name": name, "namespace": "nohiki"}
        )
        if (
            document.get("apiVersion") != "v1"
            or document.get("kind") != "Secret"
            or document.get("type") != expected_type
            or metadata != expected_metadata
            or not isinstance(name, str)
        ):
            _fail(label, "has a malformed Secret identity")
        name = cast(str, name)
        data = document.get("stringData")
        if name in inventory or not isinstance(data, dict):
            _fail(label, "contains duplicate identities or malformed data")
        data_mapping = cast(dict[object, object], data)
        if not all(
            isinstance(key, str)
            and isinstance(value, str)
            and (_SOPS_VALUE.fullmatch(value) is not None or (name == "nohiki-oauth-credentials" and value == ""))
            for key, value in data_mapping.items()
        ):
            _fail(label, "contains plaintext or malformed ciphertext")
        string_data = cast(dict[str, str], data_mapping)
        inventory[name] = set(string_data)
        if name == "nohiki-oauth-credentials":
            encrypted = {
                key: isinstance(string_data.get(key), str) and _SOPS_VALUE.fullmatch(string_data[key]) is not None
                for key in _OAUTH_KEYS
            }
            pairs = (
                ("github_client_id", "github_client_secret"),
                ("google_client_id", "google_client_secret"),
            )
            if any(encrypted[left] != encrypted[right] for left, right in pairs):
                _fail(label, "contains an incomplete OAuth ciphertext pair")
            if not any(encrypted[left] and encrypted[right] for left, right in pairs):
                _fail(label, "contains no complete OAuth ciphertext pair")
        _validate_sops_metadata(document.get("sops"), recipient, label)
    if inventory != expected:
        _fail(label, "does not exactly match the required Secret name/key inventory")
    return set(inventory)


def _validate_encrypted_tls_secret(secret_path: Path, recipient: str) -> None:
    label = "encrypted TLS source Secret"
    secret = _load_mapping(secret_path, label)
    if set(secret) != {"apiVersion", "kind", "metadata", "type", "stringData", "sops"}:
        _fail(label, "has unexpected or missing top-level fields")
    if secret.get("apiVersion") != "v1" or secret.get("kind") != "Secret":
        _fail(label, "must be a core/v1 Secret")
    if (
        secret.get("metadata")
        != {
            "name": "nohiki-model-egress-tls-source",
            "namespace": "nohiki",
        }
        or secret.get("type") != "kubernetes.io/tls"
    ):
        _fail(label, "has the wrong identity or type")
    data = secret.get("stringData")
    if not isinstance(data, dict) or set(data) != {"tls.crt", "tls.key", "ca.crt"}:
        _fail(label, "does not contain the exact required key inventory")
    data_mapping = cast(dict[str, object], data)
    if not all(isinstance(value, str) and _SOPS_VALUE.fullmatch(value) for value in data_mapping.values()):
        _fail(label, "contains plaintext or malformed ciphertext")
    _validate_sops_metadata(secret.get("sops"), recipient, label)


def _validate_local_kustomization(path: Path) -> None:
    manifest = _load_mapping(path, "local Secret Kustomization")
    resources = manifest.get("resources")
    expected = [
        "namespace.yaml",
        "nohiki-llm-runtime.sops.yaml",
        "nohiki-model-egress-tls-source.sops.yaml",
        "nohiki-app-secrets.sops.yaml",
        "model-egress-secrets.yaml",
    ]
    if set(manifest) != {"apiVersion", "kind", "resources"}:
        _fail(
            "local Secret Kustomization",
            "has unauthorized generators, components, patches, or fields",
        )
    if (
        manifest.get("apiVersion") != "kustomize.config.k8s.io/v1beta1"
        or manifest.get("kind") != "Kustomization"
        or resources != expected
    ):
        _fail(
            "local Secret Kustomization",
            "does not have the exact encrypted source inventory",
        )


def _validate_flux(path: Path) -> None:
    manifest = _load_mapping(path, "runtime-secrets Kustomization")
    if set(manifest) != {"apiVersion", "kind", "metadata", "spec"}:
        _fail("runtime-secrets Kustomization", "has unauthorized top-level fields")
    if manifest.get("apiVersion") != "kustomize.toolkit.fluxcd.io/v1" or manifest.get("kind") != "Kustomization":
        _fail("runtime-secrets Kustomization", "has the wrong API identity")
    if manifest.get("metadata") != {
        "name": "runtime-secrets",
        "namespace": "flux-system",
    }:
        _fail("runtime-secrets Kustomization", "has the wrong name or namespace")
    spec = manifest.get("spec")
    if not isinstance(spec, dict):
        _fail("runtime-secrets Kustomization", "has no spec")
    spec_mapping = cast(dict[object, object], spec)
    allowed_spec_fields = {
        "dependsOn",
        "interval",
        "retryInterval",
        "timeout",
        "sourceRef",
        "path",
        "prune",
        "wait",
        "decryption",
        "healthChecks",
    }
    if set(spec_mapping) != allowed_spec_fields:
        _fail("runtime-secrets Kustomization", "has unauthorized spec fields")
    spec_values = cast(dict[str, object], spec_mapping)
    expected = {
        "dependsOn": [{"name": "infrastructure"}],
        "sourceRef": {"kind": "GitRepository", "name": "flux-system"},
        "path": "./infra/k8s/gitops/secrets/local",
        "prune": True,
        "wait": True,
        "decryption": {"provider": "sops", "secretRef": {"name": "flux-sops"}},
    }
    for key, value in expected.items():
        if spec_values.get(key) != value:
            _fail("runtime-secrets Kustomization", f"has invalid {key} ownership")
    health_checks = spec_values.get("healthChecks")
    expected_checks = [
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
    ]
    if health_checks != expected_checks:
        _fail("runtime-secrets Kustomization", "has an incomplete readiness inventory")
    if (
        spec_values.get("interval") != "10m"
        or spec_values.get("timeout") != "2m"
        or spec_values.get("retryInterval") != "1m"
    ):
        _fail(
            "runtime-secrets Kustomization",
            "must keep canonical reconcile, timeout, and retry intervals",
        )
    platform = _load_mapping(path.with_name("platform.yaml"), "local platform Kustomization")
    platform_spec = platform.get("spec")
    dependencies = platform_spec.get("dependsOn") if isinstance(platform_spec, dict) else None
    if not isinstance(dependencies, list) or {"name": "runtime-secrets"} not in dependencies:
        _fail(
            "local platform Kustomization",
            "must depend directly on runtime-secrets",
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--secrets-dir", type=Path, required=True)
    parser.add_argument("--age-key-file", type=Path)
    parser.add_argument("--sops-config", type=Path, default=_DEFAULT_SOPS)
    parser.add_argument("--encrypted-secret", type=Path, default=_DEFAULT_ENCRYPTED_SECRET)
    parser.add_argument(
        "--encrypted-app-secrets",
        type=Path,
        default=_DEFAULT_ENCRYPTED_APP_SECRETS,
    )
    parser.add_argument(
        "--local-secret-kustomization",
        type=Path,
        default=_ROOT / "infra/k8s/gitops/secrets/local/kustomization.yaml",
    )
    parser.add_argument("--runtime-kustomization", type=Path, default=_DEFAULT_RUNTIME_KUSTOMIZATION)
    return parser


def main() -> int:
    """Validate local Secret sources and encrypted ownership contracts."""
    args = _parser().parse_args()
    age_key_file = args.age_key_file
    if age_key_file is None:
        configured = os.environ.get("SOPS_AGE_KEY_FILE", "")
        if not configured:
            sys.stderr.write("Secret source validation failed: SOPS_AGE_KEY_FILE is required\n")
            return 1
        age_key_file = Path(configured)
    validated_sources: ValidatedSources | None = None
    try:
        contract = _load_local_contract()
        age_recipient = _validate_age_key(age_key_file)
        validated_sources = _validate_sources(
            args.secrets_dir,
            required_sources=_APP_REQUIRED_SOURCES + _runtime_required_sources(contract),
            contract=contract,
        )
        policy_recipient = _validate_sops_and_secret(args.sops_config, args.encrypted_secret, contract)
        _validate_encrypted_tls_secret(
            args.encrypted_secret.with_name("nohiki-model-egress-tls-source.sops.yaml"),
            policy_recipient,
        )
        _validate_encrypted_app_secrets(args.encrypted_app_secrets, policy_recipient, contract)
        _validate_local_kustomization(args.local_secret_kustomization)
        if age_recipient != policy_recipient:
            _fail("SOPS_AGE_KEY_FILE", "does not match the repository SOPS recipient")
        _validate_flux(args.runtime_kustomization)
        validated_sources.revalidate()
    except ValidationError as error:
        sys.stderr.write(f"Secret source validation failed: {error}\n")
        return 1
    finally:
        if validated_sources is not None:
            validated_sources.close()
    sys.stdout.write("Secret source validation passed; no files or cluster resources were changed\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
