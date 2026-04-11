"""Document processing service for ECST event-driven architecture."""

from nohiki.doc.process.v1 import ProcessedDocumentSnapshot, ProcessingLevel

from doc_process_service.cache import compute_content_hash
from doc_process_service.core.config import Settings, get_settings
from doc_process_service.core.exceptions import (
    ContentNotFoundError,
    DocProcessError,
    DocumentNotFoundError,
    ProcessingTimeoutError,
    ProviderNotInstalledError,
    ProviderUnavailableError,
)
from doc_process_service.models.domain import ProcessingOptions, ProcessingResult
from doc_process_service.services.processing import ProcessingService

__all__ = [
    "ContentNotFoundError",
    "DocProcessError",
    "DocumentNotFoundError",
    "ProcessedDocumentSnapshot",
    "ProcessingLevel",
    "ProcessingOptions",
    "ProcessingResult",
    "ProcessingService",
    "ProcessingTimeoutError",
    "ProviderNotInstalledError",
    "ProviderUnavailableError",
    "Settings",
    "compute_content_hash",
    "get_settings",
]
