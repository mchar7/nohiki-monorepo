"""Kafka event handlers for ML compute operations.

This worker consumes from ml.internal.k8s-compute.v1 and executes actual ML
inference using nohiki-ml-core. This is where the DRY ML code runs.

Architecture:
    1. ml-gateway-service routes requests to this topic
    2. This worker consumes InternalComputeRequest messages
    3. Uses nohiki-ml-core pipeline for encoding
    4. Publishes completion events to callback topics
"""

from __future__ import annotations

import asyncio
import json
from asyncio import CancelledError as _CancelledError
from asyncio import create_task as _create_task
from asyncio import get_running_loop as _get_running_loop
from asyncio import timeout as _timeout
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, TypedDict

import numpy as np
from nohiki.common.v1 import ErrorInfo, EventMetadata
from nohiki.ml.v1 import (
    BatchEmbeddingCallback,
    BatchEmbeddingResult,
    BatchEmbeddingResultItem,
    DenseData,
    EmbeddingCallback,
    EmbeddingCompleted,
    EmbeddingResult,
    EmbeddingType,
    EmbeddingVector,
    EncodingMode,
    InternalComputeRequest,
    MlOperationType,
    MultiVectorData,
    SparseData,
)
from nohiki_kafka_client import MessageContext, Topics, callback_from_command
from nohiki_kafka_client import create_event_metadata as _lib_create_event_metadata
from nohiki_ml_core.pipeline import DenseBatchEncodingResult, DenseEncodingResult, EncodingResult
from nohiki_ml_manifest import EmbeddingValidator
from nohiki_observability import get_logger
from uuid_utils.compat import uuid7

from ml_compute_service.core.config import get_settings
from ml_compute_service.core.kafka import kafka_client
from ml_compute_service.core.pipeline import get_encoding_pipeline

if TYPE_CHECKING:
    from nohiki.common.v1 import CommandHeader
    from nohiki.ml.v1 import EmbeddingRequested
    from nohiki_ml_core.pipeline import MLEncodingPipeline

logger = get_logger(__name__)
settings = get_settings()
_INFERENCE_SEMAPHORE = asyncio.Semaphore(settings.kafka.consumer.max_concurrent_handlers)
_INFERENCE_TASKS: set[asyncio.Task[object]] = set()


_MIN_MATRIX_DIMENSIONS = 2


class _QdrantSinkSparseVector(TypedDict):
    indices: list[int]
    values: list[float]


class _QdrantSinkVector(TypedDict):
    muvera: list[float]
    colbert: list[list[float]]
    sparse: _QdrantSinkSparseVector


class _QdrantSinkPayload(TypedDict):
    id: str
    collection_name: str
    vector: _QdrantSinkVector
    payload: dict[str, str]


def _to_float_list(arr: np.ndarray | Sequence[float]) -> list[float]:
    """Convert a one-dimensional numeric array or sequence to Python floats."""
    return [float(value) for value in arr]


def _to_int_list(arr: np.ndarray | Sequence[int]) -> list[int]:
    """Convert a one-dimensional integer array or sequence to Python ints."""
    return [int(value) for value in arr]


def _to_nested_float_list(arr: np.ndarray | Sequence[Sequence[float]]) -> list[list[float]]:
    """Convert a numeric array or nested sequence into two-dimensional Python floats."""
    array = np.asarray(arr, dtype=np.float64)
    if array.ndim < _MIN_MATRIX_DIMENSIONS:
        msg = f"nested float values must have at least two dimensions, got shape {array.shape}"
        raise ValueError(msg)
    rows = array.reshape(-1, array.shape[-1])
    return [[float(value) for value in row] for row in rows]


def _as_float_array(values: np.ndarray | Sequence[float], *, name: str, dimensions: int) -> np.ndarray:
    """Validate an inference output before it crosses the service boundary."""
    array = np.asarray(values)
    if array.ndim != dimensions:
        msg = f"{name} must be {dimensions}D, got shape {array.shape}"
        raise ValueError(msg)
    if not np.issubdtype(array.dtype, np.floating):
        msg = f"{name} must have a floating dtype, got {array.dtype}"
        raise ValueError(msg)
    if not np.isfinite(array).all():
        msg = f"{name} contains non-finite values"
        raise ValueError(msg)
    return array


