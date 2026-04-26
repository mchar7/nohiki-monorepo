"""Unit tests for events/__init__.py module."""

from __future__ import annotations


class TestModuleExports:
    """Tests for module exports."""

    def test_exports_publishers(self) -> None:
        """Test that individual publishers are exported."""
        from user_auth_service.events import (
            publish_user_created_event,
            publish_user_deleted_event,
            publish_user_updated_event,
        )

        assert callable(publish_user_created_event)
        assert callable(publish_user_updated_event)
        assert callable(publish_user_deleted_event)

    def test_all_contains_expected_exports(self) -> None:
        """Test that __all__ contains all expected exports."""
        from user_auth_service.events import __all__

        expected = [
            "publish_user_created_event",
            "publish_user_updated_event",
            "publish_user_deleted_event",
        ]

        for export in expected:
            assert export in __all__, f"{export} missing from __all__"
