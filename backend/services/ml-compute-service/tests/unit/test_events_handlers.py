"""Tests for ml_compute_service.events.handlers module."""

from __future__ import annotations

import asyncio
import gc
import threading
from collections.abc import Coroutine
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
from nohiki.ml.v1 import (
    EmbeddingType,
    EncodingMode,
    MlOperationType,
)


class TestToFloatList:
    """Tests for _to_float_list helper."""

    def test_converts_numpy_array(self) -> None:
        """Test converting numpy array to list of floats."""
        from ml_compute_service.events.handlers import _to_float_list

        arr = np.array([1.0, 2.0, 3.0])
        result = _to_float_list(arr)

        assert result == [1.0, 2.0, 3.0]

    def test_converts_sequence(self) -> None:
        """Test converting sequence to list of floats."""
        from ml_compute_service.events.handlers import _to_float_list

        seq = (1.0, 2.0, 3.0)
        result = _to_float_list(seq)

        assert result == [1.0, 2.0, 3.0]


class TestToIntList:
    """Tests for _to_int_list helper."""

    def test_converts_numpy_array(self) -> None:
        """Test converting numpy array to list of ints."""
        from ml_compute_service.events.handlers import _to_int_list

        arr = np.array([1, 2, 3])
        result = _to_int_list(arr)

        assert result == [1, 2, 3]

    def test_converts_sequence(self) -> None:
        """Test converting sequence to list of ints."""
        from ml_compute_service.events.handlers import _to_int_list

        seq = [1, 2, 3]
        result = _to_int_list(seq)

        assert result == [1, 2, 3]


class TestToNestedFloatList:
    """Tests for _to_nested_float_list helper."""

    def test_converts_2d_numpy_array(self) -> None:
        """Test converting 2D numpy array to nested list."""
        from ml_compute_service.events.handlers import _to_nested_float_list

        arr = np.array([[1.0, 2.0], [3.0, 4.0]])
        result = _to_nested_float_list(arr)

        assert result == [[1.0, 2.0], [3.0, 4.0]]

    def test_converts_nested_sequence(self) -> None:
        """Test converting nested sequence to nested list."""
        from ml_compute_service.events.handlers import _to_nested_float_list

        seq = ((1.0, 2.0), (3.0, 4.0))
        result = _to_nested_float_list(seq)

        assert result == [[1.0, 2.0], [3.0, 4.0]]

    def test_rejects_one_dimensional_input(self) -> None:
        """Nested vectors must retain a token-by-dimension matrix boundary."""
        from ml_compute_service.events.handlers import _to_nested_float_list

        with pytest.raises(ValueError, match="at least two dimensions"):
            _to_nested_float_list(np.array([1.0, 2.0]))


class TestInferenceTensorValidation:
    """Reject malformed model tensors before callback serialization."""

    @pytest.mark.parametrize(
        ("values", "dimensions", "error"),
        [
            (np.zeros((1, 2), dtype=np.float32), 1, "must be 1D"),
            (np.array([1, 2], dtype=np.int64), 1, "floating dtype"),
            (np.array([0.1, float("nan")], dtype=np.float32), 1, "non-finite"),
        ],
        ids=["rank", "dtype", "finite"],
    )
    def test_rejects_invalid_inference_arrays(
        self,
        values: np.ndarray,
        dimensions: int,
        error: str,
    ) -> None:
        from ml_compute_service.events.handlers import _as_float_array

        with pytest.raises(ValueError, match=error):
            _as_float_array(values, name="test embedding", dimensions=dimensions)

    def test_rejects_dense_batch_hash_cardinality_mismatch(self) -> None:
        """Every dense batch row must have exactly one corresponding content hash."""
        from ml_compute_service.events.handlers import _validate_dense_batch_result

        pipeline = MagicMock()
        pipeline.manifest.dense.embedding_dim = 2
        result = MagicMock()
        result.dense_embeddings = np.zeros((2, 2), dtype=np.float32)
        result.content_hashes = ["only-one-hash"]

        with pytest.raises(ValueError, match="cardinality mismatch"):
            _validate_dense_batch_result(
                pipeline,
                result,
                expected_count=2,
                entity_type="skill",
                collection_version="v1",
            )


class TestValidateRetrievalResult:
    """Reject malformed retrieval output before it crosses the collection boundary."""

    def _make_pipeline(self, *, muvera_dim: int = 2, colbert_dim: int = 2) -> MagicMock:
        pipeline = MagicMock()
        pipeline.manifest.muvera_output_dimension = muvera_dim
        pipeline.manifest.late_interaction.token_dim = colbert_dim
        pipeline.manifest.get_entity_version.return_value = "v1"
        return pipeline

    def test_accepts_well_formed_result(self) -> None:
        """A well-formed retrieval result validates version and dimensions without raising."""
        from ml_compute_service.events.handlers import _validate_retrieval_result

        pipeline = self._make_pipeline()
        result = MagicMock()
        result.muvera_fde = np.array([0.1, 0.2], dtype=np.float32)
        result.colbert_tokens = np.zeros((3, 2), dtype=np.float32)
        result.sparse_vector.values = np.array([0.5, 0.6], dtype=np.float32)
        result.sparse_vector.indices = np.array([1, 4], dtype=np.int64)

        _validate_retrieval_result(pipeline, result, entity_type="skill", collection_version="v1")

    def test_rejects_non_integer_sparse_indices(self) -> None:
        """Sparse indices must be an integer array, not floating point."""
        from ml_compute_service.events.handlers import _validate_retrieval_result

        pipeline = self._make_pipeline()
        result = MagicMock()
        result.muvera_fde = np.array([0.1, 0.2], dtype=np.float32)
        result.colbert_tokens = np.zeros((3, 2), dtype=np.float32)
        result.sparse_vector.values = np.array([0.5, 0.6], dtype=np.float32)
        result.sparse_vector.indices = np.array([1.0, 4.0], dtype=np.float64)

        with pytest.raises(ValueError, match="1D integer array"):
            _validate_retrieval_result(pipeline, result, entity_type="skill", collection_version="v1")

    def test_rejects_sparse_cardinality_mismatch(self) -> None:
        """Sparse indices and values must have the same length."""
        from ml_compute_service.events.handlers import _validate_retrieval_result

        pipeline = self._make_pipeline()
        result = MagicMock()
        result.muvera_fde = np.array([0.1, 0.2], dtype=np.float32)
        result.colbert_tokens = np.zeros((3, 2), dtype=np.float32)
        result.sparse_vector.values = np.array([0.5, 0.6, 0.7], dtype=np.float32)
        result.sparse_vector.indices = np.array([1, 4], dtype=np.int64)

        with pytest.raises(ValueError, match="same length"):
            _validate_retrieval_result(pipeline, result, entity_type="skill", collection_version="v1")

    def test_rejects_negative_sparse_indices(self) -> None:
        """Sparse indices must be non-negative."""
        from ml_compute_service.events.handlers import _validate_retrieval_result

        pipeline = self._make_pipeline()
        result = MagicMock()
        result.muvera_fde = np.array([0.1, 0.2], dtype=np.float32)
        result.colbert_tokens = np.zeros((3, 2), dtype=np.float32)
        result.sparse_vector.values = np.array([0.5, 0.6], dtype=np.float32)
        result.sparse_vector.indices = np.array([-1, 4], dtype=np.int64)

        with pytest.raises(ValueError, match="non-negative"):
            _validate_retrieval_result(pipeline, result, entity_type="skill", collection_version="v1")


