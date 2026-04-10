"""Tests for sample_data.events module."""

from __future__ import annotations

from uuid import UUID

from nohiki.common.v1 import EventMetadata, ListingReference, ListingStatus
from nohiki.job.listing.v1 import ListingCreated
from nohiki.user.pref.v1 import PrefCreated, PrefUpdated
from nohiki_test_utils.sample_data.events import (
    LISTING_CREATED_DATA_SCIENTIST,
    LISTING_CREATED_SENIOR_PYTHON,
    PREF_CREATED_BACKEND_ENGINEER,
    PREF_UPDATED_BACKEND_ENGINEER,
)

ALL_LISTING_EVENTS = [
    LISTING_CREATED_SENIOR_PYTHON,
    LISTING_CREATED_DATA_SCIENTIST,
]

ALL_PREF_EVENTS = [
    PREF_CREATED_BACKEND_ENGINEER,
    PREF_UPDATED_BACKEND_ENGINEER,
]


class TestListingEvents:
    """Tests for listing CDC events."""

    def test_all_are_listing_created_instances(self) -> None:
        """All listing events are ListingCreated instances."""
        for event in ALL_LISTING_EVENTS:
            assert isinstance(event, ListingCreated)

    def test_all_have_metadata(self) -> None:
        """All listing events have event metadata."""
        for event in ALL_LISTING_EVENTS:
            assert event.metadata is not None
            assert isinstance(event.metadata, EventMetadata)

    def test_all_have_valid_event_ids(self) -> None:
        """All listing events have valid UUID event IDs."""
        for event in ALL_LISTING_EVENTS:
            assert event.metadata is not None
            UUID(event.metadata.event_id)

    def test_all_have_source_service(self) -> None:
        """All listing events have source service set."""
        for event in ALL_LISTING_EVENTS:
            assert event.metadata is not None
            assert event.metadata.source_service == "job-storage-service"

    def test_all_have_correlation_ids(self) -> None:
        """All listing events have correlation IDs."""
        for event in ALL_LISTING_EVENTS:
            assert event.metadata is not None
            assert event.metadata.correlation_id
            UUID(event.metadata.correlation_id)

    def test_all_have_listing_references(self) -> None:
        """All listing events have listing references."""
        for event in ALL_LISTING_EVENTS:
            assert event.listing is not None
            assert isinstance(event.listing, ListingReference)
            UUID(event.listing.listing_id)

    def test_all_have_listing_snapshots(self) -> None:
        """All listing events have embedded listing snapshots (ECST)."""
        for event in ALL_LISTING_EVENTS:
            assert event.listing_snapshot is not None
            assert event.listing_snapshot.id
            assert event.listing_snapshot.title
            assert event.listing_snapshot.company_name

    def test_listing_id_matches_snapshot_id(self) -> None:
        """Listing reference ID matches snapshot ID."""
        for event in ALL_LISTING_EVENTS:
            assert event.listing is not None
            assert event.listing_snapshot is not None
            assert event.listing.listing_id == event.listing_snapshot.id

    def test_all_have_listing_status(self) -> None:
        """All listing events have listing status set."""
        for event in ALL_LISTING_EVENTS:
            assert event.listing_status is not None
            assert event.listing_status == ListingStatus.ACTIVE

    def test_all_have_was_updated_flag(self) -> None:
        """All listing events have was_updated flag."""
        for event in ALL_LISTING_EVENTS:
            assert event.was_updated is False

    def test_all_have_store_metadata(self) -> None:
        """All listing events have store_metadata dict."""
        for event in ALL_LISTING_EVENTS:
            assert event.store_metadata is not None
            assert isinstance(event.store_metadata, dict)


