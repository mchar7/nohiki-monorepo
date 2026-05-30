"""Validation helpers and regex patterns for model fields."""

from __future__ import annotations

import re
from typing import Final

from nohiki_scaffold.config import constants
from nohiki_scaffold.core.exceptions import ValidationError

# Naming patterns
_NAME_REGEX: Final[re.Pattern[str]] = re.compile(constants.SERVICE_NAME_PATTERN)
_LIB_NAME_REGEX: Final[re.Pattern[str]] = re.compile(constants.LIB_NAME_PATTERN)
_OWNER_REGEX: Final[re.Pattern[str]] = re.compile(constants.OWNER_PATTERN)
_SCHEMA_REGEX: Final[re.Pattern[str]] = re.compile(constants.SCHEMA_NAME_PATTERN)
_ENV_PREFIX_REGEX: Final[re.Pattern[str]] = re.compile(constants.ENV_PREFIX_PATTERN)

# Service concurrency bounds
_MIN_CONCURRENT: Final[int] = 1
_MAX_CONCURRENT: Final[int] = 200

# S3, LLM, environment variable patterns
_BUCKET_REGEX: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
_KEY_PREFIX_REGEX: Final[re.Pattern[str]] = re.compile(r"^[a-zA-Z0-9_\-./]{1,128}$")
_ENV_VAR_REGEX: Final[re.Pattern[str]] = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_LLM_PROVIDER_REGEX: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
_LLM_MODEL_REGEX: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_./:\-]{0,127}$")

# Qdrant entities
_QDRANT_ENTITIES: Final[frozenset[str]] = frozenset({"jobs", "profiles", "skills", "occupations"})


def validate_name(value: str) -> None:
    """Raise ValidationError if service name does not match pattern."""
    if not _NAME_REGEX.fullmatch(value):
        msg = f"Invalid service name {value!r}: must match {constants.SERVICE_NAME_PATTERN}"
        raise ValidationError(msg)


def validate_lib_name(value: str) -> None:
    """Raise ValidationError if lib name does not match pattern."""
    if not _LIB_NAME_REGEX.fullmatch(value):
        msg = f"Invalid lib name {value!r}: must match {constants.LIB_NAME_PATTERN}"
        raise ValidationError(msg)


def validate_owner(value: str) -> None:
    """Raise ValidationError if owner does not match pattern."""
    if not _OWNER_REGEX.fullmatch(value):
        msg = f"Invalid owner {value!r}: must match {constants.OWNER_PATTERN}"
        raise ValidationError(msg)


def validate_schema_name(value: str) -> None:
    """Raise ValidationError if schema name does not match pattern."""
    if not _SCHEMA_REGEX.fullmatch(value):
        msg = f"Invalid schema_name {value!r}: must match {constants.SCHEMA_NAME_PATTERN}"
        raise ValidationError(msg)


def validate_env_prefix(value: str) -> None:
    """Raise ValidationError if env_prefix does not match pattern."""
    if not _ENV_PREFIX_REGEX.fullmatch(value):
        msg = f"Invalid env_prefix {value!r}: must match {constants.ENV_PREFIX_PATTERN}"
        raise ValidationError(msg)


def validate_bucket_name(value: str) -> None:
    """Raise ValidationError if S3 bucket name does not match AWS rules."""
    if not _BUCKET_REGEX.fullmatch(value):
        msg = f"Invalid s3.bucket_name {value!r}: must match {_BUCKET_REGEX.pattern} (S3 naming rules)"
        raise ValidationError(msg)


def validate_key_prefix(value: str) -> None:
    """Raise ValidationError if S3 key_prefix does not match pattern."""
    if not _KEY_PREFIX_REGEX.fullmatch(value):
        msg = f"Invalid s3.key_prefix {value!r}: must match {_KEY_PREFIX_REGEX.pattern}"
        raise ValidationError(msg)


def validate_llm_provider(value: str) -> None:
    """Raise ValidationError if LLM provider does not match pattern."""
    if not _LLM_PROVIDER_REGEX.fullmatch(value):
        msg = f"Invalid llm.provider {value!r}: must match {_LLM_PROVIDER_REGEX.pattern}"
        raise ValidationError(msg)


def validate_llm_model(value: str) -> None:
    """Raise ValidationError if LLM model does not match pattern."""
    if not _LLM_MODEL_REGEX.fullmatch(value):
        msg = f"Invalid llm.model {value!r}: must match {_LLM_MODEL_REGEX.pattern}"
        raise ValidationError(msg)


def validate_env_var_name(value: str) -> None:
    """Raise ValidationError if environment variable name does not match pattern."""
    if not _ENV_VAR_REGEX.fullmatch(value):
        msg = f"Invalid llm.api_key_env {value!r}: must match {_ENV_VAR_REGEX.pattern}"
        raise ValidationError(msg)


def validate_qdrant_entity(value: str) -> None:
    """Raise ValidationError if Qdrant entity is not in canonical set."""
    if value not in _QDRANT_ENTITIES:
        msg = f"Invalid qdrant.collection_entity {value!r}: must be one of {sorted(_QDRANT_ENTITIES)}"
        raise ValidationError(msg)


def validate_max_concurrent_handlers(value: int) -> None:
    """Raise ValidationError if max_concurrent_handlers is out of bounds."""
    if not _MIN_CONCURRENT <= value <= _MAX_CONCURRENT:
        msg = f"kafka.max_concurrent_handlers={value} must be between {_MIN_CONCURRENT} and {_MAX_CONCURRENT}"
        raise ValidationError(msg)


def validate_description(value: str) -> None:
    """Raise ValidationError if description exceeds max length or contains control chars."""
    if len(value) > constants.MAX_DESCRIPTION_LEN:
        msg = f"description exceeds {constants.MAX_DESCRIPTION_LEN} chars"
        raise ValidationError(msg)
    # Reject control characters (all in range U+0000 to U+000F except tab/LF/CR)
    if any(ch in value for ch in "\x00\x01\x02\x03\x04\x05\x06\x07\x08\x0b\x0c\x0e\x0f"):
        msg = "description contains control characters"
        raise ValidationError(msg)
