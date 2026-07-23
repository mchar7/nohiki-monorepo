"""Shared fixtures for the cross-service integration test package.

Only the OpenTelemetry kill-switch lives here. Tests get their containers
from ``nohiki_db_utils.testing`` (Postgres) and
``nohiki_redis_utils.testing`` (Redis) via the per-subtree conftests under
``tests/integration/`` and ``tests/api/``.
"""

from __future__ import annotations

import os

# Disable OpenTelemetry completely during tests. Set at module import so any
# observability bootstrap that runs at test-collect time also sees the flags.
os.environ["OTEL_SDK_DISABLED"] = "true"
os.environ["OTEL_TRACES_EXPORTER"] = "none"
os.environ["OTEL_METRICS_EXPORTER"] = "none"
os.environ["OTEL_LOGS_EXPORTER"] = "none"
os.environ["OTEL_PYTHON_DISABLED_INSTRUMENTATIONS"] = "all"
