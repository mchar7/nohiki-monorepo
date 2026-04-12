"""Text conversion utilities for document generation.

Provides HTML to plain text conversion and text sanitization.
"""

from __future__ import annotations

import re

import html2text

_html_to_text_converter = html2text.HTML2Text()
_html_to_text_converter.ignore_links = False
_html_to_text_converter.body_width = 0

_METADATA_COMMENT_RE = re.compile(r"<!--\s*TMPL_META.*?-->", flags=re.DOTALL)


def sanitize_text(text: str) -> str:
    """Sanitize generated output by removing template metadata and null characters.

    Args:
        text: Text to sanitize

    Returns:
        Sanitized text

    """
    if not text:
        return text

    text = _METADATA_COMMENT_RE.sub("", text)
    return text.replace("\x00", "")


def convert_html_to_text(html: str) -> str:
    """Convert HTML content to plain text using html2text.

    Args:
        html: HTML content to convert

    Returns:
        Plain text representation

    """
    plain_text = _html_to_text_converter.handle(html)
    return sanitize_text(plain_text)
