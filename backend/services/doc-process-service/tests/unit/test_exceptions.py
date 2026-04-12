"""Tests for doc_process_service.core.exceptions module."""

import pytest
from doc_process_service.core.exceptions import (
    ContentNotFoundError,
    DocProcessError,
    ProcessingTimeoutError,
    ProviderNotInstalledError,
    ProviderUnavailableError,
)
from nohiki_common_exceptions import NohikiError


class TestDocProcessError:
    """Tests for DocProcessError base exception."""

    def test_is_exception(self) -> None:
        """Test DocProcessError is an Exception."""
        assert issubclass(DocProcessError, Exception)

    def test_can_raise_with_message(self) -> None:
        """Test can raise with custom message."""
        error = DocProcessError("test error")
        assert str(error) == "test error"


class TestProviderUnavailableError:
    """Tests for ProviderUnavailableError."""

    def test_inherits_doc_process_error(self) -> None:
        """Test inherits from NohikiError (via ExternalServiceError)."""
        assert issubclass(ProviderUnavailableError, NohikiError)

    def test_message_format(self) -> None:
        """Test error message includes provider name."""
        error = ProviderUnavailableError("docling")

        assert "docling" in str(error)
        assert "unavailable" in str(error).lower()

    def test_provider_attribute(self) -> None:
        """Test provider attribute is set."""
        error = ProviderUnavailableError("docling")

        assert error.provider == "docling"


class TestProcessingTimeoutError:
    """Tests for ProcessingTimeoutError."""

    def test_inherits_doc_process_error(self) -> None:
        """Test inherits from NohikiError (via ExternalServiceError)."""
        assert issubclass(ProcessingTimeoutError, NohikiError)

    def test_message_format(self) -> None:
        """Test error message includes task_id and timeout."""
        error = ProcessingTimeoutError("task_123", 60.0)

        assert "task_123" in str(error)
        assert "60" in str(error)

    def test_attributes(self) -> None:
        """Test task_id and timeout_seconds attributes are set."""
        error = ProcessingTimeoutError("task_abc", 120.5)

        assert error.task_id == "task_abc"
        assert error.timeout_seconds == pytest.approx(120.5)


class TestContentNotFoundError:
    """Tests for ContentNotFoundError."""

    def test_inherits_doc_process_error(self) -> None:
        """Test inherits from NohikiError (via DataNotAvailableError)."""
        assert issubclass(ContentNotFoundError, NohikiError)

    def test_message_format(self) -> None:
        """Test error message includes content_id."""
        error = ContentNotFoundError("motor:tsb:123:456")

        assert "motor:tsb:123:456" in str(error)

    def test_content_id_attribute(self) -> None:
        """Test content_id attribute is set."""
        error = ContentNotFoundError("content_xyz")

        assert error.content_id == "content_xyz"


class TestProviderNotInstalledError:
    """Tests for ProviderNotInstalledError."""

    def test_inherits_doc_process_error(self) -> None:
        """Test inherits from DocProcessError."""
        assert issubclass(ProviderNotInstalledError, DocProcessError)

    def test_message_format(self) -> None:
        """Test error message includes provider and install hint."""
        error = ProviderNotInstalledError("docling", "pip install docling-core")

        assert "docling" in str(error)
        assert "pip install docling-core" in str(error)

    def test_attributes(self) -> None:
        """Test provider and install_hint attributes are set."""
        error = ProviderNotInstalledError("mypackage", "pip install mypackage")

        assert error.provider == "mypackage"
        assert error.install_hint == "pip install mypackage"
