"""E2E testing configuration.

Supports both Docker Compose and Kubernetes targets.
Set NOHIKI_TARGET=compose (default) or NOHIKI_TARGET=k8s.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class E2EConfig:
    """Configuration for E2E testing environment."""

    # Deployment target: 'compose' or 'k8s'
    target: str = "compose"

    # HTTP settings
    base_url: str = "http://localhost:8000"

    # Kafka settings
    kafka_bootstrap_servers: str = "localhost:29092"

    # Kubernetes settings
    k8s_namespace: str = "default"

    # Timeouts
    deployment_timeout: int = 300
    workflow_timeout: int = 180
    event_timeout: int = 60

    # Feature flags
    verify_observability: bool = False

    @property
    def is_k8s(self) -> bool:
        """Whether we're targeting a Kubernetes deployment."""
        return self.target in ("k8s", "kubernetes")

    @classmethod
    def from_environment(cls) -> E2EConfig:
        """Create configuration from environment variables."""
        target = os.getenv("NOHIKI_TARGET", "compose").lower()
        return cls(
            target=target,
            base_url=os.getenv("E2E_BASE_URL", "http://localhost:8000"),
            kafka_bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:29092"),
            k8s_namespace=os.getenv("K8S_NAMESPACE", "default"),
            deployment_timeout=int(os.getenv("E2E_DEPLOYMENT_TIMEOUT", "300")),
            workflow_timeout=int(os.getenv("E2E_WORKFLOW_TIMEOUT", "180")),
            event_timeout=int(os.getenv("E2E_EVENT_TIMEOUT", "60")),
            verify_observability=os.getenv("E2E_VERIFY_OBSERVABILITY", "false").lower() == "true",
        )
