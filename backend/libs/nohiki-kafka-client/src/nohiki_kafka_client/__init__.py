"""Kafka client wrapper for the Nohiki platform.

High-level async Kafka client built on aiokafka,
with built-in support for:
- Decorator-based message handler registration
- Dead Letter Queue (DLQ) with retry support
- Circuit breaker for producer resilience
- OpenTelemetry tracing and metrics
- Database session middleware integration
"""

from typing import TYPE_CHECKING

from nohiki_kafka_client.admin import (
    AdminError,
    EnsureTopicsResult,
    KafkaAdmin,
    TopicAlreadyExistsError,
    TopicDescription,
    TopicSpec,
)
from nohiki_kafka_client.client import AutoKafkaClient, HasKafkaSettings, create_kafka_client, get_kafka_client
from nohiki_kafka_client.config import (
    GlobalDLQConfig,
    KafkaClientConfig,
    KafkaConsumerSettings,
    KafkaMixin,
    KafkaSettings,
    ResilienceSettings,
)
from nohiki_kafka_client.consumer import KafkaConsumer, PartitionOffsetTracker, RetryConsumer
from nohiki_kafka_client.dlq import ConsumedMessage, DLQMessage, DLQResult, ErrorInfo, ProcessingContext
from nohiki_kafka_client.exceptions import DLQPublishError, KafkaClientError
from nohiki_kafka_client.handlers import (
    DbSessionConfig,
    DLQStrategy,
    ErrorAction,
    HandlerRegistryMixin,
    MessageContext,
    Middleware,
    ResilienceConfig,
    classify_error_action,
)
from nohiki_kafka_client.middleware import execute_middleware_chain
from nohiki_kafka_client.observability import (
    ConsumerSpanParams,
    KafkaCapability,
    KafkaHealthProbe,
    KafkaMetrics,
    create_consumer_span,
    create_producer_span,
    end_span_error,
    end_span_ok,
    extract_trace_context,
    get_kafka_metrics,
    get_span_id_from_context,
    get_trace_id_from_context,
    inject_trace_context,
    maybe_enable_otel,
)
from nohiki_kafka_client.producer import KafkaProducer, Transaction
from nohiki_kafka_client.resilience import CircuitBreaker, CircuitState
from nohiki_kafka_client.supervision import (
    ConsumerFactory,
    ConsumerMetrics,
    ConsumerState,
    ConsumerSupervisor,
    ErrorCategory,
    HealthSummary,
    HealthSummaryValue,
    KafkaConnectionState,
    KafkaHealthState,
    KafkaLifecycleConfig,
    KafkaLifecycleManager,
    SupervisedConsumer,
    SupervisorConfig,
    calculate_backoff,
    classify_error,
    ensure_kafka_ready,
    get_lifecycle_manager,
    init_lifecycle_manager,
    is_recoverable,
)
from nohiki_kafka_client.topics import Topics
from nohiki_kafka_client.utils import (
    EVENT_VERSION,
    CallbackStateMixin,
    CommandContext,
    callback_from_command,
    check_broker_connectivity,
    create_event_metadata,
)

if TYPE_CHECKING:
    from nohiki_kafka_client.middleware.rate_limit import (
        RateLimitAlgorithm as RateLimitAlgorithm,
    )
    from nohiki_kafka_client.middleware.rate_limit import (
        RateLimitConfig as RateLimitConfig,
    )
    from nohiki_kafka_client.middleware.rate_limit import (
        RateLimitMiddleware as RateLimitMiddleware,
    )


def __getattr__(name: str) -> object:
    """Lazy import rate limiting components (requires [ratelimit] extra)."""
    if name in {"RateLimitAlgorithm", "RateLimitConfig", "RateLimitMiddleware"}:
        try:
            from nohiki_kafka_client.middleware import rate_limit  # noqa: PLC0415
        except ImportError as e:
            msg = f"{name} requires the [ratelimit] extra. Install with: pip install nohiki-kafka-client[ratelimit]"
            raise ImportError(msg) from e
        return getattr(rate_limit, name)
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)


__all__ = [
    "EVENT_VERSION",
    "AdminError",
    "AutoKafkaClient",
    "CallbackStateMixin",
    "CircuitBreaker",
    "CircuitState",
    "CommandContext",
    "ConsumedMessage",
    "ConsumerFactory",
    "ConsumerMetrics",
    "ConsumerSpanParams",
    "ConsumerState",
    "ConsumerSupervisor",
    "DLQMessage",
    "DLQPublishError",
    "DLQResult",
    "DLQStrategy",
    "DbSessionConfig",
    "EnsureTopicsResult",
    "ErrorAction",
    "ErrorCategory",
    "ErrorInfo",
    "GlobalDLQConfig",
    "HandlerRegistryMixin",
    "HasKafkaSettings",
    "HealthSummary",
    "HealthSummaryValue",
    "KafkaAdmin",
    "KafkaCapability",
    "KafkaClientConfig",
    "KafkaClientError",
    "KafkaConnectionState",
    "KafkaConsumer",
    "KafkaConsumerSettings",
    "KafkaHealthProbe",
    "KafkaHealthState",
    "KafkaLifecycleConfig",
    "KafkaLifecycleManager",
    "KafkaMetrics",
    "KafkaMixin",
    "KafkaProducer",
    "KafkaSettings",
    "MessageContext",
    "Middleware",
    "PartitionOffsetTracker",
    "ProcessingContext",
    "RateLimitAlgorithm",
    "RateLimitConfig",
    "RateLimitMiddleware",
    "ResilienceConfig",
    "ResilienceSettings",
    "RetryConsumer",
    "SupervisedConsumer",
    "SupervisorConfig",
    "TopicAlreadyExistsError",
    "TopicDescription",
    "TopicSpec",
    "Topics",
    "Transaction",
    "calculate_backoff",
    "callback_from_command",
    "check_broker_connectivity",
    "classify_error",
    "classify_error_action",
    "create_consumer_span",
    "create_event_metadata",
    "create_kafka_client",
    "create_producer_span",
    "end_span_error",
    "end_span_ok",
    "ensure_kafka_ready",
    "execute_middleware_chain",
    "extract_trace_context",
    "get_kafka_client",
    "get_kafka_metrics",
    "get_lifecycle_manager",
    "get_span_id_from_context",
    "get_trace_id_from_context",
    "init_lifecycle_manager",
    "inject_trace_context",
    "is_recoverable",
    "maybe_enable_otel",
]
