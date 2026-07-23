"""Repository-owned checks for internal tooling references."""

from __future__ import annotations

import re
import subprocess
import sys
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from re import Pattern
from typing import Literal, NoReturn, cast

import typer

Scope = Literal["message", "diff", "both"]
_CONFIG_RELATIVE = Path("scripts/ci/config/internal-reference-terms.toml")
_TEST_RELATIVE = Path("scripts/ci/tests/test_internal_refs.py")


class InternalRefsError(Exception):
    """A fail-closed scanner error with a diagnostic rule id."""

    def __init__(self, rule_id: str, detail: str) -> None:
        """Build a diagnostic carrying the stable rule id."""
        super().__init__(f"[internal-refs:{rule_id}] {detail}")
        self.rule_id = rule_id


def _fail(rule_id: str, detail: str) -> NoReturn:
    error = InternalRefsError(rule_id, detail)
    raise error


@dataclass(frozen=True)
class Rule:
    """One configured internal-reference rule."""

    rule_id: str
    description: str
    scope: Scope
    patterns: tuple[Pattern[str], ...]
    allow: tuple[Pattern[str], ...]


@dataclass(frozen=True)
class Finding:
    """One forbidden match in scanned text."""

    rule_id: str
    source: str
    line: int
    matched: str

    def diagnostic(self) -> str:
        """Render this finding as a rule-id-tagged diagnostic."""
        return f"[internal-refs:{self.rule_id}] {self.source}:{self.line}: {self.matched!r}"


def _repo_root() -> Path:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            cwd=Path.cwd(),
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        error = InternalRefsError("git-error", f"cannot locate repository root: {detail.strip()}")
        raise error from exc
    root = result.stdout.strip()
    if not root:
        _fail("git-error", "git returned an empty repository root")
    return Path(root)


