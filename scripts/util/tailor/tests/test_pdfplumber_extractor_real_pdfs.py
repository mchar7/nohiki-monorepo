"""End-to-end tests for ``PdfPlumberLayoutExtractor`` against real PDFs.

These tests complement :mod:`test_pdfplumber_extractor` by building actual
PDF byte payloads with reportlab and running them through the full
``pdfplumber.open`` / ``extract_words`` / clustering / matching pipeline.
That exercises every branch in ``PdfPlumberLayoutExtractor.extract`` that
depends on pdfplumber's behaviour, which the helper-only tests cannot
cover without integration.

reportlab is a dev-only dependency declared in ``pyproject.toml``. It is
not imported by any runtime code path.
"""

from __future__ import annotations

import io
from collections.abc import Callable, Iterable

import pytest
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas
from tailor.lint.layout.pdfplumber_extractor import PdfPlumberLayoutExtractor


def _render_pdf(draw: Callable[[canvas.Canvas], None], page_size: tuple[float, float] = LETTER) -> bytes:
    """Build an in-memory PDF using reportlab.

    Args:
        draw: Callback that receives a ``canvas.Canvas`` positioned at a
            fresh page. Callers use ``drawString`` / ``showPage`` /
            ``setFont`` as needed. The callback must ``showPage`` explicitly
            for any page it wants materialised.
        page_size: ``(width_pt, height_pt)`` tuple. Defaults to US Letter.

    Returns:
        PDF file bytes.
    """
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=page_size)
    draw(c)
    c.save()
    return buffer.getvalue()


def _draw_lines(
    c: canvas.Canvas,
    x_pt: float,
    y_start_pt: float,
    leading_pt: float,
    lines: Iterable[str],
) -> None:
    """Emit each string in ``lines`` at descending y-coordinates.

    reportlab's origin is bottom-left with y increasing upward. We use a
    leading spacing between baselines.
    """
    y = y_start_pt
    for line in lines:
        c.drawString(x_pt, y, line)
        y -= leading_pt


@pytest.fixture
def extractor() -> PdfPlumberLayoutExtractor:
    """A fresh extractor with the default 2pt y-tolerance."""
    return PdfPlumberLayoutExtractor()


class TestSinglePageSingleParagraph:
    """One page, one paragraph rendered as one visual line."""

    def test_extracts_page_count_and_size(self, extractor: PdfPlumberLayoutExtractor) -> None:
        """page_count reports 1 and page_size matches Letter dimensions."""

        def draw(c: canvas.Canvas) -> None:
            c.setFont("Helvetica", 12)
            c.drawString(72, 720, "Hello world")
            c.showPage()

        pdf_bytes = _render_pdf(draw)
        meta = extractor.extract(pdf_bytes, {"greeting": "Hello world"})
        assert meta.page_count == 1
        # Letter paper size is 612 x 792 points; reportlab writes floats.
        assert meta.page_size_pt[0] == pytest.approx(612.0, rel=1e-3)
        assert meta.page_size_pt[1] == pytest.approx(792.0, rel=1e-3)

    def test_matches_scope_path(self, extractor: PdfPlumberLayoutExtractor) -> None:
        """The rendered paragraph is matched back to its scope path."""

        def draw(c: canvas.Canvas) -> None:
            c.setFont("Helvetica", 12)
            c.drawString(72, 720, "The quick brown fox")
            c.showPage()

        pdf_bytes = _render_pdf(draw)
        meta = extractor.extract(pdf_bytes, {"sentence": "The quick brown fox"})
        assert len(meta.paragraphs) == 1
        assert meta.paragraphs[0].scope_path == "sentence"
        assert meta.paragraphs[0].page_number == 1
        assert len(meta.paragraphs[0].wrapped_lines) == 1
        # Substantive word count excludes stopwords (the / ).
        assert meta.paragraphs[0].wrapped_lines[0].word_count == 4

    def test_total_content_height_is_positive(self, extractor: PdfPlumberLayoutExtractor) -> None:
        """A visible paragraph contributes non-zero height to the total."""

        def draw(c: canvas.Canvas) -> None:
            c.setFont("Helvetica", 12)
            c.drawString(72, 720, "Body text")
            c.showPage()

        pdf_bytes = _render_pdf(draw)
        meta = extractor.extract(pdf_bytes, {"body": "Body text"})
        assert meta.total_content_height_pt > 0


class TestMultiLineParagraph:
    """One scope-path paragraph rendered across multiple wrapped lines."""

    def test_wrapped_lines_are_merged_into_one_paragraph(self, extractor: PdfPlumberLayoutExtractor) -> None:
        """Two visual lines with one scope text collapse into one ParagraphLayout."""
        first = "The quick brown fox jumped over the"
        second = "lazy dog near the riverbank."
        full = f"{first} {second}"

        def draw(c: canvas.Canvas) -> None:
            c.setFont("Helvetica", 12)
            # Two lines, 14pt leading (typical for 12pt body).
            _draw_lines(c, 72, 720, 14, [first, second])
            c.showPage()

        pdf_bytes = _render_pdf(draw)
        meta = extractor.extract(pdf_bytes, {"paragraph": full})
        assert len(meta.paragraphs) == 1
        assert meta.paragraphs[0].scope_path == "paragraph"
        assert len(meta.paragraphs[0].wrapped_lines) == 2
        # The bounding box spans both lines vertically. X bounds are incidental.
        _x0, y0, _x1, y1 = meta.paragraphs[0].bbox_pt
        assert y1 - y0 > 10


