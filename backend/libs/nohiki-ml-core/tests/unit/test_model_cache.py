"""Tests for ModelCacheManager."""

from __future__ import annotations

import asyncio
import io
import os
import tarfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from nohiki_ml_core import model_cache
from nohiki_ml_core.model_cache import (
    ModelArchive,
    ModelCacheManager,
    _compute_manifest_hash,
    _default_model_archives,
)
from nohiki_ml_manifest import SemanticRepresentationManifest


@pytest.fixture
def mock_manifest() -> MagicMock:
    """Create a mock SemanticRepresentationManifest."""
    manifest = MagicMock()
    manifest.late_interaction.model_id = "mixedbread-ai/mxbai-edge-colbert-v0-17m"
    manifest.late_interaction.token_dim = 48
    manifest.sparse.model_id = "Qdrant/minicoil-v1"
    manifest.dense.model_id = "TechWolf/JobBERT-v2"
    manifest.dense.embedding_dim = 1024
    return manifest


@pytest.fixture
def tmp_cache_dir(tmp_path: Path) -> Path:
    """Create a temporary cache directory."""
    cache_dir = tmp_path / "models"
    cache_dir.mkdir()
    return cache_dir


def _make_tar_gz_bytes() -> bytes:
    """Create a minimal tar.gz archive for testing."""
    return _make_named_tar_gz_bytes("model.bin", b"test model data")


def _make_named_tar_gz_bytes(name: str, content: bytes) -> bytes:
    """Create an archive containing one repository-specific file."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo(name=name)
        info.size = len(content)
        tar.addfile(info, io.BytesIO(content))
    return buf.getvalue()


def _make_tar_gz_with_member_sizes(member_sizes: list[int]) -> bytes:
    """Create an archive whose declared extraction size is deterministic."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for index, size in enumerate(member_sizes):
            data = b"x" * size
            info = tarfile.TarInfo(name=f"model-{index}.bin")
            info.size = size
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _make_mock_lock() -> AsyncMock:
    """Create a mock async context manager for distributed_lock."""
    lock_cm = AsyncMock()
    lock_cm.__aenter__ = AsyncMock()
    lock_cm.__aexit__ = AsyncMock(return_value=False)
    return lock_cm


class TestComputeManifestHash:
    """Tests for _compute_manifest_hash."""

    def test_deterministic(self, mock_manifest: MagicMock) -> None:
        """Same manifest produces same hash."""
        h1 = _compute_manifest_hash(mock_manifest)
        h2 = _compute_manifest_hash(mock_manifest)
        assert h1 == h2

    def test_changes_on_model_id_change(self, mock_manifest: MagicMock) -> None:
        """Hash changes when model ID changes."""
        h1 = _compute_manifest_hash(mock_manifest)
        mock_manifest.dense.model_id = "different-model"
        h2 = _compute_manifest_hash(mock_manifest)
        assert h1 != h2

    def test_changes_on_non_identifier_manifest_field(self, sample_manifest_data: dict[str, object]) -> None:
        """Cache identity changes when artifact-affecting manifest settings change."""
        manifest = SemanticRepresentationManifest.model_validate(sample_manifest_data)
        changed_manifest = manifest.model_copy(deep=True)
        changed_manifest.dense.max_length += 1

        assert _compute_manifest_hash(manifest) != _compute_manifest_hash(changed_manifest)

    def test_returns_16_char_hex(self, mock_manifest: MagicMock) -> None:
        """Hash is a 16-character hex string."""
        h = _compute_manifest_hash(mock_manifest)
        assert len(h) == 16
        int(h, 16)  # Should not raise


