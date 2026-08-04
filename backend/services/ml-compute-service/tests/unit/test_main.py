"""Unit tests for main.py FastAPI application."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from nohiki_ml_core.model_cache import ModelArchive


def _write_test_file(path: Path, content: bytes) -> None:
    path.write_bytes(content)


def _contains_test_files(directory: Path) -> bool:
    return any(path.is_file() for path in directory.rglob("*"))


def _read_test_file(path: Path) -> bytes:
    return path.read_bytes()


def _exception_group_contains(group: BaseExceptionGroup, expected: BaseException) -> bool:
    return any(
        error is expected or (isinstance(error, BaseExceptionGroup) and _exception_group_contains(error, expected))
        for error in group.exceptions
    )


class TestValidateComputeBackendOnStartup:
    """Tests for _validate_compute_backend_on_startup function.

    Note: The function is called at module load time, so we test the actual
    function behavior rather than trying to mock module-level execution.
    """

    def test_function_returns_compute_backend(self) -> None:
        """Verifies the function returns a ComputeBackend value."""
        from ml_compute_service.main import (
            _active_compute_backend,
            _validate_compute_backend_on_startup,
        )
        from nohiki_ml_core import ComputeBackend

        result = _validate_compute_backend_on_startup()

        assert isinstance(result, ComputeBackend)
        assert result == _active_compute_backend

    def test_active_backend_is_set(self) -> None:
        """Verifies _active_compute_backend is set at module load."""
        from ml_compute_service.main import _active_compute_backend
        from nohiki_ml_core import ComputeBackend

        assert isinstance(_active_compute_backend, ComputeBackend)


class TestAppCreation:
    """Tests for FastAPI app creation."""

    def test_app_is_created_with_correct_settings(self) -> None:
        """Verifies app is created with settings from config."""
        from ml_compute_service.main import app, settings

        assert app.title == settings.service_name_friendly
        assert app.version == settings.service_version


class TestModelCacheConfiguration:
    """Tests for startup model-loader cache configuration."""

    def test_configures_all_model_loader_cache_roots(self, tmp_path: Path) -> None:
        """Configured processing cache roots are shared by every model loader."""
        from ml_compute_service.main import _configure_model_caches

        cache_dir = tmp_path / "models"
        with patch.dict(os.environ, {}, clear=False):
            _configure_model_caches(cache_dir)

            assert os.environ["HF_HOME"] == str(cache_dir / "huggingface")
            assert os.environ["HF_HUB_CACHE"] == str(cache_dir / "huggingface" / "hub")
            assert os.environ["TRANSFORMERS_CACHE"] == str(cache_dir / "huggingface" / "hub")
            assert os.environ["SENTENCE_TRANSFORMERS_HOME"] == str(cache_dir / "huggingface" / "hub")
            assert os.environ["FASTEMBED_CACHE_PATH"] == str(cache_dir / "fastembed")


class TestMainModuleWrappers:
    """Tests for main.py's lazy-import wrappers around pipeline and consumer startup."""

    def test_get_encoding_pipeline_delegates_to_pipeline_builder(self) -> None:
        """The wrapper defers pipeline construction until model caches are configured."""
        from ml_compute_service.main import get_encoding_pipeline

        sentinel_pipeline = MagicMock()
        with patch(
            "ml_compute_service.core.pipeline.get_encoding_pipeline",
            return_value=sentinel_pipeline,
        ) as mock_build:
            result = get_encoding_pipeline()

        mock_build.assert_called_once_with()
        assert result is sentinel_pipeline

    def test_start_event_consumer_delegates_to_events_module(self) -> None:
        """The wrapper defers consumer registration until model caches are configured."""
        from ml_compute_service.main import start_event_consumer

        with patch("ml_compute_service.events.start_event_consumer") as mock_start:
            start_event_consumer()

        mock_start.assert_called_once_with()