def _validate_retrieval_result(
    pipeline: MLEncodingPipeline,
    result: EncodingResult,
    entity_type: str,
    collection_version: str,
) -> None:
    """Validate retrieval output and collection version against the manifest."""
    expected_dimensions = (
        pipeline.manifest.muvera_output_dimension,
        pipeline.manifest.late_interaction.token_dim,
    )
    if not all(isinstance(dimension, int) for dimension in expected_dimensions):
        return
    validator = EmbeddingValidator(pipeline.manifest)
    validator.validate_collection_version(entity_type, collection_version)
    muvera = _as_float_array(result.muvera_fde, name="MUVERA embedding", dimensions=1)
    colbert = _as_float_array(result.colbert_tokens, name="ColBERT embeddings", dimensions=2)
    sparse_values = _as_float_array(result.sparse_vector.values, name="sparse values", dimensions=1)
    sparse_indices = np.asarray(result.sparse_vector.indices)
    if sparse_indices.ndim != 1 or not np.issubdtype(sparse_indices.dtype, np.integer):
        msg = (
            "sparse indices must be a 1D integer array, "
            f"got shape {sparse_indices.shape} and dtype {sparse_indices.dtype}"
        )
        raise ValueError(msg)
    if sparse_indices.size != sparse_values.size:
        msg = "sparse indices and values must have the same length"
        raise ValueError(msg)
    if np.any(sparse_indices < 0):
        msg = "sparse indices must be non-negative"
        raise ValueError(msg)
    validator.validate_muvera_dimension(muvera.shape[0])
    validator.validate_colbert_token_dimension(colbert.shape[1])


def _validate_dense_result(
    pipeline: MLEncodingPipeline,
    result: DenseEncodingResult,
    entity_type: str,
    collection_version: str,
) -> None:
    """Validate dense output and collection version against the manifest."""
    if not isinstance(pipeline.manifest.dense.embedding_dim, int):
        return
    dense = _as_float_array(result.dense_embedding, name="dense embedding", dimensions=1)
    validator = EmbeddingValidator(pipeline.manifest)
    validator.validate_collection_version(entity_type, collection_version)
    validator.validate_dense_dimension(dense.shape[0])


def _validate_dense_batch_result(
    pipeline: MLEncodingPipeline,
    result: DenseBatchEncodingResult,
    expected_count: int,
    entity_type: str,
    collection_version: str,
) -> None:
    """Validate batched output and collection version against the manifest."""
    if not isinstance(pipeline.manifest.dense.embedding_dim, int):
        return
    dense = _as_float_array(result.dense_embeddings, name="dense batch embeddings", dimensions=2)
    if dense.shape[0] != expected_count or len(result.content_hashes) != expected_count:
        msg = (
            "dense batch result cardinality mismatch: "
            f"expected {expected_count}, got {dense.shape[0]} embeddings and {len(result.content_hashes)} hashes"
        )
        raise ValueError(msg)
    validator = EmbeddingValidator(pipeline.manifest)
    validator.validate_collection_version(entity_type, collection_version)
    validator.validate_dense_dimension(dense.shape[1])


async def _run_inference_worker[ResultT](
    function: Callable[..., ResultT],
    /,
    *args: object,
    **kwargs: object,
) -> ResultT:
    """Run one blocking inference and release its permit after thread exit."""
    try:
        return await asyncio.to_thread(function, *args, **kwargs)
    finally:
        _INFERENCE_SEMAPHORE.release()


def _discard_inference_task[ResultT](task: asyncio.Task[ResultT]) -> None:
    """Keep orphaned inference tasks alive until their thread has exited."""
    _INFERENCE_TASKS.discard(task)
    if not task.cancelled():
        task.exception()


async def _await_inference_worker[ResultT](worker: asyncio.Task[ResultT]) -> ResultT:
    """Await a worker without propagating cancellation into its thread."""
    completion: asyncio.Future[ResultT] = _get_running_loop().create_future()

    def _resolve(done: asyncio.Task[ResultT]) -> None:
        if done.cancelled():
            if not completion.done():
                completion.cancel()
            return
        exception = done.exception()
        if completion.done():
            return
        if exception is not None:
            completion.set_exception(exception)
        else:
            completion.set_result(done.result())

    worker.add_done_callback(_resolve)
    try:
        return await completion
    except _CancelledError:
        completion.cancel()
        raise


