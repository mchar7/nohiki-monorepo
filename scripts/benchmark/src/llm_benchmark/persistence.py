"""Crash-safe JSON artifact persistence."""

import os
from pathlib import Path


def atomic_write_json(path: Path, content: str) -> None:
    """Write serialized JSON to ``path`` atomically and durably.

    The JSON is written to a sibling ``.tmp`` file, flushed and synchronized,
    then atomically replaces the destination. The parent directory is
    synchronized after the replace so the directory entry is durable. Any
    temporary file left by a failed write is removed before the error is
    propagated.

    Args:
        path: Destination JSON file.
        content: Complete serialized JSON document.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    try:
        with tmp.open("w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        tmp.replace(path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
