#!/usr/bin/env python3
"""Prepare canonical model archives on the host and seed local RustFS."""
# Heavy ML dependencies are command-specific; safe boundary failures retain exact diagnostics.
# Linear validation/cleanup stays co-located to preserve all-or-nothing archive writes.
# ruff: noqa: C901, EM101, EM102, PLC0415, S603, S607, TRY003, TRY300

from __future__ import annotations

import argparse
import base64
import binascii
import gzip
import hashlib
import json
import os
import re
import selectors
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_MANIFEST = _ROOT / "data/config/semantic_representation_manifest.json"
_BUCKET = "nohiki-ml-artifacts"
_METADATA_NAME = "model-archives.json"
_ARCHIVE_DIRECTORY = "model-archives"
_MAX_SECRET_BYTES = 4096
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]")
_NOT_FOUND_CODES = frozenset({"404", "NoSuchKey", "NotFound"})
_PRECONDITION_CODES = frozenset({"409", "412", "ConditionalRequestConflict", "PreconditionFailed"})


class _S3Client(Protocol):
    def head_bucket(self, **kwargs: object) -> object: ...

    def head_object(self, **kwargs: object) -> dict[str, Any]: ...

    def get_object(self, **kwargs: object) -> dict[str, Any]: ...

    def put_object(self, **kwargs: object) -> object: ...


class SeedError(RuntimeError):
    """A safe failure that never includes credentials or model payloads."""


@dataclass(frozen=True, slots=True)
class ArchiveSpec:
    """Manifest-derived archive identity used by ml-compute."""

    model_id: str
    revision: str | None
    extract_dir: str
    key: str

    @property
    def filename(self) -> str:
        """Return a filesystem-safe name derived from the complete object key."""
        return _SAFE_NAME.sub("_", self.key)


@dataclass(frozen=True, slots=True)
class PreparedArchive:
    """Metadata-only evidence for one prepared archive."""

    key: str
    filename: str
    byte_length: int
    sha256: str

    def as_dict(self) -> dict[str, object]:
        """Return the canonical metadata-only archive evidence."""
        return {
            "byteLength": self.byte_length,
            "filename": self.filename,
            "key": self.key,
            "sha256": self.sha256,
        }


def _canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _archive_specs(manifest_path: Path) -> tuple[ArchiveSpec, ...]:
    """Use nohiki-ml-core itself to keep host and pod object keys identical."""
    from nohiki_ml_core.model_cache import _default_model_archives
    from nohiki_ml_manifest import SemanticRepresentationManifest

    manifest = SemanticRepresentationManifest.load_from_path(manifest_path)
    return tuple(
        ArchiveSpec(
            model_id=archive.model_id,
            revision=archive.revision,
            extract_dir=archive.extract_dir,
            key=archive.s3_key,
        )
        for archive in _default_model_archives(manifest)
    )


def _pin_huggingface_main_ref(spec: ArchiveSpec, target: Path, snapshot: str) -> None:
    """Make the downloaded snapshot usable through the service's default Hub lookup."""
    repository = target / "hub" / f"models--{spec.model_id.replace('/', '--')}"
    snapshot_dir = Path(snapshot).resolve(strict=True)
    snapshots_dir = (repository / "snapshots").resolve(strict=True)
    if snapshot_dir.parent != snapshots_dir or not (repository / "blobs").is_dir():
        raise SeedError(f"source download produced an invalid Hugging Face cache for {spec.model_id}")
    ref = repository / "refs/main"
    ref.parent.mkdir(exist_ok=True)
    if ref.is_symlink():
        raise SeedError(f"source download produced an invalid Hugging Face reference for {spec.model_id}")
    ref.write_text(snapshot_dir.name, encoding="utf-8")


