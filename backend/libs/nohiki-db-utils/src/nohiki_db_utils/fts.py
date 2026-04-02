"""Full-text search utilities for PostgreSQL."""

from __future__ import annotations

import re

# Matches alphanumeric tokens (words/numbers) from raw user input
_TERM_PATTERN = re.compile(r"[a-zA-Z0-9]+")


def build_prefix_tsquery(raw_query: str) -> str:
    """Build a prefix-matching tsquery string from raw user input.

    Sanitizes input by extracting only alphanumeric tokens, then appends
    the `:*` prefix-match operator to each term. Terms are joined with `&`
    (AND) so all terms must match.

    Args:
        raw_query: Raw search string from user input.

    Returns:
        A tsquery-compatible string like ``"python:* & kube:*"``,
        or an empty string if no valid terms are found.

    """
    terms = _TERM_PATTERN.findall(raw_query)
    if not terms:
        return ""
    return " & ".join(f"{term}:*" for term in terms)
