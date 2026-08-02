from __future__ import annotations

import base64
import gzip
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_FOUNDATION = _ROOT / "infra" / "k8s" / "helm-foundation"
_RELEASES = (
    ("nohiki-foundation", _FOUNDATION),
    ("keda", _FOUNDATION / "operators" / "keda"),
    ("cloudnative-pg", _FOUNDATION / "operators" / "cloudnative-pg"),
)
_KUBERNETES_SECRET_LIMIT = 1_048_576
# Reserve space for Helm metadata growth instead of accepting a release at the API boundary.
_RELEASE_PAYLOAD_LIMIT = 900 * 1024


def _release_secret_bytes(release_name: str, chart: Path) -> int:
    release_json = subprocess.run(
        [
            "helm",
            "install",
            release_name,
            str(chart),
            "--namespace",
            "nohiki-foundation",
            "--dry-run=client",
            "--output",
            "json",
        ],
        check=True,
        capture_output=True,
    ).stdout
    compressed = gzip.compress(release_json, compresslevel=9)
    return len(base64.b64encode(compressed))


@pytest.mark.parametrize(("release_name", "chart"), _RELEASES, ids=("foundation", "keda", "cloudnative-pg"))
def test_helm_release_secret_payload_keeps_headroom(release_name: str, chart: Path) -> None:
    payload_bytes = _release_secret_bytes(release_name, chart)
    assert payload_bytes < _KUBERNETES_SECRET_LIMIT, (release_name, payload_bytes)
    assert payload_bytes <= _RELEASE_PAYLOAD_LIMIT, (release_name, payload_bytes)
