"""JSON Schema validation utilities.

Provides schema validation with caching for improved performance.
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from itertools import islice
from typing import TYPE_CHECKING, Any

from jsonschema.exceptions import SchemaError, ValidationError
from jsonschema.protocols import Validator
from nohiki_domain_utils.json_schema import get_json_schema_validator
from referencing.exceptions import Unresolvable

from doc_template_service.schemas.models import ValidationIssue

if TYPE_CHECKING:
    from doc_template_service.core.validation.models import ValidationResult

SCHEMA_CACHE_NAME = "schema_cache"
_MAX_REPORTED_SCHEMA_ISSUES = 5


@lru_cache(maxsize=128)
def _get_cached_validator(_schema_hash: str, schema_json: str) -> Validator:
    """Get a cached validator. Hash param is for cache key uniqueness only."""
    schema: dict[str, Any] = json.loads(schema_json)
    return get_json_schema_validator(schema)


def get_schema_validator(schema: dict[str, Any]) -> Validator:
    """Get a validator cached by immutable schema content.

    Caching by ``id(schema)`` is unsafe because schemas are mutable and object
    IDs are reused after garbage collection.

    Args:
        schema: JSON Schema dict

    Returns:
        Validator for the schema's declared dialect, defaulting to Draft 2020-12.

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

        errors = iter(validator.iter_errors(data))
        for error in islice(errors, _MAX_REPORTED_SCHEMA_ISSUES):
            result.valid = False
            path = "/".join(str(p) for p in error.path) if error.path else "$"
            result.issues.append(
                ValidationIssue(
                    path=path,
                    keyword=str(error.validator),
                    message=error.message,
                )
            )
        if next(errors, None) is not None:
            result.issues.append(
                ValidationIssue(
                    path="$",
                    keyword="truncated",
                    message="Additional schema violations omitted",
                )
            )
    except (SchemaError, Unresolvable) as e:
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