class TestValidateDenseResult:
    """Reject malformed dense output before it crosses the collection boundary."""

    def test_accepts_well_formed_result(self) -> None:
        """A well-formed dense result validates version and dimension without raising."""
        from ml_compute_service.events.handlers import _validate_dense_result

        pipeline = MagicMock()
        pipeline.manifest.dense.embedding_dim = 3
        pipeline.manifest.get_entity_version.return_value = "v1"
        result = MagicMock()
        result.dense_embedding = np.array([0.1, 0.2, 0.3], dtype=np.float32)

        _validate_dense_result(pipeline, result, entity_type="skill", collection_version="v1")

    def test_rejects_stale_collection_version(self) -> None:
        """A mismatched collection_version is rejected as stale data."""
        from ml_compute_service.events.handlers import _validate_dense_result
        from nohiki_common_exceptions import StaleDataError

        pipeline = MagicMock()
        pipeline.manifest.dense.embedding_dim = 3
        pipeline.manifest.get_entity_version.return_value = "v2"
        result = MagicMock()
        result.dense_embedding = np.array([0.1, 0.2, 0.3], dtype=np.float32)

        with pytest.raises(StaleDataError):
            _validate_dense_result(pipeline, result, entity_type="skill", collection_version="v1")


class TestValidateDenseBatchResultDimensionCheck:
    """Validate collection version and dimension once row cardinality is confirmed."""

    def test_accepts_well_formed_batch_result(self) -> None:
        """A well-formed batch result validates version and dimension without raising."""
        from ml_compute_service.events.handlers import _validate_dense_batch_result

        pipeline = MagicMock()
        pipeline.manifest.dense.embedding_dim = 2
        pipeline.manifest.get_entity_version.return_value = "v1"
        result = MagicMock()
        result.dense_embeddings = np.zeros((2, 2), dtype=np.float32)
        result.content_hashes = ["h1", "h2"]

        _validate_dense_batch_result(
            pipeline,
            result,
            expected_count=2,
            entity_type="skill",
            collection_version="v1",
        )

    def test_rejects_dimension_mismatch(self) -> None:
        """A dense batch row whose width diverges from the manifest is rejected."""
        from ml_compute_service.events.handlers import _validate_dense_batch_result
        from nohiki_common_exceptions import ValidationError

        pipeline = MagicMock()
        pipeline.manifest.dense.embedding_dim = 4
        pipeline.manifest.get_entity_version.return_value = "v1"
        result = MagicMock()
        result.dense_embeddings = np.zeros((2, 2), dtype=np.float32)
        result.content_hashes = ["h1", "h2"]

        with pytest.raises(ValidationError, match="Dense dimension must be 4"):
            _validate_dense_batch_result(
                pipeline,
                result,
                expected_count=2,
                entity_type="skill",
                collection_version="v1",
            )


class TestInferenceTimeoutLifecycle:
    """Protect timeout, permit, callback, and orphan-task lifecycle contracts."""

    @staticmethod
    async def _yield_once() -> None:
        """Yield one event-loop turn without relying on wall-clock timing."""
        loop = asyncio.get_running_loop()
        yielded: asyncio.Future[None] = loop.create_future()
        loop.call_soon(yielded.set_result, None)
        await yielded

    @staticmethod
    async def _wait_for_thread(event: threading.Event) -> None:
        """Wait for a worker-thread gate without blocking the event loop."""
        await asyncio.to_thread(event.wait)

    @pytest.mark.asyncio
    async def test_timeout_retains_permit_until_thread_completion(self) -> None:
        """A timed-out model cannot overlap later work before its thread exits."""
        from ml_compute_service.events.handlers import _run_inference

        semaphore = asyncio.Semaphore(1)
        first_started = threading.Event()
        first_release = threading.Event()
        first_finished = threading.Event()
        second_started = threading.Event()
        active = 0
        maximum_active = 0
        active_lock = threading.Lock()

        def enter_model() -> None:
            nonlocal active, maximum_active
            with active_lock:
                active += 1
                maximum_active = max(maximum_active, active)

        def leave_model() -> None:
            nonlocal active
            with active_lock:
                active -= 1

        def first_model() -> str:
            enter_model()
            first_started.set()
            try:
                first_release.wait()
                return "first"
            finally:
                leave_model()
                first_finished.set()

        def second_model() -> str:
            enter_model()
            second_started.set()
            try:
                return "second"
            finally:
                leave_model()

        with (
            patch("ml_compute_service.events.handlers._INFERENCE_SEMAPHORE", semaphore),
            patch("ml_compute_service.events.handlers.settings") as mock_settings,
        ):
            mock_settings.processing.timeout_seconds = 0
            timed_out = asyncio.create_task(_run_inference(first_model))
            await self._wait_for_thread(first_started)

            with pytest.raises(TimeoutError):
                await timed_out
            mock_settings.processing.timeout_seconds = 60

            later = asyncio.create_task(_run_inference(second_model))
            await self._yield_once()
            assert not second_started.is_set()

            first_release.set()
            assert await later == "second"
            await self._wait_for_thread(first_finished)

        assert maximum_active == 1

    @pytest.mark.asyncio
    async def test_timeout_callback_is_published_exactly_once(self) -> None:
        """Timeout emits one error callback and never emits a late success callback."""
        from ml_compute_service.events.handlers import _handle_embedding

        request = MagicMock()
        request.requested_types = [EmbeddingType.DENSE]
        request.encoding_mode = EncodingMode.DOCUMENT
        request.entity_id = "timeout-entity"
        request.text = "blocked text"
        request.collection_version = "v1"
        request.entity_type.name = "SKILL"
        request.command.attributes = {}
        request.command.operation_id = "timeout-operation"
        request.command.callback_topic = "ml.callback.test.v1"
        request.publish_to_index = False
        message = MagicMock()
        message.embedding_request = request
        message.metadata.correlation_id = "timeout-correlation"
        context = MagicMock()

        started = threading.Event()
        release = threading.Event()
        finished = threading.Event()
        result = MagicMock()
        result.dense_embedding = [1.0, 2.0]
        result.content_hash = "late-success"

        def encode_dense(_text: str, _entity_id: str) -> MagicMock:
            started.set()
            try:
                release.wait()
                return result
            finally:
                finished.set()

        pipeline = MagicMock()
        pipeline.encode_dense = encode_dense
        pipeline.manifest.dense.model_id = "dense-model"

        with (
            patch("ml_compute_service.events.handlers._INFERENCE_SEMAPHORE", asyncio.Semaphore(1)),
            patch("ml_compute_service.events.handlers.settings") as mock_settings,
            patch("ml_compute_service.events.handlers.get_encoding_pipeline", return_value=pipeline),
            patch("ml_compute_service.events.handlers.kafka_client") as mock_kafka,
        ):
            mock_settings.processing.timeout_seconds = 0
            mock_settings.service_name = "ml-compute-service"
            mock_kafka.publish = AsyncMock()

            await _handle_embedding(message, context)
            await self._wait_for_thread(started)

            assert mock_kafka.publish.call_count == 1
            callback = mock_kafka.publish.call_args.kwargs["message"]
            assert callback.error is not None
            assert callback.success is None

            release.set()
            await self._wait_for_thread(finished)
            await self._yield_once()

            assert mock_kafka.publish.call_count == 1

    @pytest.mark.asyncio
    async def test_orphan_worker_exception_is_consumed(self) -> None:
        """An exception raised after timeout does not reach the loop exception handler."""
        from ml_compute_service.events.handlers import _run_inference

        semaphore = asyncio.Semaphore(1)
        started = threading.Event()
        release = threading.Event()
        finished = threading.Event()
        loop = asyncio.get_running_loop()
        exception_contexts: list[dict[str, object]] = []
        previous_handler = loop.get_exception_handler()

        def loop_exception_handler(_loop: asyncio.AbstractEventLoop, context: dict[str, object]) -> None:
            exception_contexts.append(context)

        def failing_model() -> None:
            started.set()
            try:
                release.wait()
                msg = "orphan inference failure"
                raise RuntimeError(msg)
            finally:
                finished.set()

        loop.set_exception_handler(loop_exception_handler)
        try:
            with (
                patch("ml_compute_service.events.handlers._INFERENCE_SEMAPHORE", semaphore),
                patch("ml_compute_service.events.handlers.settings") as mock_settings,
            ):
                mock_settings.processing.timeout_seconds = 0
                timed_out = asyncio.create_task(_run_inference(failing_model))
                await self._wait_for_thread(started)

                with pytest.raises(TimeoutError):
                    await timed_out

                release.set()
                await self._wait_for_thread(finished)
                for _ in range(4):
                    await self._yield_once()
                gc.collect()
                await self._yield_once()
        finally:
            loop.set_exception_handler(previous_handler)

        assert exception_contexts == []

    @pytest.mark.asyncio
    async def test_await_inference_worker_propagates_task_cancellation(self) -> None:
        """A cancelled worker task surfaces as CancelledError to the caller, not a hang."""
        from ml_compute_service.events.handlers import _await_inference_worker

        async def blocked() -> str:
            await asyncio.sleep(3600)
            return "unreachable"

        worker = asyncio.create_task(blocked())
        await self._yield_once()
        worker.cancel()

        with pytest.raises(asyncio.CancelledError):
            await _await_inference_worker(worker)

    @pytest.mark.asyncio
    async def test_run_inference_releases_permit_when_task_creation_fails(self) -> None:
        """A failed worker task creation must not leak the acquired semaphore permit."""
        from ml_compute_service.events import handlers
        from ml_compute_service.events.handlers import _run_inference

        def fail_after_closing_coroutine(coro: Coroutine[object, object, object]) -> None:
            coro.close()
            msg = "no running loop"
            raise RuntimeError(msg)

        semaphore = asyncio.Semaphore(1)
        with (
            patch.object(handlers, "_INFERENCE_SEMAPHORE", semaphore),
            patch.object(handlers, "_create_task", side_effect=fail_after_closing_coroutine),
            pytest.raises(RuntimeError, match="no running loop"),
        ):
            await _run_inference(lambda: "unused")

        assert not semaphore.locked()


