"""Single canonical skill text normalizer.

This is the authoritative normalizer for the entire seeding pipeline.
All sources and the seeder itself call this function before any DB operation.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Final

_MAX_NORMALIZED_LENGTH: Final[int] = 100
_WORD_INTERNAL_HYPHEN: Final[re.Pattern[str]] = re.compile(r"(?<=[a-z0-9])-(?=[a-z0-9])")
_MULTI_SPACE: Final[re.Pattern[str]] = re.compile(r"\s{2,}")
_QUOTES: Final[re.Pattern[str]] = re.compile(r"""["']""")


def normalize_skill_text(text: str, *, max_length: int = _MAX_NORMALIZED_LENGTH) -> str:
    """Normalize a skill text to its canonical form.

    Pipeline stages (in order):
    1. NFKC Unicode normalization (fullwidth → ASCII, compatibility decomposition)
    2. Diacritics strip (NFD decomposition + remove Mn combining marks)
    3. Lowercase
    4. Word-internal hyphen → space (front-end → front end)
    5. Strip quote characters
    6. Collapse multiple whitespace
    7. Strip leading/trailing whitespace
    8. Truncate to max_length

    Language canonicalization is the upstream LLM pipeline's responsibility.
    Handles only mechanical format variation.

    Args:
        text: Raw skill text to normalize.
        max_length: Maximum character length for the result.

    Returns:
        Normalized skill text, or empty string if input normalizes to empty.

    """
    result = unicodedata.normalize("NFKC", text)
    result = "".join(c for c in unicodedata.normalize("NFD", result) if unicodedata.category(c) != "Mn")
    result = result.lower()
    result = _WORD_INTERNAL_HYPHEN.sub(" ", result)
    result = _QUOTES.sub("", result)
    result = _MULTI_SPACE.sub(" ", result)
    result = result.strip()
    return result[:max_length].rstrip()
