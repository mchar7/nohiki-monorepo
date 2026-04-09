"""Tests for polyfactory-based factories."""

from __future__ import annotations

from datetime import datetime

from nohiki.common.v1 import (
    Compensation,
    EventMetadata,
    Location,
    WorkArrangement,
)
from nohiki.job.listing.v1 import ListingCreated, ListingSnapshot
from nohiki.user.pref.v1 import PrefCreated, SearchPrefSnapshot
from nohiki_test_utils.factories import (
    CompensationFactory,
    EventMetadataFactory,
    ListingCreatedFactory,
    ListingSnapshotFactory,
    LocationFactory,
    PrefCreatedFactory,
    SearchPrefSnapshotFactory,
)


class TestLocationFactory:
    """Tests for LocationFactory."""

    def test_build_creates_valid_location(self) -> None:
        """Factory builds valid Location instance."""
        location = LocationFactory.build()
        assert isinstance(location, Location)
        assert location.country

    def test_build_with_overrides(self) -> None:
        """Factory respects field overrides."""
        location = LocationFactory.build(city="San Francisco", state_province="CA")
        assert location.city == "San Francisco"
        assert location.state_province == "CA"

    def test_batch_creates_multiple_instances(self) -> None:
        """Factory batch creates multiple unique instances."""
        locations = LocationFactory.batch(5)
        assert len(locations) == 5
        assert all(isinstance(loc, Location) for loc in locations)


class TestCompensationFactory:
    """Tests for CompensationFactory."""

    def test_build_creates_valid_compensation(self) -> None:
        """Factory builds valid Compensation instance."""
        comp = CompensationFactory.build()
        assert isinstance(comp, Compensation)

    def test_build_with_overrides(self) -> None:
        """Factory respects field overrides."""
        comp = CompensationFactory.build()
        assert isinstance(comp, Compensation)

    def test_batch_creates_multiple_instances(self) -> None:
        """Factory batch creates multiple unique instances."""
        comps = CompensationFactory.batch(3)
        assert len(comps) == 3
        assert all(isinstance(c, Compensation) for c in comps)


class TestEventMetadataFactory:
    """Tests for EventMetadataFactory."""

    def test_build_creates_valid_metadata(self) -> None:
        """Factory builds valid EventMetadata instance."""
        metadata = EventMetadataFactory.build()
        assert isinstance(metadata, EventMetadata)
        assert metadata.event_id
        assert metadata.timestamp is not None
        assert isinstance(metadata.timestamp, datetime)

    def test_timestamp_is_timezone_aware(self) -> None:
        """Generated timestamps are timezone-aware for betterproto2 compatibility."""
        metadata = EventMetadataFactory.build()
        assert metadata.timestamp is not None
        assert metadata.timestamp.tzinfo is not None

    def test_build_with_overrides(self) -> None:
        """Factory respects field overrides."""
        metadata = EventMetadataFactory.build(
            event_id="custom-event-id",
            source_service="test-service",
        )
        assert metadata.event_id == "custom-event-id"
        assert metadata.source_service == "test-service"


class TestListingSnapshotFactory:
    """Tests for ListingSnapshotFactory."""

    def test_build_creates_valid_listing(self) -> None:
        """Factory builds valid ListingSnapshot instance."""
        listing = ListingSnapshotFactory.build()
        assert isinstance(listing, ListingSnapshot)
        assert listing.id
        assert listing.title
        assert listing.company_name

    def test_build_with_overrides(self) -> None:
        """Factory respects field overrides."""
        listing = ListingSnapshotFactory.build(
            title="Senior Python Engineer",
            work_arrangement=WorkArrangement.REMOTE,
        )
        assert listing.title == "Senior Python Engineer"
        assert listing.work_arrangement == WorkArrangement.REMOTE

    def test_batch_creates_multiple_instances(self) -> None:
        """Factory batch creates multiple unique instances."""
        listings = ListingSnapshotFactory.batch(10)
        assert len(listings) == 10
        assert all(isinstance(listing, ListingSnapshot) for listing in listings)
        ids = [listing.id for listing in listings]
        assert len(ids) == len(set(ids))

    def test_serialization_roundtrip(self) -> None:
        """Factory-generated instances can be serialized and deserialized."""
        listing = ListingSnapshotFactory.build()
        listing_dict = listing.to_dict()
        assert isinstance(listing_dict, dict)
        assert listing_dict["id"] == listing.id
        assert listing_dict["title"] == listing.title


