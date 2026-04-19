"""Module-shared constants for job-storage-service.

Centralizes values that would otherwise drift between ``main.py`` (stale
saga sweep) and ``services/bank_service.py`` (saga TTL on creation).
"""

from __future__ import annotations

from datetime import timedelta

# In-flight ingest sagas live up to 24h before being expired by the
# StaleSagaDetector. Re-discovery after expiry creates a fresh saga row.
SAGA_TTL: timedelta = timedelta(hours=24)