class TestStartEventConsumer:
    """Tests for start_event_consumer function."""

    def test_starts_kafka_consumers(self) -> None:
        """Test that start_event_consumer starts Kafka consumers."""
        from ml_compute_service.events.handlers import start_event_consumer

        with (
            patch("ml_compute_service.events.handlers.kafka_client") as mock_kafka,
            patch("ml_compute_service.events.handlers.logger") as mock_logger,
            patch("ml_compute_service.events.handlers.settings") as mock_settings,
        ):
            mock_kafka.start_consumers = MagicMock()
            mock_settings.service_name = "ml-compute-service"

            start_event_consumer()

            mock_kafka.start_consumers.assert_called_once()
            mock_logger.info.assert_called_once()


class TestHandleInternalCompute:
    """Tests for handle_internal_compute handler."""

    @pytest.mark.asyncio
    async def test_handles_embedding_operation(self) -> None:
        """Test routing to embedding handler for EMBEDDING operation type."""
        from ml_compute_service.events.handlers import handle_internal_compute

        message = MagicMock()
        message.operation_type = MlOperationType.EMBEDDING
        message.embedding_request = MagicMock()

        context = MagicMock()

        with patch(
            "ml_compute_service.events.handlers._handle_embedding",
            new_callable=AsyncMock,
        ) as mock_handle:
            await handle_internal_compute(message, context)

            mock_handle.assert_called_once_with(message, context)

    @pytest.mark.asyncio
    async def test_handles_rerank_operation(self) -> None:
        """Test warning for RERANK operation type."""
        from ml_compute_service.events.handlers import handle_internal_compute

        message = MagicMock()
        message.operation_type = MlOperationType.RERANK

        context = MagicMock()

        with (
            patch("ml_compute_service.events.handlers.logger") as mock_logger,
            patch(
                "ml_compute_service.events.handlers._publish_embedding_error",
                new_callable=AsyncMock,
            ) as mock_publish_error,
        ):
            await handle_internal_compute(message, context)

            mock_logger.warning.assert_called_once()
            mock_publish_error.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_unknown_operation(self) -> None:
        """Test warning for unknown operation type."""
        from ml_compute_service.events.handlers import handle_internal_compute

        message = MagicMock()
        message.operation_type = MagicMock()
        message.operation_type.name = "UNKNOWN"

        context = MagicMock()

        with patch("ml_compute_service.events.handlers.logger") as mock_logger:
            await handle_internal_compute(message, context)

            mock_logger.warning.assert_called_once()


class TestGetCommand:
    """Extract the CommandHeader matching the request's declared operation type."""

    def test_returns_embedding_command(self) -> None:
        """EMBEDDING operations resolve the command from embedding_request."""
        from ml_compute_service.events.handlers import _get_command

        message = MagicMock()
        message.operation_type = MlOperationType.EMBEDDING
        message.embedding_request.command = "embedding-command"

        assert _get_command(message) == "embedding-command"

    def test_raises_when_embedding_request_missing(self) -> None:
        """EMBEDDING operations require an embedding_request payload."""
        from ml_compute_service.events.handlers import _get_command

        message = MagicMock()
        message.operation_type = MlOperationType.EMBEDDING
        message.embedding_request = None

        with pytest.raises(ValueError, match="embedding_request is None"):
            _get_command(message)

    def test_returns_batch_embedding_command(self) -> None:
        """BATCH_EMBEDDING operations resolve the command from batch_embedding_request."""
        from ml_compute_service.events.handlers import _get_command

        message = MagicMock()
        message.operation_type = MlOperationType.BATCH_EMBEDDING
        message.batch_embedding_request.command = "batch-command"

        assert _get_command(message) == "batch-command"

    def test_raises_when_batch_embedding_request_missing(self) -> None:
        """BATCH_EMBEDDING operations require a batch_embedding_request payload."""
        from ml_compute_service.events.handlers import _get_command

        message = MagicMock()
        message.operation_type = MlOperationType.BATCH_EMBEDDING
        message.batch_embedding_request = None

        with pytest.raises(ValueError, match="batch_embedding_request is None"):
            _get_command(message)

    def test_raises_when_rerank_request_missing(self) -> None:
        """RERANK operations require a rerank_request payload."""
        from ml_compute_service.events.handlers import _get_command

        message = MagicMock()
        message.operation_type = MlOperationType.RERANK
        message.rerank_request = None

        with pytest.raises(ValueError, match="rerank_request is None"):
            _get_command(message)

    def test_raises_for_unknown_operation_type(self) -> None:
        """An operation type outside the known set is rejected rather than silently ignored."""
        from ml_compute_service.events.handlers import _get_command

        message = MagicMock()
        message.operation_type = MagicMock()

        with pytest.raises(ValueError, match="Unknown operation type"):
            _get_command(message)


