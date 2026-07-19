#!/usr/bin/env python3
"""Provision the exact local LLM runtime Secret as SOPS ciphertext."""

import argparse
import base64
import os
import secrets
import stat
import sys
import tempfile
from contextlib import suppress
from pathlib import Path

import yaml
from provision_local_app_secrets import ProvisionError, _run, _source, _validate_policy
from validate_local_secret_sources import (
    _PROVIDER_SOURCES,
    LocalContractSnapshot,
    ValidationError,
    _load_local_contract,
    _open_directory,
    _runtime_required_sources,
    _validate_sops_and_secret,
    _validate_sources,
)

_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_OUTPUT = _ROOT / "infra/k8s/gitops/secrets/local/nohiki-llm-runtime.sops.yaml"
_DEFAULT_SOPS_CONFIG = _ROOT / ".sops.yaml"
_LOGICAL_PATH = "infra/k8s/gitops/secrets/local/nohiki-llm-runtime.sops.yaml"


def _manifest(sources: dict[str, bytes], contract: LocalContractSnapshot) -> dict[str, object]:
    return {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {"name": "nohiki-llm-runtime", "namespace": "nohiki"},
        "type": "Opaque",
        "data": {
            f"{credential}_api_key": base64.b64encode(_source(sources, _PROVIDER_SOURCES[credential]).encode()).decode(
                "ascii"
            )
            for credential in contract.provider_credentials
        },
    }


def provision(secrets_dir: Path, output: Path, sops_config: Path) -> None:
    """Provision the encrypted local LLM runtime Secret."""
    try:
        contract = _load_local_contract()
    except ValidationError as error:
        raise ProvisionError(str(error)) from error
    recipient = _validate_policy(sops_config)
    try:
        sources = _validate_sources(
            secrets_dir,
            required_sources=_runtime_required_sources(contract),
            optional_sources=(),
            contract=contract,
        )
    except ValidationError as error:
        raise ProvisionError(str(error)) from error
    if ".." in output.parts or output.name != _DEFAULT_OUTPUT.name:
        sources.close()
        message = "output must name the intended local runtime Secret manifest"
        raise ProvisionError(message)
    try:
        parent_descriptor = _open_directory(output.parent, "output parent")
    except ValidationError as error:
        sources.close()
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
        with tempfile.TemporaryDirectory(prefix="nohiki-local-runtime-secret-") as name:
            directory = Path(name)
            directory.chmod(0o700)
            document = _manifest(sources, contract)
            try:
                sources.revalidate()
            except ValidationError as error:
                message = "Secret sources changed before ciphertext generation"
                raise ProvisionError(message) from error
            plaintext = directory / "runtime.yaml"
            plaintext.write_text(
                yaml.safe_dump(document, sort_keys=False),
                encoding="utf-8",
            )
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
                validated_recipient = _validate_sops_and_secret(sops_config, validation_copy, contract)
            except ValidationError as error:
                message = "SOPS output failed runtime Secret validation"
                raise ProvisionError(message) from error
            if validated_recipient != recipient:
                message = "SOPS output used an unauthorized Age recipient"
                raise ProvisionError(message)
            try:
                sources.revalidate()
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
        os.close(parent_descriptor)
        sources.close()


def main() -> int:
    """Provision the runtime Secret from command-line arguments."""
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
        sys.stderr.write(f"Runtime Secret provisioning failed: {error}\n")
        return 1
    sys.stdout.write("Encrypted runtime Secret provisioned; no plaintext material remains\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
