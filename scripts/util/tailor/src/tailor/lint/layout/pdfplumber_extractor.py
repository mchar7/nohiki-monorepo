"""pdfplumber-based ``LayoutExtractor`` implementation.

The extractor parses PDF bytes, reconstructs per-word bounding boxes, clusters
them into wrapped lines by y-coordinate, and matches the resulting text
fragments back to scope paths in the source document.

Design constraints:
    - Pure read-only on the PDF (pdfplumber ``open(BytesIO(...))``).
    - No network, no filesystem writes.
    - Deterministic output for identical input bytes.
    - Text-matching tolerates whitespace normalisation (collapses runs of
      whitespace, strips trailing punctuation for fuzzy-equality).

Known trade-offs vs. the future Playwright-based extractor:
    - PDF has no semantic paragraphs; this reconstructs them by matching
      rendered text against scope_path values from ``document_data``. Some
      short paragraphs that happen to be substrings of longer paragraphs
      can be ambiguous — the extractor resolves ties by reading order.
    - Column-detection is left to future work; single-column layouts are
      fully supported.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pdfplumber

from tailor.lint.content.rules._helpers import count_substantive_words
from tailor.lint.layout.extractor import (
    LayoutExtractor,
    LayoutMetadata,
    LineLayout,
    ParagraphLayout,
)

if TYPE_CHECKING:
    from pdfplumber.page import Page


_DEFAULT_LINE_CLUSTER_TOLERANCE_PT: float = 2.0
"""Words with vertical centers within this many points are treated as one line."""

_WHITESPACE_RE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    """Collapse whitespace runs and strip leading/trailing whitespace."""
    return _WHITESPACE_RE.sub(" ", text).strip()


@dataclass(frozen=True, slots=True)
class _RawWord:
    """Minimal per-word record from pdfplumber.

    Kept internal: the public boundary is ``LineLayout`` / ``ParagraphLayout``.
    """

    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    page_number: int


@dataclass(frozen=True, slots=True)
class _ReconstructedLine:
    """A cluster of words sharing the same y-band, concatenated."""

    text: str
    bbox: tuple[float, float, float, float]
    word_count: int
    page_number: int


class PdfPlumberLayoutExtractor(LayoutExtractor):
    """Default layout extractor backed by pdfplumber.

    Instances are thread-safe for different PDF byte payloads because each
    ``extract`` call opens a fresh ``pdfplumber.PDF`` context. The extractor
    holds no per-call state.

    Args:
        line_cluster_tolerance_pt: Half-height tolerance when clustering words
            into lines by vertical center. Defaults to 2.0pt, which suits
            typical 11-14pt body text at ~1.2 leading. Increase slightly if a
            template uses tight leading and lines are being merged together,
            or if a template uses loose leading and single lines are being
            split across two clusters.

    Example:
        >>> extractor = PdfPlumberLayoutExtractor()
        >>> metadata = extractor.extract(pdf_bytes, document_data)
        >>> metadata.page_count  # doctest: +SKIP
        1
    """

    def __init__(self, line_cluster_tolerance_pt: float = _DEFAULT_LINE_CLUSTER_TOLERANCE_PT) -> None:
        """Store the y-cluster tolerance after validating positivity.

        Args:
            line_cluster_tolerance_pt: Positive float; see class docstring.

        Raises:
            ValueError: ``line_cluster_tolerance_pt`` is zero or negative.
        """
        if line_cluster_tolerance_pt <= 0:
            msg = f"line_cluster_tolerance_pt must be positive, got {line_cluster_tolerance_pt}"
            raise ValueError(msg)
        self._y_tol = line_cluster_tolerance_pt

    def extract(self, pdf_bytes: bytes, document_data: dict[str, object]) -> LayoutMetadata:
        """Extract structured layout metadata from ``pdf_bytes``.

        Args:
            pdf_bytes: Raw PDF file bytes (non-empty).
            document_data: Source document JSON used to map rendered text to
                scope paths. Missing or unmatched paragraphs are silently
                dropped — layout rules that care emit their own diagnostics.

        Returns:
            Populated :class:`LayoutMetadata`. Empty PDFs yield
            ``page_count=0`` / ``paragraphs=()``.

        Raises:
            ValueError: ``pdf_bytes`` is empty.
        """
        if not pdf_bytes:
            msg = "pdfplumber extractor received empty pdf_bytes"
            raise ValueError(msg)

        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            if not pdf.pages:
                return LayoutMetadata(
                    page_count=0,
                    page_size_pt=(0.0, 0.0),
                    paragraphs=(),
                    total_content_height_pt=0.0,
                )
            page_size_pt = (float(pdf.pages[0].width), float(pdf.pages[0].height))
            raw_words: list[_RawWord] = []
            for page_idx, page in enumerate(pdf.pages, start=1):
                raw_words.extend(self._extract_words(page, page_idx))

        lines = self._cluster_lines(raw_words)
        candidates = _iter_scope_path_strings(document_data)
        paragraphs = self._match_paragraphs_to_scopes(lines, candidates)
        total_height = _total_content_height(paragraphs)

        return LayoutMetadata(
            page_count=len({w.page_number for w in raw_words}) if raw_words else 0,
            page_size_pt=page_size_pt,
            paragraphs=tuple(paragraphs),
            total_content_height_pt=total_height,
        )

    def _extract_words(self, page: Page, page_number: int) -> list[_RawWord]:
        """Read per-word bboxes from one pdfplumber page.

        ``extract_words`` returns a list of dicts; we copy into frozen
        dataclasses so the rest of the extractor can stay immutable.
        """
        words: list[_RawWord] = []
        for w in page.extract_words(use_text_flow=True, keep_blank_chars=False):
            text = str(w.get("text", ""))
            if not text:
                continue
            words.append(
                _RawWord(
                    text=text,
                    x0=float(w["x0"]),
                    y0=float(w["top"]),
                    x1=float(w["x1"]),
                    y1=float(w["bottom"]),
                    page_number=page_number,
                )
            )
        return words

    def _cluster_lines(self, words: list[_RawWord]) -> list[_ReconstructedLine]:
        """Cluster words into lines by vertical-center proximity.

        Words are grouped first by page, then by y-center (midpoint between
        ``y0`` and ``y1``). Two words belong to the same line when their
        centers differ by less than ``self._y_tol``. Within a line, words
        are ordered by ``x0`` (left-to-right).
        """
        if not words:
            return []
        lines: list[_ReconstructedLine] = []
        # Stable sort: page then y-center then x0, in reading order.
        sorted_words = sorted(words, key=lambda w: (w.page_number, (w.y0 + w.y1) / 2, w.x0))
        current: list[_RawWord] = []
        current_center: float | None = None
        current_page: int | None = None

        def _flush() -> None:
            if not current:
                return
            text = " ".join(w.text for w in current)
            x0 = min(w.x0 for w in current)
            y0 = min(w.y0 for w in current)
            x1 = max(w.x1 for w in current)
            y1 = max(w.y1 for w in current)
            # current_page is set whenever current is non-empty; the guard
            # above prevents _flush() from seeing a None page number.
            page_number = current_page if current_page is not None else 0
            lines.append(
                _ReconstructedLine(
                    text=text,
                    bbox=(x0, y0, x1, y1),
                    word_count=len(current),
                    page_number=page_number,
                )
            )

        for w in sorted_words:
            center = (w.y0 + w.y1) / 2
            if current_center is None or w.page_number != current_page or abs(center - current_center) > self._y_tol:
                _flush()
                current = [w]
                current_center = center
                current_page = w.page_number
            else:
                current.append(w)
                # Rolling average keeps center stable against drift.
                current_center = (current_center * (len(current) - 1) + center) / len(current)
        _flush()
        return lines

    def _match_paragraphs_to_scopes(
        self,
        lines: list[_ReconstructedLine],
        candidates: list[tuple[str, str]],
    ) -> list[ParagraphLayout]:
        """Match ``(scope_path, text)`` candidates against reconstructed lines.

        For each candidate, greedily consume consecutive lines whose
        concatenated text prefix-matches the candidate's normalized text.
        Once the candidate is consumed, emit a ``ParagraphLayout``; advance
        the consumed line pointer so later candidates match subsequent lines.

        Candidates that cannot be matched are silently skipped. Unmatched
        ``orphan_detected`` or ``page_overflow`` rules targeting these paths
        see no paragraphs for that path, which the rules handle as no-op.
        """
        paragraphs: list[ParagraphLayout] = []
        cursor = 0
        n = len(lines)
        for scope_path, raw_text in candidates:
            target = _normalize(raw_text)
            if not target or cursor >= n:
                continue
            collected = self._collect_matching_lines(lines, cursor, target)
            if collected is None:
                continue
            start_idx, end_idx = collected
            consumed = lines[start_idx:end_idx]
            paragraphs.append(self._build_paragraph(scope_path, consumed))
            cursor = end_idx
        return paragraphs

    def _collect_matching_lines(
        self,
        lines: list[_ReconstructedLine],
        start: int,
        target: str,
    ) -> tuple[int, int] | None:
        """Return ``(start, end_exclusive)`` line range whose concat matches ``target``.

        Matching is prefix-tolerant: keep appending lines until the concatenated
        normalized text either equals or contains the target. Break out when we
        overshoot without a match.

        Uses a list + ``" ".join`` accumulator instead of iterative string
        concatenation so matching cost is O(n * target_len) rather than the
        O(n^2) that ``accum = f"{accum} {piece}"`` produced per iteration.
        """
        parts: list[str] = []
        for i in range(start, len(lines)):
            piece = _normalize(lines[i].text)
            if not piece:
                continue
            parts.append(piece)
            accum_norm = " ".join(parts)
            if accum_norm == target or target in accum_norm:
                return (start, i + 1)
            if not target.startswith(accum_norm[: len(target)]):
                # Went past the target without a match; give up on this candidate.
                return None
        return None

    def _build_paragraph(self, scope_path: str, consumed: list[_ReconstructedLine]) -> ParagraphLayout:
        """Aggregate consumed lines into one ``ParagraphLayout``."""
        x0 = min(line.bbox[0] for line in consumed)
        y0 = min(line.bbox[1] for line in consumed)
        x1 = max(line.bbox[2] for line in consumed)
        y1 = max(line.bbox[3] for line in consumed)
        wrapped = tuple(
            LineLayout(
                text=line.text,
                bbox_pt=line.bbox,
                word_count=line.word_count,
                substantive_word_count=count_substantive_words(line.text),
            )
            for line in consumed
        )
        return ParagraphLayout(
            scope_path=scope_path,
            bbox_pt=(x0, y0, x1, y1),
            wrapped_lines=wrapped,
            page_number=consumed[0].page_number,
        )


def _iter_scope_path_strings(data: object, prefix: str = "") -> list[tuple[str, str]]:
    """Walk ``data`` and yield every ``(scope_path, text)`` for string leaves.

    String leaves are emitted so the extractor can match rendered lines back
    to source paragraphs. Lists preserve index-notation paths (``foo[0]``),
    dicts use ``dot.path`` notation. Non-string / non-container values are
    skipped.
    """
    out: list[tuple[str, str]] = []
    _walk(data, prefix, out)
    return out


def _walk(node: object, path: str, out: list[tuple[str, str]]) -> None:
    """Recursive helper for :func:`_iter_scope_path_strings`."""
    if isinstance(node, str):
        if node.strip():
            out.append((path, node))
        return
    if isinstance(node, dict):
        for key, value in node.items():
            if not isinstance(key, str):
                continue
            child_path = f"{path}.{key}" if path else key
            _walk(value, child_path, out)
        return
    if isinstance(node, list):
        for idx, value in enumerate(node):
            child_path = f"{path}[{idx}]"
            _walk(value, child_path, out)
        return
    # ints/floats/booleans/None are not visible text. Skip them.


def _total_content_height(paragraphs: list[ParagraphLayout]) -> float:
    """Sum paragraph heights across pages.

    Cross-page paragraphs contribute the bbox height on their starting page
    only. This is close enough for fill-ratio and overflow calculations
    without needing per-page slicing.
    """
    return sum(max(0.0, p.bbox_pt[3] - p.bbox_pt[1]) for p in paragraphs)
