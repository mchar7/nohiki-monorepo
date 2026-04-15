from __future__ import annotations

from types import SimpleNamespace

import pytest
from job_ingest_discovery_service.core.models import DiscoveryRequest, DiscoveryResult
from job_ingest_discovery_service.providers.base import BaseProvider
from job_ingest_discovery_service.providers.discovery import (
    _iter_provider_packages,
    _load_provider,
    discover_providers,
)
from nohiki.common.v1 import JobBoardSource


class _TestProvider(BaseProvider):
    @property
    def name(self) -> str:
        return "test"

    @property
    def supported_sources(self) -> list[JobBoardSource]:
        return [JobBoardSource.INDEED]

    async def discover(self, request: DiscoveryRequest) -> DiscoveryResult:
        return DiscoveryResult(listings=[], provider_name=self.name)


def test_iter_provider_packages_filters_non_pkgs_and_private(monkeypatch: pytest.MonkeyPatch) -> None:
    import job_ingest_discovery_service.providers.discovery as discovery_module

    monkeypatch.setattr(
        discovery_module.pkgutil,
        "iter_modules",
        lambda _paths: [
            SimpleNamespace(name="_private", ispkg=True),
            SimpleNamespace(name="notpkg", ispkg=False),
            SimpleNamespace(name="jobspy", ispkg=True),
        ],
    )

    assert _iter_provider_packages() == ["jobspy"]


def test_load_provider_returns_none_on_import_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import job_ingest_discovery_service.providers.discovery as discovery_module

    def _raise(_path: str) -> object:
        raise ImportError

    monkeypatch.setattr(discovery_module.importlib, "import_module", _raise)

    assert _load_provider("missing") is None


def test_load_provider_returns_none_when_missing_get_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    import job_ingest_discovery_service.providers.discovery as discovery_module

    monkeypatch.setattr(discovery_module.importlib, "import_module", lambda _p: object())

    assert _load_provider("nop") is None


def test_load_provider_returns_none_when_get_provider_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    import job_ingest_discovery_service.providers.discovery as discovery_module

    def _raise() -> None:
        msg = "boom"
        raise RuntimeError(msg)

    module = SimpleNamespace(get_provider=_raise)
    monkeypatch.setattr(discovery_module.importlib, "import_module", lambda _p: module)

    assert _load_provider("bad") is None


def test_discover_providers_returns_loaded_instances(monkeypatch: pytest.MonkeyPatch) -> None:
    import job_ingest_discovery_service.providers.discovery as discovery_module

    monkeypatch.setattr(discovery_module, "_iter_provider_packages", lambda: ["a", "b"])

    providers = [_TestProvider()]
    monkeypatch.setattr(discovery_module, "_load_provider", lambda _name: providers.pop() if providers else None)

    discovered = discover_providers()

    assert len(discovered) == 1
    assert discovered[0].name == "test"
