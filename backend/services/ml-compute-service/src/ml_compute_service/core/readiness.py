"""Readiness gate for ML model warm-up lifecycle.

Tracks whether ML models have been downloaded and warmed up.
The /readyz endpoint returns 503 while models are loading,
allowing Docker/K8s to distinguish "starting" from "unhealthy".
"""

from __future__ import annotations

import enum
import threading


class ReadinessState(enum.Enum):
    """Possible states of the readiness gate."""

    LOADING = "loading"
    READY = "ready"
    FAILED = "failed"


class ReadinessGate:
    """Thread-safe gate that tracks model warm-up progress."""

    __slots__ = ("_lock", "_state")

    def __init__(self) -> None:
        """Initialize gate in LOADING state."""
        self._state = ReadinessState.LOADING
        self._lock = threading.Lock()

    @property
    def state(self) -> ReadinessState:
        """Current readiness state."""
        with self._lock:
            return self._state

    @property
    def is_ready(self) -> bool:
        """Whether models are loaded and service is fully ready."""
        return self.state == ReadinessState.READY

    @property
    def is_failed(self) -> bool:
        """Whether model loading has failed."""
        return self.state == ReadinessState.FAILED

    def mark_ready(self) -> None:
        """Mark models as loaded and service as ready."""
        with self._lock:
            self._state = ReadinessState.READY

    def mark_failed(self) -> None:
        """Mark model loading as failed."""
        with self._lock:
            self._state = ReadinessState.FAILED

    def reset(self) -> None:
        """Reset to loading state (for testing)."""
        with self._lock:
            self._state = ReadinessState.LOADING


readiness_gate = ReadinessGate()
