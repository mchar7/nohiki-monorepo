"""Constants and configuration for projection handlers.

Projection handlers are split into two consumer groups so that high-volume
bulk topics (skills bootstrap, job listings) cannot starve latency-sensitive
user-facing projections (profiles, uploads, correlations, templates).
Each group gets its own concurrency semaphore via the kafka client.
"""

from __future__ import annotations

from bff_service.core.config import get_settings

settings = get_settings()

# User-facing projections: low volume, latency-sensitive
projection_priority_group_id = f"{settings.kafka.consumer_group}-projections-priority"

# Authentication revocations replay independently from mutable account projections.
projection_auth_revocation_group_id = f"{settings.kafka.consumer_group}-projections-auth-revocation"

# Bulk projections: high volume, latency-tolerant (skills bootstrap, job listings)
projection_bulk_group_id = f"{settings.kafka.consumer_group}-projections-bulk"

if settings.database is None:
    _msg = "BFF service requires DATABASE to be configured for projections"
    raise RuntimeError(_msg)
