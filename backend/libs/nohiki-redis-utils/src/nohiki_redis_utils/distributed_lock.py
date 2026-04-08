"""Distributed locking functionality for Redis cache."""

from __future__ import annotations


class DistributedLockError(Exception):
    """Raised when distributed lock operations fail."""
