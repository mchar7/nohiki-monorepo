"""Shared JSON Schema dialect selection."""

from __future__ import annotations

from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.protocols import Validator
from jsonschema.validators import validator_for
from referencing import Registry

_NO_NETWORK_REGISTRY: Registry[Any] = Registry()


def get_json_schema_validator(schema: dict[str, Any]) -> Validator:
    """Return a meta-schema-checked validator for the declared dialect."""
    validator_class = validator_for(schema, default=Draft202012Validator)
    validator_class.check_schema(schema)
    return validator_class(schema, registry=_NO_NETWORK_REGISTRY)
