"""Core configuration and exceptions for document processing service."""

from doc_process_service.core.config import (
    CacheSettings,
    CircuitBreakerSettings,
    DoclingSettings,
    Settings,
    VLMSettings,
    get_settings,
)
from doc_process_service.core.exceptions import (
    ContentNotFoundError,
    DocProcessError,
    DocumentNotFoundError,
    ProcessingTimeoutError,
    ProviderNotInstalledError,
    ProviderUnavailableError,
)

__all__ = [
    "CacheSettings",
    "CircuitBreakerSettings",
    "ContentNotFoundError",
    "DocProcessError",
    "DoclingSettings",
    "DocumentNotFoundError",
    "ProcessingTimeoutError",
    "ProviderNotInstalledError",
    "ProviderUnavailableError",
    "Settings",
    "VLMSettings",
    "get_settings",
]
