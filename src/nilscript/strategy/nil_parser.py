"""The `.strategy.nil` parser — `parse_strategy_nil(text) -> Strategy`, the exact inverse of
`nil_printer.print_strategy_nil` (same tokenizer family as cycles/capabilities).

Reserved future forms (`par/weighted/dynamic/delegate/override`) PARSE-REFUSE with
`NilUnsupportedFormError` carrying `code = "V9_UNSUPPORTED_FORM"` and a message naming the form and
the supported algebra — a clear governance answer, not a generic syntax error (the no-rewrite
guarantee: a future form is a new interpreter case, never a grammar rework).
"""

from __future__ import annotations

from typing import Any

from nilscript.cycle.nil_parser import NilSyntaxError, _Reader, _tokenize
from nilscript.strategy.models import RESERVED_FORMS, Strategy

_SUPPORTED = "auto, approve, seq, quorum, when/else"


class NilUnsupportedFormError(NilSyntaxError):
    """A grammar-reserved strategy form (not yet part of the MVP-5 algebra). Distinguishable from a
    plain syntax error by `code` so callers can render it as the governance answer it is."""

    code = "V9_UNSUPPORTED_FORM"

    def __init__(self, form: str, line: int, col: int) -> None:
        super().__init__(
            f"[V9_UNSUPPORTED_FORM] strategy form {form!r} is reserved but not supported in the "
            f"MVP approval algebra; supported forms: {_SUPPORTED}",
            line,
            col,
        )
        self.form = form


class _StrategyReader(_Reader):
    def strategy(self) -> dict[str, Any]:
        self._expect_word("strategy")
        strategy_id = self._word()
        version_tok = self._peek()
        version = self._word()
        if not version.startswith("v") or not version[1:].isdigit():
            self._fail(f"expected a version like v1 but found {version!r}", version_tok)
        self._expect_punct("{")
        raw: dict[str, Any] = {
            "nil": "strategy/0.1",
            "strategy_id": strategy_id,
            "version": int(version[1:]),
        }
        while self._is_word("workspace"):
            self._next()
            raw["workspace"] = self._string()
        raw["root"] = self._root()
        self._expect_punct("}")
        if self._peek().kind != "eof":
            self._fail(f"unexpected trailing token {self._peek().value!r}")
        return raw

    def _root(self) -> dict[str, Any]:
        """Either the two-clause conditional (`when "…" -> … / else -> …`) or one node expression."""
        if self._is_word("when"):
            self._next()
            when = self._string()
            self._expect_punct("->")
            then = self._node()
            self._expect_word("else")
            self._expect_punct("->")
            else_ = self._node()
            return {"form": "conditional", "when": when, "then": then, "else": else_}
        return self._node()

    def _node(self) -> dict[str, Any]:
        tok = self._peek()
        form = self._word()
        if form in RESERVED_FORMS:
            raise NilUnsupportedFormError(form, tok.line, tok.col)
        if form == "auto":
            return self._auto()
        if form == "approve":
            return self._approve()
        if form == "seq":
            return self._seq()
        if form == "quorum":
            return self._quorum()
        self._fail(f"unknown strategy form {form!r} (supported: {_SUPPORTED})", tok)

    def _auto(self) -> dict[str, Any]:
        self._expect_punct("(")
        self._expect_word("policy")
        self._expect_punct(":")
        policy = self._word()
        self._expect_punct(")")
        return {"form": "auto", "policy": policy}

    def _approve(self) -> dict[str, Any]:
        self._expect_punct("(")
        unit: dict[str, Any] = {}
        while not self._is_punct(")"):
            key_tok = self._peek()
            key = self._word()
            self._expect_punct(":")
            if key in ("role", "person"):
                unit["by"] = key
                unit["name"] = self._word()
            elif key == "distinct_from":
                unit["distinct_from"] = self._id_list()
            elif key == "timeout":
                unit["timeout"] = self._timeout()
            else:
                self._fail(f"unknown approve field {key!r}", key_tok)
            if self._is_punct(","):
                self._next()
        self._expect_punct(")")
        return {"form": "approve", "unit": unit}

    def _timeout(self) -> dict[str, Any]:
        timeout: dict[str, Any] = {"after": self._word()}
        if self._is_punct("->"):
            self._next()
            route_tok = self._peek()
            route = self._word()
            if route == "escalate":
                self._expect_punct("(")
                self._expect_word("role")
                self._expect_punct(":")
                timeout["then"] = {"kind": "escalate", "to": self._word()}
                self._expect_punct(")")
            elif route == "reject":
                timeout["then"] = {"kind": "reject"}
            else:
                self._fail(f"unknown timeout route {route!r} (escalate/reject)", route_tok)
        return timeout

    def _seq(self) -> dict[str, Any]:
        self._expect_punct("(")
        items = [self._node()]
        while self._is_punct(","):
            self._next()
            items.append(self._node())
        self._expect_punct(")")
        return {"form": "seq", "items": items}

    def _quorum(self) -> dict[str, Any]:
        self._expect_punct("(")
        quorum: dict[str, Any] = {"form": "quorum", "k": self._number()}
        while self._is_punct(","):
            self._next()
            key_tok = self._peek()
            key = self._word()
            if key == "distinct":
                quorum["distinct"] = True
            elif key == "of":
                self._expect_punct(":")
                self._expect_punct("[")
                of = [self._node()]
                while self._is_punct(","):
                    self._next()
                    of.append(self._node())
                self._expect_punct("]")
                quorum["of"] = of
            else:
                self._fail(f"unknown quorum field {key!r}", key_tok)
        self._expect_punct(")")
        return quorum


def parse_strategy_nil(text: str) -> Strategy:
    """Parse `.strategy.nil` source into a validated `Strategy`. Malformed input refuses with
    `NilSyntaxError(message, line, col)`; a reserved form refuses with `NilUnsupportedFormError`
    (`code = V9_UNSUPPORTED_FORM`). Governance well-formedness (SoD, quorum satisfiability, timeout
    routes, auto-vs-risk) lives in `validate.validate_strategy` — refusal lists, not exceptions."""
    tokens = _tokenize(text)
    reader = _StrategyReader(tokens)
    raw = reader.strategy()
    try:
        return Strategy.model_validate(raw)
    except NilSyntaxError:
        raise
    except ValueError as exc:
        first = tokens[0]
        raise NilSyntaxError(f"invalid strategy: {exc}", first.line, first.col) from exc


__all__ = ["parse_strategy_nil", "NilUnsupportedFormError", "NilSyntaxError"]
