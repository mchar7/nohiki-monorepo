"""Shared type aliases for tailor CLI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

ImageFormat = Literal["png", "jpeg", "webp"]
RenderOutputFormat = Literal["pdf", "html", "text", "png", "jpeg", "webp"]
OutputFormat = Literal["pdf", "html", "text", "json", "png", "jpeg", "webp"]

type JsonValue = str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]
type JsonDict = dict[str, JsonValue]

_EXTENSION_FORMAT: dict[str, OutputFormat] = {
    ".pdf": "pdf",
    ".html": "html",
    ".htm": "html",
    ".txt": "text",
    ".json": "json",
    ".png": "png",
    ".jpeg": "jpeg",
    ".jpg": "jpeg",
    ".webp": "webp",
}


def infer_output_format(path: Path) -> OutputFormat:
    """Infer output format from file extension.

    Args:
        path: Output file path with extension.

    Returns:
        The inferred output format.

    Raises:
        ValueError: If the extension is not recognized.
    """
    ext = path.suffix.lower()
    if ext not in _EXTENSION_FORMAT:
        supported = ", ".join(sorted(_EXTENSION_FORMAT))
        msg = f"Unsupported output extension '{ext}'. Supported: {supported}"
        raise ValueError(msg)
    return _EXTENSION_FORMAT[ext]


@dataclass(frozen=True, slots=True)
class OutputSpec:
    """A single output target with format inferred from path.

    Args:
        path: Destination file path for this output.
        format: Output format, inferred from the path extension.
    """

    path: Path
    format: OutputFormat
