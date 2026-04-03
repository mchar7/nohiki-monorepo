"""Tests for FreshnessTrackingMixin."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from nohiki_db_utils import FreshnessTrackingMixin


class FakeResource(FreshnessTrackingMixin):
    """Minimal resource for testing freshness tracking."""

    __staleness_days__ = 30

    def __init__(
        self,
        *,
        last_used_at: datetime | None = None,
        usage_count: int = 0,
    ) -> None:
        self.last_used_at = last_used_at
        self.usage_count = usage_count


class TestRecordUsage:
    """Tests for FreshnessTrackingMixin.record_usage()."""

    def test_record_usage_sets_timestamp(self) -> None:
        """record_usage sets last_used_at to current time."""
        resource = FakeResource()
        assert resource.last_used_at is None

        resource.record_usage()

        assert resource.last_used_at is not None
        assert (datetime.now(UTC) - resource.last_used_at).total_seconds() < 2

    def test_record_usage_increments_count(self) -> None:
        """record_usage increments usage_count by 1."""
        resource = FakeResource()
        assert resource.usage_count == 0

        resource.record_usage()
        assert resource.usage_count == 1

        resource.record_usage()
        assert resource.usage_count == 2

        resource.record_usage()
        assert resource.usage_count == 3

    def test_record_usage_updates_timestamp_on_subsequent_calls(self) -> None:
        """Each record_usage call updates the timestamp."""
        resource = FakeResource()
        resource.record_usage()
        first_ts = resource.last_used_at

        resource.record_usage()
        second_ts = resource.last_used_at

        assert second_ts is not None
        assert first_ts is not None
        assert second_ts >= first_ts


class TestIsStaleness:
    """Tests for FreshnessTrackingMixin.is_stale property."""

    def test_never_used_is_stale(self) -> None:
        """Resource that has never been used is considered stale."""
        resource = FakeResource()
        assert resource.is_stale is True

    def test_recently_used_is_not_stale(self) -> None:
        """Resource used within the staleness window is not stale."""
        resource = FakeResource(last_used_at=datetime.now(UTC) - timedelta(days=5))
        assert resource.is_stale is False

    def test_used_at_boundary_is_not_stale(self) -> None:
        """Resource used exactly at the staleness boundary is not stale."""
        # 29 days ago with __staleness_days__ = 30
        resource = FakeResource(last_used_at=datetime.now(UTC) - timedelta(days=29))
        assert resource.is_stale is False

    def test_used_beyond_boundary_is_stale(self) -> None:
        """Resource used beyond the staleness window is stale."""
        resource = FakeResource(last_used_at=datetime.now(UTC) - timedelta(days=31))
        assert resource.is_stale is True

    def test_custom_staleness_days(self) -> None:
        """Custom __staleness_days__ is respected."""

        class LongLivedResource(FreshnessTrackingMixin):
            __staleness_days__ = 365

            def __init__(self, *, last_used_at: datetime | None = None, usage_count: int = 0) -> None:
                self.last_used_at = last_used_at
                self.usage_count = usage_count

        resource = LongLivedResource(last_used_at=datetime.now(UTC) - timedelta(days=200))
        assert resource.is_stale is False

        old_resource = LongLivedResource(last_used_at=datetime.now(UTC) - timedelta(days=400))
        assert old_resource.is_stale is True

    def test_freshly_recorded_is_not_stale(self) -> None:
        """Resource becomes fresh after record_usage()."""
        resource = FakeResource(last_used_at=datetime.now(UTC) - timedelta(days=60))
        assert resource.is_stale is True

        resource.record_usage()
        assert resource.is_stale is False


class TestDaysSinceLastUse:
    """Tests for FreshnessTrackingMixin.days_since_last_use property."""

    def test_never_used_returns_none(self) -> None:
        """Never-used resource returns None for days_since_last_use."""
        resource = FakeResource()
        assert resource.days_since_last_use is None

    def test_recently_used_returns_days(self) -> None:
        """Returns correct number of days since last use."""
        resource = FakeResource(last_used_at=datetime.now(UTC) - timedelta(days=10))
        assert resource.days_since_last_use == 10

    def test_just_used_returns_zero(self) -> None:
        """Resource used today returns 0 days."""
        resource = FakeResource()
        resource.record_usage()
        assert resource.days_since_last_use == 0


class TestDefaultStalenessWindow:
    """Tests for default __staleness_days__ value."""

    def test_default_is_90_days(self) -> None:
        """Default staleness window is 90 days."""
        assert FreshnessTrackingMixin.__staleness_days__ == 90
