"""Minimal CEL-subset predicate engine for ``applies_when``.

This is **not** a full CEL implementation — it is a deterministic, three-
predicate boolean mini-language. Every expression is written in a strict
subset so it round-trips 1:1 to real CEL if we later swap in a full
CEL engine.

Supported grammar (PEG-style):

    expression  := or_expr
    or_expr     := and_expr ( 'or' and_expr )*
    and_expr    := not_expr ( 'and' not_expr )*
    not_expr    := 'not' not_expr | atom
    atom        := '(' expression ')' | predicate | 'true' | 'false'
    predicate   := name '(' string_arg ')'
    name        := 'has_tag' | 'schema_has_path' | 'has_sibling'
    string_arg  := '"' ... '"' | "'" ... "'"

Semantics:
- ``has_tag('x')`` — ``'x' in runtime.active_tags``
- ``schema_has_path('a.b.c')`` — ``navigate(data, 'a.b.c')`` is not None
- ``has_sibling('name')`` — ``'name' in runtime.sibling_documents``
- ``and`` / ``or`` — short-circuit boolean operators
- ``not`` — unary negation

Errors are reported as ``LintConfigError`` at expression-compile time.
Expressions are compiled once on load and re-evaluated per rule dispatch.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from tailor.exceptions import LintConfigError
from tailor.lint.content.rules.path_resolver import navigate

if TYPE_CHECKING:
    from tailor.lint.runtime import LintRuntimeContext

# Tokenizer

_TOKEN_RE = re.compile(
    r"""
    \s+                       | # whitespace (skipped)
    (?P<lparen>\()            |
    (?P<rparen>\))            |
    (?P<comma>,)              |
    (?P<string>"[^"]*"|'[^']*') |
    (?P<ident>[A-Za-z_][A-Za-z0-9_]*)
    """,
    re.VERBOSE,
)

_KEYWORDS: frozenset[str] = frozenset({"and", "or", "not", "true", "false"})
_PREDICATE_NAMES: frozenset[str] = frozenset({"has_tag", "schema_has_path", "has_sibling"})


@dataclass(frozen=True, slots=True)
class _Token:
    kind: str  # "lparen" | "rparen" | "comma" | "string" | "ident" | "keyword"
    value: str
    pos: int  # character offset for error reporting


def _tokenize(src: str) -> list[_Token]:
    """Tokenize a CEL-subset expression. Raises ``LintConfigError`` on unknown chars."""
    tokens: list[_Token] = []
    pos = 0
    length = len(src)
    while pos < length:
        if src[pos].isspace():
            pos += 1
            continue
        match = _TOKEN_RE.match(src, pos)
        if match is None:
            msg = f"Unexpected character {src[pos]!r} at position {pos} in: {src!r}"
            raise LintConfigError(msg)
        end = match.end()
        if (val := match.group("lparen")) is not None:
            tokens.append(_Token("lparen", val, pos))
        elif (val := match.group("rparen")) is not None:
            tokens.append(_Token("rparen", val, pos))
        elif (val := match.group("comma")) is not None:
            tokens.append(_Token("comma", val, pos))
        elif (val := match.group("string")) is not None:
            # Strip the surrounding quotes; the value carries only the content.
            tokens.append(_Token("string", val[1:-1], pos))
        elif (val := match.group("ident")) is not None:
            kind = "keyword" if val in _KEYWORDS else "ident"
            tokens.append(_Token(kind, val, pos))
        pos = end
    return tokens


# AST

# Evaluator callables take (data, runtime) and return bool.
_EvalFn = Callable[[dict[str, object], "LintRuntimeContext"], bool]


@dataclass(frozen=True, slots=True)
class CompiledPredicate:
    """A parsed + compiled ``applies_when`` expression, ready for repeated evaluation.

    Attributes:
        source: Original expression text (for diagnostic messages).
        evaluate: Bound callable that returns ``bool`` for a ``(data, runtime)`` pair.
    """

    source: str
    evaluate: _EvalFn


# Parser


class _Parser:
    """Recursive-descent parser for the CEL-subset grammar."""

    def __init__(self, tokens: list[_Token], source: str) -> None:
        self._tokens = tokens
        self._source = source
        self._pos = 0

    def parse(self) -> _EvalFn:
        """Parse a full expression; assert EOF afterwards."""
        expr = self._parse_or()
        if self._pos != len(self._tokens):
            tok = self._tokens[self._pos]
            msg = f"Unexpected token {tok.value!r} at position {tok.pos} in: {self._source!r}"
            raise LintConfigError(msg)
        return expr

    def _peek(self) -> _Token | None:
        return self._tokens[self._pos] if self._pos < len(self._tokens) else None

    def _advance(self) -> _Token:
        tok = self._tokens[self._pos]
        self._pos += 1
        return tok

    def _match_keyword(self, keyword: str) -> bool:
        tok = self._peek()
        if tok is not None and tok.kind == "keyword" and tok.value == keyword:
            self._advance()
            return True
        return False

    def _expect(self, kind: str) -> _Token:
        tok = self._peek()
        if tok is None or tok.kind != kind:
            got = tok.value if tok is not None else "<end>"
            msg = f"Expected {kind!r}, got {got!r} in: {self._source!r}"
            raise LintConfigError(msg)
        return self._advance()

    def _parse_or(self) -> _EvalFn:
        left = self._parse_and()
        while self._match_keyword("or"):
            right = self._parse_and()
            left = _or(left, right)
        return left

    def _parse_and(self) -> _EvalFn:
        left = self._parse_not()
        while self._match_keyword("and"):
            right = self._parse_not()
            left = _and(left, right)
        return left

    def _parse_not(self) -> _EvalFn:
        if self._match_keyword("not"):
            inner = self._parse_not()
            return _not(inner)
        return self._parse_atom()

    def _parse_atom(self) -> _EvalFn:
        tok = self._peek()
        if tok is None:
            msg = f"Unexpected end of expression: {self._source!r}"
            raise LintConfigError(msg)

        if tok.kind == "lparen":
            self._advance()
            expr = self._parse_or()
            self._expect("rparen")
            return expr

        if tok.kind == "keyword" and tok.value in ("true", "false"):
            self._advance()
            literal = tok.value == "true"
            return _const(value=literal)

        if tok.kind == "ident":
            return self._parse_predicate()

        msg = f"Unexpected token {tok.value!r} at position {tok.pos} in: {self._source!r}"
        raise LintConfigError(msg)

    def _parse_predicate(self) -> _EvalFn:
        name_tok = self._advance()
        if name_tok.value not in _PREDICATE_NAMES:
            allowed = ", ".join(sorted(_PREDICATE_NAMES))
            msg = (
                f"Unknown predicate {name_tok.value!r} at position {name_tok.pos} "
                f"(allowed: {allowed}) in: {self._source!r}"
            )
            raise LintConfigError(msg)
        self._expect("lparen")
        arg_tok = self._expect("string")
        self._expect("rparen")

        match name_tok.value:
            case "has_tag":
                return _has_tag(arg_tok.value)
            case "schema_has_path":
                return _schema_has_path(arg_tok.value)
            case "has_sibling":
                return _has_sibling(arg_tok.value)
            case _:  # pragma: no cover — defended by _PREDICATE_NAMES above.
                msg = f"Unreachable: predicate {name_tok.value!r}"
                raise LintConfigError(msg)


# Evaluator constructors (closures over captured args)


def _and(left: _EvalFn, right: _EvalFn) -> _EvalFn:
    def _run(data: dict[str, object], runtime: LintRuntimeContext) -> bool:
        return left(data, runtime) and right(data, runtime)

    return _run


def _or(left: _EvalFn, right: _EvalFn) -> _EvalFn:
    def _run(data: dict[str, object], runtime: LintRuntimeContext) -> bool:
        return left(data, runtime) or right(data, runtime)

    return _run


def _not(inner: _EvalFn) -> _EvalFn:
    def _run(data: dict[str, object], runtime: LintRuntimeContext) -> bool:
        return not inner(data, runtime)

    return _run


def _const(*, value: bool) -> _EvalFn:
    def _run(_data: dict[str, object], _runtime: LintRuntimeContext) -> bool:
        return value

    return _run


def _has_tag(tag: str) -> _EvalFn:
    def _run(_data: dict[str, object], runtime: LintRuntimeContext) -> bool:
        return tag in runtime.active_tags

    return _run


def _schema_has_path(path: str) -> _EvalFn:
    def _run(data: dict[str, object], _runtime: LintRuntimeContext) -> bool:
        return navigate(data, path) is not None

    return _run


def _has_sibling(name: str) -> _EvalFn:
    def _run(_data: dict[str, object], runtime: LintRuntimeContext) -> bool:
        return name in runtime.sibling_documents

    return _run


# Public compile entry point


def compile_predicate(source: str) -> CompiledPredicate:
    """Compile an ``applies_when`` expression into a callable predicate.

    Args:
        source: CEL-subset expression text.

    Returns:
        ``CompiledPredicate`` whose ``evaluate`` method returns ``bool``.

    Raises:
        LintConfigError: Tokenization or parsing fails.
    """
    tokens = _tokenize(source)
    if not tokens:
        msg = f"Empty applies_when expression: {source!r}"
        raise LintConfigError(msg)
    parser = _Parser(tokens, source)
    fn = parser.parse()
    return CompiledPredicate(source=source, evaluate=fn)
