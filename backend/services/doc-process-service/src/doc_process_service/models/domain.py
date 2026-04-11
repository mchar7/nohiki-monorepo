"""Domain models for document processing.

Uses proto models from nohiki.doc.process.v1 as canonical domain models.
Only provides additional configuration/result wrappers not defined in proto.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from nohiki.doc.process.v1 import ProcessedDocumentSnapshot, ProcessingLevel


@dataclass(frozen=True, slots=True)
class ProcessingOptions:
    """Immutable, hashable processing configuration for Docling client."""

    enable_ocr: bool = False
    ocr_languages: tuple[str, ...] = ()
    extract_tables: bool = True
    extract_images: bool = False
    enable_vlm_descriptions: bool = False

    @property
    def level(self) -> ProcessingLevel:
        """Determine effective processing level from options."""
        if self.enable_vlm_descriptions:
            return ProcessingLevel.FULL
        if self.extract_images:
            return ProcessingLevel.IMAGES
        if self.enable_ocr:
            return ProcessingLevel.OCR
        if self.extract_tables:
            return ProcessingLevel.TABLES
        return ProcessingLevel.BASIC

    def to_cache_key_part(self) -> str:
        """Generate deterministic hash for cache key construction."""
        data = {
            "ocr": self.enable_ocr,
            "ocr_langs": self.ocr_languages,
            "tables": self.extract_tables,
            "images": self.extract_images,
            "vlm": self.enable_vlm_descriptions,
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:16]


def is_snapshot_empty(snapshot: ProcessedDocumentSnapshot) -> bool:
    """Check if snapshot content extraction yielded no results."""
    return not snapshot.markdown.strip() and snapshot.table_count == 0


@dataclass(frozen=True, slots=True)
class ProcessingResult:
    """Result of a processing operation with either content or error."""

    content: ProcessedDocumentSnapshot | None = None
    error: str | None = None
    is_retryable: bool = False

    @property
    def success(self) -> bool:
        """Check if processing completed successfully."""
        return self.content is not None and self.error is None

    @property
    def is_cacheable(self) -> bool:
        """Check if result should be cached."""
        return self.success and self.content is not None and not is_snapshot_empty(self.content)
