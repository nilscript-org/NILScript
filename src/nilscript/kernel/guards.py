"""The guard language for `condition`/`foreach`: a constrained, total, side-effect-free boolean
expression engine. NOT eval — a hand-written tokenizer + recursive-descent parser over a closed
grammar, so a hostile or malformed guard can only raise GuardError, never execute host code,
loop, or reach the filesystem (wosool-dsl/02-GRAMMAR-AND-PRIMITIVES.md §5).

Grammar (low → high precedence):
    or      := and ( '||' and )*
    and     := not ( '&&' not )*
    not     := '!' not | comparison
    comp    := primary ( ( '=='|'!='|'<'|'<='|'>'|'>='|'in' ) primary )?
    primary := '(' or ')' | macro | reference | number | string | 'true'|'false'|'null' | list
    macro   := ( 'has' | 'size' ) '(' or ')'
    list    := '[' ( primary ( ',' primary )* )? ']'
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from nilscript.kernel.references import ReferenceError, parse_reference, resolve


class GuardError(Exception):
    """The guard is malformed, exceeds the grammar, or did not evaluate to a boolean."""


# --- tokenizer ------------------------------------------------------------------------------

_TOKEN = re.compile(
    r"""
      (?P<ws>\s+)
    | (?P<ref>\$\.(?:step_[0-9]+|item|input)(?:\.[A-Za-z_]\w*|\[[0-9]+\])*)
    | (?P<number>-?\d+(?:\.\d+)?)
    | (?P<string>'[^']*'|"[^"]*")
    | (?P<op><=|>=|==|!=|&&|\|\||[<>!()\[\],])
    | (?P<name>[A-Za-z_]\w*)
    """,
    re.VERBOSE,
)


@dataclass(frozen=True)
class _Tok:
    kind: str
    text: str


def _tokenize(source: str) -> list[_Tok]:
    tokens: list[_Tok] = []
    pos = 0
    while pos < len(source):
        match = _TOKEN.match(source, pos)
        if match is None:
            raise GuardError(f"unexpected character at {pos}: {source[pos : pos + 8]!r}")
        pos = match.end()
        kind = match.lastgroup
        assert kind is not None
        if kind == "ws":
            continue
        tokens.append(_Tok(kind=kind, text=match.group()))
    return tokens


# --- parser + evaluator ---------------------------------------------------------------------

_KEYWORDS = {"true": True, "false": False, "null": None}
_COMPARATORS = {"==", "!=", "<", "<=", ">", ">=", "in"}


class _Parser:
    def __init__(self, tokens: list[_Tok], ctx: dict[str, Any], item: Any) -> None:
        self._tokens = tokens
        self._pos = 0
        self._ctx = ctx
        self._item = item

    def _peek(self) -> _Tok | None:
        return self._tokens[self._pos] if self._pos < len(self._tokens) else None

    def _advance(self) -> _Tok:
        tok = self._peek()
        if tok is None:
            raise GuardError("unexpected end of guard")
        self._pos += 1
        return tok

    def _expect(self, text: str) -> None:
        tok = self._advance()
        if tok.text != text:
            raise GuardError(f"expected {text!r}, got {tok.text!r}")

    def parse(self) -> Any:
        value = self._or()
        trailing = self._peek()
        if trailing is not None:
            raise GuardError(f"trailing tokens: {trailing.text!r}")
        return value

    def _or(self) -> Any:
        value = self._and()
        while (tok := self._peek()) is not None and tok.text == "||":
            self._advance()
            right = self._and()  # always parse the operand — never short-circuit token consumption
            value = bool(value) or bool(right)
        return value

    def _and(self) -> Any:
        value = self._not()
        while (tok := self._peek()) is not None and tok.text == "&&":
            self._advance()
            right = self._not()  # always parse the operand — never short-circuit token consumption
            value = bool(value) and bool(right)
        return value

    def _not(self) -> Any:
        tok = self._peek()
        if tok is not None and tok.text == "!":
            self._advance()
            return not bool(self._not())
        return self._comparison()

    def _comparison(self) -> Any:
        left = self._primary()
        tok = self._peek()
        if tok is None or tok.text not in _COMPARATORS:
            return left
        op = self._advance().text
        right = self._primary()
        return self._apply(op, left, right)

    @staticmethod
    def _apply(op: str, left: Any, right: Any) -> bool:
        try:
            if op == "==":
                return bool(left == right)
            if op == "!=":
                return bool(left != right)
            if op == "in":
                return left in right
            if op == "<":
                return bool(left < right)
            if op == "<=":
                return bool(left <= right)
            if op == ">":
                return bool(left > right)
            return bool(left >= right)
        except TypeError as exc:
            raise GuardError(f"cannot compare {left!r} {op} {right!r}") from exc

    def _primary(self) -> Any:
        tok = self._advance()
        if tok.text == "(":
            value = self._or()
            self._expect(")")
            return value
        if tok.text == "[":
            return self._list()
        if tok.kind == "ref":
            return self._resolve_ref(tok.text)
        if tok.kind == "number":
            return float(tok.text) if "." in tok.text else int(tok.text)
        if tok.kind == "string":
            return tok.text[1:-1]
        if tok.kind == "name":
            return self._name(tok.text)
        raise GuardError(f"unexpected token {tok.text!r}")

    def _list(self) -> list[Any]:
        items: list[Any] = []
        if (tok := self._peek()) is not None and tok.text == "]":
            self._advance()
            return items
        items.append(self._primary())
        while (tok := self._peek()) is not None and tok.text == ",":
            self._advance()
            items.append(self._primary())
        self._expect("]")
        return items

    def _name(self, name: str) -> Any:
        if name in _KEYWORDS:
            return _KEYWORDS[name]
        if name == "size":  # has() is pre-rewritten before parsing (see _rewrite_has)
            self._expect("(")
            inner = self._or()
            self._expect(")")
            if not isinstance(inner, list | str | dict):
                raise GuardError(f"size() needs a list/string/object, got {type(inner).__name__}")
            return len(inner)
        raise GuardError(f"unknown name {name!r}")

    def _resolve_ref(self, text: str) -> Any:
        if parse_reference(text) is None:
            raise GuardError(f"malformed reference {text!r}")
        try:
            return resolve(text, self._ctx, item=self._item)
        except ReferenceError:
            raise GuardError(f"unresolved reference {text!r}") from None


def evaluate_guard(expression: str, ctx: dict[str, Any], *, item: Any = None) -> bool:
    """Evaluate a guard to a bool. Raises GuardError on anything outside the grammar, an
    unresolved reference, an unknown function, or a non-boolean result."""
    # has() tolerates a non-resolving reference (→ false); every other reference must resolve.
    # Pre-rewriting has(...) to a literal keeps the parser uniformly strict (see _rewrite_has).
    parser = _Parser(_tokenize(_rewrite_has(expression, ctx, item)), ctx, item)
    try:
        value = parser.parse()
    except GuardError:
        raise
    except (IndexError, ValueError) as exc:
        raise GuardError(str(exc)) from exc
    if not isinstance(value, bool):
        raise GuardError(f"guard did not evaluate to a boolean: {value!r}")
    return value


def _rewrite_has(expression: str, ctx: dict[str, Any], item: Any) -> str:
    """Replace has($.ref) with true/false by resolving the reference leniently, so the parser
    never sees a reference that must tolerate non-resolution. Keeps the parser uniformly strict
    (a non-has reference that fails to resolve is a genuine GuardError)."""

    def replace(match: re.Match[str]) -> str:
        ref = match.group(1)
        if parse_reference(ref) is None:
            raise GuardError(f"malformed reference in has(): {ref!r}")
        try:
            resolve(ref, ctx, item=item)
            return "true"
        except ReferenceError:
            return "false"

    return re.sub(
        r"has\(\s*(\$\.(?:step_[0-9]+|item|input)(?:\.[A-Za-z_]\w*|\[[0-9]+\])*)\s*\)",
        replace,
        expression,
    )
