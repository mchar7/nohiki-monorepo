"""Tests for OutboxMetrics class."""

from __future__ import annotations

from nohiki_db_utils.outbox_metrics import OutboxMetrics, get_outbox_metrics


class TestOutboxMetrics:
    """Tests for OutboxMetrics OTel instrumentation."""

    def test_singleton_instance(self) -> None:
        """get_outbox_metrics returns the same instance on repeated calls."""
        m1 = get_outbox_metrics()
        m2 = get_outbox_metrics()
        assert m1 is m2

    def test_record_write_does_not_raise(self) -> None:
        """record_write completes without error."""
        m = OutboxMetrics()
        m.record_write(
            event_type="job-listing.cdc.listing-created.v1",
            aggregate_type="job",
            duration_seconds=0.005,
            payload_bytes=1024,
        )

    def test_record_error_does_not_raise(self) -> None:
        """record_error completes without error."""
        m = OutboxMetrics()
        m.record_error(
            event_type="job-listing.cdc.listing-created.v1",
            error_type="IntegrityError",
        )

    def test_metrics_instruments_created(self) -> None:
        """All expected metric instruments are created."""
        m = OutboxMetrics()
        assert m.writes is not None
        assert m.write_duration is not None
        assert m.payload_size is not None
        assert m.errors is not None
