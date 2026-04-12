"""Tests for doc_process_service.providers.docling.types module."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from doc_process_service.providers.docling.types import (
    DOCLING_AVAILABLE,
    DoclingDocument,
    DoclingNotAvailableError,
    require_docling,
)


class TestDoclingAvailability:
    """Tests for docling availability checks."""

    def test_docling_available_flag(self) -> None:
        """Test DOCLING_AVAILABLE reflects docling-core installation."""
        assert isinstance(DOCLING_AVAILABLE, bool)

    def test_docling_document_type(self) -> None:
        """Test DoclingDocument is available when docling-core is installed."""
        if DOCLING_AVAILABLE:
            assert DoclingDocument is not None
        else:
            assert DoclingDocument is None


class TestDoclingNotAvailableError:
    """Tests for DoclingNotAvailableError exception."""

    def test_error_message_content(self) -> None:
        """Test error message contains installation hint."""
        error = DoclingNotAvailableError()
        message = str(error)

        assert "docling-core is required" in message
        assert "pip install" in message


class TestRequireDocling:
    """Tests for require_docling function."""

    def test_require_docling_passes_when_available(self) -> None:
        """Test require_docling does nothing when docling is available."""
        if DOCLING_AVAILABLE:
            require_docling()

    def test_require_docling_raises_when_unavailable(self) -> None:
        """Test require_docling raises error when docling is unavailable."""
        if not DOCLING_AVAILABLE:
            with pytest.raises(DoclingNotAvailableError):
                require_docling()


class TestImportErrorPath:
    """Tests for ImportError handling when docling-core is not installed."""

    def test_docling_document_is_none_when_import_fails(self) -> None:
        """Test DoclingDocument is None when docling-core import fails."""
        # This test simulates the ImportError path by checking if we're in the
        # condition where docling is not available
        if not DOCLING_AVAILABLE:
            assert DoclingDocument is None

    def test_require_docling_raises_when_docling_unavailable(self) -> None:
        """Test require_docling raises DoclingNotAvailableError."""
        if not DOCLING_AVAILABLE:
            with pytest.raises(DoclingNotAvailableError) as exc_info:
                require_docling()

            assert "docling-core is required" in str(exc_info.value)
            assert "pip install" in str(exc_info.value)

    @patch("doc_process_service.providers.docling.types.DOCLING_AVAILABLE", new=False)
    def test_require_docling_with_mocked_unavailability(self) -> None:
        """Test require_docling raises when DOCLING_AVAILABLE is False."""
        with pytest.raises(DoclingNotAvailableError):
            require_docling()

    def test_import_error_path_coverage(self) -> None:
        """Test ImportError path by mocking the import to fail."""
        import sys

        # Remove the module if already imported
        module_name = "doc_process_service.providers.docling.types"
        if module_name in sys.modules:
            del sys.modules[module_name]

        # Mock the docling_core import to fail
        with patch.dict("sys.modules", {"docling_core.types.doc": None}):
            # Force reimport which will trigger the ImportError path
            import doc_process_service.providers.docling.types as types_module

            assert types_module.DOCLING_AVAILABLE is False
            assert types_module.DoclingDocument is None
