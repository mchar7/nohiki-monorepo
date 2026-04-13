"""Stage 3: LLM Reranking (model-agnostic)."""

from __future__ import annotations

import asyncio
import math
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx
from nohiki_observability import get_logger

from job_correlation_evaluation_service.services.scoring.stages.native_maxsim import (
    NativeMaxSimCandidate,
)

if TYPE_CHECKING:
    from job_correlation_evaluation_service.services.scoring.pipeline_config import (
        PipelineSettings,
    )

DEFAULT_RERANKER_BATCH_SIZE = 16
DEFAULT_STAGE3_LIMIT = 50
DEFAULT_MAX_CONCURRENT_BATCHES = 4
MAX_RERANK_QUERY_CHARS = 4096
MAX_RERANK_DOCUMENT_CHARS = 8192

FAILURE_THRESHOLD = 5
RECOVERY_TIMEOUT_SECONDS = 30

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class LLMRerankConfig:
    """Operational configuration for the external reranker."""

    endpoint_url: str
    timeout_seconds: float = 30.0
    batch_size: int = DEFAULT_RERANKER_BATCH_SIZE
    default_limit: int = DEFAULT_STAGE3_LIMIT
    max_concurrent_batches: int = DEFAULT_MAX_CONCURRENT_BATCHES
    circuit_breaker_failure_threshold: int = FAILURE_THRESHOLD
    circuit_breaker_recovery_seconds: int = RECOVERY_TIMEOUT_SECONDS


@dataclass(frozen=True, slots=True)
class RerankCandidate:
    """Candidate with all stage scores after LLM reranking."""

    entity_id: str
    maxsim_score: float
    rerank_score: float
    payload: dict[str, Any]

    @classmethod
    def from_maxsim_candidate(
        cls,
        candidate: NativeMaxSimCandidate,
        rerank_score: float,
    ) -> RerankCandidate:
        """Create from NativeMaxSimCandidate with rerank score."""
        return cls(
            entity_id=candidate.entity_id,
            maxsim_score=candidate.maxsim_score,
            rerank_score=rerank_score,
            payload=candidate.payload,
        )


class CircuitBreaker:
    """Simple circuit breaker for external service calls."""

    def __init__(
        self,
        failure_threshold: int = FAILURE_THRESHOLD,
        recovery_timeout: int = RECOVERY_TIMEOUT_SECONDS,
    ) -> None:
        """Initialize circuit breaker with thresholds."""
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._failure_count = 0
        self._last_failure_time: float | None = None
        self._is_open = False

    @property
    def is_open(self) -> bool:
        """Check if circuit is open (blocking requests)."""
        if not self._is_open:
            return False
        if self._last_failure_time is not None:
            elapsed = time.monotonic() - self._last_failure_time
            if elapsed >= self._recovery_timeout:
                self._is_open = False
                self._failure_count = 0
                return False
        return True

    def record_success(self) -> None:
        """Record a successful call."""
        self._failure_count = 0
        self._is_open = False

    def record_failure(self) -> None:
        """Record a failed call."""
        self._failure_count += 1
        self._last_failure_time = time.monotonic()
        if self._failure_count >= self._failure_threshold:
            self._is_open = True
            logger.warning(
                "Circuit breaker opened",
                failure_count=self._failure_count,
                threshold=self._failure_threshold,
            )


