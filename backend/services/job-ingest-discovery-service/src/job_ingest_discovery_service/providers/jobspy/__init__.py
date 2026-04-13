"""JobSpy provider implementation."""

from job_ingest_discovery_service.providers.base import BaseProvider
from job_ingest_discovery_service.providers.jobspy.provider import JobSpyProvider

__all__ = ["JobSpyProvider", "get_provider"]


def get_provider() -> BaseProvider:
    """Create and return a JobSpy provider instance."""
    return JobSpyProvider()