class TestHandleEmbedding:
    """Tests for _handle_embedding function."""

    def _make_retrieval_request(self) -> MagicMock:
        """Create a mock embedding request with retrieval types."""
        req = MagicMock()
        req.requested_types = [
            EmbeddingType.MUVERA,
            EmbeddingType.SPARSE,
            EmbeddingType.COLBERT,
        ]
        req.encoding_mode = EncodingMode.DOCUMENT
        req.entity_id = "test-entity"
        req.text = "test text"
        req.collection_version = "v1"
        req.entity_type = MagicMock()
        req.command.attributes = {}
        req.command.operation_id = "550e8400-e29b-41d4-a716-446655440000"
        req.command.callback_topic = "ml.callback.test.v1"
        req.publish_to_index = False
        return req

    def _make_dense_request(self) -> MagicMock:
        """Create a mock embedding request with DENSE type only."""
        req = MagicMock()
        req.requested_types = [EmbeddingType.DENSE]
        req.encoding_mode = EncodingMode.DOCUMENT
        req.entity_id = "test-entity"
        req.text = "test text"
        req.collection_version = "v1"
        req.entity_type = MagicMock()
        req.command.attributes = {}
        req.command.operation_id = "550e8400-e29b-41d4-a716-446655440000"
        req.command.callback_topic = "ml.callback.test.v1"
        req.publish_to_index = False
        return req

    def _make_retrieval_result(self) -> MagicMock:
        """Create a mock EncodingResult from the pipeline."""
        result = MagicMock()
        result.muvera_fde = [1.0, 2.0]
        result.sparse_vector.indices = [0, 1]
        result.sparse_vector.values = [0.5, 0.5]
        result.colbert_tokens = MagicMock()
        result.colbert_tokens.flatten.return_value = MagicMock(tolist=lambda: [1.0, 2.0])
        result.colbert_tokens.shape = (2, 48)
        result.content_hash = "abc123"
        return result

    def _make_message(self, embedding_request: MagicMock) -> MagicMock:
        """Create a mock InternalComputeRequest."""
        message = MagicMock()
        message.embedding_request = embedding_request
        message.metadata.correlation_id = "test-correlation"
        return message

    @pytest.mark.asyncio
    async def test_handles_retrieval_embedding(self) -> None:
        """Test retrieval embedding (MUVERA+SPARSE+COLBERT) with DOCUMENT mode."""
        from ml_compute_service.events.handlers import _handle_embedding

        req = self._make_retrieval_request()
        message = self._make_message(req)
        context = MagicMock()

        mock_pipeline = MagicMock()
        mock_pipeline.encode_document.return_value = self._make_retrieval_result()

        with (
            patch("ml_compute_service.events.handlers.get_encoding_pipeline", return_value=mock_pipeline),
            patch("ml_compute_service.events.handlers.kafka_client") as mock_kafka,
        ):
            mock_kafka.publish = AsyncMock()
            mock_kafka.publish_raw = AsyncMock()

            await _handle_embedding(message, context)

            mock_kafka.publish.assert_called_once()
            mock_pipeline.encode_document.assert_called_once()

    @pytest.mark.asyncio
    async def test_handles_dense_only_embedding(self) -> None:
        """Test DENSE-only embedding uses encode_dense."""
        from ml_compute_service.events.handlers import _handle_embedding

        req = self._make_dense_request()
        message = self._make_message(req)
        context = MagicMock()

        mock_pipeline = MagicMock()
        mock_dense_result = MagicMock()
        mock_dense_result.dense_embedding = [1.0, 2.0]
        mock_dense_result.content_hash = "abc123"
        mock_pipeline.encode_dense.return_value = mock_dense_result

        with (
            patch("ml_compute_service.events.handlers.get_encoding_pipeline", return_value=mock_pipeline),
            patch("ml_compute_service.events.handlers.kafka_client") as mock_kafka,
        ):
            mock_kafka.publish = AsyncMock()

            await _handle_embedding(message, context)

            mock_kafka.publish.assert_called_once()
            mock_pipeline.encode_dense.assert_called_once()
            mock_pipeline.encode_document.assert_not_called()
            mock_pipeline.encode_query.assert_not_called()

    @pytest.mark.asyncio
    async def test_query_encoding_mode_uses_encode_query(self) -> None:
        """Test QUERY encoding mode dispatches to encode_query."""
        from ml_compute_service.events.handlers import _handle_embedding

        req = self._make_retrieval_request()
        req.encoding_mode = EncodingMode.QUERY
        message = self._make_message(req)
        context = MagicMock()

        mock_pipeline = MagicMock()
        mock_pipeline.encode_query.return_value = self._make_retrieval_result()

        with (
            patch("ml_compute_service.events.handlers.get_encoding_pipeline", return_value=mock_pipeline),
            patch("ml_compute_service.events.handlers.kafka_client") as mock_kafka,
        ):
            mock_kafka.publish = AsyncMock()
            mock_kafka.publish_raw = AsyncMock()

            await _handle_embedding(message, context)

            mock_pipeline.encode_query.assert_called_once()
            mock_pipeline.encode_document.assert_not_called()

    @pytest.mark.asyncio
    async def test_publish_to_index_sends_qdrant_payload(self) -> None:
        """Test that publish_to_index=True publishes JSON to Qdrant sink topic."""
        from ml_compute_service.events.handlers import _handle_embedding

        req = self._make_retrieval_request()
        req.publish_to_index = True
        message = self._make_message(req)
        context = MagicMock()

        mock_pipeline = MagicMock()
        mock_pipeline.encode_document.return_value = self._make_retrieval_result()

        with (
            patch("ml_compute_service.events.handlers.get_encoding_pipeline", return_value=mock_pipeline),
            patch("ml_compute_service.events.handlers._build_qdrant_sink_payload", return_value={"id": "x"}),
            patch("ml_compute_service.events.handlers.kafka_client") as mock_kafka,
        ):
            mock_kafka.publish = AsyncMock()
            mock_kafka.publish_raw = AsyncMock()

            await _handle_embedding(message, context)

            assert mock_kafka.publish.call_count == 2
            mock_kafka.publish_raw.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_qdrant_publish_when_publish_to_index_false(self) -> None:
        """Test that publish_to_index=False skips Qdrant sink publish."""
        from ml_compute_service.events.handlers import _handle_embedding

        req = self._make_retrieval_request()
        req.publish_to_index = False
        message = self._make_message(req)
        context = MagicMock()

        mock_pipeline = MagicMock()
        mock_pipeline.encode_document.return_value = self._make_retrieval_result()

        with (
            patch("ml_compute_service.events.handlers.get_encoding_pipeline", return_value=mock_pipeline),
            patch("ml_compute_service.events.handlers.kafka_client") as mock_kafka,
        ):
            mock_kafka.publish = AsyncMock()
            mock_kafka.publish_raw = AsyncMock()

            await _handle_embedding(message, context)

            mock_kafka.publish.assert_called_once()
            mock_kafka.publish_raw.assert_not_called()

    @pytest.mark.asyncio
    async def test_raises_when_embedding_request_is_none(self) -> None:
        """Test ValueError when embedding_request is None."""
        from ml_compute_service.events.handlers import _handle_embedding

        message = MagicMock()
        message.embedding_request = None

        context = MagicMock()

        with pytest.raises(ValueError, match="embedding_request is required"):
            await _handle_embedding(message, context)

    @pytest.mark.asyncio
    async def test_handles_exception_and_publishes_error(self) -> None:
        """Test exception handling and error publishing."""
        from ml_compute_service.events.handlers import _handle_embedding

        req = self._make_retrieval_request()
        message = self._make_message(req)
        context = MagicMock()

        with (
            patch("ml_compute_service.events.handlers.get_encoding_pipeline") as mock_get_pipeline,
            patch(
                "ml_compute_service.events.handlers._publish_embedding_error",
                new_callable=AsyncMock,
            ) as mock_publish,
            patch("ml_compute_service.events.handlers.logger") as mock_logger,
            patch("ml_compute_service.events.handlers.asyncio") as mock_asyncio,
        ):
            mock_pipeline = MagicMock()
            mock_asyncio.to_thread = AsyncMock(side_effect=RuntimeError("Embedding failed"))
            mock_get_pipeline.return_value = mock_pipeline

            await _handle_embedding(message, context)

            mock_publish.assert_called_once()
            mock_logger.exception.assert_called_once()


