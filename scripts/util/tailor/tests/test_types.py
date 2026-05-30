"""Tests for tailor.core.types -- infer_output_format and OutputSpec."""

from __future__ import annotations

from pathlib import Path

import pytest
from tailor.core.types import OutputSpec, infer_output_format


class TestInferOutputFormat:
    """Tests for infer_output_format()."""

    def test_pdf_extension(self) -> None:
        assert infer_output_format(Path("resume.pdf")) == "pdf"

    def test_html_extension(self) -> None:
        assert infer_output_format(Path("resume.html")) == "html"

    def test_htm_extension(self) -> None:
        assert infer_output_format(Path("resume.htm")) == "html"

    def test_txt_extension(self) -> None:
        assert infer_output_format(Path("resume.txt")) == "text"

    def test_json_extension(self) -> None:
        assert infer_output_format(Path("data.json")) == "json"

    def test_png_extension(self) -> None:
        assert infer_output_format(Path("preview.png")) == "png"

    def test_jpeg_extension(self) -> None:
        assert infer_output_format(Path("preview.jpeg")) == "jpeg"

    def test_jpg_extension(self) -> None:
        assert infer_output_format(Path("preview.jpg")) == "jpeg"

    def test_webp_extension(self) -> None:
        assert infer_output_format(Path("preview.webp")) == "webp"

    def test_case_insensitive_pdf(self) -> None:
        """Extension matching must be case-insensitive."""
        assert infer_output_format(Path("resume.PDF")) == "pdf"

    def test_case_insensitive_html(self) -> None:
        assert infer_output_format(Path("resume.Html")) == "html"

    def test_unknown_extension_raises_value_error(self) -> None:
        """Unsupported extensions must raise ValueError."""
        with pytest.raises(ValueError, match="Unsupported output extension"):
            infer_output_format(Path("resume.doc"))

    def test_no_extension_raises_value_error(self) -> None:
        """Paths without extension must raise ValueError."""
        with pytest.raises(ValueError, match="Unsupported output extension"):
            infer_output_format(Path("resume"))

    def test_error_message_lists_supported_extensions(self) -> None:
        """ValueError message must mention the supported extensions."""
        with pytest.raises(ValueError, match="Unsupported output extension") as exc_info:
            infer_output_format(Path("resume.svg"))
        assert ".pdf" in str(exc_info.value)

    def test_full_path_uses_suffix_only(self) -> None:
        """infer_output_format must use only the suffix, not the full path."""
        assert infer_output_format(Path("/some/deep/dir/resume.pdf")) == "pdf"


class TestOutputSpec:
    """Tests for OutputSpec frozen dataclass."""

    def test_fields_stored_correctly(self) -> None:
        """OutputSpec must store path and format correctly."""
        path = Path("/out/resume.pdf")
        spec = OutputSpec(path=path, format="pdf")
        assert spec.path == path
        assert spec.format == "pdf"

    def test_frozen_prevents_path_mutation(self) -> None:
        """OutputSpec is frozen; path assignment must raise."""
        spec = OutputSpec(path=Path("/out/r.pdf"), format="pdf")
        frozen_field = "path"
        with pytest.raises(AttributeError):
            setattr(spec, frozen_field, Path("/other.pdf"))

    def test_frozen_prevents_format_mutation(self) -> None:
        """OutputSpec is frozen; format assignment must raise."""
        spec = OutputSpec(path=Path("/out/r.pdf"), format="pdf")
        frozen_field = "format"
        with pytest.raises(AttributeError):
            setattr(spec, frozen_field, "html")

    def test_equality_structural(self) -> None:
        """Two OutputSpec with same fields must be equal."""
        a = OutputSpec(path=Path("/out/r.pdf"), format="pdf")
        b = OutputSpec(path=Path("/out/r.pdf"), format="pdf")
        assert a == b

    def test_inequality_different_path(self) -> None:
        """OutputSpec with different paths must not be equal."""
        a = OutputSpec(path=Path("/out/a.pdf"), format="pdf")
        b = OutputSpec(path=Path("/out/b.pdf"), format="pdf")
        assert a != b
