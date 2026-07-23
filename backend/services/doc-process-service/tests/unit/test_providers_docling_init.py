"""Tests for deferred Docling provider imports."""

from __future__ import annotations

import subprocess
import sys


def test_main_defers_docling_core_until_type_access() -> None:
    """Main import keeps Docling types unloaded while lazy exports still resolve."""
    script = """
import sys
import doc_process_service.main

assert not any(name == "docling_core" or name.startswith("docling_core.") for name in sys.modules)

import doc_process_service.providers.docling as docling

assert docling.DoclingClient.__name__ == "DoclingClient"
assert "doc_process_service.providers.docling.client" in sys.modules
assert not any(name == "docling_core" or name.startswith("docling_core.") for name in sys.modules)

assert docling.DoclingDocument is not None
assert "docling_core.types.doc" in sys.modules
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


def test_lazy_exports_preserve_missing_docling_fallback() -> None:
    """Lazy type access preserves the optional-dependency error contract."""
    script = """
import builtins

real_import = builtins.__import__

def import_without_docling(name, *args, **kwargs):
    if name == "docling_core" or name.startswith("docling_core."):
        raise ImportError("simulated missing docling-core")
    return real_import(name, *args, **kwargs)

builtins.__import__ = import_without_docling

import doc_process_service.providers.docling as docling

assert docling.DOCLING_AVAILABLE is False
assert docling.DoclingDocument is None

try:
    docling.require_docling()
except docling.DoclingNotAvailableError as exc:
    assert str(exc) == (
        "docling-core is required for document processing. "
        "Install with: pip install doc-process-service[docling]"
    )
else:
    raise AssertionError("require_docling() did not raise DoclingNotAvailableError")
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
