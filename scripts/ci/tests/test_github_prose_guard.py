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


_NODE_TYPES = {
    "synthetic-pull": "PullRequest",
    "synthetic-comment": "IssueComment",
    "synthetic-review": "PullRequestReview",
    "synthetic-review-comment": "PullRequestReviewComment",
}
_EDITED_AT = "2026-01-02T03:04:05Z"


def _history_node(
    node_id: str,
    records: tuple[dict[str, object], ...] = (),
    *,
    has_next_page: bool = False,
) -> dict[str, object]:
    return {
        "id": node_id,
        "__typename": _NODE_TYPES[node_id],
        "includesCreatedEdit": bool(records),
        "lastEditedAt": _EDITED_AT if records else None,
        "userContentEdits": {
            "totalCount": len(records),
            "pageInfo": {
                "hasNextPage": has_next_page,
                "endCursor": "synthetic-cursor" if has_next_page else None,
            },
            "nodes": list(records),
        },
    }


def _edit_record(
    node_id: str,
    *,
    diff: str | None = "Synthetic prior prose",
    deleted_at: str | None = None,
) -> dict[str, object]:
    return {
        "id": f"{node_id}-edit",
        "diff": diff,
        "editedAt": _EDITED_AT,
        "deletedAt": deleted_at,
    }


def _surface_responses() -> dict[str, object]:
    return {
        "repos/example/project/pulls?state=all&per_page=100": [
            [
                {
                    "number": 17,
                    "node_id": "synthetic-pull",
                    "title": "Synthetic title",
                    "body": "Synthetic body",
                }
            ]
        ],
        "repos/example/project/issues/comments?per_page=100": [
            [
                {
                    "node_id": "synthetic-comment",
                    "issue_url": "https://api.github.invalid/repos/example/project/issues/17",
                    "body": "Synthetic conversation comment",
                }
            ]
        ],
        "repos/example/project/pulls/17/reviews?per_page=100": [
            [{"node_id": "synthetic-review", "body": "Synthetic review summary"}]
        ],
        "repos/example/project/pulls/comments?per_page=100": [
            [
                {
                    "node_id": "synthetic-review-comment",
                    "pull_request_url": "https://api.github.invalid/repos/example/project/pulls/17",
                    "body": "Synthetic inline review comment",
                }
            ]
        ],
    }


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


def test_sweep_fetches_all_pull_request_text_surfaces() -> None:
    responses = _surface_responses()
    surfaces = guard.fetch_surfaces(
        responses.__getitem__,
        lambda node_ids: [_history_node(node_id) for node_id in node_ids],
        "example/project",
        None,
    )
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
    assert result.histories == 0
    assert result.characters == sum(len(surface.text) for surface in surfaces) > 0
    assert result.findings == ()


def test_sweep_scans_retained_edits_for_every_node_type() -> None:
    responses = _surface_responses()
    records = {node_id: (_edit_record(node_id, diff="Prior .synthetic-control/record"),) for node_id in _NODE_TYPES}
    surfaces = guard.fetch_surfaces(
        responses.__getitem__,
        lambda node_ids: [_history_node(node_id, records[node_id]) for node_id in node_ids],
        "example/project",
        None,
    )
    result = guard.sweep(
        surfaces,
        _config(),
        expected_policy_digest=_SYNTHETIC_POLICY_DIGEST,
    )

    history_surfaces = [surface for surface in surfaces if surface.name.endswith("-history")]
    assert [surface.name for surface in history_surfaces] == [
        "title/body-history",
        "comment-history",
        "review-summary-history",
        "review-comment-history",
    ]
    assert [(surface.node_id, surface.edit_id, surface.edited_at) for surface in history_surfaces] == [
        (node_id, f"{node_id}-edit", _EDITED_AT) for node_id in _NODE_TYPES
    ]
    assert result.histories == 4
    assert len(result.findings) == 4
    assert {surface.name for surface, _finding in result.findings} == {surface.name for surface in history_surfaces}


def test_purged_edit_metadata_is_accepted_without_inventing_content() -> None:
    ref = guard._EditRef("synthetic-pull", 17, "title/body", "PullRequest")
    node = _history_node(
        "synthetic-pull",
        (_edit_record("synthetic-pull", diff=None, deleted_at=_EDITED_AT),),
    )

    assert guard._history_surfaces([node], [ref]) == (
        guard.Surface(
            17,
            "title/body-history",
            "",
            "synthetic-pull",
            "synthetic-pull-edit",
            _EDITED_AT,
            _EDITED_AT,
        ),
    )