class TestPrefEvents:
    """Tests for preference CDC events."""

    def test_pref_created_is_correct_type(self) -> None:
        """Pref created event is PrefCreated instance."""
        assert isinstance(PREF_CREATED_BACKEND_ENGINEER, PrefCreated)

    def test_pref_updated_is_correct_type(self) -> None:
        """Pref updated event is PrefUpdated instance."""
        assert isinstance(PREF_UPDATED_BACKEND_ENGINEER, PrefUpdated)

    def test_all_have_metadata(self) -> None:
        """All pref events have event metadata."""
        for event in ALL_PREF_EVENTS:
            assert event.metadata is not None
            assert isinstance(event.metadata, EventMetadata)

    def test_all_have_valid_event_ids(self) -> None:
        """All pref events have valid UUID event IDs."""
        for event in ALL_PREF_EVENTS:
            assert event.metadata is not None
            UUID(event.metadata.event_id)

    def test_all_have_source_service(self) -> None:
        """All pref events have source service set."""
        for event in ALL_PREF_EVENTS:
            assert event.metadata is not None
            assert event.metadata.source_service == "user-pref-service"

    def test_all_have_correlation_ids(self) -> None:
        """All pref events have correlation IDs."""
        for event in ALL_PREF_EVENTS:
            assert event.metadata is not None
            assert event.metadata.correlation_id
            UUID(event.metadata.correlation_id)

    def test_all_have_pref_ids(self) -> None:
        """All pref events have valid pref IDs."""
        for event in ALL_PREF_EVENTS:
            assert event.pref_id
            UUID(event.pref_id)

    def test_all_have_user_ids(self) -> None:
        """All pref events have valid user IDs."""
        for event in ALL_PREF_EVENTS:
            assert event.user_id
            UUID(event.user_id)

    def test_all_have_pref_snapshots(self) -> None:
        """All pref events have embedded pref snapshots (ECST)."""
        for event in ALL_PREF_EVENTS:
            assert event.pref_snapshot is not None
            assert event.pref_snapshot.id
            assert event.pref_snapshot.user_id
            assert event.pref_snapshot.pref_name

    def test_pref_id_matches_snapshot_id(self) -> None:
        """Pref event ID matches snapshot ID."""
        for event in ALL_PREF_EVENTS:
            assert event.pref_snapshot is not None
            assert event.pref_id == event.pref_snapshot.id

    def test_user_id_matches_snapshot_user_id(self) -> None:
        """User ID matches snapshot user ID."""
        for event in ALL_PREF_EVENTS:
            assert event.pref_snapshot is not None
            assert event.user_id == event.pref_snapshot.user_id


class TestEventMetadataQuality:
    """Tests for event metadata quality and consistency."""

    def test_all_events_have_timestamps(self) -> None:
        """All events have timestamps in metadata."""
        all_events = ALL_LISTING_EVENTS + ALL_PREF_EVENTS
        for event in all_events:
            assert event.metadata is not None
            assert event.metadata.timestamp is not None

    def test_all_events_have_version(self) -> None:
        """All events have version in metadata."""
        all_events = ALL_LISTING_EVENTS + ALL_PREF_EVENTS
        for event in all_events:
            assert event.metadata is not None
            assert event.metadata.version
            assert event.metadata.version == "v1"

    def test_event_ids_are_unique(self) -> None:
        """All event IDs are unique across all events."""
        all_events = ALL_LISTING_EVENTS + ALL_PREF_EVENTS
        event_ids = [e.metadata.event_id for e in all_events if e.metadata is not None]
        assert len(event_ids) == len(set(event_ids))


class TestECSTCompliance:
    """Tests for Event-Carried State Transfer compliance."""

    def test_listing_events_carry_full_snapshots(self) -> None:
        """Listing events carry complete listing data (no lookup needed)."""
        for event in ALL_LISTING_EVENTS:
            snapshot = event.listing_snapshot
            assert snapshot is not None
            assert snapshot.id
            assert snapshot.title
            assert snapshot.company_name
            assert snapshot.description
            assert snapshot.location is not None
            assert snapshot.compensation is not None
            assert snapshot.skill_requirements

    def test_pref_events_carry_full_snapshots(self) -> None:
        """Pref events carry complete preference data (no lookup needed)."""
        for event in ALL_PREF_EVENTS:
            snapshot = event.pref_snapshot
            assert snapshot is not None
            assert snapshot.id
            assert snapshot.user_id
            assert snapshot.pref_name
            assert snapshot.search_keywords
            assert len(snapshot.user_skills) > 0
            assert len(snapshot.work_arrangements) > 0


class TestSpecificEvents:
    """Tests for specific event instances."""

    def test_senior_python_listing_created(self) -> None:
        """Senior Python listing created event has correct data."""
        event = LISTING_CREATED_SENIOR_PYTHON
        assert event.listing_snapshot is not None
        assert "Python" in event.listing_snapshot.title

    def test_data_scientist_listing_created(self) -> None:
        """Data scientist listing created event has correct data."""
        event = LISTING_CREATED_DATA_SCIENTIST
        assert event.listing_snapshot is not None
        assert "Data Scientist" in event.listing_snapshot.title

    def test_backend_engineer_pref_created(self) -> None:
        """Backend engineer pref created event has correct data."""
        event = PREF_CREATED_BACKEND_ENGINEER
        assert event.pref_snapshot is not None
        assert event.pref_snapshot.pref_name == "Backend Engineering Roles"

    def test_backend_engineer_pref_updated(self) -> None:
        """Backend engineer pref updated event has correct data."""
        event = PREF_UPDATED_BACKEND_ENGINEER
        assert event.pref_snapshot is not None
        assert event.pref_snapshot.pref_name == "Backend Engineering Roles"

    def test_pref_created_and_updated_same_pref(self) -> None:
        """Created and updated events reference the same preference."""
        assert PREF_CREATED_BACKEND_ENGINEER.pref_id == PREF_UPDATED_BACKEND_ENGINEER.pref_id
        assert PREF_CREATED_BACKEND_ENGINEER.user_id == PREF_UPDATED_BACKEND_ENGINEER.user_id
