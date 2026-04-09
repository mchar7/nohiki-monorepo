"""Factories for event domain models."""

from __future__ import annotations

from nohiki.common.v1 import EventMetadata
from nohiki.job.listing.v1 import ListingCreated
from nohiki.user.pref.v1 import PrefCreated

from ._base import BetterprotoFactory


class EventMetadataFactory(BetterprotoFactory):
    """Factory for EventMetadata messages."""

    __model__ = EventMetadata


class ListingCreatedFactory(BetterprotoFactory):
    """Factory for ListingCreated event messages."""

    __model__ = ListingCreated


class PrefCreatedFactory(BetterprotoFactory):
    """Factory for PrefCreated event messages."""

    __model__ = PrefCreated
