"""Docling-core type imports with graceful degradation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

try:
    from docling_core.types.doc import DoclingDocument as _DoclingDocument

    DOCLING_AVAILABLE = True
    DoclingDocument = _DoclingDocument
except ImportError:
    DOCLING_AVAILABLE = False

    if TYPE_CHECKING:
        from docling_core.types.doc import DoclingDocument
    else:
        DoclingDocument: Any = None


class DoclingNotAvailableError(ImportError):
    """Raised when docling-core is required but not installed."""

    def __init__(self) -> None:
        """Initialize docling not available error."""
        super().__init__(
            "docling-core is required for document processing. Install with: pip install doc-process-service[docling]"
        )


def require_docling() -> None:
    """Ensure docling-core is available.

    Raises:
        DoclingNotAvailableError: If docling-core is not installed.

    """
    if not DOCLING_AVAILABLE:
        raise DoclingNotAvailableError


__all__ = [
    "DOCLING_AVAILABLE",
    "DoclingDocument",
    "DoclingNotAvailableError",
    "require_docling",
]
