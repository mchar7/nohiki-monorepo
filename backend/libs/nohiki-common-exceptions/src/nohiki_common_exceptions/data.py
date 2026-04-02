"""Data availability exceptions for Nohiki services."""

from dataclasses import dataclass

from .base import ErrorSeverity, NohikiError, RetryStrategy

_MAX_IDS_IN_MESSAGE = 5


@dataclass
class DataNotAvailableError(NohikiError):
    """Raised when required data cannot be retrieved from cache or fallback.

    This exception indicates a temporary unavailability of data. The data may
    become available on retry, so this exception triggers retry logic.

    Use this exception when:
    - Cache miss occurs and the data might be populated soon
    - A service temporarily cannot respond to data requests
    - Network issues prevent data retrieval

    Attributes:
        resource_type: The type of resource that is unavailable (e.g., "Listing", "Profile").
        resource_id: The identifier of the unavailable resource.
        source: Where the data was expected (e.g., "cache", "grpc", "database").

    """

    resource_type: str = ""
    resource_id: str = ""
    source: str = ""

    def __post_init__(self) -> None:
        """Set default message and retry behavior."""
        if not self.message:
            self.message = f"{self.resource_type} '{self.resource_id}' unavailable from {self.source}"
        self.severity = ErrorSeverity.HIGH
        self.retry_strategy = RetryStrategy.RETRY_EXPONENTIAL
        self.context |= {
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "source": self.source,
        }
        super().__post_init__()


@dataclass
class DataNotFoundError(NohikiError):
    """Raised when data definitively does not exist.

    Unlike DataNotAvailableError, this exception indicates that the data
    genuinely does not exist, not that it's temporarily unavailable.
    This exception does NOT trigger retry logic.

    Use this exception when:
    - A database lookup returns no results for a known-good query
    - An entity was deleted
    - The ID is invalid or refers to a non-existent resource

    Attributes:
        resource_type: The type of resource not found (e.g., "Listing", "Account").
        resource_id: The identifier that was looked up.

    """

    resource_type: str = ""
    resource_id: str = ""

    def __post_init__(self) -> None:
        """Set default message and mark as non-retryable."""
        if not self.message:
            self.message = f"{self.resource_type} '{self.resource_id}' not found"
        self.severity = ErrorSeverity.MEDIUM
        self.retry_strategy = RetryStrategy.NO_RETRY
        self.context |= {
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
        }
        super().__post_init__()


@dataclass
class StaleDataError(NohikiError):
    """Raised when data exists but is too old to be useful.

    This exception indicates the data was found but has exceeded its
    maximum acceptable age. A retry may succeed if the data is refreshed.

    Use this exception when:
    - Cached data has exceeded its validity period
    - Time-sensitive data is older than allowed
    - Business rules require fresher data than what's available

    Attributes:
        resource_type: The type of stale resource.
        resource_id: The identifier of the stale resource.
        data_age_seconds: How old the data is in seconds.
        max_age_seconds: Maximum acceptable age in seconds.

    """

    resource_type: str = ""
    resource_id: str = ""
    data_age_seconds: float = 0.0
    max_age_seconds: float = 0.0

    def __post_init__(self) -> None:
        """Set default message with age information."""
        if not self.message:
            self.message = (
                f"{self.resource_type} '{self.resource_id}' is stale "
                f"(age: {self.data_age_seconds}s, max: {self.max_age_seconds}s)"
            )
        self.severity = ErrorSeverity.MEDIUM
        self.retry_strategy = RetryStrategy.RETRY_IMMEDIATE
        self.context |= {
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "data_age_seconds": self.data_age_seconds,
            "max_age_seconds": self.max_age_seconds,
        }
        super().__post_init__()


@dataclass
class DataIntegrityError(NohikiError):
    """Raised when data that MUST exist is missing or inconsistent.

    Unlike DataNotAvailableError (temporary) or DataNotFoundError (entity
    doesn't exist), this exception indicates a data integrity violation:
    the data was expected to exist based on prior writes but is missing.
    This is NOT retryable; it requires investigation.

    Use this exception when:
    - Embeddings are missing from Qdrant for a skill that was previously indexed
    - A foreign-key reference points to a non-existent record
    - A required projection table entry is absent after upstream event processing

    Attributes:
        resource_type: The type of resource with integrity issues.
        resource_ids: Identifiers of the missing/inconsistent resources.

    """

    resource_type: str = ""
    resource_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Set default message and mark as non-retryable."""
        if not self.message:
            ids_str = ", ".join(self.resource_ids[:_MAX_IDS_IN_MESSAGE])
            overflow = len(self.resource_ids) - _MAX_IDS_IN_MESSAGE
            suffix = f" (and {overflow} more)" if overflow > 0 else ""
            self.message = f"{self.resource_type} integrity violation: missing [{ids_str}{suffix}]"
        self.severity = ErrorSeverity.CRITICAL
        self.retry_strategy = RetryStrategy.NO_RETRY
        self.context |= {
            "resource_type": self.resource_type,
            "resource_ids": list(self.resource_ids),
        }
        super().__post_init__()