def _download(spec: ArchiveSpec, target: Path) -> None:
    if spec.extract_dir == "fastembed":
        from fastembed import SparseTextEmbedding

        SparseTextEmbedding(model_name=spec.model_id, cache_dir=str(target))
    else:
        from huggingface_hub import snapshot_download

        arguments: dict[str, object] = {
            "repo_id": spec.model_id,
            "cache_dir": target / "hub",
        }
        if spec.revision is not None:
            arguments["revision"] = spec.revision
        snapshot = snapshot_download(**arguments)
        _pin_huggingface_main_ref(spec, target, snapshot)
    if not any(path.is_file() for path in target.rglob("*")):
        raise SeedError(f"source download produced no files for {spec.model_id}")


def _tree_entries(root: Path) -> Iterator[Path]:
    root = root.resolve(strict=True)

    def visit(directory: Path) -> Iterator[Path]:
        with os.scandir(directory) as children:
            for child in sorted(children, key=lambda item: item.name):
                path = Path(child.path)
                mode = child.stat(follow_symlinks=False).st_mode
                if stat.S_ISLNK(mode):
                    try:
                        target = path.resolve(strict=True)
                    except (FileNotFoundError, RuntimeError) as error:
                        raise SeedError(f"model staging contains a broken symlink: {path.relative_to(root)}") from error
                    if not target.is_relative_to(root) or not target.is_file():
                        raise SeedError(f"model staging symlink escapes its archive: {path.relative_to(root)}")
                    yield path
                elif stat.S_ISDIR(mode):
                    yield path
                    yield from visit(path)
                elif stat.S_ISREG(mode):
                    yield path
                else:
                    raise SeedError(f"model staging contains an unsupported entry: {path.relative_to(root)}")

    yield from visit(root)


def _normalized_tar_info(archive: tarfile.TarFile, path: Path, root: Path) -> tarfile.TarInfo:
    info = archive.gettarinfo(str(path), arcname=str(path.relative_to(root)))
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mtime = 0
    if info.isdir():
        info.mode = 0o755
    elif info.isfile():
        info.mode = 0o644
    else:
        info.mode = 0o777
    return info


def _package(source: Path, destination: Path) -> PreparedArchive:
    digest = hashlib.sha256()
    with (
        destination.open("wb") as raw,
        gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed,
        tarfile.open(fileobj=compressed, mode="w") as archive,
    ):
        root = source.resolve(strict=True)
        for path in _tree_entries(root):
            info = _normalized_tar_info(archive, path, root)
            if info.isfile():
                with path.open("rb") as payload:
                    archive.addfile(info, payload)
            else:
                archive.addfile(info)
    with destination.open("rb") as stream:
        byte_length = 0
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            byte_length += len(block)
            digest.update(block)
    return PreparedArchive("", destination.name, byte_length, digest.hexdigest())


def _write_exclusive(path: Path, value: object) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        os.write(descriptor, _canonical_bytes(value))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def prepare(manifest_path: Path, attempt_dir: Path) -> dict[str, object]:
    """Download and package every manifest model into a private attempt directory."""
    archive_dir = attempt_dir / _ARCHIVE_DIRECTORY
    metadata_path = attempt_dir / _METADATA_NAME
    if archive_dir.exists() or metadata_path.exists() or metadata_path.is_symlink():
        raise SeedError("model archive preparation output already exists for this attempt")
    archive_dir.mkdir(mode=0o700)
    prepared: list[PreparedArchive] = []
    try:
        for spec in _archive_specs(manifest_path):
            destination = archive_dir / spec.filename
            with tempfile.TemporaryDirectory(prefix="model-source-", dir=attempt_dir) as temporary:
                source = Path(temporary)
                _download(spec, source)
                evidence = _package(source, destination)
            prepared.append(PreparedArchive(spec.key, evidence.filename, evidence.byte_length, evidence.sha256))
        record: dict[str, object] = {
            "apiVersion": "nohiki.io/v1alpha1",
            "archives": [item.as_dict() for item in prepared],
            "bucket": _BUCKET,
            "kind": "LocalModelArchiveSeed",
        }
        _write_exclusive(metadata_path, record)
        return record
    except BaseException:
        for path in archive_dir.iterdir():
            path.unlink(missing_ok=True)
        archive_dir.rmdir()
        metadata_path.unlink(missing_ok=True)
        raise


