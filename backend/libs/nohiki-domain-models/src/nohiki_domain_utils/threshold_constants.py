"""Shared threshold constants for notification and auto-tailoring features.

These values derive from the L2R scoring pipeline calibration:
- Sigmoid calibrator bounds: [0.02, 0.98] -> practical fit_score range [2, 98]
- Score tiers: 0-30 poor, 30-60 moderate, 60-75 good, 75-85 strong, 85+ excellent
- 50% = "good matches only" lower bound; 99% = practical ceiling (sigmoid cap)

All values are on the 0-100 percentage scale (matching proto / notification-service).
The BFF API layer converts to 0.0-1.0 ratio for its own models.
"""

from __future__ import annotations

from typing import Final

# Notification threshold: minimum fit_score to trigger notifications.
# None (absent) = notifications disabled for this preference.
NOTIFICATION_THRESHOLD_MIN: Final[int] = 50
NOTIFICATION_THRESHOLD_MAX: Final[int] = 99
DEFAULT_NOTIFICATION_THRESHOLD: Final[int] = 70

# Auto-tailor threshold: minimum fit_score for automatic document tailoring.
# None (absent) = auto-tailoring disabled for this preference.
AUTO_TAILOR_THRESHOLD_MIN: Final[int] = 50
AUTO_TAILOR_THRESHOLD_MAX: Final[int] = 99
DEFAULT_AUTO_TAILOR_THRESHOLD: Final[int] = 80

# Conversion factor between percentage (0-100) and ratio (0.0-1.0) scales.
PERCENTAGE_SCALE: Final[int] = 100