class LLMRerankStage:
    """Stage 3: LLM reranking via external inference endpoint.

    Model-agnostic: endpoint URL determines which model is used.
    This stage is OPTIONAL and can be skipped based on configuration.

    Pipeline Position:
        Stage 1: MUVERA ANN (Qdrant)     → ~1000 candidates (retrieval only)
        Stage 2: MaxSim Rerank           → ~150 candidates
        Stage 3: LLM Rerank (optional)   → ~50 candidates   ← THIS STAGE
        Stage 4: L2R Final Ranking       → Final ranked list

    Graceful Degradation:
        If reranking fails (timeout, circuit open, error), candidates
        pass through with rerank_score=0.0. This prevents LLM issues
        from breaking the entire pipeline.

    """

    def __init__(
        self,
        endpoint_url: str | LLMRerankConfig = "",
        **legacy_settings: float,
    ) -> None:
        """Initialize the reranker from typed or legacy settings.

        Args:
            endpoint_url: Typed configuration or external reranker URL.
            **legacy_settings: Backward-compatible numeric constructor settings.
        """
        config = (
            endpoint_url
            if isinstance(endpoint_url, LLMRerankConfig)
            else LLMRerankConfig(
                endpoint_url=endpoint_url,
                timeout_seconds=float(legacy_settings.get("timeout_seconds", 30.0)),
                batch_size=int(legacy_settings.get("batch_size", DEFAULT_RERANKER_BATCH_SIZE)),
                default_limit=int(legacy_settings.get("default_limit", DEFAULT_STAGE3_LIMIT)),
                max_concurrent_batches=int(
                    legacy_settings.get("max_concurrent_batches", DEFAULT_MAX_CONCURRENT_BATCHES)
                ),
                circuit_breaker_failure_threshold=int(
                    legacy_settings.get("circuit_breaker_failure_threshold", FAILURE_THRESHOLD)
                ),
                circuit_breaker_recovery_seconds=int(
                    legacy_settings.get("circuit_breaker_recovery_seconds", RECOVERY_TIMEOUT_SECONDS)
                ),
            )
        )
        self._endpoint_url = config.endpoint_url
        self._timeout = config.timeout_seconds
        self._batch_size = config.batch_size
        self._default_limit = config.default_limit
        self._max_concurrent_batches = config.max_concurrent_batches
        self._circuit_breaker = CircuitBreaker(
            failure_threshold=config.circuit_breaker_failure_threshold,
            recovery_timeout=config.circuit_breaker_recovery_seconds,
        )
        self._client: httpx.AsyncClient | None = None

        logger.info(
            "LLM rerank stage initialized",
            endpoint_url=config.endpoint_url,
            timeout_seconds=config.timeout_seconds,
            batch_size=config.batch_size,
            default_limit=config.default_limit,
            max_concurrent_batches=config.max_concurrent_batches,
        )

    @classmethod
    def from_settings(cls, settings: PipelineSettings) -> LLMRerankStage:
        """Create from PipelineSettings."""
        return cls(
            LLMRerankConfig(
                endpoint_url=settings.reranker_endpoint_url,
                timeout_seconds=settings.rerank_timeout_seconds,
                batch_size=settings.rerank_batch_size,
                default_limit=settings.stage3_candidate_limit,
                circuit_breaker_failure_threshold=settings.circuit_breaker_failure_threshold,
                circuit_breaker_recovery_seconds=settings.circuit_breaker_recovery_seconds,
            )
        )

    def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def close(self) -> None:
        """Close HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _unavailable_reason(self, query_text: str) -> str | None:
        """Return why reranking must be bypassed, if unavailable."""
        if self._circuit_breaker.is_open:
            return "Circuit breaker open"
        if not self._endpoint_url:
            return "No reranker endpoint configured"
        if not query_text.strip():
            return "Empty reranker query"
        return None

    async def rerank(
        self,
        query_text: str,
        candidates: list[NativeMaxSimCandidate],
        limit: int | None = None,
    ) -> list[RerankCandidate]:
        """Rerank candidates using external LLM endpoint.

        Args:
            query_text: Query text for reranking
            candidates: Stage 1+2 candidates (NativeMaxSimCandidate)
            limit: Max candidates to rerank (default: default_limit)

        Returns:
            Candidates with rerank_score added, sorted by rerank_score

        """
        if not candidates:
            return []

        effective_limit = limit or self._default_limit
        candidates_to_rerank = candidates[:effective_limit]

        if reason := self._unavailable_reason(query_text):
            logger.warning("Skipping LLM rerank", reason=reason)
            return self._passthrough_candidates(candidates_to_rerank)

        logger.debug(
            "Starting LLM reranking",
            input_candidates=len(candidates_to_rerank),
            query_length=len(query_text),
        )

        try:
            documents = self._prepare_documents(candidates_to_rerank)
            scores = await self._call_reranker(query_text, documents)
            if scores is None:
                self._circuit_breaker.record_failure()
                results = self._passthrough_candidates(candidates_to_rerank)
            else:
                results = self._apply_scores(candidates_to_rerank, scores)
                self._circuit_breaker.record_success()
                logger.info("LLM reranking completed", output_candidates=len(results))
        except (httpx.HTTPError, httpx.TimeoutException, TypeError, ValueError, KeyError) as e:
            logger.warning("LLM reranking failed, using passthrough", error=str(e))
            self._circuit_breaker.record_failure()
            results = self._passthrough_candidates(candidates_to_rerank)
        return results

    def _prepare_documents(
        self,
        candidates: list[NativeMaxSimCandidate],
    ) -> list[dict[str, str]]:
        """Prepare documents for reranking request."""
        documents = []
        for c in candidates:
            payload = c.payload
            title = payload.get("title", "")
            description = payload.get("description", "")
            company = payload.get("company_name", "")

            text_parts = [p for p in [title, company, description] if p]
            text = (" | ".join(text_parts) if text_parts else "")[:MAX_RERANK_DOCUMENT_CHARS]

            documents.append({"id": c.entity_id, "text": text})
        return documents

    async def _call_reranker(
        self,
        query: str,
        documents: list[dict[str, str]],
    ) -> dict[str, float] | None:
        """Call external reranker endpoint.

        Returns:
            Dict mapping document ID to rerank score

        """
        client = self._get_client()

        batches = [documents[i : i + self._batch_size] for i in range(0, len(documents), self._batch_size)]
        if len(batches) == 1:
            try:
                return await self._call_reranker_batch(client, query, batches[0])
            except (httpx.HTTPError, httpx.TimeoutException, TypeError, ValueError, KeyError) as exc:
                logger.warning("LLM reranking batch failed", error=str(exc))
                return None

        semaphore = asyncio.Semaphore(self._max_concurrent_batches)
        tasks: list[asyncio.Task[dict[str, float]]] = []
        had_error = False

        try:
            async with asyncio.TaskGroup() as task_group:
                tasks.extend(
                    task_group.create_task(self._call_reranker_batch(client, query, batch, semaphore))
                    for batch in batches
                )
        except* (httpx.HTTPError, httpx.TimeoutException, TypeError, ValueError, KeyError) as exc_group:
            logger.warning("LLM reranking batch failed", error=str(exc_group))
            had_error = True

        if had_error:
            return None

        all_scores: dict[str, float] = {}
        for task in tasks:
            all_scores |= task.result()

        return all_scores

    async def _call_reranker_batch(
        self,
        client: httpx.AsyncClient,
        query: str,
        batch: list[dict[str, str]],
        semaphore: asyncio.Semaphore | None = None,
    ) -> dict[str, float]:
        """Call the reranker for one batch and return its scores."""
        if semaphore is None:
            return await self._send_reranker_batch(client, query, batch)

        async with semaphore:
            return await self._send_reranker_batch(client, query, batch)

    async def _send_reranker_batch(
        self,
        client: httpx.AsyncClient,
        query: str,
        batch: list[dict[str, str]],
    ) -> dict[str, float]:
        """Send a single reranker batch request."""
        response = await client.post(
            self._endpoint_url,
            json={
                "query": query[:MAX_RERANK_QUERY_CHARS],
                "documents": batch,
            },
        )
        response.raise_for_status()

        result = response.json()
        if not isinstance(result, dict) or not isinstance(result.get("results"), list):
            msg = "Reranker response must contain a results list"
            raise TypeError(msg)

        allowed_ids = {document["id"] for document in batch}
        scores: dict[str, float] = {}
        for item in result["results"]:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                msg = "Reranker result must contain a string id"
                raise TypeError(msg)
            entity_id = item["id"]
            if entity_id not in allowed_ids or entity_id in scores:
                msg = f"Reranker returned unexpected or duplicate id: {entity_id}"
                raise ValueError(msg)
            score = float(item.get("score", 0.0))
            if not math.isfinite(score):
                msg = f"Reranker returned non-finite score for id: {entity_id}"
                raise ValueError(msg)
            scores[entity_id] = score
        return scores

    def _apply_scores(
        self,
        candidates: list[NativeMaxSimCandidate],
        scores: dict[str, float],
    ) -> list[RerankCandidate]:
        """Apply rerank scores and sort candidates."""
        results = [
            RerankCandidate.from_maxsim_candidate(
                c,
                rerank_score=scores.get(c.entity_id, 0.0),
            )
            for c in candidates
        ]

        results.sort(key=lambda x: x.rerank_score, reverse=True)
        return results

    def _passthrough_candidates(
        self,
        candidates: list[NativeMaxSimCandidate],
    ) -> list[RerankCandidate]:
        """Pass through candidates with rerank_score=0.0."""
        return [RerankCandidate.from_maxsim_candidate(c, rerank_score=0.0) for c in candidates]

    async def rerank_with_texts(
        self,
        query_text: str,
        candidates: list[NativeMaxSimCandidate],
        document_texts: dict[str, str],
        limit: int | None = None,
    ) -> list[RerankCandidate]:
        """Rerank with explicit document texts (for S3-fetched full text).

        Args:
            query_text: Query text for reranking
            candidates: Stage 2 candidates
            document_texts: Dict mapping entity_id to full document text
            limit: Max candidates to rerank

        Returns:
            Candidates with rerank_score added

        """
        if not candidates:
            return []

        effective_limit = limit or self._default_limit
        candidates_to_rerank = candidates[:effective_limit]

        if self._circuit_breaker.is_open or not self._endpoint_url:
            return self._passthrough_candidates(candidates_to_rerank)
        if not query_text.strip():
            return self._passthrough_candidates(candidates_to_rerank)

        try:
            documents = [
                {
                    "id": c.entity_id,
                    "text": document_texts.get(c.entity_id, "")[:MAX_RERANK_DOCUMENT_CHARS],
                }
                for c in candidates_to_rerank
            ]

            scores = await self._call_reranker(query_text, documents)
            if scores is None:
                self._circuit_breaker.record_failure()
                return self._passthrough_candidates(candidates_to_rerank)
            results = self._apply_scores(candidates_to_rerank, scores)
            self._circuit_breaker.record_success()

        except (httpx.HTTPError, httpx.TimeoutException, TypeError, ValueError, KeyError) as e:
            logger.warning("LLM reranking failed", error=str(e))
            self._circuit_breaker.record_failure()
            return self._passthrough_candidates(candidates_to_rerank)
        else:
            return results
