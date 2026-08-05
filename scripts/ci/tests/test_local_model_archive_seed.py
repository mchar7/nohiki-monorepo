"""Focused contracts for the local manifest-derived model archive carrier."""

from __future__ import annotations

import importlib.util
import io
import json
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path
from types import ModuleType

import boto3
import pytest
import yaml
from botocore.exceptions import ClientError, EndpointConnectionError

_ROOT = Path(__file__).resolve().parents[3]
_HELPER = _ROOT / "infra/k8s/local/model_archive_seed.py"
_KINDCTL = _ROOT / "infra/k8s/local/kindctl"
_LIFECYCLE = _ROOT / "infra/k8s/local/lifecycle.sh"
_MANIFEST = _ROOT / "data/config/semantic_representation_manifest.json"
_RUSTFS_VALUES = _ROOT / "infra/k8s/helm/charts/rustfs/values.yaml"
_LOCAL_VALUES = _ROOT / "infra/k8s/helm/values.local.yaml"


def _load_helper() -> ModuleType:
    spec = importlib.util.spec_from_file_location("model_archive_seed", _HELPER)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_ml_compute_seed_sdk_is_in_the_locked_runtime_closure() -> None:
    result = subprocess.run(
        [
            shutil.which("uv") or "uv",
            "export",
            "--frozen",
            "--offline",
            "--no-hashes",
            "--no-dev",
            "--package",
            "ml-compute-service",
        ],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert re.search(r"(?m)^boto3==", result.stdout), result.stdout
    assert re.search(r"(?m)^botocore==", result.stdout), result.stdout


def test_manifest_derives_exact_ml_core_archive_keys() -> None:
    helper = _load_helper()

    assert [archive.key for archive in helper._archive_specs(_MANIFEST)] == [
        "models/colbert/mixedbread-ai/mxbai-edge-colbert-v0-17m/model.tar.gz",
        "models/dense/TechWolf/JobBERT-v2/model.tar.gz",
        "models/sparse/Qdrant/minicoil-v1/model.tar.gz",
    ]


def test_preparation_is_deterministic_and_emits_metadata_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    helper = _load_helper()
    specs = (helper.ArchiveSpec("owner/model", "revision", "huggingface", "models/owner/model/revision/model.tar.gz"),)
    monkeypatch.setattr(helper, "_archive_specs", lambda _manifest: specs)

    def download(_spec: object, target: Path) -> None:
        (target / "payload.bin").write_bytes(b"private-model-payload")

    monkeypatch.setattr(helper, "_download", download)
    attempts = (tmp_path / "attempt-1", tmp_path / "attempt-2")
    for attempt in attempts:
        attempt.mkdir(mode=0o700)
        helper.main(["prepare", "--attempt-dir", str(attempt), "--manifest", str(_MANIFEST)])

    first_output, second_output = capsys.readouterr().out.splitlines()
    first = json.loads(first_output)
    second = json.loads(second_output)
    assert first == second
    assert first == json.loads((attempts[0] / "model-archives.json").read_bytes())
    assert set(first) == {"apiVersion", "archives", "bucket", "kind"}
    assert set(first["archives"][0]) == {"byteLength", "filename", "key", "sha256"}
    assert "private-model-payload" not in first_output + second_output
    first_archive = attempts[0] / "model-archives" / first["archives"][0]["filename"]
    second_archive = attempts[1] / "model-archives" / second["archives"][0]["filename"]
    assert first_archive.read_bytes() == second_archive.read_bytes()


def test_huggingface_archives_extract_as_complete_hub_caches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    helper = _load_helper()
    specs = tuple(spec for spec in helper._archive_specs(_MANIFEST) if spec.extract_dir == "huggingface")
    monkeypatch.setattr(helper, "_archive_specs", lambda _manifest: specs)

    class _HuggingFaceHubStub(ModuleType):
        @staticmethod
        def snapshot_download(*, repo_id: str, cache_dir: Path, revision: str | None = None) -> str:
            repository = cache_dir / f"models--{repo_id.replace('/', '--')}"
            blob = repository / "blobs/config"
            blob.parent.mkdir(parents=True)
            blob.write_bytes(f"{repo_id}:{revision}".encode())
            snapshot = repository / "snapshots/test-commit"
            snapshot.mkdir(parents=True)
            (snapshot / "config.json").symlink_to("../../blobs/config")
            return str(snapshot)

    monkeypatch.setitem(sys.modules, "huggingface_hub", _HuggingFaceHubStub("huggingface_hub"))
    attempt = tmp_path / "attempt"
    attempt.mkdir(mode=0o700)
    record = helper.prepare(_MANIFEST, attempt)
    cache_root = tmp_path / "service-cache"

    for spec, evidence in zip(specs, record["archives"], strict=True):
        archive_path = attempt / "model-archives" / evidence["filename"]
        with tarfile.open(archive_path, "r:gz") as archive:
            archive.extractall(cache_root / spec.extract_dir, filter="data")
        repository = cache_root / "huggingface" / "hub" / f"models--{spec.model_id.replace('/', '--')}"
        snapshot = repository / "snapshots" / (repository / "refs/main").read_text(encoding="utf-8")
        assert (repository / "blobs").is_dir()
        assert snapshot.is_dir()
        assert (snapshot / "config.json").is_file()


def test_readiness_poll_tolerates_resources_not_existing_yet(monkeypatch: pytest.MonkeyPatch) -> None:
    helper = _load_helper()
    return_codes = iter((1, 1, 0, 0))
    commands: list[list[str]] = []

    def run(command: list[str], **_kwargs: object) -> object:
        commands.append(command)
        return helper.subprocess.CompletedProcess(command, next(return_codes))

    monkeypatch.setattr(helper.subprocess, "run", run)
    monkeypatch.setattr(helper.time, "monotonic", lambda: 0)
    monkeypatch.setattr(helper.time, "sleep", lambda _seconds: None)

    helper._wait_for_rustfs_backend(Path("/kubeconfig"), "nohiki", timeout_seconds=1)

    assert [command[4] for command in commands] == ["get", "get", "get", "rollout"]


def test_upload_reads_authoritative_cluster_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    helper = _load_helper()
    encoded = {
        "access-key": helper.base64.b64encode(b"test-access").decode(),
        "secret-key": helper.base64.b64encode(b"test-secret").decode(),
        "unrelated": helper.base64.b64encode(b"ignored").decode(),
    }
    commands: list[list[str]] = []

    def run(command: list[str], **_kwargs: object) -> object:
        commands.append(command)
        return helper.subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"data": encoded}).encode(),
        )

    monkeypatch.setattr(helper.subprocess, "run", run)

    assert helper._cluster_credentials(Path("/kubeconfig"), "nohiki") == ("test-access", "test-secret")
    assert commands[0][-2:] == ["secret/nohiki-rustfs-credentials", "--output=json"]