async def _run_inference[ResultT](
    function: Callable[..., ResultT],
    /,
    *args: object,
    **kwargs: object,
) -> ResultT:
    """Run blocking inference off-loop with the configured request deadline."""
    await _INFERENCE_SEMAPHORE.acquire()
    try:
        worker = _create_task(_run_inference_worker(function, *args, **kwargs))
    except Exception:
        _INFERENCE_SEMAPHORE.release()
        raise
    _INFERENCE_TASKS.add(worker)
    worker.add_done_callback(_discard_inference_task)
    async with _timeout(settings.processing.timeout_seconds):
        return await _await_inference_worker(worker)


def start_event_consumer() -> None:
    """Start the Kafka event consumer."""
    logger.info("Starting event consumer", service=settings.service_name)
    kafka_client.start_consumers()


def _get_command(message: InternalComputeRequest) -> CommandHeader:
    """Extract CommandHeader from the nested payload request message."""
    match message.operation_type:
        case MlOperationType.EMBEDDING:
            if message.embedding_request is None:
                msg = "embedding_request is None on InternalComputeRequest"
                raise ValueError(msg)
            return message.embedding_request.command
        case MlOperationType.BATCH_EMBEDDING:
            if message.batch_embedding_request is None:
                msg = "batch_embedding_request is None on InternalComputeRequest"
                raise ValueError(msg)
            return message.batch_embedding_request.command
        case MlOperationType.RERANK:
            if message.rerank_request is None:
                msg = "rerank_request is None on InternalComputeRequest"
                raise ValueError(msg)
            return message.rerank_request.command
        case _:
            msg = f"Unknown operation type: {message.operation_type}"
            raise ValueError(msg)


@kafka_client.message_handler(
    Topics.ML_INTERNAL_K8S_COMPUTE,
    InternalComputeRequest,
    group_id=settings.kafka.consumer_group,
    preserve_partition_order=False,
)
async def handle_internal_compute(
    message: InternalComputeRequest,
    context: MessageContext,
) -> None:
    """Execute ML compute using nohiki-ml-core based on operation_type."""
    match message.operation_type:
        case MlOperationType.EMBEDDING:
            await _handle_embedding(message, context)
        case MlOperationType.BATCH_EMBEDDING:
            await _handle_batch_embedding(message, context)
        case MlOperationType.RERANK:
            command = _get_command(message)
            logger.warning(
                "Rerank request received on K8s worker -- requires GPU; route to Modal provider",
                operation_id=command.operation_id,
            )
        case _:
            logger.warning(
                "Unknown operation type received",
                operation_type=message.operation_type,
            )


