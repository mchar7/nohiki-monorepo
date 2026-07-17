#!/usr/bin/env python3
"""Descriptor-bound validation for Flux bootstrap inputs."""

from __future__ import annotations

import fcntl
import hashlib
import os
import re
import shutil
import stat
import sys
from pathlib import Path
from typing import NoReturn

AGE_KEY_MAX_BYTES = 64 * 1024
KUBECONFIG_MAX_BYTES = 1024 * 1024
FLUX_FILE_MAX_BYTES = 32 * 1024 * 1024
FLUX_FILES = ("gotk-components.yaml", "gotk-sync.yaml", "kustomization.yaml")
PRIVATE_FILE_MODE = 0o600
WORKTREE_FILE_MODE = 0o644
GIT_OBJECT_ID = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?\Z")


def _fail(message: str) -> NoReturn:
    sys.stderr.write(f"Error: {message}\n")
    raise SystemExit(1)


def _read_bounded(fd: int, expected_size: int, limit: int, label: str) -> bytes:
    if not 0 < expected_size <= limit:
        _fail(f"{label} size is outside the accepted boundary.")
    chunks: list[bytes] = []
    remaining = expected_size
    while remaining:
        chunk = os.read(fd, min(remaining, 1024 * 1024))
        if not chunk:
            _fail(f"{label} changed while it was being snapshotted.")
        chunks.append(chunk)
        remaining -= len(chunk)
    if os.read(fd, 1):
        _fail(f"{label} changed while it was being snapshotted.")
    return b"".join(chunks)


def _write_private_file(destination: Path, content: bytes, label: str) -> None:
    try:
        destination_fd = os.open(
            destination,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
            PRIVATE_FILE_MODE,
        )
    except OSError as error:
        _fail(f"cannot create the private {label} snapshot: {error.strerror}")
    try:
        view = memoryview(content)
        while view:
            written = os.write(destination_fd, view)
            view = view[written:]
        os.fchmod(destination_fd, PRIVATE_FILE_MODE)
        os.fsync(destination_fd)
    finally:
        os.close(destination_fd)


