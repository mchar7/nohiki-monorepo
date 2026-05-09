"""Dataset download utilities using git LFS.

Uses git clone with LFS support for reliable downloads
from HuggingFace datasets.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from job_embedding_finetuning.dataset_adapters.base import DatasetInfo, DatasetTier

if TYPE_CHECKING:
    from collections.abc import Sequence

GIT_CLONE_TIMEOUT_SECONDS = 6 * 60 * 60
GIT_LFS_CHECK_TIMEOUT_SECONDS = 10


class DownloadError(Exception):
    """Raised when a dataset download fails."""

    def __init__(self, dataset: str, message: str) -> None:
        """Initialize with dataset name and error message."""
        self.dataset = dataset
        super().__init__(f"Failed to download {dataset}: {message}")


def _target_path(info: DatasetInfo, data_dir: Path) -> Path:
    """Return a dataset path that is contained directly by the data root."""
    root = data_dir.resolve()
    target = (root / info.local_dir_name).resolve()
    if not info.local_dir_name or target.parent != root:
        raise DownloadError(info.name, f"invalid local directory name: {info.local_dir_name!r}")
    return target


def _remove_path(path: Path) -> None:
    """Remove a file, symlink, or directory without following symlinks."""
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def _is_complete_clone(path: Path) -> bool:
    """Return whether a prior git clone completed successfully."""
    return path.is_dir() and not path.is_symlink() and (path / ".git").is_dir()


def _run_git_clone(repo_url: str, target_dir: Path) -> subprocess.CompletedProcess[str]:
    """Run git clone command for a HuggingFace repository.

    Args:
        repo_url: HuggingFace dataset repository URL.
        target_dir: Local directory to clone into.

    Returns:
        CompletedProcess result.

    Raises:
        subprocess.TimeoutExpired: If the clone exceeds the time limit.
    """
    cmd = ["git", "clone", repo_url, str(target_dir)]

    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
        timeout=GIT_CLONE_TIMEOUT_SECONDS,
    )


def _check_clone_result(result: subprocess.CompletedProcess[str], dataset: str) -> None:
    """Raise when git clone did not complete successfully."""
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or f"git exited with {result.returncode}"
        raise DownloadError(dataset, message)


def download_dataset(
    info: DatasetInfo,
    data_dir: Path,
    *,
    force: bool = False,
) -> bool:
    """Download a single dataset using git LFS.

    Args:
        info: Dataset metadata.
        data_dir: Root directory for downloaded datasets.
        force: If True, re-download even if already present.

    Returns:
        True when a new clone was installed, False when a complete clone was
        already present.

    Raises:
        DownloadError: If the download fails.

    """
    target_dir = _target_path(info, data_dir)

    if _is_complete_clone(target_dir) and not force:
        return False

    data_dir = target_dir.parent
    data_dir.mkdir(parents=True, exist_ok=True)
    staging_dir = data_dir / f".{info.local_dir_name}.download"
    _remove_path(staging_dir)

    hf_url = f"https://huggingface.co/datasets/{info.hf_repo}"
    try:
        result = _run_git_clone(hf_url, staging_dir)
        _check_clone_result(result, info.name)

        _remove_path(target_dir)
        staging_dir.replace(target_dir)
    except subprocess.TimeoutExpired as error:
        _remove_path(staging_dir)
        raise DownloadError(info.name, f"clone timed out after {GIT_CLONE_TIMEOUT_SECONDS} seconds") from error
    except BaseException:
        _remove_path(staging_dir)
        raise

    return True


def download_datasets_by_tier(
    datasets: Sequence[DatasetInfo],
    data_dir: Path,
    *,
    force: bool = False,
) -> dict[str, bool]:
    """Download multiple datasets.

    Args:
        datasets: Sequence of dataset metadata to download.
        data_dir: Root directory for downloaded datasets.
        force: If True, re-download even if already present.

    Returns:
        Dictionary mapping dataset names to successful availability.

    """
    results: dict[str, bool] = {}

    for info in datasets:
        try:
            download_dataset(info, data_dir, force=force)
            results[info.name] = True
        except DownloadError:
            results[info.name] = False

    return results


def check_git_lfs() -> bool:
    """Check if git-lfs is installed and configured.

    Returns:
        True if git-lfs is available.

    """
    try:
        result = subprocess.run(
            ["git", "lfs", "version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=GIT_LFS_CHECK_TIMEOUT_SECONDS,
        )
    except OSError, subprocess.SubprocessError:
        return False
    return result.returncode == 0


def get_download_status(data_dir: Path, datasets: Sequence[DatasetInfo]) -> dict[str, bool]:
    """Get download status for a list of datasets.

    Args:
        data_dir: Root directory for downloaded datasets.
        datasets: Sequence of dataset metadata to check.

    Returns:
        Dictionary mapping dataset names to download status.

    """
    status: dict[str, bool] = {}

    for info in datasets:
        target_dir = _target_path(info, data_dir)
        status[info.name] = _is_complete_clone(target_dir)

    return status


def get_tier_datasets(tier: DatasetTier) -> list[DatasetInfo]:
    """Get all dataset infos for a specific tier.

    This function should be called after adapters are imported
    to ensure the registry is populated.

    Args:
        tier: The dataset tier to filter by.

        Downloadable DatasetInfo entries for the specified tier.

    """
    from job_embedding_finetuning.dataset_adapters.registry import list_datasets_by_tier

    return [info for info in list_datasets_by_tier(tier) if info.hf_repo != "local"]
