"""S3 client exceptions."""

from __future__ import annotations


class S3Error(Exception):
    """Base exception for S3 operations."""

    def __init__(self, message: str, key: str | None = None) -> None:
        """Initialize S3 error.

        Args:
            message: Error message.
            key: S3 object key that caused the error.

        """
        super().__init__(message)
        self.key = key


class S3ObjectNotFoundError(S3Error):
    """Raised when an S3 object is not found."""

    def __init__(self, key: str) -> None:
        """Initialize not found error.

        Args:
            key: S3 object key that was not found.

        """
        super().__init__(f"S3 object not found: {key}", key=key)


class S3PermissionError(S3Error):
    """Raised when access to an S3 object is denied."""

    def __init__(self, key: str) -> None:
        """Initialize permission error.

        Args:
            key: S3 object key that access was denied for.

        """
        super().__init__(f"Access denied to S3 object: {key}", key=key)


class S3ObjectTooLargeError(S3Error):
    """Raised before an object download can exceed its configured byte limit."""

    def __init__(self, key: str, max_bytes: int, actual_bytes: int | None = None) -> None:
        """Initialize an object-size error."""
        actual = f" ({actual_bytes} bytes)" if actual_bytes is not None else ""
        super().__init__(f"S3 object{actual} exceeds {max_bytes}-byte download limit", key=key)
        self.max_bytes = max_bytes
        self.actual_bytes = actual_bytes


class S3ConnectionError(S3Error):
    """Raised when connection to S3 fails."""

    def __init__(self, message: str) -> None:
        """Initialize connection error.

        Args:
            message: Error message describing the connection failure.

        """
        super().__init__(f"S3 connection error: {message}")
