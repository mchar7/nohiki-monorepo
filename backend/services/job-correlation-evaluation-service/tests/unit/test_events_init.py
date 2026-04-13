"""Unit tests for the events package's import contract.

events/__init__.py intentionally re-exports nothing (see its module docstring):
submodules are imported directly by callers to keep package initialization
side-effect free and avoid import cycles between handlers and matching
services. These tests pin that contract and cover the one piece of setter
behavior not already exercised by tests/unit/events/*.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from job_correlation_evaluation_service import events


class TestPackageHasNoReExports:
    """The events package must stay a plain, side-effect-free namespace."""

    def test_no_dunder_all(self) -> None:
        """No __all__ means nothing is declared as re-exported from the package."""
        assert not hasattr(events, "__all__")

    def test_handler_and_publisher_symbols_are_not_reexported(self) -> None:
        """Concrete functions must live only on their owning submodules."""
        not_reexported = [
            "start_event_consumer",
            "set_ml_scoring_service",
            "set_backfill_ml_scoring_service",
            "publish_correlation_evaluated",
        ]
        for name in not_reexported:
            assert not hasattr(events, name), f"{name} should not be re-exported from events"


class TestOwningModuleImports:
    """Each symbol must remain importable from the module that actually defines it."""

    def test_start_event_consumer_owned_by_handlers(self) -> None:
        from job_correlation_evaluation_service.events.handlers import start_event_consumer

        assert callable(start_event_consumer)

    def test_set_backfill_ml_scoring_service_owned_by_backfill_handler(self) -> None:
        from job_correlation_evaluation_service.events.backfill_handler import (
            set_backfill_ml_scoring_service,
        )

        assert callable(set_backfill_ml_scoring_service)

    def test_publish_correlation_evaluated_owned_by_publishers(self) -> None:
        from job_correlation_evaluation_service.events.publishers import (
            publish_correlation_evaluated,
        )

        assert callable(publish_correlation_evaluated)


class TestSetMlScoringService:
    """Behavior for handlers.set_ml_scoring_service, not covered elsewhere."""

    def test_sets_the_module_level_scoring_service(self) -> None:
        from job_correlation_evaluation_service.events import handlers

        mock_service = MagicMock()
        try:
            handlers.set_ml_scoring_service(mock_service)

            assert handlers._services.ml_scoring_service is mock_service
        finally:
            handlers.set_ml_scoring_service(None)

    def test_clearing_the_service_resets_to_none(self) -> None:
        from job_correlation_evaluation_service.events import handlers

        handlers.set_ml_scoring_service(MagicMock())

        handlers.set_ml_scoring_service(None)

        assert handlers._services.ml_scoring_service is None