class TestSearchPrefSnapshotFactory:
    """Tests for SearchPrefSnapshotFactory."""

    def test_build_creates_valid_pref(self) -> None:
        """Factory builds valid SearchPrefSnapshot instance."""
        pref = SearchPrefSnapshotFactory.build()
        assert isinstance(pref, SearchPrefSnapshot)
        assert pref.id
        assert pref.user_id
        assert pref.pref_name

    def test_build_with_overrides(self) -> None:
        """Factory respects field overrides."""
        pref = SearchPrefSnapshotFactory.build(
            pref_name="Test Preference",
            search_keywords=["python", "backend"],
        )
        assert pref.pref_name == "Test Preference"
        assert pref.search_keywords == ["python", "backend"]

    def test_batch_creates_multiple_instances(self) -> None:
        """Factory batch creates multiple unique instances."""
        prefs = SearchPrefSnapshotFactory.batch(5)
        assert len(prefs) == 5
        assert all(isinstance(pref, SearchPrefSnapshot) for pref in prefs)
        ids = [pref.id for pref in prefs]
        assert len(ids) == len(set(ids))

    def test_serialization_roundtrip(self) -> None:
        """Factory-generated instances can be serialized and deserialized."""
        pref = SearchPrefSnapshotFactory.build()
        pref_dict = pref.to_dict()
        assert isinstance(pref_dict, dict)
        assert pref_dict["id"] == pref.id


class TestListingCreatedFactory:
    """Tests for ListingCreatedFactory."""

    def test_build_creates_valid_event(self) -> None:
        """Factory builds valid ListingCreated event."""
        event = ListingCreatedFactory.build()
        assert isinstance(event, ListingCreated)
        assert event.metadata is not None
        assert event.listing_snapshot is not None

    def test_build_with_overrides(self) -> None:
        """Factory respects field overrides."""
        custom_snapshot = ListingSnapshotFactory.build(title="Custom Title")
        event = ListingCreatedFactory.build(listing_snapshot=custom_snapshot)
        assert event.listing_snapshot is not None
        assert event.listing_snapshot.title == "Custom Title"


class TestPrefCreatedFactory:
    """Tests for PrefCreatedFactory."""

    def test_build_creates_valid_event(self) -> None:
        """Factory builds valid PrefCreated event."""
        event = PrefCreatedFactory.build()
        assert isinstance(event, PrefCreated)
        assert event.metadata is not None
        assert event.pref_snapshot is not None

    def test_build_with_overrides(self) -> None:
        """Factory respects field overrides."""
        custom_snapshot = SearchPrefSnapshotFactory.build(pref_name="Custom Pref")
        event = PrefCreatedFactory.build(pref_snapshot=custom_snapshot)
        assert event.pref_snapshot is not None
        assert event.pref_snapshot.pref_name == "Custom Pref"


class TestFactoryFixtures:
    """Tests for pytest fixture integration."""

    def test_listing_snapshot_factory_fixture(
        self,
        listing_snapshot_factory: type[ListingSnapshotFactory],
    ) -> None:
        """Listing factory fixture is available and functional."""
        listing = listing_snapshot_factory.build()
        assert isinstance(listing, ListingSnapshot)

    def test_search_pref_snapshot_factory_fixture(
        self,
        search_pref_snapshot_factory: type[SearchPrefSnapshotFactory],
    ) -> None:
        """Pref factory fixture is available and functional."""
        pref = search_pref_snapshot_factory.build()
        assert isinstance(pref, SearchPrefSnapshot)

    def test_sample_listing_fixture(self, sample_listing: ListingSnapshot) -> None:
        """Sample listing fixture provides curated persona."""
        assert isinstance(sample_listing, ListingSnapshot)
        assert sample_listing.id
        assert sample_listing.title

    def test_sample_pref_fixture(self, sample_pref: SearchPrefSnapshot) -> None:
        """Sample pref fixture provides curated persona."""
        assert isinstance(sample_pref, SearchPrefSnapshot)
        assert sample_pref.id
        assert sample_pref.pref_name
