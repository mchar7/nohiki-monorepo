"""Factories for common domain models."""

from __future__ import annotations

from nohiki.common.v1 import Compensation, Location

from ._base import BetterprotoFactory


class LocationFactory(BetterprotoFactory):
    """Factory for Location messages."""

    __model__ = Location


class CompensationFactory(BetterprotoFactory):
    """Factory for Compensation messages."""

    __model__ = Compensation
