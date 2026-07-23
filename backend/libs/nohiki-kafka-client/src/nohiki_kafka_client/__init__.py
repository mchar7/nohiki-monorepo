"""Kafka client wrapper for the Nohiki platform.

High-level async Kafka client built on aiokafka,
with built-in support for:
- Decorator-based message handler registration
- Dead Letter Queue (DLQ) with retry support
- Circuit breaker for producer resilience
- OpenTelemetry tracing and metrics
- Database session middleware integration
"""

import importlib
from typing import TYPE_CHECKING

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
    from nohiki_kafka_client.admin import (
        AdminError as AdminError,
    )
    from nohiki_kafka_client.admin import (
        EnsureTopicsResult as EnsureTopicsResult,
    )
    from nohiki_kafka_client.admin import (
        KafkaAdmin as KafkaAdmin,
    )
    from nohiki_kafka_client.admin import (
        TopicAlreadyExistsError as TopicAlreadyExistsError,
    )
    from nohiki_kafka_client.admin import (
        TopicDescription as TopicDescription,
    )
    from nohiki_kafka_client.admin import (
        TopicSpec as TopicSpec,
    )
    from nohiki_kafka_client.middleware.rate_limit import (
        RateLimitAlgorithm as RateLimitAlgorithm,
    )
    from nohiki_kafka_client.middleware.rate_limit import (
        RateLimitConfig as RateLimitConfig,
    )
    from nohiki_kafka_client.middleware.rate_limit import (
        RateLimitMiddleware as RateLimitMiddleware,
    )
    from nohiki_kafka_client.observability import (
        ConsumerSpanParams as ConsumerSpanParams,
    )
    from nohiki_kafka_client.observability import (
        KafkaCapability as KafkaCapability,
    )
    from nohiki_kafka_client.observability import (
        KafkaHealthProbe as KafkaHealthProbe,
    )
    from nohiki_kafka_client.observability import (
        KafkaMetrics as KafkaMetrics,
    )
    from nohiki_kafka_client.observability import (
        create_consumer_span as create_consumer_span,
    )
    from nohiki_kafka_client.observability import (
        create_producer_span as create_producer_span,
    )
    from nohiki_kafka_client.observability import (
        end_span_error as end_span_error,
    )
    from nohiki_kafka_client.observability import (
        end_span_ok as end_span_ok,
    )
    from nohiki_kafka_client.observability import (
        extract_trace_context as extract_trace_context,
    )
    from nohiki_kafka_client.observability import (
        get_kafka_metrics as get_kafka_metrics,
    )
    from nohiki_kafka_client.observability import (
        get_span_id_from_context as get_span_id_from_context,
    )
    from nohiki_kafka_client.observability import (
        get_trace_id_from_context as get_trace_id_from_context,
    )
    from nohiki_kafka_client.observability import (
        inject_trace_context as inject_trace_context,
    )
    from nohiki_kafka_client.observability import (
        maybe_enable_otel as maybe_enable_otel,
    )

_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "AdminError": ("nohiki_kafka_client.admin", "AdminError"),
    "EnsureTopicsResult": ("nohiki_kafka_client.admin", "EnsureTopicsResult"),
    "KafkaAdmin": ("nohiki_kafka_client.admin", "KafkaAdmin"),
    "TopicAlreadyExistsError": ("nohiki_kafka_client.admin", "TopicAlreadyExistsError"),
    "TopicDescription": ("nohiki_kafka_client.admin", "TopicDescription"),
    "TopicSpec": ("nohiki_kafka_client.admin", "TopicSpec"),
    "ConsumerSpanParams": ("nohiki_kafka_client.observability", "ConsumerSpanParams"),
    "KafkaCapability": ("nohiki_kafka_client.observability", "KafkaCapability"),
    "KafkaHealthProbe": ("nohiki_kafka_client.observability", "KafkaHealthProbe"),
    "KafkaMetrics": ("nohiki_kafka_client.observability", "KafkaMetrics"),
    "create_consumer_span": ("nohiki_kafka_client.observability", "create_consumer_span"),
    "create_producer_span": ("nohiki_kafka_client.observability", "create_producer_span"),
    "end_span_error": ("nohiki_kafka_client.observability", "end_span_error"),
    "end_span_ok": ("nohiki_kafka_client.observability", "end_span_ok"),
    "extract_trace_context": ("nohiki_kafka_client.observability", "extract_trace_context"),
    "get_kafka_metrics": ("nohiki_kafka_client.observability", "get_kafka_metrics"),
    "get_span_id_from_context": ("nohiki_kafka_client.observability", "get_span_id_from_context"),
    "get_trace_id_from_context": ("nohiki_kafka_client.observability", "get_trace_id_from_context"),
    "inject_trace_context": ("nohiki_kafka_client.observability", "inject_trace_context"),
    "maybe_enable_otel": ("nohiki_kafka_client.observability", "maybe_enable_otel"),
    "RateLimitAlgorithm": ("nohiki_kafka_client.middleware.rate_limit", "RateLimitAlgorithm"),
    "RateLimitConfig": ("nohiki_kafka_client.middleware.rate_limit", "RateLimitConfig"),
    "RateLimitMiddleware": ("nohiki_kafka_client.middleware.rate_limit", "RateLimitMiddleware"),
}
_RATE_LIMIT_IMPORTS = frozenset({"RateLimitAlgorithm", "RateLimitConfig", "RateLimitMiddleware"})


def __getattr__(name: str) -> object:
    """Resolve admin, observability, and optional rate-limit exports on first use."""
    if name not in _LAZY_IMPORTS:
        msg = f"module {__name__!r} has no attribute {name!r}"
        raise AttributeError(msg)

    module_path, attr_name = _LAZY_IMPORTS[name]
    try:
        module = importlib.import_module(module_path)
    except ImportError as e:
        if name not in _RATE_LIMIT_IMPORTS:
            raise
        msg = f"{name} requires the [ratelimit] extra. Install with: pip install nohiki-kafka-client[ratelimit]"
        raise ImportError(msg) from e
    return getattr(module, attr_name)


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
