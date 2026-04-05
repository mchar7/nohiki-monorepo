"""Download and cache ML models with S3 as shared storage and Redis lock coordination.

On startup, ml-compute-service calls ``ModelCacheManager.ensure_models_available()``
which:

1. Checks if models matching the current manifest hash are already cached locally.
2. Acquires a Redis distributed lock (so only one pod acts at a time).
3. For each model archive declared in the manifest:
   a. If the archive exists in S3 → download and extract to local cache.
   b. If the archive is **missing** from S3 → download from the upstream source
      (HuggingFace Hub / PyPI) via a caller-provided callback, package as tar.gz,
      upload to S3 for other pods, then extract locally.
4. Writes a version marker so subsequent startups skip all of the above.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import shutil
import stat
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from nohiki_observability import get_logger

if TYPE_CHECKING:
    from nohiki_ml_manifest import SemanticRepresentationManifest
    from nohiki_redis_utils import RedisCache
    from nohiki_s3_client import S3Client

logger = get_logger(__name__)

_LOCK_TTL_SECONDS = 600
_LOCK_TIMEOUT_SECONDS = 300
_VERSION_MARKER = ".cache_version"
_MAX_ARCHIVE_BYTES = 1 * 1024 * 1024 * 1024
_MAX_EXTRACTED_BYTES = 8 * 1024 * 1024 * 1024
_MAX_ARCHIVE_MEMBERS = 100_000


class SourceDownloader(Protocol):
    """Protocol for downloading a model from its upstream source.

    Implementations receive a ``ModelArchive`` and a temporary directory.
    They must download the model files into ``target_dir`` so that the
    directory can be packaged into a tar.gz archive and uploaded to S3.

    The implementation lives in the calling service (e.g. ml-compute-service)
    because it depends on heavy optional libraries (pylate, sentence-transformers,
    fastembed) that are not available in nohiki-ml-core itself.
    """

    async def __call__(self, archive: ModelArchive, target_dir: Path) -> None:
        """Download model files for *archive* into *target_dir*."""
        ...


@dataclass(frozen=True, slots=True)
class ModelArchive:
    """Describes a model archive and how to obtain it.

    Attributes:
        s3_key: Object key in the shared S3 bucket.
        extract_dir: Subdirectory under the local cache root to extract into
            (e.g. ``"huggingface"`` or ``"fastembed"``).
        model_id: Upstream model identifier (HuggingFace repo ID or PyPI model name).
        revision: Optional pinned upstream revision (typically a commit SHA).

    """

    s3_key: str
    extract_dir: str
    model_id: str
    revision: str | None = None


def _compute_manifest_hash(manifest: SemanticRepresentationManifest) -> str:
    """Compute a stable hash from every manifest field that can affect artifacts."""
    dumped = manifest.model_dump(mode="json")
    if isinstance(dumped, dict):
        content = json.dumps(dumped, sort_keys=True, separators=(",", ":"))
    else:  # Supports lightweight manifest test doubles.
        content = "|".join(
            [
                manifest.late_interaction.model_id,
                manifest.sparse.model_id,
                manifest.dense.model_id,
                str(manifest.late_interaction.token_dim),
                str(manifest.dense.embedding_dim),
            ]
        )
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def _model_revision(config: object) -> str | None:
    """Return a configured upstream pin without treating test doubles as values."""
    for field in ("revision", "pinned_revision", "commit_hash"):
        revision = getattr(config, field, None)
        if isinstance(revision, str) and revision:
            return revision
    return None


def _default_model_archives(manifest: SemanticRepresentationManifest) -> list[ModelArchive]:
    """Build archives keyed only by each upstream artifact's identity.

    The broader manifest hash remains a local compatibility marker, but must not
    create duplicate S3 objects when unrelated manifest settings change.
    """
    late = manifest.late_interaction
    dense = manifest.dense
    sparse = manifest.sparse
    archives = (
        ("colbert", late, "huggingface"),
        ("dense", dense, "huggingface"),
        ("sparse", sparse, "fastembed"),
    )
    result: list[ModelArchive] = []
    for kind, config, extract_dir in archives:
        model_id = config.model_id
        revision = _model_revision(config)
        revision_suffix = f"/{revision}" if revision is not None else ""
        result.append(
            ModelArchive(
                s3_key=f"models/{kind}/{model_id}{revision_suffix}/model.tar.gz",
                extract_dir=extract_dir,
                model_id=model_id,
                revision=revision,
            )
        )
    return result


def _validate_file_symlink(path: Path, root: Path) -> None:
    try:
        target = path.resolve(strict=True)
    except (FileNotFoundError, RuntimeError) as exc:
        msg = f"Model staging symlink is broken: {path}"
        raise ValueError(msg) from exc
    if not target.is_relative_to(root):
        msg = f"Model staging symlink escapes staging directory: {path}"
        raise ValueError(msg)
    if not stat.S_ISREG(target.stat().st_mode):
        msg = f"Model staging symlink target is not a regular file: {path}"
        raise ValueError(msg)


def _regular_tree_entries(source_dir: Path) -> list[Path]:
    """Return a contained tree, allowing only file symlinks that stay within it."""
    root_stat = source_dir.lstat()
    if not stat.S_ISDIR(root_stat.st_mode):
        msg = f"Model staging root is not a directory: {source_dir}"
        raise ValueError(msg)
    root = source_dir.resolve(strict=True)
    entries: list[Path] = []

    def visit(directory: Path) -> None:
        with os.scandir(directory) as children:
            for child in sorted(children, key=lambda entry: entry.name):
                path = Path(child.path)
                mode = child.stat(follow_symlinks=False).st_mode
                if stat.S_ISLNK(mode):
                    _validate_file_symlink(path, root)
                elif not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                    msg = f"Model staging entry is not a regular file or directory: {path}"
                    raise ValueError(msg)
                elif not path.resolve(strict=True).is_relative_to(root):
                    msg = f"Model staging entry escapes staging directory: {path}"
                    raise ValueError(msg)
                entries.append(path)
                if stat.S_ISDIR(mode):
                    visit(path)

    visit(source_dir)
    return entries


def _package_directory_as_tar_gz(source_dir: Path) -> bytes:
    """Package a validated directory's contents into an in-memory tar.gz archive."""
    entries = _regular_tree_entries(source_dir)
    source_bytes = sum(path.stat().st_size for path in entries if not path.is_dir())
    if source_bytes > _MAX_EXTRACTED_BYTES:
        msg = f"Model directory size {source_bytes} exceeds extracted limit {_MAX_EXTRACTED_BYTES}"
        raise ValueError(msg)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz", dereference=True) as tar:
        for item in entries:
            tar.add(item, arcname=item.relative_to(source_dir), recursive=False)
    result = buf.getvalue()
    if len(result) > _MAX_ARCHIVE_BYTES:
        msg = f"Model archive size {len(result)} exceeds limit {_MAX_ARCHIVE_BYTES}"
        raise ValueError(msg)
    return result


