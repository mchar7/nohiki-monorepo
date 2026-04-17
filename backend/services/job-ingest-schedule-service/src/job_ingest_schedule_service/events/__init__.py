"""Event handlers for job-ingest-schedule-service.

Importing this module registers all Kafka handlers via decorator side effects.
"""

from __future__ import annotations

__all__ = ["start_event_consumer"]


def start_event_consumer() -> None:
    """Lazy re-export that breaks the circular import chain."""
    from job_ingest_schedule_service.events.handlers import (  # noqa: PLC0415
        start_event_consumer as _start,
    )

    _start()
