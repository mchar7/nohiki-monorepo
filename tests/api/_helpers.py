"""Shared helpers for API tests."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from requests.exceptions import RequestException

if TYPE_CHECKING:
    from .client import NohikiClient

logger = logging.getLogger("nohiki-api-tests")


def _is_profile_data_complete(profile: dict) -> bool:
    """Check if profile has required data for meaningful ML scoring."""
    salary = profile.get("salary_preference") or {}
    experience = profile.get("experience_preference") or {}
    return bool(
        salary.get("min_salary") is not None
        and experience.get("experience_years") is not None
        and profile.get("work_arrangements"),
    )


def poll_for_complete_profile(
    client: NohikiClient,
    pref_id: str,
    timeout: int = 30,
) -> dict | None:
    """Poll until profile update propagates through the CDC pipeline."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            profile = client.get_profile(pref_id)
        except (RequestException, KeyError, ValueError) as exc:
            # Projection lag is transient during CDC propagation.
            logger.debug("Profile fetch transient error: %s", exc)
        else:
            if _is_profile_data_complete(profile):
                logger.info("Profile update propagated: %s", pref_id)
                return profile
        time.sleep(1.0)
    logger.warning("Timed out waiting for profile update: %s", pref_id)
    return None
