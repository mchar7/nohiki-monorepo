"""Tests for S3 exceptions."""

from __future__ import annotations

from nohiki_s3_client.exceptions import (
    S3ConnectionError,
    S3Error,
    S3ObjectNotFoundError,
    S3PermissionError,
)


class TestS3Error:
    """Tests for base S3Error."""

    def test_init_with_message_only(self) -> None:
        """Test S3Error with message only."""
        error = S3Error("Test error message")
        assert str(error) == "Test error message"
        assert error.key is None

    def test_init_with_key(self) -> None:
        """Test S3Error with message and key."""
        error = S3Error("Test error message", key="test/object.txt")
        assert str(error) == "Test error message"
        assert error.key == "test/object.txt"


class TestS3ObjectNotFoundError:
    """Tests for S3ObjectNotFoundError."""

    def test_init(self) -> None:
        """Test S3ObjectNotFoundError initialization."""
        error = S3ObjectNotFoundError("attachments/user-123/resume.pdf")
        assert "S3 object not found" in str(error)
        assert "attachments/user-123/resume.pdf" in str(error)
        assert error.key == "attachments/user-123/resume.pdf"

    def test_inherits_from_s3_error(self) -> None:
        """Test that S3ObjectNotFoundError inherits from S3Error."""
        error = S3ObjectNotFoundError("test-key")
        assert isinstance(error, S3Error)


class TestS3PermissionError:
    """Tests for S3PermissionError."""

    def test_init(self) -> None:
        """Test S3PermissionError initialization."""
        error = S3PermissionError("private/secret.txt")
        assert "Access denied" in str(error)
        assert "private/secret.txt" in str(error)
        assert error.key == "private/secret.txt"

    def test_inherits_from_s3_error(self) -> None:
        """Test that S3PermissionError inherits from S3Error."""
        error = S3PermissionError("test-key")
        assert isinstance(error, S3Error)


class TestS3ConnectionError:
    """Tests for S3ConnectionError."""

    def test_init(self) -> None:
        """Test S3ConnectionError initialization."""
        error = S3ConnectionError("Connection refused")
        assert "S3 connection error" in str(error)
        assert "Connection refused" in str(error)

    def test_inherits_from_s3_error(self) -> None:
        """Test that S3ConnectionError inherits from S3Error."""
        error = S3ConnectionError("timeout")
        assert isinstance(error, S3Error)

    def test_key_is_none(self) -> None:
        """Test that S3ConnectionError has no key."""
        error = S3ConnectionError("network error")
        assert error.key is None
