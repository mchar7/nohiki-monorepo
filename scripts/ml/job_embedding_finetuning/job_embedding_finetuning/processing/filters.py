"""Quality filters for training pairs.

Provides configurable filtering pipeline to ensure high-quality
training data for embedding finetuning.
"""

from __future__ import annotations

import hashlib
import html
import logging
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, Final

from job_embedding_finetuning.dataset_adapters.base import TrainingPair

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)

# Text cleaning patterns
_UNICODE_ESCAPE: Final = re.compile(r"\\u([0-9a-fA-F]{4})")
_HEX_ESCAPE: Final = re.compile(r"\\x([0-9a-fA-F]{2})")
_CONTROL_CHARS: Final = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
_MULTI_SPACE: Final = re.compile(r"[ \t]+")
_MULTI_NEWLINE: Final = re.compile(r"\n\s*\n+")

# non-ASCII character replacements - O(n) via str.translate
_CHAR_MAP: Final[dict[int, str]] = {
    # Dashes and hyphens
    0x2010: "-",  # hyphen
    0x2011: "-",  # non-breaking hyphen
    0x2012: "-",  # figure dash
    0x2013: "-",  # en dash
    0x2014: "-",  # em dash
    0x2015: "-",  # horizontal bar
    0x2212: "-",  # minus sign
    0xFE58: "-",  # small em dash
    0xFE63: "-",  # small hyphen-minus
    0xFF0D: "-",  # fullwidth hyphen-minus
    # Quotes
    0x2018: "'",  # left single quote
    0x2019: "'",  # right single quote
    0x201A: "'",  # single low-9 quote
    0x201B: "'",  # single high-reversed-9 quote
    0x2039: "'",  # single left angle quote
    0x203A: "'",  # single right angle quote
    0x201C: '"',  # left double quote
    0x201D: '"',  # right double quote
    0x201E: '"',  # double low-9 quote
    0x201F: '"',  # double high-reversed-9 quote
    0x00AB: '"',  # left double angle quote
    0x00BB: '"',  # right double angle quote
    0x301D: '"',  # reversed double prime quote
    0x301E: '"',  # double prime quote
    # Ellipsis and dots
    0x2026: "...",  # ellipsis
    0x22EF: "...",  # midline horizontal ellipsis
    # Bullets and dots
    0x2022: "-",  # bullet
    0x2023: "-",  # triangular bullet
    0x2043: "-",  # hyphen bullet
    0x204C: "-",  # black leftwards bullet
    0x204D: "-",  # black rightwards bullet
    0x2219: "-",  # bullet operator
    0x25AA: "-",  # black small square
    0x25CF: "-",  # black circle
    0x25E6: "-",  # white bullet
    0x00B7: ".",  # middle dot
    0x2027: ".",  # hyphenation point
    # Spaces
    0x00A0: " ",  # non-breaking space
    0x2000: " ",  # en quad
    0x2001: " ",  # em quad
    0x2002: " ",  # en space
    0x2003: " ",  # em space
    0x2004: " ",  # three-per-em space
    0x2005: " ",  # four-per-em space
    0x2006: " ",  # six-per-em space
    0x2007: " ",  # figure space
    0x2008: " ",  # punctuation space
    0x2009: " ",  # thin space
    0x200A: " ",  # hair space
    0x202F: " ",  # narrow no-break space
    0x205F: " ",  # medium mathematical space
    0x3000: " ",  # ideographic space
    # Zero-width and invisible
    0x200B: "",  # zero-width space
    0x200C: "",  # zero-width non-joiner
    0x200D: "",  # zero-width joiner
    0x200E: "",  # left-to-right mark
    0x200F: "",  # right-to-left mark
    0x2060: "",  # word joiner
    0x2061: "",  # function application
    0x2062: "",  # invisible times
    0x2063: "",  # invisible separator
    0x2064: "",  # invisible plus
    0xFEFF: "",  # BOM / zero-width no-break space
    # Slashes
    0x2044: "/",  # fraction slash
    0x2215: "/",  # division slash
    0xFF0F: "/",  # fullwidth solidus
    # Ampersand and special
    0xFF06: "&",  # fullwidth ampersand
    0xFE60: "&",  # small ampersand
    # Arrows (convert to text)
    0x2192: "->",  # rightwards arrow
    0x2190: "<-",  # leftwards arrow
    0x2194: "<->",  # left right arrow
    # Trademark/copyright
    0x00AE: "(R)",  # registered
    0x00A9: "(C)",  # copyright
    0x2122: "(TM)",  # trademark
    # Math operators
    0x00D7: "x",  # multiplication sign
    0x00F7: "/",  # division sign
    0x2260: "!=",  # not equal
    0x2264: "<=",  # less than or equal
    0x2265: ">=",  # greater than or equal
    0x00B1: "+/-",  # plus-minus
}
_CHAR_TRANS: Final = str.maketrans(_CHAR_MAP)

