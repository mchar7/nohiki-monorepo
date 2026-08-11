"""Contract tests for durable lint and deprecation reporting."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from ci_checks.checks import reporting
from ci_checks.checks.tests import TestResult as _TestResult


def test_lint_summary_deduplicates_sarif_findings(tmp_path: Path) -> None:
    document = {
        "version": "2.1.0",
        "runs": [
            {
                "tool": {"driver": {"name": "Biome"}},
                "results": [
                    {
                        "ruleId": "lint/example",
                        "message": {"text": "same | finding"},
                        "locations": [
                            {
                                "physicalLocation": {
                                    "artifactLocation": {"uri": "src/example.ts"},
                                    "region": {"startLine": 7},
                                }
                            }
                        ],
                    },
                    {
                        "ruleId": "lint/example",
                        "message": {"text": "same | finding"},
                        "locations": [
                            {
                                "physicalLocation": {
                                    "artifactLocation": {"uri": "src/example.ts"},
                                    "region": {"startLine": 7},
                                }
                            }
                        ],
                    },
                ],
            }
        ],
    }
    (tmp_path / "biome.sarif").write_text(json.dumps(document), encoding="utf-8")

    summary = reporting.render_lint_summary(tmp_path)

    assert summary.count("same \\| finding") == 1
    assert "`src/example.ts:7`" in summary


def test_lint_summary_includes_every_deduplicated_sarif_finding(tmp_path: Path) -> None:
    results = [{"ruleId": f"rule-{index}", "message": {"text": f"finding-{index}"}} for index in range(41)]
    document = {
        "version": "2.1.0",
        "runs": [{"tool": {"driver": {"name": "Ruff"}}, "results": results}],
    }
    (tmp_path / "ruff.sarif").write_text(json.dumps(document), encoding="utf-8")

    summary = reporting.render_lint_summary(tmp_path)

    assert "finding-0" in summary
    assert "finding-40" in summary
    assert "retained in code scanning" not in summary


def test_lint_summary_sanitizes_repo_and_outside_file_uris(tmp_path: Path) -> None:
    repository_root = tmp_path / "repository"
    report_directory = repository_root / "lint-results"
    report_directory.mkdir(parents=True)
    outside_path = tmp_path / "session-private" / "work.py"
    document = {
        "version": "2.1.0",
        "runs": [
            {
                "tool": {"driver": {"name": "Ruff"}},
                "results": [
                    {
                        "message": {"text": "inside"},
                        "locations": [
                            {
                                "physicalLocation": {
                                    "artifactLocation": {"uri": (repository_root / "src/example.py").as_uri()}
                                }
                            }
                        ],
                    },
                    {
                        "message": {"text": "outside"},
                        "locations": [{"physicalLocation": {"artifactLocation": {"uri": outside_path.as_uri()}}}],
                    },
                ],
            }
        ],
    }
    (report_directory / "ruff.sarif").write_text(json.dumps(document), encoding="utf-8")

    summary = reporting.render_lint_summary(report_directory, repository_root)

    assert "src/example.py" in summary
    assert "external/work.py" in summary
    assert str(tmp_path) not in summary


def test_lint_summary_is_present_without_report_files(tmp_path: Path) -> None:
    assert reporting.render_lint_summary(tmp_path) == (
        "### Lint diagnostics\n\nNo lint diagnostic reports were produced.\n"
    )


def test_deprecation_parser_surfaces_google_genai_exception(tmp_path: Path) -> None:
    output = (
        "=============================== warnings summary ===============================\n"
        ".venv/lib/python3.14/site-packages/google/genai/types.py:42\n"
        "  /workspace/.venv/lib/python3.14/site-packages/google/genai/types.py:42: "
        "DeprecationWarning: '_UnionGenericAlias' is deprecated and slated for removal in Python 3.17\n"
        "-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html"
    )

    findings = reporting.parse_deprecation_findings(output, tmp_path)

    assert findings == [
        reporting.DeprecationFinding(
            category="DeprecationWarning",
            site="site-packages/google/genai/types.py",
            line=42,
            message="'_UnionGenericAlias' is deprecated and slated for removal in Python 3.17",
        )
    ]


def test_deprecation_parser_sanitizes_outside_repository_path(tmp_path: Path) -> None:
    raw_path = tmp_path.parent / "session-private" / "work.py"
    output = f"{raw_path}:7: DeprecationWarning: old API"

    findings = reporting.parse_deprecation_findings(output, tmp_path)
    summary = reporting.render_deprecation_summary(findings, [])
    issue_body = reporting._issue_body(findings, "https://example.test/run/1", reporting._finding_set(findings))

    assert findings[0].site == "external/work.py"
    assert str(raw_path.parent) not in summary
    assert str(raw_path.parent) not in issue_body


def test_actionlint_converter_suppresses_only_native_parallel_nodes(tmp_path: Path) -> None:
    workflow = tmp_path / ".github/workflows/checks.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("steps:\n  - parallel:\n      - run: true\n", encoding="utf-8")
    message = 'step must run script with "run" section or run action with "uses" section'
    report = [
        {
            "message": message,
            "filepath": ".github/workflows/checks.yml",
            "line": 2,
            "column": 5,
            "end_column": 13,
            "kind": "syntax-check",
        },
        {
            "message": message,
            "filepath": ".github/workflows/other.yml",
            "line": 2,
            "column": 5,
            "end_column": 13,
            "kind": "syntax-check",
        },
    ]
    input_path = tmp_path / "actionlint.json"
    output_path = tmp_path / "actionlint.sarif"
    input_path.write_text(json.dumps(report), encoding="utf-8")

    reportable = reporting.convert_actionlint_sarif(input_path, output_path, tmp_path)
    sarif = json.loads(output_path.read_text(encoding="utf-8"))

    assert reportable == 1
    assert sarif["runs"][0]["results"][0]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] == (
        ".github/workflows/other.yml"
    )


def test_tracking_issue_is_created_once_for_the_finding_set(monkeypatch: pytest.MonkeyPatch) -> None:
    finding = reporting.DeprecationFinding("DeprecationWarning", "site-packages/example.py", 3, "old API")
    calls: list[tuple[str, ...]] = []

    def fake_gh(*args: str) -> str:
        calls.append(args)
        return "[]" if args[:2] == ("issue", "list") else ""

    monkeypatch.setattr(reporting, "_gh", fake_gh)

    reporting.sync_deprecation_issue("owner/repo", [finding], "https://example.test/run/1")

    assert [call[:2] for call in calls] == [
        ("issue", "list"),
        ("label", "create"),
        ("issue", "create"),
    ]


def test_tracking_issue_is_unchanged_for_same_finding_set(monkeypatch: pytest.MonkeyPatch) -> None:
    finding = reporting.DeprecationFinding("DeprecationWarning", "site-packages/example.py", 3, "old API")
    finding_set = reporting._finding_set([finding])
    calls: list[tuple[str, ...]] = []

    def fake_gh(*args: str) -> str:
        calls.append(args)
        return json.dumps(
            [
                {
                    "number": 12,
                    "title": "Dependency deprecation diagnostics",
                    "state": "OPEN",
                    "body": f"<!-- finding-set: {finding_set} -->",
                }
            ]
        )

    monkeypatch.setattr(reporting, "_gh", fake_gh)

    reporting.sync_deprecation_issue("owner/repo", [finding], "https://example.test/run/1")

    assert len(calls) == 1
    assert calls[0][:2] == ("issue", "list")


def test_tracking_issue_updates_in_place_when_findings_change(monkeypatch: pytest.MonkeyPatch) -> None:
    finding = reporting.DeprecationFinding("PendingDeprecationWarning", "src/example.py", 8, "old API")
    calls: list[tuple[str, ...]] = []

    def fake_gh(*args: str) -> str:
        calls.append(args)
        if args[:2] == ("issue", "list"):
            return json.dumps(
                [
                    {
                        "number": 12,
                        "title": "Dependency deprecation diagnostics",
                        "state": "OPEN",
                        "body": f"<!-- finding-set: {'0' * 64} -->",
                    }
                ]
            )
        return ""

    monkeypatch.setattr(reporting, "_gh", fake_gh)

    reporting.sync_deprecation_issue("owner/repo", [finding], "https://example.test/run/2")

    assert [call[:2] for call in calls] == [("issue", "list"), ("issue", "edit")]
    assert all(call[:2] != ("issue", "create") for call in calls)


def test_tracking_issue_selects_tracker_instead_of_first_labeled_issue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    finding = reporting.DeprecationFinding("PendingDeprecationWarning", "src/example.py", 8, "old API")
    calls: list[tuple[str, ...]] = []

    def fake_gh(*args: str) -> str:
        calls.append(args)
        if args[:2] == ("issue", "list"):
            return json.dumps(
                [
                    {"number": 4, "state": "OPEN", "title": "Unrelated", "body": ""},
                    {
                        "number": 12,
                        "state": "OPEN",
                        "title": "Dependency deprecation diagnostics",
                        "body": f"<!-- finding-set: {'0' * 64} -->",
                    },
                ]
            )
        return ""

    monkeypatch.setattr(reporting, "_gh", fake_gh)

    reporting.sync_deprecation_issue("owner/repo", [finding], "https://example.test/run/2")

    assert calls[1][:3] == ("issue", "edit", "12")


def test_tracking_issue_rejects_duplicate_trackers_before_mutation(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_gh(*args: str) -> str:
        calls.append(args)
        return json.dumps(
            [
                {
                    "number": 12,
                    "state": "OPEN",
                    "title": "Dependency deprecation diagnostics",
                    "body": "",
                },
                {
                    "number": 7,
                    "state": "CLOSED",
                    "title": "Renamed",
                    "body": "<!-- dependency-deprecation-tracker -->",
                },
            ]
        )

    monkeypatch.setattr(reporting, "_gh", fake_gh)

    with pytest.raises(RuntimeError, match="multiple dependency deprecation trackers found: 7, 12"):
        reporting.sync_deprecation_issue("owner/repo", [], "https://example.test/run/2")

    assert len(calls) == 1


def test_sweep_overrides_warning_filters_and_ignores_test_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warning = (
        "/workspace/.venv/lib/python3.14/site-packages/google/genai/types.py:42: "
        "DeprecationWarning: '_UnionGenericAlias' is deprecated"
    )
    captured_args: tuple[object, ...] = ()
    synchronized: list[reporting.DeprecationFinding] = []

    async def fake_run(*args: object, **_kwargs: object) -> list[_TestResult]:
        nonlocal captured_args
        captured_args = args
        return [_TestResult(name="nohiki-llm-client", passed=False, output=warning)]

    monkeypatch.setattr(reporting, "_load_testable_packages", lambda _scope: [object()])
    monkeypatch.setattr(reporting, "run_tests_parallel", fake_run)
    monkeypatch.setattr(
        reporting,
        "sync_deprecation_issue",
        lambda _repository, findings, _run_url: synchronized.extend(findings),
    )
    summary = tmp_path / "summary.md"

    reporting.deprecation_sweep_cmd(
        summary=summary,
        repository="owner/repo",
        run_url="https://example.test/run/3",
        workers=2,
    )

    assert captured_args[2] == (
        "-W",
        "always::DeprecationWarning",
        "-W",
        "always::PendingDeprecationWarning",
    )
    rendered = summary.read_text(encoding="utf-8")
    assert synchronized == []
    assert "site-packages/google/genai/types.py:42" in rendered
    assert "test failures ignored (report-only): nohiki-llm-client" in rendered