async def _handle_embedding(
    message: InternalComputeRequest,
    _context: MessageContext,
) -> None:
    """Execute embedding using nohiki-ml-core pipeline."""
    req = message.embedding_request
    if req is None:
        msg = "InternalComputeRequest.embedding_request is required but was None"
        raise ValueError(msg)

    pipeline = get_encoding_pipeline()
    requested_types_set = frozenset(req.requested_types)
    needs_retrieval = requested_types_set - {EmbeddingType.DENSE}

    try:
        embeddings: list[EmbeddingVector] = []
        retrieval_result: EncodingResult | None = None

        if needs_retrieval:
            retrieval_result = await _encode_retrieval(pipeline, req)
            _validate_retrieval_result(
                pipeline,
                retrieval_result,
                req.entity_type.name.lower(),
                req.collection_version,
            )
            embeddings.extend(
                _extract_retrieval_vectors(pipeline, retrieval_result, requested_types_set, req),
            )

        if EmbeddingType.DENSE in requested_types_set:
            dense_result = await _run_inference(pipeline.encode_dense, req.text, req.entity_id)
            _validate_dense_result(
                pipeline,
                dense_result,
                req.entity_type.name.lower(),
                req.collection_version,
            )
            embeddings.append(
                _build_dense_vector(pipeline, dense_result, req.collection_version),
            )

        embedding_result = _build_embedding_result(pipeline, message, req, embeddings)
        callback_event = EmbeddingCallback(
            metadata=_create_event_metadata(
                message.metadata.correlation_id if message.metadata else None,
            ),
            callback=callback_from_command(req.command),
            entity_id=req.entity_id,
            entity_type=req.entity_type,
            success=embedding_result,
        )
        await kafka_client.publish(
            topic=req.command.callback_topic,
            message=callback_event,
            key=req.entity_id,
        )

        if req.publish_to_index and retrieval_result is not None:
            fact_event = EmbeddingCompleted(
                metadata=_create_event_metadata(
                    message.metadata.correlation_id if message.metadata else None,
                ),
                entity_id=req.entity_id,
                entity_type=req.entity_type,
                payload=embedding_result,
            )
            await kafka_client.publish(
                topic=Topics.ML_EMBEDDING_COMPLETED,
                message=fact_event,
                key=req.entity_id,
            )
            json_payload = _build_qdrant_sink_payload(req, retrieval_result, pipeline)
            await kafka_client.publish_raw(
                topic=Topics.ML_EMBEDDING_COMPLETED_JSON,
                value=json.dumps(json_payload).encode("utf-8"),
                key=req.entity_id,
                headers={"content-type": "application/json"},
            )

        logger.info(
            "Embedding completed",
            operation_id=req.command.operation_id,
            entity_id=req.entity_id,
            requested_types=[t.name for t in req.requested_types],
            encoding_mode=req.encoding_mode.name,
            num_embeddings=len(embeddings),
        )

    except Exception as e:
        logger.exception(
            "Embedding failed",
            operation_id=req.command.operation_id,
            entity_id=req.entity_id,
            requested_types=[t.name for t in req.requested_types],
            error=str(e),
        )
        await _publish_embedding_error(message, str(e))


async def _encode_retrieval(
    pipeline: MLEncodingPipeline,
    req: EmbeddingRequested,
) -> EncodingResult:
    """Dispatch to the pipeline encode method for the given encoding_mode."""
    match req.encoding_mode:
        case EncodingMode.DOCUMENT:
            result = await _run_inference(pipeline.encode_document, req.text, req.entity_id)
        case EncodingMode.QUERY:
            result = await _run_inference(pipeline.encode_query, req.text)
        case _:
            msg = f"encoding_mode must be DOCUMENT or QUERY, got {req.encoding_mode!r}"
            raise ValueError(msg)
    return result


def _extract_retrieval_vectors(
    pipeline: MLEncodingPipeline,
    result: EncodingResult,
    requested_types: frozenset[EmbeddingType],
    req: EmbeddingRequested,
) -> list[EmbeddingVector]:
    """Extract EmbeddingVector instances from EncodingResult for requested types."""
    vectors: list[EmbeddingVector] = []

    if EmbeddingType.MUVERA in requested_types:
        vectors.append(
            EmbeddingVector(
                embedding_type=EmbeddingType.MUVERA,
                dense=DenseData(values=_to_float_list(result.muvera_fde)),
                content_hash=result.content_hash,
                model_id=pipeline.manifest.late_interaction.model_id,
                collection_version=req.collection_version,
            )
        )

    if EmbeddingType.SPARSE in requested_types:
        vectors.append(
            EmbeddingVector(
                embedding_type=EmbeddingType.SPARSE,
                sparse=SparseData(
                    indices=_to_int_list(result.sparse_vector.indices),
                    values=_to_float_list(result.sparse_vector.values),
                ),
                content_hash=result.content_hash,
                model_id=pipeline.manifest.sparse.model_id,
                collection_version=req.collection_version,
            )
        )

    if EmbeddingType.COLBERT in requested_types:
        colbert_flat = result.colbert_tokens.flatten().tolist()
        vectors.append(
            EmbeddingVector(
                embedding_type=EmbeddingType.COLBERT,
                multi_vector=MultiVectorData(
                    values=colbert_flat,
                    num_tokens=result.colbert_tokens.shape[0],
                    token_dim=result.colbert_tokens.shape[1],
                ),
                content_hash=result.content_hash,
                model_id=pipeline.manifest.late_interaction.model_id,
                collection_version=req.collection_version,
            )
        )

    return vectors


