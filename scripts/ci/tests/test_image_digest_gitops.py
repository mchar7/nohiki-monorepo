from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from collections.abc import Callable
from functools import cache
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _ROOT / "scripts" / "ci" / "image_digests.py"
_IMAGE_DIGESTS_SPEC = importlib.util.spec_from_file_location("image_digests", _SCRIPT)
assert _IMAGE_DIGESTS_SPEC is not None
assert _IMAGE_DIGESTS_SPEC.loader is not None
image_digests = importlib.util.module_from_spec(_IMAGE_DIGESTS_SPEC)
_IMAGE_DIGESTS_SPEC.loader.exec_module(image_digests)
_WORKFLOW = _ROOT / ".github" / "workflows" / "build-push.yml"
_CHART = _ROOT / "infra" / "k8s" / "helm"
_SCHEDULE_TICK_IMAGE = "ghcr.io/mchar7/nohiki-monorepo/sys-tick-job"
_PROD_PLATFORM_OVERLAY = _ROOT / "infra" / "k8s" / "gitops" / "platform" / "prod"
_FIRST_PARTY_PREFIX = "ghcr.io/mchar7/nohiki-monorepo/"
_SYNTHETIC_REPOSITORY = "example-org/example-monorepo"
_SYNTHETIC_PREFIX = f"ghcr.io/{_SYNTHETIC_REPOSITORY}"
_PROD_IDENTITY = Path(__file__).parent / "fixtures" / "values.prod.identity.yaml"
_PROD_NETWORK = Path(__file__).parent / "fixtures" / "values.prod.network.yaml"


def _digest_values(tmp_path: Path, *, omit: str | None = None, invalid: str | None = None) -> Path:
    digests = {
        f"{_FIRST_PARTY_PREFIX}{name}": f"sha256:{index + 1:064x}"
        for index, name in enumerate(_names())
        if name != omit
    }
    if invalid is not None:
        digests[f"{_FIRST_PARTY_PREFIX}{invalid}"] = "not-a-digest"
    path = tmp_path / "values.prod.digests.yaml"
    path.write_text(yaml.safe_dump({"global": {"imageDigests": digests}}), encoding="utf-8")
    return path


def _render(values_name: str, extra_values: Path | None = None) -> subprocess.CompletedProcess[str]:
    command = [
        "helm",
        "template",
        "nohiki",
        str(_CHART),
        "--namespace",
        "nohiki-prod" if values_name == "values.prod.yaml" else "nohiki-local",
        "--values",
        str(_CHART / values_name),
    ]
    if values_name == "values.prod.yaml":
        command.extend(["--values", str(_PROD_IDENTITY), "--values", str(_PROD_NETWORK)])
    elif values_name == "values.staging.yaml":
        # Staging enables the chart-managed store; its workload-identity coordinates
        # arrive via runtime substitution, so a bare render needs a synthetic identity.
        command.extend(["--values", str(_PROD_IDENTITY)])
    if extra_values is not None:
        command.extend(["--values", str(extra_values)])
    return subprocess.run(command, cwd=_ROOT, capture_output=True, text=True, check=False)


def _images(value: object) -> list[str]:
    if isinstance(value, dict):
        images = [value["image"]] if isinstance(value.get("image"), str) else []
        return images + [image for child in value.values() for image in _images(child)]
    if isinstance(value, list):
        return [image for child in value for image in _images(child)]
    return []


def _assert_schedule_tick_image(actual: str, expected: str) -> None:
    assert actual == expected
    assert not actual.startswith("ghcr.io/sys-tick-job")


@cache
def _matrix_include() -> list[dict[str, object]]:
    workflow = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))
    return workflow["jobs"]["build-push"]["strategy"]["matrix"]["include"]


@cache
def _names() -> tuple[str, ...]:
    return tuple(entry["name"] for entry in _matrix_include())


def _record(name: str, index: int = 0, *, repository: str = _SYNTHETIC_REPOSITORY) -> dict[str, str]:
    return {
        "name": name,
        "image": f"ghcr.io/{repository}/{name}",
        "digest": f"sha256:{index + 1:064x}",
        "sourceSha": "a" * 40,
        "workflowUrl": f"https://github.com/{repository}/actions/runs/123",
    }


