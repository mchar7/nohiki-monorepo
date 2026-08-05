"""Behavior checks for the GitHub prose disclosure guard."""

from __future__ import annotations

import importlib.util
import io
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_ROOT = Path(__file__).parents[3]
_SPEC = importlib.util.spec_from_file_location(
    "github_prose_guard",
    _ROOT / "scripts/dev/github_prose_guard.py",
)
assert _SPEC is not None
assert _SPEC.loader is not None
_guard = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _guard
_SPEC.loader.exec_module(_guard)
guard = _guard

_SYNTHETIC_POLICY_DIGEST = "d1998af15d2b1b4ad0aa288ec795917aa1ca4a96023e4a76d5d9a4bea90008e3"
_SYNTHETIC_PATH_EXPRESSION = re.compile(
    r"(?:^|(?<=[\s/]))[.]synthetic-control(?:[/\\]|$)",
    re.IGNORECASE,
)


class _SyntheticConfig:
    def __init__(self) -> None:
        self.vocabulary = (
            SimpleNamespace(
                id="synthetic-path-shape",
                scope=SimpleNamespace(value="message"),
                severity=SimpleNamespace(value="error"),
                patterns=(SimpleNamespace(expression=_SYNTHETIC_PATH_EXPRESSION),),
            ),
        )

    def vocabulary_for(self, _path: str, scope: str) -> tuple[SimpleNamespace, ...]:
        return self.vocabulary if scope == "message" else ()


def _config() -> _SyntheticConfig:
    return _SyntheticConfig()


def _scan(text: str) -> tuple[object, ...]:
    return guard.scan_disclosures(
        text,
        _config(),
        expected_policy_digest=_SYNTHETIC_POLICY_DIGEST,
    )


def test_configured_vocabulary_uses_precomputed_digest() -> None:
    assert guard._policy_digest(_config()) == _SYNTHETIC_POLICY_DIGEST


@pytest.mark.parametrize(
    ("text", "column"),
    [
        (".synthetic-control/records/item", 1),
        ("Inspect .synthetic-control/records/item before publishing.", 9),
        ("Inspect /srv/example/.synthetic-control/records/item before publishing.", 22),
    ],
)
def test_configured_path_rule_covers_relative_and_inline_forms(text: str, column: int) -> None:
    assert _scan(text) == (guard.Finding("synthetic-path-shape", 1, column),)


def test_clean_prose_passes() -> None:
    assert _scan("The requested change is ready for review.") == ()


def test_policy_integrity_mismatch_fails_closed() -> None:
    with pytest.raises(RuntimeError, match="integrity check"):
        guard.scan_disclosures(
            "clean synthetic prose",
            _config(),
            expected_policy_digest="0" * 64,
        )


def test_sweep_fetches_all_pull_request_prose_surfaces() -> None:
    responses: dict[str, object] = {
        "repos/example/project/pulls?state=all&per_page=100": [
            [{"number": 17, "title": "Synthetic title", "body": "Synthetic body"}]
        ],
        "repos/example/project/issues/comments?per_page=100": [
            [
                {
                    "issue_url": "https://api.github.invalid/repos/example/project/issues/17",
                    "body": "Synthetic conversation comment",
                }
            ]
        ],
        "repos/example/project/pulls/17/reviews?per_page=100": [[{"body": "Synthetic review summary"}]],
        "repos/example/project/pulls/comments?per_page=100": [
            [
                {
                    "pull_request_url": "https://api.github.invalid/repos/example/project/pulls/17",
                    "body": "Synthetic inline review comment",
                }
            ]
        ],
    }
    surfaces = guard.fetch_surfaces(responses.__getitem__, "example/project", None)
    result = guard.sweep(
        surfaces,
        _config(),
        expected_policy_digest=_SYNTHETIC_POLICY_DIGEST,
    )

    assert [surface.name for surface in surfaces] == [
        "title",
        "body",
        "comment",
        "review-summary",
        "review-comment",
    ]
    assert result.pull_requests == 1
    assert result.comments == 2
    assert result.characters == sum(len(surface.text) for surface in surfaces) > 0
    assert result.findings == ()


def test_sweep_fails_closed_on_empty_api_payload() -> None:
    with pytest.raises(RuntimeError, match="no pull requests"):
        guard.fetch_surfaces(lambda _endpoint: [], "example/project", None)


def test_malformed_review_summary_fails_closed() -> None:
    responses: dict[str, object] = {
        "repos/example/project/pulls/17": {
            "number": 17,
            "title": "Synthetic title",
            "body": "Synthetic body",
        },
        "repos/example/project/issues/17/comments?per_page=100": [[]],
        "repos/example/project/pulls/17/comments?per_page=100": [[]],
        "repos/example/project/pulls/17/reviews?per_page=100": [[{"body": 42}]],
    }

    with pytest.raises(RuntimeError, match="malformed review summary"):
        guard.fetch_surfaces(responses.__getitem__, "example/project", 17)


def test_unexpected_scanner_error_refuses_without_echoing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    sensitive = "synthetic-scanner-error-payload"
    monkeypatch.setattr(guard, "_repository_root", lambda: _ROOT)
    monkeypatch.setattr(guard, "_load_guard", lambda _repository: (_config(), "gh"))
    monkeypatch.setattr(guard.sys, "stdin", io.StringIO("Synthetic prose"))

    def scanner_error(*_args: object, **_kwargs: object) -> tuple[object, ...]:
        raise RuntimeError(sensitive)

    monkeypatch.setattr(guard, "scan_disclosures", scanner_error)

    assert guard.main(["scan"]) == 2
    captured = capsys.readouterr()
    assert sensitive not in captured.out
    assert sensitive not in captured.err
    assert "unexpected scanner failure" in captured.err


def test_rendering_never_echoes_matched_text(capsys: pytest.CaptureFixture[str]) -> None:
    sensitive = "synthetic-sensitive-payload"
    surface = guard.Surface(17, "comment", sensitive)
    result = guard.SweepResult(
        pull_requests=1,
        comments=1,
        characters=len(sensitive),
        findings=((surface, guard.Finding("synthetic-rule", 2, 4)),),
    )

    guard._render_sweep(result)
    captured = capsys.readouterr()
    assert sensitive not in captured.out
    assert sensitive not in captured.err
    assert "PR #17 comment:2:4: [synthetic-rule]" in captured.err