class TestLifespan:
    """Tests for lifespan context manager."""

    @pytest.mark.asyncio
    async def test_normal_lifespan_warms_before_supervision_and_cleans_up(self) -> None:
        """Warmup completes before consumer supervision and normal shutdown is ordered."""
        from ml_compute_service.core.readiness import ReadinessGate, ReadinessState

        events: list[str] = []
        supervisor_entered = asyncio.Event()
        gate = ReadinessGate()

        async def wait_for_consumers() -> None:
            assert events[-1] == "consumer_started"
            assert gate.state is ReadinessState.READY
            events.append("supervision_entered")
            supervisor_entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                events.append("supervision_cancelled")

        mock_pipeline = MagicMock()
        mock_pipeline.colbert.warm_up.side_effect = lambda: events.append("colbert_warmed")
        mock_pipeline.sparse.warm_up.side_effect = lambda: events.append("sparse_warmed")

        with (
            patch("ml_compute_service.main.ensure_kafka_ready", new_callable=AsyncMock),
            patch(
                "ml_compute_service.main._ensure_models_cached",
                new_callable=AsyncMock,
                side_effect=lambda: events.append("models_cached"),
            ),
            patch(
                "ml_compute_service.main.get_encoding_pipeline",
                return_value=mock_pipeline,
            ),
            patch("ml_compute_service.main.kafka_client") as mock_kafka,
            patch("ml_compute_service.main.CacheFactory") as mock_cache_factory,
            patch("ml_compute_service.main.obs") as mock_obs,
            patch("ml_compute_service.main.start_event_consumer") as mock_start,
            patch("ml_compute_service.main.readiness_gate", new=gate),
        ):
            mock_start.side_effect = lambda: events.append("consumer_started")
            mock_kafka.wait_for_consumers = AsyncMock(side_effect=wait_for_consumers)
            mock_kafka.stop_consumers = AsyncMock(side_effect=lambda: events.append("consumers_stopped"))
            mock_kafka.close = AsyncMock(side_effect=lambda: events.append("kafka_closed"))
            mock_cache_factory.close_all = AsyncMock(side_effect=lambda: events.append("redis_closed"))
            mock_obs.shutdown.side_effect = lambda: events.append("observability_shutdown")

            from ml_compute_service.main import lifespan

            async with lifespan(MagicMock(spec=FastAPI)):
                await supervisor_entered.wait()
                assert gate.state is ReadinessState.READY
                events.append("body")

        assert events == [
            "models_cached",
            "colbert_warmed",
            "sparse_warmed",
            "consumer_started",
            "supervision_entered",
            "body",
            "supervision_cancelled",
            "consumers_stopped",
            "kafka_closed",
            "redis_closed",
            "observability_shutdown",
        ]

    @pytest.mark.asyncio
    async def test_fatal_consumer_failure_interrupts_lifespan_after_warmup(
        self,
    ) -> None:
        """Owner failure cancels lifespan only after warmup starts consumers and readiness."""
        from ml_compute_service.core.readiness import ReadinessGate, ReadinessState

        events: list[str] = []
        warmup_entered = asyncio.Event()
        release_warmup = asyncio.Event()
        supervision_entered = asyncio.Event()
        release_failure = asyncio.Event()
        failure = RuntimeError("consumer owner failed")
        gate = ReadinessGate()

        async def warm_models() -> None:
            warmup_entered.set()
            await release_warmup.wait()

        async def wait_for_consumers() -> None:
            assert events[-1] == "consumer_started"
            assert gate.state is ReadinessState.READY
            events.append("supervision_entered")
            supervision_entered.set()
            await release_failure.wait()
            raise failure

        mock_pipeline = MagicMock()
        with (
            patch("ml_compute_service.main.ensure_kafka_ready", new_callable=AsyncMock),
            patch(
                "ml_compute_service.main._ensure_models_cached",
                new_callable=AsyncMock,
                side_effect=warm_models,
            ),
            patch(
                "ml_compute_service.main.get_encoding_pipeline",
                return_value=mock_pipeline,
            ),
            patch("ml_compute_service.main.kafka_client") as mock_kafka,
            patch("ml_compute_service.main.CacheFactory") as mock_cache_factory,
            patch("ml_compute_service.main.obs") as mock_obs,
            patch("ml_compute_service.main.start_event_consumer") as mock_start,
            patch("ml_compute_service.main.readiness_gate", new=gate),
        ):
            mock_start.side_effect = lambda: events.append("consumer_started")
            mock_kafka.wait_for_consumers = AsyncMock(side_effect=wait_for_consumers)
            mock_kafka.stop_consumers = AsyncMock(side_effect=lambda: events.append("consumers_stopped"))
            mock_kafka.close = AsyncMock(side_effect=lambda: events.append("kafka_closed"))
            mock_cache_factory.close_all = AsyncMock(side_effect=lambda: events.append("redis_closed"))
            mock_obs.shutdown.side_effect = lambda: events.append("observability_shutdown")

            from ml_compute_service.main import lifespan

            async def run_lifespan_until_consumer_failure() -> None:
                async with lifespan(MagicMock(spec=FastAPI)):
                    await warmup_entered.wait()
                    assert gate.state is ReadinessState.LOADING
                    assert mock_start.call_count == 0
                    assert mock_kafka.wait_for_consumers.await_count == 0

                    release_warmup.set()
                    await supervision_entered.wait()
                    release_failure.set()
                    try:
                        await asyncio.Event().wait()
                    finally:
                        events.append("body_cancelled")

            with pytest.raises(BaseExceptionGroup) as raised:
                await run_lifespan_until_consumer_failure()

        assert _exception_group_contains(raised.value, failure)
        assert events == [
            "consumer_started",
            "supervision_entered",
            "body_cancelled",
            "consumers_stopped",
            "kafka_closed",
            "redis_closed",
            "observability_shutdown",
        ]


