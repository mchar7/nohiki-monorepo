"""Centralized content hashing for cross-provider deduplication."""

from __future__ import annotations

import hashlib


def compute_content_hash(title: str, company: str, description: str) -> str:
    """Compute SHA-256 hash of job content for deduplication.

    Uses title + company + description to detect duplicates across providers.
    Same job from multiple providers will produce identical hash.
    """
    normalized = f"{title.strip().lower()}|{company.strip().lower()}|{description.strip()}"
    return hashlib.sha256(normalized.encode()).hexdigest()
