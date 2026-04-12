"""JSON Schema validation utilities.

Provides schema validation with caching for improved performance.
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from jsonschema import Draft7Validator
from jsonschema.exceptions import SchemaError, ValidationError

from doc_template_service.schemas.models import ValidationIssue

if TYPE_CHECKING:
    from doc_template_service.core.validation.models import ValidationResult

SCHEMA_CACHE_NAME = "schema_cache"


@lru_cache(maxsize=128)
def _get_cached_validator(_schema_hash: str, schema_json: str) -> Draft7Validator:
    """Get a cached validator. Hash param is for cache key uniqueness only."""
    return Draft7Validator(json.loads(schema_json))


def get_schema_validator(schema: dict[str, Any]) -> Draft7Validator:
    """Get a validator cached by immutable schema content.

    Caching by ``id(schema)`` is unsafe because schemas are mutable and object
    IDs are reused after garbage collection.

    Args:
        schema: JSON Schema dict

    Returns:
        Draft7Validator instance for the schema (cached)

    """
    schema_json = json.dumps(schema, sort_keys=True)
    schema_hash = hashlib.sha256(schema_json.encode()).hexdigest()
    return _get_cached_validator(schema_hash, schema_json)


def validate_data_against_schema(
    data: dict[str, Any],
    schema: dict[str, Any],
    result: ValidationResult,
) -> None:
    """Validate the data against the JSON Schema.

    Args:
        data: Data to validate
        schema: JSON Schema to validate against
        result: Result object to populate with issues

    """
    try:
        validator = get_schema_validator(schema)

        errors = list(validator.iter_errors(data))
        if errors:
            result.valid = False
            for error in errors:
                path = "/".join(str(p) for p in error.path) if error.path else "$"
                result.issues.append(
                    ValidationIssue(
                        path=path,
                        keyword=error.validator,
                        message=error.message,
                    )
                )
    except SchemaError as e:
        result.valid = False
        result.issues.append(
            ValidationIssue(
                path="$",
                keyword="schema_error",
                message=f"Schema error: {e}",
            )
        )
    except ValidationError as e:
        result.valid = False
        result.issues.append(
            ValidationIssue(
                path="$",
                keyword="validation_error",
                message=f"Validation error: {e}",
            )
        )
    except (ValueError, TypeError) as e:
        result.valid = False
        result.issues.append(
            ValidationIssue(
                path="$",
                keyword="data_error",
                message=f"Data error: {e}",
            )
        )