def _load_metadata(attempt_dir: Path) -> tuple[dict[str, object], tuple[PreparedArchive, ...]]:
    metadata_path = attempt_dir / _METADATA_NAME
    try:
        raw = metadata_path.read_bytes()
        record = json.loads(raw)
    except (OSError, json.JSONDecodeError) as error:
        raise SeedError("model archive metadata is missing or invalid") from error
    if not isinstance(record, dict) or _canonical_bytes(record) != raw:
        raise SeedError("model archive metadata is not canonical")
    if record.get("bucket") != _BUCKET or record.get("kind") != "LocalModelArchiveSeed":
        raise SeedError("model archive metadata contract is invalid")
    raw_archives = record.get("archives")
    if not isinstance(raw_archives, list):
        raise SeedError("model archive metadata archives are invalid")
    archives: list[PreparedArchive] = []
    for item in raw_archives:
        if not isinstance(item, dict):
            raise SeedError("model archive metadata entry is invalid")
        try:
            evidence = PreparedArchive(
                key=str(item["key"]),
                filename=str(item["filename"]),
                byte_length=int(item["byteLength"]),
                sha256=str(item["sha256"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise SeedError("model archive metadata entry is invalid") from error
        if evidence.filename != _SAFE_NAME.sub("_", evidence.key) or not re.fullmatch(r"[0-9a-f]{64}", evidence.sha256):
            raise SeedError("model archive metadata identity is invalid")
        path = attempt_dir / _ARCHIVE_DIRECTORY / evidence.filename
        if not path.is_file() or path.is_symlink() or path.stat().st_size != evidence.byte_length:
            raise SeedError(f"prepared model archive does not match metadata: {evidence.filename}")
        digest = _sha256_file(path)
        if digest != evidence.sha256:
            raise SeedError(f"prepared model archive digest does not match metadata: {evidence.filename}")
        archives.append(evidence)
    return record, tuple(archives)


def _port_forward(kubeconfig: Path, namespace: str) -> tuple[subprocess.Popen[str], str]:
    process = subprocess.Popen(
        [
            "kubectl",
            f"--kubeconfig={kubeconfig}",
            "--namespace",
            namespace,
            "port-forward",
            "service/nohiki-rustfs",
            ":9000",
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if process.stdout is None:
        raise SeedError("kubectl port-forward stdout pipe is unavailable")
    deadline = time.monotonic() + 30
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    try:
        while (remaining := deadline - time.monotonic()) > 0:
            if not selector.select(remaining):
                break
            line = process.stdout.readline()
            if match := re.search(r"Forwarding from 127\.0\.0\.1:(\d+)", line):
                return process, f"http://127.0.0.1:{match.group(1)}"
            if process.poll() is not None:
                break
    finally:
        selector.close()
    if process.poll() is None:
        process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
    raise SeedError("RustFS port-forward did not become ready")


def _wait_for_rustfs_backend(
    kubeconfig: Path,
    namespace: str,
    *,
    timeout_seconds: int = 20 * 60,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    base_command = ["kubectl", f"--kubeconfig={kubeconfig}", "--namespace", namespace]
    while (remaining := deadline - time.monotonic()) > 0:
        try:
            result = subprocess.run(
                [
                    *base_command,
                    "get",
                    "service/nohiki-rustfs",
                    "statefulset/nohiki-rustfs",
                ],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=min(10, remaining),
            )
        except subprocess.TimeoutExpired:
            continue
        if result.returncode == 0:
            break
        time.sleep(min(2, max(0, deadline - time.monotonic())))
    else:
        raise SeedError("RustFS Service and StatefulSet discovery wait did not complete within 20 minutes")

    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise SeedError("RustFS Ready backend wait did not complete within 20 minutes")
    try:
        subprocess.run(
            [
                *base_command,
                "rollout",
                "status",
                "statefulset/nohiki-rustfs",
                f"--timeout={max(1, int(remaining))}s",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=remaining + 5,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        raise SeedError("RustFS Ready backend wait did not complete within 20 minutes") from error


def _decode_cluster_credential(encoded: object) -> str:
    if not isinstance(encoded, str):
        raise SeedError("RustFS credential Secret is missing or invalid")
    try:
        raw = base64.b64decode(encoded, validate=True)
        decoded = raw.decode("utf-8")
    except (binascii.Error, UnicodeDecodeError) as error:
        raise SeedError("RustFS credential Secret is missing or invalid") from error
    if not raw or len(raw) > _MAX_SECRET_BYTES or decoded != decoded.strip():
        raise SeedError("RustFS credential Secret is missing or invalid")
    return decoded


def _decode_cluster_credentials(payload: object) -> tuple[str, str]:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
        raise SeedError("RustFS credential Secret is missing or invalid")
    data = payload["data"]
    try:
        access_key = data["access-key"]
        secret_key = data["secret-key"]
    except KeyError as error:
        raise SeedError("RustFS credential Secret is missing or invalid") from error
    return _decode_cluster_credential(access_key), _decode_cluster_credential(secret_key)


def _cluster_credentials(kubeconfig: Path, namespace: str) -> tuple[str, str]:
    try:
        result = subprocess.run(
            [
                "kubectl",
                f"--kubeconfig={kubeconfig}",
                "--namespace",
                namespace,
                "get",
                "secret/nohiki-rustfs-credentials",
                "--output=json",
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
        payload = json.loads(result.stdout)
    except (
        json.JSONDecodeError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ) as error:
        raise SeedError("RustFS credential Secret is missing or invalid") from error
    return _decode_cluster_credentials(payload)


def _client_error_code(error: object) -> str:
    response = getattr(error, "response", None)
    if not isinstance(response, dict):
        return ""
    detail = response.get("Error")
    return str(detail.get("Code", "")) if isinstance(detail, dict) else ""


def _wait_for_bucket(client: _S3Client, *, timeout_seconds: int = 120) -> None:
    from botocore.exceptions import BotoCoreError, ClientError

    deadline = time.monotonic() + timeout_seconds
    last_error: BaseException | None = None
    while (remaining := deadline - time.monotonic()) > 0:
        try:
            client.head_bucket(Bucket=_BUCKET)
            if time.monotonic() <= deadline:
                return
            break
        except (BotoCoreError, ClientError) as error:
            last_error = error
            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(min(2, remaining))
    raise SeedError(f"RustFS bucket {_BUCKET} did not become ready within {timeout_seconds} seconds") from last_error


def _head_archive(client: _S3Client, evidence: PreparedArchive) -> bool:
    from botocore.exceptions import BotoCoreError, ClientError

    try:
        remote = client.head_object(Bucket=_BUCKET, Key=evidence.key)
    except ClientError as error:
        if _client_error_code(error) in _NOT_FOUND_CODES:
            return False
        raise SeedError(f"RustFS object identity inspection failed: {evidence.key}") from error
    except BotoCoreError as error:
        raise SeedError(f"RustFS object identity inspection failed: {evidence.key}") from error
    metadata = remote.get("Metadata")
    remote_sha256 = metadata.get("sha256") if isinstance(metadata, dict) else None
    if remote.get("ContentLength") != evidence.byte_length or remote_sha256 != evidence.sha256:
        raise SeedError(f"RustFS immutable object identity mismatch: {evidence.key}")
    return True


def _verify_archive(client: _S3Client, evidence: PreparedArchive) -> None:
    from botocore.exceptions import BotoCoreError, ClientError

    try:
        remote = client.get_object(Bucket=_BUCKET, Key=evidence.key)
        body = remote["Body"]
        remote_digest = hashlib.sha256()
        remote_length = 0
        try:
            while block := body.read(1024 * 1024):
                remote_length += len(block)
                remote_digest.update(block)
        finally:
            body.close()
    except (BotoCoreError, ClientError, KeyError, OSError, TypeError) as error:
        raise SeedError(f"RustFS object evidence inspection failed: {evidence.key}") from error
    if remote_length != evidence.byte_length or remote_digest.hexdigest() != evidence.sha256:
        raise SeedError(f"RustFS object evidence mismatch after upload: {evidence.key}")


def _upload_archive(client: _S3Client, path: Path, evidence: PreparedArchive) -> None:
    from botocore.exceptions import BotoCoreError, ClientError

    if not _head_archive(client, evidence):
        try:
            with path.open("rb") as payload:
                client.put_object(
                    Bucket=_BUCKET,
                    Key=evidence.key,
                    Body=payload,
                    ContentType="application/gzip",
                    Metadata={"sha256": evidence.sha256},
                    IfNoneMatch="*",
                )
        except ClientError as error:
            if _client_error_code(error) not in _PRECONDITION_CODES:
                raise SeedError(f"RustFS immutable object creation failed: {evidence.key}") from error
            if not _head_archive(client, evidence):
                raise SeedError(f"RustFS immutable object creation conflicted: {evidence.key}") from error
        except (BotoCoreError, OSError) as error:
            raise SeedError(f"RustFS immutable object creation failed: {evidence.key}") from error
    _verify_archive(client, evidence)


def upload(attempt_dir: Path, kubeconfig: Path, namespace: str) -> dict[str, object]:
    """Upload prepared bytes through a local-only RustFS port-forward."""
    import boto3
    from botocore.config import Config

    record, archives = _load_metadata(attempt_dir)
    access_key, secret_key = _cluster_credentials(kubeconfig, namespace)
    _wait_for_rustfs_backend(kubeconfig, namespace)
    forward, endpoint = _port_forward(kubeconfig, namespace)
    try:
        client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="local",
            config=Config(
                signature_version="s3v4",
                connect_timeout=10,
                read_timeout=120,
                retries={"max_attempts": 3, "mode": "standard"},
                s3={"addressing_style": "path"},
            ),
        )
        _wait_for_bucket(client)
        for evidence in archives:
            path = attempt_dir / _ARCHIVE_DIRECTORY / evidence.filename
            _upload_archive(client, path, evidence)
        return record
    finally:
        forward.terminate()
        try:
            forward.wait(timeout=5)
        except subprocess.TimeoutExpired:
            forward.kill()
            forward.wait(timeout=5)


def _absolute_directory(raw: str, label: str) -> Path:
    path = Path(raw)
    if not path.is_absolute() or not path.is_dir() or path.is_symlink() or path.resolve() != path:
        raise SeedError(f"{label} must be an absolute canonical directory")
    return path


def main(argv: list[str] | None = None) -> None:
    """Run one model archive carrier phase."""
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("--attempt-dir", required=True)
    prepare_parser.add_argument("--manifest", default=str(_DEFAULT_MANIFEST))
    upload_parser = subparsers.add_parser("upload")
    upload_parser.add_argument("--attempt-dir", required=True)
    upload_parser.add_argument("--kubeconfig", required=True)
    upload_parser.add_argument("--namespace", default="nohiki")
    arguments = parser.parse_args(argv)
    attempt = _absolute_directory(arguments.attempt_dir, "--attempt-dir")
    if arguments.command == "prepare":
        record = prepare(Path(arguments.manifest), attempt)
    else:
        record = upload(attempt, Path(arguments.kubeconfig), arguments.namespace)
    sys.stdout.buffer.write(_canonical_bytes(record))


if __name__ == "__main__":
    try:
        main()
    except SeedError as error:
        raise SystemExit(f"ERROR: {error}") from error
