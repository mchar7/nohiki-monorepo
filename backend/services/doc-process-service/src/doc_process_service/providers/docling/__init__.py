"""Docling Serve processing provider."""

from doc_process_service.providers.docling.client import DoclingClient
from doc_process_service.providers.docling.config import DoclingClientConfig
from doc_process_service.providers.docling.types import (
    DOCLING_AVAILABLE,
    DoclingDocument,
    DoclingNotAvailableError,
    require_docling,
)

__all__ = [
    "DOCLING_AVAILABLE",
    "DoclingClient",
    "DoclingClientConfig",
    "DoclingDocument",
    "DoclingNotAvailableError",
    "require_docling",
]