class TestValidateComputeBackendGPU:
    """Tests for GPU backend validation path."""

    def test_gpu_backend_raises_when_unavailable(self) -> None:
        """GPU backend config raises GpuNotAvailableError when GPU not present."""
        from ml_compute_service.core.config import ComputeBackendConfig
        from ml_compute_service.main import _validate_compute_backend_on_startup
        from nohiki_ml_core import GpuNotAvailableError

        with (
            patch("ml_compute_service.main.settings") as mock_settings,
            patch(
                "ml_compute_service.main.validate_compute_backend",
                side_effect=GpuNotAvailableError("No GPU"),
            ),
            patch("ml_compute_service.main.logger"),
        ):
            mock_settings.processing.compute_backend = ComputeBackendConfig.GPU
            with pytest.raises(GpuNotAvailableError):
                _validate_compute_backend_on_startup()

    def test_gpu_backend_returns_cuda_when_available(self) -> None:
        """GPU backend config returns CUDA when validation passes."""
        from ml_compute_service.core.config import ComputeBackendConfig
        from ml_compute_service.main import _validate_compute_backend_on_startup
        from nohiki_ml_core import ComputeBackend

        with (
            patch("ml_compute_service.main.settings") as mock_settings,
            patch("ml_compute_service.main.validate_compute_backend"),
            patch("ml_compute_service.main.logger"),
        ):
            mock_settings.processing.compute_backend = ComputeBackendConfig.GPU
            result = _validate_compute_backend_on_startup()
            assert result == ComputeBackend.CUDA


class TestValidateComputeBackendAuto:
    """Tests for AUTO backend detection path."""

    def test_auto_backend_detects_available(self) -> None:
        """AUTO backend config auto-detects and returns the available backend."""
        from ml_compute_service.core.config import ComputeBackendConfig
        from ml_compute_service.main import _validate_compute_backend_on_startup
        from nohiki_ml_core import ComputeBackend

        mock_caps = MagicMock()
        mock_caps.cuda_available = False
        mock_caps.device_count = 0

        with (
            patch("ml_compute_service.main.settings") as mock_settings,
            patch(
                "ml_compute_service.main.get_available_backend",
                return_value=ComputeBackend.CPU,
            ),
            patch(
                "ml_compute_service.main.detect_gpu_capabilities",
                return_value=mock_caps,
            ),
            patch("ml_compute_service.main.logger"),
        ):
            mock_settings.processing.compute_backend = ComputeBackendConfig.AUTO
            result = _validate_compute_backend_on_startup()
            assert result == ComputeBackend.CPU