def _build_dense_vector(
    pipeline: MLEncodingPipeline,
    result: DenseEncodingResult,
    collection_version: str,
) -> EmbeddingVector:
    """Build DENSE EmbeddingVector from DenseEncodingResult."""
    return EmbeddingVector(
        embedding_type=EmbeddingType.DENSE,
        dense=DenseData(values=_to_float_list(result.dense_embedding)),
        content_hash=result.content_hash,
        model_id=pipeline.manifest.dense.model_id,
        collection_version=collection_version,
    )


def _build_embedding_result(
    pipeline: MLEncodingPipeline,
    message: InternalComputeRequest,
    req: EmbeddingRequested,
    embeddings: list[EmbeddingVector],
) -> EmbeddingResult:
    """Construct EmbeddingResult success payload from computed embeddings."""
    content_hash = embeddings[0].content_hash
    return EmbeddingResult(
        collection_version=req.collection_version,
        content_hash=content_hash,
        requested_types=list(req.requested_types),
        encoding_mode=req.encoding_mode,
        embeddings=embeddings,
        payload_metadata=_build_payload_metadata(pipeline, message, dict(req.command.attributes)),
    )


def _build_payload_metadata(
    pipeline: MLEncodingPipeline,
    message: InternalComputeRequest,
    attributes: dict[str, str],
) -> dict[str, str]:
    """Build payload_metadata by merging technical metadata with command attributes."""
    payload: dict[str, str] = {
        "model_id": pipeline.manifest.late_interaction.model_id,
        "provider": message.selected_provider,
    }
    payload |= attributes
    return payload


def _build_qdrant_sink_payload(
    req: EmbeddingRequested,
    result: EncodingResult,
    pipeline: MLEncodingPipeline,
) -> _QdrantSinkPayload:
    """Build JSON payload for Qdrant Kafka sink connector."""
    muvera_values = _to_float_list(result.muvera_fde)
    colbert_tokens = _to_nested_float_list(result.colbert_tokens)
    sparse_indices = _to_int_list(result.sparse_vector.indices)
    sparse_values = _to_float_list(result.sparse_vector.values)

    entity_type = req.entity_type.name.lower()
    collection_name = pipeline.manifest.get_collection_name(entity_type)

    return {
        "id": req.entity_id,
        "collection_name": collection_name,
        "vector": {
            "muvera": muvera_values,
            "colbert": colbert_tokens,
            "sparse": {"indices": sparse_indices, "values": sparse_values},
        },
        "payload": {
            "entity_id": req.entity_id,
            "entity_type": entity_type,
            "collection_version": req.collection_version,
            "content_hash": result.content_hash,
            "model_id": pipeline.manifest.late_interaction.model_id,
            **req.command.attributes,
        },
    }


async def _publish_embedding_error(message: InternalComputeRequest, error: str) -> None:
    """Publish EmbeddingCallback with ErrorInfo to the requester's callback topic."""
    req = message.embedding_request
    if req is None:
        msg = "Cannot publish embedding error - embedding_request is None on InternalComputeRequest"
        raise ValueError(msg)

    failed = EmbeddingCallback(
        metadata=_create_event_metadata(message.metadata.correlation_id if message.metadata else None),
        callback=callback_from_command(req.command),
        entity_id=req.entity_id,
        entity_type=req.entity_type,
        error=ErrorInfo(error_code="PIPELINE_ERROR", error_message=error, retryable=False),
    )
    await kafka_client.publish(
        topic=req.command.callback_topic,
        message=failed,
        key=req.entity_id,
    )


