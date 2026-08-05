#!/usr/bin/env python3
"""Scan GitHub-bound prose without rendering matched text."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import re
import shlex
import stat
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Never, Protocol, TypedDict, cast


@dataclass(frozen=True, slots=True)
class Finding:
    """One redacted disclosure location."""

    rule: str
    line: int
    column: int


@dataclass(frozen=True, slots=True)
class Surface:
    """One GitHub-retained prose surface."""

    pull_request: int
    name: str
    text: str
    node_id: str | None = None
    edit_id: str | None = None
    edited_at: str | None = None
    deleted_at: str | None = None


@dataclass(frozen=True, slots=True)
class SweepResult:
    """Aggregate result of one repository sweep."""

    pull_requests: int
    comments: int
    histories: int
    characters: int
    findings: tuple[tuple[Surface, Finding], ...]


@dataclass(frozen=True, slots=True)
class _EditRef:
    node_id: str
    pull_request: int
    name: str
    typename: str


class _PageInfo(TypedDict):
    hasNextPage: bool
    endCursor: str | None


class _EditRecord(TypedDict):
    id: str
    editedAt: str
    diff: str | None
    deletedAt: str | None


class _EditPage(TypedDict):
    totalCount: int
    pageInfo: _PageInfo
    nodes: list[_EditRecord]


class _Pattern(Protocol):
    expression: re.Pattern[str]


class _VocabularyRule(Protocol):
    id: str
    scope: object
    severity: object
    patterns: Sequence[_Pattern]


class _Config(Protocol):
    vocabulary: Sequence[_VocabularyRule]

    def vocabulary_for(self, path: str, scope: str) -> Sequence[_VocabularyRule]: ...


class _GuardError(RuntimeError):
    """A safe-to-render refusal reason."""


type ApiGet = Callable[[str], object]
type EditGet = Callable[[Sequence[str]], object]


_EXPECTED_POLICY_DIGEST = "d7685e4ee0c63673e71d7dbd778e9a5b260a6f0cd749f0a2f1d0023cf2370547"
_EDIT_HISTORY_QUERY = """
query($ids: [ID!]!) {
  nodes(ids: $ids) {
    __typename
    ... on PullRequest {
      id
      includesCreatedEdit
      lastEditedAt
      userContentEdits(first: 100) {
        totalCount
        pageInfo { hasNextPage endCursor }
        nodes { id diff editedAt deletedAt }
      }
    }
    ... on IssueComment {
      id
      includesCreatedEdit
      lastEditedAt
      userContentEdits(first: 100) {
        totalCount
        pageInfo { hasNextPage endCursor }
        nodes { id diff editedAt deletedAt }
      }
    }
    ... on PullRequestReview {
      id
      includesCreatedEdit
      lastEditedAt
      userContentEdits(first: 100) {
        totalCount
        pageInfo { hasNextPage endCursor }
        nodes { id diff editedAt deletedAt }
      }
    }
    ... on PullRequestReviewComment {
      id
      includesCreatedEdit
      lastEditedAt
      userContentEdits(first: 100) {
        totalCount
        pageInfo { hasNextPage endCursor }
        nodes { id diff editedAt deletedAt }
      }
    }
  }
}
"""


def _fail(message: str) -> Never:
    raise _GuardError(message)


def _configured_value(value: object, field: str) -> str:
    rendered = getattr(value, "value", value)
    if not isinstance(rendered, str) or not rendered:
        _fail(f"private disclosure vocabulary contains an invalid {field}")
    return rendered


def _policy_digest(config: _Config) -> str:
    """Return an opaque digest of the configured vocabulary policy."""
    rules = tuple(config.vocabulary)
    if not rules:
        _fail("no private disclosure vocabulary is configured")
    records: list[tuple[str, str, str, tuple[tuple[str, int], ...]]] = []
    rule_ids: set[str] = set()
    for rule in rules:
        rule_id = _configured_value(getattr(rule, "id", None), "rule identifier")
        if rule_id in rule_ids:
            _fail("private disclosure vocabulary contains duplicate rule identifiers")
        rule_ids.add(rule_id)
        patterns = tuple(getattr(rule, "patterns", ()))
        if not patterns:
            _fail("private disclosure vocabulary contains a rule without patterns")
        expressions: list[tuple[str, int]] = []
        for pattern in patterns:
            expression = getattr(pattern, "expression", None)
            if not isinstance(expression, re.Pattern):
                _fail("private disclosure vocabulary contains an invalid pattern")
            expressions.append((expression.pattern, expression.flags))
        records.append(
            (
                rule_id,
                _configured_value(getattr(rule, "scope", None), "rule scope"),
                _configured_value(getattr(rule, "severity", None), "rule severity"),
                tuple(expressions),
            )
        )
    payload = json.dumps(sorted(records), ensure_ascii=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _active_vocabulary(
    config: _Config,
    expected_policy_digest: str,
) -> tuple[_VocabularyRule, ...]:
    if _policy_digest(config) != expected_policy_digest:
        _fail("private disclosure vocabulary failed its integrity check")
    rules = tuple(config.vocabulary_for("GITHUB_PROSE.txt", "message"))
    enabled = tuple(
        rule for rule in rules if _configured_value(getattr(rule, "severity", None), "rule severity") != "off"
    )
    if not enabled:
        _fail("no private disclosure vocabulary applies to GitHub prose")
    return enabled


def scan_disclosures(
    text: str,
    config: _Config,
    *,
    expected_policy_digest: str = _EXPECTED_POLICY_DIGEST,
) -> tuple[Finding, ...]:
    """Return redacted findings derived only from configured vocabulary patterns."""
    findings: set[Finding] = set()
    lines = text.splitlines()
    for rule in _active_vocabulary(config, expected_policy_digest):
        rule_id = _configured_value(getattr(rule, "id", None), "rule identifier")
        for pattern in tuple(getattr(rule, "patterns", ())):
            expression = getattr(pattern, "expression", None)
            if not isinstance(expression, re.Pattern):
                _fail("private disclosure vocabulary contains an invalid pattern")
            for line_number, line in enumerate(lines, start=1):
                for match in expression.finditer(line):
                    if match.start() == match.end():
                        _fail("private disclosure vocabulary contains an empty pattern")
                    findings.add(Finding(rule_id, line_number, match.start() + 1))
    return tuple(sorted(findings, key=lambda item: (item.line, item.column, item.rule)))


def _repository_root() -> Path:
    completed = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
    )
    root = completed.stdout.rstrip("\n")
    if not root or "\n" in root:
        _fail("Git returned an invalid repository root")
    return Path(root)


def _hook_assignments(repository: Path) -> Mapping[str, str]:
    completed = subprocess.run(
        ["git", "rev-parse", "--git-path", "hooks/pre-push"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    rendered = completed.stdout.rstrip("\n")
    if not rendered or "\n" in rendered:
        _fail("Git returned an invalid pre-push hook path")
    hook = Path(rendered) if Path(rendered).is_absolute() else repository / rendered
    assignments: dict[str, str] = {}
    required = {"PYTHON", "GIT", "GH"}
    for line in hook.read_text(encoding="utf-8").splitlines():
        name, separator, value = line.partition("=")
        if (
            not separator
            or re.fullmatch(r"[A-Z][A-Z0-9_]*", name) is None
            or (name not in required and not name.endswith("_TREE") and not name.endswith("_TREE_SHA256"))
        ):
            continue
        words = shlex.split(value, posix=True)
        if len(words) != 1:
            _fail("invalid pinned-tool assignment in pre-push hook")
        assignments[name] = words[0]
    tree_names = {name for name in assignments if name.endswith("_TREE")}
    if len(tree_names) != 1:
        _fail("the installed pre-push hook does not expose one private policy tree")
    tree_name = next(iter(tree_names))
    wanted = required | {tree_name, f"{tree_name}_SHA256"}
    if wanted.difference(assignments):
        _fail("the installed pre-push hook does not expose all pinned tools")
    return assignments


def _policy_package(root: Path) -> str:
    packages = tuple(
        entry.name for entry in (root / "src").iterdir() if entry.is_dir() and (entry / "config.py").is_file()
    )
    if len(packages) != 1:
        _fail("the installed private policy tree has an invalid package layout")
    return packages[0]


def _policy_tree_digest(root: Path) -> str:
    info = root.lstat()
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        _fail("the installed private policy tree is not a directory")
    records: list[tuple[bytes, bytes, bytes]] = []
    for directory, directory_names, file_names in os.walk(root, followlinks=False):
        directory_names.sort(key=os.fsencode)
        file_names.sort(key=os.fsencode)
        current = Path(directory)
        for name in (*directory_names, *file_names):
            path = current / name
            relative = os.fsencode(path.relative_to(root).as_posix())
            entry = path.lstat()
            if stat.S_ISDIR(entry.st_mode) and not stat.S_ISLNK(entry.st_mode):
                records.append((relative, b"040000", b""))
            elif stat.S_ISREG(entry.st_mode) and not stat.S_ISLNK(entry.st_mode):
                mode = b"100755" if stat.S_IMODE(entry.st_mode) == 0o700 else b"100644"
                records.append(
                    (
                        relative,
                        mode,
                        hashlib.sha256(path.read_bytes()).hexdigest().encode(),
                    )
                )
            else:
                _fail("the installed private policy tree contains an unsupported entry")
    package = _policy_package(root)
    digest = hashlib.sha256(f"{package}-tree-v1\0".encode())
    for relative, mode, content_digest in sorted(records):
        digest.update(mode)
        digest.update(b"\0")
        digest.update(str(len(relative)).encode())
        digest.update(b":")
        digest.update(relative)
        digest.update(b"\0")
        digest.update(content_digest)
        digest.update(b"\n")
    return digest.hexdigest()


def _load_guard(repository: Path) -> tuple[_Config, str]:
    pins = _hook_assignments(repository)
    tree_name = next(name for name in pins if name.endswith("_TREE"))
    tree = Path(pins[tree_name])
    if _policy_tree_digest(tree) != pins[f"{tree_name}_SHA256"]:
        _fail("the installed private policy tree failed its integrity check")
    git_dir = str(Path(pins["GIT"]).parent)
    os.environ["PATH"] = f"{git_dir}{os.pathsep}{os.environ.get('PATH', '')}"
    sys.path.insert(0, str(tree / "src"))
    sys.dont_write_bytecode = True
    module = importlib.import_module(f"{_policy_package(tree)}.config")
    load_config = getattr(module, "load_config", None)
    if not callable(load_config):
        _fail("the installed private policy package has no configuration loader")
    loader = cast(Callable[[Path], object], load_config)
    return cast(_Config, loader(repository)), pins["GH"]


def _gh_json(gh: str, repository: Path, endpoint: str, *, paginate: bool) -> object:
    command = [gh, "api", "--method", "GET"]
    if paginate:
        command.extend(("--paginate", "--slurp"))
    command.append(endpoint)
    completed = subprocess.run(
        command,
        cwd=repository,
        check=False,
        capture_output=True,
        timeout=60,
    )
    if completed.returncode != 0:
        _fail(f"GitHub API request failed with exit status {completed.returncode}")
    try:
        return json.loads(completed.stdout)
    except UnicodeDecodeError, json.JSONDecodeError:
        _fail("GitHub API returned malformed JSON")


def _gh_edit_history(gh: str, repository: Path, node_ids: Sequence[str]) -> object:
    nodes: list[object] = []
    for offset in range(0, len(node_ids), 100):
        payload = json.dumps(
            {
                "query": _EDIT_HISTORY_QUERY,
                "variables": {"ids": list(node_ids[offset : offset + 100])},
            },
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode()
        completed = subprocess.run(
            [gh, "api", "graphql", "--input", "-"],
            cwd=repository,
            check=False,
            capture_output=True,
            input=payload,
            timeout=60,
        )
        if completed.returncode != 0:
            _fail(f"GitHub GraphQL request failed with exit status {completed.returncode}")
        try:
            response = json.loads(completed.stdout)
        except UnicodeDecodeError, json.JSONDecodeError:
            _fail("GitHub GraphQL returned malformed JSON")
        if (
            not isinstance(response, dict)
            or "errors" in response
            or not isinstance(data := response.get("data"), dict)
            or not isinstance(page := data.get("nodes"), list)
        ):
            _fail("GitHub GraphQL returned malformed edit history")
        nodes.extend(page)
    return nodes


def _pages(value: object, surface: str) -> list[object]:
    if not isinstance(value, list) or any(not isinstance(page, list) for page in value):
        _fail(f"GitHub API returned malformed {surface} pages")
    pages = cast(list[list[object]], value)
    return [item for page in pages for item in page]


def _object_mapping(value: object, failure: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        _fail(failure)
    return cast(dict[str, object], value)


def _required_int(item: object, key: str, surface: str) -> int:
    values = _object_mapping(item, f"GitHub API returned malformed {surface}")
    if type(value := values.get(key)) is not int:
        _fail(f"GitHub API returned malformed {surface}")
    return value


def _required_string(item: object, key: str, surface: str) -> str:
    values = _object_mapping(item, f"GitHub API returned malformed {surface}")
    if not isinstance(value := values.get(key), str) or not value:
        _fail(f"GitHub API returned malformed {surface}")
    return value


def _body(item: object, key: str, surface: str) -> str:
    values = _object_mapping(item, f"GitHub API returned malformed {surface}")
    if key not in values:
        _fail(f"GitHub API returned malformed {surface}")
    value = values[key]
    if value is not None and not isinstance(value, str):
        _fail(f"GitHub API returned malformed {surface}")
    return "" if value is None else value


def _url_number(item: object, key: str, surface: str) -> int:
    values = _object_mapping(item, f"GitHub API returned malformed {surface}")
    if not isinstance(value := values.get(key), str):
        _fail(f"GitHub API returned malformed {surface}")
    rendered = value.rstrip("/").rsplit("/", 1)[-1]
    if not rendered.isascii() or not rendered.isdigit():
        _fail(f"GitHub API returned malformed {surface}")
    return int(rendered)


def _edit_page(value: object) -> _EditPage:
    failure = "GitHub GraphQL returned malformed edit history"
    page = _object_mapping(value, failure)
    if type(total := page.get("totalCount")) is not int or total < 0:
        _fail(failure)

    page_info_value = _object_mapping(page.get("pageInfo"), failure)
    if type(has_next_page := page_info_value.get("hasNextPage")) is not bool:
        _fail(failure)
    end_cursor = page_info_value.get("endCursor")
    if end_cursor is not None and not isinstance(end_cursor, str):
        _fail(failure)

    record_values = page.get("nodes")
    if not isinstance(record_values, list) or len(record_values) != total:
        _fail("GitHub GraphQL returned incomplete edit history")
    records: list[_EditRecord] = []
    for record_value in record_values:
        record = _object_mapping(record_value, "GitHub GraphQL returned malformed edit history record")
        edit_id = _required_string(record, "id", "edit history record")
        edited_at = _required_string(record, "editedAt", "edit history record")
        if "diff" not in record or "deletedAt" not in record:
            _fail("GitHub GraphQL returned malformed edit history record")
        diff = record["diff"]
        deleted_at = record["deletedAt"]
        if (diff is not None and not isinstance(diff, str)) or (
            deleted_at is not None and not isinstance(deleted_at, str)
        ):
            _fail("GitHub GraphQL returned malformed edit history record")
        records.append(
            {
                "id": edit_id,
                "editedAt": edited_at,
                "diff": diff,
                "deletedAt": deleted_at,
            }
        )
    return {
        "totalCount": total,
        "pageInfo": {
            "hasNextPage": has_next_page,
            "endCursor": end_cursor,
        },
        "nodes": records,
    }


def _history_surfaces(value: object, refs: Sequence[_EditRef]) -> tuple[Surface, ...]:
    if not isinstance(value, list):
        _fail("GitHub GraphQL returned malformed edit history")
    expected = {ref.node_id: ref for ref in refs}
    if len(expected) != len(refs) or len(value) != len(expected):
        _fail("GitHub GraphQL returned incomplete edit history")

    seen: set[str] = set()
    surfaces: list[Surface] = []
    for node in value:
        node_values = _object_mapping(node, "GitHub GraphQL returned malformed edit history")
        node_id = _required_string(node_values, "id", "edit history node")
        typename = _required_string(node_values, "__typename", "edit history node")
        ref = expected.get(node_id)
        if ref is None or typename != ref.typename or node_id in seen:
            _fail("GitHub GraphQL returned mismatched edit history")
        seen.add(node_id)
        if type(node_values.get("includesCreatedEdit")) is not bool:
            _fail("GitHub GraphQL returned malformed edit history")
        last_edited = node_values.get("lastEditedAt")
        if last_edited is not None and not isinstance(last_edited, str):
            _fail("GitHub GraphQL returned malformed edit history")
        edits = _edit_page(node_values.get("userContentEdits"))
        if edits["pageInfo"]["hasNextPage"]:
            _fail("GitHub GraphQL truncated edit history")
        for record in edits["nodes"]:
            if record["diff"] is None and record["deletedAt"] is None:
                _fail("GitHub GraphQL returned unavailable edit history")
            surfaces.append(
                Surface(
                    ref.pull_request,
                    f"{ref.name}-history",
                    "" if record["diff"] is None else record["diff"],
                    node_id,
                    record["id"],
                    record["editedAt"],
                    record["deletedAt"],
                )
            )
    if seen != expected.keys():
        _fail("GitHub GraphQL returned incomplete edit history")
    return tuple(surfaces)


def fetch_surfaces(
    api_get: ApiGet,
    edit_get: EditGet,
    repository_name: str,
    pull_request: int | None,
) -> tuple[Surface, ...]:
    """Fetch every retained pull-request text surface, failing on malformed data."""
    base = f"repos/{repository_name}"
    if pull_request is None:
        pulls = _pages(api_get(f"{base}/pulls?state=all&per_page=100"), "pull request")
        if not pulls:
            _fail("GitHub API returned no pull requests")
        numbers = {_required_int(item, "number", "pull request") for item in pulls}
        issue_comments = _pages(api_get(f"{base}/issues/comments?per_page=100"), "comment")
        review_comments = _pages(api_get(f"{base}/pulls/comments?per_page=100"), "review comment")
    else:
        item = api_get(f"{base}/pulls/{pull_request}")
        if _required_int(item, "number", "pull request") != pull_request:
            _fail("GitHub API returned the wrong pull request")
        pulls = [item]
        numbers = {pull_request}
        issue_comments = _pages(api_get(f"{base}/issues/{pull_request}/comments?per_page=100"), "comment")
        review_comments = _pages(api_get(f"{base}/pulls/{pull_request}/comments?per_page=100"), "review comment")
    review_summaries: list[tuple[int, object]] = []
    for number in sorted(numbers):
        reviews = _pages(
            api_get(f"{base}/pulls/{number}/reviews?per_page=100"),
            "review summary",
        )
        review_summaries.extend((number, item) for item in reviews)

    surfaces: list[Surface] = []
    refs: list[_EditRef] = []
    for item in pulls:
        number = _required_int(item, "number", "pull request")
        title = _body(item, "title", "pull request title")
        if not title:
            _fail("GitHub API returned an empty pull request title")
        body = _body(item, "body", "pull request body")
        node_id = _required_string(item, "node_id", "pull request")
        surfaces.extend(
            (
                Surface(number, "title", title, node_id),
                Surface(number, "body", body, node_id),
            )
        )
        refs.append(_EditRef(node_id, number, "title/body", "PullRequest"))
    for item in issue_comments:
        number = pull_request if pull_request is not None else _url_number(item, "issue_url", "comment")
        if number in numbers:
            body = _body(item, "body", "comment")
            node_id = _required_string(item, "node_id", "comment")
            surfaces.append(Surface(number, "comment", body, node_id))
            refs.append(_EditRef(node_id, number, "comment", "IssueComment"))
    for number, item in review_summaries:
        body = _body(item, "body", "review summary")
        node_id = _required_string(item, "node_id", "review summary")
        surfaces.append(Surface(number, "review-summary", body, node_id))
        refs.append(_EditRef(node_id, number, "review-summary", "PullRequestReview"))
    for item in review_comments:
        number = pull_request if pull_request is not None else _url_number(item, "pull_request_url", "review comment")
        if number in numbers:
            body = _body(item, "body", "review comment")
            node_id = _required_string(item, "node_id", "review comment")
            surfaces.append(Surface(number, "review-comment", body, node_id))
            refs.append(_EditRef(node_id, number, "review-comment", "PullRequestReviewComment"))
    surfaces.extend(_history_surfaces(edit_get([ref.node_id for ref in refs]), refs))
    return tuple(surfaces)


def sweep(
    surfaces: Sequence[Surface],
    config: _Config,
    *,
    expected_policy_digest: str = _EXPECTED_POLICY_DIGEST,
) -> SweepResult:
    """Scan fetched surfaces and prove that the payload was nonempty."""
    if not surfaces:
        _fail("the sweep fetched no prose surfaces")
    pull_requests = {surface.pull_request for surface in surfaces}
    characters = sum(len(surface.text) for surface in surfaces)
    if characters == 0:
        _fail("the sweep fetched no prose content")
    findings = tuple(
        (surface, finding)
        for surface in surfaces
        for finding in scan_disclosures(
            surface.text,
            config,
            expected_policy_digest=expected_policy_digest,
        )
    )
    comments = sum(surface.name in {"comment", "review-comment"} for surface in surfaces)
    histories = sum(surface.name.endswith("-history") for surface in surfaces)
    return SweepResult(len(pull_requests), comments, histories, characters, findings)


def _repository_name(gh: str, repository: Path) -> str:
    completed = subprocess.run(
        [gh, "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        _fail(f"GitHub repository lookup failed with exit status {completed.returncode}")
    name = completed.stdout.strip()
    if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", name) is None:
        _fail("GitHub repository lookup returned an invalid name")
    return name


def _render_input(findings: Sequence[Finding]) -> None:
    for finding in findings:
        sys.stderr.write(f"github-prose-guard: input:{finding.line}:{finding.column}: [{finding.rule}] disclosure\n")


def _render_sweep(result: SweepResult) -> None:
    sys.stdout.write(
        "github-prose-guard: "
        f"fetched {result.pull_requests} pull requests, {result.comments} comments, "
        f"{result.histories} retained edit records, {result.characters} characters\n"
        "github-prose-guard: deleted nodes are not enumerable through GitHub APIs; this audit is read-only\n"
    )
    for surface, finding in result.findings:
        metadata = ""
        if surface.node_id is not None:
            metadata += f" node={surface.node_id}"
        if surface.edit_id is not None:
            metadata += f" edit={surface.edit_id}"
        if surface.edited_at is not None:
            metadata += f" editedAt={surface.edited_at}"
        if surface.deleted_at is not None:
            metadata += f" deletedAt={surface.deleted_at}"
        sys.stderr.write(
            "github-prose-guard: "
            f"PR #{surface.pull_request} {surface.name}{metadata}:"
            f"{finding.line}:{finding.column}: [{finding.rule}] disclosure\n"
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="github-prose-guard", allow_abbrev=False)
    commands = parser.add_subparsers(dest="command", required=True)
    scan = commands.add_parser("scan", allow_abbrev=False)
    scan.add_argument("path", nargs="?", default="-", type=Path)
    audit = commands.add_parser("sweep", allow_abbrev=False)
    audit.add_argument("--pr", type=int)
    return parser


def _execute(arguments: argparse.Namespace) -> int:
    repository = _repository_root()
    config, gh = _load_guard(repository)
    if arguments.command == "scan":
        path = cast(Path, arguments.path)
        text = sys.stdin.read() if str(path) == "-" else path.read_text(encoding="utf-8")
        findings = scan_disclosures(text, config)
        _render_input(findings)
        return 1 if findings else 0
    pull_request = cast(int | None, arguments.pr)
    if pull_request is not None and pull_request <= 0:
        _fail("pull request number must be positive")
    name = _repository_name(gh, repository)

    def api_get(endpoint: str) -> object:
        return _gh_json(gh, repository, endpoint, paginate="?" in endpoint)

    def edit_get(node_ids: Sequence[str]) -> object:
        return _gh_edit_history(gh, repository, node_ids)

    result = sweep(fetch_surfaces(api_get, edit_get, name, pull_request), config)
    _render_sweep(result)
    return 1 if result.findings else 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the disclosure guard command."""
    arguments = _parser().parse_args(argv)
    try:
        result = _execute(arguments)
    except _GuardError as error:
        sys.stderr.write(f"github-prose-guard: error: {error}\n")
        return 2
    except OSError, subprocess.SubprocessError:
        sys.stderr.write("github-prose-guard: error: local operation failed\n")
        return 2
    except Exception:  # noqa: BLE001 - an unexpected scanner failure must refuse publication
        sys.stderr.write("github-prose-guard: error: unexpected scanner failure\n")
        return 2
    else:
        return result


if __name__ == "__main__":
    raise SystemExit(main())
