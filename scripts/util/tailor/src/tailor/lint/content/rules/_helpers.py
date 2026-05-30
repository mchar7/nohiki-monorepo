"""Shared text helpers for content lint rule implementations.

NLTK-free heuristics kept deliberately minimal and dependency-free. Each helper
is pure and stateless so rules can share the same functions safely from any
thread. Anything mutable or stateful belongs in the rule implementation, not
here.

Exposed primitives:
    ``tokenize(text)`` — word-token extraction (apostrophe-preserving).
    ``split_sentences(text)`` — sentence splitter on ``.!?`` boundaries.
    ``count_syllables(word)`` — vowel-group heuristic with silent-``e`` tweak.
    ``as_strings(items)`` — filter a resolved-items list down to ``str`` values.
    ``count_substantive_words(text)`` — non-stopword token count.
    ``compile_cached(pattern, flags)`` — LRU-cached regex compilation shared
        across all rules so the same pattern+flags pair compiles exactly once.
    ``STOPWORDS`` — curated ~55-word frozenset of common function words.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from typing import TypeGuard

# Kept small on purpose: articles, prepositions, auxiliary verbs, pronouns,
# and determiners. Rules that need a different set can accept a ``stopwords``
# override.
STOPWORDS: Final[frozenset[str]] = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "if",
        "then",
        "of",
        "in",
        "on",
        "at",
        "to",
        "for",
        "with",
        "by",
        "from",
        "as",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "am",
        "has",
        "have",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "shall",
        "should",
        "can",
        "could",
        "may",
        "might",
        "must",
        "i",
        "you",
        "he",
        "she",
        "it",
        "we",
        "they",
        "me",
        "him",
        "her",
        "us",
        "them",
        "this",
        "that",
        "these",
        "those",
        "my",
        "your",
        "his",
        "its",
        "our",
        "their",
    },
)

# Matches runs of letters with optional internal apostrophes (e.g. ``don't``,
# ``it's``, ``customers'``). Intentionally excludes digits so ``1999`` is
# treated as a numeric literal by cross-path rules, not a word.
_WORD_RE = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)*")

# Compiled once. Splits on one or more whitespace characters that follow a
# sentence-terminating punctuation (``.!?``) or on newlines between fragments
# that lack terminal punctuation (common in short-form list items).
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")

# Contiguous vowel group. Count ``y`` as a vowel using a pragmatic English
# heuristic (``rhythm`` → 1, ``style`` → 1, ``happy`` → 2).
_VOWEL_GROUP_RE = re.compile(r"[aeiouy]+")

# Punctuation stripped when isolating a word's orthographic core.
_WORD_EDGE_STRIP = "'\".,;:!?()[]{}"

# Trailing digraphs where the final ``e`` is pronounced, so the silent-``e``
# rule must not subtract a syllable.
_PRONOUNCED_FINAL_E_ENDINGS = ("le", "ee", "ye", "oe", "ae", "ie", "ue")


def tokenize(text: str) -> list[str]:
    """Extract word tokens from ``text``.

    Preserves case and internal apostrophes; excludes digits and punctuation.

    Args:
        text: Arbitrary string.

    Returns:
        Tokens in left-to-right order. Empty list when there are no letters.
    """
    return _WORD_RE.findall(text)


def split_sentences(text: str) -> list[str]:
    """Split ``text`` into non-empty, stripped sentences.

    Sentences are divided on ``.!?`` followed by whitespace, or on newline runs
    (which are treated as implicit sentence boundaries — useful for short-form
    list item data where terminal periods are often omitted).

    Args:
        text: Arbitrary string.

    Returns:
        List of sentence strings. Empty list when ``text`` is empty or whitespace.
    """
    stripped = text.strip()
    if not stripped:
        return []
    return [part.strip() for part in _SENTENCE_SPLIT_RE.split(stripped) if part.strip()]


def count_syllables(word: str) -> int:
    """Estimate the syllable count of a single English word.

    Heuristic: count contiguous vowel groups, drop the trailing ``e`` when it
    is typically silent (e.g. ``make``, ``believe``), and never return less
    than ``1`` for a non-empty word. Good enough for rhythm detection at
    sentence granularity; not a dictionary lookup.

    Args:
        word: A single word; surrounding punctuation is stripped.

    Returns:
        Non-negative integer; ``0`` only when ``word`` contains no letters.
    """
    core = word.lower().strip(_WORD_EDGE_STRIP)
    if not core:
        return 0
    groups = _VOWEL_GROUP_RE.findall(core)
    count = len(groups)
    if count == 0:
        return 0
    if core.endswith("e") and count > 1 and not core.endswith(_PRONOUNCED_FINAL_E_ENDINGS):
        count -= 1
    return max(count, 1)


def as_strings(items: list[object]) -> list[str]:
    """Filter a resolved-items list down to strings only.

    Path resolution returns ``list[object]`` because some scopes target
    mixed-type arrays (dicts of bullet items, nested lists, etc.). Text-family
    rules work at the string level and use this helper to skip non-strings
    silently.

    Args:
        items: Mixed-type resolved items.

    Returns:
        Strings in original order. Empty list when no strings are present.
    """
    return [item for item in items if isinstance(item, str)]


def count_substantive_words(text: str, *, stopwords: frozenset[str] = STOPWORDS) -> int:
    """Count tokens in ``text`` that are not in ``stopwords`` (case-insensitive).

    Used by layout rules to distinguish orphan lines worth flagging from
    single-stopword leftovers (e.g. a trailing ``the`` carrying no content).

    Args:
        text: Arbitrary string.
        stopwords: Override set; defaults to the module-level ``STOPWORDS``.

    Returns:
        Number of tokens whose lowercase form is not in ``stopwords``.
    """
    # Stream over the regex iterator rather than materialising a token list.
    # This produces equivalent output with one fewer allocation per call.
    return sum(1 for match in _WORD_RE.finditer(text) if match.group().lower() not in stopwords)


def is_str_keyed_dict(value: object) -> TypeGuard[dict[str, object]]:
    """Check whether ``value`` is a ``dict`` with exclusively string keys.

    Shared TypeGuard used by section-family and structure-family rules so
    both narrow the same way. Returning a ``TypeGuard`` lets callers use the
    narrowed type in place without allocating a fresh dict copy per item.

    Args:
        value: Any object emitted by the path resolver.

    Returns:
        ``True`` iff ``value`` is a dict whose every key is a ``str``.
    """
    return isinstance(value, dict) and all(isinstance(k, str) for k in value)


@lru_cache(maxsize=256)
def compile_cached(pattern: str, flags: int = 0) -> re.Pattern[str]:
    """Return a compiled regex, cached by ``(pattern, flags)``.

    Rules that accept user-supplied regex patterns (``banned_patterns``,
    ``banned_openers``, ``banned_child_names``, ``max_consecutive_opener``,
    ``mention_count``, ``ratio``, …) used to recompile their patterns on every
    ``check()`` invocation. Because rule params are frozen, the
    ``(pattern, flags)`` identity is stable across invocations and an LRU
    cache sized for ~256 distinct patterns eliminates that cost for the
    entire generate pipeline.

    Args:
        pattern: Regex source string.
        flags: ``re`` compile flags (e.g. ``re.IGNORECASE``).

    Returns:
        A compiled :class:`re.Pattern` reused across calls.
    """
    return re.compile(pattern, flags)
