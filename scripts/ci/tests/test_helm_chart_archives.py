"""Contracts for committed local Helm dependency archives."""

from __future__ import annotations

import tarfile
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[3]
_CHART = _ROOT / "infra" / "k8s" / "helm"


def _local_charts() -> tuple[tuple[str, Path], ...]:
    metadata = yaml.safe_load((_CHART / "Chart.yaml").read_text(encoding="utf-8"))
    return tuple(
        sorted(
            (
                dependency["name"],
                (_CHART / dependency["repository"].removeprefix("file://")).resolve(),
            )
            for dependency in metadata["dependencies"]
            if dependency["repository"].startswith("file://")
        )
    )


@pytest.mark.parametrize(
    ("name", "source"),
    _local_charts(),
    ids=lambda value: value if isinstance(value, str) else None,
)
def test_packaged_local_chart_templates_match_source(name: str, source: Path) -> None:
    metadata = yaml.safe_load((source / "Chart.yaml").read_text(encoding="utf-8"))
    assert metadata["name"] == name

    archive_path = _CHART / "charts" / f"{name}-{metadata['version']}.tgz"
    assert archive_path.is_file(), f"{name}: missing packaged local dependency"

    source_templates = {
        path.relative_to(source).as_posix(): path.read_bytes()
        for path in (source / "templates").rglob("*")
        if path.is_file()
    }
    with tarfile.open(archive_path, mode="r:gz") as archive:
        prefix = f"{name}/"
        archived_files = {
            member.name.removeprefix(prefix): extracted.read()
            for member in archive.getmembers()
            if member.isfile()
            and member.name.startswith(prefix)
            and (extracted := archive.extractfile(member)) is not None
        }

    archived_metadata = yaml.safe_load(archived_files["Chart.yaml"].decode("utf-8"))
    archived_templates = {path: body for path, body in archived_files.items() if path.startswith("templates/")}

    assert archived_metadata == metadata, f"{name}: packaged Chart.yaml differs from source"
    assert archived_templates.keys() == source_templates.keys(), f"{name}: packaged template set differs from source"
    for path, body in source_templates.items():
        assert archived_templates[path] == body, f"{name}: packaged {path} differs from source"
