"""Enumeration types for seeding conflict resolution and source authority."""

from __future__ import annotations

import enum


class ConflictStrategy(enum.Enum):
    """How a source handles conflicts with existing data."""

    SKIP = "skip"
    VERSION_GATE_UPDATE = "version_gate_update"
    UPSERT = "upsert"


class SourceAuthority(enum.IntEnum):
    """Authority ranking for conflict resolution; higher value wins."""

    NOHIKI_LEARNED = 1
    TABIYA = 2
    CURATED = 3
