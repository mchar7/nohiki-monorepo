"""Committed duration-balanced Python test batch assignments."""

import tomllib
from dataclasses import dataclass

from ci_checks.core.packages import REPO_ROOT

_BATCH_DATA = REPO_ROOT / "scripts" / "ci" / "python-test-batches.toml"


@dataclass(frozen=True, slots=True)
class TestBatch:
    """One Python test batch and its workspace requirements."""

    name: str
    packages: tuple[str, ...]
    needs_pnpm: bool


def load_test_batches() -> tuple[TestBatch, ...]:
    """Load and validate the committed Python test batch data."""
    data = tomllib.loads(_BATCH_DATA.read_text(encoding="utf-8"))
    raw_batches = data.get("batches")
    if not isinstance(raw_batches, list):
        msg = f"{_BATCH_DATA} must define [[batches]]"
        raise TypeError(msg)

    batches: list[TestBatch] = []
    for raw_batch in raw_batches:
        if not isinstance(raw_batch, dict):
            msg = "each Python test batch must be a table"
            raise TypeError(msg)
        name = raw_batch.get("name")
        packages = raw_batch.get("packages")
        needs_pnpm = raw_batch.get("needs_pnpm")
        if not isinstance(name, str) or not isinstance(needs_pnpm, bool):
            msg = "each Python test batch requires a string name and boolean needs_pnpm"
            raise TypeError(msg)
        if not isinstance(packages, list) or not all(isinstance(package, str) for package in packages):
            msg = f"Python test batch {name!r} requires a string package list"
            raise TypeError(msg)
        batches.append(TestBatch(name=name, packages=tuple(packages), needs_pnpm=needs_pnpm))

    if len(batches) != 3 or len({batch.name for batch in batches}) != 3:
        msg = "Python tests require exactly three uniquely named batches"
        raise ValueError(msg)
    return tuple(batches)
