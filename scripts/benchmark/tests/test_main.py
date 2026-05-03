"""Tests for __main__.py entry point."""

from __future__ import annotations

import runpy
from unittest.mock import patch


def test_main_invokes_cli() -> None:
    with patch("llm_benchmark.cli.main") as mock_main:
        runpy.run_module("llm_benchmark", run_name="__main__")
        mock_main.assert_called_once()