def _assemble(
    tmp_path: Path,
    records: list[dict[str, str]],
    *,
    repository: str = _SYNTHETIC_REPOSITORY,
) -> subprocess.CompletedProcess[str]:
    records_dir = tmp_path / "records"
    records_dir.mkdir(parents=True)
    for index, record in enumerate(records):
        (records_dir / f"{index}.json").write_text(json.dumps(record), encoding="utf-8")
    return subprocess.run(
        [
            sys.executable,
            str(_SCRIPT),
            "assemble",
            "--records",
            str(records_dir),
            "--repository",
            repository,
            "--output",
            str(tmp_path / "digests.yaml"),
        ],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _assemble_direct(
    tmp_path: Path,
    records: list[dict[str, str]],
    *,
    repository: str = _SYNTHETIC_REPOSITORY,
) -> None:
    records_dir = tmp_path / "records"
    records_dir.mkdir(parents=True)
    for index, record in enumerate(records):
        (records_dir / f"{index}.json").write_text(json.dumps(record), encoding="utf-8")
    args = image_digests.parser().parse_args(
        [
            "assemble",
            "--workflow",
            str(_WORKFLOW),
            "--records",
            str(records_dir),
            "--repository",
            repository,
            "--output",
            str(tmp_path / "digests.yaml"),
        ]
    )
    image_digests.assemble(args)


def test_assemble_accepts_exact_matrix_and_is_deterministic(tmp_path: Path) -> None:
    names = _names()
    assert len(names) == len(set(names))
    records = [_record(name, index) for index, name in enumerate(names)]
    first = _assemble(tmp_path / "first", records)
    second = _assemble(tmp_path / "second", list(reversed(records)))
    assert first.returncode == second.returncode == 0, first.stderr + second.stderr
    first_output = (tmp_path / "first" / "digests.yaml").read_text(encoding="utf-8")
    second_output = (tmp_path / "second" / "digests.yaml").read_text(encoding="utf-8")
    assert first_output == second_output
    document = yaml.safe_load(first_output)
    digests = document["global"]["imageDigests"]
    assert set(digests) == {record["image"] for record in records}
    assert set(digests.values()) == {record["digest"] for record in records}
    assert "imageDigestProvenance" not in document["global"]
    cpu_key = f"{_SYNTHETIC_PREFIX}/ml-compute-service"
    gpu_key = f"{_SYNTHETIC_PREFIX}/ml-compute-service-gpu"
    assert cpu_key in digests
    assert gpu_key in digests
    assert digests[cpu_key] != digests[gpu_key]


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda records: records.pop(), "record set mismatch"),
        (
            lambda records: records.append(_record("not-in-matrix", 23)),
            "noncanonical image",
        ),
        (lambda records: records.append(dict(records[0])), "duplicate record"),
        (
            lambda records: records[0].update(image="ghcr.io/other/repository/image"),
            "noncanonical image",
        ),
        (
            lambda records: records[0].update(digest="not-a-digest"),
            "malformed or duplicate digest",
        ),
        (
            lambda records: records[0].update(digest="sha256:" + "A" * 64),
            "malformed or duplicate digest",
        ),
        (
            lambda records: records[1].update(digest=records[0]["digest"]),
            "malformed or duplicate digest",
        ),
        (lambda records: records[0].update(sourceSha="abc123"), "sourceSha"),
        (
            lambda records: records[0].update(workflowUrl="https://example.com/actions/runs/123"),
            "workflowUrl",
        ),
    ],
    ids=[
        "missing-name",
        "extra-name",
        "duplicate-name",
        "wrong-ref",
        "bad-digest",
        "uppercase-digest",
        "reused-digest",
        "invalid-sha",
        "invalid-run-url",
    ],
)
def test_assemble_rejects_invalid_record_sets(
    tmp_path: Path, mutate: Callable[[list[dict[str, str]]], object], match: str
) -> None:
    records = [_record(name, index) for index, name in enumerate(_names())]
    mutate(records)
    with pytest.raises(ValueError, match=match):
        _assemble_direct(tmp_path, records)
    assert not (tmp_path / "digests.yaml").exists()


@pytest.mark.parametrize(
    "repository",
    ["no-slash", "owner/", "/repo", "owner/repo/extra", "own er/repo", ""],
    ids=[
        "missing-slash",
        "empty-repo",
        "empty-owner",
        "too-many-parts",
        "space",
        "empty",
    ],
)
def test_assemble_rejects_noncanonical_repository(tmp_path: Path, repository: str) -> None:
    records = [_record(name, index) for index, name in enumerate(_names())]
    with pytest.raises(ValueError, match="repository must be a canonical"):
        _assemble_direct(tmp_path, records, repository=repository)
    assert not (tmp_path / "digests.yaml").exists()