def test_upload_rejects_same_length_remote_corruption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    helper = _load_helper()
    spec = helper.ArchiveSpec("owner/model", None, "huggingface", "models/owner/model/model.tar.gz")
    monkeypatch.setattr(helper, "_archive_specs", lambda _manifest: (spec,))
    monkeypatch.setattr(
        helper,
        "_download",
        lambda _spec, target: (target / "payload.bin").write_bytes(b"archive-source"),
    )
    attempt = tmp_path / "attempt"
    attempt.mkdir(mode=0o700)
    record = helper.prepare(_MANIFEST, attempt)
    evidence = record["archives"][0]

    class FakeForward:
        def terminate(self) -> None:
            pass

        def wait(self, *, timeout: int) -> None:
            assert timeout == 5

    class FakeClient:
        def head_bucket(self, **_kwargs: object) -> None:
            pass

        def put_object(self, **_kwargs: object) -> None:
            pass

        def head_object(self, **_kwargs: object) -> dict[str, object]:
            return {
                "ContentLength": evidence["byteLength"],
                "Metadata": {"sha256": evidence["sha256"]},
            }

        def get_object(self, **_kwargs: object) -> dict[str, object]:
            length = evidence["byteLength"]
            return {"Body": io.BytesIO(b"x" * length)}

    monkeypatch.setattr(helper, "_cluster_credentials", lambda *_args: ("test-access", "test-secret"))

    monkeypatch.setattr(helper, "_wait_for_rustfs_backend", lambda *_args: None)
    monkeypatch.setattr(helper.subprocess, "run", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(helper, "_port_forward", lambda *_args: (FakeForward(), "http://127.0.0.1:1"))
    monkeypatch.setattr(boto3, "client", lambda *_args, **_kwargs: FakeClient())

    with pytest.raises(helper.SeedError, match="object evidence mismatch"):
        helper.upload(attempt, tmp_path / "kubeconfig", "nohiki")


def test_bucket_readiness_retries_transport_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    helper = _load_helper()
    clock = [0.0]

    class FakeClient:
        calls = 0

        def head_bucket(self, **_kwargs: object) -> None:
            self.calls += 1
            if self.calls < 3:
                raise EndpointConnectionError(endpoint_url="http://127.0.0.1:1")

    client = FakeClient()
    monkeypatch.setattr(helper.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(helper.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))

    helper._wait_for_bucket(client, timeout_seconds=5)

    assert client.calls == 3
    assert clock[0] == 4


def test_bucket_readiness_transport_failures_stop_at_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    helper = _load_helper()
    clock = [0.0]

    class FakeClient:
        calls = 0

        def head_bucket(self, **_kwargs: object) -> None:
            self.calls += 1
            raise EndpointConnectionError(endpoint_url="http://127.0.0.1:1")

    client = FakeClient()
    monkeypatch.setattr(helper.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(helper.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))

    with pytest.raises(helper.SeedError, match="within 3 seconds"):
        helper._wait_for_bucket(client, timeout_seconds=3)

    assert client.calls == 2
    assert clock[0] == 3


def test_preexisting_archive_identity_mismatch_is_never_overwritten(tmp_path: Path) -> None:
    helper = _load_helper()
    payload = b"prepared-archive"
    path = tmp_path / "model.tar.gz"
    path.write_bytes(payload)
    evidence = helper.PreparedArchive(
        "models/owner/model/model.tar.gz",
        path.name,
        len(payload),
        helper.hashlib.sha256(payload).hexdigest(),
    )

    class FakeClient:
        put_calls = 0

        def head_object(self, **_kwargs: object) -> dict[str, object]:
            return {
                "ContentLength": evidence.byte_length,
                "Metadata": {"sha256": "0" * 64},
            }

        def put_object(self, **_kwargs: object) -> None:
            self.put_calls += 1

    client = FakeClient()
    with pytest.raises(helper.SeedError, match="immutable object identity mismatch"):
        helper._upload_archive(client, path, evidence)

    assert client.put_calls == 0


def test_conditional_create_race_refuses_a_different_archive(tmp_path: Path) -> None:
    helper = _load_helper()
    payload = b"prepared-archive"
    path = tmp_path / "model.tar.gz"
    path.write_bytes(payload)
    evidence = helper.PreparedArchive(
        "models/owner/model/model.tar.gz",
        path.name,
        len(payload),
        helper.hashlib.sha256(payload).hexdigest(),
    )

    class FakeClient:
        head_calls = 0
        put_calls = 0

        def head_object(self, **_kwargs: object) -> dict[str, object]:
            self.head_calls += 1
            if self.head_calls == 1:
                raise ClientError({"Error": {"Code": "404"}}, "HeadObject")
            return {
                "ContentLength": evidence.byte_length,
                "Metadata": {"sha256": "f" * 64},
            }

        def put_object(self, **kwargs: object) -> None:
            self.put_calls += 1
            assert kwargs["IfNoneMatch"] == "*"
            raise ClientError({"Error": {"Code": "PreconditionFailed"}}, "PutObject")

    client = FakeClient()
    with pytest.raises(helper.SeedError, match="immutable object identity mismatch"):
        helper._upload_archive(client, path, evidence)

    assert client.head_calls == 2
    assert client.put_calls == 1


def test_local_publication_prepares_then_uploads_before_platform_wait() -> None:
    source = _KINDCTL.read_text(encoding="utf-8")
    publish = source[source.index("def publish_images(") : source.index("def validate_publication_record(")]
    finalize = source[source.index("def finalize_flux_runtime(") : source.index("def qualify_offline_policy(")]

    assert publish.index('"prepare"') < publish.index("write_publication_output(attempt, record)")
    upload = finalize.index('"upload"')
    platform_wait = finalize.index("state = wait_kustomization(", upload)
    assert upload < platform_wait
    assert "port-forward" not in source, "kindctl must delegate RustFS transport to the seed helper"


def test_rustfs_chart_declares_model_cache_bucket() -> None:
    values = yaml.safe_load(_RUSTFS_VALUES.read_text(encoding="utf-8"))
    local_values = yaml.safe_load(_LOCAL_VALUES.read_text(encoding="utf-8"))

    assert "nohiki-ml-artifacts" in values["buckets"]
    assert "nohiki-ml-artifacts" in local_values["rustfs"]["buckets"]


def test_publication_is_push_delegate_only() -> None:
    lifecycle = _LIFECYCLE.read_text(encoding="utf-8")

    assert re.search(r"\bgit\s+push\b", lifecycle) is None
    assert "PUSH-DELEGATE" in lifecycle