class TestMultipleParagraphs:
    """Sequential paragraphs — cursor must advance so later paragraphs match."""

    def test_two_paragraphs_match_in_reading_order(self, extractor: PdfPlumberLayoutExtractor) -> None:
        """Two scope paths map to two distinct paragraphs in document order."""

        def draw(c: canvas.Canvas) -> None:
            c.setFont("Helvetica", 12)
            _draw_lines(c, 72, 720, 28, ["First paragraph here.", "Second paragraph here."])
            c.showPage()

        pdf_bytes = _render_pdf(draw)
        meta = extractor.extract(
            pdf_bytes,
            {"body": ["First paragraph here.", "Second paragraph here."]},
        )
        scope_paths = [p.scope_path for p in meta.paragraphs]
        assert scope_paths == ["body[0]", "body[1]"]


class TestMultiPage:
    """Multiple pages — page_count reflects unique pages that have words."""

    def test_two_page_document_reports_page_count_two(self, extractor: PdfPlumberLayoutExtractor) -> None:
        """A 2-page PDF produces page_count=2 and paragraphs on respective pages."""

        def draw(c: canvas.Canvas) -> None:
            c.setFont("Helvetica", 12)
            c.drawString(72, 720, "Page one content.")
            c.showPage()
            c.setFont("Helvetica", 12)
            c.drawString(72, 720, "Page two content.")
            c.showPage()

        pdf_bytes = _render_pdf(draw)
        meta = extractor.extract(
            pdf_bytes,
            {"sections": ["Page one content.", "Page two content."]},
        )
        assert meta.page_count == 2
        assert {p.page_number for p in meta.paragraphs} == {1, 2}


class TestUnmatchedParagraphs:
    """Scope paths without matching rendered text are silently skipped."""

    def test_missing_text_drops_paragraph_silently(self, extractor: PdfPlumberLayoutExtractor) -> None:
        """A scope path whose text is not on the page yields no ParagraphLayout."""

        def draw(c: canvas.Canvas) -> None:
            c.setFont("Helvetica", 12)
            c.drawString(72, 720, "Present paragraph.")
            c.showPage()

        pdf_bytes = _render_pdf(draw)
        meta = extractor.extract(
            pdf_bytes,
            {
                "present": "Present paragraph.",
                "missing": "This text never made it to the PDF.",
            },
        )
        # Only the present paragraph matches; missing is silently dropped.
        scope_paths = [p.scope_path for p in meta.paragraphs]
        assert "present" in scope_paths
        assert "missing" not in scope_paths


class TestEmptyPageEdgeCases:
    """Pages with no visible words; empty-input error path."""

    def test_blank_page_yields_no_paragraphs(self, extractor: PdfPlumberLayoutExtractor) -> None:
        """A single blank page produces page_count=0 (no words extracted)."""

        def draw(c: canvas.Canvas) -> None:
            c.showPage()  # No text drawn.

        pdf_bytes = _render_pdf(draw)
        meta = extractor.extract(pdf_bytes, {"body": "Anything"})
        # pdfplumber reports the page but extract_words is empty, so our
        # raw_words set is empty, page_count is 0 by the set-size check.
        assert meta.page_count == 0
        assert meta.paragraphs == ()

    def test_empty_pdf_bytes_raises_value_error(self, extractor: PdfPlumberLayoutExtractor) -> None:
        """Empty bytes fail fast before reaching pdfplumber."""
        with pytest.raises(ValueError, match="empty pdf_bytes"):
            extractor.extract(b"", {})


class TestLineClusteringTolerance:
    """The y-tolerance constructor arg changes clustering behaviour."""

    def test_tight_tolerance_separates_close_lines(self, extractor: PdfPlumberLayoutExtractor) -> None:
        """Default 2pt tolerance separates 14pt-leading lines into distinct lines."""

        def draw(c: canvas.Canvas) -> None:
            c.setFont("Helvetica", 12)
            _draw_lines(c, 72, 720, 14, ["Line one.", "Line two."])
            c.showPage()

        pdf_bytes = _render_pdf(draw)
        meta = extractor.extract(
            pdf_bytes,
            {"body": ["Line one.", "Line two."]},
        )
        # Two distinct paragraphs, one line each.
        assert len(meta.paragraphs) == 2
        for para in meta.paragraphs:
            assert len(para.wrapped_lines) == 1

    def test_wide_tolerance_merges_close_lines(self) -> None:
        """A 50pt tolerance collapses two 14pt-spaced lines into one logical line."""
        wide = PdfPlumberLayoutExtractor(line_cluster_tolerance_pt=50.0)

        def draw(c: canvas.Canvas) -> None:
            c.setFont("Helvetica", 12)
            _draw_lines(c, 72, 720, 14, ["Close line A", "Close line B"])
            c.showPage()

        pdf_bytes = _render_pdf(draw)
        meta = wide.extract(pdf_bytes, {"body": "Close line A Close line B"})
        # With generous tolerance the two physical lines merge into one
        # reconstructed line, which matches the combined target.
        assert len(meta.paragraphs) == 1
        assert len(meta.paragraphs[0].wrapped_lines) == 1
