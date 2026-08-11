"""Tests for semantic version validation utilities."""

from typing import cast

import pytest
from doc_template_service.core.semver_validation import (
    SemanticVersionError,
    compare_versions,
    is_version_greater,
    validate_semantic_version,
)


class TestValidateSemanticVersion:
    """Tests for validate_semantic_version function."""

    def test_valid_simple_version(self) -> None:
        """Test validation of simple semantic versions."""
        assert validate_semantic_version("1.0.0") == "1.0.0"
        assert validate_semantic_version("0.1.0") == "0.1.0"
        assert validate_semantic_version("10.20.30") == "10.20.30"

    def test_valid_prerelease_version(self) -> None:
        """Test validation of versions with prerelease identifiers."""
        assert validate_semantic_version("1.0.0-alpha") == "1.0.0-alpha"
        assert validate_semantic_version("1.0.0-alpha.1") == "1.0.0-alpha.1"
        assert validate_semantic_version("1.0.0-beta.2") == "1.0.0-beta.2"
        assert validate_semantic_version("1.0.0-rc.1") == "1.0.0-rc.1"

    def test_valid_build_metadata_version(self) -> None:
        """Test validation of versions with build metadata."""
        assert validate_semantic_version("1.0.0+build") == "1.0.0+build"
        assert validate_semantic_version("1.0.0+build.123") == "1.0.0+build.123"

    def test_valid_prerelease_with_build_metadata(self) -> None:
        """Test validation of versions with both prerelease and build metadata."""
        assert validate_semantic_version("1.0.0-alpha+build") == "1.0.0-alpha+build"
        assert validate_semantic_version("1.0.0-beta.1+build.456") == "1.0.0-beta.1+build.456"

    def test_empty_version_raises_error(self) -> None:
        """Test that empty version string raises SemanticVersionError."""
        with pytest.raises(SemanticVersionError, match="non-empty string"):
            validate_semantic_version("")

    def test_none_version_raises_error(self) -> None:
        """Test that None version raises SemanticVersionError."""
        with pytest.raises(SemanticVersionError):
            validate_semantic_version(cast("str", None))

    def test_invalid_format_raises_error(self) -> None:
        """Test that invalid version formats raise SemanticVersionError."""
        with pytest.raises(SemanticVersionError, match="semantic versioning format"):
            validate_semantic_version("1.0")

        with pytest.raises(SemanticVersionError, match="semantic versioning format"):
            validate_semantic_version("1")

        with pytest.raises(SemanticVersionError, match="semantic versioning format"):
            validate_semantic_version("v1.0.0")

        with pytest.raises(SemanticVersionError, match="semantic versioning format"):
            validate_semantic_version("1.0.0.0")

        with pytest.raises(SemanticVersionError, match="semantic versioning format"):
            validate_semantic_version("\u0661.\u0662.\u0663")

        with pytest.raises(SemanticVersionError, match="semantic versioning format"):
            validate_semantic_version("1.2.3-01")

        with pytest.raises(SemanticVersionError, match="semantic versioning format"):
            validate_semantic_version("1.2.3-alpha..1")

    def test_leading_zeros_raises_error(self) -> None:
        """Test that versions with leading zeros raise SemanticVersionError."""
        with pytest.raises(SemanticVersionError, match="semantic versioning format"):
            validate_semantic_version("01.0.0")

        with pytest.raises(SemanticVersionError, match="semantic versioning format"):
            validate_semantic_version("1.00.0")


class TestIsVersionGreater:
    """Tests for is_version_greater function."""

    def test_major_version_greater(self) -> None:
        """Test that higher major version is greater."""
        assert is_version_greater("2.0.0", "1.0.0") is True
        assert is_version_greater("1.0.0", "2.0.0") is False

    def test_minor_version_greater(self) -> None:
        """Test that higher minor version is greater."""
        assert is_version_greater("1.2.0", "1.1.0") is True
        assert is_version_greater("1.1.0", "1.2.0") is False

    def test_patch_version_greater(self) -> None:
        """Test that higher patch version is greater."""
        assert is_version_greater("1.0.2", "1.0.1") is True
        assert is_version_greater("1.0.1", "1.0.2") is False

    def test_equal_versions_not_greater(self) -> None:
        """Test that equal versions are not greater."""
        assert is_version_greater("1.0.0", "1.0.0") is False

    def test_prerelease_less_than_release(self) -> None:
        """Test that prerelease versions are less than release versions."""
        assert is_version_greater("1.0.0", "1.0.0-alpha") is True
        assert is_version_greater("1.0.0-alpha", "1.0.0") is False

    def test_invalid_version_raises_error(self) -> None:
        """Test that invalid versions raise SemanticVersionError."""
        with pytest.raises(SemanticVersionError):
            is_version_greater("invalid", "1.0.0")

        with pytest.raises(SemanticVersionError):
            is_version_greater("1.0.0", "invalid")


class TestCompareVersions:
    """Tests for compare_versions function."""

    def test_first_version_less(self) -> None:
        """Test comparison when first version is less."""
        assert compare_versions("1.0.0", "2.0.0") == -1
        assert compare_versions("1.0.0", "1.1.0") == -1
        assert compare_versions("1.0.0", "1.0.1") == -1

    def test_versions_equal(self) -> None:
        """Test comparison when versions are equal."""
        assert compare_versions("1.0.0", "1.0.0") == 0
        assert compare_versions("2.5.3", "2.5.3") == 0

    def test_first_version_greater(self) -> None:
        """Test comparison when first version is greater."""
        assert compare_versions("2.0.0", "1.0.0") == 1
        assert compare_versions("1.1.0", "1.0.0") == 1
        assert compare_versions("1.0.1", "1.0.0") == 1

    def test_prerelease_comparison(self) -> None:
        """Test comparison of prerelease versions."""
        assert compare_versions("1.0.0-alpha", "1.0.0") == -1
        assert compare_versions("1.0.0", "1.0.0-alpha") == 1
        assert compare_versions("1.0.0-alpha", "1.0.0-alpha") == 0

    def test_invalid_version_raises_error(self) -> None:
        """Test that invalid versions raise SemanticVersionError."""
        with pytest.raises(SemanticVersionError):
            compare_versions("invalid", "1.0.0")

        with pytest.raises(SemanticVersionError):
            compare_versions("1.0.0", "invalid")


class TestSemanticVersionErrorException:
    """Tests for SemanticVersionError exception class."""

    def test_exception_attributes(self) -> None:
        """Test that exception has correct attributes."""
        error = SemanticVersionError("1.0", "Invalid format")
        assert error.version == "1.0"
        assert "1.0" in str(error)
        assert "Invalid format" in str(error)

    def test_exception_message_format(self) -> None:
        """Test exception message format."""
        error = SemanticVersionError("bad", "test message")
        assert str(error) == "Invalid semantic version 'bad': test message"