# Pattern to strip any remaining non-ASCII after translation
_NON_ASCII: Final = re.compile(r"[^\x00-\x7F]+")


@lru_cache(maxsize=100000)
def clean_text(text: str) -> str:
    """Clean text by normalizing unicode, removing special chars, fixing whitespace.

    Args:
        text: Raw input text.

    Returns:
        Cleaned text ready for training.

    """
    if not text:
        return ""

    # Decode unicode escapes (e.g., \\u2013 -> actual character)
    text = _UNICODE_ESCAPE.sub(lambda m: chr(int(m.group(1), 16)), text)
    text = _HEX_ESCAPE.sub(lambda m: chr(int(m.group(1), 16)), text)

    # Decode HTML entities
    text = html.unescape(text)

    # Replace non-ASCII characters with ASCII equivalents (O(n) via translate)
    text = text.translate(_CHAR_TRANS)

    # Remove control characters (but keep newlines and tabs for now)
    text = _CONTROL_CHARS.sub("", text)

    # Normalize unicode (NFC form)
    text = unicodedata.normalize("NFC", text)

    # Strip any remaining non-ASCII characters
    text = _NON_ASCII.sub("", text)

    # Normalize whitespace
    text = _MULTI_SPACE.sub(" ", text)
    text = _MULTI_NEWLINE.sub("\n", text)
    return text.strip()


# Invalid text values to filter out
_INVALID_VALUES: Final[frozenset[str]] = frozenset(
    {
        "unknown",
        "n/a",
        "na",
        "none",
        "null",
        "nan",
        "undefined",
        "-",
        ".",
        "",
    }
)


@dataclass(frozen=True, slots=True)
class FilterConfig:
    """Configuration for training pair filters.

    Attributes:
        min_anchor_length: Minimum anchor text length.
        max_anchor_length: Maximum anchor text length.
        min_positive_length: Minimum positive text length.
        max_positive_length: Maximum positive text length.
        remove_duplicates: Remove exact duplicate pairs.
        remove_near_duplicates: Remove semantically similar pairs.
        near_duplicate_threshold: Jaccard similarity threshold for near-duplicates.
        require_positive: Require non-empty positive text.
        clean_text: Apply text cleaning (unicode, HTML, whitespace normalization).
        filter_invalid_values: Filter out pairs with invalid values like "unknown".

    """

    min_anchor_length: int = 3
    max_anchor_length: int = 512
    min_positive_length: int = 3
    max_positive_length: int = 512
    remove_duplicates: bool = True
    remove_near_duplicates: bool = False
    near_duplicate_threshold: float = 0.95
    require_positive: bool = True
    clean_text: bool = True
    filter_invalid_values: bool = True


@dataclass(slots=True)
class FilterStats:
    """Statistics from filter application.

    Attributes:
        total_input: Total pairs input to filter.
        passed: Pairs that passed all filters.
        filtered_anchor_length: Pairs filtered by anchor length.
        filtered_positive_length: Pairs filtered by positive length.
        filtered_duplicate: Pairs filtered as duplicates.
        filtered_near_duplicate: Pairs filtered as near-duplicates.
        filtered_empty: Pairs filtered for empty required fields.
        filtered_invalid: Pairs filtered for invalid values.

    """

    total_input: int = 0
    passed: int = 0
    filtered_anchor_length: int = 0
    filtered_positive_length: int = 0
    filtered_duplicate: int = 0
    filtered_near_duplicate: int = 0
    filtered_empty: int = 0
    filtered_invalid: int = 0

    def log_summary(self) -> None:
        """Log a summary of filter statistics."""
        if self.total_input == 0:
            return

        pass_rate = (self.passed / self.total_input) * 100
        logger.info(
            "Filter results: %d/%d passed (%.1f%%). "
            "Filtered: anchor_len=%d, pos_len=%d, dup=%d, near_dup=%d, empty=%d, invalid=%d",
            self.passed,
            self.total_input,
            pass_rate,
            self.filtered_anchor_length,
            self.filtered_positive_length,
            self.filtered_duplicate,
            self.filtered_near_duplicate,
            self.filtered_empty,
            self.filtered_invalid,
        )


def _compute_pair_hash(anchor: str, positive: str) -> str:
    """Compute a hash for a training pair for deduplication.

    Args:
        anchor: Anchor text.
        positive: Positive text.

    Returns:
        SHA256 hash of the normalized pair.

    """
    normalized = f"{anchor.lower().strip()}|||{positive.lower().strip()}"
    return hashlib.sha256(normalized.encode()).hexdigest()


def _compute_token_set(text: str) -> frozenset[str]:
    """Compute token set for Jaccard similarity.

    Args:
        text: Input text.

    Returns:
        Frozenset of lowercase tokens.

    """
    # Simple whitespace tokenization
    tokens = text.lower().split()
    return frozenset(tokens)


