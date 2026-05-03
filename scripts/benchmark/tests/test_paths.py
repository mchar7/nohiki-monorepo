"""Tests for portable path resolution utilities."""

from __future__ import annotations

from pathlib import Path

from llm_benchmark.paths import get_api_keys_dir, get_results_dir


class TestGetResultsDir:
    """Tests for get_results_dir function."""

    def test_returns_path_instance(self) -> None:
        result = get_results_dir()
        assert isinstance(result, Path)

    def test_path_ends_with_results(self) -> None:
        result = get_results_dir()
        assert result.name == "results"

    def test_path_under_benchmark_dir(self) -> None:
        result = get_results_dir()
        assert "benchmark" in str(result)

    def test_path_is_absolute(self) -> None:
        result = get_results_dir()
        assert result.is_absolute()


class TestGetApiKeysDir:
    """Tests for get_api_keys_dir function."""

    def test_returns_path_instance(self) -> None:
        result = get_api_keys_dir()
        assert isinstance(result, Path)

    def test_path_ends_with_api_keys_dir(self) -> None:
        result = get_api_keys_dir()
        assert result.name == "api_keys"

    def test_path_is_absolute(self) -> None:
        result = get_api_keys_dir()
        assert result.is_absolute()

    def test_path_under_infra_secrets(self) -> None:
        result = get_api_keys_dir()
        path_str = str(result)
        assert "infra" in path_str
        assert "secrets" in path_str

    def test_path_under_llm_provider(self) -> None:
        result = get_api_keys_dir()
        assert result.parent.name == "provider"
        assert result.parent.parent.name == "llm"