def _snapshot_age_key(source: Path, destination: Path) -> str:
    try:
        source_fd = os.open(source, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    except OSError as error:
        _fail(f"cannot securely open SOPS_AGE_KEY_FILE: {error.strerror}")
    try:
        metadata = os.fstat(source_fd)
        if not stat.S_ISREG(metadata.st_mode):
            _fail("SOPS_AGE_KEY_FILE must be a regular file.")
        if metadata.st_uid != os.geteuid():
            _fail("SOPS_AGE_KEY_FILE must be owned by the current user.")
        if stat.S_IMODE(metadata.st_mode) & 0o077:
            _fail("SOPS_AGE_KEY_FILE must not grant group or other permissions.")
        content = _read_bounded(source_fd, metadata.st_size, AGE_KEY_MAX_BYTES, "SOPS_AGE_KEY_FILE")
        if b"\x00" in content or not content.endswith(b"\n"):
            _fail("SOPS_AGE_KEY_FILE violates text boundaries.")
        try:
            lines = content.decode("ascii").splitlines()
        except UnicodeDecodeError:
            _fail("SOPS_AGE_KEY_FILE must contain ASCII Age identity text.")
        identities = [line for line in lines if line.startswith("AGE-SECRET-KEY-1")]
        if len(identities) != 1 or any(line and not line.startswith("#") and line not in identities for line in lines):
            _fail("SOPS_AGE_KEY_FILE must contain exactly one Age identity.")
    finally:
        os.close(source_fd)

    _write_private_file(destination, content, "Age key")
    return hashlib.sha256(content).hexdigest()


def _snapshot_kubeconfig(source: Path, destination: Path) -> str:
    try:
        source_fd = os.open(source, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    except OSError as error:
        _fail(f"cannot securely open KUBECONFIG: {error.strerror}")
    try:
        metadata = os.fstat(source_fd)
        if not stat.S_ISREG(metadata.st_mode):
            _fail("KUBECONFIG must be a regular file.")
        if metadata.st_uid != os.geteuid():
            _fail("KUBECONFIG must be owned by the current user.")
        if stat.S_IMODE(metadata.st_mode) & 0o077:
            _fail("KUBECONFIG must not grant group or other permissions.")
        content = _read_bounded(source_fd, metadata.st_size, KUBECONFIG_MAX_BYTES, "KUBECONFIG")
        if b"\x00" in content:
            _fail("KUBECONFIG violates text boundaries.")
        try:
            content.decode("utf-8")
        except UnicodeDecodeError:
            _fail("KUBECONFIG must contain UTF-8 text.")
    finally:
        os.close(source_fd)
    _write_private_file(destination, content, "kubeconfig source")
    return hashlib.sha256(content).hexdigest()


def _validated_flux_contents(directory: Path) -> list[tuple[str, bytes]]:
    try:
        directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW)
    except OSError as error:
        _fail(f"cannot securely open generated Flux snapshot: {error.strerror}")
    try:
        names = {entry.name for entry in os.scandir(directory_fd)}
        if names != set(FLUX_FILES):
            _fail("generated Flux snapshot does not contain the exact file allowlist.")
        validated: list[tuple[str, bytes]] = []
        for name in FLUX_FILES:
            try:
                fd = os.open(
                    name,
                    os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
                    dir_fd=directory_fd,
                )
            except OSError as error:
                _fail(f"cannot securely open generated Flux file {name}: {error.strerror}")
            try:
                metadata = os.fstat(fd)
                if not stat.S_ISREG(metadata.st_mode):
                    _fail(f"generated Flux file {name} is not regular.")
                if metadata.st_uid != os.geteuid():
                    _fail(f"generated Flux file {name} has an unexpected owner.")
                if stat.S_IMODE(metadata.st_mode) != PRIVATE_FILE_MODE:
                    _fail(f"generated Flux file {name} must have mode 0600.")
                content = _read_bounded(
                    fd,
                    metadata.st_size,
                    FLUX_FILE_MAX_BYTES,
                    f"generated Flux file {name}",
                )
                if b"\x00" in content or not content.endswith(b"\n"):
                    _fail(f"generated Flux file {name} violates text boundaries.")
                try:
                    content.decode("utf-8")
                except UnicodeDecodeError:
                    _fail(f"generated Flux file {name} is not valid UTF-8.")
                validated.append((name, content))
            finally:
                os.close(fd)
        return validated
    finally:
        os.close(directory_fd)


def _write_git_blob(repository: Path, content: bytes) -> str:
    git = shutil.which("git")
    if git is None:
        _fail("git CLI not found.")
    input_read, input_write = os.pipe()
    output_read, output_write = os.pipe()
    file_actions = [
        (os.POSIX_SPAWN_DUP2, input_read, 0),
        (os.POSIX_SPAWN_DUP2, output_write, 1),
        (os.POSIX_SPAWN_CLOSE, input_write),
        (os.POSIX_SPAWN_CLOSE, output_read),
        (os.POSIX_SPAWN_CLOSE, input_read),
        (os.POSIX_SPAWN_CLOSE, output_write),
    ]
    try:
        process_id = os.posix_spawn(
            git,
            [git, "-C", os.fspath(repository), "hash-object", "-w", "--stdin"],
            os.environ,
            file_actions=file_actions,
        )
    except OSError as error:
        os.close(input_read)
        os.close(input_write)
        os.close(output_read)
        os.close(output_write)
        _fail(f"cannot start git hash-object: {error.strerror}")
    os.close(input_read)
    os.close(output_write)
    try:
        view = memoryview(content)
        while view:
            written = os.write(input_write, view)
            view = view[written:]
    finally:
        os.close(input_write)
    try:
        output = os.read(output_read, 128)
    finally:
        os.close(output_read)
    _, wait_status = os.waitpid(process_id, 0)
    if os.waitstatus_to_exitcode(wait_status) != 0:
        _fail("cannot write a validated Flux blob to the Git object database.")
    return output.decode("ascii", errors="strict").strip()


def _write_validated_flux_blobs(directory: Path, repository: Path, destination: Path) -> None:
    validated = _validated_flux_contents(directory)
    records: list[tuple[str, str]] = []
    for name, content in validated:
        object_id = _write_git_blob(repository, content)
        if not GIT_OBJECT_ID.fullmatch(object_id):
            _fail("cannot write a validated Flux blob to the Git object database.")
        records.append((name, object_id))

    try:
        destination.mkdir(mode=0o755, exist_ok=True)
        destination_fd = os.open(destination, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW)
    except OSError as error:
        _fail(f"cannot create the validated Flux worktree directory: {error.strerror}")
    try:
        if any(os.scandir(destination_fd)):
            _fail("Flux worktree destination is no longer empty.")
        os.fchmod(destination_fd, 0o755)
        for name, content in validated:
            fd = os.open(
                name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
                WORKTREE_FILE_MODE,
                dir_fd=destination_fd,
            )
            try:
                view = memoryview(content)
                while view:
                    written = os.write(fd, view)
                    view = view[written:]
                os.fchmod(fd, WORKTREE_FILE_MODE)
                os.fsync(fd)
            finally:
                os.close(fd)
    finally:
        os.close(destination_fd)

    for name, object_id in records:
        sys.stdout.write(f"{name} {object_id}\n")


def _sealed_snapshot(path: str, expected_hash: str) -> int:
    try:
        source_fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    except OSError as error:
        _fail(f"cannot securely reopen private snapshot: {error.strerror}")
    try:
        metadata = os.fstat(source_fd)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) != PRIVATE_FILE_MODE
        ):
            _fail("private snapshot descriptor metadata changed.")
        content = _read_bounded(source_fd, metadata.st_size, KUBECONFIG_MAX_BYTES, "private snapshot")
    finally:
        os.close(source_fd)
    if hashlib.sha256(content).hexdigest() != expected_hash:
        _fail("private snapshot content hash changed.")

    sealed_fd = os.memfd_create("nohiki-bootstrap-snapshot", os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
    view = memoryview(content)
    while view:
        written = os.write(sealed_fd, view)
        view = view[written:]
    os.lseek(sealed_fd, 0, os.SEEK_SET)
    fcntl.fcntl(
        sealed_fd,
        fcntl.F_ADD_SEALS,
        fcntl.F_SEAL_WRITE | fcntl.F_SEAL_GROW | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_SEAL,
    )
    os.set_inheritable(sealed_fd, not os.get_inheritable(sealed_fd))
    return sealed_fd


def _exec_bound(arguments: list[str]) -> None:
    try:
        separator = arguments.index("--")
    except ValueError:
        _fail("exec-bound requires -- before the consumer command.")
    binding_arguments = arguments[:separator]
    command = arguments[separator + 1 :]
    if not command or len(binding_arguments) % 3:
        _fail("exec-bound requires PATH SHA256 PLACEHOLDER triplets and a command.")

    descriptors: list[int] = []
    replacements: dict[str, str] = {}
    try:
        for offset in range(0, len(binding_arguments), 3):
            path, expected_hash, placeholder = binding_arguments[offset : offset + 3]
            sealed_fd = _sealed_snapshot(path, expected_hash)
            descriptors.append(sealed_fd)
            replacements[placeholder] = f"/proc/self/fd/{sealed_fd}"

        resolved_command = [
            next(
                (
                    argument.replace(token, descriptor)
                    for token, descriptor in replacements.items()
                    if token in argument
                ),
                argument,
            )
            for argument in command
        ]
        executable = shutil.which(resolved_command[0])
        if executable is None:
            _fail("descriptor-bound consumer executable was not found.")
        process_id = os.posix_spawn(executable, resolved_command, os.environ)
        _, wait_status = os.waitpid(process_id, 0)
        exit_code = os.waitstatus_to_exitcode(wait_status)
        if exit_code:
            raise SystemExit(exit_code)
    finally:
        for fd in descriptors:
            os.close(fd)


def main(argv: list[str]) -> None:
    """Dispatch one descriptor-safe snapshot operation."""
    match argv[1:]:
        case ["snapshot-age-key", source, destination]:
            sys.stdout.write(f"{_snapshot_age_key(Path(source), Path(destination))}\n")
        case ["snapshot-kubeconfig", source, destination]:
            sys.stdout.write(f"{_snapshot_kubeconfig(Path(source), Path(destination))}\n")
        case ["exec-bound", *arguments]:
            _exec_bound(arguments)
        case ["validate-flux", directory]:
            _validated_flux_contents(Path(directory))
        case ["write-flux-blobs", directory, repository, destination]:
            _write_validated_flux_blobs(Path(directory), Path(repository), Path(destination))
        case _:
            _fail(
                "usage: secure-snapshot.py snapshot-age-key SOURCE DESTINATION | "
                "snapshot-kubeconfig SOURCE DESTINATION | exec-bound PATH SHA256 "
                "PLACEHOLDER [...] -- COMMAND [...] | validate-flux DIRECTORY | "
                "write-flux-blobs DIRECTORY REPOSITORY DESTINATION"
            )


if __name__ == "__main__":
    main(sys.argv)
