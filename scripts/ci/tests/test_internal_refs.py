from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from ci_checks.checks.internal_refs import (
    InternalRefsError,
    load_rules,
    scan_message,
    scan_range,
    scan_text,
)

_ROOT = Path(__file__).parents[3]
_CONFIG = _ROOT / "scripts/ci/config/internal-reference-terms.toml"


def _git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(["git", *arguments], cwd=repository, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _repository(tmp_path: Path) -> Path:
    repository = tmp_path / "repo"
    (repository / "scripts/ci/config").mkdir(parents=True)
    (repository / "scripts/ci/tests").mkdir(parents=True)
    (repository / "scripts/ci/config/internal-reference-terms.toml").write_text(
        _CONFIG.read_text(encoding="utf-8"), encoding="utf-8"
    )
    subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
    _git(repository, "config", "user.name", "Test Owner")
    _git(repository, "config", "user.email", "owner@example.invalid")
    return repository


def _commit(repository: Path, message: str) -> str:
    _git(repository, "add", ".")
    subprocess.run(["git", "commit", "-qm", message], cwd=repository, check=True)
    return _git(repository, "rev-parse", "HEAD")


def test_config_parses_rules_and_scopes() -> None:
    rules = load_rules(_ROOT)
    assert rules
    assert {rule.scope for rule in rules} <= {"message", "diff", "both"}
    assert {rule.rule_id for rule in rules} >= {"workflow-term", "internal-path", "decision-identifier"}
    assert all(rule.allow is not None for rule in rules)


def test_personal_path_patterns_match_runtime_literals() -> None:
    rules = load_rules(_ROOT)
    personal_path = "/" + "home/" + "matt"
    persist_path = "/" + "persist/" + "home"
    findings = scan_text(f"use {personal_path} and {persist_path}", rules, "message", "message")
    assert {finding.rule_id for finding in findings} == {"internal-path"}


def test_planning_path_patterns_still_match() -> None:
    rules = load_rules(_ROOT)
    dot_planning = "." + "planning"
    local_planning = "." + "local/" + "planning"
    findings = scan_text(f"see {dot_planning}/x and {local_planning}/y", rules, "message", "message")
    assert {finding.rule_id for finding in findings} == {"internal-path"}
    assert len(findings) == 2


def test_planted_message_reports_rule_id(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    message = repository / "message"
    workflow_term = "sub" + "agent"
    message.write_text(f"update {workflow_term} planning\n", encoding="utf-8")

    findings = scan_message(str(message), repository)

    assert any(finding.rule_id == "workflow-term" for finding in findings)


def test_planted_added_diff_is_reported_but_removed_text_is_ignored(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    tracked = repository / "tracked.txt"
    tracked.write_text("clean\n", encoding="utf-8")
    base = _commit(repository, "add tracked file")
    workflow_term = "sub" + "agent"
    tracked.write_text(f"{workflow_term} reference\n", encoding="utf-8")
    tip = _commit(repository, "add note")
    findings = scan_range(f"{base}..{tip}", repository)
    assert any(finding.rule_id == "workflow-term" for finding in findings)

    tracked.write_text("clean\n", encoding="utf-8")
    deleted_tip = _commit(repository, "remove note")
    deleted_findings = scan_range(f"{tip}..{deleted_tip}", repository)
    assert deleted_findings == ()


def test_clean_range_passes_and_config_touch_is_exempt(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    clean = repository / "clean.txt"
    clean.write_text("public implementation\n", encoding="utf-8")
    base = _commit(repository, "add clean file")
    clean.write_text("public implementation updated\n", encoding="utf-8")
    tip = _commit(repository, "update clean file")
    assert scan_range(f"{base}..{tip}", repository) == ()

    config = repository / "scripts/ci/config/internal-reference-terms.toml"
    workflow_term = "sub" + "agent"
    config.write_text(
        config.read_text(encoding="utf-8") + f"# {workflow_term} planning\n",
        encoding="utf-8",
    )
    config_tip = _commit(repository, "update scanner config")
    assert scan_range(f"{tip}..{config_tip}", repository) == ()


def test_missing_config_fails_closed(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    (repository / "scripts/ci/config/internal-reference-terms.toml").unlink()

    with pytest.raises(InternalRefsError, match=r"internal-refs:config-error"):
        scan_range("HEAD..HEAD", repository)


def test_malformed_config_fails_closed(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    config = repository / "scripts/ci/config/internal-reference-terms.toml"
    config.write_text("[rules\n", encoding="utf-8")

    with pytest.raises(InternalRefsError, match=r"internal-refs:config-error"):
        scan_range("HEAD..HEAD", repository)