async def _handle_batch_embedding(
    message: InternalComputeRequest,
    _context: MessageContext,
) -> None:
    """Execute batch dense embedding using nohiki-ml-core pipeline.

    All items are encoded in one logical operation via encode_dense_batch, which
    micro-batches native model forward passes to bound inference memory.
    """
    req = message.batch_embedding_request
    if req is None:
        msg = "InternalComputeRequest.batch_embedding_request is required but was None"
        raise ValueError(msg)

    if not req.items:
        await _publish_batch_error(message, "Batch embedding request must contain at least one item")
        return
    if len(req.items) > settings.processing.max_request_items:
        await _publish_batch_error(
            message,
            f"Batch size {len(req.items)} exceeds compute limit {settings.processing.max_request_items}",
        )
        return
    total_text_chars = sum(len(item.text) for item in req.items)
    if total_text_chars > settings.processing.max_batch_text_bytes:
        await _publish_batch_error(
            message,
            f"Batch text size {total_text_chars} characters exceeds compute limit "
            f"{settings.processing.max_batch_text_bytes} bytes",
        )
        return
    total_text_bytes = sum(len(item.text.encode("utf-8")) for item in req.items)
    if total_text_bytes > settings.processing.max_batch_text_bytes:
        await _publish_batch_error(
            message,
            f"Batch text size {total_text_bytes} UTF-8 bytes exceeds compute limit "
            f"{settings.processing.max_batch_text_bytes} bytes",
        )
        return

    pipeline = get_encoding_pipeline()
    texts = [item.text for item in req.items]
    entity_ids = [item.entity_id for item in req.items]

    try:
        batch_result = await _run_inference(
            pipeline.encode_dense_batch,
            texts,
            entity_ids,
            batch_size=settings.processing.inference_batch_size,
        )
        _validate_dense_batch_result(
            pipeline,
            batch_result,
            len(req.items),
            req.entity_type.name.lower(),
            req.collection_version,
        )
        results: list[BatchEmbeddingResultItem] = [
            BatchEmbeddingResultItem(
                point_id=item.point_id,
                entity_id=item.entity_id,
                embeddings=[
                    EmbeddingVector(
                        embedding_type=EmbeddingType.DENSE,
                        dense=DenseData(values=_to_float_list(embedding_row)),
                        content_hash=content_hash,
                        model_id=pipeline.manifest.dense.model_id,
                        collection_version=req.collection_version,
                    )
                ],
                content_hash=content_hash,
                item_attributes=dict(item.item_attributes) if item.item_attributes else {},
            )
            for item, embedding_row, content_hash in zip(
                req.items,
                batch_result.dense_embeddings,
                batch_result.content_hashes,
                strict=True,
            )
        ]
        callback_event = BatchEmbeddingCallback(
            metadata=_create_event_metadata(
                message.metadata.correlation_id if message.metadata else None,
            ),
            callback=callback_from_command(req.command),
            entity_type=req.entity_type,
            collection_version=req.collection_version,
            encoding_mode=req.encoding_mode,
            success=BatchEmbeddingResult(results=results),
        )
        await kafka_client.publish(
            topic=req.command.callback_topic,
            message=callback_event,
            key=req.command.operation_id,
        )
        logger.info(
            "Batch embedding completed",
            operation_id=req.command.operation_id,
            item_count=len(req.items),
            result_count=len(results),
        )
    except Exception as e:
        logger.exception(
            "Batch embedding failed",
            operation_id=req.command.operation_id,
            item_count=len(req.items),
            error=str(e),
        )
        await _publish_batch_error(message, str(e))


async def _publish_batch_error(message: InternalComputeRequest, error: str) -> None:
    """Publish BatchEmbeddingCallback with ErrorInfo to the requester's callback topic."""
    req = message.batch_embedding_request
    if req is None:
        msg = "Cannot publish batch error - batch_embedding_request is None on InternalComputeRequest"
        raise ValueError(msg)

    failed = BatchEmbeddingCallback(
        metadata=_create_event_metadata(
            message.metadata.correlation_id if message.metadata else None,
        ),
        callback=callback_from_command(req.command),
        entity_type=req.entity_type,
        collection_version=req.collection_version,
        encoding_mode=req.encoding_mode,
        error=ErrorInfo(error_code="PIPELINE_ERROR", error_message=error, retryable=False),
    )
    await kafka_client.publish(
        topic=req.command.callback_topic,
        message=failed,
        key=req.command.operation_id,
    )


def _create_event_metadata(correlation_id: str | None = None) -> EventMetadata:
    """Create EventMetadata for outgoing events.

    If no correlation_id is provided, generates one to ensure all ML compute
    events are traceable.
    """
    return _lib_create_event_metadata(
        settings.service_name,
        correlation_id or str(uuid7()),
    )
