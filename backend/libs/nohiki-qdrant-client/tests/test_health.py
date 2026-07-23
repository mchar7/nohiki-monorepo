"""Tests for Qdrant health probe module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from nohiki_common_exceptions import HealthProbeResult
from nohiki_qdrant_client.health import ProbeTiming, QdrantHealthProbe, ensure_qdrant_ready


class _FakeTime:
    def __init__(self) -> None:
        self.elapsed = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.elapsed

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.elapsed += seconds


class TestQdrantHealthProbe:
    """Tests for QdrantHealthProbe class."""

    @pytest.fixture
    def mock_client(self) -> AsyncMock:
        """Create a mock AsyncQdrantClient."""
        return AsyncMock()

    def test_name_property(self, mock_client: AsyncMock) -> None:
        """Test the name property returns correct value."""
        probe = QdrantHealthProbe(mock_client)
        assert probe.name == "qdrant"

    @pytest.mark.asyncio
    async def test_check_returns_healthy_when_qdrant_accessible(self, mock_client: AsyncMock) -> None:
        """Test check returns healthy result when Qdrant is accessible."""
        mock_collections = MagicMock()
        mock_collections.collections = [MagicMock(name="test_collection")]
        mock_client.get_collections = AsyncMock(return_value=mock_collections)

        probe = QdrantHealthProbe(mock_client)
        result = await probe.check()

        assert isinstance(result, HealthProbeResult)
        assert result.is_healthy() is True
        assert result.name == "qdrant"
        assert "Qdrant is healthy" in result.message
        assert result.details["collection_count"] == 1

    @pytest.mark.asyncio
    async def test_check_returns_unhealthy_on_timeout(self, mock_client: AsyncMock) -> None:
        """Test check returns unhealthy result on timeout."""
        mock_client.get_collections = AsyncMock(side_effect=TimeoutError)

        probe = QdrantHealthProbe(mock_client, timeout_seconds=5.0)
        result = await probe.check()

        assert isinstance(result, HealthProbeResult)
        assert result.is_healthy() is False
        assert result.name == "qdrant"
        assert "timeout" in result.message.lower()

    @pytest.mark.asyncio
    async def test_check_returns_unhealthy_on_connection_error(self, mock_client: AsyncMock) -> None:
        """Test check returns unhealthy result on connection error."""
        mock_client.get_collections = AsyncMock(side_effect=OSError("Connection refused"))

        probe = QdrantHealthProbe(mock_client)
        result = await probe.check()

        assert isinstance(result, HealthProbeResult)
        assert result.is_healthy() is False
        assert result.name == "qdrant"
        assert "connection failed" in result.message.lower()

    @pytest.mark.asyncio
    async def test_check_returns_unhealthy_on_runtime_error(self, mock_client: AsyncMock) -> None:
        """Test check returns unhealthy result on runtime error."""
        mock_client.get_collections = AsyncMock(side_effect=RuntimeError("Some error"))

        probe = QdrantHealthProbe(mock_client)
        result = await probe.check()

        assert isinstance(result, HealthProbeResult)
        assert result.is_healthy() is False
        assert "connection failed" in result.message.lower()

    @pytest.mark.asyncio
    async def test_check_returns_unhealthy_on_unexpected_error(self, mock_client: AsyncMock) -> None:
        """Test check returns unhealthy result on unexpected error."""
        mock_client.get_collections = AsyncMock(side_effect=Exception("Unexpected"))

        probe = QdrantHealthProbe(mock_client)
        result = await probe.check()

        assert isinstance(result, HealthProbeResult)
        assert result.is_healthy() is False
        assert result.name == "qdrant"
        assert "unexpected" in result.message.lower()

    @pytest.mark.asyncio
    async def test_check_with_required_collections_all_present(self, mock_client: AsyncMock) -> None:
        """Test check passes when all required collections exist."""
        mock_collections = MagicMock()
        coll1 = MagicMock()
        coll1.name = "collection1"
        coll2 = MagicMock()
        coll2.name = "collection2"
        mock_collections.collections = [coll1, coll2]
        mock_client.get_collections = AsyncMock(return_value=mock_collections)

        probe = QdrantHealthProbe(
            mock_client,
            collection_names=["collection1", "collection2"],
        )
        result = await probe.check()

        assert result.is_healthy() is True

    @pytest.mark.asyncio
    async def test_check_with_required_collections_missing(self, mock_client: AsyncMock) -> None:
        """Test check fails when required collections are missing."""
        mock_collections = MagicMock()
        coll1 = MagicMock()
        coll1.name = "collection1"
        mock_collections.collections = [coll1]
        mock_client.get_collections = AsyncMock(return_value=mock_collections)

        probe = QdrantHealthProbe(
            mock_client,
            collection_names=["collection1", "missing_collection"],
        )
        result = await probe.check()

        assert result.is_healthy() is False
        assert "missing collections" in result.message.lower()


class TestEnsureQdrantReady:
    """Tests for ensure_qdrant_ready function."""

    @pytest.fixture
    def mock_client(self) -> AsyncMock:
        """Create a mock AsyncQdrantClient."""
        return AsyncMock()

    @pytest.mark.asyncio
    async def test_returns_when_qdrant_healthy(self, mock_client: AsyncMock) -> None:
        """Test function returns immediately when Qdrant is healthy."""
        mock_collections = MagicMock()
        mock_collections.collections = []
        mock_client.get_collections = AsyncMock(return_value=mock_collections)

        await ensure_qdrant_ready(mock_client, timeout_seconds=1.0, retry_interval_seconds=0.1)

    @pytest.mark.asyncio
    async def test_retries_until_qdrant_ready(self, mock_client: AsyncMock) -> None:
        """Test function retries until Qdrant becomes ready."""
        mock_collections = MagicMock()
        mock_collections.collections = []
        mock_client.get_collections = AsyncMock(
            side_effect=[
                TimeoutError(),
                TimeoutError(),
                mock_collections,
            ]
        )
        fake_time = _FakeTime()

        await ensure_qdrant_ready(
            mock_client,
            timeout_seconds=5.0,
            retry_interval_seconds=0.1,
            timing=ProbeTiming(clock=fake_time, sleep=fake_time.sleep),
        )

        assert mock_client.get_collections.call_count == 3
        assert fake_time.sleeps == pytest.approx([0.1, 0.1])

    @pytest.mark.asyncio
    async def test_raises_after_timeout(self, mock_client: AsyncMock) -> None:
        """Test function raises RuntimeError after timeout."""
        mock_client.get_collections = AsyncMock(side_effect=TimeoutError())
        fake_time = _FakeTime()

        with pytest.raises(RuntimeError) as exc_info:
            await ensure_qdrant_ready(
                mock_client,
                timeout_seconds=0.2,
                retry_interval_seconds=0.1,
                timing=ProbeTiming(clock=fake_time, sleep=fake_time.sleep),
            )

        assert "unavailable" in str(exc_info.value).lower()
        assert fake_time.elapsed == pytest.approx(0.2)
        assert fake_time.sleeps == pytest.approx([0.1, 0.1])

    @pytest.mark.asyncio
    async def test_with_required_collections(self, mock_client: AsyncMock) -> None:
        """Test function waits for required collections."""
        mock_collections = MagicMock()
        coll = MagicMock()
        coll.name = "required_collection"
        mock_collections.collections = [coll]
        mock_client.get_collections = AsyncMock(return_value=mock_collections)

        await ensure_qdrant_ready(
            mock_client,
            timeout_seconds=1.0,
            retry_interval_seconds=0.1,
            required_collections=["required_collection"],
        )
