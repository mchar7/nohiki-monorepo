"""Business-logic constants for the auth-listings weighting formula.

These are domain invariants, NOT environment-configurable.
The weight formula is: geographic_tier x recency_multiplier x language_bonus.
"""

from __future__ import annotations

GEOGRAPHIC_TIER_SAME_COUNTRY: float = 1.0
"""Weight multiplier when listing is in the same country as the user."""

GEOGRAPHIC_TIER_BACKFILL: float = 0.15
"""Weight multiplier for backfill listings from other countries."""

RECENCY_BRACKETS: tuple[tuple[int, float], ...] = (
    (0, 1.0),
    (2, 0.9),
    (7, 0.75),
    (14, 0.5),
    (30, 0.3),
)
"""Age-to-multiplier mapping. Each tuple is (max_days_old, multiplier).

Walk the brackets: if the listing's age in days is <= the bracket's threshold,
use that bracket's multiplier. If beyond all brackets, use RECENCY_FLOOR.
"""

RECENCY_FLOOR: float = 0.15
"""Minimum recency multiplier for listings older than the last bracket."""

LANGUAGE_MISMATCH_FACTOR: float = 0.7
"""Multiplier applied when listing language differs from user's preferred language."""
