"""Structlog processors for log enrichment.

These processors add service metadata, correlation IDs, and trace information
to log events.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from opentelemetry import trace

from .correlation import get_correlation_id

_REDACTED = "[REDACTED]"
_SENSITIVE_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "client_secret",
        "credentials",
        "id_token",
        "cookie",
        "password",
        "private_key",
        "proxy_authorization",
        "refresh_token",
        "secret",
        "set_cookie",
        "token",
    }
)


def redact_sensitive_data(
    _logger: structlog.typing.WrappedLogger,
    _method_name: str,
    event_dict: structlog.typing.EventDict,
) -> structlog.typing.EventDict:
    """Redact credentials from structured fields, including nested mappings."""

    def _redact(value: object) -> object:
        if isinstance(value, dict):
            return {
                key: _REDACTED if str(key).lower().replace("-", "_") in _SENSITIVE_KEYS else _redact(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [_redact(item) for item in value]
        if isinstance(value, tuple):
            return tuple(_redact(item) for item in value)
        return value

    for key, value in event_dict.items():
        normalized_key = str(key).lower().replace("-", "_")
        event_dict[key] = _REDACTED if normalized_key in _SENSITIVE_KEYS else _redact(value)
    return event_dict


if TYPE_CHECKING:
    import structlog


def add_timestamp(
    _logger: structlog.typing.WrappedLogger,
    _method_name: str,
    event_dict: structlog.typing.EventDict,
) -> structlog.typing.EventDict:
    """Add ISO timestamp to log events."""
    event_dict["timestamp"] = datetime.now(UTC).isoformat()
    return event_dict


def add_correlation_id(
    _logger: structlog.typing.WrappedLogger,
    _method_name: str,
    event_dict: structlog.typing.EventDict,
) -> structlog.typing.EventDict:
    """Add correlation ID to log events."""
    correlation_id = get_correlation_id()
    if correlation_id:
        event_dict["correlation_id"] = correlation_id
    return event_dict


def add_trace_info(
    _logger: structlog.typing.WrappedLogger,
    _method_name: str,
    event_dict: structlog.typing.EventDict,
) -> structlog.typing.EventDict:
    """Add OpenTelemetry trace information to log events."""
    span = trace.get_current_span()
    if span and (span_context := span.get_span_context()).is_valid:
        event_dict["trace_id"] = format(span_context.trace_id, "032x")
        event_dict["span_id"] = format(span_context.span_id, "016x")
    return event_dict


class ServiceInfoProcessor:
    """Processor that adds service name and version to log events."""

    __slots__ = ("_service_name", "_service_version")

    def __init__(self, service_name: str, service_version: str) -> None:
        """Initialize with service metadata."""
        self._service_name = service_name
        self._service_version = service_version

    def __call__(
        self,
        _logger: structlog.typing.WrappedLogger,
        _method_name: str,
        event_dict: structlog.typing.EventDict,
    ) -> structlog.typing.EventDict:
        """Add service information to log events."""
        event_dict["service"] = self._service_name
        event_dict["version"] = self._service_version
        return event_dict
