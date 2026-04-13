"""JSearch provider for job discovery.

This provider uses the JSearch API (Google Jobs aggregator) to search for
job listings across multiple job boards and company career pages.
"""

from job_ingest_discovery_service.providers.base import BaseProvider

from .client import JSearchClient, SearchParams, get_jsearch_client, reset_jsearch_client
from .constants import SERVICE_NAME
from .exceptions import JSearchError, JSearchNotConfiguredError, JSearchRateLimitError
from .provider import JSearchProvider

__all__ = [
    "SERVICE_NAME",
    "JSearchClient",
    "JSearchError",
    "JSearchNotConfiguredError",
    "JSearchProvider",
    "JSearchRateLimitError",
    "SearchParams",
    "get_jsearch_client",
    "get_provider",
    "reset_jsearch_client",
]


def get_provider() -> BaseProvider:
    """Create and return a JSearch provider instance."""
    return JSearchProvider()
