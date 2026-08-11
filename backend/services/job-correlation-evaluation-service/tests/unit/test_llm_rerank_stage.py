"""Tests for LLM reranking stage."""

from __future__ import annotations

import asyncio
import time
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from job_correlation_evaluation_service.services.scoring.stages.llm_rerank import (
    CircuitBreaker,
    LLMRerankConfig,
    LLMRerankStage,
    RerankCandidate,
)
from job_correlation_evaluation_service.services.scoring.stages.native_maxsim import (
    NativeMaxSimCandidate,
)


class TestRerankCandidate:
    """Tests for RerankCandidate dataclass."""

    def test_rerank_candidate_creation(self) -> None:
        """Test RerankCandidate can be created."""
        candidate = RerankCandidate(
            entity_id="job-123",
            maxsim_score=12.5,
            rerank_score=0.92,
            payload={"title": "Software Engineer"},
        )

        assert candidate.entity_id == "job-123"
        assert candidate.rerank_score == pytest.approx(0.92)

    def test_from_maxsim_candidate(self) -> None:
        """Test creating RerankCandidate from NativeMaxSimCandidate."""
        maxsim = NativeMaxSimCandidate(
            entity_id="job-123",
            maxsim_score=12.5,
            payload={"title": "Engineer"},
        )

        rerank = RerankCandidate.from_maxsim_candidate(maxsim, rerank_score=0.95)

        assert rerank.entity_id == "job-123"

        assert rerank.maxsim_score == pytest.approx(12.5)
        assert rerank.rerank_score == pytest.approx(0.95)
        assert rerank.payload == {"title": "Engineer"}


class TestCircuitBreaker:
    """Tests for CircuitBreaker."""

    def test_initial_state_closed(self) -> None:
        """Test circuit breaker starts closed."""
        cb = CircuitBreaker()
        assert not cb.is_open

    def test_opens_after_threshold(self) -> None:
        """Test circuit opens after reaching failure threshold."""
        cb = CircuitBreaker(failure_threshold=3)

        cb.record_failure()
        assert not cb.is_open

        cb.record_failure()
        assert not cb.is_open

        cb.record_failure()
        assert cb.is_open

    def test_success_resets_failure_count(self) -> None:
        """Test success resets failure count."""
        cb = CircuitBreaker(failure_threshold=3)

        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        cb.record_failure()

        assert not cb.is_open

    def test_success_closes_circuit(self) -> None:
        """Test success closes an open circuit."""
        cb = CircuitBreaker(failure_threshold=2)

        cb.record_failure()
        cb.record_failure()
        assert cb.is_open

        cb.record_success()
        assert not cb.is_open

    def test_recovery_after_timeout(self) -> None:
        """Test circuit closes after recovery timeout."""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=1)

        cb.record_failure()
        # Circuit should be open immediately after failure
        # But we need to check before recovery timeout kicks in
        # Manually check internal state
        assert cb._is_open
        assert cb._failure_count >= 1

        # Simulate time passing by manipulating last_failure_time
        cb._last_failure_time = time.monotonic() - 2  # 2 seconds ago
        # Now is_open should return False due to recovery
        assert not cb.is_open


