"""Semantic version validation and comparison utilities."""

import re

import semver
from nohiki_observability import get_logger

logger = get_logger(__name__)

# Semantic version regex pattern (SemVer 2.0.0)
SEMVER_PATTERN = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(-[0-9A-Za-z\-\.]+)?(\+[0-9A-Za-z\-\.]+)?$")


class SemanticVersionError(ValueError):
    """Exception raised for semantic version validation errors."""

    def __init__(self, version: str, message: str) -> None:
        """Initialize the exception with version and message details."""
        self.version = version
        error_msg = f"Invalid semantic version '{version}': {message}"
        super().__init__(error_msg)


def validate_semantic_version(version: str) -> str:
    """Validate that a version string conforms to semantic versioning.

    Args:
        version: Version string to validate

    Returns:
        The validated version string (normalized)

    Raises:
        SemanticVersionError: If the version is invalid

    """
    if not version or not isinstance(version, str):
        raise SemanticVersionError(version, "Version must be a non-empty string")

    # Check basic format with regex
    if not SEMVER_PATTERN.match(version):
        raise SemanticVersionError(
            version, "Must follow semantic versioning format: MAJOR.MINOR.PATCH[-prerelease][+build]"
        )

    try:
        # Use semver library for thorough validation
        parsed = semver.Version.parse(version)
        return str(parsed)
    except ValueError as e:
        raise SemanticVersionError(version, str(e)) from e


def is_version_greater(new_version: str, current_version: str) -> bool:
    """Check if new_version is semantically greater than current_version.

    Args:
        new_version: The new version to compare
        current_version: The current version to compare against

    Returns:
        True if new_version > current_version, False otherwise

    Raises:
        SemanticVersionError: If either version is invalid

    """
    validated_new = validate_semantic_version(new_version)
    validated_current = validate_semantic_version(current_version)

    try:
        new_ver = semver.Version.parse(validated_new)
        current_ver = semver.Version.parse(validated_current)

        result = new_ver > current_ver

        logger.debug(
            "Version comparison",
            new_version=validated_new,
            current_version=validated_current,
            is_greater=result,
        )

    except ValueError as e:
        comparison_key = f"{new_version} vs {current_version}"
        raise SemanticVersionError(comparison_key, str(e)) from e
    else:
        return result


def compare_versions(version1: str, version2: str) -> int:
    """Compare two semantic versions.

    Args:
        version1: First version to compare
        version2: Second version to compare

    Returns:
        -1 if version1 < version2
         0 if version1 == version2
         1 if version1 > version2

    Raises:
        SemanticVersionError: If either version is invalid

    """
    validated_v1 = validate_semantic_version(version1)
    validated_v2 = validate_semantic_version(version2)

    try:
        v1 = semver.Version.parse(validated_v1)
        v2 = semver.Version.parse(validated_v2)

        if v1 < v2:
            result = -1
        elif v1 > v2:
            result = 1
        else:
            result = 0
    except ValueError as e:
        comparison_key = f"{version1} vs {version2}"
        raise SemanticVersionError(comparison_key, str(e)) from e
    else:
        return result
