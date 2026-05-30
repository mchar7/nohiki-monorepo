"""Layout metadata types + extractor Protocol.

The types here are an abstraction over the rendering engine. Rule classes
consume the structured ``LayoutMetadata`` without knowing whether it came
from pdfplumber, Playwright, or a test fixture. This is what makes the
extractor swappable without touching rules or YAML config.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field


class LineLayout(BaseModel, frozen=True, extra="forbid"):
    """Per-wrapped-line layout data inside a paragraph.

    A "line" here is a single baseline run as laid out on the page. PDF files
    do not preserve semantic lines — these are reconstructed by the extractor
    from word bounding boxes clustered by y-coordinate.

    Attributes:
        text: The raw text of this wrapped line, in reading order.
        bbox_pt: ``(x0, y0, x1, y1)`` in PDF points, page-local origin.
        word_count: Total whitespace-split tokens on this line.
        substantive_word_count: ``word_count`` minus stopwords/punctuation.
    """

    text: str
    bbox_pt: tuple[float, float, float, float]
    word_count: int = Field(ge=0)
    substantive_word_count: int = Field(ge=0)


class ParagraphLayout(BaseModel, frozen=True, extra="forbid"):
    """Per-paragraph (or per-bullet) layout data.

    One ``ParagraphLayout`` corresponds to one logical paragraph in the source
    document data — matched back to the document via ``scope_path``. The path
    is an arbitrary document-schema identifier such as ``paragraphs[2]`` or
    ``sections[0].items[1]``; the extractor does not interpret the path.

    Attributes:
        scope_path: Document path this paragraph came from (for rule matching).
        bbox_pt: Minimal bounding box enclosing every wrapped line.
        wrapped_lines: One ``LineLayout`` per visual line on the page.
        page_number: 1-indexed page where this paragraph starts.
    """

    scope_path: str
    bbox_pt: tuple[float, float, float, float]
    wrapped_lines: tuple[LineLayout, ...]
    page_number: int = Field(ge=1)


class LayoutMetadata(BaseModel, frozen=True, extra="forbid"):
    """Structured layout info extracted from a rendered document.

    Every ``LayoutExtractor`` implementation populates this shape. Rules
    consume it without caring which extractor produced it, so the extractor
    can be swapped (pdfplumber → Playwright) without touching rules.

    Attributes:
        page_count: Total number of pages in the rendered output.
        page_size_pt: ``(width, height)`` in points; ``(612, 792)`` for US Letter.
        paragraphs: One entry per matched source paragraph, in reading order.
        total_content_height_pt: Sum of paragraph heights; useful for fill-ratio
            and overflow calculations across variable-height pages.
    """

    page_count: int = Field(ge=0)
    page_size_pt: tuple[float, float]
    paragraphs: tuple[ParagraphLayout, ...]
    total_content_height_pt: float = Field(ge=0.0)


@runtime_checkable
class LayoutExtractor(Protocol):
    """Extracts :class:`LayoutMetadata` from rendered PDF bytes.

    Implementations must be pure (no side effects, no network calls beyond
    what's needed to parse the PDF) and deterministic: the same ``pdf_bytes``
    must always produce equal ``LayoutMetadata``.
    """

    def extract(
        self,
        pdf_bytes: bytes,
        document_data: dict[str, object],
    ) -> LayoutMetadata:
        """Parse ``pdf_bytes`` into layout metadata.

        Args:
            pdf_bytes: Raw PDF file bytes.
            document_data: Primary JSON document data, used to recover the
                mapping from rendered text back to scope paths.

        Returns:
            A populated :class:`LayoutMetadata` object.

        Raises:
            ValueError: If ``pdf_bytes`` is malformed or empty.
        """
        ...
