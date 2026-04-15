from __future__ import annotations

import pytest
from job_ingest_discovery_service.core.models import DiscoveryRequest, DiscoveryResult
from job_ingest_discovery_service.providers.base import BaseProvider
from nohiki.common.v1 import JobBoardSource


class _TestProvider(BaseProvider):
    @property
    def name(self) -> str:
        return "test"

    @property
    def supported_sources(self) -> list[JobBoardSource]:
        return [JobBoardSource.INDEED, JobBoardSource.LINKEDIN]

    async def discover(self, request: DiscoveryRequest) -> DiscoveryResult:
        return DiscoveryResult(listings=[], provider_name=self.name)


def test_supports_source_true_for_supported_source() -> None:
    provider = _TestProvider()

    assert provider.supports_source(JobBoardSource.INDEED) is True


def test_supports_source_false_for_unsupported_source() -> None:
    provider = _TestProvider()

    assert provider.supports_source(JobBoardSource.GOOGLE) is False


@pytest.mark.asyncio
async def test_health_check_default_is_true() -> None:
    provider = _TestProvider()

    assert await provider.health_check() is True


def test_repr_includes_name_and_sources() -> None:
    provider = _TestProvider()

    value = repr(provider)

    assert "_TestProvider" in value
    assert "name='test'" in value
    assert "INDEED" in value
    assert "LINKEDIN" in value
