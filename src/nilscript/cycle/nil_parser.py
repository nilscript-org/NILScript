"""The `.nil` parser — `parse_nil(text) -> Cycle`, the exact inverse of `nil_printer.print_nil`.

A hand-written tokenizer + recursive-descent reader (no dependencies — `lark` is not installed and
the kernel stays dep-free). It produces a raw dict and hands it to `Cycle.model_validate`, so the
parser never re-implements validation: it inherits the FROZEN v0.2 schema (closed objects, id/verb
patterns, discriminated step union, tier enums). The parser's only job is shape; the model is the law.

Malformed input raises `NilSyntaxError(message, line, col)` with the source position.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, NoReturn

from nilscript.cycle.models import Cycle


class NilSyntaxError(ValueError):
    """A `.nil` parse failure, carrying the 1-based source position of the offending token."""

    def __init__(self, message: str, line: int, col: int) -> None:
        super().__init__(f"{message} (line {line}, col {col})")
        self.message = message
        self.line = line
        self.col = col


# ── tokenizer --------------------------------------------------------------------------------

# Punctuation that forms its own token. `->` must be matched before `-` would be (we never emit a
# bare `-`, so order only matters for the arrow).
_PUNCT = ("->", "{", "}", "(", ")", "[", "]", ":", ";", ",", "=")
# A bare word: identifier, dotted verb/path, tier, number. We keep it loose and let the model
# validate the shape — the tokenizer only splits the stream.
_WORD_RE = re.compile(r"[A-Za-z0-9_.\-+]+")
_WS_RE = re.compile(r"[ \t\r\n]+")


@dataclass(frozen=True)
class _Token:
    kind: str  # "punct" | "string" | "word"
    value: str
    line: int
    col: int


def _tokenize(text: str) -> list[_Token]:
    tokens: list[_Token] = []
    i = 0
    line = 1
    col = 1
    n = len(text)
    while i < n:
        ch = text[i]
        ws = _WS_RE.match(text, i)
        if ws:
            chunk = ws.group(0)
            newlines = chunk.count("\n")
            if newlines:
                line += newlines
                col = len(chunk) - chunk.rfind("\n")
            else:
                col += len(chunk)
            i = ws.end()
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "/":  # line comment
            end = text.find("\n", i)
            if end == -1:
                break
            col += end - i
            i = end
            continue
        if ch == '"':
            value, length = _read_string(text, i, line, col)
            tokens.append(_Token("string", value, line, col))
            i += length
            col += length
            continue
        matched_punct = next((p for p in _PUNCT if text.startswith(p, i)), None)
        if matched_punct is not None:
            tokens.append(_Token("punct", matched_punct, line, col))
            i += len(matched_punct)
            col += len(matched_punct)
            continue
        word = _WORD_RE.match(text, i)
        if word:
            tokens.append(_Token("word", word.group(0), line, col))
            length = word.end() - i
            i = word.end()
            col += length
            continue
        raise NilSyntaxError(f"unexpected character {ch!r}", line, col)
    tokens.append(_Token("eof", "", line, col))
    return tokens


def _read_string(text: str, start: int, line: int, col: int) -> tuple[str, int]:
    """Read a JSON-style double-quoted string starting at `start`. Returns (value, char_length)."""
    i = start + 1
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "\n":
            raise NilSyntaxError("unterminated string", line, col)
        if ch == '"':
            raw = text[start : i + 1]
            try:
                return json.loads(raw), len(raw)
            except json.JSONDecodeError as exc:  # pragma: no cover - escape edge
                raise NilSyntaxError(f"bad string literal: {exc.msg}", line, col) from exc
        i += 1
    raise NilSyntaxError("unterminated string", line, col)


# ── recursive-descent reader -----------------------------------------------------------------


class _Reader:
    def __init__(self, tokens: list[_Token]) -> None:
        self.tokens = tokens
        self.pos = 0

    # cursor helpers ---------------------------------------------------------------------------
    def _peek(self) -> _Token:
        return self.tokens[self.pos]

    def _next(self) -> _Token:
        tok = self.tokens[self.pos]
        if tok.kind != "eof":
            self.pos += 1
        return tok

    def _fail(self, message: str, tok: _Token | None = None) -> NoReturn:
        tok = tok or self._peek()
        raise NilSyntaxError(message, tok.line, tok.col)

    def _expect_punct(self, value: str) -> _Token:
        tok = self._peek()
        if tok.kind != "punct" or tok.value != value:
            self._fail(f"expected {value!r} but found {tok.value!r}", tok)
        return self._next()

    def _expect_word(self, value: str) -> _Token:
        tok = self._peek()
        if tok.kind != "word" or tok.value != value:
            self._fail(f"expected keyword {value!r} but found {tok.value!r}", tok)
        return self._next()

    def _word(self) -> str:
        tok = self._peek()
        if tok.kind != "word":
            self._fail(f"expected a name but found {tok.value!r}", tok)
        return self._next().value

    def _string(self) -> str:
        tok = self._peek()
        if tok.kind != "string":
            self._fail(f"expected a quoted string but found {tok.value!r}", tok)
        return self._next().value

    def _is_punct(self, value: str) -> bool:
        tok = self._peek()
        return tok.kind == "punct" and tok.value == value

    def _is_word(self, value: str) -> bool:
        tok = self._peek()
        return tok.kind == "word" and tok.value == value

    # top-level --------------------------------------------------------------------------------
    def cycle(self) -> dict:
        self._expect_word("cycle")
        cycle_id = self._word()
        trigger = self._trigger_header()
        self._expect_punct("{")
        raw: dict[str, Any] = {"nil": "cycle/0.2", "cycle_id": cycle_id, "trigger": trigger}
        self._cycle_body(raw)
        self._expect_punct("}")
        if self._peek().kind != "eof":
            self._fail(f"unexpected trailing token {self._peek().value!r}")
        return raw

    def _trigger_header(self) -> dict:
        if self._is_word("triggers_on"):
            self._next()
            verb = self._word()
            trigger: dict[str, Any] = {"type": "event", "on_verb": verb}
            if self._is_word("where"):
                self._next()
                self._expect_punct("(")
                while not self._is_punct(")"):
                    key = self._word()
                    if key == "on_event":
                        trigger["on_event"] = self._word()
                    elif key == "source_adapter":
                        trigger["source_adapter"] = self._string()
                    elif key == "match":
                        trigger["match"] = self._arg_map()
                    else:
                        self._fail(f"unknown event-trigger field {key!r}")
                    if self._is_punct(";"):
                        self._next()
                self._expect_punct(")")
            return trigger
        if self._is_word("triggers"):
            self._next()
            kind = self._word()
            if kind == "manual":
                return {"type": "manual"}
            if kind == "schedule":
                self._expect_punct("{")
                sched: dict[str, Any] = {"type": "schedule"}
                while not self._is_punct("}"):
                    key = self._word()
                    self._expect_punct(":")
                    if key == "cron":
                        sched["cron"] = self._string()
                    elif key == "interval_seconds":
                        sched["interval_seconds"] = self._number()
                    elif key == "timezone":
                        sched["timezone"] = self._string()
                    else:
                        self._fail(f"unknown schedule field {key!r}")
                    if self._is_punct(";"):
                        self._next()
                self._expect_punct("}")
                return sched
            self._fail(f"unknown trigger kind {kind!r}")
        self._fail("expected a trigger (triggers_on / triggers manual / triggers schedule)")

    def _cycle_body(self, raw: dict) -> None:
        variables: list[dict] = []
        while not self._is_punct("}"):
            tok = self._peek()
            if tok.kind != "word":
                self._fail(f"expected a section keyword but found {tok.value!r}", tok)
            kw = tok.value
            if kw == "workspace":
                self._next()
                raw["workspace"] = self._string()
            elif kw == "intent":
                self._next()
                raw["intent"] = self._bilingual()
            elif kw == "documentation":
                self._next()
                raw["documentation"] = self._bilingual()
            elif kw == "meta":
                raw["metadata"] = self._meta()
            elif kw == "let":
                variables.append(self._variable())
            elif kw == "context":
                raw["context"] = self._context()
            elif kw == "roles":
                raw["roles"] = self._roles()
            elif kw == "policies":
                raw["policies"] = self._policies()
            elif kw == "resources":
                self._next()
                raw["resources"] = self._string_list()
            elif kw == "flow":
                raw["flow"] = self._flow()
            elif kw == "outcomes":
                raw["outcomes"] = self._outcomes()
            else:
                self._fail(f"unknown section {kw!r}", tok)
        if variables:
            raw["variables"] = variables

    # sections ---------------------------------------------------------------------------------
    def _meta(self) -> dict:
        self._expect_word("meta")
        self._expect_punct("{")
        meta: dict[str, Any] = {}
        while not self._is_punct("}"):
            key = self._word()
            self._expect_punct(":")
            if key == "version":
                meta["version"] = self._string()
            elif key == "owner":
                meta["owner"] = self._string()
            elif key == "description":
                meta["description"] = self._bilingual()
            elif key == "tags":
                meta["tags"] = self._string_list()
            else:
                self._fail(f"unknown meta field {key!r}")
            if self._is_punct(";"):
                self._next()
        self._expect_punct("}")
        return meta

    def _variable(self) -> dict:
        self._expect_word("let")
        name = self._word()
        self._expect_punct("=")
        # the expression is a dotted path token (e.g. context.payload)
        expr = self._word()
        self._expect_punct(";")
        return {"name": name, "expression": expr}

    def _context(self) -> list[dict]:
        self._expect_word("context")
        self._expect_punct("{")
        refs: list[dict] = []
        while not self._is_punct("}"):
            name = self._word()
            self._expect_punct(":")
            entity_type = self._word()
            ref: dict[str, Any] = {"name": name, "entity_type": entity_type}
            if self._is_punct("("):
                self._next()
                self._expect_word("role")
                self._expect_punct(":")
                ref["role"] = self._word()
                self._expect_punct(")")
            self._expect_punct(";")
            refs.append(ref)
        self._expect_punct("}")
        return refs

    def _roles(self) -> list[dict]:
        self._expect_word("roles")
        self._expect_punct("{")
        roles: list[dict] = []
        while not self._is_punct("}"):
            roles.append({"role": self._word()})
            if self._is_punct(","):
                self._next()
        self._expect_punct("}")
        return roles

    def _policies(self) -> list[dict]:
        self._expect_word("policies")
        self._expect_punct("{")
        policies: list[dict] = []
        while not self._is_punct("}"):
            self._expect_word("policy")
            policy: dict[str, Any] = {"policy_id": self._word()}
            while not (self._is_word("policy") or self._is_punct("}")):
                field = self._word()
                if field == "applies_to":
                    policy["applies_to"] = self._id_list()
                elif field == "when":
                    policy["condition"] = self._string()
                elif field == "raises_tier":
                    policy["raises_tier"] = self._word()
                else:
                    self._fail(f"unknown policy field {field!r}")
            policies.append(policy)
        self._expect_punct("}")
        return policies

    def _flow(self) -> dict:
        self._expect_word("flow")
        self._expect_word("entry")
        entry = self._word()
        self._expect_punct("{")
        steps: list[dict] = []
        while not self._is_punct("}"):
            steps.append(self._step())
        self._expect_punct("}")
        return {"entry": entry, "steps": steps}

    def _step(self) -> dict:
        self._expect_word("step")
        step_id = self._word()
        self._expect_punct("{")
        # the first keyword inside the step decides its type
        head = self._peek()
        if head.kind != "word":
            self._fail(f"expected a step body keyword but found {head.value!r}", head)
        if head.value in ("use", "query"):
            step = self._action_like(step_id, head.value)
        elif head.value == "decision":
            step = self._decision(step_id)
        elif head.value == "await":
            step = self._approval(step_id)
        elif head.value == "notify":
            step = self._notify(step_id)
        else:
            self._fail(f"unknown step type {head.value!r}", head)
        self._expect_punct("}")
        return step

    def _action_like(self, step_id: str, keyword: str) -> dict:
        self._expect_word(keyword)
        use = self._word()
        with_ = self._arg_map()
        step_type = "action" if keyword == "use" else "query"
        step: dict[str, Any] = {"id": step_id, "type": step_type, "use": use, "with": with_}
        self._read_output_and_next(step)
        return step

    def _decision(self, step_id: str) -> dict:
        self._expect_word("decision")
        self._expect_word("when")
        when = self._string()
        self._expect_word("on_true")
        on_true = self._word()
        step: dict[str, Any] = {"id": step_id, "type": "decision", "when": when, "on_true": on_true}
        if self._is_word("on_false"):
            self._next()
            step["on_false"] = self._word()
        if self._is_word("next"):
            self._next()
            step["next"] = self._word()
        return step

    def _approval(self, step_id: str) -> dict:
        self._expect_word("await")
        self._expect_word("approval")
        self._expect_punct("{")
        step: dict[str, Any] = {"id": step_id, "type": "approval"}
        while not self._is_punct("}"):
            key = self._word()
            self._expect_punct(":")
            if key == "title":
                step["title"] = self._bilingual()
            elif key == "description":
                step["description"] = self._bilingual()
            elif key == "approver":
                step["approver"] = self._word()
            elif key == "timeout_seconds":
                step["timeout_seconds"] = self._number()
            else:
                self._fail(f"unknown approval field {key!r}")
            if self._is_punct(";"):
                self._next()
        self._expect_punct("}")
        # branches: on approve/reject/timeout -> Step
        while self._is_word("on"):
            self._next()
            branch = self._word()
            self._expect_punct("->")
            target = self._word()
            if branch == "approve":
                step["on_approve"] = target
            elif branch == "reject":
                step["on_reject"] = target
            elif branch == "timeout":
                step["on_timeout"] = target
            else:
                self._fail(f"unknown approval branch {branch!r}")
        return step

    def _notify(self, step_id: str) -> dict:
        self._expect_word("notify")
        message = self._bilingual()
        step: dict[str, Any] = {"id": step_id, "type": "notify", "message": message}
        if self._is_word("next"):
            self._next()
            step["next"] = self._word()
        return step

    def _read_output_and_next(self, step: dict) -> None:
        if self._is_word("output"):
            self._next()
            step["output"] = self._word()
        if self._is_word("next"):
            self._next()
            step["next"] = self._word()

    def _outcomes(self) -> list[dict]:
        self._expect_word("outcomes")
        self._expect_punct("{")
        outcomes: list[dict] = []
        while not self._is_punct("}"):
            name = self._word()
            out: dict[str, Any] = {"name": name}
            if self._is_word("when"):
                self._next()
                out["when"] = self._string()
            self._expect_punct(";")
            outcomes.append(out)
        self._expect_punct("}")
        return outcomes

    # value readers ----------------------------------------------------------------------------
    def _bilingual(self) -> str | dict:
        if self._peek().kind == "string":
            return self._string()  # single string: ar==en handled by model coercion below
        self._expect_punct("{")
        bi: dict[str, str] = {}
        while not self._is_punct("}"):
            key = self._word()
            self._expect_punct(":")
            if key == "ar":
                bi["ar"] = self._string()
            elif key == "en":
                bi["en"] = self._string()
            else:
                self._fail(f"unknown bilingual field {key!r}")
            if self._is_punct(";"):
                self._next()
        self._expect_punct("}")
        return bi

    def _string_list(self) -> list[str]:
        self._expect_punct("[")
        items: list[str] = []
        while not self._is_punct("]"):
            items.append(self._string())
            if self._is_punct(","):
                self._next()
        self._expect_punct("]")
        return items

    def _id_list(self) -> list[str]:
        self._expect_punct("[")
        items: list[str] = []
        while not self._is_punct("]"):
            items.append(self._word())
            if self._is_punct(","):
                self._next()
        self._expect_punct("]")
        return items

    def _arg_map(self) -> dict:
        self._expect_punct("{")
        args: dict[str, Any] = {}
        while not self._is_punct("}"):
            key = self._word()
            self._expect_punct(":")
            args[key] = self._arg_value()
            if self._is_punct(","):
                self._next()
        self._expect_punct("}")
        return args

    def _arg_value(self) -> Any:
        """Read one arg value. Strings/numbers/bools/null/nested JSON containers — printed by the
        printer as JSON, so we re-read JSON-shaped tokens here for an exact round trip."""
        tok = self._peek()
        if tok.kind == "string":
            return self._string()
        if self._is_punct("[") or self._is_punct("{"):
            return self._json_container()
        # a bare word: number, bool, null, or a bare identifier value
        word = self._word()
        if word == "true":
            return True
        if word == "false":
            return False
        if word == "null":
            return None
        num = _try_number(word)
        return num if num is not None else word

    def _json_container(self) -> Any:
        """Read a `[...]` / `{...}` literal as JSON values (used inside arg maps for nested data)."""
        if self._is_punct("["):
            self._next()
            arr: list[Any] = []
            while not self._is_punct("]"):
                arr.append(self._arg_value())
                if self._is_punct(","):
                    self._next()
            self._expect_punct("]")
            return arr
        self._expect_punct("{")
        obj: dict[str, Any] = {}
        while not self._is_punct("}"):
            key = self._string() if self._peek().kind == "string" else self._word()
            self._expect_punct(":")
            obj[key] = self._arg_value()
            if self._is_punct(","):
                self._next()
        self._expect_punct("}")
        return obj

    def _number(self) -> int:
        tok = self._peek()
        word = self._word()
        try:
            return int(word)
        except ValueError:
            self._fail(f"expected an integer but found {word!r}", tok)


def _try_number(word: str) -> int | float | None:
    try:
        return int(word)
    except ValueError:
        pass
    try:
        return float(word)
    except ValueError:
        return None


# ── public entrypoint --------------------------------------------------------------------------


def parse_nil(text: str) -> Cycle:
    """Parse `.nil` source into a validated `Cycle`. Raises `NilSyntaxError` on malformed input.

    A single quoted bilingual string sets both `ar` and `en` (the `en`-is-the-source rule from the
    surface spec). The result is validated by `Cycle.model_validate`, inheriting the frozen schema.
    """
    tokens = _tokenize(text)
    reader = _Reader(tokens)
    raw = reader.cycle()
    _coerce_single_string_bilinguals(raw)
    try:
        return Cycle.model_validate(raw)
    except NilSyntaxError:
        raise
    except ValueError as exc:
        # A schema violation that the grammar allowed (e.g. a bad verb pattern). Surface it at the
        # cycle open so callers still get a NilSyntaxError, not a bare pydantic error.
        first = tokens[0]
        raise NilSyntaxError(f"invalid cycle: {exc}", first.line, first.col) from exc


def _as_bilingual(value: Any) -> Any:
    """A single quoted string at a bilingual position means ar==en (the surface `en`-is-source rule).
    A dict is already an explicit {ar, en}. Anything else is left for the model to reject."""
    return {"ar": value, "en": value} if isinstance(value, str) else value


def _coerce_single_string_bilinguals(raw: dict) -> None:
    """Coerce the EXACT structural bilingual positions — never a `with`/`match` arg that happens to
    share a key name. The `_bilingual()` reader returns str (single) or dict (explicit) at each."""
    if "intent" in raw:
        raw["intent"] = _as_bilingual(raw["intent"])
    if "documentation" in raw:
        raw["documentation"] = _as_bilingual(raw["documentation"])
    meta = raw.get("metadata")
    if isinstance(meta, dict) and "description" in meta:
        meta["description"] = _as_bilingual(meta["description"])
    flow = raw.get("flow")
    if isinstance(flow, dict):
        for step in flow.get("steps", []):
            if not isinstance(step, dict):
                continue
            for key in ("title", "description", "message"):
                if key in step:
                    step[key] = _as_bilingual(step[key])
