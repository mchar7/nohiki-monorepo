"""Protobuf initialization for OpenTelemetry.

This module imports OpenTelemetry protobuf messages to ensure they're properly
initialized before any other OTEL imports. This prevents protobuf registration
order issues that can cause runtime errors.

The imports are done at module load time (when this module is imported),
so simply importing this module performs the necessary initialization.
"""

from google.protobuf import duration_pb2
from opentelemetry.proto.common.v1 import common_pb2
from opentelemetry.proto.logs.v1 import logs_pb2
from opentelemetry.proto.metrics.v1 import metrics_pb2
from opentelemetry.proto.resource.v1 import resource_pb2
from opentelemetry.proto.trace.v1 import trace_pb2

_PROTOBUF_MODULES: tuple[object, ...] = (duration_pb2, common_pb2, logs_pb2, metrics_pb2, resource_pb2, trace_pb2)


def init_protobuf() -> None:
    """No-op function - initialization happens on module import."""
    _ = _PROTOBUF_MODULES
