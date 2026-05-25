"""Tests for CheckRegistry auto-discovery and filtering."""

from __future__ import annotations

import pytest
from health_check.core.base import HealthCheck
from health_check.core.models import CheckCategory, CheckMetadata, CheckResult, CheckStatus
from health_check.core.registry import CheckRegistry
from health_check.platform.models import PlatformTarget

from tests.conftest import make_metadata

if __name__ != "__main__":
    from health_check.platform.protocol import Platform


class _AlphaCheck(HealthCheck):
    @property
    def metadata(self) -> CheckMetadata:
        return make_metadata(
            check_id="alpha",
            category=CheckCategory.INFRASTRUCTURE,
            platforms=frozenset({PlatformTarget.COMPOSE}),
        )

    async def execute(self, platform: Platform) -> CheckResult:
        return self._make_result(CheckStatus.PASSED, "ok")


class _BetaCheck(HealthCheck):
    @property
    def metadata(self) -> CheckMetadata:
        return make_metadata(
            check_id="beta",
            category=CheckCategory.DATABASE,
            platforms=frozenset({PlatformTarget.KUBERNETES}),
        )

    async def execute(self, platform: Platform) -> CheckResult:
        return self._make_result(CheckStatus.PASSED, "ok")


class _GammaCheck(HealthCheck):
    @property
    def metadata(self) -> CheckMetadata:
        return make_metadata(
            check_id="gamma",
            category=CheckCategory.INFRASTRUCTURE,
            platforms=frozenset({PlatformTarget.COMPOSE, PlatformTarget.KUBERNETES}),
        )

    async def execute(self, platform: Platform) -> CheckResult:
        return self._make_result(CheckStatus.PASSED, "ok")


@pytest.fixture
def registry_with_checks() -> CheckRegistry:
    """Registry pre-populated with alpha, beta, and gamma checks."""
    reg = CheckRegistry()
    reg.register(_AlphaCheck())
    reg.register(_BetaCheck())
    reg.register(_GammaCheck())
    return reg


class TestCheckRegistry:
    def test_register_and_len(self, registry_with_checks: CheckRegistry) -> None:
        assert len(registry_with_checks) == 3

    def test_all_checks(self, registry_with_checks: CheckRegistry) -> None:
        ids = {c.metadata.check_id for c in registry_with_checks.all_checks}
        assert ids == {"alpha", "beta", "gamma"}

    def test_get_check_by_id(self, registry_with_checks: CheckRegistry) -> None:
        check = registry_with_checks.get_check("alpha")
        assert check is not None
        assert check.metadata.check_id == "alpha"

    def test_get_check_missing_returns_none(self, registry_with_checks: CheckRegistry) -> None:
        assert registry_with_checks.get_check("nonexistent") is None

    def test_register_rejects_duplicate_id(self, registry_with_checks: CheckRegistry) -> None:
        reg = CheckRegistry()
        reg.register(_AlphaCheck())
        with pytest.raises(ValueError, match="Duplicate health check id: alpha"):
            reg.register(_AlphaCheck())

    def test_filter_by_platform_compose(self, registry_with_checks: CheckRegistry) -> None:
        checks = registry_with_checks.get_checks(platform=PlatformTarget.COMPOSE)
        ids = {c.metadata.check_id for c in checks}
        assert "alpha" in ids
        assert "gamma" in ids
        assert "beta" not in ids

    def test_filter_by_platform_k8s(self, registry_with_checks: CheckRegistry) -> None:
        checks = registry_with_checks.get_checks(platform=PlatformTarget.KUBERNETES)
        ids = {c.metadata.check_id for c in checks}
        assert "beta" in ids
        assert "gamma" in ids
        assert "alpha" not in ids

    def test_filter_by_category(self, registry_with_checks: CheckRegistry) -> None:
        checks = registry_with_checks.get_checks(categories=frozenset({CheckCategory.INFRASTRUCTURE}))
        ids = {c.metadata.check_id for c in checks}
        assert ids == {"alpha", "gamma"}

    def test_filter_by_check_ids(self, registry_with_checks: CheckRegistry) -> None:
        checks = registry_with_checks.get_checks(check_ids=frozenset({"alpha", "beta"}))
        ids = {c.metadata.check_id for c in checks}
        assert ids == {"alpha", "beta"}

    def test_exclude_ids(self, registry_with_checks: CheckRegistry) -> None:
        checks = registry_with_checks.get_checks(excluded_ids=frozenset({"alpha"}))
        ids = {c.metadata.check_id for c in checks}
        assert "alpha" not in ids
        assert "beta" in ids

    def test_no_filters_returns_all(self, registry_with_checks: CheckRegistry) -> None:
        checks = registry_with_checks.get_checks()
        assert len(checks) == 3

    def test_combined_platform_and_category_filter(self, registry_with_checks: CheckRegistry) -> None:
        checks = registry_with_checks.get_checks(
            platform=PlatformTarget.COMPOSE,
            categories=frozenset({CheckCategory.INFRASTRUCTURE}),
        )
        ids = {c.metadata.check_id for c in checks}
        assert ids == {"alpha", "gamma"}

    def test_discover_finds_real_checks(self) -> None:
        reg = CheckRegistry()
        reg.discover()
        assert len(reg) > 0

    def test_discover_registers_concrete_checks_only(self) -> None:
        reg = CheckRegistry()
        reg.discover()
        for check in reg.all_checks:
            assert not getattr(check.__class__, "__abstractmethods__", None)

    def test_discover_idempotent_on_collision(self) -> None:
        reg1 = CheckRegistry()
        reg1.discover()
        reg2 = CheckRegistry()
        reg2.discover()
        assert len(reg1) == len(reg2)

    def test_discover_check_ids_unique(self) -> None:
        reg = CheckRegistry()
        reg.discover()
        ids = [c.metadata.check_id for c in reg.all_checks]
        assert len(ids) == len(set(ids))

    def test_all_concrete_subclasses_recursive(self) -> None:
        from health_check.core.registry import _all_concrete_subclasses

        class _Base(HealthCheck):
            pass

        class _Mid(_Base):
            @property
            def metadata(self) -> CheckMetadata:
                return make_metadata(check_id="mid")

            async def execute(self, platform: Platform) -> CheckResult:
                return self._make_result(CheckStatus.PASSED, "ok")

        class _Leaf(_Mid):
            @property
            def metadata(self) -> CheckMetadata:
                return make_metadata(check_id="leaf")

        subclasses = list(_all_concrete_subclasses(_Base))
        ids = {c.metadata.check_id for c in (cls() for cls in subclasses)}
        assert "mid" in ids
        assert "leaf" in ids