class TestDefaultModelArchives:
    """Tests for _default_model_archives."""

    def test_returns_three_archives(self, mock_manifest: MagicMock) -> None:
        """Returns one archive per model type."""
        archives = _default_model_archives(mock_manifest)
        assert len(archives) == 3

    def test_s3_keys_contain_model_ids(self, mock_manifest: MagicMock) -> None:
        """S3 keys include the model IDs from manifest."""
        archives = _default_model_archives(mock_manifest)
        keys = [a.s3_key for a in archives]
        assert any("mxbai-edge-colbert" in k for k in keys)
        assert any("JobBERT-v2" in k for k in keys)
        assert any("minicoil-v1" in k for k in keys)

    def test_extract_dirs(self, mock_manifest: MagicMock) -> None:
        """Extract dirs are huggingface or fastembed."""
        archives = _default_model_archives(mock_manifest)
        dirs = {a.extract_dir for a in archives}
        assert dirs == {"huggingface", "fastembed"}

    def test_archives_carry_model_id(self, mock_manifest: MagicMock) -> None:
        """Each archive carries the upstream model_id for source downloads."""
        archives = _default_model_archives(mock_manifest)
        ids = {a.model_id for a in archives}
        assert "mixedbread-ai/mxbai-edge-colbert-v0-17m" in ids
        assert "TechWolf/JobBERT-v2" in ids
        assert "Qdrant/minicoil-v1" in ids

    def test_unrelated_manifest_change_keeps_archive_key(self, sample_manifest_data: dict[str, object]) -> None:
        """Changing an unrelated model setting does not duplicate the dense archive."""
        manifest = SemanticRepresentationManifest.model_validate(sample_manifest_data)
        changed_manifest = manifest.model_copy(deep=True)
        changed_manifest.dense.max_length += 1

        original = _default_model_archives(manifest)
        changed = _default_model_archives(changed_manifest)

        assert original[1].s3_key == changed[1].s3_key

    def test_sibling_model_change_keeps_archive_key(self, sample_manifest_data: dict[str, object]) -> None:
        """Changing a sibling model does not duplicate the ColBERT archive."""
        manifest = SemanticRepresentationManifest.model_validate(sample_manifest_data)
        changed_manifest = manifest.model_copy(deep=True)
        changed_manifest.dense.model_id = "another/dense-model"

        original = _default_model_archives(manifest)
        changed = _default_model_archives(changed_manifest)

        assert original[0].s3_key == changed[0].s3_key
        assert original[1].s3_key != changed[1].s3_key

    def test_model_revision_changes_archive_key(self, mock_manifest: MagicMock) -> None:
        """Changing a model revision selects a distinct archive object."""
        mock_manifest.dense.revision = "revision-a"
        original = _default_model_archives(mock_manifest)

        mock_manifest.dense.revision = "revision-b"
        changed = _default_model_archives(mock_manifest)

        assert original[1].s3_key != changed[1].s3_key
        assert original[1].revision == "revision-a"
        assert changed[1].revision == "revision-b"