class TestEncodeRetrieval:
    """Tests for _encode_retrieval helper."""

    @pytest.mark.asyncio
    async def test_document_mode_uses_asyncio_to_thread(self) -> None:
        """Test DOCUMENT mode dispatches to encode_document via asyncio.to_thread."""
        from ml_compute_service.events.handlers import _encode_retrieval

        pipeline = MagicMock()
        req = MagicMock()
        req.encoding_mode = EncodingMode.DOCUMENT
        req.text = "test text"
        req.entity_id = "ent-1"

        with patch("ml_compute_service.events.handlers.asyncio") as mock_asyncio:
            mock_asyncio.to_thread = AsyncMock(return_value=MagicMock())
            await _encode_retrieval(pipeline, req)

        mock_asyncio.to_thread.assert_called_once_with(pipeline.encode_document, req.text, req.entity_id)

    @pytest.mark.asyncio
    async def test_query_mode_uses_asyncio_to_thread(self) -> None:
        """Test QUERY mode dispatches to encode_query via asyncio.to_thread."""
        from ml_compute_service.events.handlers import _encode_retrieval

        pipeline = MagicMock()
        req = MagicMock()
        req.encoding_mode = EncodingMode.QUERY
        req.text = "test query"

        with patch("ml_compute_service.events.handlers.asyncio") as mock_asyncio:
            mock_asyncio.to_thread = AsyncMock(return_value=MagicMock())
            await _encode_retrieval(pipeline, req)

        mock_asyncio.to_thread.assert_called_once_with(pipeline.encode_query, req.text)

    @pytest.mark.asyncio
    async def test_invalid_encoding_mode_raises_value_error(self) -> None:
        """Test that an unrecognized encoding_mode raises ValueError."""
        from ml_compute_service.events.handlers import _encode_retrieval

        pipeline = MagicMock()
        req = MagicMock()
        req.encoding_mode = MagicMock()

        with pytest.raises(ValueError, match="encoding_mode must be DOCUMENT or QUERY"):
            await _encode_retrieval(pipeline, req)


class TestExtractRetrievalVectors:
    """Tests for _extract_retrieval_vectors helper."""

    def _make_result(self) -> MagicMock:
        """Create a mock EncodingResult."""
        result = MagicMock()
        result.muvera_fde = [1.0, 2.0]
        result.sparse_vector.indices = [0, 1]
        result.sparse_vector.values = [0.5, 0.5]
        result.colbert_tokens = MagicMock()
        result.colbert_tokens.flatten.return_value = MagicMock(tolist=lambda: [1.0, 2.0])
        result.colbert_tokens.shape = (2, 48)
        result.content_hash = "abc123"
        return result

    def test_extracts_muvera_vector(self) -> None:
        """Test MUVERA vector extraction."""
        from ml_compute_service.events.handlers import _extract_retrieval_vectors

        pipeline = MagicMock()
        pipeline.manifest.late_interaction.model_id = "colbert-model"
        req = MagicMock()
        req.collection_version = "v1"

        vectors = _extract_retrieval_vectors(
            pipeline,
            self._make_result(),
            frozenset({EmbeddingType.MUVERA}),
            req,
        )

        assert len(vectors) == 1
        assert vectors[0].embedding_type == EmbeddingType.MUVERA

    def test_extracts_sparse_vector(self) -> None:
        """Test SPARSE vector extraction."""
        from ml_compute_service.events.handlers import _extract_retrieval_vectors

        pipeline = MagicMock()
        pipeline.manifest.sparse.model_id = "sparse-model"
        req = MagicMock()
        req.collection_version = "v1"

        vectors = _extract_retrieval_vectors(
            pipeline,
            self._make_result(),
            frozenset({EmbeddingType.SPARSE}),
            req,
        )

        assert len(vectors) == 1
        assert vectors[0].embedding_type == EmbeddingType.SPARSE

    def test_extracts_colbert_vector(self) -> None:
        """Test COLBERT vector extraction."""
        from ml_compute_service.events.handlers import _extract_retrieval_vectors

        pipeline = MagicMock()
        pipeline.manifest.late_interaction.model_id = "colbert-model"
        req = MagicMock()
        req.collection_version = "v1"

        vectors = _extract_retrieval_vectors(
            pipeline,
            self._make_result(),
            frozenset({EmbeddingType.COLBERT}),
            req,
        )

        assert len(vectors) == 1
        assert vectors[0].embedding_type == EmbeddingType.COLBERT

    def test_extracts_all_retrieval_types(self) -> None:
        """Test extracting all three retrieval vector types."""
        from ml_compute_service.events.handlers import _extract_retrieval_vectors

        pipeline = MagicMock()
        pipeline.manifest.late_interaction.model_id = "colbert-model"
        pipeline.manifest.sparse.model_id = "sparse-model"
        req = MagicMock()
        req.collection_version = "v1"

        all_types = frozenset({EmbeddingType.MUVERA, EmbeddingType.SPARSE, EmbeddingType.COLBERT})
        vectors = _extract_retrieval_vectors(pipeline, self._make_result(), all_types, req)

        assert len(vectors) == 3
        types = {v.embedding_type for v in vectors}
        assert types == {EmbeddingType.MUVERA, EmbeddingType.SPARSE, EmbeddingType.COLBERT}

    def test_returns_empty_when_no_matching_types(self) -> None:
        """Test that non-retrieval types yield no vectors."""
        from ml_compute_service.events.handlers import _extract_retrieval_vectors

        pipeline = MagicMock()
        req = MagicMock()
        req.collection_version = "v1"

        vectors = _extract_retrieval_vectors(
            pipeline,
            self._make_result(),
            frozenset({EmbeddingType.DENSE}),
            req,
        )

        assert vectors == []


