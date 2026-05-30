"""Tests for tailor.display.progress -- StatusSpinner and status_spinner context manager."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture
from tailor.display.progress import StatusSpinner, status_spinner


@pytest.fixture
def mock_live(mocker: MockerFixture) -> MagicMock:
    """Patch rich.Live to prevent actual terminal I/O during spinner tests."""
    mock = mocker.patch("tailor.display.progress.Live")
    mock.return_value.__enter__ = MagicMock(return_value=mock.return_value)
    mock.return_value.__exit__ = MagicMock(return_value=False)
    mock.return_value.refresh = MagicMock()
    return mock


class TestStatusSpinnerConstruction:
    """Tests for StatusSpinner initialisation."""

    def test_initial_status_stored(self) -> None:
        """Initial status string must be stored as the _status attribute."""
        spinner = StatusSpinner("Loading data...")
        assert spinner._status == "Loading data..."

    def test_default_initial_status(self) -> None:
        """StatusSpinner must default to 'Working...' when no status is given."""
        spinner = StatusSpinner()
        assert spinner._status == "Working..."

    def test_spinner_text_set_on_construction(self) -> None:
        """The internal Spinner's text must be set during __init__."""
        spinner = StatusSpinner("Initialising...")
        assert spinner._spinner.text is not None

    def test_live_is_none_before_entering_context(self) -> None:
        """_live must be None before entering the context manager."""
        spinner = StatusSpinner()
        assert spinner._live is None


class TestStatusSpinnerUpdate:
    """Tests for StatusSpinner.update()."""

    def test_update_changes_status_attribute(self) -> None:
        """update() must replace _status with the new value."""
        spinner = StatusSpinner("Old status")
        spinner.update("New status")
        assert spinner._status == "New status"

    def test_update_changes_spinner_text(self) -> None:
        """update() must rebuild and reassign _spinner.text."""
        spinner = StatusSpinner("Before")
        old_text = spinner._spinner.text
        spinner.update("After")
        assert spinner._spinner.text is not old_text

    def test_update_without_live_does_not_raise(self) -> None:
        """update() when _live is None must not raise any exception."""
        spinner = StatusSpinner()
        spinner.update("safe update")  # _live is None here


class TestStatusSpinnerContextManager:
    """Tests for StatusSpinner used as a context manager."""

    def test_enter_creates_live(self, mock_live: MagicMock) -> None:
        """__enter__ must create a Live instance and assign it to _live."""
        spinner = StatusSpinner("Working")
        spinner.__enter__()
        assert spinner._live is not None
        mock_live.return_value.__enter__.assert_called_once()

    def test_exit_clears_live(self, mock_live: MagicMock) -> None:
        """__exit__ must stop Live and set _live back to None."""
        spinner = StatusSpinner("Working")
        spinner.__enter__()
        spinner.__exit__(None, None, None)
        assert spinner._live is None
        mock_live.return_value.__exit__.assert_called_once()

    def test_context_manager_usage(self, mock_live: MagicMock) -> None:
        """StatusSpinner must work correctly as a 'with' context manager."""
        with StatusSpinner("In context") as sp:
            assert sp._live is not None
        assert sp._live is None

    def test_update_calls_live_refresh_inside_context(self, mock_live: MagicMock) -> None:
        """update() inside the context manager must call _live.refresh()."""
        with StatusSpinner("Working") as sp:
            sp.update("Updated inside context")
        mock_live.return_value.refresh.assert_called_once()


class TestStatusSpinnerContextManagerEdgeCases:
    """Edge cases for StatusSpinner context manager protocol."""

    def test_exit_when_live_is_none_does_not_raise(self) -> None:
        """__exit__ must be a no-op and not raise when _live is None."""
        spinner = StatusSpinner()
        spinner.__exit__(None, None, None)  # _live is None; must not raise

    def test_enter_returns_self(self, mock_live: MagicMock) -> None:
        """__enter__ must return the StatusSpinner instance itself."""
        spinner = StatusSpinner()
        result = spinner.__enter__()
        assert result is spinner


class TestStatusSpinnerContextManagerFunction:
    """Tests for the status_spinner() context manager function."""

    def test_yields_status_spinner_instance(self, mock_live: MagicMock) -> None:
        """status_spinner() must yield a StatusSpinner instance."""
        with status_spinner("Starting...") as sp:
            assert isinstance(sp, StatusSpinner)

    def test_spinner_is_entered_inside_context(self, mock_live: MagicMock) -> None:
        """The yielded spinner must have _live set while inside the context."""
        with status_spinner("Working") as sp:
            assert sp._live is not None

    def test_spinner_live_cleared_after_context(self, mock_live: MagicMock) -> None:
        """After the context exits, _live must be None."""
        with status_spinner("Working") as sp:
            pass
        assert sp._live is None

    def test_update_callable_on_yielded_spinner(self, mock_live: MagicMock) -> None:
        """update() must be callable on the yielded StatusSpinner without error."""
        with status_spinner("Initial") as sp:
            sp.update("Updated")
        assert sp._status == "Updated"
