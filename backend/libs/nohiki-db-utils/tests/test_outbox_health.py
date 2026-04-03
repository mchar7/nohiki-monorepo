"""Tests for OutboxHealthProbe."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from nohiki_common_exceptions import HealthStatus
from nohiki_db_utils.outbox_health import OutboxHealthProbe
from nohiki_db_utils.testing import create_mock_session


def _make_session_factory(
    scalar_result: int | None = 0,
    *,
    raises: Exception | None = None,
) -> tuple[Any, AsyncMock]:
    """Create a mock session factory returning an async context manager."""
    mock_session = create_mock_session()

    if raises:
        mock_session.execute.side_effect = raises
    else:
        mock_result = MagicMock()
        mock_result.scalar.return_value = scalar_result
        mock_session.execute.return_value = mock_result

    @asynccontextmanager
    async def factory() -> AsyncGenerator[Any]:
        yield mock_session

    return factory, mock_session


class TestOutboxHealthProbe:
    """Tests for OutboxHealthProbe health check."""

    @pytest.mark.asyncio
    async def test_healthy_when_backlog_empty(self) -> None:
        """Probe reports healthy when outbox has 0 rows."""
        factory, _ = _make_session_factory(scalar_result=0)
        probe = OutboxHealthProbe(factory, "test_schema")

        result = await probe.check()

        assert result.status == HealthStatus.HEALTHY
        assert result.name == "outbox_backlog"
        assert "0 rows" in result.message

    @pytest.mark.asyncio
    async def test_healthy_when_below_threshold(self) -> None:
        """Probe reports healthy when backlog is below threshold."""
        factory, _ = _make_session_factory(scalar_result=50)
        probe = OutboxHealthProbe(factory, "test_schema", max_backlog=100)

        result = await probe.check()

        assert result.status == HealthStatus.HEALTHY
        assert result.details["count"] == 50

    @pytest.mark.asyncio
    async def test_degraded_when_above_threshold(self) -> None:
        """Probe reports degraded when backlog exceeds threshold."""
        factory, _ = _make_session_factory(scalar_result=150)
        probe = OutboxHealthProbe(factory, "test_schema", max_backlog=100)

        result = await probe.check()

        assert result.status == HealthStatus.DEGRADED
        assert "150 rows" in result.message
        assert result.details["count"] == 150
        assert result.details["threshold"] == 100

    @pytest.mark.asyncio
    async def test_degraded_at_exact_threshold_plus_one(self) -> None:
        """Probe reports degraded when count is exactly threshold + 1."""
        factory, _ = _make_session_factory(scalar_result=101)
        probe = OutboxHealthProbe(factory, "test_schema", max_backlog=100)

        result = await probe.check()

        assert result.status == HealthStatus.DEGRADED

    @pytest.mark.asyncio
    async def test_healthy_at_exact_threshold(self) -> None:
        """Probe reports healthy when count equals threshold."""
        factory, _ = _make_session_factory(scalar_result=100)
        probe = OutboxHealthProbe(factory, "test_schema", max_backlog=100)

        result = await probe.check()

        assert result.status == HealthStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_unhealthy_on_database_error(self) -> None:
        """Probe reports unhealthy when database query fails."""
        factory, _ = _make_session_factory(raises=ConnectionError("connection refused"))
        probe = OutboxHealthProbe(factory, "test_schema")

        result = await probe.check()

        assert result.status == HealthStatus.UNHEALTHY
        assert "connection refused" in result.message

    @pytest.mark.asyncio
    async def test_probe_name(self) -> None:
        """Probe has correct name."""
        factory, _ = _make_session_factory()
        probe = OutboxHealthProbe(factory, "test_schema")

        assert probe.name == "outbox_backlog"

    @pytest.mark.asyncio
    async def test_custom_max_backlog(self) -> None:
        """Probe respects custom max_backlog setting."""
        factory, _ = _make_session_factory(scalar_result=20)
        probe = OutboxHealthProbe(factory, "test_schema", max_backlog=10)

        result = await probe.check()

        assert result.status == HealthStatus.DEGRADED

    @pytest.mark.asyncio
    async def test_null_scalar_treated_as_zero(self) -> None:
        """Probe treats NULL scalar result as 0 rows."""
        factory, _ = _make_session_factory(scalar_result=None)
        probe = OutboxHealthProbe(factory, "test_schema")

        result = await probe.check()

        assert result.status == HealthStatus.HEALTHY
        assert result.details["count"] == 0