def _move_directory(source: Path, target: Path) -> None:
    if target.is_symlink():
        msg = f"Model cache target is a symlink: {target}"
        raise ValueError(msg)
    target.mkdir(parents=True, exist_ok=True)
    for item in sorted(source.iterdir()):
        dst = target / item.name
        if dst.is_symlink():
            msg = f"Model cache target collision is a symlink: {dst}"
            raise ValueError(msg)
        if item.is_dir():
            if dst.exists() and not dst.is_dir():
                dst.unlink()
            _move_directory(item, dst)
        else:
            if dst.is_dir():
                shutil.rmtree(dst)
            elif dst.exists():
                dst.unlink()
            shutil.move(str(item), dst)
    source.rmdir()


def _merge_directory(source_dir: Path, target_dir: Path) -> None:
    """Dereference staged file links, then move the validated tree into the cache."""
    entries = _regular_tree_entries(source_dir)
    for path in entries:
        if path.is_symlink():
            target = path.resolve(strict=True)
            path.unlink()
            os.link(target, path)
    _move_directory(source_dir, target_dir)


class ModelCacheManager:
    """Download and cache ML models with S3 as shared storage.

    The manager implements a three-tier caching strategy:

    1. **Local disk**: fastest, checked first via a version marker file.
    2. **S3 bucket**: shared across pods, checked under Redis lock.
    3. **Upstream source**: HuggingFace Hub / PyPI, used only when S3
       doesn't have the archive yet (first-ever deployment or model change).

    A Redis distributed lock ensures only one pod downloads at a time.
    Other pods wait for the lock holder to finish, then verify the local cache.

    Args:
        s3_client: Async S3 client for model archive storage.
        redis_cache: Redis cache for distributed locking across pods.
        cache_dir: Local directory for cached models.
        manifest: Semantic representation manifest defining which models to use.
        source_downloader: Callback that downloads a model from its upstream
            source into a temporary directory. Required so that this class
            does not depend on heavy ML libraries directly.

    """

    def __init__(
        self,
        s3_client: S3Client,
        redis_cache: RedisCache,
        cache_dir: Path,
        manifest: SemanticRepresentationManifest,
        source_downloader: SourceDownloader,
    ) -> None:
        """Initialize the model cache manager."""
        self._s3 = s3_client
        self._redis = redis_cache
        self._cache_dir = cache_dir
        self._manifest = manifest
        self._source_downloader = source_downloader
        self._manifest_hash = _compute_manifest_hash(manifest)
        self._archives = _default_model_archives(manifest)
        self._write_lock = asyncio.Lock()

    @property
    def manifest_hash(self) -> str:
        """Current manifest hash used for cache invalidation."""
        return self._manifest_hash

    def _is_cache_valid(self) -> bool:
        """Check if local cache matches the current manifest hash."""
        marker = self._cache_dir / _VERSION_MARKER
        if not marker.exists():
            return False
        return marker.read_text().strip() == self._manifest_hash

    def _write_version_marker(self) -> None:
        """Write the manifest hash to the version marker file."""
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        marker = self._cache_dir / _VERSION_MARKER
        marker.write_text(self._manifest_hash)

    def _clear_managed_cache(self) -> None:
        """Remove only cache paths owned by the configured model archives."""
        if self._cache_dir.is_symlink():
            msg = f"Model cache root is a symlink: {self._cache_dir}"
            raise ValueError(msg)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        managed_paths = {
            *(self._cache_dir / archive.extract_dir for archive in self._archives),
            *(self._staging_dir(archive) for archive in self._archives),
            self._cache_dir / _VERSION_MARKER,
        }
        for path in sorted(managed_paths):
            if path.is_symlink() or path.is_file():
                path.unlink()
            elif path.exists():
                shutil.rmtree(path)

    async def ensure_models_available(self) -> None:
        """Ensure all models are available in the local cache.

        Flow:
            1. If local cache is valid (version marker matches) → return immediately.
            2. Acquire Redis distributed lock.
            3. Re-check local cache (another pod may have finished while we waited).
            4. For each model archive:
               a. If archive exists in S3 → download from S3 and extract locally.
               b. If archive is missing from S3 → download from upstream source,
                  package as tar.gz, upload to S3, then extract locally.
            5. Write version marker.

        Raises:
            DistributedLockError: If the lock cannot be acquired within timeout.
            S3ConnectionError: If S3 is unreachable.
            RuntimeError: If a model fails to download from its upstream source.

        """
        if self._is_cache_valid():
            logger.info(
                "Model cache is valid, skipping download",
                manifest_hash=self._manifest_hash,
                cache_dir=str(self._cache_dir),
            )
            return

        logger.info(
            "Model cache invalid or missing, acquiring lock for download",
            manifest_hash=self._manifest_hash,
        )

        async with self._redis.distributed_lock(
            f"model-download-{self._manifest_hash}",
            ttl_seconds=_LOCK_TTL_SECONDS,
            timeout_seconds=_LOCK_TIMEOUT_SECONDS,
        ):
            if self._is_cache_valid():
                logger.info("Another pod already downloaded models, cache is now valid")
                return

            logger.info(
                "Clearing invalid managed model cache before rebuild",
                manifest_hash=self._manifest_hash,
                cache_dir=str(self._cache_dir),
            )
            async with self._write_lock:
                await asyncio.to_thread(self._clear_managed_cache)
            try:
                await self._populate_all_models()
                self._write_version_marker()
            except BaseException:
                async with self._write_lock:
                    await asyncio.to_thread(self._clear_managed_cache)
                raise

        logger.info(
            "All models downloaded and cached",
            manifest_hash=self._manifest_hash,
            cache_dir=str(self._cache_dir),
        )

    async def _populate_all_models(self) -> None:
        """Ensure every model archive is in S3 and extracted locally."""
        async with asyncio.TaskGroup() as tg:
            for archive in self._archives:
                tg.create_task(self._ensure_archive(archive))

    async def _ensure_archive(self, archive: ModelArchive) -> None:
        """Ensure a single model archive is available locally.

        If the archive exists in S3, download and extract it.
        If not, download from the upstream source, package, upload to S3,
        then extract locally.
        """
        target_dir = self._cache_dir / archive.extract_dir
        target_dir.mkdir(parents=True, exist_ok=True)

        if await self._s3.object_exists(archive.s3_key):
            logger.info("Model archive found in S3, downloading", s3_key=archive.s3_key)
            await self._download_and_extract_from_s3(archive, target_dir)
        else:
            logger.info(
                "Model archive not in S3, downloading from upstream source",
                s3_key=archive.s3_key,
                model_id=archive.model_id,
            )
            await self._download_from_source_and_upload(archive, target_dir)

    async def _download_and_extract_from_s3(self, archive: ModelArchive, target_dir: Path) -> None:
        """Download an archive from S3, then serialize extraction into its target."""
        data = await self._s3.get_object(archive.s3_key, max_bytes=_MAX_ARCHIVE_BYTES)
        staging_dir = self._staging_dir(archive)

        async with self._write_lock:
            shutil.rmtree(staging_dir, ignore_errors=True)
            staging_dir.mkdir(parents=True)
            try:
                await asyncio.to_thread(self._extract_tar_gz, data, staging_dir)
                await asyncio.to_thread(_merge_directory, staging_dir, target_dir)
            finally:
                shutil.rmtree(staging_dir, ignore_errors=True)

        logger.info(
            "Model archive extracted from S3",
            s3_key=archive.s3_key,
            target_dir=str(target_dir),
        )

    def _staging_dir(self, archive: ModelArchive) -> Path:
        """Return the stable per-archive staging directory."""
        digest = hashlib.sha256(archive.s3_key.encode()).hexdigest()[:12]
        return self._cache_dir / f".staging-{digest}"

    async def _download_from_source_and_upload(self, archive: ModelArchive, target_dir: Path) -> None:
        """Download from upstream source, package, upload to S3, extract locally.

        Downloads land in a per-archive staging directory: archives can share
        ``extract_dir``, and packaging a live shared directory races sibling
        downloads (torn reads) and leaks their files into the uploaded archive.

        Args:
            archive: Model archive to populate.
            target_dir: Shared extraction directory the staged files merge into.
        """
        staging_dir = self._staging_dir(archive)
        try:
            async with self._write_lock:
                shutil.rmtree(staging_dir, ignore_errors=True)
                staging_dir.mkdir(parents=True)
            await self._source_downloader(archive, staging_dir)

            logger.info(
                "Packaging model archive for S3 upload",
                s3_key=archive.s3_key,
                source_dir=str(staging_dir),
            )
            archive_bytes = await asyncio.to_thread(_package_directory_as_tar_gz, staging_dir)

            await self._s3.put_object(
                archive.s3_key,
                archive_bytes,
                content_type="application/gzip",
            )
            logger.info(
                "Model archive uploaded to S3",
                s3_key=archive.s3_key,
                size_bytes=len(archive_bytes),
            )

            async with self._write_lock:
                await asyncio.to_thread(_merge_directory, staging_dir, target_dir)
        finally:
            shutil.rmtree(staging_dir, ignore_errors=True)

    @staticmethod
    def _extract_tar_gz(data: bytes, target_dir: Path) -> None:
        """Extract a tar.gz archive into the target directory (sync, for to_thread)."""
        if len(data) > _MAX_ARCHIVE_BYTES:
            msg = f"Model archive size {len(data)} exceeds limit {_MAX_ARCHIVE_BYTES}"
            raise ValueError(msg)
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            members = tar.getmembers()
            if len(members) > _MAX_ARCHIVE_MEMBERS:
                msg = f"Model archive member count {len(members)} exceeds limit {_MAX_ARCHIVE_MEMBERS}"
                raise ValueError(msg)
            extracted_bytes = sum(member.size for member in members if member.isfile())
            if extracted_bytes > _MAX_EXTRACTED_BYTES:
                msg = f"Extracted model size {extracted_bytes} exceeds limit {_MAX_EXTRACTED_BYTES}"
                raise ValueError(msg)
            tar.extractall(path=target_dir, members=members, filter="data")