def test_record_writes_buildx_digest_provenance(tmp_path: Path) -> None:
    output = tmp_path / "record.json"
    record = _record(_names()[0])
    env = os.environ | {
        "IMAGE_NAME": record["name"],
        "IMAGE_REF": record["image"],
        "IMAGE_DIGEST": record["digest"],
        "SOURCE_SHA": record["sourceSha"],
        "WORKFLOW_URL": record["workflowUrl"],
        "GITHUB_REPOSITORY": _SYNTHETIC_REPOSITORY,
    }
    result = subprocess.run(
        [sys.executable, str(_SCRIPT), "record", "--output", str(output)],
        cwd=_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(output.read_text(encoding="utf-8")) == record


def test_production_helmrelease_consumes_generated_digest_overlay() -> None:
    # Post-cutover the prod platform HelmRelease (rendered from the Flux overlay)
    # carries the ordered valuesFiles that end with the generated digest overlay.
    rendered = subprocess.run(
        ["kubectl", "kustomize", str(_PROD_PLATFORM_OVERLAY)],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    release = next(
        document
        for document in yaml.safe_load_all(rendered)
        if isinstance(document, dict) and document.get("kind") == "HelmRelease"
    )
    assert release["spec"]["chart"]["spec"]["valuesFiles"] == [
        "infra/k8s/helm/values.yaml",
        "infra/k8s/helm/values.prod.yaml",
        "infra/k8s/helm/values.prod.identity.yaml",
        "infra/k8s/helm/values.prod.network.yaml",
        "infra/k8s/helm/values.prod.digests.yaml",
    ]


@pytest.mark.parametrize(
    ("omit", "invalid"),
    [(None, None), ("user-auth-service", None), (None, "user-auth-service")],
    ids=["missing-map", "incomplete-map", "invalid-map"],
)
def test_production_digest_maps_fail_closed(tmp_path: Path, omit: str | None, invalid: str | None) -> None:
    overlay = None if omit is None and invalid is None else _digest_values(tmp_path, omit=omit, invalid=invalid)
    result = _render("values.prod.yaml", overlay)
    assert result.returncode != 0
    assert "digest" in result.stderr.lower()


def test_complete_digest_map_renders_all_enabled_first_party_images_immutable(
    tmp_path: Path,
) -> None:
    result = _render("values.prod.yaml", _digest_values(tmp_path))
    assert result.returncode == 0, result.stderr
    documents = [document for document in yaml.safe_load_all(result.stdout) if isinstance(document, dict)]
    images = [image for image in _images(documents) if image.startswith(_FIRST_PARTY_PREFIX)]
    assert images
    assert all("@sha256:" in image and ":sha-" not in image for image in images)
    assert {_SCHEDULE_TICK_IMAGE, f"{_FIRST_PARTY_PREFIX}user-auth-service"} <= {
        image.split("@", 1)[0] for image in images
    }


@pytest.mark.parametrize("values_name", ["values.local.yaml", "values.staging.yaml"])
def test_nonproduction_environments_still_render_without_digest_map(
    values_name: str,
) -> None:
    result = _render(values_name)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "invalid_ref",
    [
        "ghcr.io/sys-tick-job:sha-933dda3",
        "ghcr.io/sys-tick-job@sha256:" + "f" * 64,
    ],
    ids=["bare-ghcr-tag", "bare-ghcr-digest"],
)
def test_schedule_tick_image_assertion_rejects_bare_ghcr_path(invalid_ref: str) -> None:
    with pytest.raises(AssertionError):
        _assert_schedule_tick_image(invalid_ref, invalid_ref)


def test_ml_compute_cpu_and_gpu_variants_are_distinct_matrix_rows() -> None:
    """Both accelerator images build from one Dockerfile as distinct matrix rows.

    The CPU row (ml-compute-service) carries no GPU build arg, so it takes the
    default sync-cpu stage (+cpu torch). The GPU row (ml-compute-service-gpu)
    selects the sync-gpu stage via ML_COMPUTE_BUILDER=sync-gpu (+cu130 torch).
    Distinct names keep their digests in separate global.imageDigests keys.
    """
    rows = {row["name"]: row for row in _matrix_include()}
    assert "ml-compute-service" in rows, sorted(rows)
    assert "ml-compute-service-gpu" in rows, sorted(rows)

    cpu, gpu = rows["ml-compute-service"], rows["ml-compute-service-gpu"]
    # Same Dockerfile; the builder stage is chosen purely by the build arg.
    assert cpu["dockerfile"] == gpu["dockerfile"]
    assert "sync-gpu" not in str(cpu.get("build_args", "")), cpu
    assert "ML_COMPUTE_BUILDER=sync-gpu" in str(gpu.get("build_args", "")), gpu