def _jaccard_similarity(set1: frozenset[str], set2: frozenset[str]) -> float:
    """Compute Jaccard similarity between two token sets.

    Args:
        set1: First token set.
        set2: Second token set.

    Returns:
        Jaccard similarity score (0.0 to 1.0).

    """
    if not set1 or not set2:
        return 0.0
    intersection = len(set1 & set2)
    union = len(set1 | set2)
    return intersection / union if union > 0 else 0.0


class DuplicateTracker:
    """Tracks seen pairs for deduplication."""

    def __init__(self, *, track_near_duplicates: bool = False, threshold: float = 0.95) -> None:
        """Initialize the duplicate tracker.

        Args:
            track_near_duplicates: Whether to track near-duplicates.
            threshold: Jaccard similarity threshold for near-duplicates.

        """
        self._seen_hashes: set[str] = set()
        self._seen_token_sets: list[frozenset[str]] = []
        self._track_near: bool = track_near_duplicates
        self._threshold: float = threshold

    def is_duplicate(self, anchor: str, positive: str) -> bool:
        """Check if a pair is a duplicate.

        Args:
            anchor: Anchor text.
            positive: Positive text.

        Returns:
            True if the pair is a duplicate.

        """
        pair_hash = _compute_pair_hash(anchor, positive)
        if pair_hash in self._seen_hashes:
            return True
        self._seen_hashes.add(pair_hash)
        return False

    def is_near_duplicate(self, anchor: str, positive: str) -> bool:
        """Check if a pair is a near-duplicate.

        Args:
            anchor: Anchor text.
            positive: Positive text.

        Returns:
            True if the pair is a near-duplicate.

        """
        if not self._track_near:
            return False

        combined = f"{anchor} {positive}"
        token_set = _compute_token_set(combined)

        for seen_set in self._seen_token_sets:
            if _jaccard_similarity(token_set, seen_set) >= self._threshold:
                return True

        self._seen_token_sets.append(token_set)
        return False


def _check_length(text: str, min_len: int, max_len: int) -> bool:
    """Check if text length is within bounds."""
    return min_len <= len(text) <= max_len


def _is_invalid_value(text: str) -> bool:
    """Check if text is an invalid/placeholder value."""
    return text.lower().strip() in _INVALID_VALUES


def _check_content_validity(pair: TrainingPair, config: FilterConfig, stats: FilterStats) -> bool:
    """Check content validity (empty, invalid values, length)."""
    if config.require_positive and not pair.positive:
        stats.filtered_empty += 1
        return False

    if config.filter_invalid_values and (_is_invalid_value(pair.anchor) or _is_invalid_value(pair.positive)):
        stats.filtered_invalid += 1
        return False

    if not _check_length(pair.anchor, config.min_anchor_length, config.max_anchor_length):
        stats.filtered_anchor_length += 1
        return False

    if pair.positive and not _check_length(pair.positive, config.min_positive_length, config.max_positive_length):
        stats.filtered_positive_length += 1
        return False

    return True


def _check_duplicates(pair: TrainingPair, config: FilterConfig, tracker: DuplicateTracker, stats: FilterStats) -> bool:
    """Check for duplicate pairs."""
    if config.remove_duplicates and tracker.is_duplicate(pair.anchor, pair.positive):
        stats.filtered_duplicate += 1
        return False

    if config.remove_near_duplicates and tracker.is_near_duplicate(pair.anchor, pair.positive):
        stats.filtered_near_duplicate += 1
        return False

    return True


def _filter_pair(
    pair: TrainingPair,
    config: FilterConfig,
    tracker: DuplicateTracker,
    stats: FilterStats,
) -> bool:
    """Check if a pair passes all filters. Updates stats as side effect.

    Returns:
        True if pair passes, False if filtered out.

    """
    if not _check_content_validity(pair, config, stats):
        return False
    return _check_duplicates(pair, config, tracker, stats)


def _clean_pair(pair: TrainingPair) -> TrainingPair:
    """Create a new pair with cleaned text fields."""
    return TrainingPair(
        anchor=clean_text(pair.anchor),
        positive=clean_text(pair.positive),
        negative=clean_text(pair.negative) if pair.negative else None,
        label=pair.label,
        source_dataset=pair.source_dataset,
        pair_type=pair.pair_type,
    )


def apply_filters(
    pairs: Iterator[TrainingPair],
    config: FilterConfig,
) -> Iterator[TrainingPair]:
    """Apply quality filters to training pairs.

    Args:
        pairs: Iterator of training pairs.
        config: Filter configuration.

    Yields:
        Training pairs that pass all filters.

    """
    stats = FilterStats()
    tracker = DuplicateTracker(
        track_near_duplicates=config.remove_near_duplicates,
        threshold=config.near_duplicate_threshold,
    )

    for raw_pair in pairs:
        stats.total_input += 1

        # Apply text cleaning if enabled
        pair = _clean_pair(raw_pair) if config.clean_text else raw_pair

        if _filter_pair(pair, config, tracker, stats):
            stats.passed += 1
            yield pair

    stats.log_summary()