class TestBuildDenseVector:
    """Tests for _build_dense_vector helper."""

    def test_builds_dense_embedding_vector(self) -> None:
        """Test building a DENSE EmbeddingVector from DenseEncodingResult."""
        from ml_compute_service.events.handlers import _build_dense_vector

        pipeline = MagicMock()
        pipeline.manifest.dense.model_id = "dense-model"

        result = MagicMock()
        result.dense_embedding = [0.1, 0.2, 0.3]
        result.content_hash = "hash123"

        vector = _build_dense_vector(pipeline, result, "v2")

        assert vector.embedding_type == EmbeddingType.DENSE
        assert vector.content_hash == "hash123"
        assert vector.model_id == "dense-model"
        assert vector.collection_version == "v2"


class TestBuildEmbeddingResult:
    """Tests for _build_embedding_result helper."""

    def test_builds_embedding_result_with_embeddings(self) -> None:
        """Test constructing EmbeddingResult success payload from computed embeddings."""
        from ml_compute_service.events.handlers import _build_embedding_result

        pipeline = MagicMock()
        pipeline.manifest.late_interaction.model_id = "test-model"

        message = MagicMock()
        message.metadata.correlation_id = "corr-1"
        message.selected_provider = "k8s"

        req = MagicMock()
        req.collection_version = "v1"
        req.requested_types = [EmbeddingType.DENSE]
        req.encoding_mode = EncodingMode.DOCUMENT
        req.command.attributes = {"key": "val"}

        embedding = MagicMock()
        embedding.content_hash = "hash-abc"

        with patch("ml_compute_service.events.handlers.settings") as mock_settings:
            mock_settings.service_name = "ml-compute-service"
            result = _build_embedding_result(pipeline, message, req, [embedding])

        assert result.collection_version == "v1"
        assert result.content_hash == "hash-abc"
        assert result.requested_types == [EmbeddingType.DENSE]
        assert result.encoding_mode == EncodingMode.DOCUMENT
        assert len(result.embeddings) == 1


class TestCreateEventMetadata:
    """Tests for _create_event_metadata helper."""

    def test_creates_metadata_with_uuid(self) -> None:
        """Test creating metadata with UUID event_id."""
        from ml_compute_service.events.handlers import _create_event_metadata

        metadata = _create_event_metadata()

        assert metadata.event_id is not None
        assert len(metadata.event_id) == 36

    def test_creates_metadata_with_correlation_id(self) -> None:
        """Test creating metadata with correlation_id."""
        from ml_compute_service.events.handlers import _create_event_metadata

        metadata = _create_event_metadata("test-correlation")

        assert metadata.correlation_id == "test-correlation"

    def test_creates_metadata_without_correlation_id(self) -> None:
        """Test creating metadata with default correlation_id."""
        from ml_compute_service.events.handlers import _create_event_metadata

        metadata = _create_event_metadata()

        # When None is passed, it should use a generated UUID
        assert metadata.correlation_id is not None


class TestBuildPayloadMetadata:
    """Tests for _build_payload_metadata helper."""

    def test_builds_metadata_with_model_and_provider(self) -> None:
        """Test building payload metadata with model and provider info."""
        from ml_compute_service.events.handlers import _build_payload_metadata

        mock_pipeline = MagicMock()
        mock_pipeline.manifest.late_interaction.model_id = "test-model"

        message = MagicMock()
        message.selected_provider = "test-provider"

        context = {"key1": "value1", "key2": "value2"}

        result = _build_payload_metadata(mock_pipeline, message, context)

        assert result["model_id"] == "test-model"
        assert result["provider"] == "test-provider"
        assert result["key1"] == "value1"
        assert result["key2"] == "value2"


class TestBuildQdrantSinkPayload:
    """Tests for _build_qdrant_sink_payload helper."""

    def test_builds_payload_with_all_vectors(self) -> None:
        """Test building Qdrant payload with all vector types."""
        from ml_compute_service.events.handlers import _build_qdrant_sink_payload

        mock_req = MagicMock()
        mock_req.entity_id = "test-entity"
        mock_req.entity_type.name = "JOB"
        mock_req.collection_version = "v1"
        mock_req.command.attributes = {}

        mock_result = MagicMock()
        mock_result.muvera_fde = np.array([1.0, 2.0])
        mock_result.colbert_tokens = np.array([[[1.0, 2.0], [3.0, 4.0]]])
        mock_result.sparse_vector.indices = np.array([0, 1])
        mock_result.sparse_vector.values = np.array([0.5, 0.5])
        mock_result.content_hash = "abc123"

        mock_pipeline = MagicMock()
        mock_pipeline.manifest.late_interaction.model_id = "test-model"
        mock_pipeline.manifest.get_collection_name.return_value = "jobs-v1"

        result = _build_qdrant_sink_payload(mock_req, mock_result, mock_pipeline)

        assert result["id"] == "test-entity"
        assert result["collection_name"] == "jobs-v1"
        assert "vector" in result
        assert "muvera" in result["vector"]
        assert "colbert" in result["vector"]
        assert "sparse" in result["vector"]
        assert result["payload"]["content_hash"] == "abc123"


class TestPublishEmbeddingError:
    """Tests for _publish_embedding_error function."""

    @pytest.mark.asyncio
    async def test_publishes_error_event(self) -> None:
        """Test publishing EmbeddingCallback error to command.callback_topic."""
        from ml_compute_service.events.handlers import _publish_embedding_error

        embedding_request = MagicMock()
        embedding_request.entity_id = "test-entity"
        embedding_request.entity_type = MagicMock()
        embedding_request.command.callback_topic = "ml.callback.test.v1"
        embedding_request.command.operation_id = "op-test"

        message = MagicMock()
        message.embedding_request = embedding_request
        message.metadata.correlation_id = "test-correlation"

        with patch("ml_compute_service.events.handlers.kafka_client") as mock_kafka:
            mock_kafka.publish = AsyncMock()

            await _publish_embedding_error(message, "Test error message")

            mock_kafka.publish.assert_called_once()
            call_args = mock_kafka.publish.call_args
            assert call_args.kwargs["topic"] == "ml.callback.test.v1"

    @pytest.mark.asyncio
    async def test_raises_when_embedding_request_is_none(self) -> None:
        """Test ValueError raised when embedding_request is None."""
        from ml_compute_service.events.handlers import _publish_embedding_error

        message = MagicMock()
        message.embedding_request = None

        with pytest.raises(ValueError, match="embedding_request is None"):
            await _publish_embedding_error(message, "Test error")


class TestHandleInternalComputeBatchRouting:
    """Tests for BATCH_EMBEDDING routing in handle_internal_compute."""

    @pytest.mark.asyncio
    async def test_routes_batch_embedding_to_handler(self) -> None:
        """Test BATCH_EMBEDDING operation type routes to _handle_batch_embedding."""
        from ml_compute_service.events.handlers import handle_internal_compute

        message = MagicMock()
        message.operation_type = MlOperationType.BATCH_EMBEDDING
        message.batch_embedding_request = MagicMock()
        context = MagicMock()

        with patch(
            "ml_compute_service.events.handlers._handle_batch_embedding",
            new_callable=AsyncMock,
        ) as mock_handle:
            await handle_internal_compute(message, context)

        mock_handle.assert_called_once_with(message, context)