class TestWarmUpModelsFailure:
    """Tests for _warm_up_models_and_start_consumers failure path."""

    @pytest.mark.asyncio
    async def test_marks_failed_on_exception(self) -> None:
        """Warmup failure marks readiness gate as failed and re-raises."""
        with (
            patch("ml_compute_service.main._ensure_models_cached", new_callable=AsyncMock),
            patch(
                "ml_compute_service.main.get_encoding_pipeline",
                side_effect=RuntimeError("Model download failed"),
            ),
            patch("ml_compute_service.main.readiness_gate") as mock_gate,
            patch("ml_compute_service.main.logger"),
        ):
            from ml_compute_service.main import _warm_up_models_and_start_consumers

            with pytest.raises(RuntimeError, match="Model download failed"):
                await _warm_up_models_and_start_consumers()

            mock_gate.mark_failed.assert_called_once()


class TestLifespanShutdownCancelsWarmup:
    """Tests for lifespan shutdown cancelling in-progress warmup."""

    @pytest.mark.asyncio
    async def test_normal_shutdown_cancels_warmup_without_starting_supervision(
        self,
    ) -> None:
        """Shutdown during loading cancels warmup and never supervises absent consumers."""
        from ml_compute_service.core.readiness import ReadinessGate, ReadinessState

        events: list[str] = []
        warmup_entered = asyncio.Event()
        gate = ReadinessGate()

        async def blocked_warmup() -> None:
            warmup_entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                events.append("warmup_cancelled")

        with (
            patch("ml_compute_service.main.ensure_kafka_ready", new_callable=AsyncMock),
            patch(
                "ml_compute_service.main._ensure_models_cached",
                new_callable=AsyncMock,
                side_effect=blocked_warmup,
            ),
            patch("ml_compute_service.main.kafka_client") as mock_kafka,
            patch("ml_compute_service.main.CacheFactory") as mock_cache_factory,
            patch("ml_compute_service.main.obs") as mock_obs,
            patch("ml_compute_service.main.start_event_consumer") as mock_start,
            patch("ml_compute_service.main.readiness_gate", new=gate),
        ):
            mock_kafka.wait_for_consumers = AsyncMock(
                side_effect=AssertionError("supervision started before consumers")
            )
            mock_kafka.stop_consumers = AsyncMock(side_effect=lambda: events.append("consumers_stopped"))
            mock_kafka.close = AsyncMock(side_effect=lambda: events.append("kafka_closed"))
            mock_cache_factory.close_all = AsyncMock(side_effect=lambda: events.append("redis_closed"))
            mock_obs.shutdown.side_effect = lambda: events.append("observability_shutdown")

            from ml_compute_service.main import lifespan

            async with lifespan(MagicMock(spec=FastAPI)):
                await warmup_entered.wait()
                assert gate.state is ReadinessState.LOADING

        mock_start.assert_not_called()
        mock_kafka.wait_for_consumers.assert_not_awaited()
        assert events == [
            "warmup_cancelled",
            "consumers_stopped",
            "kafka_closed",
            "redis_closed",
            "observability_shutdown",
        ]


