"""Factory for listing domain models."""

from __future__ import annotations

from nohiki.job.listing.v1 import ListingSnapshot

from ._base import BetterprotoFactory


class ListingSnapshotFactory(BetterprotoFactory):
    """Factory for ListingSnapshot messages."""

    __model__ = ListingSnapshot