class TestPublishBatchError:
    """Tests for _publish_batch_error function."""

    @pytest.mark.asyncio
    async def test_publishes_batch_failed_event(self) -> None:
        """Test publishing BatchEmbeddingCallback error to command.callback_topic."""
        from ml_compute_service.events.handlers import _publish_batch_error

        batch_request = MagicMock()
        batch_request.entity_type = MagicMock()
        batch_request.command.callback_topic = "skill.sys.batch-callback.v1"
        batch_request.command.operation_id = "batch-123"
        batch_request.collection_version = "skills-v7"
        batch_request.encoding_mode = EncodingMode.QUERY

        message = MagicMock()
        message.batch_embedding_request = batch_request
        message.metadata.correlation_id = "batch-123"

        with patch("ml_compute_service.events.handlers.kafka_client") as mock_kafka:
            mock_kafka.publish = AsyncMock()

            await _publish_batch_error(message, "Pipeline crashed")

            mock_kafka.publish.assert_called_once()
            call_args = mock_kafka.publish.call_args
            assert call_args.kwargs["topic"] == "skill.sys.batch-callback.v1"
            assert call_args.kwargs["key"] == "batch-123"
            failed = call_args.kwargs["message"]
            assert failed.collection_version == "skills-v7"
            assert failed.encoding_mode == EncodingMode.QUERY

    @pytest.mark.asyncio
    async def test_raises_when_batch_request_is_none(self) -> None:
        """Test ValueError raised when batch_embedding_request is None."""
        from ml_compute_service.events.handlers import _publish_batch_error

        message = MagicMock()
        message.batch_embedding_request = None

        with pytest.raises(ValueError, match="batch_embedding_request is None"):
            await _publish_batch_error(message, "Test error")


