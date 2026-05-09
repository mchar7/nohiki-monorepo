"""Skill text normalizer — reimplemented from skill_graph_service.seeding.normalizer.

MUST produce identical output to the authoritative normalizer at
backend/services/skill-graph-service/src/skill_graph_service/seeding/normalizer.py
(cannot import directly — fine-tuning package is not a workspace member).

Pipeline: NFKC → diacritics strip → lowercase → word-internal hyphen→space →
strip quotes → collapse whitespace → strip → truncate(100).
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

    Stages:
        1. NFKC Unicode normalization (fullwidth → ASCII, ligatures → components)
        2. Strip diacritics (NFD decompose + remove Mn category marks)
        3. Lowercase
        4. Word-internal hyphen → space (preserves leading/trailing hyphens)
        5. Strip single and double quotes
        6. Collapse multiple whitespace to single space
        7. Strip leading/trailing whitespace
        8. Truncate to max_length

    Args:
        text: Raw skill text to normalize.
        max_length: Maximum output length (default: 100).

    Returns:
        Normalized canonical form of the skill text.
    """
    result = unicodedata.normalize("NFKC", text)
    result = "".join(c for c in unicodedata.normalize("NFD", result) if unicodedata.category(c) != "Mn")
    result = result.lower()
    result = _WORD_INTERNAL_HYPHEN.sub(" ", result)
    result = _QUOTES.sub("", result)
    result = _MULTI_SPACE.sub(" ", result)
    result = result.strip()
    return result[:max_length]
