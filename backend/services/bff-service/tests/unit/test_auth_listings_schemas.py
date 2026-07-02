"""Unit tests for auth-listings Pydantic models and pipeline data types."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest
from bff_service.services.auth_listings.schemas import (
    AuthListingItem,
    AuthListingsResponse,
    WeightedCandidate,
)


class TestAuthListingItem:
    """Validate the public API response model for listing cards."""

    def test_validates_with_full_fields(self) -> None:
        """Model accepts all declared fields."""
        item = AuthListingItem(
            title="Backend Engineer",
            company_name="Acme Corp",
            location_raw="Berlin, Germany",
            work_arrangement="REMOTE",
            required_skills=["Python", "FastAPI"],
            posted_at=datetime.now(UTC),
            language="en",
        )
        assert item.title == "Backend Engineer"
        assert item.company_name == "Acme Corp"
        assert item.location_raw == "Berlin, Germany"
        assert item.work_arrangement == "REMOTE"
        assert item.required_skills == ["Python", "FastAPI"]
        assert item.language == "en"

    def test_optional_fields_accept_none(self) -> None:
        """Nullable fields (work_arrangement, language) accept None.

        ``location_raw`` is non-nullable to match the underlying NOT NULL
        projection column; the empty string represents 'no parsable location'.
        """
        item = AuthListingItem(
            title="SWE",
            company_name="X Corp",
            location_raw="",
            work_arrangement=None,
            required_skills=[],
            posted_at=datetime.now(UTC),
            language=None,
        )
        assert item.location_raw == ""
        assert item.work_arrangement is None
        assert item.language is None

    @pytest.mark.parametrize(
        "field_name",
        ["id", "listing_url", "description", "weight"],
    )
    def test_excluded_fields_not_present(self, field_name: str) -> None:
        """Security-sensitive fields must NOT exist on the model."""
        assert field_name not in AuthListingItem.model_fields


class TestAuthListingsResponse:
    """Validate the top-level auth-listings response wrapper."""

    def test_serializes_correctly(self) -> None:
        """Response model round-trips through model_dump / model_validate."""
        now = datetime.now(UTC)
        item = AuthListingItem(
            title="Data Scientist",
            company_name="DataCo",
            location_raw="Munich, Germany",
            work_arrangement="HYBRID",
            required_skills=["Python", "SQL"],
            posted_at=now,
            language="de",
        )
        response = AuthListingsResponse(listings=[item], country="DEU")

        data = response.model_dump(mode="json")
        assert data["country"] == "DEU"
        assert len(data["listings"]) == 1
        assert data["listings"][0]["title"] == "Data Scientist"

        # Round-trip
        restored = AuthListingsResponse.model_validate(data)
        assert restored.country == "DEU"
        assert restored.listings[0].title == "Data Scientist"

    def test_empty_listings(self) -> None:
        """Empty listings list is valid."""
        response = AuthListingsResponse(listings=[], country="USA")
        assert response.listings == []
        assert response.country == "USA"


class TestWeightedCandidate:
    """Validate the transient pipeline dataclass."""

    def _make_candidate(self, *, weight: float = 0.85) -> WeightedCandidate:
        """Build a WeightedCandidate with sensible defaults."""
        return WeightedCandidate(
            title="ML Engineer",
            company_name="AI Corp",
            location_raw="London, UK",
            work_arrangement="REMOTE",
            required_skills=["PyTorch"],
            posted_at=datetime.now(UTC),
            language="en",
            weight=weight,
        )

    def test_frozen_raises_on_direct_assignment(self) -> None:
        """Frozen dataclass rejects attribute assignment."""
        candidate = self._make_candidate()
        with pytest.raises(dataclasses.FrozenInstanceError):
            type(candidate).__setattr__(candidate, "weight", 0.5)

    def test_frozen_can_mutate_via_object_setattr(self) -> None:
        """object.__setattr__() bypasses frozen guard for test scenarios."""
        candidate = self._make_candidate(weight=0.85)
        object.__setattr__(candidate, "weight", 0.42)
        assert candidate.weight == pytest.approx(0.42)

    def test_has_slots(self) -> None:
        """WeightedCandidate uses __slots__ for memory efficiency."""
        assert hasattr(WeightedCandidate, "__slots__")

    def test_slots_prevent_arbitrary_attributes(self) -> None:
        """Slots prevent adding undeclared attributes."""
        candidate = self._make_candidate()
        with pytest.raises((AttributeError, TypeError)):
            type(candidate).__setattr__(candidate, "undeclared_field", "nope")

    def test_fields_match_schema(self) -> None:
        """Dataclass fields match the expected set."""
        field_names = {f.name for f in dataclasses.fields(WeightedCandidate)}
        expected = {
            "title",
            "company_name",
            "location_raw",
            "work_arrangement",
            "required_skills",
            "posted_at",
            "language",
            "weight",
        }
        assert field_names == expected