class TestLLMRerankStage:
    """Tests for LLMRerankStage."""

    @pytest.fixture
    def stage(self) -> LLMRerankStage:
        """Create LLMRerankStage."""
        return LLMRerankStage(
            LLMRerankConfig(
                endpoint_url="http://localhost:8080/rerank",
                timeout_seconds=10.0,
                batch_size=10,
                default_limit=50,
            )
        )

    @pytest.fixture
    def sample_candidates(self) -> list[NativeMaxSimCandidate]:
        """Create sample MaxSim candidates."""
        return [
            NativeMaxSimCandidate(
                entity_id="job-001",
                maxsim_score=12.5,
                payload={
                    "title": "Software Engineer",
                    "description": "Build great software",
                    "company_name": "Tech Corp",
                },
            ),
            NativeMaxSimCandidate(
                entity_id="job-002",
                maxsim_score=10.5,
                payload={
                    "title": "Data Scientist",
                    "description": "Analyze data",
                    "company_name": "Data Inc",
                },
            ),
        ]

    def test_init(self, stage: LLMRerankStage) -> None:
        """Test stage initialization."""
        assert stage._endpoint_url == "http://localhost:8080/rerank"
        assert stage._timeout == pytest.approx(10.0)
        assert stage._batch_size == 10
        assert stage._default_limit == 50
        assert stage._max_concurrent_batches == 4

    @pytest.mark.asyncio
    async def test_rerank_empty_candidates(self, stage: LLMRerankStage) -> None:
        """Test rerank returns empty for empty input."""
        result = await stage.rerank("python developer", [])
        assert result == []

    @pytest.mark.asyncio
    async def test_rerank_circuit_open_passthrough(
        self,
        stage: LLMRerankStage,
        sample_candidates: list[NativeMaxSimCandidate],
    ) -> None:
        """Test rerank passes through when circuit is open."""
        stage._circuit_breaker._is_open = True
        stage._circuit_breaker._last_failure_time = time.monotonic()

        result = await stage.rerank("python developer", sample_candidates)

        assert len(result) == 2
        assert all(c.rerank_score == pytest.approx(0.0) for c in result)

    @pytest.mark.asyncio
    async def test_rerank_no_endpoint_passthrough(
        self,
        sample_candidates: list[NativeMaxSimCandidate],
    ) -> None:
        """Test rerank passes through when no endpoint configured."""
        stage = LLMRerankStage(LLMRerankConfig(endpoint_url=""))

        result = await stage.rerank("python developer", sample_candidates)

        assert len(result) == 2
        assert all(c.rerank_score == pytest.approx(0.0) for c in result)

    @pytest.mark.asyncio
    async def test_rerank_success(
        self,
        stage: LLMRerankStage,
        sample_candidates: list[NativeMaxSimCandidate],
    ) -> None:
        """Test successful reranking."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [
                {"id": "job-001", "score": 0.95},
                {"id": "job-002", "score": 0.85},
            ]
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(stage, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_get_client.return_value = mock_client

            result = await stage.rerank("python developer", sample_candidates)

        assert len(result) == 2
        assert result[0].rerank_score == pytest.approx(0.95)
        assert result[1].rerank_score == pytest.approx(0.85)

    @pytest.mark.asyncio
    async def test_rerank_batches_are_parallel_but_bounded(self) -> None:
        """Test batched requests run concurrently but respect the limit."""
        stage = LLMRerankStage(
            LLMRerankConfig(
                endpoint_url="http://localhost:8080/rerank",
                timeout_seconds=10.0,
                batch_size=2,
                default_limit=10,
                max_concurrent_batches=2,
            )
        )
        candidates = [
            NativeMaxSimCandidate(
                entity_id=f"job-{i:03d}",
                maxsim_score=10.0 - i,
                payload={"title": f"Job {i}"},
            )
            for i in range(5)
        ]

        active_requests = 0
        max_active_requests = 0

        async def post(*_args: object, **kwargs: object) -> MagicMock:
            nonlocal active_requests, max_active_requests

            payload = cast("dict[str, Any]", kwargs["json"])
            documents = cast("list[dict[str, str]]", payload["documents"])

            active_requests += 1
            max_active_requests = max(max_active_requests, active_requests)
            try:
                await asyncio.sleep(0.05)
                response = MagicMock()
                response.json.return_value = {
                    "results": [{"id": doc["id"], "score": float(doc["id"].split("-")[1])} for doc in documents]
                }
                response.raise_for_status = MagicMock()
                return response
            finally:
                active_requests -= 1

        with patch.object(stage, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.post.side_effect = post
            mock_get_client.return_value = mock_client

            result = await stage.rerank("python developer", candidates)

        assert mock_client.post.call_count == 3
        assert max_active_requests == 2
        assert [candidate.entity_id for candidate in result] == ["job-004", "job-003", "job-002", "job-001", "job-000"]

    @pytest.mark.asyncio
    async def test_rerank_http_error_passthrough(
        self,
        stage: LLMRerankStage,
        sample_candidates: list[NativeMaxSimCandidate],
    ) -> None:
        """Test rerank falls back on HTTP error."""
        with patch.object(stage, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.post.side_effect = httpx.HTTPError("Connection refused")
            mock_get_client.return_value = mock_client

            result = await stage.rerank("python developer", sample_candidates)

        assert len(result) == 2
        assert all(c.rerank_score == pytest.approx(0.0) for c in result)
        assert stage._circuit_breaker._failure_count == 1

    @pytest.mark.parametrize(
        "invalid_results",
        [
            [{"id": "attacker-controlled-id", "score": 1.0}],
            [{"id": "job-001", "score": 0.2}, {"id": "job-001", "score": 0.9}],
        ],
        ids=["unexpected-id", "duplicate-id"],
    )
    @pytest.mark.asyncio
    async def test_invalid_response_ids_fail_closed_and_open_circuit(
        self,
        sample_candidates: list[NativeMaxSimCandidate],
        invalid_results: list[dict[str, object]],
    ) -> None:
        """Untrusted response IDs cannot affect ranking and count as an endpoint failure."""
        stage = LLMRerankStage(
            LLMRerankConfig(
                endpoint_url="http://localhost:8080/rerank",
                circuit_breaker_failure_threshold=1,
                circuit_breaker_recovery_seconds=3600,
            )
        )
        response = MagicMock()
        response.json.return_value = {"results": invalid_results}
        response.raise_for_status = MagicMock()
        client = AsyncMock()
        client.post.return_value = response

        with patch.object(stage, "_get_client", return_value=client):
            first = await stage.rerank("python developer", sample_candidates)
            second = await stage.rerank("python developer", sample_candidates)

        assert [candidate.rerank_score for candidate in first] == [0.0, 0.0]
        assert [candidate.rerank_score for candidate in second] == [0.0, 0.0]
        client.post.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_rerank_multi_batch_error_passthrough(
        self,
    ) -> None:
        """Test multi-batch failures still fall back to passthrough."""
        stage = LLMRerankStage(
            LLMRerankConfig(
                endpoint_url="http://localhost:8080/rerank",
                timeout_seconds=10.0,
                batch_size=2,
                default_limit=10,
                max_concurrent_batches=2,
            )
        )
        candidates = [
            NativeMaxSimCandidate(
                entity_id=f"job-{i:03d}",
                maxsim_score=10.0,
                payload={"title": f"Job {i}"},
            )
            for i in range(5)
        ]

        async def post(*_args: object, **kwargs: object) -> MagicMock:
            payload = cast("dict[str, Any]", kwargs["json"])
            documents = cast("list[dict[str, str]]", payload["documents"])
            if any(doc["id"] == "job-002" for doc in documents):
                error_message = "Connection refused"
                raise httpx.HTTPError(error_message)

            response = MagicMock()
            response.json.return_value = {"results": [{"id": doc["id"], "score": 0.9} for doc in documents]}
            response.raise_for_status = MagicMock()
            return response

        with patch.object(stage, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.post.side_effect = post
            mock_get_client.return_value = mock_client

            result = await stage.rerank("python developer", candidates)

        assert len(result) == 5
        assert all(candidate.rerank_score == pytest.approx(0.0) for candidate in result)
        assert stage._circuit_breaker._failure_count == 1

    @pytest.mark.asyncio
    async def test_rerank_timeout_passthrough(
        self,
        stage: LLMRerankStage,
        sample_candidates: list[NativeMaxSimCandidate],
    ) -> None:
        """Test rerank falls back on timeout."""
        with patch.object(stage, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.post.side_effect = httpx.TimeoutException("Timeout")
            mock_get_client.return_value = mock_client

            result = await stage.rerank("python developer", sample_candidates)

        assert len(result) == 2
        assert all(c.rerank_score == pytest.approx(0.0) for c in result)

    @pytest.mark.asyncio
    async def test_rerank_respects_limit(
        self,
        stage: LLMRerankStage,
    ) -> None:
        """Test rerank respects limit parameter."""
        candidates = [
            NativeMaxSimCandidate(
                entity_id=f"job-{i:03d}",
                maxsim_score=10.0,
                payload={"title": f"Job {i}"},
            )
            for i in range(100)
        ]

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [{"id": f"job-{i:03d}", "score": 0.9 - i * 0.01} for i in range(10)]
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(stage, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_get_client.return_value = mock_client

            result = await stage.rerank("query", candidates, limit=10)

        assert len(result) == 10

    def test_prepare_documents(
        self,
        stage: LLMRerankStage,
        sample_candidates: list[NativeMaxSimCandidate],
    ) -> None:
        """Test document preparation for reranking."""
        docs = stage._prepare_documents(sample_candidates)

        assert len(docs) == 2
        assert docs[0]["id"] == "job-001"
        assert "Software Engineer" in docs[0]["text"]
        assert "Tech Corp" in docs[0]["text"]

    def test_apply_scores(
        self,
        stage: LLMRerankStage,
        sample_candidates: list[NativeMaxSimCandidate],
    ) -> None:
        """Test applying scores to candidates."""
        scores = {"job-001": 0.95, "job-002": 0.85}

        result = stage._apply_scores(sample_candidates, scores)

        assert len(result) == 2
        # Sorted by rerank_score descending
        assert result[0].rerank_score == pytest.approx(0.95)
        assert result[1].rerank_score == pytest.approx(0.85)

    def test_passthrough_candidates(
        self,
        stage: LLMRerankStage,
        sample_candidates: list[NativeMaxSimCandidate],
    ) -> None:
        """Test passthrough creates candidates with zero rerank score."""
        result = stage._passthrough_candidates(sample_candidates)

        assert len(result) == 2
        assert all(c.rerank_score == pytest.approx(0.0) for c in result)
        assert all(isinstance(c, RerankCandidate) for c in result)

    @pytest.mark.asyncio
    async def test_close(self, stage: LLMRerankStage) -> None:
        """Test closing the HTTP client."""
        stage._client = AsyncMock()
        await stage.close()
        assert stage._client is None

    @pytest.mark.asyncio
    async def test_close_when_not_opened(self, stage: LLMRerankStage) -> None:
        """Test close is safe when client not created."""
        assert stage._client is None
        await stage.close()  # Should not raise
        assert stage._client is None

    @pytest.mark.asyncio
    async def test_rerank_with_texts_empty(self, stage: LLMRerankStage) -> None:
        """Test rerank_with_texts returns empty for empty input."""
        result = await stage.rerank_with_texts("query", [], {})
        assert result == []

    @pytest.mark.asyncio
    async def test_rerank_with_texts_circuit_open(
        self,
        stage: LLMRerankStage,
        sample_candidates: list[NativeMaxSimCandidate],
    ) -> None:
        """Test rerank_with_texts passes through when circuit is open."""
        stage._circuit_breaker._is_open = True
        stage._circuit_breaker._last_failure_time = time.monotonic()

        result = await stage.rerank_with_texts(
            "query",
            sample_candidates,
            {"job-001": "Full text 1", "job-002": "Full text 2"},
        )

        assert len(result) == 2
        assert all(c.rerank_score == pytest.approx(0.0) for c in result)

    @pytest.mark.asyncio
    async def test_rerank_with_texts_success(
        self,
        stage: LLMRerankStage,
        sample_candidates: list[NativeMaxSimCandidate],
    ) -> None:
        """Test rerank_with_texts with successful call."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [
                {"id": "job-001", "score": 0.95},
                {"id": "job-002", "score": 0.85},
            ]
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(stage, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_get_client.return_value = mock_client

            result = await stage.rerank_with_texts(
                "python developer",
                sample_candidates,
                {"job-001": "Full description 1", "job-002": "Full description 2"},
            )

        assert len(result) == 2
        assert result[0].rerank_score == pytest.approx(0.95)

    @pytest.mark.asyncio
    async def test_rerank_with_texts_error_passthrough(
        self,
        stage: LLMRerankStage,
        sample_candidates: list[NativeMaxSimCandidate],
    ) -> None:
        """Test rerank_with_texts falls back on error."""
        with patch.object(stage, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.post.side_effect = httpx.HTTPError("Error")
            mock_get_client.return_value = mock_client

            result = await stage.rerank_with_texts(
                "query",
                sample_candidates,
                {"job-001": "text", "job-002": "text"},
            )

        assert len(result) == 2
        assert all(c.rerank_score == pytest.approx(0.0) for c in result)


class TestLLMRerankStageFromSettings:
    """Tests for LLMRerankStage.from_settings factory."""

    def test_from_settings(self) -> None:
        """Test creating stage from settings."""
        settings = MagicMock()
        settings.reranker_endpoint_url = "http://test:8080/rerank"
        settings.rerank_timeout_seconds = 15.0
        settings.rerank_batch_size = 20
        settings.stage3_candidate_limit = 100

        stage = LLMRerankStage.from_settings(settings)

        assert stage._endpoint_url == "http://test:8080/rerank"
        assert stage._timeout == pytest.approx(15.0)
        assert stage._batch_size == 20
        assert stage._default_limit == 100
        assert stage._max_concurrent_batches == 4
