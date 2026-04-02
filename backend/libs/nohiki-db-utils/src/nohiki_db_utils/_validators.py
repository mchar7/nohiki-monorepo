"""Defensive input validation for trusted-but-interpolated SQL fragments.

SQL parameterization cannot bind schema or table names; they must be
interpolated into the SQL string. Even though schemas come from trusted
application settings (not user input), validating them at the interpolation
boundary provides defense-in-depth against misconfiguration or future code
paths that might route untrusted data through these APIs.
"""

from __future__ import annotations

import re

# PostgreSQL unquoted identifier: letter or underscore, then alphanumerics/underscores.
# Conservative pattern, rejects quoted identifiers, dollar signs, and Unicode.
# Matches common-case schema names like "user_pref_schema", "bff_schema".
_SCHEMA_NAME_RE = re.compile(r"\A[a-zA-Z_][a-zA-Z0-9_]{0,62}\Z")


def validate_schema_name(schema: str) -> None:
    """Assert that `schema` is a safe SQL identifier fragment for interpolation.

    Args:
        schema: Candidate schema name to validate.

    Raises:
        ValueError: If `schema` is empty, too long, or contains characters
            outside the allowed identifier alphabet.

    """
    if not schema:
        msg = "schema name must be a non-empty string"
        raise ValueError(msg)
    if not _SCHEMA_NAME_RE.match(schema):
        msg = f"schema name {schema!r} is not a safe SQL identifier; must match [a-zA-Z_][a-zA-Z0-9_]{{0,62}}"
        raise ValueError(msg)