class TestDownloadModelFromSource:
    """Tests for _download_model_from_source callback."""

    @pytest.mark.asyncio
    async def test_fastembed_stages_model_files(self, tmp_path: Path) -> None:
        """FastEmbed receives its staging cache explicitly without mutating global state."""
        archive = ModelArchive(
            s3_key="models/sparse/test/model.tar.gz",
            extract_dir="fastembed",
            model_id="test/sparse-model",
        )
        mock_sparse_cls = MagicMock()

        async def run_in_thread(function: object, *args: object, **kwargs: object) -> object:
            if function is mock_sparse_cls:
                assert not args
                assert kwargs == {
                    "model_name": archive.model_id,
                    "cache_dir": str(tmp_path),
                }
                _write_test_file(tmp_path / "model.onnx", b"model data")
                return MagicMock()
            assert not kwargs
            assert args == (tmp_path,)
            return _contains_test_files(tmp_path)

        mock_module = MagicMock()
        mock_module.SparseTextEmbedding = mock_sparse_cls
        with (
            patch.dict("os.environ", {"FASTEMBED_CACHE_PATH": "/final/cache"}, clear=False) as environment,
            patch("ml_compute_service.main.asyncio.to_thread", side_effect=run_in_thread),
            patch("ml_compute_service.main.logger"),
            patch("importlib.import_module", return_value=mock_module),
        ):
            from ml_compute_service.main import _download_model_from_source

            await _download_model_from_source(archive, tmp_path)

            assert environment["FASTEMBED_CACHE_PATH"] == "/final/cache"
            assert _read_test_file(tmp_path / "model.onnx") == b"model data"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("model_id", ["test/dense-model", "test/colbert-model"])
    async def test_huggingface_download_stages_repository_under_target(self, tmp_path: Path, model_id: str) -> None:
        """Every Hugging Face model downloads explicitly into the staging tree."""
        archive = ModelArchive(
            s3_key=f"models/{model_id}/model.tar.gz",
            extract_dir="huggingface",
            model_id=model_id,
        )
        expected_cache_dir = tmp_path / "hub"

        def snapshot_download(*, repo_id: str, cache_dir: Path) -> Path:
            assert repo_id == model_id
            assert cache_dir == expected_cache_dir
            repository = cache_dir / "models--test--model"
            blob = repository / "blobs" / "digest"
            blob.parent.mkdir(parents=True)
            blob.write_text("{}")
            snapshot = repository / "snapshots" / "revision"
            snapshot.mkdir(parents=True)
            (snapshot / "config.json").symlink_to(blob)
            return snapshot

        with (
            patch("ml_compute_service.main.asyncio.to_thread", new_callable=AsyncMock) as to_thread,
            patch("ml_compute_service.main.logger"),
            patch(
                "ml_compute_service.main.snapshot_download",
                side_effect=snapshot_download,
            ) as downloader,
        ):
            to_thread.side_effect = lambda function, *args, **kwargs: function(*args, **kwargs)
            from ml_compute_service.main import _download_model_from_source

            await _download_model_from_source(archive, tmp_path)

        downloader.assert_called_once_with(repo_id=model_id, cache_dir=expected_cache_dir)
        config = expected_cache_dir / "models--test--model/snapshots/revision/config.json"
        assert config.is_symlink()
        assert config.read_text() == "{}"

    @pytest.mark.asyncio
    async def test_huggingface_download_with_pinned_revision_passes_revision_kwarg(
        self,
        tmp_path: Path,
    ) -> None:
        """A pinned revision is forwarded to the downloader instead of using latest."""
        archive = ModelArchive(
            s3_key="models/dense/test/model.tar.gz",
            extract_dir="huggingface",
            model_id="test/pinned-model",
            revision="abc123",
        )
        expected_cache_dir = tmp_path / "hub"

        def snapshot_download(*, repo_id: str, revision: str, cache_dir: Path) -> Path:
            assert repo_id == archive.model_id
            assert revision == "abc123"
            assert cache_dir == expected_cache_dir
            repository = cache_dir / "models--test--model"
            blob = repository / "blobs" / "digest"
            blob.parent.mkdir(parents=True)
            blob.write_text("{}")
            snapshot = repository / "snapshots" / "abc123"
            snapshot.mkdir(parents=True)
            (snapshot / "config.json").symlink_to(blob)
            return snapshot

        with (
            patch("ml_compute_service.main.asyncio.to_thread", new_callable=AsyncMock) as to_thread,
            patch("ml_compute_service.main.logger"),
            patch(
                "ml_compute_service.main.snapshot_download",
                side_effect=snapshot_download,
            ) as downloader,
        ):
            to_thread.side_effect = lambda function, *args, **kwargs: function(*args, **kwargs)
            from ml_compute_service.main import _download_model_from_source

            await _download_model_from_source(archive, tmp_path)

        downloader.assert_called_once_with(
            repo_id=archive.model_id,
            revision="abc123",
            cache_dir=expected_cache_dir,
        )
        config = expected_cache_dir / "models--test--model/snapshots/abc123/config.json"
        assert config.is_symlink()
        assert config.read_text() == "{}"

    @pytest.mark.asyncio
    async def test_empty_huggingface_download_fails(self, tmp_path: Path) -> None:
        """A downloader return without staged files cannot become an empty archive."""
        archive = ModelArchive(
            s3_key="models/dense/test/model.tar.gz",
            extract_dir="huggingface",
            model_id="test/empty-model",
        )

        with (
            patch("ml_compute_service.main.asyncio.to_thread", new_callable=AsyncMock) as to_thread,
            patch("ml_compute_service.main.logger"),
            patch(
                "ml_compute_service.main.snapshot_download",
                return_value=tmp_path / "hub",
            ),
        ):
            to_thread.side_effect = lambda function, *args, **kwargs: function(*args, **kwargs)
            from ml_compute_service.main import _download_model_from_source

            with pytest.raises(RuntimeError, match="produced no model files") as raised:
                await _download_model_from_source(archive, tmp_path)

        assert archive.model_id in str(raised.value)
        assert str(tmp_path) in str(raised.value)

    @pytest.mark.asyncio
    async def test_huggingface_download_error_propagates(self, tmp_path: Path) -> None:
        """Upstream download failures retain their original exception."""
        archive = ModelArchive(
            s3_key="models/dense/test/model.tar.gz",
            extract_dir="huggingface",
            model_id="test/failing-model",
        )
        failure = OSError("hub unavailable")

        with (
            patch("ml_compute_service.main.asyncio.to_thread", new_callable=AsyncMock) as to_thread,
            patch("ml_compute_service.main.logger"),
            patch("ml_compute_service.main.snapshot_download", side_effect=failure),
        ):
            to_thread.side_effect = lambda function, *args, **kwargs: function(*args, **kwargs)
            from ml_compute_service.main import _download_model_from_source

            with pytest.raises(OSError, match="hub unavailable") as raised:
                await _download_model_from_source(archive, tmp_path)

        assert raised.value is failure