def _mapping(value: object, context: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        _fail("config-error", f"{context} must be a table")
    return cast(Mapping[str, object], value)


def _required_string(table: Mapping[str, object], key: str, context: str) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value:
        _fail("config-error", f"{context}.{key} must be a non-empty string")
    return value


def _regex_list(table: Mapping[str, object], key: str, context: str) -> tuple[Pattern[str], ...]:
    value = table.get(key)
    if (
        not isinstance(value, list)
        or (key == "regex" and not value)
        or not all(isinstance(item, str) and item for item in value)
    ):
        _fail("config-error", f"{context}.{key} must be a string list")
    patterns: list[Pattern[str]] = []
    for index, expression in enumerate(cast(list[object], value)):
        try:
            patterns.append(re.compile(cast(str, expression), re.IGNORECASE))
        except re.error as exc:
            error = InternalRefsError("config-error", f"{context}.{key}[{index}] is invalid: {exc}")
            raise error from exc
    return tuple(patterns)


def load_rules(repo_root: Path | None = None) -> tuple[Rule, ...]:
    """Load and validate the versioned term configuration."""
    root = repo_root or _repo_root()
    path = root / _CONFIG_RELATIVE
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        error = InternalRefsError("config-error", f"cannot load {path}: {exc}")
        raise error from exc
    table = _mapping(document, "root")
    raw_rules = table.get("rules")
    if not isinstance(raw_rules, list) or not raw_rules:
        _fail("config-error", "root.rules must be a non-empty table list")

    rules: list[Rule] = []
    for index, raw_rule in enumerate(cast(list[object], raw_rules)):
        context = f"rules[{index}]"
        rule = _mapping(raw_rule, context)
        rule_id = _required_string(rule, "id", context)
        description = _required_string(rule, "description", context)
        if "allow" not in rule:
            _fail("config-error", f"{context}.allow must be a string list")
        allow = _regex_list(rule, "allow", context)
        scope_value = _required_string(rule, "scope", context)
        if scope_value not in {"message", "diff", "both"}:
            _fail("config-error", f"{context}.scope must be message, diff, or both")
        rules.append(
            Rule(
                rule_id=rule_id,
                description=description,
                scope=cast(Scope, scope_value),
                patterns=_regex_list(rule, "regex", context),
                allow=allow,
            )
        )
    return tuple(rules)


def _allowed(rule: Rule, matched: str) -> bool:
    return any(pattern.search(matched) is not None for pattern in rule.allow)


def scan_text(
    text: str, rules: tuple[Rule, ...], scope: Literal["message", "diff"], source: str
) -> tuple[Finding, ...]:
    """Scan text for rules applicable to one input scope."""
    findings: list[Finding] = []
    for rule in rules:
        if rule.scope not in {scope, "both"}:
            continue
        for pattern in rule.patterns:
            for match in pattern.finditer(text):
                matched = match.group(0)
                if _allowed(rule, matched):
                    continue
                findings.append(
                    Finding(
                        rule_id=rule.rule_id,
                        source=source,
                        line=text.count("\n", 0, match.start()) + 1,
                        matched=matched,
                    )
                )
    return tuple(findings)


def scan_message(message_file: str, repo_root: Path | None = None) -> tuple[Finding, ...]:
    """Scan one commit message file, or standard input when ``message_file`` is ``-``."""
    rules = load_rules(repo_root)
    try:
        text = sys.stdin.read() if message_file == "-" else Path(message_file).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        error = InternalRefsError("input-error", f"cannot read commit message {message_file}: {exc}")
        raise error from exc
    return scan_text(text, rules, "message", message_file)


def _git_log(root: Path, arguments: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", "log", *arguments],
            check=True,
            capture_output=True,
            cwd=root,
            text=True,
        )
    except (OSError, UnicodeError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        error = InternalRefsError("git-error", f"git log failed: {detail.strip()}")
        raise error from exc
    return result.stdout


def _patch_chunks(patch_text: str) -> tuple[tuple[str, str], ...]:
    chunks = re.split(r"(?m)(?=^diff --git )", patch_text)
    if patch_text and not any(chunk.startswith("diff --git ") for chunk in chunks):
        _fail("git-error", "git produced a patch without diff headers")
    parsed: list[tuple[str, str]] = []
    for chunk in chunks:
        if not chunk.startswith("diff --git "):
            continue
        header = chunk.splitlines()[0]
        match = re.fullmatch(r"diff --git a/(\S+) b/(\S+)", header)
        if match is None:
            _fail("git-error", f"cannot parse patch header: {header}")
        parsed.append((match.group(1), chunk))
    return tuple(parsed)


def _added_patch_text(chunk: str) -> str:
    return "\n".join(line for line in chunk.splitlines() if line.startswith("+") and not line.startswith("+++"))


def _is_exempt(path: str) -> bool:
    relative = Path(path)
    return relative in {_CONFIG_RELATIVE, _TEST_RELATIVE}


def scan_range(range_spec: str, repo_root: Path | None = None) -> tuple[Finding, ...]:
    """Scan messages and additions in outgoing patches for a revision range.

    Patch scanning is additions-only so cleanup commits can remove already-present
    history contamination without re-reporting the text they remove. Gitleaks
    remains responsible for detecting deleted secrets.
    """
    if not range_spec or not range_spec.strip() or range_spec.count("..") != 1:
        _fail("input-error", "range must be a non-empty A..B revision pair")
    left, right = (part.strip() for part in range_spec.split(".."))
    if not left or not right:
        _fail("input-error", "range must be a non-empty A..B revision pair")

    root = repo_root or _repo_root()
    rules = load_rules(root)
    revision_range = f"{left}..{right}"
    messages = _git_log(root, ["--format=%B", revision_range])
    findings = list(scan_text(messages, rules, "message", f"range {revision_range} messages"))
    patch_text = _git_log(root, ["-p", "--no-ext-diff", "--format=", revision_range])
    for path, chunk in _patch_chunks(patch_text):
        if _is_exempt(path):
            continue
        if "new file mode " in chunk:
            findings.extend(scan_text(path, rules, "diff", path))
        added_text = _added_patch_text(chunk)
        findings.extend(scan_text(added_text, rules, "diff", path))
    return tuple(findings)


def internal_refs_cmd(
    message: str | None = typer.Option(None, "--message", help="Commit message file, or - for standard input"),
    range_ref: str | None = typer.Option(None, "--range", help="Outgoing revision range A..B"),
) -> None:
    """Block internal tooling references in commit messages and outgoing history."""
    if (message is None) == (range_ref is None):
        parameter_error = "provide exactly one of --message or --range"
        raise typer.BadParameter(parameter_error)
    try:
        findings = scan_message(message) if message is not None else scan_range(cast(str, range_ref))
    except InternalRefsError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    if findings:
        for finding in findings:
            typer.echo(finding.diagnostic(), err=True)
        raise typer.Exit(1)
    typer.echo("internal-refs: clean")
