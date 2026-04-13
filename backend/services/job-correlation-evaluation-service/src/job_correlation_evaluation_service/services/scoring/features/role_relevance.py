"""Deterministic role identity matching for title relevance."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nohiki.job.listing.v1 import ListingSnapshot
    from nohiki.user.pref.v1 import SearchPrefSnapshot

_MIN_ROLE_TOKENS = 2

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
_TITLE_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "at",
        "for",
        "in",
        "of",
        "on",
        "or",
        "the",
        "to",
        "with",
        "all",
        "level",
        "levels",
    }
)
_SENIORITY_TOKENS = frozenset(
    {
        "associate",
        "chief",
        "director",
        "entry",
        "executive",
        "intern",
        "junior",
        "lead",
        "manager",
        "mid",
        "principal",
        "senior",
        "staff",
        "vp",
    }
)


def role_relevance(listing: ListingSnapshot, profile: SearchPrefSnapshot) -> float | None:
    """Return bounded title-role compatibility, or ``None`` without role input.

    Search discovery terms preserve the user's primary role phrase first. The
    first normalized multi-token term is therefore role identity; later terms
    remain skills for semantic and skill factors. ``pref_name`` is only a
    legacy fallback when no role-shaped search term exists.
    """
    role_text = _first_role_phrase(getattr(profile, "search_keywords", ()))
    if role_text is None:
        candidate = getattr(profile, "pref_name", None)
        role_text = candidate if isinstance(candidate, str) else None
    role_tokens = _identity_tokens(role_text or "")
    title = getattr(listing, "title", None)
    title_tokens = _identity_tokens(title if isinstance(title, str) else "")
    if not role_tokens or not title_tokens:
        return None

    role_set = set(role_tokens)
    title_set = set(title_tokens)
    overlap = len(role_set & title_set)
    if overlap == 0:
        return 0.0

    coverage = overlap / len(role_set)
    precision = overlap / len(title_set)
    if _contains_sequence(title_tokens, role_tokens):
        return 1.0
    return max(0.0, min(1.0, 0.75 * coverage + 0.25 * precision))


def _first_role_phrase(keywords: Iterable[object]) -> str | None:
    """Return the first string search term with at least two identity tokens."""
    if isinstance(keywords, str):
        return None
    try:
        iterator = iter(keywords)
    except TypeError:
        return None
    for keyword in iterator:
        if isinstance(keyword, str) and len(_identity_tokens(keyword)) >= _MIN_ROLE_TOKENS:
            return keyword
    return None


def _identity_tokens(text: str) -> tuple[str, ...]:
    """Tokenize and drop generic title/seniority words."""
    if not isinstance(text, str):
        return ()
    return tuple(
        token
        for token in _TOKEN_PATTERN.findall(text.lower())
        if token not in _TITLE_STOPWORDS and token not in _SENIORITY_TOKENS
    )


def _contains_sequence(haystack: tuple[str, ...], needle: tuple[str, ...]) -> bool:
    """Return whether an ordered role phrase occurs in title identity tokens."""
    width = len(needle)
    return any(haystack[index : index + width] == needle for index in range(len(haystack) - width + 1))


__all__ = ["role_relevance"]
