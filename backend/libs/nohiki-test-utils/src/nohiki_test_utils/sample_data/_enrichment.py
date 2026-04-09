"""Enrichment simulation transform factories for RawJobPosting."""

from __future__ import annotations

import re

from nohiki_test_utils.sample_data._types import TransformFn

_HTML_ENTITIES: tuple[tuple[str, str], ...] = (
    ("&amp;", "&"),
    ("&lt;", "<"),
    ("&gt;", ">"),
    ("&nbsp;", " "),
    ("&#39;", "'"),
    ("&#x27;", "'"),
    ("&quot;", '"'),
    ("&#43;", "+"),
)

_UNICODE_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("\u2019", "'"),
    ("\u2018", "'"),
    ("\u201c", '"'),
    ("\u201d", '"'),
    ("\u2013", "-"),
    ("\u2014", "--"),
    ("\u00a0", " "),
)


def strip_paragraphs_containing(*markers: str) -> TransformFn:
    """Return a transform that removes paragraphs containing any of the given substrings.

    Paragraphs are delimited by two or more consecutive newlines. Any paragraph
    whose text contains one of the given markers (case-insensitive) is dropped.
    This is how the LLM enrichment step strips boilerplate such as EEO statements.

    Args:
        *markers: Case-insensitive substrings. Paragraphs containing any of these
            are removed entirely.

    Returns:
        A transform function that strips matching paragraphs from the text.
    """
    lowered = tuple(m.lower() for m in markers)

    def _transform(text: str) -> str:
        paragraphs = re.split(r"\n{2,}", text)
        return "\n\n".join(p for p in paragraphs if not any(marker in p.lower() for marker in lowered))

    return _transform


def strip_html_tags() -> TransformFn:
    """Return a transform that strips HTML tags and decodes common HTML entities.

    Simulates the formatting cleanup the enrichment LLM applies to postings
    scraped from job boards that inject HTML markup into listing descriptions.

    Returns:
        A transform function that removes HTML markup and normalizes entities.
    """

    def _transform(text: str) -> str:
        result = re.sub(r"<[^>]+>", "", text)
        for entity, replacement in _HTML_ENTITIES:
            result = result.replace(entity, replacement)
        return result

    return _transform


def fix_unicode_artifacts() -> TransformFn:
    """Return a transform that replaces common unicode artifacts with ASCII equivalents.

    Simulates the artifact cleanup the enrichment LLM applies to postings
    that contain typographic unicode characters from word processors or CMS exports.

    Returns:
        A transform function that normalizes unicode artifact characters.
    """

    def _transform(text: str) -> str:
        result = text
        for original, replacement in _UNICODE_REPLACEMENTS:
            result = result.replace(original, replacement)
        return result

    return _transform


def replace_text(old: str, new: str = "") -> TransformFn:
    """Return a transform that replaces all occurrences of a substring.

    Args:
        old: Substring to find and replace.
        new: Replacement string. Defaults to empty string (deletion).

    Returns:
        A transform function that performs the substitution.
    """

    def _transform(text: str) -> str:
        return text.replace(old, new)

    return _transform


STRIP_EEO: TransformFn = strip_paragraphs_containing("equal opportunity")

__all__ = [
    "STRIP_EEO",
    "fix_unicode_artifacts",
    "replace_text",
    "strip_html_tags",
    "strip_paragraphs_containing",
]
