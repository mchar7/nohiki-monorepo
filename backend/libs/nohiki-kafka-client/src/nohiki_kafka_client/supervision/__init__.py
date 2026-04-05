"""Consumer supervision and lifecycle management."""

from .lifecycle import (
    KafkaConnectionState,
    KafkaHealthState,
    KafkaLifecycleConfig,
    KafkaLifecycleManager,
    ensure_kafka_ready,
    get_lifecycle_manager,
    init_lifecycle_manager,
)
from .supervisor import (
    ConsumerFactory,
    ConsumerMetrics,
    ConsumerState,
    ConsumerSupervisor,
    ErrorCategory,
    HealthSummary,
    HealthSummaryValue,
    SupervisedConsumer,
    SupervisorConfig,
    calculate_backoff,
    classify_error,
    is_recoverable,
)

__all__ = [
    "ConsumerFactory",
    "ConsumerMetrics",
    "ConsumerState",
    "ConsumerSupervisor",
    "ErrorCategory",
    "HealthSummary",
    "HealthSummaryValue",
    "KafkaConnectionState",
    "KafkaHealthState",
    "KafkaLifecycleConfig",
    "KafkaLifecycleManager",
    "SupervisedConsumer",
    "SupervisorConfig",
    "calculate_backoff",
    "classify_error",
    "ensure_kafka_ready",
    "get_lifecycle_manager",
    "init_lifecycle_manager",
    "is_recoverable",
]
