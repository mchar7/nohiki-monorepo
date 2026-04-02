"""Validation exceptions for Nohiki services."""

from dataclasses import dataclass
from typing import Any

from .base import ErrorSeverity, NohikiError, RetryStrategy

# Maximum length for invalid value representation in logs
_MAX_VALUE_LENGTH = 100


@dataclass
class ValidationError(NohikiError):
    """Raised when input data fails validation.

    This exception indicates the input data is fundamentally invalid
    and cannot be processed. It does NOT trigger retry logic since
    retrying with the same invalid data would produce the same result.

    Use this exception when:
    - Required fields are missing
    - Field values fail format/type validation
    - Business rule validation fails

    Attributes:
        field_name: Name of the field that failed validation.
        invalid_value: The value that failed validation (truncated in logs).
        constraint: Description of the constraint that was violated.

    """

    field_name: str = ""
    invalid_value: Any = None
    constraint: str = ""

    def __post_init__(self) -> None:
        """Set default message and mark as non-retryable."""
        if not self.message:
            self.message = f"Validation failed for '{self.field_name}': {self.constraint}"
        self.severity = ErrorSeverity.LOW
        self.retry_strategy = RetryStrategy.NO_RETRY

        # Truncate invalid value for logging to avoid exposing large payloads
        invalid_value_str = str(self.invalid_value)
        if len(invalid_value_str) > _MAX_VALUE_LENGTH:
            invalid_value_str = invalid_value_str[:_MAX_VALUE_LENGTH] + "..."

        self.context |= {
            "field_name": self.field_name,
            "invalid_value": invalid_value_str,
            "constraint": self.constraint,
        }
        super().__post_init__()


@dataclass
class SchemaVersionMismatchError(NohikiError):
    """Raised when event schema version doesn't correlation expected.

    This exception indicates an incompatibility between the schema version
    of incoming data and what this service expects. This is NOT retryable
    as it requires code changes to resolve.

    Use this exception when:
    - Protobuf schema version is incompatible
    - JSON schema version doesn't correlation expectations
    - API version negotiation fails

    Attributes:
        expected_version: The version this service expects.
        actual_version: The version that was received.

    """

    expected_version: str = ""
    actual_version: str = ""

    def __post_init__(self) -> None:
        """Set default message and mark as non-retryable."""
        if not self.message:
            self.message = f"Schema version miscorrelation: expected {self.expected_version}, got {self.actual_version}"
        self.severity = ErrorSeverity.HIGH
        self.retry_strategy = RetryStrategy.NO_RETRY
        self.context |= {
            "expected_version": self.expected_version,
            "actual_version": self.actual_version,
        }
        super().__post_init__()