class TestEnsureModelsCached:
    """Tests for _ensure_models_cached function."""

    @pytest.mark.asyncio
    async def test_creates_manager_and_calls_ensure(self) -> None:
        """Verifies _ensure_models_cached reads manifest and delegates to ModelCacheManager."""
        mock_manifest = MagicMock()
        mock_manager_instance = MagicMock()
        mock_manager_instance.ensure_models_available = AsyncMock()

        with (
            patch.dict("os.environ", {}, clear=False) as environment,
            patch("ml_compute_service.main.get_manifest", return_value=mock_manifest),
            patch("ml_compute_service.main.settings") as mock_settings,
            patch("ml_compute_service.main.S3Client") as mock_s3,
            patch("ml_compute_service.main.CacheFactory") as mock_cf,
            patch(
                "ml_compute_service.main.ModelCacheManager",
                return_value=mock_manager_instance,
            ) as mock_mcm,
            patch("ml_compute_service.main.logger"),
        ):
            mock_settings.processing.cache_dir = Path("/home/app/.cache")
            mock_settings.s3 = MagicMock()
            mock_settings.redis_url = "redis://localhost:6379/0"

            from ml_compute_service.main import _ensure_models_cached

            await _ensure_models_cached()

            mock_s3.assert_called_once_with(mock_settings.s3)
            mock_cf.create_cache.assert_called_once_with("model-cache", redis_url="redis://localhost:6379/0")
            mock_mcm.assert_called_once()
            call_kwargs = mock_mcm.call_args.kwargs
            assert call_kwargs["manifest"] is mock_manifest
            assert environment["FASTEMBED_CACHE_PATH"] == "/home/app/.cache/fastembed"
            mock_manager_instance.ensure_models_available.assert_called_once()


class TestEventsModuleImport:
    """Tests for events module import."""

    def test_events_exports_start_consumer(self) -> None:
        """Verifies events module exports start_event_consumer."""
        from ml_compute_service.events import start_event_consumer

        assert callable(start_event_consumer)

    def test_handlers_exports_handler(self) -> None:
        """Verifies handlers module exports expected handlers."""
        from ml_compute_service.events.handlers import (
            handle_internal_compute,
            start_event_consumer,
        )

        assert callable(handle_internal_compute)
        assert callable(start_event_consumer)
