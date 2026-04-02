"""Standardized exception hierarchy for Nohiki services.

Consistent exception hierarchy that all Nohiki services
- Automatic retry classification in Kafka handlers
- Structured logging with severity levels
- Clear distinction between retryable and non-retryable errors

Example:
    from nohiki_common_exceptions import (
        DataNotAvailableError,
        DataNotFoundError,
        RetryStrategy,
    )

    # Raise a retryable error
    raise DataNotAvailableError(
        resource_type="Listing",
        resource_id="abc-123",
        source="cache",
    )

    # Check if an exception is retryable
    try:
        await get_data()
    except NohikiError as e:
        if e.is_retryable:
            await retry_later()
        else:
            await send_to_dlq()

"""

__version__ = "0.1.0"

from .base import (
    ErrorSeverity,
    NohikiError,
    RetryStrategy,
)
from .data import (
    DataIntegrityError,
    DataNotAvailableError,
    DataNotFoundError,
    StaleDataError,
)
from .external import (
    ExternalServiceError,
    RateLimitedError,
)
from .health import (
    HealthProbe,
    HealthProbeResult,
    HealthProbeTimer,
    HealthStatus,
    create_degraded_result,
    create_healthy_result,
    create_unhealthy_result,
)
from .user_messages import (
    DEFAULT_MESSAGES,
    UserFacingErrorCode,
    get_default_message,
)
from .validation import (
    SchemaVersionMismatchError,
    ValidationError,
)

__all__ = [
    "DEFAULT_MESSAGES",
    "DataIntegrityError",
    "DataNotAvailableError",
    "DataNotFoundError",
    "ErrorSeverity",
    "ExternalServiceError",
    "HealthProbe",
    "HealthProbeResult",
    "HealthProbeTimer",
    "HealthStatus",
    "NohikiError",
    "RateLimitedError",
    "RetryStrategy",
    "SchemaVersionMismatchError",
    "StaleDataError",
    "UserFacingErrorCode",
    "ValidationError",
    "create_degraded_result",
    "create_healthy_result",
    "create_unhealthy_result",
    "get_default_message",
]
