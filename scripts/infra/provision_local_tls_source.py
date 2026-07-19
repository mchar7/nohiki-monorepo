#!/usr/bin/env python3
"""Provision the tracked local TLS source as SOPS ciphertext only."""

import argparse
import os
import re
import secrets
import stat
import subprocess
import sys
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import cast

import yaml
from validate_local_secret_sources import (
    _AGE_RECIPIENT,
    ValidationError,
    _open_directory,
    _validate_sops_metadata,
)
from validate_local_secret_sources import (
    _load_mapping as _load_validated_mapping,
)

_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_OUTPUT = _ROOT / "infra/k8s/gitops/secrets/local/nohiki-model-egress-tls-source.sops.yaml"
_SOPS_CONFIG = _ROOT / ".sops.yaml"
_LOGICAL_PATH = "infra/k8s/gitops/secrets/local/nohiki-model-egress-tls-source.sops.yaml"
_DNS_NAME = "nohiki-model-egress.nohiki.svc.cluster.local"
_SOPS_VALUE = re.compile(r"ENC\[AES256_GCM,data:[^,]+,iv:[^,]+,tag:[^,]+,type:(?:str|bytes)\]\Z")


class ProvisionError(RuntimeError):
    """A provisioning failure safe to display without Secret contents."""


def _run(command: list[str], *, cwd: Path | None = None, pass_fds: tuple[int, ...] = ()) -> None:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            pass_fds=pass_fds,
        )
    except FileNotFoundError as error:
        message = f"required command {command[0]!r} is unavailable"
        raise ProvisionError(message) from error
    if result.returncode != 0:
        message = f"{command[0]} failed while provisioning local TLS material"
        raise ProvisionError(message)


def _load_mapping(path: Path) -> dict[str, object]:
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        message = "generated SOPS manifest could not be validated"
        raise ProvisionError(message) from error
    if not isinstance(loaded, dict) or not all(isinstance(key, str) for key in loaded):
        message = "generated SOPS manifest is not a YAML mapping"
        raise ProvisionError(message)
    return cast(dict[str, object], loaded)


def _policy_recipient() -> str:
    try:
        config = _load_validated_mapping(_SOPS_CONFIG, ".sops.yaml")
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
        message = "SOPS policy has an unauthorized encryption backend"
        raise ProvisionError(message)
    return recipient


def _verify_ciphertext(path: Path, recipient: str) -> None:
    document = _load_mapping(path)
    if set(document) != {
        "apiVersion",
        "kind",
        "metadata",
        "type",
        "stringData",
        "sops",
    }:
        message = "generated SOPS manifest has an invalid field inventory"
        raise ProvisionError(message)
    if document.get("apiVersion") != "v1" or document.get("kind") != "Secret":
        message = "generated SOPS manifest has an invalid API identity"
        raise ProvisionError(message)
    if (
        document.get("metadata")
        != {
            "name": "nohiki-model-egress-tls-source",
            "namespace": "nohiki",
        }
        or document.get("type") != "kubernetes.io/tls"
    ):
        message = "generated SOPS manifest has an invalid Secret identity"
        raise ProvisionError(message)
    data = document.get("stringData")
    if not isinstance(data, dict) or set(data) != {"tls.crt", "tls.key", "ca.crt"}:
        message = "generated SOPS manifest has an invalid key inventory"
        raise ProvisionError(message)
    if not all(isinstance(value, str) and _SOPS_VALUE.fullmatch(value) for value in data.values()):
        message = "generated SOPS manifest contains plaintext or malformed ciphertext"
        raise ProvisionError(message)
    try:
        _validate_sops_metadata(document.get("sops"), recipient, "generated TLS source")
    except ValidationError as error:
        message = "generated SOPS manifest has invalid encryption metadata"
        raise ProvisionError(message) from error


