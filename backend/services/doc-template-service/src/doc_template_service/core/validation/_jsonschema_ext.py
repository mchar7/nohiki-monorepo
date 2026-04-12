"""Enhanced JSON Schema validator with custom keywords and error reporting.

This module extends the JSON Schema Draft 2020-12 validator to add support for
custom keywords (x-label, x-order, x-ui-type, x-errorMessage) and enhanced
error reporting capabilities.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import TYPE_CHECKING, Any, cast

from jsonschema import Draft202012Validator
from jsonschema.validators import extend

if TYPE_CHECKING:
    from collections.abc import Iterator

    from jsonschema.exceptions import ValidationError

from doc_template_service.schemas.models import ValidationIssue

# Type aliases (PEP 695)
type ValidatorType = object  # Proper type for validator would be complex
type InstanceType = object  # Type for validated instances


# Custom keyword handlers (no-op validators)
def x_label_validator(
    _validator: ValidatorType, _x_label: str, _instance: InstanceType, _schema: dict[str, Any]
) -> Iterator[None]:
    """No-op validator for the x-label keyword."""
    # This is a no-op validator - it always passes
    yield from ()


def x_order_validator(
    _validator: ValidatorType, _x_order: int, _instance: InstanceType, _schema: dict[str, Any]
) -> Iterator[None]:
    """No-op validator for the x-order keyword."""
    # This is a no-op validator - it always passes
    yield from ()


def x_ui_type_validator(
    _validator: ValidatorType, _x_ui_type: str, _instance: InstanceType, _schema: dict[str, Any]
) -> Iterator[None]:
    """No-op validator for the x-ui-type keyword."""
    # This is a no-op validator - it always passes
    yield from ()


def x_error_message_validator(
    _validator: ValidatorType, _x_error_message: str, _instance: InstanceType, _schema: dict[str, Any]
) -> Iterator[None]:
    """No-op validator for the x-errorMessage keyword."""
    # This is a no-op validator - it always passes
    yield from ()


# Define custom keywords to extend the Draft 2020-12 validator
CUSTOM_KEYWORDS = {
    "x-label": x_label_validator,
    "x-order": x_order_validator,
    "x-ui-type": x_ui_type_validator,
    "x-errorMessage": x_error_message_validator,
}


# Extend the Draft202012Validator with our custom keywords
# jsonschema.validators.extend is untyped in stubs
ExtendedDraft2020Validator = extend(Draft202012Validator, CUSTOM_KEYWORDS)

# Ensure format validation is enabled
ExtendedDraft2020Validator.FORMAT_CHECKER = Draft202012Validator.FORMAT_CHECKER


class RichValidator:
    """Enhanced JSON Schema validator with custom keywords and error handling.

    This validator wraps the JSON Schema Draft 2020-12 validator to add support for:
    - Custom UI keywords (x-label, x-order, x-ui-type) as no-op validators
    - Custom error messages via the x-errorMessage keyword
    - Schema caching for improved performance
    - Enhanced error reporting with accurate JSON paths
    """

    def __init__(
        self,
        schema: dict[str, Any],
        *_args: object,
        **_kwargs: object,
    ) -> None:
        """Initialize the RichValidator with the given schema.

        Args:
            schema: The JSON schema to validate against
            *_args: Additional positional arguments (ignored)
            **_kwargs: Additional keyword arguments (ignored)

        """
        self.schema = schema
        self.validator = ExtendedDraft2020Validator(schema, format_checker=ExtendedDraft2020Validator.FORMAT_CHECKER)

    def iter_errors(self, instance: object) -> Iterator[ValidationError]:
        """Iterate through validation errors.

        Args:
            instance: The instance to validate

        Returns:
            Iterator of ValidationError objects

        """
        return cast("Iterator[ValidationError]", self.validator.iter_errors(instance))

    def validate(self, instance: object) -> None:
        """Validate an instance against the schema.

        Args:
            instance: The instance to validate

        Raises:
            ValidationError: If the instance is invalid

        """
        errors = list(self.iter_errors(instance))
        if errors:
            raise errors[0]

    def is_valid(self, instance: object) -> bool:
        """Check if an instance is valid against the schema.

        Args:
            instance: The instance to validate

        Returns:
            True if the instance is valid, False otherwise

        """
        return bool(self.validator.is_valid(instance))

    def iter_errors_with_paths(self, instance: object) -> list[tuple[list[str | int], ValidationError]]:
        """Iterate through validation errors with their JSON paths.

        Args:
            instance: The instance to validate

        Returns:
            List of tuples containing (json_path, validation_error)

        """
        errors_with_paths: list[tuple[list[str | int], ValidationError]] = []

        for error in self.iter_errors(instance):
            # Build the JSON path from the error's path
            path_parts: list[str] = []
            for path_part in error.path:
                if isinstance(path_part, int):
                    path_parts.append(f"[{path_part}]")
                elif path_parts:
                    path_parts.append(f".{path_part}")
                else:
                    path_parts.append(f"{path_part}")

            # Store the error with its path (path contains str | int)
            errors_with_paths.append((list(error.path), error))

        return errors_with_paths

    def get_error_message(self, error: ValidationError) -> str:
        """Get the error message for a validation error, with x-errorMessage override support.

        Args:
            error: The validation error

        Returns:
            The error message, possibly overridden by x-errorMessage

        """
        # Check if there's an x-errorMessage in the schema related to this error
        schema_path: list[str | int] = list(error.schema_path)

        # Remove the last element if it's the validation keyword
        validator_str = str(error.validator) if error.validator else ""
        if schema_path and any(validator_str == str(p) for p in schema_path):
            schema_path = schema_path[:-1]

        # Try to find the x-errorMessage in the schema
        current_schema: dict[str, Any] = self.schema
        try:
            # Navigate to the relevant schema node
            for path_element in schema_path:
                str_key = str(path_element)
                if isinstance(current_schema, dict) and str_key in current_schema:
                    current_schema = cast("dict[str, Any]", current_schema[str_key])
                else:
                    # Path doesn't exist in schema
                    break

            # Check if the current schema node has an x-errorMessage
            if isinstance(current_schema, dict) and "x-errorMessage" in current_schema:
                return str(current_schema["x-errorMessage"])
        except KeyError, TypeError, IndexError:
            pass

        # If no custom message found, return the original error message
        return error.message

    def create_validation_issues(self, instance: object) -> list[ValidationIssue]:
        """Validate an instance and create ValidationIssue objects for any errors.

        Args:
            instance: The instance to validate

        Returns:
            List of ValidationIssue objects

        """
        issues = []

        for path, error in self.iter_errors_with_paths(instance):
            # Create a JSON path string (e.g., "$.person.name" or "$.items[3].title")
            json_path = "$"
            for i, path_part in enumerate(path):
                if isinstance(path_part, int):
                    json_path += f"[{path_part}]"
                elif i > 0 or path_part:  # Skip empty first segment
                    json_path += f".{path_part}"

            # Get the message (with possible x-errorMessage override)
            message = self.get_error_message(error)

            # Create the ValidationIssue
            # Get keyword - validator can be str or None
            keyword = str(error.validator) if error.validator else "unknown"
            issue = ValidationIssue(
                path=json_path,
                keyword=keyword,
                message=message,
            )
            issues.append(issue)

        return issues


@lru_cache(maxsize=128)
def _get_cached_validator_sync(schema_str: str) -> RichValidator:
    """Get a cached validator instance for the given schema string (sync)."""
    schema: dict[str, Any] = json.loads(schema_str)
    return RichValidator(schema)


async def get_cached_validator(schema_str: str) -> RichValidator:
    """Get a cached validator instance for the given schema string (async wrapper)."""
    return _get_cached_validator_sync(schema_str)


def get_validator(schema: dict[str, Any]) -> RichValidator:
    """Get a validator instance for the given schema, using caching.

    Args:
        schema: JSON schema as a dictionary

    Returns:
        A RichValidator instance for the schema

    """
    # Convert schema to a canonical string representation for caching
    schema_str = json.dumps(schema, sort_keys=True)
    return _get_cached_validator_sync(schema_str)


def validate_data(schema: dict[str, Any], data: object) -> list[ValidationIssue]:
    """Validate data against a schema and return any validation issues.

    Args:
        schema: JSON schema to validate against
        data: Data to validate

    Returns:
        List of ValidationIssue objects for any validation errors

    """
    validator = get_validator(schema)
    return validator.create_validation_issues(data)
