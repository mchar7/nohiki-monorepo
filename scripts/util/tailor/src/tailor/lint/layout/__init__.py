"""Layout lint — post-render PDF-based rules.

The layout engine runs after the document has been rendered to PDF. Layout
metadata is extracted via a pluggable ``LayoutExtractor`` protocol so the
extractor implementation can be swapped later (e.g. pdfplumber today, a
DOM-based extractor tomorrow) without changing the rule classes or YAML
config shape.

Public exports:
    - ``LayoutExtractor`` — protocol for swapping extractors.
    - ``LayoutMetadata`` / ``ParagraphLayout`` / ``LineLayout`` — extractor output.
    - ``PdfPlumberLayoutExtractor`` — default pdfplumber implementation.
    - ``LayoutRuleRegistry`` + ``register_layout_rules`` — parallel to content
      rule registry for ``layout.*`` rule types.
    - ``run_layout_lint`` — drives extraction + rule evaluation for a rendered
      PDF + lint config.
"""

from tailor.lint.layout.extractor import (
    LayoutExtractor,
    LayoutMetadata,
    LineLayout,
    ParagraphLayout,
)
from tailor.lint.layout.pdfplumber_extractor import PdfPlumberLayoutExtractor
from tailor.lint.layout.rules import (
    LAYOUT_RULE_REGISTRY,
    LayoutRuleRegistry,
    MaxPagesExceededParams,
    MaxPagesExceededRule,
    OrphanDetectedParams,
    OrphanDetectedRule,
    PageOverflowParams,
    PageOverflowRule,
    register_layout_rules,
    run_layout_lint,
)

__all__ = [
    "LAYOUT_RULE_REGISTRY",
    "LayoutExtractor",
    "LayoutMetadata",
    "LayoutRuleRegistry",
    "LineLayout",
    "MaxPagesExceededParams",
    "MaxPagesExceededRule",
    "OrphanDetectedParams",
    "OrphanDetectedRule",
    "PageOverflowParams",
    "PageOverflowRule",
    "ParagraphLayout",
    "PdfPlumberLayoutExtractor",
    "register_layout_rules",
    "run_layout_lint",
]
