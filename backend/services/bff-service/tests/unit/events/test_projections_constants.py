"""Tests for projections constants module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestProjectionConstants:
    """Tests for projection constants configuration."""

    def test_projection_priority_group_id_format(self) -> None:
        """Should format priority group_id with kafka consumer group suffix."""
        from bff_service.events.projections._constants import (
            projection_priority_group_id,
        )

        assert projection_priority_group_id.endswith("-projections-priority")

    def test_projection_bulk_group_id_format(self) -> None:
        """Should format bulk group_id with kafka consumer group suffix."""
        from bff_service.events.projections._constants import projection_bulk_group_id

        assert projection_bulk_group_id.endswith("-projections-bulk")

    def test_missing_database_config_raises_runtime_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should raise RuntimeError when database is not configured."""
        import importlib
        import sys

        mock_settings = MagicMock()
        mock_settings.kafka.consumer_group = "test-group"
        mock_settings.database = None

        monkeypatch.delitem(sys.modules, "bff_service.events.projections._constants", raising=False)

        with (
            patch("bff_service.core.config.get_settings", return_value=mock_settings),
            pytest.raises(RuntimeError, match="DATABASE to be configured"),
        ):
            importlib.import_module("bff_service.events.projections._constants")
