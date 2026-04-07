"""Logger wrapper providing a typed interface for structlog.

A Logger class that wraps structlog's BoundLogger
with explicit typing and a consistent API.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import structlog


class Logger:
    """Structured logger with OpenTelemetry integration.

    Wraps structlog's BoundLogger to provide a typed interface and
    ensure consistent logging patterns across all Nohiki services.
    """

    __slots__ = ("_logger",)

    def __init__(self, logger: structlog.typing.FilteringBoundLogger) -> None:
        """Initialize with a structlog bound logger."""
        self._logger = logger

    def debug(self, event: str, **kwargs: object) -> None:
        """Log a debug message."""
        self._logger.debug(event, **kwargs)

    def info(self, event: str, *, flush: bool = False, **kwargs: object) -> None:
        """Log an info message."""
        self._logger.info(event, **kwargs)
        if flush:
            sys.stdout.flush()

    def warning(self, event: str, **kwargs: object) -> None:
        """Log a warning message."""
        self._logger.warning(event, **kwargs)

    def error(self, event: str, **kwargs: object) -> None:
        """Log an error message."""
        self._logger.error(event, **kwargs)

    def exception(self, event: str, **kwargs: object) -> None:
        """Log an exception with traceback."""
        self._logger.exception(event, **kwargs)

    def critical(self, event: str, **kwargs: object) -> None:
        """Log a critical message."""
        self._logger.critical(event, **kwargs)

    def bind(self, **kwargs: object) -> Logger:
        """Return a new logger with additional context bound."""
        return Logger(self._logger.bind(**kwargs))
