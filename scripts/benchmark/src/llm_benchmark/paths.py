"""Portable path resolution for the benchmark suite.

Uses centralized path resolution from nohiki_test_utils, which uses PROJECT_ROOT
env var (set by direnv/.envrc) when available, falling back to uv workspace marker
file discovery. All benchmark paths are derived from the resolved monorepo root.
"""

from __future__ import annotations

from pathlib import Path

from nohiki_test_utils import get_repo_root


def get_results_dir() -> Path:
    """Get the path to the benchmark results directory.

    Returns:
        Absolute path to the results directory.
    """
    return get_repo_root() / "scripts" / "benchmark" / "results"


def get_api_keys_dir() -> Path:
    """Get the path to the provider API key secrets directory.

    Each file in this directory is named after its provider (e.g., ``openrouter``,
    ``openai``) and contains the raw API key string.  This mirrors the shared
    secrets layout used by Docker Compose and Kubernetes.

    Returns:
        Absolute path to ``infra/shared/secrets/llm/provider/api_keys/``.
    """
    return get_repo_root() / "infra" / "shared" / "secrets" / "llm" / "provider" / "api_keys"
