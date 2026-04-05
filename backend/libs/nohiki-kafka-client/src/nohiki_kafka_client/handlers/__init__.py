"""Handler types, decorators, and registry for Kafka message processing."""

from nohiki_kafka_client.middleware.protocol import Middleware

from .registry import HandlerRegistryMixin, _HandlerMetadata
from .types import (
    CircuitBreakerConfig,
    DbSessionConfig,
    DLQStrategy,
    ErrorAction,
    HandlerRegistration,
    KafkaPublisher,
    MessageContext,
    MessageHandlerFunc,
    ResilienceConfig,
    classify_error_action,
)

__all__ = [
    "CircuitBreakerConfig",
    "DLQStrategy",
    "DbSessionConfig",
    "ErrorAction",
    "HandlerRegistration",
    "HandlerRegistryMixin",
    "KafkaPublisher",
    "MessageContext",
    "MessageHandlerFunc",
    "Middleware",
    "ResilienceConfig",
    "_HandlerMetadata",
    "classify_error_action",
]