def test_unavailable_unpurged_edit_fails_closed() -> None:
    ref = guard._EditRef("synthetic-pull", 17, "title/body", "PullRequest")
    node = _history_node("synthetic-pull", (_edit_record("synthetic-pull", diff=None),))

    with pytest.raises(RuntimeError, match="unavailable edit history"):
        guard._history_surfaces([node], [ref])


def test_paginated_edit_history_fails_closed() -> None:
    ref = guard._EditRef("synthetic-pull", 17, "title/body", "PullRequest")
    node = _history_node("synthetic-pull", has_next_page=True)

    with pytest.raises(RuntimeError, match="truncated edit history"):
        guard._history_surfaces([node], [ref])


def test_sweep_fails_closed_on_empty_api_payload() -> None:
    with pytest.raises(RuntimeError, match="no pull requests"):
        guard.fetch_surfaces(lambda _endpoint: [], lambda _node_ids: [], "example/project", None)


def test_malformed_review_summary_fails_closed() -> None:
    responses: dict[str, object] = {
        "repos/example/project/pulls/17": {
            "number": 17,
            "node_id": "synthetic-pull",
            "title": "Synthetic title",
            "body": "Synthetic body",
        },
        "repos/example/project/issues/17/comments?per_page=100": [[]],
        "repos/example/project/pulls/17/comments?per_page=100": [[]],
        "repos/example/project/pulls/17/reviews?per_page=100": [[{"body": 42}]],
    }

    with pytest.raises(RuntimeError, match="malformed review summary"):
        guard.fetch_surfaces(responses.__getitem__, lambda _node_ids: [], "example/project", 17)


@pytest.mark.parametrize(
    ("endpoint", "surface"),
    [
        ("repos/example/project/pulls/17", "pull request body"),
        ("repos/example/project/issues/17/comments?per_page=100", "comment"),
        ("repos/example/project/pulls/17/reviews?per_page=100", "review summary"),
        ("repos/example/project/pulls/17/comments?per_page=100", "review comment"),
    ],
)
def test_missing_body_key_fails_closed(endpoint: str, surface: str) -> None:
    responses: dict[str, object] = {
        "repos/example/project/pulls/17": {
            "number": 17,
            "node_id": "synthetic-pull",
            "title": "Synthetic title",
            "body": "Synthetic body",
        },
        "repos/example/project/issues/17/comments?per_page=100": [[]],
        "repos/example/project/pulls/17/comments?per_page=100": [[]],
        "repos/example/project/pulls/17/reviews?per_page=100": [[]],
    }
    responses[endpoint] = (
        {"number": 17, "title": "Synthetic title"} if endpoint == "repos/example/project/pulls/17" else [[{}]]
    )

    with pytest.raises(RuntimeError, match=rf"malformed {surface}"):
        guard.fetch_surfaces(responses.__getitem__, lambda _node_ids: [], "example/project", 17)


def test_loading_policy_disables_bytecode_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    pins = {
        "POLICY_TREE": "/tmp/synthetic-policy",
        "POLICY_TREE_SHA256": "synthetic-digest",
        "GIT": "/nix/store/synthetic/bin/git",
        "GH": "/nix/store/synthetic/bin/gh",
    }
    module = SimpleNamespace(load_config=lambda _repository: _config())
    monkeypatch.setattr(guard, "_hook_assignments", lambda _repository: pins)
    monkeypatch.setattr(guard, "_policy_tree_digest", lambda _tree: "synthetic-digest")
    monkeypatch.setattr(guard, "_policy_package", lambda _tree: "synthetic_policy")
    monkeypatch.setattr(guard.importlib, "import_module", lambda _name: module)
    monkeypatch.setattr(guard.sys, "dont_write_bytecode", False)

    config, gh = guard._load_guard(_ROOT)

    assert isinstance(config, _SyntheticConfig)
    assert gh == pins["GH"]
    assert guard.sys.dont_write_bytecode is True


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
        histories=1,
        findings=((surface, guard.Finding("synthetic-rule", 2, 4)),),
    )

    guard._render_sweep(result)
    captured = capsys.readouterr()
    assert sensitive not in captured.out
    assert sensitive not in captured.err
    assert "1 retained edit records" in captured.out
    assert "deleted nodes are not enumerable through GitHub APIs; this audit is read-only" in captured.out
    assert "PR #17 comment:2:4: [synthetic-rule]" in captured.err
