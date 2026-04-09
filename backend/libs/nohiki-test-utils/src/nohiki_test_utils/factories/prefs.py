"""Factory for preference domain models."""

from __future__ import annotations

from nohiki.user.pref.v1 import SearchPrefSnapshot

from ._base import BetterprotoFactory


class SearchPrefSnapshotFactory(BetterprotoFactory):
    """Factory for SearchPrefSnapshot messages."""

    __model__ = SearchPrefSnapshot
