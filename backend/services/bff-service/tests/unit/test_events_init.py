"""Unit tests for events/__init__.py module."""

from __future__ import annotations

import importlib
import sys
from collections.abc import Callable
from unittest.mock import MagicMock, patch

from nohiki_kafka_client import Topics


class TestStartEventConsumer:
    """Tests for start_event_consumer function."""

    def test_starts_kafka_consumers(self) -> None:
        """Test that start_event_consumer starts Kafka consumers."""
        with (
            patch("bff_service.events.kafka_client") as mock_kafka,
            patch("bff_service.events.logger") as mock_logger,
        ):
            mock_kafka.start_consumers = MagicMock()

            from bff_service.events import start_event_consumer

            start_event_consumer()

            mock_kafka.start_consumers.assert_called_once()
            mock_logger.info.assert_called()

    def test_logs_service_name_on_start(self) -> None:
        """Test that start_event_consumer logs the service name."""
        with (
            patch("bff_service.events.kafka_client") as mock_kafka,
            patch("bff_service.events.logger") as mock_logger,
            patch("bff_service.events.settings") as mock_settings,
        ):
            mock_kafka.start_consumers = MagicMock()
            mock_settings.service_name = "bff-service"

            from bff_service.events import start_event_consumer

            start_event_consumer()

            mock_logger.info.assert_called_with(
                "Starting event consumer",
                service="bff-service",
            )


class TestModuleExports:
    """Tests for module exports."""

    def test_exports_projections_module(self) -> None:
        """Test that projections module is exported."""
        from bff_service.events import projections

        assert projections is not None

    def test_exports_start_event_consumer(self) -> None:
        """Test that start_event_consumer is exported."""
        from bff_service.events import start_event_consumer

        assert callable(start_event_consumer)

    def test_all_contains_expected_exports(self) -> None:
        """Test that __all__ contains all expected exports."""
        from bff_service.events import __all__

        expected = [
            "doc_template",
            "job_correlation",
            "job_listing",
            "skill",
            "start_event_consumer",
            "user_auth",
            "user_pref",
            "user_upload",
        ]

        for export in expected:
            assert export in __all__, f"{export} missing from __all__"


def test_registers_revocation_handlers_on_dedicated_group() -> None:
    """Both auth revocation events register on the independent replay group."""
    from bff_service.events import projections
    from bff_service.events.projections import user_auth

    registrations: list[tuple[object, object, dict[str, object]]] = []

    def message_handler(topic: object, message_type: object, **kwargs: object) -> Callable[[object], object]:
        registrations.append((topic, message_type, kwargs))
        return lambda function: function

    with (
        patch.dict(sys.modules),
        patch.object(projections, "user_auth", user_auth),
        patch.object(user_auth.kafka_client, "message_handler", side_effect=message_handler),
        patch.object(
            user_auth.kafka_client,
            "with_db_session",
            side_effect=lambda: lambda function: function,
        ),
    ):
        del sys.modules[user_auth.__name__]
        isolated_user_auth = importlib.import_module(user_auth.__name__)

    revocation_registrations = {
        topic: kwargs
        for topic, _message_type, kwargs in registrations
        if topic in {Topics.USER_AUTH_ACCESS_TOKEN_REVOKED, Topics.USER_AUTH_ACCOUNT_DELETED}
    }
    assert set(revocation_registrations) == {
        Topics.USER_AUTH_ACCESS_TOKEN_REVOKED,
        Topics.USER_AUTH_ACCOUNT_DELETED,
    }
    assert {kwargs["group_id"] for kwargs in revocation_registrations.values()} == {
        isolated_user_auth.projection_auth_revocation_group_id
    }
    assert all(kwargs["preserve_partition_order"] is False for kwargs in revocation_registrations.values())
