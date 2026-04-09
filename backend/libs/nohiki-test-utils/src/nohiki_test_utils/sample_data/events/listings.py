"""Pre-composed listing CDC event fixtures."""

from __future__ import annotations

from nohiki.common.v1 import ListingReference, ListingStatus
from nohiki.job.listing.v1 import ListingCreated

from nohiki_test_utils.sample_data._common import make_event_metadata
from nohiki_test_utils.sample_data._ids import (
    EVENT_SENIOR_PYTHON_LISTING_CREATED_ID,
)
from nohiki_test_utils.sample_data.listings.software import (
    DATA_SCIENTIST_REMOTE,
    SENIOR_PYTHON_REMOTE,
)

LISTING_CREATED_SENIOR_PYTHON = ListingCreated(
    metadata=make_event_metadata(
        event_id=EVENT_SENIOR_PYTHON_LISTING_CREATED_ID,
        source_service="job-storage-service",
        correlation_id=EVENT_SENIOR_PYTHON_LISTING_CREATED_ID,
    ),
    listing=ListingReference(listing_id=SENIOR_PYTHON_REMOTE.id),
    was_updated=False,
    listing_status=ListingStatus.ACTIVE,
    store_metadata={},
    listing_snapshot=SENIOR_PYTHON_REMOTE,
)

LISTING_CREATED_DATA_SCIENTIST = ListingCreated(
    metadata=make_event_metadata(
        event_id="e1f2a3b4-c5d6-4e5f-9a8b-1c2d3e4f5a6b",
        source_service="job-storage-service",
        correlation_id="e1f2a3b4-c5d6-4e5f-9a8b-1c2d3e4f5a6b",
    ),
    listing=ListingReference(listing_id=DATA_SCIENTIST_REMOTE.id),
    was_updated=False,
    listing_status=ListingStatus.ACTIVE,
    store_metadata={},
    listing_snapshot=DATA_SCIENTIST_REMOTE,
)
