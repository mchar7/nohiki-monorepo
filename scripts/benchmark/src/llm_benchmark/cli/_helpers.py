"""Shared CLI helper utilities.

Provides common functionality used across multiple CLI commands:
API key loading, result file discovery, fixture checksums, and
timestamped snapshot management.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import typer
from nohiki_llm_client import (
    ApiKeyRegistry,
    LLMModelConfig,
    LLMProviderSettings,
    LLMSettings,
    resolve_chain,
)
from nohiki_llm_client.config.constants import (
    API_KEY_OPTIONAL_PROVIDERS,
    KEYLESS_PROVIDERS,
)
from pydantic import ValidationError

from llm_benchmark.config.constants import MAX_SNAPSHOTS
from llm_benchmark.display.console import console
from llm_benchmark.paths import get_api_keys_dir, get_results_dir
from llm_benchmark.schemas.metrics import BenchmarkResult

_VALIDATION_KEY_PLACEHOLDER = "unused-benchmark-validation-placeholder"


def _provider_needs_registry_key(model: str, base_url: str | None) -> bool:
    """Return whether a model requires a provider-registry key."""
    provider = model.partition(":")[0]
    if provider in KEYLESS_PROVIDERS or provider in API_KEY_OPTIONAL_PROVIDERS:
        return False
    return not (provider == "openai" and base_url is not None)


def _group_model_specs(group: object) -> list[tuple[str, str | None]]:
    """Extract model and endpoint pairs from a raw provider group."""
    if not isinstance(group, dict) or not isinstance(models := group.get("models"), list):
        return []
    specs: list[tuple[str, str | None]] = []
    for entry in models:
        if not isinstance(entry, dict):
            continue
        base_url = entry.get("base_url")
        specs.append(
            (
                str(entry.get("model", "")),
                base_url if isinstance(base_url, str) else None,
            )
        )
    return specs


def _referenced_key_providers(payload: dict[str, object]) -> set[str]:
    """Return providers needing placeholders for whole-document validation."""
    groups: list[object] = [payload.get("provider")]
    if isinstance(chains := payload.get("chains"), dict):
        groups.extend(chains.values())
    return {
        model.partition(":")[0]
        for group in groups
        for model, base_url in _group_model_specs(group)
        if _provider_needs_registry_key(model, base_url)
    }


def _contains_credentials(value: object) -> bool:
    """Return whether parsed settings contain a forbidden embedded credential."""
    if isinstance(value, dict):
        return any(
            key == "api_key" or (key == "api_keys" and bool(item)) or _contains_credentials(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_credentials(item) for item in value)
    return False


def load_credential_free_chain(
    path: Path,
    chain: str | None,
    api_keys: ApiKeyRegistry,
) -> tuple[tuple[LLMModelConfig, ...], LLMProviderSettings]:
    """Load and resolve a credential-free standard LLM settings chain."""
    raw: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        msg = "LLMSettings JSON must define a top-level object"
        raise TypeError(msg)
    payload = cast("dict[str, object]", raw)
    if _contains_credentials(payload):
        msg = "LLMSettings JSON must not contain API keys; use the existing secret registry"
        raise typer.BadParameter(msg, param_hint="--llm-settings")

    key_values = dict.fromkeys(_referenced_key_providers(payload), _VALIDATION_KEY_PLACEHOLDER)
    provider = payload.setdefault("provider", {})
    if not isinstance(provider, dict):
        msg = "LLMSettings provider must be an object"
        raise TypeError(msg)
    cast("dict[str, object]", provider)["api_keys"] = key_values
    validated = LLMSettings.model_validate(payload)
    resolved = resolve_chain(chain, validated)

    runtime_data = resolved.model_dump(exclude={"api_keys"})
    runtime_data["api_keys"] = api_keys
    runtime = LLMProviderSettings.model_validate(runtime_data)
    return tuple(runtime.models), runtime


def load_api_keys() -> ApiKeyRegistry:
    """Load provider API keys from the canonical secrets directory.

    Each file in the directory is named after its provider (e.g., ``openrouter``,
    ``openai``) and contains the raw API key string.

    Returns:
        Populated ``ApiKeyRegistry`` with all discovered provider keys.

    Raises:
        typer.Exit: If the keys directory does not exist or contains no key files.
    """
    keys_dir = get_api_keys_dir()
    if not keys_dir.exists():
        console.print(f"[red]Error:[/red] API keys directory not found: {keys_dir}")
        raise typer.Exit(code=1)
    raw = {f.name: f.read_text().strip() for f in keys_dir.iterdir() if f.is_file()}
    if not raw:
        console.print(f"[red]Error:[/red] No API key files found in: {keys_dir}")
        raise typer.Exit(code=1)
    return ApiKeyRegistry.model_validate(raw)


def load_api_keys_optional() -> ApiKeyRegistry:
    """Load the canonical provider key registry only when it is available.

    Unlike :func:`load_api_keys`, a missing or empty secret directory is not an
    error: it yields an empty registry so keyless-capable custom endpoints (e.g.
    a localhost OpenAI-compatible proxy) still dispatch. When the canonical
    registry exists and holds keys, they are returned so an available provider
    key (e.g. OpenAI) is used automatically. Never exposes key values.

    Returns:
        Populated ``ApiKeyRegistry`` when the canonical directory has key files,
        otherwise an empty ``ApiKeyRegistry``.
    """
    keys_dir = get_api_keys_dir()
    if not keys_dir.exists() or not any(f.is_file() for f in keys_dir.iterdir()):
        return ApiKeyRegistry()
    return load_api_keys()


def load_benchmark_result(path: Path) -> BenchmarkResult:
    """Load and validate a benchmark result for a CLI command."""
    try:
        return BenchmarkResult.load(path)
    except (json.JSONDecodeError, ValidationError, OSError) as exc:
        console.print(f"[red]Error:[/red] Invalid benchmark result: {type(exc).__name__}")
        raise typer.Exit(code=1) from exc


def get_default_output_path() -> Path:
    """Return the default benchmark output path (time-insensitive).

    Returns:
        Path ``<results_dir>/benchmark.json``.
    """
    return get_results_dir() / "benchmark.json"


def find_latest_result() -> Path | None:
    """Find the most recently saved benchmark result file.

    Prefers the canonical ``benchmark.json`` when present, then falls back to
    the most recently modified timestamped file.

    Returns:
        Path to latest result file, or None if no results exist.
    """
    results_dir = get_results_dir()
    results_dir.mkdir(parents=True, exist_ok=True)
    canonical = results_dir / "benchmark.json"
    if canonical.exists():
        return canonical
    results = sorted(
        (
            path
            for path in results_dir.glob("benchmark_*.json")
            if not path.name.endswith((".eval.json", ".eval.checkpoint.json"))
        ),
        key=lambda path: path.stat().st_mtime,
    )
    return results[-1] if results else None


def save_timestamped_snapshot(
    result: BenchmarkResult,
    output_path: Path,
    *,
    keep_last: int = MAX_SNAPSHOTS,
) -> Path:
    """Save an immutable timestamped snapshot alongside the canonical output file.

    Saves to ``{stem}_{YYYYMMDD_HHMMSS}.json`` in the same directory, then prunes
    old snapshots so at most ``keep_last`` timestamped files are retained.

    Args:
        result: Complete benchmark result to snapshot.
        output_path: Canonical output path (e.g. ``benchmark.json``).
        keep_last: Maximum number of timestamped snapshots to retain.

    Returns:
        Path of the newly written snapshot file.
    """
    if keep_last < 1:
        msg = "keep_last must be at least 1"
        raise ValueError(msg)
    try:
        ts = datetime.fromisoformat(result.timestamp)
    except ValueError:
        ts = datetime.now(UTC)
    ts = ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts.astimezone(UTC)
    stamp = ts.strftime("%Y%m%d_%H%M%S")
    snapshot_path = output_path.parent / f"{output_path.stem}_{stamp}.json"
    sequence = 2
    while snapshot_path.exists():
        snapshot_path = output_path.parent / f"{output_path.stem}_{stamp}_{sequence}.json"
        sequence += 1
    result.save(snapshot_path)
    existing = sorted(output_path.parent.glob(f"{output_path.stem}_*.json"), reverse=True)
    for old in existing[keep_last:]:
        old.unlink(missing_ok=True)
    return snapshot_path
