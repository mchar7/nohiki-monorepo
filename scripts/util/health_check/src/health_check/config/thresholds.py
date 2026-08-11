"""Tunable operational thresholds for health check evaluation."""

from __future__ import annotations

import os
from typing import Final

STALE_SERVICE_THRESHOLD_HOURS: Final[float] = 6.0
"""Services running longer than this many hours are inspected for Kafka issues."""

CONSUMER_LAG_THRESHOLD: Final[int] = 100
"""Maximum acceptable Kafka consumer lag before a group is considered unhealthy."""

CHECK_DEFAULT_TIMEOUT_SECONDS: Final[float] = 30.0
"""Default per-check timeout applied when ``CheckMetadata.timeout_seconds`` is unset."""

FIX_DEFAULT_TIMEOUT_SECONDS: Final[float] = 60.0
"""Default timeout for automated fix operations."""


KAFKA_CONNECT_DEFAULT_PORT: Final[int] = 8083
"""Default Kafka Connect REST API port."""

GRAFANA_DEFAULT_URL: Final[str] = "http://localhost:3001"
"""Default Grafana base URL for observability checks (host port 3001 → container 3000)."""

PROMETHEUS_DEFAULT_URL: Final[str] = "http://localhost:9090"
"""Default Prometheus base URL for observability checks."""

TEMPO_DEFAULT_URL: Final[str] = "http://localhost:3200"
"""Default Tempo base URL for observability checks."""

MIMIR_DEFAULT_URL: Final[str] = "http://localhost:9009"
"""Default Mimir base URL for observability checks."""

LOKI_DEFAULT_URL: Final[str] = "http://localhost:3100"
"""Default Loki base URL for observability checks."""

PYROSCOPE_DEFAULT_URL: Final[str] = "http://localhost:4040"
"""Default Pyroscope continuous profiling base URL for observability checks."""

PHOENIX_DEFAULT_URL: Final[str] = "http://localhost:6006"
"""Default Arize Phoenix LLM observability base URL for observability checks."""

GRAFANA_ADMIN_USER: Final[str] = os.environ.get("GF_SECURITY_ADMIN_USER", "admin")
"""Grafana admin username; reads GF_SECURITY_ADMIN_USER env var, falls back to compose default."""

GRAFANA_ADMIN_PASSWORD: Final[str] = os.environ.get("GF_SECURITY_ADMIN_PASSWORD", "admin")
"""Grafana admin password; reads GF_SECURITY_ADMIN_PASSWORD env var, falls back to compose default."""

GOTENBERG_PORT: Final[int] = 3000

HTTP_CHECK_TIMEOUT_SECONDS: Final[float] = 10.0
"""Timeout for HTTP health-check requests."""

K8S_RESTART_THRESHOLD: Final[int] = 5
"""Number of pod restarts above which excessive-restart check fails."""

KAFKA_TOPICS_CMD_TIMEOUT_SECONDS: Final[int] = 20
"""Timeout for kafka-topics --list CLI invocations (longer than broker ping)."""

IMPORT_CHECK_TIMEOUT_SECONDS: Final[int] = 10
"""Timeout for exec_in_service import verification commands."""

KAFKA_GROUP_MEMBERSHIP_TIMEOUT_SECONDS: Final[int] = 15
"""Timeout for kafka-consumer-groups --describe membership queries."""

POSTGRES_PORT: Final[int] = 5432
"""Standard PostgreSQL TCP port."""

REDIS_PORT: Final[int] = 6379
"""Standard Redis TCP port."""

KAFKA_PORT: Final[int] = 29092
"""Kafka broker INTERNAL listener port (compose network only)."""

QDRANT_PORT: Final[int] = 6333
"""Qdrant HTTP API port."""

RUSTFS_PORT: Final[int] = 9000
"""RustFS S3-compatible storage internal HTTP port (service-to-service)."""

RUSTFS_HOST_PORT: Final[int] = 9002
"""RustFS S3 API port as mapped to the host in Docker Compose (compose port mapping: 9002→9000)."""

GOTENBERG_PORT: Final[int] = 3000
"""Gotenberg PDF-generation service HTTP port."""

DOCLING_PORT: Final[int] = 5001
"""Docling document-processing service HTTP port."""

SKILL_GRAPH_MIN_SKILL_COUNT: Final[int] = 10_000
"""Minimum number of skill nodes expected in skill_graph_schema.skill_node."""

SKILL_GRAPH_MIN_EMBEDDING_COUNT: Final[int] = 10_000
"""Minimum number of skill embedding points expected in the Qdrant skills collection."""