class TestHandleBatchEmbedding:
    """Tests for _handle_batch_embedding handler."""

    def _make_batch_items(self, count: int = 2) -> list[MagicMock]:
        """Create mock BatchEmbeddingItem list."""
        items = []
        for i in range(count):
            item = MagicMock()
            item.point_id = f"point-{i}"
            item.entity_id = f"entity-{i}"
            item.text = f"Skill text {i}"
            item.item_attributes = {}
            items.append(item)
        return items

    def _make_batch_message(self, count: int = 2) -> MagicMock:
        """Create a mock InternalComputeRequest for batch embedding."""
        req = MagicMock()
        req.items = self._make_batch_items(count)
        req.collection_version = "v1"
        req.entity_type = MagicMock()
        req.encoding_mode = MagicMock()
        req.command.callback_topic = "skill.sys.batch-callback.v1"
        req.command.operation_id = "batch-abc"

        message = MagicMock()
        message.batch_embedding_request = req
        message.metadata.correlation_id = "batch-abc"
        return message

    def _make_batch_encoding_result(self, count: int = 2) -> MagicMock:
        """Create a mock DenseBatchEncodingResult with per-item arrays and hashes."""
        result = MagicMock()
        result.dense_embeddings = [np.array([0.1 * i, 0.2 * i]) for i in range(1, count + 1)]
        result.content_hashes = [f"h{i}" for i in range(1, count + 1)]
        return result

    @pytest.mark.asyncio
    async def test_raises_when_batch_request_is_none(self) -> None:
        """Test ValueError raised when batch_embedding_request is None."""
        from ml_compute_service.events.handlers import _handle_batch_embedding

        message = MagicMock()
        message.batch_embedding_request = None
        context = MagicMock()

        with pytest.raises(ValueError, match="batch_embedding_request is required"):
            await _handle_batch_embedding(message, context)

    @pytest.mark.asyncio
    async def test_publishes_completed_on_success(self) -> None:
        """Test BatchEmbeddingCompleted published after successful encode_dense_batch."""
        from ml_compute_service.events.handlers import _handle_batch_embedding

        message = self._make_batch_message()
        context = MagicMock()
        mock_pipeline = MagicMock()
        mock_pipeline.manifest.dense.model_id = "dense-model"

        with (
            patch(
                "ml_compute_service.events.handlers.get_encoding_pipeline",
                return_value=mock_pipeline,
            ),
            patch("ml_compute_service.events.handlers.asyncio") as mock_asyncio,
            patch("ml_compute_service.events.handlers.kafka_client") as mock_kafka,
        ):
            mock_asyncio.to_thread = AsyncMock(return_value=self._make_batch_encoding_result())
            mock_kafka.publish = AsyncMock()

            await _handle_batch_embedding(message, context)

            mock_kafka.publish.assert_called_once()
            call_args = mock_kafka.publish.call_args
            assert call_args.kwargs["topic"] == "skill.sys.batch-callback.v1"
            assert call_args.kwargs["key"] == "batch-abc"
            from nohiki.ml.v1 import BatchEmbeddingCallback

            assert isinstance(call_args.kwargs["message"], BatchEmbeddingCallback)

    @pytest.mark.asyncio
    async def test_result_count_matches_item_count(self) -> None:
        """Test one result item per input item in the callback success payload."""
        from ml_compute_service.events.handlers import _handle_batch_embedding
        from nohiki.ml.v1 import BatchEmbeddingCallback

        item_count = 3
        message = self._make_batch_message(item_count)
        context = MagicMock()
        mock_pipeline = MagicMock()
        mock_pipeline.manifest.dense.model_id = "m"

        published: list[object] = []

        async def capture(**kwargs: object) -> None:
            published.append(kwargs.get("message"))

        with (
            patch(
                "ml_compute_service.events.handlers.get_encoding_pipeline",
                return_value=mock_pipeline,
            ),
            patch("ml_compute_service.events.handlers.asyncio") as mock_asyncio,
            patch("ml_compute_service.events.handlers.kafka_client") as mock_kafka,
        ):
            mock_asyncio.to_thread = AsyncMock(return_value=self._make_batch_encoding_result(item_count))
            mock_kafka.publish = capture

            await _handle_batch_embedding(message, context)

        assert len(published) == 1
        evt = published[0]
        assert isinstance(evt, BatchEmbeddingCallback)
        assert evt.success is not None
        assert len(evt.success.results) == item_count

    @pytest.mark.asyncio
    @pytest.mark.parametrize("item_count", [30, 100])
    async def test_accepts_full_request_and_micro_batches_inference(self, item_count: int) -> None:
        """Admission accepts protobuf-valid batches while inference stays bounded."""
        from ml_compute_service.events.handlers import _handle_batch_embedding

        message = self._make_batch_message(item_count)
        mock_pipeline = MagicMock()
        mock_pipeline.manifest.dense.model_id = "m"
        batch_result = self._make_batch_encoding_result(item_count)

        with (
            patch(
                "ml_compute_service.events.handlers.get_encoding_pipeline",
                return_value=mock_pipeline,
            ),
            patch(
                "ml_compute_service.events.handlers._run_inference",
                new_callable=AsyncMock,
                return_value=batch_result,
            ) as mock_inference,
            patch("ml_compute_service.events.handlers.kafka_client") as mock_kafka,
        ):
            mock_kafka.publish = AsyncMock()
            await _handle_batch_embedding(message, MagicMock())

        mock_inference.assert_awaited_once_with(
            mock_pipeline.encode_dense_batch,
            [f"Skill text {i}" for i in range(item_count)],
            [f"entity-{i}" for i in range(item_count)],
            batch_size=8,
        )
        publish_call = mock_kafka.publish.await_args
        assert publish_call is not None
        callback = publish_call.kwargs["message"]
        assert [result.point_id for result in callback.success.results] == [f"point-{i}" for i in range(item_count)]
        assert [result.content_hash for result in callback.success.results] == [
            f"h{i}" for i in range(1, item_count + 1)
        ]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("text", "accepted"),
        [("a" * 999_999, True), ("a" * 1_000_000, True), ("a" * 1_000_001, False)],
        ids=["below-limit", "at-limit", "above-limit"],
    )
    async def test_enforces_aggregate_text_limit_before_inference(
        self,
        text: str,
        *,
        accepted: bool,
    ) -> None:
        """Aggregate text admission is inclusive and rejection is terminal."""
        from ml_compute_service.events.handlers import _handle_batch_embedding

        message = self._make_batch_message(1)
        message.batch_embedding_request.items[0].text = text
        mock_pipeline = MagicMock()
        mock_pipeline.manifest.dense.model_id = "m"
        with (
            patch(
                "ml_compute_service.events.handlers.get_encoding_pipeline",
                return_value=mock_pipeline,
            ) as mock_get_pipeline,
            patch(
                "ml_compute_service.events.handlers._run_inference",
                new_callable=AsyncMock,
                return_value=self._make_batch_encoding_result(1),
            ) as mock_inference,
            patch("ml_compute_service.events.handlers.kafka_client") as mock_kafka,
        ):
            mock_kafka.publish = AsyncMock()
            await _handle_batch_embedding(message, MagicMock())

        publish_call = mock_kafka.publish.await_args
        assert publish_call is not None
        callback = publish_call.kwargs["message"]
        if accepted:
            mock_get_pipeline.assert_called_once_with()
            mock_inference.assert_awaited_once()
            assert callback.success is not None
            assert callback.error is None
        else:
            mock_get_pipeline.assert_not_called()
            mock_inference.assert_not_awaited()
            assert callback.success is None
            assert callback.error is not None
            assert callback.error.error_message == (
                "Batch text size 1000001 characters exceeds compute limit 1000000 bytes"
            )
            assert callback.error.retryable is False

    @pytest.mark.asyncio
    async def test_rejects_101_items_before_inference(self) -> None:
        """Requests beyond the protobuf maximum never reach the model."""
        from ml_compute_service.events.handlers import _handle_batch_embedding

        message = self._make_batch_message(101)
        with (
            patch(
                "ml_compute_service.events.handlers._run_inference",
                new_callable=AsyncMock,
            ) as mock_inference,
            patch(
                "ml_compute_service.events.handlers._publish_batch_error",
                new_callable=AsyncMock,
            ) as mock_error,
        ):
            await _handle_batch_embedding(message, MagicMock())

        mock_inference.assert_not_awaited()
        mock_error.assert_awaited_once_with(
            message,
            "Batch size 101 exceeds compute limit 100",
        )

    @pytest.mark.asyncio
    async def test_rejects_empty_items_before_inference(self) -> None:
        """An empty batch cannot reach the model or return a bare success."""
        from ml_compute_service.events.handlers import _handle_batch_embedding

        message = self._make_batch_message(0)
        with (
            patch(
                "ml_compute_service.events.handlers._run_inference",
                new_callable=AsyncMock,
            ) as mock_inference,
            patch(
                "ml_compute_service.events.handlers._publish_batch_error",
                new_callable=AsyncMock,
            ) as mock_error,
        ):
            await _handle_batch_embedding(message, MagicMock())

        mock_inference.assert_not_awaited()
        mock_error.assert_awaited_once_with(
            message,
            "Batch embedding request must contain at least one item",
        )

    @pytest.mark.asyncio
    async def test_rejects_multibyte_text_exceeding_byte_limit_within_char_limit(self) -> None:
        """Multi-byte text can pass the character gate yet still exceed the byte budget."""
        from ml_compute_service.events.handlers import _handle_batch_embedding

        # Each euro sign is 1 Python character but 3 UTF-8 bytes: 400,000 chars stays
        # under the 1,000,000-character limit while encoding to 1,200,000 bytes.
        message = self._make_batch_message(1)
        message.batch_embedding_request.items[0].text = "\u20ac" * 400_000

        with (
            patch(
                "ml_compute_service.events.handlers.get_encoding_pipeline",
            ) as mock_get_pipeline,
            patch(
                "ml_compute_service.events.handlers._run_inference",
                new_callable=AsyncMock,
            ) as mock_inference,
            patch("ml_compute_service.events.handlers.kafka_client") as mock_kafka,
        ):
            mock_kafka.publish = AsyncMock()
            await _handle_batch_embedding(message, MagicMock())

        mock_get_pipeline.assert_not_called()
        mock_inference.assert_not_awaited()
        publish_call = mock_kafka.publish.await_args
        assert publish_call is not None
        callback = publish_call.kwargs["message"]
        assert callback.success is None
        assert callback.error is not None
        assert callback.error.error_message == (
            "Batch text size 1200000 UTF-8 bytes exceeds compute limit 1000000 bytes"
        )
        assert callback.error.retryable is False

    @pytest.mark.asyncio
    async def test_publishes_failed_on_pipeline_exception(self) -> None:
        """Test _publish_batch_error called when encode_dense_batch raises."""
        from ml_compute_service.events.handlers import _handle_batch_embedding

        message = self._make_batch_message()
        context = MagicMock()

        with (
            patch(
                "ml_compute_service.events.handlers.get_encoding_pipeline",
                return_value=MagicMock(),
            ),
            patch("ml_compute_service.events.handlers.asyncio") as mock_asyncio,
            patch(
                "ml_compute_service.events.handlers._publish_batch_error",
                new_callable=AsyncMock,
            ) as mock_error,
            patch("ml_compute_service.events.handlers.logger"),
        ):
            mock_asyncio.to_thread = AsyncMock(side_effect=RuntimeError("OOM"))

            await _handle_batch_embedding(message, context)

            mock_error.assert_called_once_with(message, "OOM")

    @pytest.mark.asyncio
    async def test_operation_id_echoed_in_callback(self) -> None:
        """Test operation_id from command is echoed in the callback header."""
        from ml_compute_service.events.handlers import _handle_batch_embedding
        from nohiki.ml.v1 import BatchEmbeddingCallback

        message = self._make_batch_message()
        message.batch_embedding_request.command.operation_id = "specific-op-id"
        context = MagicMock()
        mock_pipeline = MagicMock()
        mock_pipeline.manifest.dense.model_id = "m"

        published: list[object] = []

        async def capture(**kwargs: object) -> None:
            published.append(kwargs.get("message"))

        with (
            patch(
                "ml_compute_service.events.handlers.get_encoding_pipeline",
                return_value=mock_pipeline,
            ),
            patch("ml_compute_service.events.handlers.asyncio") as mock_asyncio,
            patch("ml_compute_service.events.handlers.kafka_client") as mock_kafka,
        ):
            mock_asyncio.to_thread = AsyncMock(return_value=self._make_batch_encoding_result())
            mock_kafka.publish = capture

            await _handle_batch_embedding(message, context)

        evt = published[0]
        assert isinstance(evt, BatchEmbeddingCallback)
        assert evt.success is not None
