"""Cache key construction utilities."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CacheKeyBuilder:
    """Constructs cache keys with consistent prefixing and separation."""

    prefix: str = "doc"
    separator: str = ":"

    def raw_key(self, content_id: str) -> str:
        """Build key for raw document bytes."""
        return f"{self.prefix}{self.separator}raw{self.separator}{content_id}"

    def processed_key(self, content_hash: str, level_suffix: str = "") -> str:
        """Build key for processed document content."""
        base = f"{self.prefix}{self.separator}processed{self.separator}{content_hash}"
        return f"{base}{self.separator}{level_suffix}" if level_suffix else base

    def checksum_key(self, content_id: str) -> str:
        """Build key for content checksum."""
        return f"{self.prefix}{self.separator}checksum{self.separator}{content_id}"

    def task_key(self, task_id: str) -> str:
        """Build key for async task state."""
        return f"{self.prefix}{self.separator}task{self.separator}{task_id}"
