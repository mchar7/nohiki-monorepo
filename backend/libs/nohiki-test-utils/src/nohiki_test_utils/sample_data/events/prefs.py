"""Pre-composed preference CDC event fixtures."""

from __future__ import annotations

from nohiki.user.pref.v1 import PrefCreated, PrefUpdated

from nohiki_test_utils.sample_data._common import make_event_metadata
from nohiki_test_utils.sample_data._ids import EVENT_PREF_CREATED_ID
from nohiki_test_utils.sample_data.prefs.software import BACKEND_ENGINEER_PREF

PREF_CREATED_BACKEND_ENGINEER = PrefCreated(
    metadata=make_event_metadata(
        event_id=EVENT_PREF_CREATED_ID,
        source_service="user-pref-service",
        correlation_id=EVENT_PREF_CREATED_ID,
    ),
    pref_id=BACKEND_ENGINEER_PREF.id,
    user_id=BACKEND_ENGINEER_PREF.user_id,
    pref_snapshot=BACKEND_ENGINEER_PREF,
)

PREF_UPDATED_BACKEND_ENGINEER = PrefUpdated(
    metadata=make_event_metadata(
        event_id="f2a3b4c5-d6e7-4f5a-9b8c-2d3e4f5a6b7c",
        source_service="user-pref-service",
        correlation_id="f2a3b4c5-d6e7-4f5a-9b8c-2d3e4f5a6b7c",
    ),
    pref_id=BACKEND_ENGINEER_PREF.id,
    user_id=BACKEND_ENGINEER_PREF.user_id,
    pref_snapshot=BACKEND_ENGINEER_PREF,
)