def _generate_plaintext(directory: Path) -> Path:
    ca_key = directory / "ca.key"
    ca_cert = directory / "ca.crt"
    server_key = directory / "tls.key"
    request = directory / "tls.csr"
    server_cert = directory / "tls.crt"
    extension = directory / "server.ext"
    plaintext = directory / "source.yaml"

    _run(
        [
            "openssl",
            "genpkey",
            "-algorithm",
            "RSA",
            "-pkeyopt",
            "rsa_keygen_bits:3072",
            "-out",
            str(ca_key),
        ]
    )
    _run(
        [
            "openssl",
            "req",
            "-x509",
            "-new",
            "-sha256",
            "-key",
            str(ca_key),
            "-out",
            str(ca_cert),
            "-days",
            "3650",
            "-subj",
            "/CN=nohiki-local-model-egress-ca",
            "-addext",
            "basicConstraints=critical,CA:TRUE,pathlen:0",
            "-addext",
            "keyUsage=critical,keyCertSign,cRLSign",
            "-addext",
            "subjectKeyIdentifier=hash",
        ]
    )
    _run(
        [
            "openssl",
            "genpkey",
            "-algorithm",
            "RSA",
            "-pkeyopt",
            "rsa_keygen_bits:3072",
            "-out",
            str(server_key),
        ]
    )
    _run(
        [
            "openssl",
            "req",
            "-new",
            "-sha256",
            "-key",
            str(server_key),
            "-out",
            str(request),
            "-subj",
            f"/CN={_DNS_NAME}",
        ]
    )
    extension.write_text(
        "basicConstraints=critical,CA:FALSE\n"
        "keyUsage=critical,digitalSignature,keyEncipherment\n"
        f"subjectAltName=DNS:{_DNS_NAME}\n"
        "extendedKeyUsage=serverAuth\n",
        encoding="ascii",
    )
    _run(
        [
            "openssl",
            "x509",
            "-req",
            "-sha256",
            "-in",
            str(request),
            "-CA",
            str(ca_cert),
            "-CAkey",
            str(ca_key),
            "-CAcreateserial",
            "-out",
            str(server_cert),
            "-days",
            "825",
            "-extfile",
            str(extension),
        ]
    )
    _run(["openssl", "verify", "-CAfile", str(ca_cert), str(server_cert)])
    _run(
        [
            "openssl",
            "x509",
            "-in",
            str(server_cert),
            "-checkhost",
            _DNS_NAME,
            "-noout",
        ]
    )

    document = {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {
            "name": "nohiki-model-egress-tls-source",
            "namespace": "nohiki",
        },
        "type": "kubernetes.io/tls",
        "stringData": {
            "tls.crt": server_cert.read_text(encoding="ascii"),
            "tls.key": server_key.read_text(encoding="ascii"),
            "ca.crt": ca_cert.read_text(encoding="ascii"),
        },
    }
    plaintext.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    plaintext.chmod(0o600)
    return plaintext


def provision(output: Path) -> None:
    """Generate, encrypt, validate, and atomically replace the TLS source."""
    if ".." in output.parts or output.name != _DEFAULT_OUTPUT.name:
        message = "output must name the intended local TLS source manifest"
        raise ProvisionError(message)
    recipient = _policy_recipient()
    try:
        parent_descriptor = _open_directory(output.parent, "output parent")
    except ValidationError as error:
        raise ProvisionError(str(error)) from error
    encrypted_temporary: str | None = None
    old_umask = os.umask(0o077)
    try:
        try:
            existing = os.stat(output.name, dir_fd=parent_descriptor, follow_symlinks=False)
        except FileNotFoundError:
            existing = None
        if existing is not None and not stat.S_ISREG(existing.st_mode):
            message = "output must not be a symlink or non-regular file"
            raise ProvisionError(message)
        with tempfile.TemporaryDirectory(prefix="nohiki-local-pki-") as name:
            directory = Path(name)
            directory.chmod(0o700)
            plaintext = _generate_plaintext(directory)
            encrypted_temporary = f".{output.name}.{secrets.token_hex(16)}"
            file_descriptor = os.open(
                encrypted_temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
                dir_fd=parent_descriptor,
            )
            os.close(file_descriptor)
            inheritable = True
            os.set_inheritable(parent_descriptor, inheritable)
            encrypted_path = Path(f"/proc/self/fd/{parent_descriptor}/{encrypted_temporary}")
            _run(
                [
                    "sops",
                    "--config",
                    str(_SOPS_CONFIG),
                    "--age",
                    recipient,
                    "encrypt",
                    "--filename-override",
                    _LOGICAL_PATH,
                    "--output",
                    str(encrypted_path),
                    str(plaintext),
                ],
                cwd=_ROOT,
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
            _verify_ciphertext(validation_copy, recipient)
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
        os.close(parent_descriptor)


def main() -> int:
    """Provision the local TLS source from command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=_DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        provision(args.output)
    except ProvisionError as error:
        sys.stderr.write(f"Local TLS source provisioning failed: {error}\n")
        return 1
    sys.stdout.write("Encrypted local TLS source provisioned; no plaintext material remains\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