class TestModelCacheManager:
    """Tests for ModelCacheManager."""

    def _make_manager(
        self,
        mock_manifest: MagicMock,
        tmp_cache_dir: Path,
        *,
        source_downloader: AsyncMock | None = None,
    ) -> tuple[ModelCacheManager, AsyncMock, MagicMock, AsyncMock]:
        """Create a ModelCacheManager with mocked dependencies."""
        mock_s3 = AsyncMock()
        mock_redis = MagicMock()
        mock_redis.distributed_lock = MagicMock()
        mock_downloader = source_downloader or AsyncMock()

        manager = ModelCacheManager(
            s3_client=mock_s3,
            redis_cache=mock_redis,
            cache_dir=tmp_cache_dir,
            manifest=mock_manifest,
            source_downloader=mock_downloader,
        )
        return manager, mock_s3, mock_redis, mock_downloader

    def test_manifest_hash_property(self, mock_manifest: MagicMock, tmp_cache_dir: Path) -> None:
        """manifest_hash property returns the computed hash."""
        manager, *_ = self._make_manager(mock_manifest, tmp_cache_dir)
        assert manager.manifest_hash == _compute_manifest_hash(mock_manifest)

    @pytest.mark.asyncio
    async def test_skips_everything_when_cache_valid(self, mock_manifest: MagicMock, tmp_cache_dir: Path) -> None:
        """Skips all downloads when version marker matches."""
        manager, mock_s3, _, mock_dl = self._make_manager(mock_manifest, tmp_cache_dir)

        marker = tmp_cache_dir / ".cache_version"
        marker.write_text(manager.manifest_hash)

        await manager.ensure_models_available()

        mock_s3.get_object.assert_not_called()
        mock_s3.object_exists.assert_not_called()
        mock_dl.assert_not_called()

    @pytest.mark.asyncio
    async def test_downloads_from_s3_when_archives_exist(self, mock_manifest: MagicMock, tmp_cache_dir: Path) -> None:
        """Downloads from S3 when archives exist there."""
        archive_data = _make_tar_gz_bytes()

        async def get_bounded_object(_key: str, *, max_bytes: int) -> bytes:
            assert max_bytes >= len(archive_data)
            return archive_data

        manager, mock_s3, mock_redis, mock_dl = self._make_manager(mock_manifest, tmp_cache_dir)
        mock_s3.object_exists.return_value = True
        mock_s3.get_object.side_effect = get_bounded_object
        mock_redis.distributed_lock.return_value = _make_mock_lock()

        await manager.ensure_models_available()

        assert mock_s3.object_exists.call_count == 3
        assert mock_s3.get_object.call_count == 3
        mock_dl.assert_not_called()
        mock_s3.put_object.assert_not_called()
        assert (tmp_cache_dir / ".cache_version").read_text() == manager.manifest_hash

    @pytest.mark.asyncio
    async def test_downloads_from_source_when_s3_missing(self, mock_manifest: MagicMock, tmp_cache_dir: Path) -> None:
        """Downloads from upstream source and uploads to S3 when archives missing."""

        def fake_source_download(_archive: ModelArchive, target_dir: Path) -> None:
            (target_dir / "model.bin").write_bytes(b"fake model")

        mock_dl = AsyncMock(side_effect=fake_source_download)
        manager, mock_s3, mock_redis, _ = self._make_manager(mock_manifest, tmp_cache_dir, source_downloader=mock_dl)
        mock_s3.object_exists.return_value = False
        mock_redis.distributed_lock.return_value = _make_mock_lock()

        await manager.ensure_models_available()

        assert mock_s3.object_exists.call_count == 3
        assert mock_dl.call_count == 3
        assert mock_s3.put_object.call_count == 3
        mock_s3.get_object.assert_not_called()
        assert (tmp_cache_dir / ".cache_version").read_text() == manager.manifest_hash

    @pytest.mark.asyncio
    async def test_mixed_s3_hit_and_miss(self, mock_manifest: MagicMock, tmp_cache_dir: Path) -> None:
        """Some archives in S3, others need source download."""

        def fake_source_download(_archive: ModelArchive, target_dir: Path) -> None:
            (target_dir / "model.bin").write_bytes(b"fake model")

        mock_dl = AsyncMock(side_effect=fake_source_download)
        manager, mock_s3, mock_redis, _ = self._make_manager(mock_manifest, tmp_cache_dir, source_downloader=mock_dl)
        mock_s3.object_exists.side_effect = [True, False, True]
        mock_s3.get_object.return_value = _make_tar_gz_bytes()
        mock_redis.distributed_lock.return_value = _make_mock_lock()

        await manager.ensure_models_available()

        assert mock_s3.get_object.call_count == 2
        assert mock_dl.call_count == 1
        assert mock_s3.put_object.call_count == 1

    @pytest.mark.asyncio
    async def test_stale_cache_triggers_redownload(self, mock_manifest: MagicMock, tmp_cache_dir: Path) -> None:
        """Downloads when version marker has old hash."""
        manager, mock_s3, mock_redis, _ = self._make_manager(mock_manifest, tmp_cache_dir)
        mock_s3.object_exists.return_value = True
        mock_s3.get_object.return_value = _make_tar_gz_bytes()
        mock_redis.distributed_lock.return_value = _make_mock_lock()

        marker = tmp_cache_dir / ".cache_version"
        marker.write_text("old_stale_hash")

        await manager.ensure_models_available()

        assert mock_s3.get_object.call_count == 3
        assert marker.read_text() == manager.manifest_hash

    @pytest.mark.asyncio
    async def test_skips_download_after_lock_if_another_pod_finished(
        self, mock_manifest: MagicMock, tmp_cache_dir: Path
    ) -> None:
        """After acquiring lock, re-checks cache and skips if valid."""
        manager, mock_s3, mock_redis, _ = self._make_manager(mock_manifest, tmp_cache_dir)

        mock_lock_cm = AsyncMock()
        mock_lock_cm.__aexit__ = AsyncMock(return_value=False)

        async def enter_lock(_self: object) -> None:
            await asyncio.sleep(0)
            marker = tmp_cache_dir / ".cache_version"
            marker.write_text(manager.manifest_hash)

        mock_lock_cm.__aenter__ = enter_lock
        mock_redis.distributed_lock.return_value = mock_lock_cm

        await manager.ensure_models_available()

        mock_s3.get_object.assert_not_called()
        mock_s3.object_exists.assert_not_called()

    @pytest.mark.asyncio
    async def test_extracts_to_correct_subdirectories(self, mock_manifest: MagicMock, tmp_cache_dir: Path) -> None:
        """Archives are extracted to their specified extract_dir."""
        manager, mock_s3, mock_redis, _ = self._make_manager(mock_manifest, tmp_cache_dir)
        mock_s3.object_exists.return_value = True
        mock_s3.get_object.return_value = _make_tar_gz_bytes()
        mock_redis.distributed_lock.return_value = _make_mock_lock()

        await manager.ensure_models_available()

        assert (tmp_cache_dir / "huggingface").is_dir()
        assert (tmp_cache_dir / "fastembed").is_dir()
        assert (tmp_cache_dir / "huggingface" / "model.bin").exists()
        assert (tmp_cache_dir / "fastembed" / "model.bin").exists()

    @pytest.mark.asyncio
    async def test_concurrent_source_archives_merge_sibling_huggingface_repositories(
        self, mock_manifest: MagicMock, tmp_cache_dir: Path
    ) -> None:
        """Concurrent source staging retains both repositories in the shared hub."""
        both_downloads_started = asyncio.Event()
        started = 0

        async def stage_repository(archive: ModelArchive, target_dir: Path) -> None:
            nonlocal started
            started += 1
            if started == 2:
                both_downloads_started.set()
            await both_downloads_started.wait()
            repository = target_dir / "hub" / f"models--{archive.model_id.replace('/', '--')}"
            repository.mkdir(parents=True)
            (repository / "config.json").write_text(archive.model_id)

        downloader = AsyncMock(side_effect=stage_repository)
        manager, mock_s3, mock_redis, _ = self._make_manager(mock_manifest, tmp_cache_dir, source_downloader=downloader)
        archives = [
            ModelArchive("dense.tar.gz", "huggingface", "test/dense"),
            ModelArchive("colbert.tar.gz", "huggingface", "test/colbert"),
        ]
        manager._archives = archives
        mock_s3.object_exists.return_value = False
        mock_redis.distributed_lock.return_value = _make_mock_lock()

        await manager.ensure_models_available()

        hub = tmp_cache_dir / "huggingface" / "hub"
        assert (hub / "models--test--dense" / "config.json").read_text() == "test/dense"
        assert (hub / "models--test--colbert" / "config.json").read_text() == "test/colbert"
        assert mock_s3.put_object.call_count == 2

    @pytest.mark.asyncio
    async def test_source_downloader_failure_removes_staging_and_preserves_error(
        self, mock_manifest: MagicMock, tmp_cache_dir: Path
    ) -> None:
        """A failed upstream download does not leave manifest-keyed staging behind."""
        error = RuntimeError("source download failed")

        async def fail_download(_archive: ModelArchive, target_dir: Path) -> None:
            (target_dir / "partial.bin").write_bytes(b"partial")
            raise error

        manager, mock_s3, mock_redis, _ = self._make_manager(
            mock_manifest, tmp_cache_dir, source_downloader=AsyncMock(side_effect=fail_download)
        )
        archive = ModelArchive("dense.tar.gz", "huggingface", "test/dense")
        manager._archives = [archive]
        mock_s3.object_exists.return_value = False
        mock_redis.distributed_lock.return_value = _make_mock_lock()

        with pytest.RaisesGroup(RuntimeError) as caught:
            await manager.ensure_models_available()

        assert caught.value.exceptions == (error,)
        assert not manager._staging_dir(archive).exists()

    @pytest.mark.asyncio
    async def test_packaging_failure_removes_staging_and_preserves_error(
        self, monkeypatch: pytest.MonkeyPatch, mock_manifest: MagicMock, tmp_cache_dir: Path
    ) -> None:
        """A packaging error removes the completed source download staging directory."""
        error = RuntimeError("packaging failed")

        def download(_archive: ModelArchive, target_dir: Path) -> None:
            (target_dir / "model.bin").write_bytes(b"model")

        def fail_packaging(_source_dir: Path) -> bytes:
            raise error

        monkeypatch.setattr(model_cache, "_package_directory_as_tar_gz", fail_packaging)
        manager, mock_s3, mock_redis, _ = self._make_manager(
            mock_manifest, tmp_cache_dir, source_downloader=AsyncMock(side_effect=download)
        )
        archive = ModelArchive("dense.tar.gz", "huggingface", "test/dense")
        manager._archives = [archive]
        mock_s3.object_exists.return_value = False
        mock_redis.distributed_lock.return_value = _make_mock_lock()

        with pytest.RaisesGroup(RuntimeError) as caught:
            await manager.ensure_models_available()

        assert caught.value.exceptions == (error,)
        assert not manager._staging_dir(archive).exists()

    @pytest.mark.asyncio
    async def test_s3_put_failure_removes_staging_and_preserves_error(
        self, mock_manifest: MagicMock, tmp_cache_dir: Path
    ) -> None:
        """An upload error removes its packaged staging directory."""
        error = RuntimeError("S3 put failed")

        def download(_archive: ModelArchive, target_dir: Path) -> None:
            (target_dir / "model.bin").write_bytes(b"model")

        manager, mock_s3, mock_redis, _ = self._make_manager(
            mock_manifest, tmp_cache_dir, source_downloader=AsyncMock(side_effect=download)
        )
        archive = ModelArchive("dense.tar.gz", "huggingface", "test/dense")
        manager._archives = [archive]
        mock_s3.object_exists.return_value = False
        mock_s3.put_object.side_effect = error
        mock_redis.distributed_lock.return_value = _make_mock_lock()

        with pytest.RaisesGroup(RuntimeError) as caught:
            await manager.ensure_models_available()

        assert caught.value.exceptions == (error,)
        assert not manager._staging_dir(archive).exists()

    @pytest.mark.asyncio
    async def test_successful_source_merge_consumes_staging(
        self, mock_manifest: MagicMock, tmp_cache_dir: Path
    ) -> None:
        """A successful merge moves the model into cache and consumes staging."""

        def download(_archive: ModelArchive, target_dir: Path) -> None:
            (target_dir / "model.bin").write_bytes(b"model")

        manager, mock_s3, mock_redis, _ = self._make_manager(
            mock_manifest, tmp_cache_dir, source_downloader=AsyncMock(side_effect=download)
        )
        archive = ModelArchive("dense.tar.gz", "huggingface", "test/dense")
        manager._archives = [archive]
        mock_s3.object_exists.return_value = False
        mock_redis.distributed_lock.return_value = _make_mock_lock()

        await manager.ensure_models_available()

        assert (tmp_cache_dir / "huggingface" / "model.bin").read_bytes() == b"model"
        assert not manager._staging_dir(archive).exists()

    @pytest.mark.asyncio
    async def test_contained_source_file_symlink_is_archived_and_merged_as_regular_bytes(
        self, mock_manifest: MagicMock, tmp_cache_dir: Path
    ) -> None:
        """Hugging Face snapshot links are dereferenced before upload and merge."""

        def download(_archive: ModelArchive, target_dir: Path) -> None:
            repository = target_dir / "hub" / "models--test--dense"
            blob = repository / "blobs" / "digest"
            blob.parent.mkdir(parents=True)
            blob.write_bytes(b"model weights")
            snapshot = repository / "snapshots" / "revision"
            snapshot.mkdir(parents=True)
            (snapshot / "model.bin").symlink_to(blob)

        manager, mock_s3, mock_redis, _ = self._make_manager(
            mock_manifest, tmp_cache_dir, source_downloader=AsyncMock(side_effect=download)
        )
        manager._archives = [ModelArchive("dense.tar.gz", "huggingface", "test/dense")]
        mock_s3.object_exists.return_value = False
        mock_redis.distributed_lock.return_value = _make_mock_lock()

        await manager.ensure_models_available()

        uploaded = mock_s3.put_object.await_args.args[1]
        with tarfile.open(fileobj=io.BytesIO(uploaded), mode="r:gz") as archive:
            member = archive.getmember("hub/models--test--dense/snapshots/revision/model.bin")
            assert member.isfile()
            extracted = archive.extractfile(member)
            assert extracted is not None
            assert extracted.read() == b"model weights"
        cached = tmp_cache_dir / "huggingface/hub/models--test--dense/snapshots/revision/model.bin"
        assert not cached.is_symlink()
        assert cached.read_bytes() == b"model weights"

    @pytest.mark.asyncio
    async def test_source_nonregular_entry_is_rejected_without_uploading(
        self, mock_manifest: MagicMock, tmp_cache_dir: Path
    ) -> None:
        """Source staging rejects FIFO entries rather than reading them as model data."""

        def download(_archive: ModelArchive, target_dir: Path) -> None:
            os.mkfifo(target_dir / "model.pipe")

        manager, mock_s3, mock_redis, _ = self._make_manager(
            mock_manifest, tmp_cache_dir, source_downloader=AsyncMock(side_effect=download)
        )
        manager._archives = [ModelArchive("dense.tar.gz", "huggingface", "test/dense")]
        mock_s3.object_exists.return_value = False
        mock_redis.distributed_lock.return_value = _make_mock_lock()

        with pytest.RaisesGroup(ValueError):
            await manager.ensure_models_available()

        mock_s3.put_object.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("marker_state", ["missing", "invalid"])
    @pytest.mark.parametrize("stale_kind", ["internal_symlink", "external_symlink", "partial_file"])
    async def test_invalid_cache_clears_managed_target_before_source_merge(
        self,
        mock_manifest: MagicMock,
        tmp_cache_dir: Path,
        tmp_path: Path,
        marker_state: str,
        stale_kind: str,
    ) -> None:
        """Invalid managed cache contents cannot collide with fresh population."""
        target = tmp_cache_dir / "huggingface"
        target.mkdir()
        outside = tmp_path / "outside.bin"
        outside.write_bytes(b"outside")
        if stale_kind == "internal_symlink":
            internal = target / "stale.bin"
            internal.write_bytes(b"stale")
            (target / "stale-link").symlink_to(internal)
        elif stale_kind == "external_symlink":
            (target / "stale-link").symlink_to(outside)
        else:
            (target / "partial.bin").write_bytes(b"partial")
        if marker_state == "invalid":
            (tmp_cache_dir / ".cache_version").write_text("stale-manifest")

        def download(_archive: ModelArchive, target_dir: Path) -> None:
            (target_dir / "fresh.bin").write_bytes(b"fresh")

        manager, mock_s3, mock_redis, _ = self._make_manager(
            mock_manifest, tmp_cache_dir, source_downloader=AsyncMock(side_effect=download)
        )
        manager._archives = [ModelArchive("dense.tar.gz", "huggingface", "test/dense")]
        mock_s3.object_exists.return_value = False
        mock_redis.distributed_lock.return_value = _make_mock_lock()

        await manager.ensure_models_available()

        assert (target / "fresh.bin").read_bytes() == b"fresh"
        assert not (target / "stale-link").exists()
        assert not (target / "partial.bin").exists()
        assert outside.read_bytes() == b"outside"
        assert (tmp_cache_dir / ".cache_version").read_text() == manager.manifest_hash

    def test_target_symlink_collision_is_rejected_without_outside_write(self, tmp_path: Path) -> None:
        """A merge still rejects a destination symlink outside cache reset."""
        outside = tmp_path / "outside"
        outside.mkdir()
        target = tmp_path / "target"
        target.mkdir()
        (target / "nested").symlink_to(outside, target_is_directory=True)
        source = tmp_path / "source"
        nested = source / "nested"
        nested.mkdir(parents=True)
        (nested / "model.bin").write_bytes(b"model")

        with pytest.raises(ValueError, match="target collision is a symlink"):
            model_cache._merge_directory(source, target)

        assert not (outside / "model.bin").exists()

    @pytest.mark.asyncio
    async def test_valid_nested_regular_source_tree_is_packaged_and_merged(
        self, mock_manifest: MagicMock, tmp_cache_dir: Path
    ) -> None:
        """Nested directories containing only regular files remain supported."""

        def download(_archive: ModelArchive, target_dir: Path) -> None:
            nested = target_dir / "repository" / "snapshots" / "revision"
            nested.mkdir(parents=True)
            (nested / "model.bin").write_bytes(b"model")

        manager, mock_s3, mock_redis, _ = self._make_manager(
            mock_manifest, tmp_cache_dir, source_downloader=AsyncMock(side_effect=download)
        )
        manager._archives = [ModelArchive("dense.tar.gz", "huggingface", "test/dense")]
        mock_s3.object_exists.return_value = False
        mock_redis.distributed_lock.return_value = _make_mock_lock()

        await manager.ensure_models_available()

        cached = tmp_cache_dir / "huggingface" / "repository" / "snapshots" / "revision" / "model.bin"
        assert cached.read_bytes() == b"model"
        mock_s3.put_object.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_s3_archives_merge_sibling_huggingface_repositories(
        self, mock_manifest: MagicMock, tmp_cache_dir: Path
    ) -> None:
        """S3 extraction uses the same serialized merge boundary as source staging."""
        manager, mock_s3, mock_redis, _ = self._make_manager(mock_manifest, tmp_cache_dir)
        archives = [
            ModelArchive("dense.tar.gz", "huggingface", "test/dense"),
            ModelArchive("colbert.tar.gz", "huggingface", "test/colbert"),
        ]
        manager._archives = archives
        payloads = {
            "dense.tar.gz": _make_named_tar_gz_bytes("hub/models--test--dense/config.json", b"dense"),
            "colbert.tar.gz": _make_named_tar_gz_bytes("hub/models--test--colbert/config.json", b"colbert"),
        }

        async def get_archive(key: str, *, max_bytes: int) -> bytes:
            assert max_bytes >= len(payloads[key])
            await asyncio.sleep(0)
            return payloads[key]

        mock_s3.object_exists.return_value = True
        mock_s3.get_object.side_effect = get_archive
        mock_redis.distributed_lock.return_value = _make_mock_lock()

        await manager.ensure_models_available()

        hub = tmp_cache_dir / "huggingface" / "hub"
        assert (hub / "models--test--dense" / "config.json").read_bytes() == b"dense"
        assert (hub / "models--test--colbert" / "config.json").read_bytes() == b"colbert"

    @pytest.mark.asyncio
    async def test_source_download_uploads_tar_gz_to_s3(self, mock_manifest: MagicMock, tmp_cache_dir: Path) -> None:
        """Source-downloaded models are packaged and uploaded to S3."""

        def fake_source_download(_archive: ModelArchive, target_dir: Path) -> None:
            (target_dir / "weights.bin").write_bytes(b"x" * 100)
            (target_dir / "config.json").write_bytes(b'{"key": "val"}')

        mock_dl = AsyncMock(side_effect=fake_source_download)
        manager, mock_s3, mock_redis, _ = self._make_manager(mock_manifest, tmp_cache_dir, source_downloader=mock_dl)
        mock_s3.object_exists.return_value = False
        mock_redis.distributed_lock.return_value = _make_mock_lock()

        await manager.ensure_models_available()

        for call in mock_s3.put_object.call_args_list:
            uploaded_bytes = call.args[1] if len(call.args) > 1 else call.kwargs["data"]
            assert isinstance(uploaded_bytes, bytes)
            assert len(uploaded_bytes) > 0
            with tarfile.open(fileobj=io.BytesIO(uploaded_bytes), mode="r:gz") as tar:
                names = tar.getnames()
                assert "weights.bin" in names or "model.bin" in names


