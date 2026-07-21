from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from ci_checks.core.image_inventory import (
    affected_images,
    image_names,
    load_inventory,
    matrix,
    read_affected_record,
    write_affected_record,
)

_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _ROOT / "scripts" / "ci" / "image_matrix.py"


def test_inventory_is_complete_unique_and_owned() -> None:
    images = load_inventory()
    names = image_names(images)
    assert len(names) == len(set(names)) == 27
    assert all(image["ownership"] for image in images)
    assert all((_ROOT / str(image["dockerfile"])).is_file() for image in images)
    assert matrix(images)["include"] == [
        {
            "name": image["name"],
            "context": image["context"],
            "dockerfile": image["dockerfile"],
            "build_args": image["build_args"],
            "timeout_minutes": image["timeout"],
        }
        for image in images
    ]


def test_ownership_is_data_driven_and_unmatched_paths_fail_closed() -> None:
    images = load_inventory()
    all_names = image_names(images)
    assert affected_images({"backend/services/user-auth-service/src/app.py"}, images) == ["user-auth-service"]
    backend_names = affected_images({"backend/libs/nohiki-common/src/value.py"}, images)
    assert "user-auth-service" in backend_names
    assert "sys-tick-job" in backend_names
    assert "frontend" not in backend_names
    assert affected_images({"unmapped/synthetic.file"}, images) == all_names
    assert (
        affected_images(
            {
                "backend/services/user-auth-service/src/app.py",
                "unmapped/synthetic.file",
            },
            images,
        )
        == all_names
    )


def test_affected_artifact_schema_and_sha_select_matrix(tmp_path: Path) -> None:
    images = load_inventory()
    artifact = tmp_path / "affected-images.json"
    write_affected_record(artifact, "a" * 40, ["frontend", "kafka-connect"])
    assert json.loads(artifact.read_text(encoding="utf-8")) == {
        "head_sha": "a" * 40,
        "images": ["frontend", "kafka-connect"],
    }
    selected = read_affected_record(artifact, "a" * 40, images)
    assert [entry["name"] for entry in matrix(images, selected)["include"]] == [
        "frontend",
        "kafka-connect",
    ]

    with pytest.raises(ValueError, match="head_sha"):
        read_affected_record(artifact, "b" * 40, images)


def test_matrix_emitter_fails_closed_on_missing_or_invalid_artifact(
    tmp_path: Path,
) -> None:
    images = load_inventory()
    invalid = tmp_path / "affected-images.json"
    invalid.write_text('{"head_sha":"bad","images":[]}', encoding="utf-8")
    for artifact in (tmp_path / "missing.json", invalid):
        result = subprocess.run(
            [
                sys.executable,
                str(_SCRIPT),
                "matrix",
                "--artifact",
                str(artifact),
                "--source-sha",
                "a" * 40,
            ],
            cwd=_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0
        assert json.loads(result.stdout) == matrix(images)
        assert "building the full image inventory" in result.stderr
