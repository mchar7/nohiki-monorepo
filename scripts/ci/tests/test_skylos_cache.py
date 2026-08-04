"""Contracts for the thin Skylos cache-retention adapter."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from ci_checks.checks import skylos_cache as skylos_cache_check


@pytest.mark.requires_skylos
def test_pinned_skylos_invalidates_warm_grep_when_caller_changes(
    tmp_path: Path,
) -> None:
    from skylos.core.grep_cache import GrepCache
    from skylos.core.grep_verify import grep_verify_findings

    definition = tmp_path / "definition.py"
    usage = tmp_path / "usage.py"
    definition.write_text("def target():\n    return 1\n", encoding="utf-8")
    usage.write_text("value = 1\n", encoding="utf-8")
    finding = {
        "name": "target",
        "simple_name": "target",
        "full_name": "definition.target",
        "type": "function",
        "file": str(definition),
        "line": 1,
        "confidence": 80,
    }
    cache = GrepCache()

    before = grep_verify_findings([finding], str(tmp_path), cache=cache)
    usage.write_text(
        "from definition import target\n\ntarget()\n",
        encoding="utf-8",
    )
    after = grep_verify_findings([finding], str(tmp_path), cache=cache)

    assert "definition.target" not in before
    assert after["definition.target"].alive is True


@pytest.mark.requires_skylos
def test_static_cache_pruning_bounds_entries_after_scan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from skylos import cli as skylos_cli

    static_cache = tmp_path / ".skylos" / "cache" / "runs" / "v1" / "static"
    static_cache.mkdir(parents=True)
    manifest = static_cache / "stat-manifest.json"
    manifest.write_text("{}\n", encoding="utf-8")
    entries = [static_cache / f"head-{index}.cache" for index in range(4)]
    for index, entry in enumerate(entries):
        entry.write_text(str(index), encoding="utf-8")
        os.utime(entry, ns=(index, index))

    def finish_scan() -> None:
        raise SystemExit(1)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SKYLOS_CACHE_DIR", str(tmp_path / ".skylos"))
    monkeypatch.setattr(skylos_cli, "main", finish_scan)

    with pytest.raises(SystemExit, match="1"):
        skylos_cache_check.main()

    assert sorted(path.name for path in static_cache.glob("*.cache")) == [
        "head-2.cache",
        "head-3.cache",
    ]
    assert manifest.is_file()


@pytest.mark.requires_skylos
def test_static_cache_pruning_failure_blocks_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from skylos import cli as skylos_cli

    static_cache = tmp_path / ".skylos" / "cache" / "runs" / "v1" / "static"
    static_cache.mkdir(parents=True)
    entries = [static_cache / f"head-{index}.cache" for index in range(3)]
    for index, entry in enumerate(entries):
        entry.write_text(str(index), encoding="utf-8")
        os.utime(entry, ns=(index, index))

    def finish_scan() -> None:
        raise SystemExit(1)

    def fail_unlink(_path: Path) -> None:
        message = "read-only cache"
        raise OSError(message)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SKYLOS_CACHE_DIR", str(tmp_path / ".skylos"))
    monkeypatch.setattr(skylos_cli, "main", finish_scan)
    monkeypatch.setattr(Path, "unlink", fail_unlink)

    with pytest.raises(SystemExit) as raised:
        skylos_cache_check.main()

    assert raised.value.code == 2
    assert "Skylos static cache pruning failed: read-only cache" in capsys.readouterr().err
