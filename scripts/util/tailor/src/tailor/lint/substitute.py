"""``{{ var }}`` substitution for rule params.

Substitution is performed **after** YAML parsing and **before** the rule's
``PARAMS_MODEL`` validates the final dict. Rule classes declare which of their
param fields accept substitution via ``SUBSTITUTABLE_PARAMS: ClassVar[frozenset[str]]``.

Only top-level string params are substituted; nested dicts/lists are not
recursed into. This keeps substitution rules predictable for YAML authors.

A missing variable raises ``LintConfigError`` (no silent ``""`` fallback)
because a blank regex / target would cause confusing false positives at rule
runtime.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from tailor.exceptions import LintConfigError

# ``{{ varname }}`` with optional whitespace. Double-braces only: single
# braces stay literal so rules can still contain e.g. f-string-like text.
_VAR_PATTERN = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


def substitute_string(value: str, variables: Mapping[str, str], *, context: str) -> str:
    """Expand all ``{{ var }}`` references in ``value`` against ``variables``.

    Args:
        value: Param string value (may contain zero or more placeholders).
        variables: Variable map from ``runtime.variables``.
        context: Human-readable locator (e.g. ``"rule_id=foo param=target"``)
            included in missing-variable error messages.

    Returns:
        The fully-expanded string. No placeholders remain.

    Raises:
        LintConfigError: A referenced variable is absent from ``variables``.
    """

    def _replace(match: re.Match[str]) -> str:
        var_name = match.group(1)
        if var_name not in variables:
            msg = f"Unknown variable {{{{ {var_name} }}}} in {context} (available: {sorted(variables)})"
            raise LintConfigError(msg)
        return variables[var_name]

    return _VAR_PATTERN.sub(_replace, value)


def substitute_params(
    params: Mapping[str, object],
    substitutable_fields: frozenset[str],
    variables: Mapping[str, str],
    *,
    rule_id: str,
) -> dict[str, object]:
    """Apply ``{{ var }}`` substitution to the declared subset of param fields.

    Returns a shallow copy of ``params`` with the specified string fields
    expanded. Non-string values for substitutable fields pass through
    untouched (a later Pydantic validation will flag the type error). Fields
    not in ``substitutable_fields`` are copied verbatim.

    Args:
        params: Raw params dict from YAML.
        substitutable_fields: Field names the rule declared as substitutable.
        variables: Variable map from ``runtime.variables``.
        rule_id: Used for diagnostic error messages.

    Returns:
        New dict with substitutions applied.

    Raises:
        LintConfigError: A ``{{ var }}`` reference cannot be resolved.
    """
    if not substitutable_fields:
        return dict(params)

    # ``re.Pattern.sub`` is already a no-op on no-match strings, so a separate
    # ``.search()`` pre-check buys nothing. Just call ``substitute_string``.
    result: dict[str, object] = {}
    for key, value in params.items():
        if key in substitutable_fields and isinstance(value, str):
            result[key] = substitute_string(value, variables, context=f"rule_id={rule_id!r} param={key!r}")
        else:
            result[key] = value
    return result