class TestModelArchiveLimits:
    """Security boundaries for model packaging and extraction."""

    def test_rejects_archive_over_compressed_size_limit(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(model_cache, "_MAX_ARCHIVE_BYTES", 8)

        with pytest.raises(ValueError, match="archive size 9 exceeds limit 8"):
            ModelCacheManager._extract_tar_gz(b"x" * 9, tmp_path)

    def test_rejects_archive_over_member_count_limit(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(model_cache, "_MAX_ARCHIVE_MEMBERS", 1)
        archive = _make_tar_gz_with_member_sizes([1, 1])

        with pytest.raises(ValueError, match="member count 2 exceeds limit 1"):
            ModelCacheManager._extract_tar_gz(archive, tmp_path)

    def test_rejects_archive_over_extracted_size_limit(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(model_cache, "_MAX_EXTRACTED_BYTES", 3)
        archive = _make_tar_gz_with_member_sizes([4])

        with pytest.raises(ValueError, match="Extracted model size 4 exceeds limit 3"):
            ModelCacheManager._extract_tar_gz(archive, tmp_path)

    def test_rejects_source_directory_over_extracted_size_limit(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(model_cache, "_MAX_EXTRACTED_BYTES", 8)
        (tmp_path / "weights.bin").write_bytes(b"x" * 9)

        with pytest.raises(ValueError, match="Model directory size 9 exceeds extracted limit 8"):
            model_cache._package_directory_as_tar_gz(tmp_path)

    def test_rejects_compressed_archive_over_archive_limit(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(model_cache, "_MAX_ARCHIVE_BYTES", 1)
        (tmp_path / "weights.bin").write_bytes(b"model")

        with pytest.raises(ValueError, match=r"Model archive size \d+ exceeds limit 1"):
            model_cache._package_directory_as_tar_gz(tmp_path)

    def test_rejects_external_file_symlink(self, tmp_path: Path) -> None:
        source = tmp_path / "source"
        source.mkdir()
        outside = tmp_path / "outside.bin"
        outside.write_bytes(b"secret")
        (source / "model.bin").symlink_to(outside)

        with pytest.raises(ValueError, match="symlink escapes staging directory"):
            model_cache._package_directory_as_tar_gz(source)

    def test_rejects_directory_symlink(self, tmp_path: Path) -> None:
        source = tmp_path / "source"
        source.mkdir()
        target = source / "real-directory"
        target.mkdir()
        (target / "model.bin").write_bytes(b"model")
        (source / "linked-directory").symlink_to(target, target_is_directory=True)

        with pytest.raises(ValueError, match="symlink target is not a regular file"):
            model_cache._package_directory_as_tar_gz(source)

    def test_rejects_broken_file_symlink(self, tmp_path: Path) -> None:
        source = tmp_path / "source"
        source.mkdir()
        (source / "model.bin").symlink_to(source / "missing.bin")

        with pytest.raises(ValueError, match="symlink is broken"):
            model_cache._package_directory_as_tar_gz(source)

    def test_archive_limit_counts_dereferenced_symlink_bytes(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        source = tmp_path / "source"
        source.mkdir()
        blob = source / "blob"
        blob.write_bytes(b"x" * 9)
        (source / "model.bin").symlink_to(blob)
        monkeypatch.setattr(model_cache, "_MAX_EXTRACTED_BYTES", 17)

        with pytest.raises(ValueError, match="Model directory size 18 exceeds extracted limit 17"):
            model_cache._package_directory_as_tar_gz(source)
