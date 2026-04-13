"""Provider abstraction layer for job discovery.

This module defines source-agnostic types and interfaces that allow
the discovery service to work with multiple job data sources without
being tightly coupled to any specific library or API.
"""

from job_ingest_discovery_service.core.models import (
    DiscoveryLocation,
    DiscoveryRequest,
    DiscoveryResult,
    RawListing,
)
from job_ingest_discovery_service.providers.base import BaseProvider
from job_ingest_discovery_service.providers.registry import ProviderRegistry, get_provider_registry
from job_ingest_discovery_service.providers.types import location_to_search_string

__all__ = [
    "BaseProvider",
    "DiscoveryLocation",
    "DiscoveryRequest",
    "DiscoveryResult",
    "ProviderRegistry",
    "RawListing",
    "get_provider_registry",
    "location_to_search_string",
]
