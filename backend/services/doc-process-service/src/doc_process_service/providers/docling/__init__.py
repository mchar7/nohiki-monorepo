"""Docling Serve processing provider."""

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from doc_process_service.providers.docling.client import DoclingClient as DoclingClient
    from doc_process_service.providers.docling.config import DoclingClientConfig as DoclingClientConfig
    from doc_process_service.providers.docling.types import DOCLING_AVAILABLE as DOCLING_AVAILABLE
    from doc_process_service.providers.docling.types import DoclingDocument as DoclingDocument
    from doc_process_service.providers.docling.types import DoclingNotAvailableError as DoclingNotAvailableError
    from doc_process_service.providers.docling.types import require_docling as require_docling

__all__ = [
    "DOCLING_AVAILABLE",
    "DoclingClient",
    "DoclingClientConfig",
    "DoclingDocument",
    "DoclingNotAvailableError",
    "require_docling",
]

_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "DoclingClient": ("doc_process_service.providers.docling.client", "DoclingClient"),
    "DoclingClientConfig": ("doc_process_service.providers.docling.config", "DoclingClientConfig"),
    "DOCLING_AVAILABLE": ("doc_process_service.providers.docling.types", "DOCLING_AVAILABLE"),
    "DoclingDocument": ("doc_process_service.providers.docling.types", "DoclingDocument"),
    "DoclingNotAvailableError": ("doc_process_service.providers.docling.types", "DoclingNotAvailableError"),
    "require_docling": ("doc_process_service.providers.docling.types", "require_docling"),
}


def __getattr__(name: str) -> object:
    """Lazy-import Docling provider components (PEP 562)."""
    if name in _LAZY_IMPORTS:
        module_path, attr_name = _LAZY_IMPORTS[name]
        module = importlib.import_module(module_path)
        return getattr(module, attr_name)
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
